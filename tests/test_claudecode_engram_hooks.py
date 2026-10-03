"""Pegasus-owned Claude Code hooks that register sessions and prompts in engram.

Three layers: what the adapter renders (and only when engram is selected), how
the planner owns and removes the settings entries, and what the rendered script
does when it runs against a fake local engram server.

Temp homes and temp directories only: no real `~/.claude`, no real engram, no
real `~/.engram`. The script is a subprocess fed JSON on stdin.
"""
from __future__ import annotations

import json
import os
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from pegasus.adapters.claudecode import Adapter
from pegasus.adapters.claudecode import render as render_module
from pegasus.core import content as content_module
from pegasus.core import credential_transport
from pegasus.core.types import ConfigKeyArtifact, Environment, FileArtifact
from test_cli_claudecode import CLI, RealHomeTestCase

ROOT = Path(__file__).resolve().parents[1]
SECRET_TRANSPORT = ROOT / "src/pegasus/adapters/opencode/assets/plugins/secret-transport.ts"
CATALOG = ROOT / "src/pegasus/content/security/credential-transport-catalog.json"
PARITY_HARNESS = ROOT / "tests/fixtures/engram_hook_redaction_parity.mjs"

HOME = Path("/home/probe")


def environment(product: str) -> Environment:
    return Environment(home=HOME, data_dir=HOME / ".local" / "share" / product)


def engram() -> content_module.Mcp:
    return next(item for item in content_module.load().mcp if item.name == "engram")


def other_server() -> content_module.Mcp:
    return next(item for item in content_module.load().mcp if item.name != "engram")


def hook_artifacts(artifacts):
    return [a for a in artifacts if a.id.startswith("mcp-hook")]


class RenderTest(unittest.TestCase):
    def setUp(self):
        self.adapter = Adapter()
        self.layout = self.adapter.layout(environment("pegasus-harness"))

    def test_engram_brings_the_script_and_the_three_settings_entries(self):
        artifacts = self.adapter.render_mcp(self.layout, engram())
        script = [a for a in artifacts if isinstance(a, FileArtifact) and a.id == "mcp-hook-script:engram"]
        entries = [a for a in artifacts if isinstance(a, ConfigKeyArtifact)]
        self.assertEqual(len(script), 1)
        self.assertTrue(script[0].executable)
        self.assertEqual(
            [a.pointer for a in entries],
            ["/hooks/SessionStart/-", "/hooks/UserPromptSubmit/-", "/hooks/SubagentStop/-"],
        )
        for entry in entries:
            self.assertEqual(entry.path, self.layout.settings_file)

    def test_no_other_server_brings_hooks(self):
        self.assertEqual(hook_artifacts(self.adapter.render_mcp(self.layout, other_server())), [])

    def test_the_entries_use_the_documented_shape_and_only_the_agreed_events(self):
        entries = {
            a.pointer.split("/")[2]: a.value
            for a in self.adapter.render_mcp(self.layout, engram())
            if isinstance(a, ConfigKeyArtifact)
        }
        self.assertEqual(set(entries), {"SessionStart", "UserPromptSubmit", "SubagentStop"})
        self.assertEqual(entries["SessionStart"]["matcher"], "startup|resume|clear|fork")
        self.assertNotIn("matcher", entries["UserPromptSubmit"])
        self.assertNotIn("matcher", entries["SubagentStop"])
        script = render_module.engram_hook_script_path(self.layout)
        for event, subcommand in (
            ("SessionStart", "session-start"),
            ("UserPromptSubmit", "prompt"),
            ("SubagentStop", "subagent-stop"),
        ):
            (hook,) = entries[event]["hooks"]
            self.assertEqual(hook["type"], "command")
            self.assertEqual(
                hook["command"],
                f"command -v python3 >/dev/null 2>&1 && python3 {shlex.quote(str(script))} {subcommand} || true",
            )
            self.assertIsInstance(hook["timeout"], int)
            if event == "SessionStart":
                self.assertNotIn("async", hook)  # it must start the server before any prompt
            else:
                self.assertIs(hook["async"], True)

    def test_a_path_with_spaces_stays_quoted_inside_the_guarded_command(self):
        layout = self.adapter.layout(Environment(home=Path("/home/a b"), data_dir=Path("/home/a b/.local/share/x")))
        for artifact in self.adapter.render_mcp(layout, engram()):
            if isinstance(artifact, ConfigKeyArtifact):
                command = artifact.value["hooks"][0]["command"]
                self.assertIn("python3 '/home/a b/.local/share/x/hooks/engram-hook.py' ", command)
                self.assertTrue(command.endswith(" || true"))

    def test_rendering_is_deterministic(self):
        first = self.adapter.render_mcp(self.layout, engram())
        second = self.adapter.render_mcp(self.layout, engram())
        self.assertEqual(first, second)

    def test_the_managed_binary_path_is_baked_in(self):
        item = engram()
        script = render_module.render_engram_hook_script(self.layout, item).decode()
        expected = str(render_module.program_path(self.layout.dependencies_dir, item))
        self.assertIn(json.dumps({"engram_bin": expected})[1:-1].split(": ")[1], script)
        self.assertIn(expected, script)

    def test_a_bound_server_falls_back_to_path(self):
        bound = replace(engram(), bound_to="my-engram")
        script = render_module.render_engram_hook_script(self.layout, bound).decode()
        self.assertIn('"engram_bin": null', script)
        self.assertNotIn(str(self.layout.dependencies_dir), script)
        self.assertEqual(len(hook_artifacts(self.adapter.render_mcp(self.layout, bound))), 4)

    def test_paths_derive_from_the_products_own_data_directory(self):
        first = self.adapter.layout(environment("pegasus-harness"))
        second = self.adapter.layout(environment("darq"))
        a = render_module.engram_hook_script_path(first)
        b = render_module.engram_hook_script_path(second)
        self.assertEqual(a, HOME / ".local/share/pegasus-harness/hooks/engram-hook.py")
        self.assertEqual(b, HOME / ".local/share/darq/hooks/engram-hook.py")
        commands = [
            artifact.value["hooks"][0]["command"]
            for layout in (first, second)
            for artifact in self.adapter.render_mcp(layout, engram())
            if isinstance(artifact, ConfigKeyArtifact)
        ]
        self.assertTrue(all("pegasus-harness" in c for c in commands[:3]))
        self.assertTrue(all("darq" in c and "pegasus-harness" not in c for c in commands[3:]))
        # The script itself carries no product name.
        text = render_module.render_engram_hook_script(second, engram()).decode()
        self.assertNotIn("pegasus-harness/mcp", text)
        self.assertIn(".local/share/darq/mcp", text)

    def test_a_layout_without_a_data_directory_renders_no_hooks(self):
        layout = self.adapter.layout(Environment(home=HOME))
        self.assertEqual(hook_artifacts(self.adapter.render_mcp(layout, engram())), [])

    def test_the_script_carries_the_whole_credential_catalog(self):
        text = render_module.render_engram_hook_script(self.layout, engram()).decode()
        namespace: dict = {"__name__": "rendered_hook"}
        exec(compile(text, "engram-hook.py", "exec"), namespace)
        self.assertEqual(namespace["CONFIG"]["catalog"], credential_transport.load_catalog())

    def test_no_protocol_text_or_unwanted_events_are_rendered(self):
        text = render_module.render_engram_hook_script(self.layout, engram()).decode()
        for forbidden in ("mem_session_summary", "MEMORY REMINDER", "CRITICAL INSTRUCTION", "additionalContext"):
            self.assertNotIn(forbidden, text)
        pointers = {a.pointer for a in self.adapter.render_mcp(self.layout, engram()) if isinstance(a, ConfigKeyArtifact)}
        for event in ("Stop", "SessionEnd"):
            self.assertNotIn(f"/hooks/{event}/-", pointers)


class PlannerOwnershipTest(RealHomeTestCase):
    """Through the real engine, with a bound engram so nothing is downloaded."""

    USER_HOOK = {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo mine"}]}
    USER_PROMPT_HOOK = {"hooks": [{"type": "command", "command": "echo prompt"}]}

    def settings(self):
        return json.loads(self.layout().settings_file.read_bytes())

    def script(self) -> Path:
        return self.home / ".local" / "share" / "pegasus-harness" / "hooks" / "engram-hook.py"

    def seed_user_hooks(self):
        self.present()
        self.layout().settings_file.write_text(
            json.dumps(
                {
                    "model": "opus",
                    "hooks": {
                        "PreToolUse": [self.USER_HOOK],
                        "UserPromptSubmit": [self.USER_PROMPT_HOOK],
                    },
                }
            ),
            encoding="utf-8",
        )

    def test_install_with_engram_creates_the_missing_hook_lists(self):
        self.install("--mcp", "engram=my-engram")
        hooks = self.settings()["hooks"]
        self.assertEqual(sorted(hooks), ["SessionStart", "SubagentStop", "UserPromptSubmit"])
        for event in hooks:
            self.assertEqual(len(hooks[event]), 1)
        self.assertTrue(self.script().is_file())
        self.assertTrue(self.script().stat().st_mode & stat.S_IXUSR)

    def test_install_without_engram_writes_no_hooks(self):
        self.install("--mcp", "context7")
        self.assertNotIn("hooks", self.settings())
        self.assertFalse(self.script().exists())

    def test_appending_keeps_the_users_own_hooks(self):
        self.seed_user_hooks()
        code, report = self.run_cli("install", "--cli", CLI, "--mcp", "engram=my-engram")
        self.assertEqual(code, 0, report)
        settings = self.settings()
        self.assertEqual(settings["model"], "opus")
        self.assertEqual(settings["hooks"]["PreToolUse"], [self.USER_HOOK])
        prompt = settings["hooks"]["UserPromptSubmit"]
        self.assertEqual(len(prompt), 2)
        self.assertEqual(prompt[0], self.USER_PROMPT_HOOK)
        self.assertIn("engram-hook.py", prompt[1]["hooks"][0]["command"])

    def test_an_object_shaped_event_fails_cleanly_and_leaves_the_file_untouched(self):
        self.present()
        original = json.dumps({"hooks": {"SessionStart": {"matcher": "x"}}}, indent=2)
        self.layout().settings_file.write_text(original, encoding="utf-8")
        code, report = self.run_cli("install", "--cli", CLI, "--mcp", "engram=my-engram")
        self.assertNotEqual(code, 0, report)
        self.assertEqual(self.layout().settings_file.read_text(encoding="utf-8"), original)
        self.assertNotIn('"-"', self.layout().settings_file.read_text(encoding="utf-8"))
        self.assertFalse(self.script().exists())

    def test_update_does_not_duplicate_the_entries(self):
        self.install("--mcp", "engram=my-engram")
        code, report = self.run_cli("update", "--cli", CLI)
        self.assertEqual(code, 0, report)
        for event, entries in self.settings()["hooks"].items():
            self.assertEqual(len(entries), 1, event)

    def test_uninstall_removes_only_pegasus_entries_and_the_script(self):
        self.seed_user_hooks()
        self.run_cli("install", "--cli", CLI, "--mcp", "engram=my-engram")
        code, report = self.run_cli("uninstall", "--cli", CLI)
        self.assertEqual(code, 0, report)
        hooks = self.settings()["hooks"]
        self.assertEqual(hooks["PreToolUse"], [self.USER_HOOK])
        self.assertEqual(hooks["UserPromptSubmit"], [self.USER_PROMPT_HOOK])
        self.assertFalse(any(entries for event, entries in hooks.items() if event in ("SessionStart", "SubagentStop")))
        self.assertFalse(self.script().exists())

    def test_restore_round_trips_to_the_users_settings(self):
        self.seed_user_hooks()
        before = self.settings()
        self.run_cli("install", "--cli", CLI, "--mcp", "engram=my-engram")
        self.assertNotEqual(self.settings(), before)
        code, report = self.run_cli("restore")
        self.assertEqual(code, 0, report)
        self.assertEqual(self.settings(), before)
        self.assertFalse(self.script().exists())

    def test_reinstalling_without_engram_removes_the_hooks(self):
        self.seed_user_hooks()
        self.run_cli("install", "--cli", CLI, "--mcp", "engram=my-engram")
        code, report = self.run_cli("install", "--cli", CLI, "--mcp", "context7")
        self.assertEqual(code, 0, report)
        hooks = self.settings()["hooks"]
        self.assertEqual(hooks["UserPromptSubmit"], [self.USER_PROMPT_HOOK])
        self.assertEqual(hooks["PreToolUse"], [self.USER_HOOK])
        self.assertFalse(hooks.get("SessionStart"))
        self.assertFalse(self.script().exists())

    def test_doctor_sees_a_hand_removed_hook_entry(self):
        self.install("--mcp", "engram=my-engram")
        _, clean = self.run_cli("doctor")
        entry = next(e for e in clean["clis"] if e["cli"] == CLI)
        self.assertEqual(entry["drifted"], [])
        self.assertEqual(entry["missing"], [])
        settings = self.settings()
        settings["hooks"]["SubagentStop"] = []
        self.layout().settings_file.write_text(json.dumps(settings), encoding="utf-8")
        _, report = self.run_cli("doctor")
        entry = next(e for e in report["clis"] if e["cli"] == CLI)
        self.assertTrue(entry["drifted"] or entry["missing"], entry)


class FakeEngram:
    """A local HTTP server that records every request."""

    def __init__(self, health=True):
        self.requests: list[dict] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _record(self, body):
                outer.requests.append(
                    {
                        "method": self.command,
                        "path": self.path,
                        "auth": self.headers.get("Authorization"),
                        "body": json.loads(body) if body else None,
                    }
                )
                self.send_response(200 if (health or self.path != "/health") else 503)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"{}")

            def do_GET(self):
                self._record(b"")

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                self._record(self.rfile.read(length))

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def posts(self, path):
        return [r for r in self.requests if r["method"] == "POST" and r["path"] == path]


FAKE_ENGRAM_BINARY = """#!{python}
import http.server, json, os, sys, threading
log = os.environ["FAKE_ENGRAM_LOG"]
with open(log, "a") as handle:
    handle.write(json.dumps({{"argv": sys.argv[1:]}}) + "\\n")
if sys.argv[1:] != ["serve"]:
    sys.exit(0)
class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass
    def _answer(self, body):
        with open(log, "a") as handle:
            handle.write(json.dumps({{"path": self.path, "body": body}}) + "\\n")
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"{{}}")
    def do_GET(self):
        self._answer(None)
    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        self._answer(json.loads(self.rfile.read(length) or b"null"))
server = http.server.HTTPServer(("127.0.0.1", int(os.environ["ENGRAM_PORT"])), Handler)
threading.Timer(15, server.shutdown).start()
server.serve_forever()
"""


class ScriptTest(unittest.TestCase):
    """The rendered script as a subprocess, JSON on stdin, a fake server on a port."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.tmp = Path(self.directory.name)
        self.adapter = Adapter()
        self.layout = self.adapter.layout(
            Environment(home=self.tmp, data_dir=self.tmp / "data")
        )
        self.item = engram()
        self.script = self.tmp / "engram-hook.py"
        self.script.write_bytes(render_module.render_engram_hook_script(self.layout, self.item))
        self.workdir = self.tmp / "widgets"
        self.workdir.mkdir()
        self.servers: list[FakeEngram] = []

    def tearDown(self):
        for server in self.servers:
            server.close()

    def fake(self, health=True) -> FakeEngram:
        server = FakeEngram(health)
        self.servers.append(server)
        return server

    def free_port(self) -> int:
        server = FakeEngram()
        port = server.port
        server.close()
        return port

    def run_script(self, command, event, port, extra_env=None, script=None):
        env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": str(self.tmp),
            "ENGRAM_PORT": str(port),
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
        }
        env.update(extra_env or {})
        result = subprocess.run(
            [sys.executable, str(script or self.script), command],
            input=event if isinstance(event, str) else json.dumps(event),
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        return result

    def event(self, **fields):
        return {"session_id": "sess-1", "cwd": str(self.workdir), **fields}

    # --- session-start ---

    def test_session_start_upserts_the_session(self):
        server = self.fake()
        self.run_script("session-start", self.event(), server.port)
        (post,) = server.posts("/sessions")
        self.assertEqual(
            post["body"], {"id": "sess-1", "project": "widgets", "directory": str(self.workdir)}
        )
        self.assertEqual([r["path"] for r in server.requests][0], "/health")

    def test_a_subagent_context_is_never_registered(self):
        server = self.fake()
        self.run_script("session-start", self.event(agent_id="a1", agent_type="x"), server.port)
        self.run_script("prompt", self.event(agent_id="a1", prompt="a long enough prompt here"), server.port)
        self.assertEqual(server.posts("/sessions"), [])
        self.assertEqual(server.posts("/prompts"), [])

    def test_project_comes_from_the_git_remote_like_the_opencode_plugin(self):
        subprocess.run(["git", "init", "-q", str(self.workdir)], check=True, env={**os.environ, "GIT_CONFIG_GLOBAL": os.devnull})
        subprocess.run(
            ["git", "-C", str(self.workdir), "remote", "add", "origin", "git@example.com:acme/Gadgets.git"],
            check=True,
            env={**os.environ, "GIT_CONFIG_GLOBAL": os.devnull},
        )
        server = self.fake()
        self.run_script("session-start", self.event(), server.port)
        self.assertEqual(server.posts("/sessions")[0]["body"]["project"], "Gadgets")

    def test_project_falls_back_to_the_git_root_then_the_directory_name(self):
        subprocess.run(["git", "init", "-q", str(self.workdir)], check=True, env={**os.environ, "GIT_CONFIG_GLOBAL": os.devnull})
        nested = self.workdir / "src" / "deep"
        nested.mkdir(parents=True)
        server = self.fake()
        self.run_script("session-start", self.event(cwd=str(nested)), server.port)
        self.assertEqual(server.posts("/sessions")[0]["body"]["project"], "widgets")

    def test_the_auth_token_is_sent_as_a_bearer_header_only_when_set(self):
        server = self.fake()
        self.run_script("session-start", self.event(), server.port)
        self.assertEqual({r["auth"] for r in server.requests}, {None})
        self.run_script("session-start", self.event(), server.port, {"ENGRAM_HTTP_TOKEN": "s3cret-token"})
        self.assertEqual({r["auth"] for r in server.requests[-2:]}, {"Bearer s3cret-token"})

    def install_fake_binary(self, log: Path) -> Path:
        binary = self.tmp / "fake-engram"
        binary.write_text(FAKE_ENGRAM_BINARY.format(python=sys.executable))
        binary.chmod(0o755)
        return binary

    def render_with_binary(self, binary: Path):
        item = engram()
        path = render_module.program_path(self.layout.dependencies_dir, item)
        path.parent.mkdir(parents=True)
        shutil.copy(binary, path)
        path.chmod(0o755)
        script = self.tmp / "engram-hook-with-binary.py"
        script.write_bytes(render_module.render_engram_hook_script(self.layout, item))
        return script

    def test_session_start_starts_the_managed_binary_when_the_server_is_down(self):
        log = self.tmp / "fake-engram.log"
        script = self.render_with_binary(self.install_fake_binary(log))
        port = self.free_port()
        self.run_script("session-start", self.event(), port, {"FAKE_ENGRAM_LOG": str(log)}, script)
        lines = [json.loads(line) for line in log.read_text().splitlines()]
        self.assertEqual(lines[0], {"argv": ["serve"]})
        sessions = [l for l in lines if l.get("path") == "/sessions"]
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["body"]["id"], "sess-1")

    def test_a_running_server_is_not_started_again(self):
        log = self.tmp / "fake-engram.log"
        script = self.render_with_binary(self.install_fake_binary(log))
        server = self.fake()
        self.run_script("session-start", self.event(), server.port, {"FAKE_ENGRAM_LOG": str(log)}, script)
        self.assertFalse(log.exists())
        self.assertEqual(len(server.posts("/sessions")), 1)

    def test_a_user_bound_engram_falls_back_to_the_one_on_path(self):
        log = self.tmp / "fake-engram.log"
        binary = self.install_fake_binary(log)
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        shutil.copy(binary, bin_dir / "engram")
        bound = replace(engram(), bound_to="my-engram")
        script = self.tmp / "bound.py"
        script.write_bytes(render_module.render_engram_hook_script(self.layout, bound))
        port = self.free_port()
        self.run_script(
            "session-start",
            self.event(),
            port,
            {"FAKE_ENGRAM_LOG": str(log), "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"},
            script,
        )
        self.assertEqual(json.loads(log.read_text().splitlines()[0]), {"argv": ["serve"]})

    def test_no_binary_at_all_still_attempts_the_http_calls(self):
        port = self.free_port()
        bound = replace(engram(), bound_to="my-engram")
        script = self.tmp / "bound.py"
        script.write_bytes(render_module.render_engram_hook_script(self.layout, bound))
        empty = self.tmp / "empty"
        empty.mkdir()
        self.run_script("session-start", self.event(), port, {"PATH": str(empty)}, script)

    # --- prompt ---

    def test_a_prompt_upserts_the_session_then_records_it(self):
        server = self.fake()
        self.run_script("prompt", self.event(prompt="please explain the retry policy"), server.port)
        paths = [r["path"] for r in server.requests if r["method"] == "POST"]
        self.assertEqual(paths, ["/sessions", "/prompts"])
        self.assertEqual(
            server.posts("/prompts")[0]["body"],
            {"session_id": "sess-1", "content": "please explain the retry policy", "project": "widgets"},
        )

    def test_short_prompts_are_not_recorded(self):
        server = self.fake()
        self.run_script("prompt", self.event(prompt="short one!"), server.port)  # exactly 10 chars
        self.run_script("prompt", self.event(prompt="   yes   "), server.port)
        self.run_script("prompt", self.event(), server.port)
        self.assertEqual(server.posts("/prompts"), [])

    def test_eleven_characters_are_recorded(self):
        server = self.fake()
        self.run_script("prompt", self.event(prompt="eleven char"), server.port)
        self.assertEqual(len(server.posts("/prompts")), 1)

    def test_long_prompts_are_truncated_to_2000_with_an_ellipsis(self):
        server = self.fake()
        self.run_script("prompt", self.event(prompt="x" * 2500), server.port)
        self.assertEqual(server.posts("/prompts")[0]["body"]["content"], "x" * 2000 + "...")

    def test_private_tags_are_stripped(self):
        server = self.fake()
        self.run_script("prompt", self.event(prompt="note <private>my diary entry</private> and more"), server.port)
        content = server.posts("/prompts")[0]["body"]["content"]
        self.assertNotIn("diary", content)
        self.assertNotIn("<private>", content)

    def test_credentials_are_redacted(self):
        server = self.fake()
        secret = "sk-" + "A1b2C3d4E5" * 3
        self.run_script(
            "prompt",
            self.event(prompt=f"use {secret} with password=hunter2hunter2 against db"),
            server.port,
        )
        content = server.posts("/prompts")[0]["body"]["content"]
        self.assertNotIn(secret, content)
        self.assertNotIn("hunter2hunter2", content)
        self.assertIn("$PEGASUS_SECRET_", content)

    def test_a_secret_straddling_the_prompt_limit_is_redacted_before_the_cut(self):
        server = self.fake()
        secret = "ghp_" + "a1B2c3D4e5" * 4
        for pad in range(1990, 2000):
            self.run_script("prompt", self.event(prompt="y" * pad + " " + secret), server.port)
        for post in server.posts("/prompts"):
            self.assertNotIn("ghp_", post["body"]["content"])

    def test_the_cut_never_precedes_redaction_even_for_private_tags(self):
        server = self.fake()
        self.run_script("prompt", self.event(prompt="y" * 1995 + " <private>topsecretvalue</private>"), server.port)
        content = server.posts("/prompts")[0]["body"]["content"]
        self.assertNotIn("<private>", content)
        self.assertNotIn("topsecret", content)

    def test_a_prompt_above_the_detection_cap_is_cut_and_redacted_never_sent_raw(self):
        server = self.fake()
        secret = "ghp_" + "a1B2c3D4e5" * 4
        self.run_script("prompt", self.event(prompt=secret + " " + "z " * 200000), server.port)
        content = server.posts("/prompts")[0]["body"]["content"]
        self.assertNotIn(secret, content)
        self.assertNotIn("ghp_", content)
        self.assertLessEqual(len(content), 2003)

    def test_a_cut_inside_a_multibyte_character_does_not_skip_redaction(self):
        for name, char in (("cjk", "\u3042"), ("emoji", "\U0001F600")):
            for pad in range(4):
                with self.subTest(padding=name, pad=pad):
                    server = self.fake()
                    secret = "ghp_" + f"{pad:02d}" + "Qw7Zk3Xv9L" * 3 + "Rt"
                    self.run_script(
                        "prompt", self.event(prompt=secret + " " + "x" * pad + char * 100000), server.port
                    )
                    content = server.posts("/prompts")[0]["body"]["content"]
                    self.assertNotIn("ghp_", content)
                    self.assertNotIn(secret[4:], content)

    def test_requests_ignore_the_proxy_environment(self):
        proxy = self.fake()
        server = self.fake()
        env = {
            "http_proxy": f"http://127.0.0.1:{proxy.port}",
            "HTTP_PROXY": f"http://127.0.0.1:{proxy.port}",
            "ALL_PROXY": f"http://127.0.0.1:{proxy.port}",
            "ENGRAM_HTTP_TOKEN": "tok-123",
        }
        self.run_script("prompt", self.event(prompt="please explain the retry policy"), server.port, env)
        self.assertEqual(proxy.requests, [])
        self.assertEqual(server.posts("/prompts")[0]["auth"], "Bearer tok-123")

    def test_many_unclosed_private_tags_complete_quickly(self):
        import time

        server = self.fake()
        started = time.monotonic()
        self.run_script("prompt", self.event(prompt="<private>" * 28000), server.port)
        self.run_script(
            "subagent-stop", self.event(agent_id="a", last_assistant_message="<private>" * 28000), server.port
        )
        self.assertLess(time.monotonic() - started, 5)

    def test_private_stripping_matches_the_lazy_regex(self):
        import re

        namespace: dict = {"__name__": "rendered_hook"}
        exec(compile(self.script.read_text(), "engram-hook.py", "exec"), namespace)
        strip = namespace["strip_private_tags"]
        for text in (
            "a <private>x</private> b <PRIVATE>y</Private> c",
            "<private><private>x</private></private>",
            "<private>unclosed and </private> then <private>again",
            "<private></private>",
            "</private><private>",
            "no tags",
        ):
            expected = re.sub(r"<private>[\s\S]*?</private>", "[REDACTED]", text, flags=re.I).strip()
            self.assertEqual(strip(text), expected, text)

    def test_the_project_of_a_root_or_trailing_slash_directory(self):
        namespace: dict = {"__name__": "rendered_hook"}
        exec(compile(self.script.read_text(), "engram-hook.py", "exec"), namespace)
        extract = namespace["extract_project_name"]
        namespace["_git"] = lambda *args: None
        self.assertEqual(extract("/"), "unknown")
        self.assertEqual(extract("/nonexistent-dir/widgets/"), "widgets")

    # --- subagent-stop ---

    def test_a_sub_agent_message_above_the_detection_cap_is_not_posted(self):
        server = self.fake()
        secret = "ghp_" + "a1B2c3D4e5" * 4
        message = "## Key Learnings\n" + "z " * 140000 + secret
        self.run_script("subagent-stop", self.event(agent_id="a1", last_assistant_message=message), server.port)
        self.assertEqual(server.posts("/observations/passive"), [])
        self.assertEqual(server.posts("/sessions"), [])

    def test_subagent_stop_posts_a_long_message_as_passive_capture(self):
        server = self.fake()
        message = "## Key Learnings\n1. The retry policy lives in the gateway adapter, not the client.\n"
        self.run_script(
            "subagent-stop", self.event(agent_id="a1", agent_type="x", last_assistant_message=message), server.port
        )
        (post,) = server.posts("/observations/passive")
        self.assertEqual(
            post["body"],
            {"session_id": "sess-1", "content": message.strip(), "project": "widgets", "source": "subagent-stop"},
        )

    def test_subagent_stop_ignores_short_messages(self):
        server = self.fake()
        self.run_script("subagent-stop", self.event(agent_id="a1", last_assistant_message="y" * 50), server.port)
        self.run_script("subagent-stop", self.event(agent_id="a1"), server.port)
        self.assertEqual(server.posts("/observations/passive"), [])
        self.run_script("subagent-stop", self.event(agent_id="a1", last_assistant_message="y" * 51), server.port)
        self.assertEqual(len(server.posts("/observations/passive")), 1)

    def test_subagent_stop_redacts_and_does_not_truncate(self):
        server = self.fake()
        secret = "ghp_" + "Z9y8X7w6V5" * 3
        message = f"## Key Learnings\n1. token {secret} <private>hidden</private> " + "z" * 3000
        self.run_script("subagent-stop", self.event(agent_id="a1", last_assistant_message=message), server.port)
        content = server.posts("/observations/passive")[0]["body"]["content"]
        self.assertNotIn(secret, content)
        self.assertNotIn("hidden", content)
        self.assertGreater(len(content), 3000)

    # --- robustness ---

    def test_server_down_exits_zero_with_empty_stdout(self):
        port = self.free_port()
        empty = self.tmp / "empty"
        empty.mkdir()
        for command, event in (
            ("session-start", self.event()),
            ("prompt", self.event(prompt="a long enough prompt text")),
            ("subagent-stop", self.event(agent_id="a", last_assistant_message="m" * 80)),
        ):
            self.run_script(command, event, port, {"PATH": str(empty)})

    def test_garbage_input_and_unknown_commands_exit_zero_silently(self):
        server = self.fake()
        for raw in ("", "not json", "[]", "null", '{"session_id": 5, "cwd": 7, "prompt": 9}'):
            for command in ("session-start", "prompt", "subagent-stop", "nonsense"):
                self.run_script(command, raw, server.port)

    def test_a_server_that_answers_errors_does_not_break_the_hook(self):
        server = self.fake(health=False)
        empty = self.tmp / "empty"
        empty.mkdir()
        self.run_script("prompt", self.event(prompt="a long enough prompt text"), server.port, {"PATH": str(empty)})

    def test_a_missing_session_id_posts_nothing(self):
        server = self.fake()
        self.run_script("prompt", {"cwd": str(self.workdir), "prompt": "a long enough prompt text"}, server.port)
        self.assertEqual(server.posts("/prompts"), [])


REDACTION_CASES = [
    "plain text with nothing secret and a commit " + "a" * 40 + " and sha " + "b" * 64,
    "use sk-" + "A1b2C3d4E5" * 3 + " now",
    "token ghp_" + "Q" * 30 + " and AKIA" + "ABCDEFGH12345678",
    "Authorization: Bearer abcdef1234567890",
    "authorization: basic dXNlcjpwYXNzd29yZA==",
    "X-Api-Key: abcdef1234567890xyz",
    "X-Hub-Signature-256: sha256=abcdef1234567890abcdef",
    "X-Aco-Joven-Signature: 1234567890abcdef\nX-Signature-Version: 12345678",
    "postgres://admin:s3cr3tP4ssw0rd@db.internal:5432/app",
    'X-Authorization: {"id":18618,"token":"' + "c" * 64 + '","clientKey":"' + "d" * 64 + '","obra_social":"12"}',
    'config {"password": "plainword", "api_key": "k1k2k3k4k5", "name": "x"}',
    "password: 'plainword' and secret = \"abcd\" and note: ok",
    "DB_PASSWORD=s3cr3tP4ss and DB_USER=admin and const token = getToken()",
    "token = accessToken; password: process.env.DB_PASS; apiKey=$API_KEY",
    "note: password=hunter2hunter and Content-Type: password=another1pass",
    "https://api.example.com/x?token=abc123def456&page=2",
    "<private>DB_PASSWORD=topsecretvalue</private> then <private>just a note</private>",
    "same value twice: password=Sup3rS3cret and again token=Sup3rS3cret and key2 secret=Other1234",
    "-----BEGIN RSA PRIVATE KEY-----\nMIIBOgIBAAJBAKj34GkxFhD90vcNLYLInFEX6Ppy1tPf9Cnzj4p4WGeKLs1Pt8Qu\n-----END RSA PRIVATE KEY-----",
    "jwt eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dBjftJeZ4CVPmB92K27uhbUJU1p1r",
    "slack xoxb-1234567890-abcdefghij and ***** and password=null and token=TODO",
    "x" * 300,
    "<private>unclosed value never closed and token=abcdefgh1234",
    "<private>aaaa-note</private> tail <private>b=c1234567</private> <private>open " + "<private>" * 50,
    "</private> stray close then <private>X=secretvalue1</private> and <PRIVATE>y1234567</PRIVATE>",
]


class RedactionParityTest(unittest.TestCase):
    """The script's redaction must equal the OpenCode secret transport's, on the
    same catalog, case by case. If either side drifts, this fails."""

    @classmethod
    def setUpClass(cls):
        text = render_module.render_engram_hook_script(
            Adapter().layout(environment("pegasus-harness")), engram()
        ).decode()
        cls.namespace: dict = {"__name__": "rendered_hook"}
        exec(compile(text, "engram-hook.py", "exec"), cls.namespace)

    def test_cases_cover_every_detection_pass(self):
        redact = self.namespace["redact"]
        changed = [case for case in REDACTION_CASES if redact(case) != case]
        self.assertGreaterEqual(len(changed), len(REDACTION_CASES) - 3)

    def test_the_script_matches_the_opencode_plugin_on_every_case(self):
        if shutil.which("node") is None:
            self.skipTest("node is not installed, cannot run the plugin")
        result = subprocess.run(
            ["node", "--experimental-strip-types", str(PARITY_HARNESS), str(SECRET_TRANSPORT), str(CATALOG)],
            input=json.dumps(REDACTION_CASES),
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        expected = json.loads(result.stdout)
        redact = self.namespace["redact"]
        for case, plugin_output in zip(REDACTION_CASES, expected, strict=True):
            self.assertEqual(redact(case), plugin_output, case)

    def test_the_catalog_the_script_carries_is_the_one_the_plugin_reads(self):
        self.assertEqual(self.namespace["CONFIG"]["catalog"], json.loads(CATALOG.read_text()))
        self.assertEqual(credential_transport.load_catalog_bytes(), CATALOG.read_bytes())


if __name__ == "__main__":
    unittest.main()
