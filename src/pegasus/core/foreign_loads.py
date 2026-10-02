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

# The values the CLI's own boolean flag parser accepts, matched case-sensitively
# and exactly (no trimming): anything else that is set is an error on its side,
# not "false". Mirrored here so the notice can say so instead of guessing.
_TRUTHY = frozenset({"true", "yes", "on", "1", "y"})
_FALSY = frozenset({"false", "no", "off", "0", "n"})

# A skills directory is a shallow tree in practice; the cap keeps a diagnostic
# from walking an absurdly deep tree.
_MAX_DEPTH = 6


def _switch_state(variables: Mapping[str, str], name: str) -> str:
    """`"unset"`, `"on"`, `"off"` or `"invalid"` for one environment variable."""
    value = str(variables.get(name, ""))
    if value == "":
        return "unset"  # not verified how the CLI reads an empty value; never claim it is wrong
    if value in _TRUTHY:
        return "on"
    if value in _FALSY:
        return "off"
    return "invalid"


def _count_entries(filesystem: FileSystem, directory: Path, entry_file: str, depth: int = 0) -> int:
    """Regular files named `entry_file` under `directory`.

    The filesystem port cannot resolve a real path, so there is no visited
    set; instead a symlinked directory is followed only when it is a direct
    child of the scanned root (the common layout: each skill linked in from
    elsewhere) and never deeper. That bounds a loop to one extra pass rather
    than an exponential walk, at the price of undercounting skills reached
    through a link nested below the top level, which a glob that follows links
    at any depth would find. A directory that happens to be named like the
    entry file is not an entry.
    """
    if depth > _MAX_DEPTH:
        return 0
    try:
        names = filesystem.list_dir(directory)
    except FileSystemError:
        return 0
    total = 0
    for name in names:
        child = directory / name
        try:
            is_directory = filesystem.resolves_to_directory(child)
            if is_directory and depth > 0 and filesystem.is_symlink(child):
                continue
        except FileSystemError:
            continue
        if is_directory:
            total += _count_entries(filesystem, child, entry_file, depth + 1)
        elif name == entry_file:
            total += 1
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
        states = {name: _switch_state(variables, name) for name in load.disabled_by}
        if "on" in states.values():
            continue
        invalid = [
            {"name": name, "value": str(variables[name])}
            for name, state in states.items()
            if state == "invalid"
        ]
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
        if invalid:
            entry["invalid_switches"] = invalid
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
            turn_off += f" ({', '.join(f'{name}=1' for name in switches[1:])} {'do' if len(switches) > 2 else 'does'} too)"
        turn_off += "."
        for item in entry.get("invalid_switches", []):
            turn_off += (
                f" {item['name']} is set to {item['value']!r}, which {cli_name} does not accept "
                f"(it takes {', '.join(sorted(_TRUTHY))} or {', '.join(sorted(_FALSY))}, "
                f"in lowercase), so it does not turn this off."
            )
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
