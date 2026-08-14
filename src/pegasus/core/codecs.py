"""Reading and writing configuration files without understanding them.

Two guarantees hold for every codec:

**Stable digests.** ``canonical_bytes`` renders a value the same way regardless
of how it was built, so an unchanged value always hashes to the same digest.

**No collateral damage.** ``dumps`` preserves the author's key order. Sorting a
user's configuration file on write would reorder work Pegasus does not own,
which is why serializing for a digest and serializing for disk are separate
functions.
"""
from __future__ import annotations

import json
from typing import Any

from pegasus.core.types import Codec


class CodecError(ValueError):
    """The document could not be parsed with the declared codec."""


def loads(codec: Codec, text: str) -> Any:
    """Parse a configuration document."""
    if codec is not Codec.JSON:
        raise _unsupported(codec)
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        raise CodecError(f"invalid {codec.value} document: {error}") from error


def dumps(codec: Codec, document: Any) -> str:
    """Serialize a configuration document for writing to disk, preserving key order."""
    if codec is not Codec.JSON:
        raise _unsupported(codec)
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def canonical_bytes(value: Any) -> bytes:
    """Render a value for hashing.

    Codec-independent on purpose: a digest describes the value Pegasus owns,
    not the file format that happens to carry it.
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _unsupported(codec: Codec) -> NotImplementedError:
    return NotImplementedError(
        f"the {codec.value} codec is declared but not implemented in this release"
    )
