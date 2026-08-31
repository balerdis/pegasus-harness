"""A purpose-built parser for the frontmatter shapes shipped content actually uses.

Not a general-purpose format parser: it accepts exactly what was measured across
every shipped descriptor -- bare and quoted scalar strings, booleans, flow-style
lists of strings, and one level of block-style mapping nesting -- and refuses
everything else, loudly, at load time.

That refusal is the point. A misparsed `tools:` or `optional_mcp:` field silently
turning into some wrong-but-plausible value would hand a real machine a wrong
permission; a hard failure naming the source file and line is a much smaller
problem than that.
"""
from __future__ import annotations

from typing import Any


class FrontmatterError(ValueError):
    """A frontmatter document used a shape this parser does not understand."""


def parse(text: str, source: str) -> dict[str, Any]:
    """Parse a frontmatter document into a plain mapping, or refuse it.

    ``source`` names the file the text came from, so every refusal can point
    at exactly the line that could not be understood.
    """
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]
    result: dict[str, Any] = {}
    i = 0
    n = len(lines)
    while i < n:
        raw_line = lines[i]
        line_no = i + 1
        if not raw_line.strip():
            i += 1
            continue
        if raw_line[0] in " \t":
            raise _refuse(source, line_no, "unexpected indentation")
        key, value_text = _split_key_value(raw_line, source, line_no)
        if value_text == "":
            # Either a one-level nested mapping, or a refused deeper/foreign shape.
            nested, consumed = _parse_nested_mapping(lines, i + 1, source)
            result[key] = nested
            i = consumed
            continue
        result[key] = _parse_scalar_or_list(value_text, source, line_no)
        i += 1
    return result


def _split_key_value(line: str, source: str, line_no: int) -> tuple[str, str]:
    if ":" not in line:
        raise _refuse(source, line_no, f"expected 'key: value', found {line!r}")
    key, _, rest = line.partition(":")
    key = key.strip()
    if not key or not all(ch.isalnum() or ch in "_-" for ch in key):
        raise _refuse(source, line_no, f"invalid key {key!r}")
    return key, rest.strip()


def _parse_nested_mapping(lines: list[str], start: int, source: str) -> tuple[dict[str, Any], int]:
    nested: dict[str, Any] = {}
    i = start
    n = len(lines)
    saw_any = False
    while i < n:
        raw_line = lines[i]
        if not raw_line.strip():
            i += 1
            continue
        if not raw_line.startswith("  ") or raw_line[2:3] in (" ", "\t"):
            break
        inner = raw_line[2:]
        if inner and inner[0] in " \t":
            raise _refuse(source, i + 1, "only one level of mapping nesting is supported")
        key, value_text = _split_key_value(inner, source, i + 1)
        if value_text == "":
            raise _refuse(source, i + 1, "only one level of mapping nesting is supported")
        nested[key] = _parse_scalar_or_list(value_text, source, i + 1)
        saw_any = True
        i += 1
    if not saw_any:
        raise _refuse(source, start, "a key with nothing after it must introduce a one-level mapping")
    return nested, i


def _parse_scalar_or_list(value_text: str, source: str, line_no: int) -> Any:
    if value_text.startswith("[") :
        return _parse_flow_list(value_text, source, line_no)
    if value_text.startswith("{"):
        raise _refuse(source, line_no, "flow-style mappings ('{...}') are not supported")
    if value_text.startswith("&") or value_text.startswith("*"):
        raise _refuse(source, line_no, "YAML anchors and aliases are not supported")
    if value_text.startswith("-"):
        raise _refuse(source, line_no, "a list item at this position is not supported")
    return _parse_scalar(value_text, source, line_no)


def _parse_flow_list(value_text: str, source: str, line_no: int) -> list[str]:
    if not value_text.endswith("]"):
        raise _refuse(source, line_no, f"unterminated flow list: {value_text!r}")
    inner = value_text[1:-1].strip()
    if not inner:
        return []
    items = [item.strip() for item in inner.split(",")]
    parsed_items = []
    for item in items:
        if not item:
            raise _refuse(source, line_no, f"empty item in flow list: {value_text!r}")
        parsed = _parse_scalar(item, source, line_no)
        if not isinstance(parsed, str):
            raise _refuse(source, line_no, f"only strings are supported inside a flow list: {item!r}")
        parsed_items.append(parsed)
    return parsed_items


def _parse_scalar(value_text: str, source: str, line_no: int) -> Any:
    if value_text == "true":
        return True
    if value_text == "false":
        return False
    if value_text.startswith('"'):
        return _parse_quoted(value_text, '"', source, line_no)
    if value_text.startswith("'"):
        return _parse_quoted(value_text, "'", source, line_no)
    if value_text == "null" or value_text == "~":
        raise _refuse(source, line_no, "null values are not supported")
    if _looks_like_number(value_text):
        raise _refuse(source, line_no, f"numeric values are not supported: {value_text!r}")
    return value_text


def _parse_quoted(value_text: str, quote: str, source: str, line_no: int) -> str:
    if len(value_text) < 2 or not value_text.endswith(quote):
        raise _refuse(source, line_no, f"unterminated quoted string: {value_text!r}")
    return value_text[1:-1]


def _looks_like_number(value_text: str) -> bool:
    try:
        float(value_text)
    except ValueError:
        return False
    return True


def _refuse(source: str, line_no: int, reason: str) -> FrontmatterError:
    return FrontmatterError(f"{source}:{line_no}: {reason}")
