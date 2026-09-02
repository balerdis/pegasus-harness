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
import shutil
import sys
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, TextIO

import pegasus
from pegasus.adapters import available
from pegasus.core import catalog as catalog_module
from pegasus.core import content as content_module
from pegasus.core import dependencies as dependencies_module
from pegasus.core import journal as journal_module
from pegasus.core import model_assignments as model_assignments_module
from pegasus.core import ownership, planner, pointer
from pegasus.core.journal import KINDS, Install, Record
from pegasus.core import mcp_handshake
from pegasus.core.types import Capability, Codec, Environment, ModelAssignment
from pegasus.infra.downloader_http import HttpDownloader
from pegasus.infra.fs_posix import PosixFileSystem
from pegasus.infra.journal_store_file import FileJournalStore
from pegasus.infra.mcp_process_subprocess import SubprocessMCPProcess
from pegasus.infra.model_assignment_store_file import FileModelAssignmentStore
from pegasus.infra.npm_installer_subprocess import SubprocessNpmInstaller
from pegasus.infra.snapshot_store_file import FileSnapshotStore, capture_paths
from pegasus.ports.downloader import Downloader
from pegasus.ports.filesystem import FileSystem, FileSystemError
from pegasus.ports.journal_store import JournalStoreError
from pegasus.ports.mcp_process import MCPProcess
from pegasus.ports.model_assignment_store import ModelAssignmentStoreError
from pegasus.ports.npm_installer import NpmInstaller
from pegasus.ports.snapshot_store import SnapshotStoreError
from pegasus.tui import app as tui_app

NODE_BINARY = "node"

SCHEMA = "pegasus/cli-report/v1"

OK = 0
FAILED = 1

# How many generations the retention pass keeps. Not a disk argument — the
# blobs are small — but a decision about how far back the recovery promise
# reaches.
RETAIN_GENERATIONS = 5


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
    downloader: Downloader = field(default_factory=HttpDownloader)
    npm_installer: NpmInstaller = field(default_factory=SubprocessNpmInstaller)
    mcp_process: MCPProcess = field(default_factory=SubprocessMCPProcess)
    mcp_handshake_timeout_seconds: float = mcp_handshake.DEFAULT_TIMEOUT_SECONDS

    @property
    def environment(self) -> Environment:
        return Environment(
            home=self.home, variables=self.variables, data_dir=self.filesystem.data_dir(self.home)
        )


def default_runtime(out: TextIO) -> Runtime:
    import os

    variables = dict(os.environ)
    return Runtime(
        filesystem=PosixFileSystem(variables),
        home=Path.home(),
        now=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        out=out,
        variables=variables,
        downloader=HttpDownloader(),
        npm_installer=SubprocessNpmInstaller(),
        mcp_process=SubprocessMCPProcess(),
    )


def journal_store(runtime: Runtime) -> FileJournalStore:
    return FileJournalStore(runtime.filesystem, home=runtime.home, pegasus_version=pegasus.__version__)


def snapshot_store(runtime: Runtime) -> FileSnapshotStore:
    return FileSnapshotStore(runtime.filesystem, home=runtime.home)


def model_assignment_store(runtime: Runtime) -> FileModelAssignmentStore:
    return FileModelAssignmentStore(runtime.filesystem, home=runtime.home)


# --- Entry point -----------------------------------------------------------


def main(argv: list[str] | None = None, *, runtime: Runtime | None = None) -> int:
    runtime = runtime or default_runtime(sys.stdout)
    parser = _parser()
    arguments = parser.parse_args(argv)
    if arguments.command is None:
        # Asking for nothing in particular, at a terminal, is asking for the
        # menu. Piped or redirected there is no menu to show and no one to
        # read it, so the usage line is still the honest answer -- and it is
        # what a script that called this by mistake needs to see.
        if _attached_to_a_terminal():
            tui_app.main()
            return OK
        parser.print_usage(runtime.out)
        return FAILED

    code, report = safe_report(arguments.command, lambda: COMMANDS[arguments.command](arguments, runtime))
    if arguments.json:
        runtime.out.write(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    else:
        runtime.out.write(_prose(report) + "\n")
    return code


#: Every exception a command handler is allowed to let through instead of
#: raising past `main` — an agent's stdin has no traceback to read, only this
#: report.
COMMAND_ERRORS = (
    CommandError,
    JournalStoreError,
    ModelAssignmentStoreError,
    planner.PlannerError,
    FileSystemError,
)


def safe_report(command: str, call: Callable[[], dict[str, Any]]) -> tuple[int, dict[str, Any]]:
    """Run one command handler and shape whatever it returns — or raises —
    into the same versioned report either way.

    This is the one piece of `main` worth calling from outside it: anything
    that wants to reach the engine the same way the flags do — the TUI's
    install screen, chiefly — gets the identical failure handling for free
    instead of reimplementing it, which is what keeps a failure from ever
    reaching a caller as a bare traceback.
    """
    try:
        report = call()
        code = OK
    except COMMAND_ERRORS as error:
        report = {"status": "failed", "error": str(error), **getattr(error, "report", {})}
        code = FAILED
    return code, {"schema": SCHEMA, "command": command, **report}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pegasus", description=__doc__.splitlines()[0])
    # Accepted on either side of the subcommand. The subparsers suppress their
    # default so an absent flag there cannot overwrite one given here.
    parser.add_argument("--json", action="store_true", help="report as a machine-readable document")
    # Answered by the parser and nothing else: no home opened, no journal read,
    # no adapter resolved. The number belongs to the binary, not to any
    # installation of it, and asking for it on a machine whose installation is
    # broken is exactly when it has to still work. It was reachable only
    # through `doctor --json` before, which is a different question entirely
    # and does all of that work to answer it.
    #
    # Unlike `--json` above, this one is NOT repeated on the subparsers, and
    # the asymmetry is the point: `--json` modifies a report, so it belongs
    # wherever the command it modifies is written. A version request modifies
    # nothing — it is its own command — and `pegasus install --cli x --version`
    # printing a number instead of installing would be a surprising way to not
    # install something.
    parser.add_argument(
        "-V", "--version", action="version", version=f"%(prog)s {pegasus.__version__}",
        help="report the version of this binary and exit",
    )
    commands = parser.add_subparsers(dest="command")

    install = commands.add_parser("install", help="place Pegasus into one CLI's configuration")
    install.add_argument("--cli", required=True)
    install.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    install.add_argument("--dry-run", action="store_true", help="report the plan without writing anything")
    install.add_argument(
        "--mcp",
        action="append",
        metavar="ID[=SERVER-KEY]",
        help=(
            "install this mcp server too (repeatable); a server not named here is not "
            "installed. Give it as ID=SERVER-KEY to bind it to a server you already "
            "administer under that key: the convention and the tool grants still "
            "arrive, and nothing is fetched or written into the mcp settings for it"
        ),
    )

    uninstall = commands.add_parser("uninstall", help="take Pegasus back out of one CLI")
    uninstall.add_argument("--cli", required=True)
    uninstall.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)

    doctor = commands.add_parser("doctor", help="what is supported, what is present, what has drifted")
    doctor.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    doctor.add_argument(
        "--start-mcp-servers",
        action="store_true",
        help="also launch each configured MCP server and perform the handshake (executes commands; off by default)",
    )

    # No `--cli`: a generation is whatever one command touched, not one CLI's
    # installation, so restoring is never scoped to a CLI the way install and
    # uninstall are.
    restore = commands.add_parser("restore", help="undo the most recent generation, or a specific one")
    restore.add_argument(
        "generation", type=int, nargs="?", default=None,
        help="the generation to restore; defaults to the most recent one that can be read back",
    )
    restore.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)

    models = commands.add_parser("models", help="assign, remove, or list per-agent model preferences")
    models.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    models_commands = models.add_subparsers(dest="models_command")

    set_parser = models_commands.add_parser("set", help="assign a model to one agent")
    set_parser.add_argument("--cli", required=True)
    set_parser.add_argument("--agent", required=True)
    set_parser.add_argument("--model", required=True, metavar="PROVIDER/MODEL")
    set_parser.add_argument("--effort", default=None)
    set_parser.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)

    unset_parser = models_commands.add_parser("unset", help="remove one agent's model assignment")
    unset_parser.add_argument("--cli", required=True)
    unset_parser.add_argument("--agent", required=True)
    unset_parser.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)

    list_parser = models_commands.add_parser("list", help="show current model assignments")
    list_parser.add_argument("--cli", default=None, help="limit to one CLI; omit to show every CLI")
    list_parser.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    return parser


# --- Commands --------------------------------------------------------------


def _install(arguments, runtime: Runtime) -> dict[str, Any]:
    return install(arguments.cli, runtime, dry_run=arguments.dry_run, mcp=arguments.mcp)


def install(cli_id: str, runtime: Runtime, *, dry_run: bool = False, mcp: list[str] | None = None) -> dict[str, Any]:
    """Place Pegasus into one CLI's configuration, and report what happened.

    This is the engine path itself, parsed flags peeled away: `_install`
    exists only to unpack an `argparse.Namespace` into these three plain
    values, so anything else that wants the same installation — the TUI's
    install screen, not a second implementation of it — calls this directly
    and renders the report it gets back, the same report `--json` would.
    """
    adapter = _adapter(cli_id)
    environment = runtime.environment
    _require_present(adapter, environment)
    # Computed early -- pure arithmetic over `adapter` and `environment`, so
    # nothing is lost by asking for it before the preflight below rather than
    # where `_materialize_dependencies` used to be the first to need it. The
    # pre-write snapshot needs it too, to name a dependency tree's prospective
    # address before that tree exists.
    layout = adapter.layout(environment)

    # The whole preflight, before the first artifact rather than after the last.
    # Writable is only half of it: a journal that cannot be read is one that
    # cannot be extended, and finding that out after placing the artifacts would
    # leave them on disk with nothing recording them — and `doctor` failing
    # against the same unreadable journal, so no way left to find out they exist.
    store = journal_store(runtime)
    store.ensure_writable()
    snapshot = snapshot_store(runtime)
    snapshot.ensure_writable()
    journal = store.load()
    # Asked before anything is written, so an adapter that cannot answer costs a
    # message instead of a traceback over a finished installation.
    activation = list(adapter.activation_steps())

    # One read of the content tree, one application of the user's choice — not
    # two of each. `build` and `render` walk the same content, and reloading
    # for the second would risk handing them two objects that could in
    # principle differ, for no reason beyond having asked disk twice.
    content = _select_mcp(mcp)
    catalog = catalog_module.build(content, adapter)
    model_overrides, model_warnings = _resolve_model_overrides(runtime, adapter, environment, content)
    artifacts = catalog_module.render(content, adapter, environment, model_overrides=model_overrides)
    installed = journal_module.install_for(journal, adapter.id)
    plan = planner.plan(
        runtime.filesystem,
        cli=adapter.id,
        artifacts=artifacts,
        # Already loaded for the preflight. It is what separates an address
        # Pegasus wrote from one the user did, so a reinstall can update its own
        # work instead of colliding with it.
        installed=installed,
    )
    # A `dependency-tree` entry has no artifact of its own for `plan` to
    # compare against -- it is materialized outside the catalog pipeline
    # entirely, below -- so `plan.retirements` cannot tell a server `--mcp`
    # still names from one it does not, and marks every existing one stale
    # regardless. Its answer for every other kind is still the right one, so
    # only that kind is replaced with the answer computed against the
    # servers this run actually kept.
    retirements = tuple(entry for entry in plan.retirements if entry.kind != "dependency-tree") + (
        _stale_dependencies(installed, content)
    )

    if dry_run:
        return {
            "cli": adapter.id,
            "status": "planned",
            "activation": activation,
            "created": [_placed(step) for step in plan.creations],
            "updated": [_placed(step) for step in plan.updates],
            "unchanged": [_placed(step) for step in plan.unchanged],
            "overwritten": [_placed(step) for step in plan.overwritten],
            "skipped": [_left(step) for step in plan.collisions],
            "retired": [_recorded(record) for record in retirements],
            "model_warnings": list(model_warnings),
        }

    # Taken before a single byte of this run reaches disk, and never for a dry
    # run: install and uninstall overwrite what the journal already claims
    # without asking, so a hand edit to an owned artifact would vanish with
    # nothing else remembering it. The journal is captured alongside the
    # artifacts, and not because it happens to live on disk too — restoring
    # the artifacts without it would put the files back while the journal kept
    # claiming the version this run is about to write, so the next install
    # would compare against fingerprints that no longer describe anything on
    # disk.
    # Retirement targets, alongside what this run writes: the mcp key would
    # land in this snapshot by accident, sharing a document with the five
    # updated agent grants, but `context7-convention.md` shares an address
    # with nothing else this run touches. Without naming it here, a `restore`
    # after a retiring reinstall would give back the key and not the file.
    #
    # A `dependency-tree` target is a directory, not a file -- `capture_paths`
    # reads a path's bytes whole, and a directory has none to read, so an
    # already-materialized tree stays out of every snapshot the way it always
    # has (see `_stale_dependencies` and the exclusion above). A tree this run
    # is *about* to materialize is different: at this point it has no bytes
    # yet at all, existing or otherwise, so capturing "this did not exist" is
    # exactly the ordinary absent-path case `capture_paths` already handles.
    # That is narrow -- it only ever lets `restore` remove a tree, never put
    # one back -- but it is what closes the hole a failed materialization
    # used to leave open: nothing before this call to `apply` catches a
    # failure there and takes the tree back out.
    dependency_targets = _prospective_dependency_targets(runtime, layout, content, installed)
    touched = sorted(
        {step.artifact.path for step in plan.placements}
        | {record.target for record in retirements if record.kind != "dependency-tree"}
        | {store.path}
        | dependency_targets,
        key=str,
    )
    try:
        snapshot.save(
            capture_paths(runtime.filesystem, touched, directories=frozenset(dependency_targets)),
            taken_at=runtime.now,
        )
    except SnapshotStoreError as error:
        raise CommandError(
            f"a snapshot of what this install is about to overwrite could not be taken, "
            f"so nothing was written: {error}"
        ) from error

    # Which configuration files were already there. Retiring gives back the keys
    # Pegasus owns, never the file itself, so this is how a rollback can tell the
    # user what it could not take back.
    documents = {step.artifact.path for step in plan.placements if step.artifact.id and _is_key(step)}
    existing = {path for path in documents if runtime.filesystem.exists(path)}

    # Fetched, verified and placed before anything else this run writes: a
    # `download` or `npm` server has no artifact for `plan` to have already
    # decided the fate of, so this is the one part of an install `planner`
    # never sees. A mismatch here raises before a single byte reaches disk,
    # so the whole install fails exactly as cleanly as a collision would.
    try:
        kept_dependencies, new_dependencies = _materialize_dependencies(runtime, layout, content, installed)
    except dependencies_module.MaterializeError as error:
        raise CommandError(str(error)) from error

    applied = planner.apply(runtime.filesystem, plan, at=runtime.now)
    config_dir = layout.config_dir
    dependency_records = kept_dependencies + new_dependencies
    all_records = applied.records + dependency_records

    # Two views of the same install, and confusing them is expensive. The merged
    # one is what gets recorded: everything this CLI owns, old and new. The
    # placed one is only what this run wrote, and it is the only thing a rollback
    # may touch — undoing the merged view would delete a working installation
    # that this run never even created.
    placed = Install(
        cli=adapter.id, installed_at=runtime.now, config_dir=config_dir, release={}, entries=all_records
    )

    # What this render no longer asks for goes back out now: after `apply`,
    # which already wrote the same configuration document with the five
    # updated agent grants, so retiring first would read a stale copy and
    # clobber them on the write-back; and before the journal is saved, because
    # a journal that still claims a key this run just removed is the exact
    # orphaning `_merged` exists to prevent.
    #
    # `retire` sits in its own `try` rather than falling through to the one
    # around `store.save`, because a failure here is a different event: this
    # run's own placements are already on disk, unrecorded, and the journal
    # was never even asked to save — the generic handler in `main` would
    # otherwise report it as if nothing had happened. Rolling this run's
    # placements back is safe to do unconditionally: `retire`'s own docstring
    # promises every operation is a no-op the second time, so whatever it
    # already removed before failing stays removed, and a later run finishes
    # retiring the rest — there is nothing here for `unplace` to undo except
    # this run's own placements.
    try:
        stale = planner.retire(runtime.filesystem, replace(placed, entries=retirements))
    except (FileSystemError, planner.PlannerError) as error:
        removed, failures = _undo_placements(runtime.filesystem, applied, placed)
        _undo_dependencies(runtime.filesystem, new_dependencies)
        left = _left_behind(runtime.filesystem, documents - existing)
        raise _unretirable(
            error,
            left,
            placed=len(applied.records),
            replaced=len(applied.replaced),
            failures=failures,
            removed=removed,
        ) from error

    # `applied.reconciled` joins the journal here and nowhere else. It never
    # reaches `placed` above, and that is the whole point of keeping the two
    # tuples apart: `placed` is what a rollback may take away, and a
    # reconciliation is an artifact this run never wrote -- offering it to
    # `unplace` would delete a correct file to undo a write that never
    # happened. It never reaches the report either, for the milder version of
    # the same reason: nothing was written, so nothing may be counted as
    # written. What it does do is let the journal finally agree with the disk,
    # so `doctor` stops reporting a drift no run could ever clear.
    merged = _merged(
        journal, adapter, environment, catalog, all_records + applied.reconciled, stale.removed, runtime.now
    )
    try:
        store.save(journal_module.with_install(journal, merged))
    except JournalStoreError as error:
        removed, failures = _undo_placements(runtime.filesystem, applied, placed)
        _undo_dependencies(runtime.filesystem, new_dependencies)
        left = _left_behind(runtime.filesystem, documents - existing)
        raise _unrecordable(
            error,
            left,
            placed=len(applied.records),
            replaced=len(applied.replaced),
            failures=failures,
            removed=removed,
            retired=list(stale.removed),
        ) from error

    # `kept_dependencies` were not touched this run at all -- the version and
    # checksum already on disk are the ones this release still asks for, so
    # they are reported alongside everything else that needed no write,
    # never as an "update" that did not happen.
    reported = applied.records + new_dependencies
    created_ids = {step.artifact.id for step in plan.creations} | {record.id for record in new_dependencies}
    retired_ids = set(stale.removed)
    return {
        "cli": adapter.id,
        "status": "installed",
        "activation": activation,
        "placed": len(all_records),
        "created": [_recorded(record) for record in reported if record.id in created_ids],
        "updated": [_recorded(record) for record in reported if record.id not in created_ids],
        "unchanged": [_placed(step) for step in applied.unchanged] + [_recorded(r) for r in kept_dependencies],
        # What the journal claims is rewritten without asking — that policy
        # stands. This is the half it never settled: whether the person finds
        # out. Named at the moment the edit is spent, which is the only moment
        # they can still do something about it.
        "overwritten": [_placed(step) for step in plan.overwritten],
        "skipped": [_left(step) for step in applied.skipped],
        # Filtered to what `retire` actually confirmed removed, not the intent
        # `retirements` describes — an unaccounted entry belongs in
        # `unaccounted`, not here, or the report would claim a removal that
        # never happened.
        "retired": [_recorded(record) for record in retirements if record.id in retired_ids],
        "unaccounted": list(stale.unaccounted),
        "journal": str(store.path),
        "retention": _retain(snapshot),
        "model_warnings": list(model_warnings),
    }


def _resolve_model_overrides(
    runtime: Runtime, adapter, environment: Environment, content: content_module.Content
) -> tuple[dict[str, str], tuple[str, ...]]:
    """Which stored model preferences this install can actually honour.

    Soft failure lives entirely in `model_assignments.resolve_for_render`; this
    is only the plumbing that gathers what it needs. An adapter that never
    declared `per_agent_model` has nothing to resolve and nothing to warn
    about -- the capability was never offered, so a preference for it could
    never have been set through `models set` in the first place.
    """
    if not adapter.capabilities().declares(Capability.PER_AGENT_MODEL):
        return {}, ()
    assignments = model_assignment_store(runtime).load()
    configurable = frozenset(agent.name for agent in content.agents if agent.model_configurable)
    catalog = adapter.model_catalog(environment)
    return model_assignments_module.resolve_for_render(assignments, adapter.id, configurable, catalog)


def _merged(journal, adapter, environment, catalog, records, retired_ids, now: str) -> Install:
    """Add what this run placed to what earlier runs already owned.

    Replacing the record instead of extending it is how an install becomes
    unownable: the second run creates nothing, because everything it wanted is
    already there — its own work from the first run — and writing that empty
    result over the journal would orphan every artifact permanently. What the
    engine already owns stays owned.

    ``retired_ids`` is threaded in rather than recomputed here on purpose: this
    function cannot tell "not re-placed because it was already correct" apart
    from "not re-placed because the user stopped asking for it" on its own —
    that distinction is what `retire()` actually confirmed removed
    (`Retired.removed`), not `plan.retirements`, which is only the intent. An
    id `retire()` could not account for stays out of ``retired_ids``, so its
    record survives this merge and a later run can still finish the job for
    it. Dropping the ids that *were* confirmed is what keeps a retired entry
    from being merged straight back in as if this run had never stopped
    asking for it.
    """
    previous = journal_module.install_for(journal, adapter.id)
    entries = records
    if previous is not None:
        dropped = {record.id for record in records} | set(retired_ids)
        entries = tuple(entry for entry in previous.entries if entry.id not in dropped) + tuple(records)
    return Install(
        cli=adapter.id,
        # The date Pegasus first landed here, not the date it was topped up.
        installed_at=previous.installed_at if previous is not None else now,
        config_dir=adapter.layout(environment).config_dir,
        release={"version": pegasus.__version__, "catalog_digest": catalog.digest},
        entries=entries,
        links=previous.links if previous is not None else (),
    )


#: Distributions whose materialized tree lives outside the catalog pipeline
#: entirely, so `_materialize_dependencies` and `_stale_dependencies` both
#: have to reason about them directly.
_MATERIALIZED_DISTRIBUTIONS = frozenset({content_module.Distribution.DOWNLOAD, content_module.Distribution.NPM})


def _materializes(item) -> bool:
    """Whether Pegasus fetches and places this server itself.

    Two reasons it might not, and they differ in kind. A `remote` server has
    nothing to place. A bound server has something to place and must not: the
    installation already administers it, and a second copy is how two versions
    end up opening one store -- which for a cache costs a reindex, and for a
    memory database costs the memories.

    One function rather than the same condition written in three places,
    because the three have to agree: what gets fetched, what gets retired, and
    what a pre-write snapshot claims an address for.
    """
    return not item.is_bound and item.distribution in _MATERIALIZED_DISTRIBUTIONS


def _stale_dependencies(installed: Install | None, content: content_module.Content) -> tuple[Record, ...]:
    """`download` and `npm` servers this render no longer names.

    The counterpart to `planner.retirements` for a kind that function never
    sees: a `dependency-tree` entry has no artifact in `artifacts` for it to
    compare against, so this asks the same question directly against the
    servers `--mcp` chose for this run instead — already filtered to exactly
    those by `select_mcp`.
    """
    if installed is None:
        return ()
    wanted = {f"dependency:{item.name}" for item in content.mcp if _materializes(item)}
    return tuple(
        entry for entry in installed.entries if entry.kind == "dependency-tree" and entry.id not in wanted
    )


def _prospective_dependency_targets(
    runtime: Runtime, layout, content: content_module.Content, installed: Install | None
) -> set[Path]:
    """Where a `download` or `npm` server would land, for every one this run
    is about to materialize fresh.

    Asked before `_materialize_dependencies` runs, so the pre-write snapshot
    can name a tree's address while it still has nothing there to read — the
    one moment `capture_paths` can honestly say something about a directory.
    The "already kept, nothing to materialize" half of that function's own
    decision is repeated here rather than shared with it, because sharing
    would mean returning `kept` and `created` from a function that has not
    fetched anything yet to decide between them.
    """
    owned = {entry.id: entry for entry in (installed.entries if installed else ())}
    targets: set[Path] = set()
    for item in content.mcp:
        if not _materializes(item):
            continue
        digest = item.checksum if item.distribution is content_module.Distribution.DOWNLOAD else item.integrity
        existing = owned.get(f"dependency:{item.name}")
        if existing is not None and existing.after_digest == digest and runtime.filesystem.exists(existing.target):
            continue
        targets.add(dependencies_module.target_dir(layout.dependencies_dir, item))
    return targets


def _materialize_dependencies(
    runtime: Runtime, layout, content: content_module.Content, installed: Install | None
) -> tuple[tuple[Record, ...], tuple[Record, ...]]:
    """Fetch and place every `download` or `npm` server this run still names.

    Returns ``(kept, created)``: a server already materialized at exactly the
    version and digest this release still asks for costs no fetch at all —
    the record the journal already holds is reused as is. Everything else is
    fetched, verified, and placed fresh; a failure here leaves whatever this
    call already placed for a *previous* server on disk, which the caller
    cleans up alongside everything else once it knows the whole install is
    being undone.
    """
    owned = {entry.id: entry for entry in (installed.entries if installed else ())}
    node_present = shutil.which(NODE_BINARY, path=runtime.variables.get("PATH")) is not None
    kept: list[Record] = []
    created: list[Record] = []
    for item in content.mcp:
        if not _materializes(item):
            continue
        digest = item.checksum if item.distribution is content_module.Distribution.DOWNLOAD else item.integrity
        existing = owned.get(f"dependency:{item.name}")
        if (
            existing is not None
            and existing.after_digest == digest
            and runtime.filesystem.exists(existing.target)
        ):
            kept.append(existing)
            continue
        try:
            created.append(_materialize_one(runtime, layout, item, node_present))
        except dependencies_module.MaterializeError:
            # A later server's failure must not leave an earlier one of this
            # same run half-recorded: nothing placed here has reached the
            # journal yet, so this is the only chance to take it back out.
            _undo_dependencies(runtime.filesystem, tuple(created))
            raise
    return tuple(kept), tuple(created)


def _materialize_one(runtime: Runtime, layout, item, node_present: bool) -> Record:
    if item.distribution is content_module.Distribution.DOWNLOAD:
        return dependencies_module.materialize(
            runtime.filesystem, runtime.downloader, layout.dependencies_dir, item, at=runtime.now
        )
    return dependencies_module.materialize_npm(
        runtime.filesystem,
        runtime.npm_installer,
        layout.dependencies_dir,
        item,
        node_present=node_present,
        at=runtime.now,
    )


def _undo_dependencies(filesystem: FileSystem, created: tuple[Record, ...]) -> None:
    """Take back a dependency tree this run just materialized, best-effort.

    Called from inside a handler that is already reporting a first failure —
    same posture as `_left_behind`: a second failure here must never replace
    that report with a worse one, so it is swallowed rather than raised.
    """
    for record in created:
        try:
            filesystem.remove_dir(record.target)
        except FileSystemError:
            continue


def _uninstall(arguments, runtime: Runtime) -> dict[str, Any]:
    return uninstall(arguments.cli, runtime)


def uninstall(cli_id: str, runtime: Runtime) -> dict[str, Any]:
    """Take Pegasus back out of one CLI's configuration, and report what was
    removed — same reasoning as `install`: the TUI's uninstall screen calls
    this directly, the report it gets back the same one `--json` would.
    """
    adapter = _adapter(cli_id)
    store = journal_store(runtime)
    store.ensure_writable()
    snapshot = snapshot_store(runtime)
    snapshot.ensure_writable()

    journal = store.load()
    activation = list(adapter.activation_steps())
    install = journal_module.install_for(journal, adapter.id)
    if install is None:
        raise CommandError(f"Pegasus is not recorded as installed in {adapter.id!r}; there is nothing to take back")

    # Same reasoning as install, in reverse: retiring overwrites what the
    # journal claims without asking, and the journal itself is captured
    # alongside the targets being retired for the same reason it is on the
    # way in. A `dependency-tree` target is a directory -- see the matching
    # note in `_install` -- so it is excluded here for the same reason.
    touched = sorted(
        {entry.target for entry in install.entries if entry.kind != "dependency-tree"} | {store.path}, key=str
    )
    try:
        snapshot.save(capture_paths(runtime.filesystem, touched), taken_at=runtime.now)
    except SnapshotStoreError as error:
        raise CommandError(
            f"a snapshot of what this uninstall is about to remove could not be taken, "
            f"so nothing was removed: {error}"
        ) from error

    retired = planner.retire(runtime.filesystem, install)
    store.save(journal_module.without_install(journal, adapter.id))
    return {
        "cli": adapter.id,
        "status": "uninstalled",
        "activation": activation,
        "removed": list(retired.removed),
        "unaccounted": list(retired.unaccounted),
        "kept_links": list(retired.kept_links),
        "retention": _retain(snapshot),
    }


def _models(arguments, runtime: Runtime) -> dict[str, Any]:
    if arguments.models_command == "set":
        return models_set(arguments.cli, arguments.agent, arguments.model, runtime, effort=arguments.effort)
    if arguments.models_command == "unset":
        return models_unset(arguments.cli, arguments.agent, runtime)
    if arguments.models_command == "list":
        return models_list(runtime, cli_id=arguments.cli)
    raise CommandError("models needs a subcommand: set, unset, or list")


def models_set(
    cli_id: str, agent: str, model: str, runtime: Runtime, *, effort: str | None = None
) -> dict[str, Any]:
    """Assign a model to one agent, refusing an assignment nothing will ever read.

    Peeled the same way `install` is: a plain function a future TUI screen can
    call directly, with `_models` doing only the argparse unpacking.
    """
    _adapter(cli_id)
    _require_configurable_agent(agent)
    try:
        assignment = ModelAssignment.parse(model, effort)
    except ValueError as error:
        raise CommandError(str(error)) from error
    store = model_assignment_store(runtime)
    assignments = store.load()
    store.save(model_assignments_module.with_assignment(assignments, cli_id, agent, assignment))
    return {
        "action": "set",
        "cli": cli_id,
        "agent": agent,
        "model": assignment.full_id,
        "effort": assignment.effort,
        "activation": (_NOT_INSTALLED_YET.format(cli=cli_id),),
    }


def models_unset(cli_id: str, agent: str, runtime: Runtime) -> dict[str, Any]:
    """Remove one agent's assignment. Removing one never set is success, not an error."""
    _adapter(cli_id)
    store = model_assignment_store(runtime)
    assignments = store.load()
    if model_assignments_module.get(assignments, cli_id, agent) is None:
        return {"action": "unset", "cli": cli_id, "agent": agent, "status": "already-unset"}
    store.save(model_assignments_module.without_assignment(assignments, cli_id, agent))
    return {
        "action": "unset",
        "cli": cli_id,
        "agent": agent,
        "status": "unset",
        "activation": (_NOT_INSTALLED_YET.format(cli=cli_id),),
    }


_NOT_INSTALLED_YET = (
    "The current installation at {cli} does not carry this yet; reinstall "
    "(`pegasus install --cli {cli}`) to write it into the rendered configuration."
)


def models_list(runtime: Runtime, *, cli_id: str | None = None) -> dict[str, Any]:
    """Current assignments, optionally narrowed to one CLI."""
    if cli_id is not None:
        _adapter(cli_id)
    assignments = model_assignment_store(runtime).load()
    return {
        "action": "list",
        "assignments": [
            {"cli": entry.cli, "agent": entry.agent, "model": entry.assignment.full_id, "effort": entry.assignment.effort}
            for entry in assignments.entries
            if cli_id is None or entry.cli == cli_id
        ],
    }


def _require_configurable_agent(agent: str) -> None:
    content = content_module.load()
    for descriptor in content.agents:
        if descriptor.name == agent:
            if not descriptor.model_configurable:
                raise CommandError(f"{agent!r} does not accept a model assignment")
            return
    raise CommandError(f"{agent!r} is not an agent this release ships")


def _restore(arguments, runtime: Runtime) -> dict[str, Any]:
    return restore(runtime, arguments.generation)


def restore(runtime: Runtime, generation: int | None = None) -> dict[str, Any]:
    """Undo the most recent generation, or a specific one, and report what
    was put back — same reasoning as `install`: the TUI's restore screen
    calls this directly, the report it gets back the same one `--json`
    would.
    """
    store = journal_store(runtime)
    store.ensure_writable()
    snapshot = snapshot_store(runtime)
    snapshot.ensure_writable()

    # Resolved before this run's own snapshot is written. Reversing the order
    # would make "the most recent generation" resolve to the copy this very
    # call is about to take, and restore would recover its own copy of the
    # present instead of anything that came before it.
    try:
        if generation is None:
            generation = snapshot.most_recent_readable()
            if generation is None:
                raise CommandError("there is no snapshot generation to restore")
        manifest = snapshot.read(generation)
    except SnapshotStoreError as error:
        raise CommandError(f"generation {generation} cannot be restored: {error}") from error

    # Same reasoning as install and uninstall: restore writes, so nothing is
    # touched without its own copy taken first. What it captures is the
    # addresses it is about to touch, plus the journal, same as the others.
    # A dependency-tree address this generation names is the one this call is
    # about to `remove_dir` -- if it is standing right now, that is exactly
    # the directory `capture_paths` cannot read back whole, so it is named
    # here the same way `_install` names one, and left uncaptured for the
    # same reason.
    directories = frozenset(entry.path for entry in manifest.entries if entry.is_directory)
    touched = sorted({entry.path for entry in manifest.entries} | {store.path}, key=str)
    try:
        snapshot.save(
            capture_paths(runtime.filesystem, touched, directories=directories), taken_at=runtime.now
        )
    except SnapshotStoreError as error:
        raise CommandError(
            f"a snapshot of what this restore is about to overwrite could not be taken, "
            f"so nothing was restored: {error}"
        ) from error

    # One address at a time, so a failure in the middle leaves some of them
    # already back. Reporting that as nothing having changed would send the
    # user looking for the problem somewhere else, and would tell an agent the
    # filesystem is in a state it is not in — so what was already done travels
    # with the failure instead of dying with it.
    written: list[str] = []
    removed: list[str] = []
    for entry in manifest.entries:
        try:
            if entry.existed:
                content = snapshot.read_blob(generation, entry.blob)
                runtime.filesystem.write_atomic(entry.path, content, mode=int(entry.mode, 8))
                written.append(str(entry.path))
            elif entry.is_directory:
                # `remove`, called below for every other absent-before entry,
                # is file-only by contract; a dependency tree needs the whole
                # directory taken back out, same as `_retire_dependency_trees`
                # -- and the same refusal to swallow a real failure: a
                # permission this process cannot override surfaces as the
                # `FileSystemError` caught just below, never as a silent
                # `removed`.
                runtime.filesystem.remove_dir(entry.path)
                removed.append(str(entry.path))
            else:
                runtime.filesystem.remove(entry.path)
                removed.append(str(entry.path))
        except (FileSystemError, SnapshotStoreError) as error:
            failure = CommandError(
                f"generation {generation} could not be put back in full, and what had already been "
                f"changed was left as it is: {error}"
            )
            failure.report = {"generation": generation, "written": written, "removed": removed}
            raise failure from error

    return {
        "status": "restored",
        "generation": generation,
        "written": written,
        "removed": removed,
        "retention": _retain(snapshot),
    }


def _doctor(arguments, runtime: Runtime) -> dict[str, Any]:
    return doctor(runtime, start_mcp_servers=getattr(arguments, "start_mcp_servers", False))


def doctor(runtime: Runtime, *, start_mcp_servers: bool = False) -> dict[str, Any]:
    """What is supported, what is present, and what has drifted, per CLI —
    the TUI's status screen calls this directly, the report it gets back
    the same one `--json` would.

    `start_mcp_servers` is the one way this stops being read-only: every
    locally-launched MCP server the journal claims for a CLI is actually
    started and put through the MCP `initialize` handshake.
    """
    environment = runtime.environment
    registry = available()
    journal = journal_store(runtime).load()
    return {
        "pegasus_version": pegasus.__version__,
        "clis": [
            _health(registry.get(cli_id), environment, journal, runtime, start_mcp_servers=start_mcp_servers)
            for cli_id in registry.ids()
        ],
    }


def _health(
    adapter, environment: Environment, journal, runtime: Runtime, *, start_mcp_servers: bool = False
) -> dict[str, Any]:
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
        "unreadable": [],
    }
    if install is None:
        return health

    # `doctor` is what somebody runs precisely because the installation looks
    # inert, which is exactly the state an unread configuration produces. Saying
    # nothing here confirms the install while the running session ignores it.
    health["activation"] = list(adapter.activation_steps())

    for entry in install.entries:
        # One entry a permission bit hides must not take the rest of the
        # report down with it — a doctor that dies over a single unreadable
        # artifact is worse than the per-entry table it would otherwise
        # produce.
        try:
            current = _current_digest(runtime.filesystem, entry)
        except FileSystemError:
            health["unreadable"].append(entry.id)
            continue
        if current is None:
            health["missing"].append(entry.id)
        elif current != entry.after_digest:
            health["drifted"].append(entry.id)

    if start_mcp_servers:
        health["mcp_servers"] = [
            {"id": check.id, "status": check.status, "detail": check.detail}
            for check in _mcp_checks(runtime, install)
        ]
    return health


_MCP_ENTRY_PREFIX = "mcp:"
_MCP_CONVENTION_PREFIX = "mcp-convention:"


def _mcp_checks(runtime: Runtime, install) -> list[mcp_handshake.ServerCheck]:
    """Launch every locally-configured MCP server the journal claims for this
    install, and hand back one verdict per server.

    Only what `_mcp_entries` finds is ever executed: a `config-key` entry
    whose id this same install wrote, read back from the configuration file
    Pegasus itself placed. Nothing named anywhere else is ever a candidate.
    """
    return [
        *(_mcp_checks_one(runtime, entry, name) for entry, name in _mcp_entries(install)),
        *_bound_checks(install),
    ]


def _bound_checks(install) -> list[mcp_handshake.ServerCheck]:
    """The servers this install granted without ever configuring them.

    A bound server writes no `/mcp/<id>` key — only its convention — so
    `_mcp_entries` cannot see it, and an install whose servers are all bound
    reported "No MCP servers configured": not a gap in the report but a false
    statement about the machine. A convention entry with no configuration key
    beside it is exactly the shape a binding leaves behind, and it is enough
    to say the true thing instead.

    What is said stops where the journal's knowledge stops, and it stops twice.
    The key the server was bound to was never recorded, so it is not named: a
    report that guessed it would be the same kind of falsehood this exists to
    remove. And a binding is not the only cause of this shape -- `retire` walks
    kinds in sorted order, `config-key` before `file`, so an uninstall that
    removed the configuration key and then failed on the convention leaves the
    journal holding exactly this. Nothing here separates the two, so neither is
    asserted; both readings are named instead. Starting the server is out of
    reach for the same reason as the key: there is nothing recorded to start.
    """
    configured = {name for _, name in _mcp_entries(install)}
    return [
        mcp_handshake.ServerCheck(
            entry.id[len(_MCP_CONVENTION_PREFIX):],
            "bound",
            "no configuration of its own in this install: either bound to a server you "
            "administer, whose tools Pegasus grants and whose convention it ships without "
            "installing or starting it, or a convention left behind by an uninstall that "
            "did not finish",
        )
        for entry in install.entries
        if entry.id.startswith(_MCP_CONVENTION_PREFIX)
        and entry.id[len(_MCP_CONVENTION_PREFIX):] not in configured
    ]


def _mcp_entries(install) -> list[tuple[Record, str]]:
    return [
        (entry, entry.id[len(_MCP_ENTRY_PREFIX):])
        for entry in install.entries
        if entry.kind == "config-key" and entry.id.startswith(_MCP_ENTRY_PREFIX)
    ]


def _mcp_checks_one(runtime: Runtime, entry: Record, name: str) -> mcp_handshake.ServerCheck:
    try:
        document = _document(runtime.filesystem, entry)
    except (FileSystemError, CommandError) as error:
        return mcp_handshake.ServerCheck(name, "unreadable", f"configuration could not be read: {error}")
    value = pointer.get_at(document, entry.pointer or "")
    if not isinstance(value, dict):
        return mcp_handshake.ServerCheck(name, "missing", "not configured")
    if value.get("type") != "local":
        return mcp_handshake.ServerCheck(name, "remote", "not a locally-launched server; not started")
    command = value.get("command")
    if not isinstance(command, list) or not command or not all(isinstance(part, str) for part in command):
        return mcp_handshake.ServerCheck(name, "invalid", "configured command is malformed")
    return mcp_handshake.check_server(
        name, tuple(command), runtime.mcp_process, timeout_seconds=runtime.mcp_handshake_timeout_seconds
    )


def _current_digest(filesystem: FileSystem, entry: Record) -> str | None:
    """What the artifact hashes to right now, or ``None`` if it is not there.

    Raises :class:`FileSystemError` when even that cannot be told — the
    caller buckets that separately from "not there", because it is not the
    same fact.
    """
    if not filesystem.exists(entry.target):
        return None
    return DIGEST_READERS[entry.kind](filesystem, entry)


def _digest_of_file(filesystem: FileSystem, entry: Record) -> str | None:
    return ownership.digest_of_bytes(filesystem.read_bytes(entry.target))


def _digest_of_dependency_tree(filesystem: FileSystem, entry: Record) -> str | None:
    """A tree that is there is all this can honestly report.

    The digest a dependency-tree record carries is the identity of what was
    materialized — the checksum of the archive, or the integrity the lockfile
    pinned — not a hash of the directory as it stands. So being present is
    the whole of what can be checked here, and answering with the recorded
    digest says exactly that and nothing more. Telling a tampered tree from
    an intact one needs a different check than this field can give.
    """
    return entry.after_digest


def _digest_of_config_key(filesystem: FileSystem, entry: Record) -> str | None:
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


DIGEST_READERS: dict[str, Callable[[FileSystem, Record], str | None]] = {
    "file": _digest_of_file,
    "config-key": _digest_of_config_key,
    "dependency-tree": _digest_of_dependency_tree,
}
"""What each kind of entry hashes to right now, keyed by `journal.KINDS`.

Keyed rather than branched for the same reason retirement is: this used to
ask whether the kind was `file` and treat everything else as a configuration
key, so a kind added later would have had its directory opened as a
document. A kind with no reader here fails at import instead.
"""

_UNREADABLE_KINDS = sorted(KINDS - DIGEST_READERS.keys())
if _UNREADABLE_KINDS:
    raise CommandError("no digest reader for kind(s): " + ", ".join(_UNREADABLE_KINDS))


def _document(filesystem: FileSystem, entry: Record):
    from pegasus.core import codecs

    try:
        return codecs.loads(Codec(entry.codec or Codec.JSON.value), filesystem.read_bytes(entry.target).decode("utf-8"))
    except (UnicodeDecodeError, codecs.CodecError) as error:
        raise CommandError(f"{entry.target} cannot be parsed, so nothing in it can be judged: {error}") from error


def _attached_to_a_terminal() -> bool:
    """Whether there is a person at a screen to show a menu to.

    Both ends are asked. Output alone would call a redirected run
    interactive; input alone would do the same for one whose keystrokes come
    from a file. The menu needs someone who can both see it and answer it.

    A stream that has been closed cannot answer the question at all and
    raises instead, which is its own answer: there is nobody there.
    """
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except ValueError:
        return False


COMMANDS = {
    "install": _install,
    "uninstall": _uninstall,
    "doctor": _doctor,
    "restore": _restore,
    "models": _models,
}


# --- Shaping the report ----------------------------------------------------


def _adapter(cli_id: str):
    registry = available()
    if cli_id not in registry:
        raise CommandError(f"{cli_id!r} is not a CLI this release supports; try one of: {', '.join(registry.ids())}")
    return registry.get(cli_id)


def _select_mcp(chosen: list[str] | None) -> content_module.Content:
    """The user's `--mcp` flags, applied to the whole content tree once.

    `ContentError` here means the user's own flag named a server that does not
    exist, which is a clean message rather than the traceback a malformed
    shipped descriptor would still deserve — that case is left to whatever
    already raises `ContentError` unhandled in `main`.
    """
    try:
        return content_module.select_mcp(content_module.load(), chosen or [])
    except content_module.ContentError as error:
        raise CommandError(str(error)) from error


def _require_present(adapter, environment: Environment) -> None:
    detection = adapter.detect(environment)
    if detection.installed or detection.config_found:
        return
    raise CommandError(
        f"{adapter.display_name} was not found on this machine, and installing into a CLI that is not "
        f"here would only leave files nothing reads"
    )


def _retain(snapshot: FileSnapshotStore) -> dict[str, Any]:
    """Run retention after a snapshot-taking command has already succeeded.

    A retention failure must never turn a command that already wrote its
    snapshot into a reported failure — the old generation left behind is
    untidy, not dangerous — so this never raises. It still has to surface
    somewhere rather than vanish silently, and the report is where every
    other fact about the run already lives, so a failed removal is named
    there under ``retention.failed``.
    """
    outcome = snapshot.retain(keep=RETAIN_GENERATIONS)
    return {"removed": list(outcome.removed), "failed": list(outcome.failed)}


def _is_key(step: planner.Step) -> bool:
    return getattr(step.artifact, "pointer", None) is not None


def _unrecordable(
    error: JournalStoreError,
    left_behind: list[str],
    *,
    placed: int,
    replaced: int = 0,
    failures: list[str] | None = None,
    removed: int = 0,
    retired: list[str] | None = None,
) -> CommandError:
    """The install came back out. Say so, and say what did not come with it.

    ``undone`` is false when this run placed nothing — a reinstall where
    everything already existed — because then there was nothing to take back and
    saying otherwise would invent an event. Pegasus owns keys inside a
    configuration file, never the file itself, so a file it had to create to hold
    them survives the rollback as an empty document. Harmless, but claiming a
    clean undo would be a small lie in the one report a user reads when something
    already went wrong.

    ``retired`` is the one thing this rollback genuinely cannot touch. It runs
    before the journal is saved, so by the time saving fails it has already
    happened — the key is unset, the file is gone — and `unplace` only knows
    how to undo this run's own placements, never a retirement; that was a
    deliberate choice, not an omission, because the snapshot taken before this
    run already holds what a retirement removed. Recovery is manual, but it is
    real, so the report says exactly that instead of a rollback that quietly
    stops short.
    """
    undone = placed > 0
    if undone:
        message = (
            f"the artifacts were placed but the journal could not be written, so they were taken back out "
            f"rather than left unrecorded: {error}"
        )
    else:
        message = f"nothing needed placing, and the journal could not be written anyway: {error}"
    if replaced:
        message += f". {replaced} already there went back to the version they held"
    if failures:
        message += (
            f". Some could not be put back, and were left as this run wrote them rather than "
            f"removed: {'; '.join(failures)}"
        )
    if left_behind:
        message += f". Left behind, empty: {', '.join(left_behind)}"
    if retired:
        message += (
            f". {len(retired)} already retired from disk before the journal failed, and this rollback does "
            f"not put them back: {', '.join(retired)}. Restore the snapshot taken before this run to get "
            f"them back"
        )
    failure = CommandError(message)
    failure.report = {
        "placed": placed,
        "rolled_back": undone,
        "left_behind": left_behind,
        "restored": replaced,
        "removed": removed,
        "retired": retired or [],
    }
    return failure


def _unretirable(
    error: FileSystemError | planner.PlannerError,
    left_behind: list[str],
    *,
    placed: int,
    replaced: int = 0,
    failures: list[str] | None = None,
    removed: int = 0,
) -> CommandError:
    """This run's own placements came back out, because retiring what this
    render no longer asks for failed before the journal ever got a chance to
    save. It is the same rollback ``_unrecordable`` performs, for a different
    cause, and it must not borrow that helper's message — the journal was
    never touched here, and saying it failed would blame the wrong thing.

    There is nothing to say about the retirement's own progress, on purpose:
    `retire()` raised instead of returning, so there is no `Retired` to read a
    fact from, and guessing a count would be inventing one. What *is* true
    without needing that fact: `retire()`'s docstring promises every operation
    is a no-op the second time, so whatever it already removed before this
    failure stays removed, and a later run finishes retiring the rest. That is
    a convergence, not a partial-failure hazard, so the message names it as
    one instead of a rollback that quietly stops short.
    """
    undone = placed > 0
    if undone:
        message = (
            f"the artifacts were placed but retiring what this run no longer asks for failed partway "
            f"through, so this run's own placements were taken back out rather than left unrecorded: {error}"
        )
    else:
        message = (
            f"nothing needed placing, and retiring what this run no longer asks for failed partway "
            f"through anyway: {error}"
        )
    if replaced:
        message += f". {replaced} already there went back to the version they held"
    if failures:
        message += (
            f". Some could not be put back, and were left as this run wrote them rather than "
            f"removed: {'; '.join(failures)}"
        )
    if left_behind:
        message += f". Left behind, empty: {', '.join(left_behind)}"
    message += (
        ". Some of what this run was retiring may already be gone from disk — retiring is a no-op the "
        "second time, so running install again finishes the rest"
    )
    failure = CommandError(message)
    failure.report = {
        "placed": placed,
        "rolled_back": undone,
        "left_behind": left_behind,
        "restored": replaced,
        "removed": removed,
    }
    return failure


def _placed(step: planner.Step) -> dict[str, Any]:
    return {"id": step.artifact.id, "target": str(step.artifact.path)}


def _recorded(record: Record) -> dict[str, Any]:
    return {"id": record.id, "kind": record.kind, "target": str(record.target)}


def _undo_placements(
    filesystem: FileSystem, applied: planner.Applied, placed: Install
) -> tuple[int, list[str]]:
    """Take this run's own placements back out, and never raise doing it.

    ``unplace`` probes as it works — retiring a file asks whether it is there,
    and retiring a key reads the document holding it — so it can fail for the
    same reason the handler calling it is already reporting. Letting that
    second failure escape replaces the specific rollback report with `main`'s
    generic one, which is the opposite of what a person needs from the one
    message they read when something has already gone wrong.

    So a rollback that cannot finish is reported as a rollback that could not
    finish, in the vocabulary the report already has for exactly that.
    """
    try:
        retired, failures = planner.unplace(filesystem, applied, placed)
    except (FileSystemError, planner.PlannerError) as error:
        return 0, [f"the rollback could not be completed: {error}"]
    return len(retired.removed), [reason for _, reason in failures]


def _left_behind(filesystem: FileSystem, candidates: set[Path]) -> list[str]:
    """Which of this run's freshly created, now-rolled-back documents are still
    there, empty — for the rollback report a person reads when something has
    already gone wrong.

    Called from inside a handler that is already reporting a first failure, so
    a second one here must not escape it: escaping would replace the specific
    `_unretirable`/`_unrecordable` report with `main`'s generic one, over the
    exact path a user reads when things went sideways. A candidate whose state
    cannot be told is left out rather than guessed at either way — dropping it
    silently is honest, unlike claiming it is there or claiming it is gone.
    """
    left: list[str] = []
    for path in candidates:
        try:
            if filesystem.exists(path):
                left.append(str(path))
        except FileSystemError:
            continue
    return sorted(left)


def _left(step: planner.Step) -> dict[str, Any]:
    return {"id": step.artifact.id, "target": str(step.artifact.path), "reason": step.reason}


def _prose(report: dict[str, Any]) -> str:
    """The same facts, for a person. Never a subset of them."""
    if report.get("status") == "failed":
        if report.get("rolled_back"):
            return f"The installation was undone. {report['error']}"
        # Claiming nothing changed is only honest when nothing did. A command
        # that got partway through says how far, because the whole point of
        # this output is that a number in it can be trusted.
        changed = len(report.get("written", ())) + len(report.get("removed", ()))
        if changed:
            return f"Stopped after changing {changed}. {report['error']}"
        return f"Nothing was changed. {report['error']}"

    command = report["command"]
    if command == "doctor":
        return "\n".join(_cli_prose(entry) for entry in report["clis"])
    if command == "restore":
        lines = [
            f"generation {report['generation']}: wrote back {len(report['written'])}, "
            f"removed {len(report['removed'])}."
        ]
        return "\n".join(_and_retention(lines, report))
    if command == "install":
        planned = report["status"] == "planned"
        lines = [
            f"{report['cli']}: {'would create' if planned else 'created'} {len(report['created'])} artifacts, "
            f"{'would update' if planned else 'updated'} {len(report['updated'])}, "
            f"{len(report['unchanged'])} already current, skipped {len(report['skipped'])}."
        ]
        if report.get("overwritten"):
            lines.append(
                "Overwritten, because Pegasus owns these and you had changed them:"
                if not planned
                else "Would be overwritten, because Pegasus owns these and you had changed them:"
            )
            lines.extend(f"  {item['id']} → {item['target']}" for item in report["overwritten"])
        if report["skipped"]:
            lines.append("Left alone because something was already there:")
            lines.extend(f"  {item['id']} → {item['target']}" for item in report["skipped"])
        if report["retired"]:
            lines.append(f"{'Would retire' if planned else 'Retired'}, no longer asked for:")
            lines.extend(f"  {item['id']} → {item['target']}" for item in report["retired"])
        # Fetched rather than indexed: a planned report has nothing to say here,
        # because a dry run never asks `retire` anything and so never learns
        # what it could not account for. Only a run that happened can.
        if report.get("unaccounted"):
            lines.append(f"Could not be accounted for: {', '.join(report['unaccounted'])}")
        if report.get("model_warnings"):
            lines.append("Model assignments that could not be honoured:")
            lines.extend(f"  {warning}" for warning in report["model_warnings"])
        return "\n".join(_and_retention(_and_activation(lines, report), report))
    if command == "models":
        return _models_prose(report)

    lines = [f"{report['cli']}: removed {len(report['removed'])}."]
    if report["unaccounted"]:
        lines.append(f"Could not be accounted for: {', '.join(report['unaccounted'])}")
    return "\n".join(_and_retention(_and_activation(lines, report), report))


def _models_prose(report: dict[str, Any]) -> str:
    action = report.get("action")
    if action == "set":
        effort = f", effort {report['effort']}" if report.get("effort") else ""
        line = f"{report['cli']}/{report['agent']}: assigned {report['model']}{effort}."
        return "\n".join(_and_activation([line], report))
    if action == "unset":
        if report["status"] == "already-unset":
            return f"{report['cli']}/{report['agent']}: no assignment to remove."
        line = f"{report['cli']}/{report['agent']}: assignment removed."
        return "\n".join(_and_activation([line], report))
    if action == "list":
        if not report["assignments"]:
            return "No model assignments."
        return "\n".join(
            f"{entry['cli']}/{entry['agent']}: {entry['model']}"
            + (f" (effort {entry['effort']})" if entry.get("effort") else "")
            for entry in report["assignments"]
        )
    return "models: nothing to report."


def _and_activation(lines: list[str], report: dict[str, Any]) -> list[str]:
    """The part a person still has to act on, so prose never hides it.

    An installation that is complete on disk can still be doing nothing, and the
    document says so under `activation`. Prose is never a subset of it.
    """
    steps = report.get("activation") or []
    if not steps:
        return lines
    return [*lines, "Before this takes effect:", *(f"  {step}" for step in steps)]


def _and_retention(lines: list[str], report: dict[str, Any]) -> list[str]:
    """The part cleanup could not finish, so prose never hides it either.

    A retention failure never fails the command — the snapshot the caller
    needed is already on disk — but it must still reach the person reading
    the report, not just the JSON document.
    """
    failed = (report.get("retention") or {}).get("failed") or []
    if not failed:
        return lines
    return [*lines, "Old snapshot generations could not be cleaned up:", *(f"  {reason}" for reason in failed)]


#: The public name for `_prose`, for a caller outside this module — the TUI's
#: install screen, chiefly. Kept as an alias rather than a rename so the
#: existing tests that reach `cli._prose` directly stay untouched.
prose_for = _prose


def _cli_prose(entry: dict[str, Any]) -> str:
    if not entry["detected"]:
        return f"{entry['display_name']}: not found on this machine."
    if not entry["pegasus_installed"]:
        return f"{entry['display_name']}: present at {entry['config_dir']}, Pegasus not installed."
    line = f"{entry['display_name']}: {entry['artifacts']} artifacts installed at {entry['config_dir']}."
    for label, key in (
        ("changed by hand", "drifted"),
        ("missing", "missing"),
        ("could not be checked", "unreadable"),
    ):
        if entry.get(key):
            line += f" {len(entry[key])} {label}: {', '.join(entry[key])}."
    # A condition rather than an order: whoever already restarted is done, and
    # telling them again every time would turn the notice into noise.
    steps = entry.get("activation") or []
    if steps:
        line += "\n  If it was already running when Pegasus was installed:"
        line += "".join(f"\n    {step}" for step in steps)
    if "mcp_servers" in entry:
        if entry["mcp_servers"]:
            line += "\n  MCP servers:"
            line += "".join(
                f"\n    {check['id']}: {check['status']} — {check['detail']}" for check in entry["mcp_servers"]
            )
        else:
            line += "\n  No MCP servers configured."
    return line
