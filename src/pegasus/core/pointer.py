"""RFC 6901 pointer navigation over plain document trees.

This module is how the engine addresses a point inside a configuration file
without understanding that file's schema. It works on any tree of dicts and
lists, so the same code serves every CLI and every codec.

Every operation returns a new document. Nothing here mutates its input.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

APPEND = "-"
"""Token that addresses the position past the end of an array."""

_MISSING = object()


class PointerError(ValueError):
    """The pointer is malformed, or the document cannot accept it."""


def parse(pointer: str) -> tuple[str, ...]:
    """Split a pointer into its decoded tokens. The empty pointer is the root."""
    if pointer == "":
        return ()
    if not pointer.startswith("/"):
        raise PointerError(f"pointer must be empty or start with '/': {pointer!r}")
    return tuple(_unescape(token) for token in pointer.split("/")[1:])


def build(tokens: tuple[str, ...]) -> str:
    """Render tokens back into a pointer. Inverse of :func:`parse`."""
    return "".join("/" + _escape(token) for token in tokens)


def get_at(document: Any, pointer: str, default: Any = None) -> Any:
    """Read the value at ``pointer``, or ``default`` when the path does not resolve."""
    node = document
    for token in parse(pointer):
        node = _child(node, token)
        if node is _MISSING:
            return default
    return node


def exists_at(document: Any, pointer: str) -> bool:
    """Report whether the path resolves, distinguishing an absent key from a null value."""
    return get_at(document, pointer, _MISSING) is not _MISSING


def set_at(document: Any, pointer: str, value: Any) -> Any:
    """Return a copy of ``document`` with ``value`` written at ``pointer``.

    Missing parents are created. Their type follows the next token: a numeric
    token or ``-`` creates a list, anything else creates a dict.
    """
    tokens = _addressable(pointer)
    result = deepcopy(document)
    node = result
    for depth, token in enumerate(tokens[:-1]):
        node = _descend(node, token, tokens[depth + 1], pointer)
    _assign(node, tokens[-1], value, pointer)
    return result


def unset_at(document: Any, pointer: str) -> Any:
    """Return a copy of ``document`` with ``pointer`` removed.

    Containers left empty by the removal are pruned, so retiring the last owned
    key does not leave an empty object behind in the user's file. Pruning stops
    at the first ancestor that still holds something. Removing a path that does
    not resolve is a no-op.
    """
    tokens = _addressable(pointer)
    result = deepcopy(document)

    nodes = [result]
    for token in tokens[:-1]:
        child = _child(nodes[-1], token)
        if child is _MISSING:
            return result
        nodes.append(child)

    if not _remove(nodes[-1], tokens[-1]):
        return result

    for depth in range(len(tokens) - 2, -1, -1):
        if nodes[depth + 1]:
            break
        _remove(nodes[depth], tokens[depth])
    return result


def _addressable(pointer: str) -> tuple[str, ...]:
    tokens = parse(pointer)
    if not tokens:
        raise PointerError("the document root is not addressable")
    return tokens


def _unescape(token: str) -> str:
    return token.replace("~1", "/").replace("~0", "~")


def _escape(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def _index(token: str, length: int) -> int | None:
    """Resolve an array token to an existing index, or None when it does not address one."""
    if not token.isdigit() or (len(token) > 1 and token.startswith("0")):
        return None
    index = int(token)
    return index if index < length else None


def _child(node: Any, token: str) -> Any:
    if isinstance(node, dict):
        return node.get(token, _MISSING)
    if isinstance(node, list):
        index = _index(token, len(node))
        return _MISSING if index is None else node[index]
    return _MISSING


def _descend(node: Any, token: str, next_token: str, pointer: str) -> Any:
    child = _child(node, token)
    if child is _MISSING:
        child = [] if next_token == APPEND or next_token.isdigit() else {}
        _assign(node, token, child, pointer)
        return child
    if not isinstance(child, (dict, list)):
        raise PointerError(f"{pointer!r} descends through a scalar at {token!r}")
    return child


def _assign(node: Any, token: str, value: Any, pointer: str) -> None:
    if isinstance(node, dict):
        node[token] = value
        return
    if isinstance(node, list):
        if token == APPEND:
            node.append(value)
            return
        index = _index(token, len(node))
        if index is None:
            raise PointerError(f"{pointer!r} does not address an existing item; use '-' to append")
        node[index] = value
        return
    raise PointerError(f"{pointer!r} cannot be written into a {type(node).__name__}")


def _remove(node: Any, token: str) -> bool:
    if isinstance(node, dict) and token in node:
        del node[token]
        return True
    if isinstance(node, list):
        index = _index(token, len(node))
        if index is not None:
            del node[index]
            return True
    return False
