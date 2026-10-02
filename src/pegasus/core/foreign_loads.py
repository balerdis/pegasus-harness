"""Evaluating and wording what a CLI reads that belongs to another CLI.

The adapter declares the fact (`types.ForeignLoad`); this module answers, for
the machine in front of it, whether the load is actually going to happen, and
words it the same way for `doctor` and for the `install`/`update` report --
one source of text, so the two can never disagree. Nothing here names a CLI:
owner, path and variable all come from the declaration.

Existence and counts only. No file declared here is ever opened.
"""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pegasus.core.types import ForeignLoad
from pegasus.ports.filesystem import FileSystem, FileSystemError

_TRUTHY = frozenset({"1", "true", "yes", "on"})

# A skills directory is a shallow tree in practice; the cap keeps a symlink
# loop from turning a diagnostic into a hang.
_MAX_DEPTH = 6


def _is_set(variables: Mapping[str, str], name: str) -> bool:
    return str(variables.get(name, "")).strip().lower() in _TRUTHY


def _count_entries(filesystem: FileSystem, directory: Path, entry_file: str, depth: int = 0) -> int:
    if depth > _MAX_DEPTH:
        return 0
    try:
        names = filesystem.list_dir(directory)
    except FileSystemError:
        return 0
    total = 0
    for name in names:
        child = directory / name
        if name == entry_file:
            total += 1
            continue
        try:
            is_directory = filesystem.resolves_to_directory(child)
        except FileSystemError:
            continue
        if is_directory:
            total += _count_entries(filesystem, child, entry_file, depth + 1)
    return total


def evaluate(
    filesystem: FileSystem,
    home: Path,
    variables: Mapping[str, str],
    loads: tuple[ForeignLoad, ...],
) -> list[dict[str, Any]]:
    """The declared loads that are going to happen right now, as report entries.

    `variables` is the environment of the process asking -- see `notice_lines`
    for why that is a caveat the wording itself carries.
    """
    active: list[dict[str, Any]] = []
    for load in loads:
        if any(_is_set(variables, name) for name in load.disabled_by):
            continue
        try:
            if any(filesystem.exists(home / relative) for relative in load.superseded_by):
                continue
            target = home / load.path
            if load.entry_file is None:
                if not filesystem.exists(target):
                    continue
                count = None
            else:
                count = _count_entries(filesystem, target, load.entry_file)
                if count == 0:
                    continue
        except FileSystemError:
            continue
        entry: dict[str, Any] = {
            "kind": load.kind,
            "owner": load.owner,
            "path": load.path,
            "disabled_by": list(load.disabled_by),
            "superseded_by": list(load.superseded_by),
            "own_takes_precedence": load.own_takes_precedence,
        }
        if count is not None:
            entry["count"] = count
        active.append(entry)
    return active


def notice_lines(
    entries: list[dict[str, Any]], *, cli_name: str, program_name: str, product_name: str
) -> list[str]:
    """The notice for a person, one line per load plus the environment caveat.

    Empty when there is nothing to say.
    """
    if not entries:
        return []
    lines: list[str] = []
    for entry in entries:
        switches = entry["disabled_by"]
        turn_off = f"Set {switches[0]}=1 to turn that off"
        if len(switches) > 1:
            turn_off += f" ({', '.join(f'{name}=1' for name in switches[1:])} does too)"
        turn_off += "."
        if entry["kind"] == "instructions":
            alternative = entry["superseded_by"]
            reason = f" (there is no ~/{alternative[0]})" if alternative else ""
            lines.append(
                f"{cli_name} will load {entry['owner']}'s ~/{entry['path']} as global instructions{reason}. "
                f"{turn_off}"
            )
        else:
            count = entry["count"]
            noun = "skill" if count == 1 else "skills"
            precedence = (
                f" A skill of the same name from {product_name} takes precedence."
                if entry.get("own_takes_precedence")
                else ""
            )
            lines.append(
                f"{cli_name} will load {count} {noun} from {entry['owner']}'s ~/{entry['path']}.{precedence} "
                f"{turn_off}"
            )
    lines.append(
        f"This check reads the environment of the shell running {program_name}; {cli_name} launched "
        f"from elsewhere, such as a desktop launcher, may have a different one."
    )
    return lines
