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
import string
from dataclasses import dataclass
from typing import Any

ALLOWED_CHARACTERS = frozenset(string.ascii_uppercase + string.digits)
"""Every character a wordmark word may use. `tui/wordmark.py`'s `GLYPHS` must
cover exactly this set -- see that module's own test."""

MAX_WORD_LENGTH = 12
"""A solo wordmark of the longest allowed word is `12 * 5 - 1 = 59` columns,
which still fits an 80-column terminal. Chosen, not derived."""


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
    reading or writing outside the one URL it names.
    """

    asset_url_template: str
    binary_asset: str
    latest_release_api_url: str


@dataclass(frozen=True)
class Identity:
    """Everything a binary needs to know about its own name.

    `wordmark_words` is one or two entries; the renderer draws whatever list
    it is given with no policy branch on count (see `tui/wordmark.py`).
    """

    product_id: str
    display_name: str
    program_name: str
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


def _wordmark_words(payload: dict[str, Any]) -> tuple[str, ...]:
    value = payload.get("wordmark_words")
    if not isinstance(value, list) or not (1 <= len(value) <= 2):
        raise IdentityError("identity needs 'wordmark_words' as a list of one or two words")
    return tuple(_word(word, "wordmark_words entry") for word in value)


def _release_source(payload: Any) -> ReleaseSource:
    if not isinstance(payload, dict):
        raise IdentityError("identity needs a 'release' object")
    template = _text(payload, "asset_url_template", "release")
    if not template.startswith("https://"):
        raise IdentityError(f"release.asset_url_template must be https: {template!r}")
    if "{tag}" not in template or "{asset}" not in template:
        raise IdentityError(
            f"release.asset_url_template must contain both {{tag}} and {{asset}}: {template!r}"
        )
    binary_asset = _text(payload, "binary_asset", "release")
    if "/" in binary_asset or "\\" in binary_asset or ".." in binary_asset:
        raise IdentityError(f"release.binary_asset must be a bare filename: {binary_asset!r}")
    api_url = _text(payload, "latest_release_api_url", "release")
    if not api_url.startswith("https://"):
        raise IdentityError(f"release.latest_release_api_url must be https: {api_url!r}")
    return ReleaseSource(
        asset_url_template=template,
        binary_asset=binary_asset,
        latest_release_api_url=api_url,
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
    wordmark_words = _wordmark_words(payload)
    release = _release_source(payload.get("release"))
    return Identity(
        product_id=product_id,
        display_name=display_name,
        program_name=program_name,
        wordmark_words=wordmark_words,
        release=release,
    )
