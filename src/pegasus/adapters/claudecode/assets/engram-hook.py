#!/usr/bin/env python3
"""Pegasus-owned Claude Code hook that registers sessions and prompts in engram.

Rendered by the Claude Code adapter ONLY when the engram MCP server is selected
(`pegasus.adapters.claudecode.render.engram_hook_artifacts`). Standard library
only. One subcommand per hook event:

    session-start   register the session (and start `engram serve` if it is down)
    prompt          register the session, then record the user's prompt
    subagent-stop   hand a sub-agent's final message to engram's passive capture

Contract, in order of importance:

* it ALWAYS exits 0, whatever goes wrong, so a hook never shows an error;
* it NEVER writes to stdout, so it injects no context into the session
  (diagnostics, if any, go to stderr);
* every HTTP call has a short timeout and goes straight to the local server,
  never through a proxy named in the environment;
* content is redacted BEFORE it is cut, and a message too large for the
  detection pass is cut (a prompt) or not sent at all (a sub-agent message),
  never sent unredacted;
* it sends no memory-protocol text and no reminders: the 7.1.0 rule that
  sub-agents write to engram only when their brief asks for it stays intact.

The two values below are filled in at render time from single sources: the
engram binary Pegasus manages, and the credential catalog the OpenCode secret
transport also reads (`content/security/credential-transport-catalog.json`).
The catalog is data; the detection passes in `redact()` are a line-for-line
port of `secret-transport.ts`'s `detectAndReplace`, kept equal by a parity test.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

CONFIG = json.loads(__CONFIG_JSON__)

HTTP_TIMEOUT = 2.0
GIT_TIMEOUT = 1.0
HEALTH_WAIT = 2.0
PROMPT_MIN = 10
PROMPT_MAX = 2000
PASSIVE_MIN = 50
# The detection pass skips anything above the catalog's byte cap; this script
# never sends such text, so a skipped pass can never leak a value.
DETECT_CAP = (CONFIG.get("catalog") or {}).get("max_detect_bytes") or 262144


# --- Credential redaction (port of secret-transport.ts, catalog-driven) -----

CATALOG = CONFIG.get("catalog") or {}


def _js_end(pattern):
    """A JS `$` (no multiline flag) only matches at the very end; Python's also
    matches before a trailing newline. `\\Z` is the exact equivalent."""
    if pattern.endswith("$") and not pattern.endswith("\\$"):
        return pattern[:-1] + "\\Z"
    return pattern


def _normalize_name(raw):
    name = re.sub(r"[^A-Z0-9]+", "_", raw.upper())
    return name.strip("_") or "SECRET"


class _Registry:
    """value -> NAME, for one process only (a hook is one short-lived process)."""

    def __init__(self):
        self.value_to_name = {}
        self.used = set()

    def register(self, value, base):
        existing = self.value_to_name.get(value)
        if existing:
            return existing
        name = _normalize_name(base)
        if name in self.used:
            n = 2
            while "%s_%d" % (name, n) in self.used:
                n += 1
            name = "%s_%d" % (name, n)
        self.used.add(name)
        self.value_to_name[value] = name
        return name


def _token(name):
    return "$PEGASUS_SECRET_" + name


def _is_placeholder(value):
    if not CATALOG:
        return False
    for p in CATALOG.get("placeholder_patterns", []):
        if re.search(_js_end(p), value):
            return True
    key_context = CATALOG.get("key_context", {})
    lowered = value.lower()
    for filler in key_context.get("filler_skip_values", []) or []:
        if filler.lower() == lowered:
            return True
    for p in key_context.get("filler_skip_patterns", []) or []:
        if re.search(_js_end(p), value):
            return True
    return False


def _components(raw):
    return [part.lower() for part in re.split(r"[_-]", raw) if part]


def _matches_catalog_key(raw, catalog_keys):
    raw_parts = _components(raw)
    if not raw_parts:
        return False
    raw_whole = "".join(raw_parts)
    for key in catalog_keys:
        key_parts = _components(key)
        key_whole = "".join(key_parts)
        if raw_whole == key_whole:
            return True
        if len(raw_parts) >= len(key_parts):
            tail = "".join(raw_parts[len(raw_parts) - len(key_parts):])
            if tail == key_whole:
                return True
    return False


def _skips_as_unquoted_code(value):
    if not CATALOG:
        return False
    for rule in CATALOG.get("key_context", {}).get("skip_unquoted_if", []):
        if re.search(_js_end(rule["pattern"]), value):
            return True
    return False


def _on_closed_part(text, apply):
    """Run an explicit `<private>...</private>` pass on the text up to its last
    close tag only. Nothing after it can match (a match ends at a close tag),
    and leaving it out stops a pile of unclosed open tags from making the lazy
    patterns rescan to the end of the text once per tag (quadratic)."""
    last = None
    for last in _PRIVATE_CLOSE.finditer(text):
        pass
    if last is None:
        return text
    return apply(text[: last.end()]) + text[last.end():]


def _detect_and_replace(text):
    if not CATALOG or not text:
        return text
    cap = CATALOG.get("max_detect_bytes")
    if cap and len(text.encode("utf-8", "replace")) > cap:
        return text
    registry = _Registry()
    min_len = CATALOG["min_value_length"]
    key_context = CATALOG["key_context"]
    key_min = key_context.get("min_value_length") or min_len
    out = text

    def substitute(pattern, name_for, value_of):
        def repl(m):
            value = value_of(m)
            if not value or len(value) < min_len or _is_placeholder(value):
                return m.group(0)
            name = registry.register(value, name_for(m))
            return m.group(0).replace(value, _token(name), 1)

        return re.compile(pattern, re.I).sub(repl, out)

    try:
        # 1. <private>NAME=value</private>: the whole tag is replaced.
        def named(m):
            if not m.group(2):
                return m.group(0)
            return _token(registry.register(m.group(2), m.group(1)))

        out = _on_closed_part(out, lambda part: re.sub(CATALOG["explicit"]["named"]["pattern"], named, part))

        # 2. <private>value</private>
        def bare(m):
            if not m.group(1):
                return m.group(0)
            return _token(registry.register(m.group(1), CATALOG["explicit"]["bare"]["name"]))

        out = _on_closed_part(out, lambda part: re.sub(CATALOG["explicit"]["bare"]["pattern"], bare, part))

        # 3. Known formats.
        for fmt in CATALOG["known_formats"]:
            def known(m, fmt=fmt):
                whole = m.group(0)
                if len(whole) < min_len or _is_placeholder(whole):
                    return whole
                return _token(registry.register(whole, fmt["name"]))

            out = re.sub(fmt["pattern"], known, out)

        # 4. Headers.
        for rule in CATALOG["headers"].values():
            if "header_names" in rule:
                names = "|".join(re.escape(n) for n in rule["header_names"])
                scheme = "(?:%s)\\s+" % "|".join(rule["schemes"]) if rule.get("schemes") else ""
                pattern = '(?:%s)\\s*:\\s*%s([^\\s,"\']{%d,})' % (names, scheme, min_len)
                out = substitute(pattern, lambda m, rule=rule: rule["name"], lambda m: m.group(1))
            elif "header_name_suffixes" in rule:
                suffixes = "|".join(re.escape(s) for s in rule["header_name_suffixes"])
                digit = "(?:-[0-9]+)?" if rule.get("allow_trailing_digit_segment") else ""
                pattern = (
                    '(?<![A-Za-z0-9-])([A-Za-z][A-Za-z0-9-]*(?:%s)%s)\\s*:\\s*([^\\s,"\']{%d,})'
                    % (suffixes, digit, min_len)
                )
                out = substitute(pattern, lambda m: m.group(1), lambda m: m.group(2))

        # 5. URL credentials.
        def url_password(m):
            password = m.group(1)
            if not password or len(password) < min_len or _is_placeholder(password):
                return m.group(0)
            name = registry.register(password, CATALOG["url_credentials"]["name"])
            return m.group(0).replace(password, _token(name), 1)

        out = re.sub(CATALOG["url_credentials"]["pattern"], url_password, out)

        keys = key_context["keys"]

        # 6. JSON "key": "value".
        def json_pair(m):
            key, value = m.group(1), m.group(2)
            if not _matches_catalog_key(key, keys) or _is_placeholder(value):
                return m.group(0)
            name = registry.register(value, key)
            return m.group(0).replace('"%s"' % value, '"%s"' % _token(name), 1)

        out = re.sub(
            '"([A-Za-z_$][A-Za-z0-9_$-]*)"\\s*:\\s*"([^"]{%d,})"' % key_min, json_pair, out
        )

        # 7. key = "value" / key: 'value'.
        def quoted_pair(m):
            key = m.group(1)
            value = m.group(2) if m.group(2) is not None else m.group(3)
            if not _matches_catalog_key(key, keys) or _is_placeholder(value):
                return m.group(0)
            name = registry.register(value, key)
            return m.group(0).replace(value, _token(name), 1)

        out = re.sub(
            "(?<![A-Za-z0-9_$-])([A-Za-z_$][A-Za-z0-9_$-]*)\\s*[:=]\\s*"
            "(?:\"([^\"]{%d,})\"|'([^']{%d,})')" % (key_min, key_min),
            quoted_pair,
            out,
        )

        # 8. key=value / key: value, unquoted. A manual scan, as in the plugin:
        # on a rejected key it advances past the key only, never past its value.
        pattern8 = re.compile(
            "(?<![A-Za-z0-9_$-])([A-Za-z_$][A-Za-z0-9_$-]*)\\s*[:=]\\s*(%s)"
            % key_context["unquoted_value_pattern"]
        )
        result = []
        cursor = 0
        pos = 0
        while True:
            m = pattern8.search(out, pos)
            if not m:
                break
            key, value = m.group(1), m.group(2)
            if (
                _matches_catalog_key(key, keys)
                and not _is_placeholder(value)
                and not _skips_as_unquoted_code(value)
            ):
                result.append(out[cursor:m.start()])
                name = registry.register(value, key)
                result.append(m.group(0).replace(value, _token(name), 1))
                cursor = m.end()
                pos = cursor
            else:
                pos = m.start() + len(key)
        result.append(out[cursor:])
        out = "".join(result)
    except Exception:
        pass
    return out


_PRIVATE_OPEN = re.compile(r"<private>", re.I)
_PRIVATE_CLOSE = re.compile(r"</private>", re.I)


def _strip_private_fallback(text):
    """`<private>[\\s\\S]*?</private>` -> `[REDACTED]`, in linear time.

    Same semantics as that lazy regex (first open tag to the first close tag
    after it; an unclosed tag stays), without its quadratic rescans when many
    open tags have no close tag: once no close tag follows an open one, none
    follows any later open one either.
    """
    out = []
    pos = 0
    while True:
        start = _PRIVATE_OPEN.search(text, pos)
        if not start:
            break
        end = _PRIVATE_CLOSE.search(text, start.end())
        if not end:
            break
        out.append(text[pos:start.start()])
        out.append("[REDACTED]")
        pos = end.end()
    out.append(text[pos:])
    return "".join(out)


def cut_to_detect_cap(text):
    """The text cut to the detection cap, in bytes, on a character boundary."""
    data = text.encode("utf-8", "replace")
    if len(data) <= DETECT_CAP:
        return text
    return data[:DETECT_CAP].decode("utf-8", "ignore")


def exceeds_detect_cap(text):
    return len(text.encode("utf-8", "replace")) > DETECT_CAP


def redact(text):
    """What `engram.ts`'s `redactCredentials` does with the secret transport loaded."""
    if not text:
        return text
    try:
        return _strip_private_fallback(_detect_and_replace(text))
    except Exception:
        return text


def strip_private_tags(text):
    if not text:
        return ""
    return _strip_private_fallback(text).strip()


def truncate(text, limit):
    if not text:
        return ""
    return text[:limit] + "..." if len(text) > limit else text


# --- Project detection (same order as engram.ts extractProjectName) ---------


def _git(directory, *args):
    try:
        result = subprocess.run(
            ["git", "-C", directory, *args],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=GIT_TIMEOUT,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.decode("utf-8", "replace").strip()


def extract_project_name(directory):
    url = _git(directory, "remote", "get-url", "origin")
    if url:
        name = re.split(r"[/:]", re.sub(r"\.git$", "", url))[-1]
        if name:
            return name
    root = _git(directory, "rev-parse", "--show-toplevel")
    if root:
        return root.split("/")[-1] or "unknown"
    # `/` or a trailing `/` has no basename: the script says "unknown" rather
    # than posting an empty project (engram.ts would post an empty string).
    return directory.rstrip("/").split("/")[-1] or "unknown"


# --- engram HTTP -------------------------------------------------------------


def _base_url():
    port = os.environ.get("ENGRAM_PORT", "").strip()
    if not port.isdigit():
        port = "7437"
    return "http://127.0.0.1:" + port


# One opener for every call: an empty ProxyHandler means no proxy, whatever
# `http_proxy`/`HTTP_PROXY` say, because prompts and the bearer token only ever
# go to the local engram server.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _request(path, body=None, method=None):
    headers = {}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    token = os.environ.get("ENGRAM_HTTP_TOKEN", "")
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(
        _base_url() + path, data=data, headers=headers, method=method or ("POST" if data is not None else "GET")
    )
    try:
        with _OPENER.open(request, timeout=HTTP_TIMEOUT) as response:
            response.read()
            return True
    except Exception:
        return False


def is_running():
    return _request("/health")


def engram_binary():
    baked = CONFIG.get("engram_bin")
    if baked and os.path.isfile(baked) and os.access(baked, os.X_OK):
        return baked
    return shutil.which("engram")


def ensure_server():
    if is_running():
        return True
    binary = engram_binary()
    if not binary:
        return False
    try:
        subprocess.Popen(
            [binary, "serve"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
    except Exception:
        return False
    deadline = time.monotonic() + HEALTH_WAIT
    while time.monotonic() < deadline:
        time.sleep(0.2)
        if is_running():
            return True
    return False


def ensure_session(event):
    session_id = event.get("session_id")
    if not session_id:
        return None
    directory = event.get("cwd") or os.getcwd()
    project = extract_project_name(directory)
    _request("/sessions", {"id": session_id, "project": project, "directory": directory})
    return session_id, project


# --- Events ------------------------------------------------------------------


def session_start(event):
    if event.get("agent_id"):
        return
    ensure_server()
    ensure_session(event)


def prompt(event):
    if event.get("agent_id"):
        return
    text = event.get("prompt")
    text = text.strip() if isinstance(text, str) else ""
    if len(text) <= PROMPT_MIN:
        return
    registered = ensure_session(event)
    if registered is None:
        return
    session_id, project = registered
    # Redact first: cutting first would split a credential at the limit and let
    # its prefix escape the patterns. The cut to the detection cap comes before
    # it only so redaction always runs; everything beyond PROMPT_MAX is dropped
    # anyway, and the cap is far above it.
    content = truncate(strip_private_tags(redact(cut_to_detect_cap(text))), PROMPT_MAX)
    _request("/prompts", {"session_id": session_id, "content": content, "project": project})


def subagent_stop(event):
    text = event.get("last_assistant_message")
    if not isinstance(text, str) or len(text) <= PASSIVE_MIN:
        return
    if exceeds_detect_cap(text):
        return  # too large to redact: not sent at all rather than sent as is
    registered = ensure_session(event)
    if registered is None:
        return
    session_id, project = registered
    content = strip_private_tags(redact(text))
    _request(
        "/observations/passive",
        {"session_id": session_id, "content": content, "project": project, "source": "subagent-stop"},
    )


COMMANDS = {"session-start": session_start, "prompt": prompt, "subagent-stop": subagent_stop}


def main(argv):
    command = COMMANDS.get(argv[1]) if len(argv) > 1 else None
    if command is None:
        return
    try:
        event = json.loads(sys.stdin.read() or "{}")
    except Exception:
        return
    if not isinstance(event, dict):
        return
    command(event)


if __name__ == "__main__":
    try:
        main(sys.argv)
    except BaseException as error:  # a hook must never fail the session
        try:
            sys.stderr.write("engram hook: %s\n" % type(error).__name__)
        except Exception:
            pass
    sys.exit(0)
