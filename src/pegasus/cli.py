"""The flags: everything Pegasus can do without a person watching.

The architecture sets one rule here — the TUI must not be able to do anything
these flags cannot. That is what makes an agent-driven installation possible,
and it means this module is a contract rather than a convenience. Its JSON is
versioned for the same reason the other contracts are.

Two properties matter more than the surface area.

**It asks before it does.** An installation that cannot be recorded is an
installation nobody can uninstall, so the journal is asked whether it could be
written *before* the first artifact is placed. If the recording fails anyway,
the install is taken back out rather than left as a home the engine no longer
recognises.

**It reports what happened, including the parts nobody wants.** Collisions,
artifacts the user edited, list items that can no longer be accounted for — an
agent reading this output has no other way to find out.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

import pegasus
from pegasus.adapters import available
from pegasus.core import catalog as catalog_module
from pegasus.core import content as content_module
from pegasus.core import journal as journal_module
from pegasus.core import ownership, planner, pointer
from pegasus.core.journal import Install, Record
from pegasus.core.types import Codec, Environment
from pegasus.infra.fs_posix import PosixFileSystem
from pegasus.infra.journal_store_file import FileJournalStore
from pegasus.ports.filesystem import FileSystem, FileSystemError
from pegasus.ports.journal_store import JournalStoreError

SCHEMA = "pegasus/cli-report/v1"

OK = 0
FAILED = 1


class CommandError(Exception):
    """Something the user needs to know about, phrased for them rather than raised at them."""


@dataclass(frozen=True)
class Runtime:
    """Everything the commands touch that is not their own logic.

    Injected rather than reached for, so the whole surface can be driven against
    an in-memory home and a fixed clock.
    """

    filesystem: FileSystem
    home: Path
    now: str
    out: TextIO
    variables: dict[str, str] = field(default_factory=dict)

    @property
    def environment(self) -> Environment:
        return Environment(home=self.home, variables=self.variables)


def default_runtime(out: TextIO) -> Runtime:
    import os

    return Runtime(
        filesystem=PosixFileSystem(),
        home=Path.home(),
        now=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        out=out,
        variables=dict(os.environ),
    )


def journal_store(runtime: Runtime) -> FileJournalStore:
    return FileJournalStore(runtime.filesystem, home=runtime.home, pegasus_version=pegasus.__version__)


# --- Entry point -----------------------------------------------------------


def main(argv: list[str] | None = None, *, runtime: Runtime | None = None) -> int:
    import sys

    runtime = runtime or default_runtime(sys.stdout)
    parser = _parser()
    arguments = parser.parse_args(argv)
    if arguments.command is None:
        parser.print_usage(runtime.out)
        return FAILED

    try:
        report = COMMANDS[arguments.command](arguments, runtime)
        code = OK
    except (CommandError, JournalStoreError, planner.PlannerError, FileSystemError) as error:
        report = {"status": "failed", "error": str(error), **getattr(error, "report", {})}
        code = FAILED

    report = {"schema": SCHEMA, "command": arguments.command, **report}
    if arguments.json:
        runtime.out.write(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    else:
        runtime.out.write(_prose(report) + "\n")
    return code


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pegasus", description=__doc__.splitlines()[0])
    # Accepted on either side of the subcommand. The subparsers suppress their
    # default so an absent flag there cannot overwrite one given here.
    parser.add_argument("--json", action="store_true", help="report as a machine-readable document")
    commands = parser.add_subparsers(dest="command")

    install = commands.add_parser("install", help="place Pegasus into one CLI's configuration")
    install.add_argument("--cli", required=True)
    install.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    install.add_argument("--dry-run", action="store_true", help="report the plan without writing anything")

    uninstall = commands.add_parser("uninstall", help="take Pegasus back out of one CLI")
    uninstall.add_argument("--cli", required=True)
    uninstall.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)

    doctor = commands.add_parser("doctor", help="what is supported, what is present, what has drifted")
    doctor.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    return parser


# --- Commands --------------------------------------------------------------


def _install(arguments, runtime: Runtime) -> dict[str, Any]:
    adapter = _adapter(arguments.cli)
    environment = runtime.environment
    _require_present(adapter, environment)

    # The whole preflight, before the first artifact rather than after the last.
    # Writable is only half of it: a journal that cannot be read is one that
    # cannot be extended, and finding that out after placing the artifacts would
    # leave them on disk with nothing recording them — and `doctor` failing
    # against the same unreadable journal, so no way left to find out they exist.
    store = journal_store(runtime)
    store.ensure_writable()
    journal = store.load()

    catalog = catalog_module.build(content_module.load(), adapter, environment)
    artifacts = catalog_module.render(content_module.load(), adapter, environment)
    plan = planner.plan(runtime.filesystem, cli=adapter.id, artifacts=artifacts)

    if arguments.dry_run:
        return {
            "cli": adapter.id,
            "status": "planned",
            "created": [_placed(step) for step in plan.creations],
            "skipped": [_left(step) for step in plan.collisions],
        }

    # Which configuration files were already there. Retiring gives back the keys
    # Pegasus owns, never the file itself, so this is how a rollback can tell the
    # user what it could not take back.
    documents = {step.artifact.path for step in plan.creations if step.artifact.id and _is_key(step)}
    existing = {path for path in documents if runtime.filesystem.exists(path)}

    applied = planner.apply(runtime.filesystem, plan, at=runtime.now)
    config_dir = adapter.layout(environment).config_dir

    # Two views of the same install, and confusing them is expensive. The merged
    # one is what gets recorded: everything this CLI owns, old and new. The
    # placed one is only what this run wrote, and it is the only thing a rollback
    # may touch — undoing the merged view would delete a working installation
    # that this run never even created.
    placed = Install(
        cli=adapter.id, installed_at=runtime.now, config_dir=config_dir, release={}, entries=applied.records
    )
    merged = _merged(journal, adapter, environment, catalog, applied.records, runtime.now)
    try:
        store.save(journal_module.with_install(journal, merged))
    except JournalStoreError as error:
        planner.retire(runtime.filesystem, placed)
        left = sorted(str(path) for path in documents - existing if runtime.filesystem.exists(path))
        raise _unrecordable(error, left, placed=len(applied.records)) from error

    return {
        "cli": adapter.id,
        "status": "installed",
        "placed": len(applied.records),
        "created": [_recorded(record) for record in applied.records],
        "skipped": [_left(step) for step in applied.skipped],
        "journal": str(store.path),
    }


def _merged(journal, adapter, environment, catalog, records, now: str) -> Install:
    """Add what this run placed to what earlier runs already owned.

    Replacing the record instead of extending it is how an install becomes
    unownable: the second run creates nothing, because everything it wanted is
    already there — its own work from the first run — and writing that empty
    result over the journal would orphan every artifact permanently. What the
    engine already owns stays owned.
    """
    previous = journal_module.install_for(journal, adapter.id)
    entries = records
    if previous is not None:
        placed = {record.id for record in records}
        entries = tuple(entry for entry in previous.entries if entry.id not in placed) + tuple(records)
    return Install(
        cli=adapter.id,
        # The date Pegasus first landed here, not the date it was topped up.
        installed_at=previous.installed_at if previous is not None else now,
        config_dir=adapter.layout(environment).config_dir,
        release={"version": pegasus.__version__, "catalog_digest": catalog.digest},
        entries=entries,
        links=previous.links if previous is not None else (),
    )


def _uninstall(arguments, runtime: Runtime) -> dict[str, Any]:
    adapter = _adapter(arguments.cli)
    store = journal_store(runtime)
    store.ensure_writable()

    journal = store.load()
    install = journal_module.install_for(journal, adapter.id)
    if install is None:
        raise CommandError(f"Pegasus is not recorded as installed in {adapter.id!r}; there is nothing to take back")

    retired = planner.retire(runtime.filesystem, install)
    store.save(journal_module.without_install(journal, adapter.id))
    return {
        "cli": adapter.id,
        "status": "uninstalled",
        "removed": list(retired.removed),
        "restored": list(retired.restored),
        "preserved": list(retired.preserved),
        "unaccounted": list(retired.unaccounted),
        "kept_links": list(retired.kept_links),
    }


def _doctor(arguments, runtime: Runtime) -> dict[str, Any]:
    environment = runtime.environment
    registry = available()
    journal = journal_store(runtime).load()
    return {
        "pegasus_version": pegasus.__version__,
        "clis": [_health(registry.get(cli_id), environment, journal, runtime) for cli_id in registry.ids()],
    }


def _health(adapter, environment: Environment, journal, runtime: Runtime) -> dict[str, Any]:
    detection = adapter.detect(environment)
    install = journal_module.install_for(journal, adapter.id)
    health: dict[str, Any] = {
        "cli": adapter.id,
        "display_name": adapter.display_name,
        "tier": adapter.tier().value,
        "detected": bool(detection.installed or detection.config_found),
        "config_dir": str(detection.config_dir) if detection.config_dir else None,
        "pegasus_installed": install is not None,
        "artifacts": len(install.entries) if install else 0,
        "drifted": [],
        "missing": [],
    }
    if install is None:
        return health

    for entry in install.entries:
        current = _current_digest(runtime.filesystem, entry)
        if current is None:
            health["missing"].append(entry.id)
        elif current != entry.after_digest:
            health["drifted"].append(entry.id)
    return health


def _current_digest(filesystem: FileSystem, entry: Record) -> str | None:
    """What the artifact hashes to right now, or ``None`` if it is not there."""
    if not filesystem.exists(entry.target):
        return None
    if entry.kind == "file":
        return ownership.digest_of_bytes(filesystem.read_bytes(entry.target))

    document = _document(filesystem, entry)
    address = entry.pointer or ""
    if address.endswith(planner.APPEND):
        items = pointer.get_at(document, address[: -len(planner.APPEND)])
        if not isinstance(items, list):
            return None
        found = next((item for item in items if ownership.digest_of_value(item) == entry.after_digest), None)
        return entry.after_digest if found is not None else None
    if not pointer.exists_at(document, address):
        return None
    return ownership.digest_of_value(pointer.get_at(document, address))


def _document(filesystem: FileSystem, entry: Record):
    from pegasus.core import codecs

    try:
        return codecs.loads(Codec(entry.codec or Codec.JSON.value), filesystem.read_bytes(entry.target).decode("utf-8"))
    except (UnicodeDecodeError, codecs.CodecError) as error:
        raise CommandError(f"{entry.target} cannot be parsed, so nothing in it can be judged: {error}") from error


COMMANDS = {"install": _install, "uninstall": _uninstall, "doctor": _doctor}


# --- Shaping the report ----------------------------------------------------


def _adapter(cli_id: str):
    registry = available()
    if cli_id not in registry:
        raise CommandError(f"{cli_id!r} is not a CLI this release supports; try one of: {', '.join(registry.ids())}")
    return registry.get(cli_id)


def _require_present(adapter, environment: Environment) -> None:
    detection = adapter.detect(environment)
    if detection.installed or detection.config_found:
        return
    raise CommandError(
        f"{adapter.display_name} was not found on this machine, and installing into a CLI that is not "
        f"here would only leave files nothing reads"
    )


def _is_key(step: planner.Step) -> bool:
    return getattr(step.artifact, "pointer", None) is not None


def _unrecordable(error: JournalStoreError, left_behind: list[str], *, placed: int) -> CommandError:
    """The install came back out. Say so, and say what did not come with it.

    ``undone`` is false when this run placed nothing — a reinstall where
    everything already existed — because then there was nothing to take back and
    saying otherwise would invent an event. Pegasus owns keys inside a
    configuration file, never the file itself, so a file it had to create to hold
    them survives the rollback as an empty document. Harmless, but claiming a
    clean undo would be a small lie in the one report a user reads when something
    already went wrong.
    """
    undone = placed > 0
    if undone:
        message = (
            f"the artifacts were placed but the journal could not be written, so they were taken back out "
            f"rather than left unrecorded: {error}"
        )
    else:
        message = f"nothing needed placing, and the journal could not be written anyway: {error}"
    if left_behind:
        message += f". Left behind, empty: {', '.join(left_behind)}"
    failure = CommandError(message)
    failure.report = {"placed": placed, "rolled_back": undone, "left_behind": left_behind}
    return failure


def _placed(step: planner.Step) -> dict[str, Any]:
    return {"id": step.artifact.id, "target": str(step.artifact.path)}


def _recorded(record: Record) -> dict[str, Any]:
    return {"id": record.id, "kind": record.kind, "target": str(record.target)}


def _left(step: planner.Step) -> dict[str, Any]:
    return {"id": step.artifact.id, "target": str(step.artifact.path), "reason": step.reason}


def _prose(report: dict[str, Any]) -> str:
    """The same facts, for a person. Never a subset of them."""
    if report.get("status") == "failed":
        if report.get("rolled_back"):
            return f"The installation was undone. {report['error']}"
        return f"Nothing was changed. {report['error']}"

    command = report["command"]
    if command == "doctor":
        return "\n".join(_cli_prose(entry) for entry in report["clis"])
    if command == "install":
        verb = "would create" if report["status"] == "planned" else "created"
        lines = [f"{report['cli']}: {verb} {len(report['created'])} artifacts, skipped {len(report['skipped'])}."]
        if report["skipped"]:
            lines.append("Left alone because something was already there:")
            lines.extend(f"  {item['id']} → {item['target']}" for item in report["skipped"])
        return "\n".join(lines)

    lines = [f"{report['cli']}: removed {len(report['removed'])}, restored {len(report['restored'])}."]
    for label, key in (
        ("Left alone because you changed them", "preserved"),
        ("Could not be accounted for", "unaccounted"),
    ):
        if report[key]:
            lines.append(f"{label}: {', '.join(report[key])}")
    return "\n".join(lines)


def _cli_prose(entry: dict[str, Any]) -> str:
    if not entry["detected"]:
        return f"{entry['display_name']}: not found on this machine."
    if not entry["pegasus_installed"]:
        return f"{entry['display_name']}: present at {entry['config_dir']}, Pegasus not installed."
    line = f"{entry['display_name']}: {entry['artifacts']} artifacts installed at {entry['config_dir']}."
    for label, key in (("changed by hand", "drifted"), ("missing", "missing")):
        if entry[key]:
            line += f" {len(entry[key])} {label}: {', '.join(entry[key])}."
    return line
