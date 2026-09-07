"""What a binary calls itself: parsed from data, never branched on in the engine.

`core/`, `ports/`, `infra/` and `tui/` never know a distribution's name. They
know only the `Identity` this module hands them, built once at the composition
root (`cli.py`) from a package data file. This module owns two things a
distribution cannot get wrong without a build-time refusal: the wordmark
charset (also consulted by `tui/wordmark.py`, so the two can never drift
apart -- see `tests/test_wordmark.py`), and the shape a self-upgrade release
source must have so it can never be coerced into fetching from somewhere other
than `https`.
"""
from __future__ import annotations

import json
import re
import string
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

ALLOWED_CHARACTERS = frozenset(string.ascii_uppercase + string.digits)
"""Every character a wordmark word may use. `tui/wordmark.py`'s `GLYPHS` must
cover exactly this set -- see that module's own test."""

MAX_WORD_LENGTH = 12
"""A solo wordmark of the longest allowed word is `12 * 5 - 1 = 59` columns,
which still fits an 80-column terminal. Chosen, not derived."""

SAFE_VERSION = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9.+-]*\Z")
r"""The one charset a version string may use anywhere it reaches a release
URL -- shared, not duplicated, with `core.upgrade._tag`, which applies this
exact same rule to a remote release's own `tag_name` before building
`f"v{version}"` into `asset_url_template`. `identity.version` reaches that
same `_tag` call every time this binary checks or performs its own upgrade,
so a version string this loose would let a malformed or malicious
`identity.json` build a path that escapes the intended
`download/{tag}/{asset}` segment on the release host -- the same class of
risk `_https_url` and `release.binary_asset` already guard against. Defined
here, in `core.identity`, rather than in `core.upgrade`, because `upgrade`
already depends on `identity` (`ReleaseSource`) and a validation rule this
module needs at parse time cannot depend back on a module that imports it.

Anchored with `\A`/`\Z`, never `^`/`$`: Python's `$` also matches immediately
before a final newline, so `^...$` applied with `match()` accepts `"1.0.0\n"` --
passing a rule whose whole purpose is to refuse whitespace, and sending a raw
newline into the release URL. `urlopen` then raises `http.client.InvalidURL`,
which subclasses neither `OSError` nor `ValueError`, so the downloader does not
catch it and the traceback escapes `upgrade` instead of becoming a clean refusal.
`\Z` matches only at the true end of the string, whatever flags or match method
a later caller reaches for."""


class IdentityError(ValueError):
    """`identity.json` is missing, malformed, or fails validation. Never a
    reason to fall back to a default identity -- there is no default."""


@dataclass(frozen=True)
class ReleaseSource:
    """Where a running binary looks for its own next release.

    `asset_url_template` must be `https://` and must contain both `{tag}` and
    `{asset}` -- the two placeholders `core.upgrade` fills in to name one
    published file. `binary_asset` names the asset itself, and must be a bare
    filename: no path separator, no `..`, so it can never be coerced into
    reading or writing outside the one URL it names. `release_page_url` is the
    human-facing releases listing page, declared here rather than derived by
    splitting `asset_url_template` on a magic substring -- not every release
    host shapes its download URL the way GitHub does.

    Every URL field is checked against its parsed authority, not merely its
    prefix: a `https://` prefix match alone would still accept
    `https://github.com@evil.example.com/...`, whose real host --
    `urlsplit(...).hostname` -- is `evil.example.com`, not `github.com`.
    """

    asset_url_template: str
    binary_asset: str
    latest_release_api_url: str
    release_page_url: str


@dataclass(frozen=True)
class Identity:
    """Everything a binary needs to know about its own name.

    `version` is this distribution's own release version -- required, never
    defaulted to the pinned engine's own `pegasus.__version__`. The two are
    independent facts: a distribution pins one engine build and then
    publishes its own releases on its own numbering, so `pegasus.__version__`
    staying fixed across every one of those releases is correct, not a bug --
    it is `version` that must change with each one, and only `identity.json`
    can say what it currently is. `--version`, the upgrade comparison, and
    `doctor`'s `pegasus_version` value all read this field, never the engine
    constant, so each reports the product a person is actually running.

    `wordmark_words` is one or two entries; the renderer draws whatever list
    it is given with no policy branch on count (see `tui/wordmark.py`).
    """

    product_id: str
    display_name: str
    program_name: str
    version: str
    wordmark_words: tuple[str, ...]
    release: ReleaseSource


def _text(payload: dict[str, Any], key: str, what: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise IdentityError(f"{what} needs {key!r}")
    return value


def _word(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value:
        raise IdentityError(f"{what} needs a non-empty word")
    if len(value) > MAX_WORD_LENGTH:
        raise IdentityError(
            f"{what} {value!r} is longer than {MAX_WORD_LENGTH} characters"
        )
    if not set(value) <= ALLOWED_CHARACTERS:
        raise IdentityError(
            f"{what} {value!r} must use only letters A-Z and digits 0-9 -- "
            f"no accents, no hyphens, no spaces"
        )
    return value


def _version(payload: dict[str, Any]) -> str:
    value = _text(payload, "version", "identity")
    if not SAFE_VERSION.match(value):
        raise IdentityError(
            f"identity.version must match {SAFE_VERSION.pattern!r}: {value!r}"
        )
    return value


def _wordmark_words(payload: dict[str, Any]) -> tuple[str, ...]:
    value = payload.get("wordmark_words")
    if not isinstance(value, list) or not (1 <= len(value) <= 2):
        raise IdentityError("identity needs 'wordmark_words' as a list of one or two words")
    return tuple(_word(word, "wordmark_words entry") for word in value)


def _https_url(value: str, what: str) -> str:
    """Reject anything a naive `str.startswith("https://")` prefix check
    would still accept: a scheme other than `https`, userinfo before the
    host (`user@host`, the exact shape that lets `https://github.com@evil.
    example.com/...` read as GitHub at a glance while `urlsplit(...)
    .hostname` names `evil.example.com`), or no host at all."""
    parts = urlsplit(value)
    if parts.scheme != "https":
        raise IdentityError(f"{what} must be https: {value!r}")
    if "@" in parts.netloc:
        raise IdentityError(f"{what} must not carry userinfo before the host: {value!r}")
    if not parts.hostname:
        raise IdentityError(f"{what} must name a host: {value!r}")
    return value


def _release_source(payload: Any) -> ReleaseSource:
    if not isinstance(payload, dict):
        raise IdentityError("identity needs a 'release' object")
    template = _text(payload, "asset_url_template", "release")
    _https_url(template, "release.asset_url_template")
    if "{tag}" not in template or "{asset}" not in template:
        raise IdentityError(
            f"release.asset_url_template must contain both {{tag}} and {{asset}}: {template!r}"
        )
    binary_asset = _text(payload, "binary_asset", "release")
    if "/" in binary_asset or "\\" in binary_asset or ".." in binary_asset:
        raise IdentityError(f"release.binary_asset must be a bare filename: {binary_asset!r}")
    api_url = _text(payload, "latest_release_api_url", "release")
    _https_url(api_url, "release.latest_release_api_url")
    page_url = _text(payload, "release_page_url", "release")
    _https_url(page_url, "release.release_page_url")
    return ReleaseSource(
        asset_url_template=template,
        binary_asset=binary_asset,
        latest_release_api_url=api_url,
        release_page_url=page_url,
    )


def parse(document: bytes) -> Identity:
    """Parse and fully validate an `identity.json` document.

    Raises :class:`IdentityError` naming exactly what is missing or invalid.
    Never returns a partial or default `Identity` -- a caller either gets a
    fully valid one or an exception, so no command can start with an identity
    only half-trusted.
    """
    try:
        text = document.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise IdentityError(f"identity.json is not valid UTF-8: {error}") from error
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise IdentityError(f"identity.json is not valid JSON: {error}") from error
    if not isinstance(payload, dict):
        raise IdentityError("identity.json must be a JSON object")
    product_id = _text(payload, "product_id", "identity")
    if "/" in product_id or "\\" in product_id or ".." in product_id:
        raise IdentityError(f"identity.product_id must be a bare name: {product_id!r}")
    display_name = _text(payload, "display_name", "identity")
    program_name = _text(payload, "program_name", "identity")
    version = _version(payload)
    wordmark_words = _wordmark_words(payload)
    release = _release_source(payload.get("release"))
    return Identity(
        product_id=product_id,
        display_name=display_name,
        program_name=program_name,
        version=version,
        wordmark_words=wordmark_words,
        release=release,
    )
