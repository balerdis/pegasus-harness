"""The flags: everything a binary built from this engine can do without a
person watching.

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
import os
import re
import shutil
import sys
import zipfile
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from importlib.resources import files as _package_files
from pathlib import Path
from typing import Any, Callable, TextIO

import pegasus
from pegasus.adapters import available
from pegasus.adapters.opencode import render as opencode_render_module
from pegasus.adapters.opencode.manifest import CLI_ID as OPENCODE_CLI_ID
from pegasus.core import catalog as catalog_module
from pegasus.core import content as content_module
from pegasus.core import dependencies as dependencies_module
from pegasus.core import identity as identity_module
from pegasus.core import journal as journal_module
from pegasus.core import model_assignments as model_assignments_module
from pegasus.core import ownership, planner, pointer
from pegasus.core import upgrade as upgrade_module
from pegasus.core.identity import Identity
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
RETAIN_GENERATIONS = 20


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
    #: Resolved once, from `identity.json`, and threaded down as a plain
    #: value from here on -- never re-read or re-branched on inside `core`,
    #: `ports`, `infra`, or `tui`. Defaulted to the packaged identity so
    #: every existing caller that builds a `Runtime` without naming one --
    #: this repo's own tests included -- still gets Pegasus's own identity,
    #: exactly as `default_runtime` would; a caller building a distribution's
    #: own `Runtime` overrides this explicitly instead.
    identity: Identity = field(default_factory=lambda: default_identity())
    downloader: Downloader = field(default_factory=HttpDownloader)
    npm_installer: NpmInstaller = field(default_factory=SubprocessNpmInstaller)
    mcp_process: MCPProcess = field(default_factory=SubprocessMCPProcess)
    mcp_handshake_timeout_seconds: float = mcp_handshake.DEFAULT_TIMEOUT_SECONDS
    #: `sys.path[0]` as the real interpreter actually set it -- read here,
    #: through `Runtime`, the same seam every other process fact
    #: (`variables`, `now`) already goes through, rather than `upgrade`
    #: reaching for `sys.path` itself. This is what `_running_binary_path`
    #: resolves: for a zipapp (built by `tools/build_zipapp.py`, run via its
    #: shebang or `python3 <path>`), Python sets this to the exact path the
    #: archive was invoked with, and `zipfile.is_zipfile` on that path comes
    #: back `True`; for `python3 -m pegasus` (this repo's own tests, and
    #: `PYTHONPATH=src` manual checks) it is the current directory, and for a
    #: plain script it is the script's own containing directory -- neither is
    #: ever itself a zip. Defaulting to the real `sys.path[0]` is what makes
    #: `upgrade` correct outside a test without any caller having to know
    #: this field exists.
    sys_path0: str = field(default_factory=lambda: sys.path[0] if sys.path else "")

    @property
    def environment(self) -> Environment:
        return Environment(
            home=self.home, variables=self.variables, data_dir=self.filesystem.data_dir(self.home)
        )


def default_identity() -> Identity:
    """Parse the identity this exact binary was built with -- `identity.json`,
    read the same way `core.content` reads `content/`: through
    `importlib.resources`, so it resolves identically from a source checkout
    and from inside a zipapp. Fails loudly (`IdentityError`, a `ValueError`)
    on anything missing or malformed -- there is no default identity to fall
    back to, by design (see `pegasus.core.identity`'s own docstring).
    """
    document = _package_files("pegasus").joinpath("identity.json").read_bytes()
    return identity_module.parse(document)


def default_runtime(out: TextIO) -> Runtime:
    import os

    variables = dict(os.environ)
    identity = default_identity()
    return Runtime(
        filesystem=PosixFileSystem(variables, product_id=identity.product_id),
        home=Path.home(),
        now=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        out=out,
        variables=variables,
        identity=identity,
        downloader=HttpDownloader(),
        npm_installer=SubprocessNpmInstaller(),
        mcp_process=SubprocessMCPProcess(),
    )


def journal_store(runtime: Runtime) -> FileJournalStore:
    return FileJournalStore(runtime.filesystem, home=runtime.home, pegasus_version=runtime.identity.version)


def snapshot_store(runtime: Runtime) -> FileSnapshotStore:
    return FileSnapshotStore(runtime.filesystem, home=runtime.home)


def model_assignment_store(runtime: Runtime) -> FileModelAssignmentStore:
    return FileModelAssignmentStore(runtime.filesystem, home=runtime.home)


# --- Entry point -----------------------------------------------------------


def main(argv: list[str] | None = None, *, runtime: Runtime | None = None) -> int:
    runtime = runtime or default_runtime(sys.stdout)
    parser = _parser(runtime.identity)
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
        runtime.out.write(_prose(report, identity=runtime.identity) + "\n")
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


def _parser(identity: Identity) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=identity.program_name,
        description=f"The flags: everything {identity.display_name} can do without a person watching.",
    )
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
        "-V", "--version", action="version", version=f"%(prog)s {identity.version}",
        help="report the version of this binary and exit",
    )
    commands = parser.add_subparsers(dest="command")

    install = commands.add_parser(
        "install", help=f"place {identity.display_name} into one CLI's configuration"
    )
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

    update = commands.add_parser(
        "update", help="reapply an installation's own selection -- mcp bindings included, no flags needed"
    )
    update.add_argument("--cli", required=True)
    update.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    update.add_argument("--dry-run", action="store_true", help="report the plan without writing anything")

    # No `--cli`: this replaces the `pegasus` program itself, never an
    # installation into a CLI's configuration -- see `upgrade`'s own
    # docstring for why that is a different concern from `update`.
    upgrade = commands.add_parser(
        "upgrade", help=f"replace the running {identity.program_name} binary with the newest published one"
    )
    upgrade.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    upgrade.add_argument(
        "--dry-run", action="store_true", help="report what would be replaced and with what version"
    )

    uninstall = commands.add_parser("uninstall", help=f"take {identity.display_name} back out of one CLI")
    uninstall.add_argument("--cli", required=True)
    uninstall.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)

    repair = commands.add_parser(
        "repair", help="remove journal hazards doctor can only name (quarantined directory entries)"
    )
    repair.add_argument("--cli", required=True)
    repair.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    repair.add_argument("--dry-run", action="store_true", help="report what would be removed without writing anything")

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
    restore.add_argument(
        "--list",
        action="store_true",
        help="show every generation that can still be restored, without restoring anything",
    )
    restore.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)

    models = commands.add_parser("models", help="assign, remove, or list per-agent model preferences")
    models.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    models_commands = models.add_subparsers(dest="models_command")

    set_parser = models_commands.add_parser("set", help="assign a model to one or more agents, in one command")
    set_parser.add_argument("--cli", required=True)
    set_parser.add_argument(
        "--assign",
        action="append",
        required=True,
        metavar="AGENT=PROVIDER/MODEL",
        help="assign a model to an agent (repeatable): --assign AGENT=PROVIDER/MODEL",
    )
    set_parser.add_argument(
        "--effort",
        action="append",
        default=[],
        metavar="AGENT=LEVEL",
        help="set the reasoning effort for an agent also named by --assign (repeatable)",
    )
    set_parser.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)

    unset_parser = models_commands.add_parser("unset", help="remove one or more agents' model assignment")
    unset_parser.add_argument("--cli", required=True)
    unset_parser.add_argument("--agent", action="append", required=True, help="repeatable")
    unset_parser.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)

    list_parser = models_commands.add_parser("list", help="show current model assignments")
    list_parser.add_argument("--cli", default=None, help="limit to one CLI; omit to show every CLI")
    list_parser.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)

    mcp = commands.add_parser(
        "mcp", help="grant, revoke, or list MCP server keys you administer yourself"
    )
    mcp.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    mcp_commands = mcp.add_subparsers(dest="mcp_command")

    mcp_grant_parser = mcp_commands.add_parser(
        "grant", help="grant one or more server keys you administer to every agent, in one command"
    )
    mcp_grant_parser.add_argument("--cli", required=True)
    mcp_grant_parser.add_argument("key", nargs="+")
    mcp_grant_parser.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)

    mcp_revoke_parser = mcp_commands.add_parser(
        "revoke", help="revoke one or more previously granted server keys, in one command"
    )
    mcp_revoke_parser.add_argument("--cli", required=True)
    mcp_revoke_parser.add_argument("key", nargs="+")
    mcp_revoke_parser.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)

    mcp_list_parser = mcp_commands.add_parser(
        "list", help="show what is granted now, and what else is available to grant"
    )
    mcp_list_parser.add_argument("--cli", required=True)
    mcp_list_parser.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)

    directory = commands.add_parser(
        "directory", help="grant or revoke a working directory outside the worktree, for every agent"
    )
    directory.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    directory_commands = directory.add_subparsers(dest="directory_command")

    directory_grant_parser = directory_commands.add_parser(
        "grant", help="grant one or more directories of your own choosing to every agent, in one command"
    )
    directory_grant_parser.add_argument("--cli", required=True)
    directory_grant_parser.add_argument("path", nargs="+")
    directory_grant_parser.add_argument(
        "--json", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS
    )

    directory_revoke_parser = directory_commands.add_parser(
        "revoke", help="revoke one or more previously granted directories, in one command"
    )
    directory_revoke_parser.add_argument("--cli", required=True)
    directory_revoke_parser.add_argument("path", nargs="+")
    directory_revoke_parser.add_argument(
        "--json", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS
    )
    return parser


# --- Commands --------------------------------------------------------------


def _install(arguments, runtime: Runtime) -> dict[str, Any]:
    return install(arguments.cli, runtime, dry_run=arguments.dry_run, mcp=arguments.mcp, label="install")


@dataclass(frozen=True)
class Progress:
    """One tick of an installation in progress, for a caller that wants to
    render it -- the TUI's install screen, though nothing here names it.

    The total spans every phase an install can touch, not only the artifacts
    the engine places, and that is deliberate: a `download` or `npm` fetch is
    network-bound and can dominate wall-clock time while being one or two
    units of work, so a total counting artifacts alone would sit at 0% through
    the slowest part of the run. Only `install` sees the plan, the dependency
    set and the retirement set together, which is why the total is computed
    here in the application layer and not in `core.planner`, which reports a
    finished unit but never knows how many siblings it has.

    `unit` is the human-recognizable name of whatever just finished -- an
    artifact's id, a dependency's name, or one of the two fixed phases
    (`"snapshot"`, `"journal"`) -- and `phase` is one of `"snapshot"`,
    `"dependencies"`, `"artifacts"`, `"retire"`, `"journal"`. Wording and
    layout are for whoever renders this, so nothing here formats any text.

    `bytes_downloaded` and `bytes_total` are `None` for every tick except one
    still in flight inside a `download` server's own fetch -- `done` has not
    advanced for one of those, since the unit it names has not finished, only
    made progress; the same `done`/`total`/`phase`/`unit` a caller ignoring
    these two fields already reads keep meaning exactly what they meant
    before this pair existed. `bytes_total` is further `None` on its own,
    independent of `bytes_downloaded`, whenever the server fetching the bytes
    never learned how many there would be -- never a guessed number standing
    in for one. This class stays a plain value: nothing on it reads a clock
    or formats a byte count into text, both of which belong to whoever
    renders it, not to the value being rendered.
    """

    done: int
    total: int
    phase: str
    unit: str
    bytes_downloaded: int | None = None
    bytes_total: int | None = None

    @property
    def fraction(self) -> float:
        return self.done / self.total

    @property
    def percent(self) -> float:
        return 100 * self.fraction


@dataclass(frozen=True)
class ModelAssignmentSpec:
    """One item of a model-assignment batch: an agent name, an unparsed
    `PROVIDER/MODEL` spec, and an optional effort.

    This is the shape `install`'s own `model_assignments` parameter takes,
    mirroring `mcp`/`granted`/`granted_directories`'s own list-of-plain-values
    shape closely enough for a caller to build the whole batch before making
    one call -- but a model assignment carries three fields, not one, so a
    bare string cannot hold it the way an mcp id or a directory path can.
    """

    agent: str
    model: str
    effort: str | None = None


def install(
    cli_id: str,
    runtime: Runtime,
    *,
    dry_run: bool = False,
    mcp: list[str] | None = None,
    granted: list[str] | None = None,
    granted_directories: list[str] | None = None,
    model_assignments: list[ModelAssignmentSpec] | None = None,
    model_removals: list[str] | None = None,
    label: str = "install",
    on_progress: Callable[["Progress"], None] | None = None,
) -> dict[str, Any]:
    """Place Pegasus into one CLI's configuration, and report what happened.

    This is the engine path itself, parsed flags peeled away: `_install`
    exists only to unpack an `argparse.Namespace` into these three plain
    values, so anything else that wants the same installation — the TUI's
    install screen, not a second implementation of it — calls this directly
    and renders the report it gets back, the same report `--json` would.

    `granted`, when given, replaces this install's whole set of user-granted
    MCP keys (`mcp_grant`/`mcp_revoke` always pass the exact set they want
    recorded). Left `None` — an ordinary `pegasus install --cli x` with no
    grant-specific flag of its own — it carries the previous install's own
    `granted_mcp` forward unchanged, the opposite of how `mcp` (the `--mcp`
    selection) behaves: silence about `--mcp` means select nothing, because
    every `install` names its whole selection explicitly on the command
    line, but there is no `--grant` flag on `install` for a grant to go
    silent about, so a plain reinstall must not read as "revoke everything".

    `granted_directories` follows the identical rule, for
    `Install.granted_directories`/`directory_grant`/`directory_revoke`: given,
    it replaces the whole set; left `None`, a plain reinstall carries the
    previous install's set forward unchanged rather than silently revoking
    every working directory the person declared.

    `model_assignments`, when given, is a whole batch of preferences to
    record in the same call that renders them -- the same "record then
    apply" split `models_set` already documents, but for as many agents as a
    caller wants in one call, one snapshot, one render, rather than one
    `install` per agent. Every item is validated (the agent is configurable,
    the model spec parses) before anything is recorded: an invalid item
    refuses the whole batch, names the offending agent and why, and writes
    nothing -- neither to the model-assignment store nor to disk. Unlike
    `mcp`/`granted`, `None` here does not mean "carry the previous set
    forward": model assignments already live in their own store, read fresh
    on every render regardless of this parameter, so there is no equivalent
    "silence retires everything" risk for this parameter to guard against --
    `None` simply means this call is not the one changing any assignment.

    `model_removals`, when given, names agents whose assignment should be
    dropped -- `models_unset`'s own batch, folded into this same call rather
    than requiring a second one. The two parameters apply against the same
    in-memory `effective_assignments` before either reaches the store, in
    the order a person would expect a mixed batch to mean: an agent named in
    both is assigned first, then immediately removed, so a removal always
    wins over an assignment for the same agent in the same call rather than
    the two racing against each other. This is what lets the TUI's models
    screen stage several assignments and a removal in one sitting and
    confirm them as one `install()` -- one snapshot, one render -- instead of
    calling `models_set` and `models_unset` separately, which would be two of
    each. A removal is never itself invalid (removing an assignment that was
    never set is a no-op, the same as `models_unset`), so it cannot be the
    offending item an all-or-nothing refusal names -- only `model_assignments`
    can.

    `label` names the intention this call is carrying out, recorded on the
    snapshot generation this run takes (see `core.snapshot.Manifest.label`).
    It defaults to `"install"` because that default is correct for both of
    the callers who ever leave it unnamed -- a bare `pegasus install` and the
    TUI's own Install screen, which really are the plain install this
    default claims to be. Every other caller of this function is doing
    something else in the person's own words -- `"update"`, `"mcp grant"`,
    `"models set"`, and so on -- and passes that word explicitly rather than
    letting this default stand in for it; nothing here reads `sys.argv` or
    the call stack to guess which one applies, because the TUI never goes
    through `argv` at all and would get the wrong answer from either.
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
    # None of this has to be the very first thing, only ahead of the snapshot
    # and the first artifact -- a promise every step below still keeps.
    #
    # `content` is resolved here, ahead of `build`/`render` below, because the
    # Node guard further down needs the chosen servers' distributions -- and
    # reading the content tree is a read, not a write, so doing it this early
    # costs the preflight nothing. `build` and `render` still get exactly one
    # read of it: the object resolved here is the same one passed to them,
    # never reloaded. Resolved before `store.ensure_writable()` on purpose: a
    # typo in `--mcp` is a mistake the user just made and can fix on the spot,
    # which is more actionable than a filesystem permission fact, so it is the
    # one they see when both are true at once.
    content = _select_mcp(mcp)
    store = journal_store(runtime)
    store.ensure_writable()
    snapshot = snapshot_store(runtime)
    snapshot.ensure_writable()
    journal = store.load()
    # `installed` has to exist before the Node guard can ask it anything: the
    # guard needs to tell "this run would fetch it" apart from "this run would
    # just keep what is already there", and that distinction lives in the
    # journal. Reading it here, ahead of `build`/`render`, costs the preflight
    # nothing new -- `plan` below already needed this same lookup, so this
    # only moves an existing read earlier rather than adding one.
    installed = journal_module.install_for(journal, adapter.id)
    # A bare `install` (`mcp is None`, meaning `--mcp` was never given on the
    # command line -- an empty list from `--mcp none` is a different, explicit
    # thing) against an installation that already has a recorded MCP
    # selection is the exact damage this guard exists to prevent: silence
    # about `--mcp` means select nothing, so a plain reinstall run for an
    # unrelated reason (a config drift fix, a new agent) would otherwise
    # retire every MCP server, convention file and binding this install ever
    # recorded, and still report success, because from `install`'s own point
    # of view retiring an unnamed server is the documented contract, not a
    # failure. `update` is unaffected: it always calls `install` with an
    # explicit reconstruction of that same selection (see `_mcp_update_selection`),
    # so `mcp` is never `None` on its path, no matter what it reconstructs --
    # this checks `mcp is None`, never the selection's own emptiness, so
    # `update`'s explicit empty selection (a first install with no MCP
    # servers at all) sails through exactly as it always has. A first
    # install, or one already recorded with an empty selection, has nothing
    # to lose either, so `installed is None` and an empty reconstruction both
    # fall through untouched -- see `UnaffectedInstallsTest` for both cases.
    #
    # `dry_run` is exempt from the refusal itself: this guard exists to stop
    # silent damage, and a dry run writes nothing -- there is no damage here
    # to stop, silent or otherwise. It is also the one command that lets a
    # person ask "what would you retire?" before deciding anything, and a
    # bare `install --dry-run` is exactly how someone would go looking for
    # that answer after hearing about this very guard; refusing it would
    # delete the only way to ask. So a dry run still reports the plan
    # (`retired` and all) exactly as it did before this guard existed, but
    # carries `mcp_warnings` -- the same advisory-prose convention
    # `model_warnings`/`grant_warnings` already use below -- naming that a
    # real run would refuse, so nobody is surprised by the refusal one
    # command later.
    mcp_warnings: list[str] = []
    if mcp is None and installed is not None:
        recorded_selection, recorded_unresolved = _mcp_update_selection(
            installed, display_name=runtime.identity.display_name
        )
        if recorded_selection or recorded_unresolved:
            named = ", ".join(sorted({*recorded_selection, *recorded_unresolved}))
            message = (
                f"{adapter.id} already has an mcp selection recorded ({named}), and a bare "
                f"install with no --mcp would silently retire all of it -- every install names "
                f"its whole selection explicitly, so this refuses instead of guessing. Run "
                f"`{runtime.identity.program_name} update --cli {adapter.id}` to keep the recorded "
                f"selection, pass --mcp ... to change it, or pass --mcp none to revoke it on purpose"
            )
            if not dry_run:
                raise CommandError(message)
            mcp_warnings = [f"a real (non-dry) run would refuse: {message}"]
    # `model_assignments`, validated and folded into an in-memory view of the
    # store before anything downstream reads it -- `_resolve_model_overrides`
    # below reads `effective_assignments`, never the store directly, so a dry
    # run previews exactly what a real run would render. Every item is
    # checked before any of them are applied: an invalid one raises here,
    # before `effective_assignments` differs from the stored one at all, so a
    # batch that fails never gets even a partial write. The store itself is
    # only touched later, once this run is known not to be a dry run and
    # everything else has already succeeded -- see the write near the end of
    # this function.
    stored_assignments = model_assignment_store(runtime).load()
    effective_assignments = stored_assignments
    if model_assignments is not None:
        parsed_assignments: list[tuple[str, ModelAssignment]] = []
        for spec in model_assignments:
            _require_configurable_agent(spec.agent)
            try:
                parsed = ModelAssignment.parse(spec.model, spec.effort)
            except ValueError as error:
                raise CommandError(f"invalid model assignment for {spec.agent!r}: {error}") from error
            parsed_assignments.append((spec.agent, parsed))
        for agent, parsed in parsed_assignments:
            effective_assignments = model_assignments_module.with_assignment(
                effective_assignments, adapter.id, agent, parsed
            )
    if model_removals is not None:
        for agent in model_removals:
            effective_assignments = model_assignments_module.without_assignment(
                effective_assignments, adapter.id, agent
            )
    # Resolved here, once `installed` is known, and applied before anything
    # downstream reads `content` again -- the Node guard included, since a
    # granted key never carries a distribution to fetch and so never changes
    # its answer, but every reader from here on must see the final agents.
    granted_keys = tuple(granted) if granted is not None else (installed.granted_mcp if installed is not None else ())
    # Every key already on the previous install's own `granted_mcp` is a key
    # nobody named in this call -- it is only here because a plain `install`
    # (and `update`, which replays a previous install verbatim) carries the
    # whole set forward unasked. A key outside that previous set is new to
    # this call -- the argument `mcp_grant` just added, say -- and a
    # collision there is a real contradiction in what was just asked for.
    # See `grant_mcp`'s own docstring for why only the carried-forward half
    # may be silently dropped.
    previously_granted = frozenset(installed.granted_mcp) if installed is not None else frozenset()
    droppable_grants = frozenset(granted_keys) & previously_granted
    try:
        content, dropped_grants = content_module.grant_mcp(content, granted_keys, droppable=droppable_grants)
    except content_module.ContentError as error:
        raise CommandError(str(error)) from error
    # A dropped key must never reach the journal: `grant_mcp` already left it
    # out of the rendered `granted_mcp`, and recording it anyway would be
    # exactly the journal-vs-render drift this codebase treats as a bug in
    # itself, not a cosmetic mismatch.
    if dropped_grants:
        granted_keys = tuple(key for key in granted_keys if key not in dropped_grants)
    grant_warnings = [
        f"{key!r} was already granted per-agent (a shipped mcp server or a key now bound by "
        f"this install's own --mcp selection); the carried-forward grant to every agent is "
        f"redundant and was dropped -- the server is still reachable through the agents that "
        f"declare it, and `{runtime.identity.program_name} mcp grant --cli {adapter.id} {key}` re-adds it explicitly "
        f"if that is not what you wanted"
        for key in dropped_grants
    ]
    # Same default-carries-forward rule `granted_keys` above already applies
    # to `granted_mcp`, for `granted_directories`. No collision to drop here:
    # see `content.grant_directories`'s own docstring for why a directory
    # grant shares no namespace with anything else this install renders.
    directory_keys = (
        tuple(granted_directories)
        if granted_directories is not None
        else (installed.granted_directories if installed is not None else ())
    )
    try:
        content = content_module.grant_directories(
            content, directory_keys, config_dir=layout.config_dir, data_dir=runtime.filesystem.data_dir(runtime.home)
        )
    except content_module.ContentError as error:
        raise CommandError(str(error)) from error
    _require_node_if_needed(content, runtime, installed)
    # Asked before anything is written, so an adapter that cannot answer costs a
    # message instead of a traceback over a finished installation.
    activation = list(adapter.activation_steps())

    catalog = catalog_module.build(content, adapter, runtime.identity)
    model_overrides, model_warnings = _resolve_model_overrides(effective_assignments, adapter, environment, content)
    artifacts = catalog_module.render(
        content, adapter, environment, runtime.identity, model_overrides=model_overrides
    )
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
        # A `download`/`npm` server has no artifact for `plan` to have
        # decided the fate of -- it is materialized outside the catalog
        # pipeline entirely, and only a real run's `_materialize_dependencies`
        # would otherwise have anything to say about it (see
        # `_previewed_dependencies`'s own docstring). Read-only, so a dry
        # run costs no fetch either.
        kept_dependencies, previewed_dependencies = _previewed_dependencies(
            runtime, layout, content, installed
        )
        return {
            "cli": adapter.id,
            "status": "planned",
            "activation": activation,
            "created": [_placed(step) for step in plan.creations] + list(previewed_dependencies),
            "updated": [_placed(step) for step in plan.updates],
            "unchanged": [_placed(step) for step in plan.unchanged]
            + [_recorded(record) for record in kept_dependencies],
            "overwritten": [_placed(step) for step in plan.overwritten],
            "skipped": [_left(step) for step in plan.collisions],
            "retired": [_recorded(record) for record in retirements],
            "model_warnings": list(model_warnings),
            "grant_warnings": grant_warnings,
            "mcp_warnings": mcp_warnings,
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

    # Every phase this run can touch, added up before the first one starts, so
    # the caller can render a real denominator from the very first tick. Only
    # the application layer can know this: it is the one place holding the
    # plan, the dependency set and the retirement set all at once. The `+ 2`
    # is the pre-write snapshot and the journal write below, each a single
    # unit regardless of how many bytes it happens to move.
    total_units = len(plan.placements) + len(dependency_targets) + len(retirements) + 2
    progress_done = 0

    def _tick(phase: str, unit: str) -> None:
        nonlocal progress_done
        progress_done += 1
        on_progress(Progress(done=progress_done, total=total_units, phase=phase, unit=unit))

    def _download_tick(name: str, bytes_downloaded: int, bytes_total: int | None) -> None:
        # `progress_done` is read, never advanced, here: a byte-level tick is
        # progress *inside* the unit currently being fetched, not a sibling
        # of the whole-unit ticks `_tick` emits once that fetch finishes --
        # advancing it here would let `done` reach `total` before the fetch,
        # verification and placement `_tick("dependencies", name)` actually
        # reports are done.
        on_progress(
            Progress(
                done=progress_done,
                total=total_units,
                phase="dependencies",
                unit=name,
                bytes_downloaded=bytes_downloaded,
                bytes_total=bytes_total,
            )
        )

    if on_progress is not None:
        on_progress(Progress(done=0, total=total_units, phase="snapshot", unit=""))

    try:
        snapshot.save(
            capture_paths(runtime.filesystem, touched, directories=frozenset(dependency_targets)),
            taken_at=runtime.now,
            label=label,
        )
    except SnapshotStoreError as error:
        raise CommandError(
            f"a snapshot of what this install is about to overwrite could not be taken, "
            f"so nothing was written: {error}"
        ) from error
    if on_progress is not None:
        _tick("snapshot", "snapshot")

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
        kept_dependencies, new_dependencies = _materialize_dependencies(
            runtime,
            layout,
            content,
            installed,
            on_step=(lambda name: _tick("dependencies", name)) if on_progress is not None else None,
            on_download_progress=_download_tick if on_progress is not None else None,
        )
    except dependencies_module.MaterializeError as error:
        raise CommandError(str(error)) from error

    applied = planner.apply(
        runtime.filesystem,
        plan,
        at=runtime.now,
        on_step=(lambda name: _tick("artifacts", name)) if on_progress is not None else None,
    )
    config_dir = layout.config_dir
    dependency_records = kept_dependencies + new_dependencies
    all_records = applied.records + dependency_records

    # Two views of the same install, and confusing them is expensive. The merged
    # one is what gets recorded: everything this CLI owns, old and new. The
    # placed one is only what this run wrote, and it is the only thing a rollback
    # may touch — undoing the merged view would delete a working installation
    # that this run never even created. `created_dirs` follows the same split:
    # `placed` carries only what *this run's* `apply` reported making, because
    # `unplace` below may only prune what this run itself created, never a
    # directory an earlier, already-successful install put there.
    placed = Install(
        cli=adapter.id,
        installed_at=runtime.now,
        config_dir=config_dir,
        release={},
        entries=all_records,
        created_dirs=applied.created_dirs,
    )
    # The wider registry `retire`, below, needs for `retirements` -- entries an
    # *earlier* install owned and this render no longer asks for. Those
    # directories were never touched by this run, so `placed.created_dirs`
    # alone would never authorise pruning any of them; the previous install's
    # own registry is what remembers they were ever Pegasus's to begin with.
    historical_created_dirs = tuple(
        dict.fromkeys((*(installed.created_dirs if installed is not None else ()), *applied.created_dirs))
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
        stale = planner.retire(
            runtime.filesystem,
            replace(placed, entries=retirements, created_dirs=historical_created_dirs),
            on_step=(lambda name: _tick("retire", name)) if on_progress is not None else None,
        )
    except (FileSystemError, planner.PlannerError) as error:
        removed, pruned, failures = _undo_placements(runtime.filesystem, applied, placed)
        _undo_dependencies(runtime.filesystem, new_dependencies)
        left = _left_behind(runtime.filesystem, documents - existing)
        raise _unretirable(
            error,
            left,
            placed=len(applied.records),
            replaced=len(applied.replaced),
            failures=failures,
            removed=removed,
            pruned=pruned,
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
        journal,
        adapter,
        environment,
        catalog,
        all_records + applied.reconciled,
        stale.removed,
        runtime.now,
        content,
        granted_keys,
        runtime.identity.version,
        applied.created_dirs,
        # `Retired.pruned` names directories relative to the configuration
        # root, because that is what a report should read like; the journal
        # records absolute paths, so they are joined back on here.
        tuple(placed.config_dir / relative for relative in stale.pruned),
        granted_directories=directory_keys,
    )
    try:
        store.save(journal_module.with_install(journal, merged))
        if on_progress is not None:
            _tick("journal", "journal")
    except JournalStoreError as error:
        removed, pruned, failures = _undo_placements(runtime.filesystem, applied, placed)
        _undo_dependencies(runtime.filesystem, new_dependencies)
        left = _left_behind(runtime.filesystem, documents - existing)
        raise _unrecordable(
            error,
            left,
            placed=len(applied.records),
            replaced=len(applied.replaced),
            failures=failures,
            removed=removed,
            pruned=pruned,
            retired=list(stale.removed),
        ) from error

    # The model-assignment batch is persisted only now, after everything else
    # this run does has already succeeded -- the journal write above
    # included. Every earlier failure path in this function returns or raises
    # before reaching here, so a run that fails partway leaves the store
    # exactly as it was, never holding a preference the render it was meant
    # to reach never happened for.
    if model_assignments is not None or model_removals is not None:
        model_assignment_store(runtime).save(effective_assignments)

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
        # `uninstall` has always reported this; `install`/`update` retire the
        # same way (see the `stale = planner.retire(...)` call above, for what
        # the current render no longer asks for) but silently dropped
        # `stale.pruned` on the floor, so a directory could disappear here
        # with nothing in the report to say so.
        "pruned": list(stale.pruned),
        "journal": str(store.path),
        "retention": _retain(snapshot),
        "model_warnings": list(model_warnings),
        "grant_warnings": grant_warnings,
    }


def _update(arguments, runtime: Runtime) -> dict[str, Any]:
    return update(arguments.cli, runtime, dry_run=arguments.dry_run)


def update(
    cli_id: str,
    runtime: Runtime,
    *,
    dry_run: bool = False,
    on_progress: Callable[["Progress"], None] | None = None,
) -> dict[str, Any]:
    """Reapply an installation's own `--mcp` selection and granted mcp keys,
    with no flags.

    A bare reinstall names nothing, and naming nothing retires every server
    not repeated on the command line -- so updating used to mean remembering
    and repeating the exact selection an earlier `install` was given, and a
    bound server's selection cannot even be read back from the rendered
    configuration: a binding writes no `/mcp/<id>` key there, only its
    convention. This reads the recorded installation instead and reconstructs
    the selection from it, then delegates to `install` for everything else --
    there is no second implementation of placing artifacts here, only the
    computation of what `--mcp` would have been.

    `granted_mcp` needs no reconstruction the way `--mcp` does: it already
    lives on the journal verbatim, so it is simply passed through -- but it
    is passed explicitly rather than left to `install`'s own default, because
    a bare `install` call defaults to "carry the previous install forward"
    and this *is* that previous install, so passing it through here keeps
    the two call sites saying the same thing for the same reason rather than
    one relying on a default the other cannot rely on. `granted_directories`
    is passed through for the identical reason.
    """
    adapter = _adapter(cli_id)
    installed = journal_module.install_for(journal_store(runtime).load(), adapter.id)
    if installed is None:
        raise CommandError(
            f"{adapter.id} has nothing installed to update; run install instead"
        )
    selection, unresolved = _mcp_update_selection(installed, display_name=runtime.identity.display_name)
    if unresolved:
        raise CommandError(
            unresolved_bindings_message(adapter.id, unresolved, program_name=runtime.identity.program_name)
        )
    return install(
        cli_id,
        runtime,
        dry_run=dry_run,
        mcp=selection,
        granted=list(installed.granted_mcp),
        granted_directories=list(installed.granted_directories),
        label="update",
        on_progress=on_progress,
    )


def _mcp_update_selection(install: Install, *, display_name: str) -> tuple[list[str], list[str]]:
    """The `--mcp` selection this install already embodies, and the ids
    `update` cannot safely reapply because their key was never recorded.

    Reuses `_mcp_entries` and `_bound_checks` -- the same classification
    `doctor` already draws between a server this install configured on its
    own and one it was only granted against a key it does not administer --
    rather than deriving it a third time. `display_name` only reaches
    `_bound_checks`'s own `ServerCheck.detail`, which this function never
    reads back (only `check.id` does) -- but every caller here already has a
    `Runtime` in reach, so there is no reason left to default it and risk a
    future reader of `.detail` seeing the packaged identity's own name
    instead of the caller's.

    `_bound_checks` no longer names a server this CLI never writes a config
    key for at all (`CliAdapter.writes_mcp_config_key` is `False`) unless it
    is a genuine, recorded binding -- that shape is this CLI's ordinary one
    for a server Pegasus obtained and administers itself, not a binding and
    not something `update` should refuse over. This still has to reapply
    that server's own grant, though, so it is picked up in the second pass
    below, straight off the journal's convention entries, and rejoins the
    selection the same bare way `--mcp <id>` would have spelled it in the
    first place -- never into `unresolved`, since there is no missing key to
    wait on.
    """
    configured = {name for _, name in _mcp_entries(install)}
    selection = [name for _, name in _mcp_entries(install)]
    unresolved = []
    accounted = set(configured)
    for check in _bound_checks(install, display_name=display_name):
        accounted.add(check.id)
        key = install.mcp_bindings.get(check.id)
        if key is None:
            unresolved.append(check.id)
        else:
            selection.append(f"{check.id}={key}")
    for entry in install.entries:
        if not entry.id.startswith(_MCP_CONVENTION_PREFIX):
            continue
        name = entry.id[len(_MCP_CONVENTION_PREFIX):]
        if name in accounted:
            continue
        # Reached only for a name `_bound_checks` skipped outright: this CLI
        # never writes a `/mcp/<id>` key for any server, and no binding was
        # recorded for this one either, so it is a normal grant, not a gap.
        selection.append(name)
    return selection, sorted(unresolved)


def update_unresolved_bindings(install: Install, *, display_name: str) -> list[str]:
    """The mcp ids `update(cli_id, ...)` would refuse this install over,
    without actually calling `update` -- the same classification
    `_mcp_update_selection` already draws, reused rather than duplicated.

    Built for `session` (the TUI's engine bridge), which has to decide
    whether to recommend `Update` at all *before* letting someone choose it,
    so the local update notice and this module's own refusal can never
    disagree about whether `update` would succeed. `display_name` is
    `runtime.identity.display_name` -- `session` always has a `Runtime` in
    reach here, so this asks for it explicitly rather than defaulting to
    the packaged identity's own.
    """
    _, unresolved = _mcp_update_selection(install, display_name=display_name)
    return unresolved


def recorded_mcp_selection(install: Install, *, display_name: str) -> list[str]:
    """The `--mcp` selection this install already embodies, spelled the way
    `install` itself reads it -- `id=key` for a server this installation
    administers under a key of its own, the bare `id` for one Pegasus
    obtains and administers.

    `update_unresolved_bindings`' twin: the other half of the pair
    `_mcp_update_selection` returns, exposed for the same caller and the
    same reason. `session` (the TUI's engine bridge) opens its selection
    screen on exactly this, so the checklist a person is shown and the
    selection `update` would reapply can never disagree about what this
    installation's selection is. They did disagree while the screen derived
    it on its own from `mcp:<id>` journal entries: a bound server writes no
    such entry (see `_bound_checks`), so every binding rendered unchecked
    and sat one Continue away from being retired.

    Ids whose key was never recorded are *not* here -- they are exactly
    `update_unresolved_bindings`' answer, and a caller that offers this
    selection as reproducible has to ask that question too before trusting
    this one.
    """
    selection, _ = _mcp_update_selection(install, display_name=display_name)
    return selection


def install_command_for(cli_id: str, ids: list[str], *, program_name: str) -> str:
    """The exact `install` invocation that would (re)record a key for each
    of ``ids``, one placeholder per id, built from the ids actually
    affected rather than from a hardcoded example.

    Public rather than the `_install_command_for` it used to be: `session`
    (the TUI's engine bridge) reuses it to build the same remedy command the
    local update notice names, so that notice and this module's own refusal
    can never disagree about what the fix is. `program_name` has no default:
    `session` used to be called with no `Runtime` in reach at all, which is
    why this once fell back to the packaged identity's own program, but
    `session` now always has `runtime.identity` in reach and passes
    `runtime.identity.program_name` explicitly -- a caller that forgets to
    thread it through now fails at the call site instead of silently naming
    the wrong product in a distribution's remedy command.
    """
    flags = " ".join(f"--mcp {name}=<key>" for name in ids)
    return f"{program_name} install --cli {cli_id} {flags}"


def mcp_placeholder_instruction() -> str:
    """The one explicit instruction both `update`'s refusal
    (:func:`unresolved_bindings_message`) and `doctor`'s matching line give
    beside :func:`install_command_for`'s command.

    Copying that command verbatim -- a very common habit -- runs the literal
    string ``<key>`` straight into `parse_mcp_choice`, which rejects it with
    a cryptic ``'<key>' is not usable as a server key`` rather than anything
    that explains what to do. Defined once so the two messages that show the
    command cannot drift apart on how they explain it.
    """
    return "replacing each <key> placeholder below with that server's actual key, which lives in the CLI's own configuration"


def unresolved_bindings_message(cli_id: str, ids: list[str], *, program_name: str) -> str:
    """The one wording every surface that refuses over an unresolved binding
    says it with -- `update`, `mcp grant`/`mcp revoke`, `mcp list`'s own
    `blocked`, and the TUI's install selection screen, which cannot
    reproduce a binding whose key was never recorded either.

    Public rather than the `_unresolved_bindings_message` it used to be, for
    the same reason `install_command_for` and `update_unresolved_bindings`
    already are: `session` (the TUI's engine bridge) reuses it, so the
    screen's blocker and this module's own refusal can never become two
    phrasings of one fact.
    """
    command = install_command_for(cli_id, ids, program_name=program_name)
    return (
        f"{cli_id} has bound mcp server(s) {', '.join(ids)} whose server key was never recorded "
        f"(an install made before this was tracked); update cannot reapply them without guessing, "
        f"and guessing would retire the very binding it exists to preserve. Run this once instead, "
        f"{mcp_placeholder_instruction()}:\n"
        f"  {command}\n"
        f"After that one run, update needs no flags ever again. doctor lists the bound ids."
    )


# --- Checking for a newer release ------------------------------------------
#
# This never touches the binary itself -- it only answers "is there a newer
# one published", so the TUI can say so. Fetching and replacing the running
# executable is a separate concern this module does not implement.

# The one remote fact this whole check exists to learn -- the tag of the
# newest published release -- used to live here as a module-level constant,
# always Pegasus's own address. It is gone, not defaulted: every reader below
# now reads `runtime.identity.release.latest_release_api_url` instead, the
# same `ReleaseSource` `upgrade` itself fetches from (see D4 in this change's
# design), so there is no shared literal a distribution's check could ever
# fall back to. Unauthenticated, which is what makes the TTL below matter --
# GitHub rate-limits anonymous callers per source IP, not per install, so a
# check run on every launch would be shared across however many machines sit
# behind the same address.

#: This lookup runs in the background on every TUI launch, unlike an MCP
#: archive download the user is actively waiting on -- `Downloader`'s own
#: default (30s, tuned for a multi-megabyte archive over a slow link) is
#: much too long to leave a worker thread alive answering a question nobody
#: asked yet. A GitHub API JSON response is a few hundred bytes; if it has
#: not arrived within a handful of seconds the network is not going to
#: produce one soon, so there is nothing to gain by waiting longer.
UPDATE_CHECK_TIMEOUT_SECONDS = 5

#: How long a cached answer is trusted before asking again. A release does
#: not appear more than a few times a year, so this trades a day of possible
#: staleness for never touching the network on an ordinary launch -- long
#: enough to matter for the rate limit above, short enough that a person
#: still learns about a new release within a day of it shipping.
UPDATE_CHECK_TTL_SECONDS = 24 * 60 * 60

#: How long a *failed* lookup is trusted before trying again -- deliberately
#: much shorter than the success TTL above. The tension is real: too short
#: and a machine with no network at all keeps paying the timeout on every
#: launch; too long and someone who just got back online keeps being told
#: nothing for a while after they would already get an answer. One hour
#: means an offline user pays the short timeout at most once an hour instead
#: of on every single launch (which is the whole defect this exists to fix),
#: while someone who reconnects mid-session is never more than an hour from
#: the check working again -- short enough that it is not a noticeable wait
#: against a TTL that already tolerates a day of staleness on success.
UPDATE_CHECK_FAILURE_TTL_SECONDS = 60 * 60

#: The cache's own filename under `runtime.filesystem.data_dir(...)` --
#: Pegasus's own data, same as the journal and snapshot generations, never
#: anything written into a CLI's configuration.
_UPDATE_CACHE_NAME = "update-check.json"


def _update_cache_path(runtime: Runtime) -> Path:
    return runtime.filesystem.data_dir(runtime.home) / _UPDATE_CACHE_NAME


def _read_update_cache(runtime: Runtime) -> dict[str, Any] | None:
    """The last answer this machine got, or `None` for anything short of a
    clean read -- absent, unreadable, or not the JSON object this writes.
    A cache is an optimization; failing to read one back is never this
    function's problem to raise about."""
    path = _update_cache_path(runtime)
    try:
        if not runtime.filesystem.exists(path):
            return None
        document = json.loads(runtime.filesystem.read_bytes(path).decode("utf-8"))
    except (FileSystemError, ValueError, UnicodeDecodeError):
        return None
    return document if isinstance(document, dict) else None


def _write_update_cache(
    runtime: Runtime, cache: dict[str, Any] | None, *, latest_version: str | None, succeeded: bool
) -> None:
    """Best effort: a cache that fails to write leaves the next launch
    checking again, which is a slower day, never a broken one.

    Starts from whatever the previous cache held so a failure never erases a
    version a previous success already learned -- only the field for the
    outcome that just happened moves. A success also clears any pending
    failure timestamp: the thing the failure entry existed to suppress (a
    retry) is no longer a concern once a fetch has actually gone through.
    """
    payload: dict[str, Any] = dict(cache or {})
    payload["latest_version"] = latest_version
    if succeeded:
        payload["success_checked_at"] = runtime.now
        payload.pop("failure_checked_at", None)
    else:
        payload["failure_checked_at"] = runtime.now
    encoded = json.dumps(payload).encode("utf-8")
    try:
        runtime.filesystem.write_atomic(
            _update_cache_path(runtime), encoded, mode=runtime.filesystem.mode_for(executable=False)
        )
    except FileSystemError:
        pass


def _timestamp_is_fresh(cache: dict[str, Any], runtime: Runtime, *, key: str, ttl_seconds: float) -> bool:
    value = cache.get(key)
    if value is None:
        return False
    try:
        then = datetime.fromisoformat(value)
        now = datetime.fromisoformat(runtime.now)
    except (TypeError, ValueError):
        return False
    return (now - then).total_seconds() < ttl_seconds


def check_for_update(runtime: Runtime) -> str | None:
    """The newest published release's version, or `None`.

    `None` is the answer to every one of these, indistinguishably: the check
    is switched off, there is no cache and the network could not be reached,
    the response was not the shape expected, or anything else at all went
    wrong. A version check that surfaces an error is worse than one that says
    nothing -- nobody asked this question, the TUI just wanted to mention the
    answer if it already had one -- so this catches everything broad on
    purpose rather than naming every way a JSON body over HTTP can misbehave.

    Reads the off switch through `runtime.variables`, the same seam every
    other engine function reads the environment through, never `os.environ`
    directly.
    """
    # A stable wire identifier, like `PEGASUS_SKILL_REGISTRY_BIN`/
    # `PEGASUS_SKILL_ROOTS` (`adapters/opencode/adapter.py`) -- an operator
    # who already has this set in their shell must not lose the off switch
    # the moment a build's identity changes, so this name is never
    # parameterized on `identity.product_id`.
    if runtime.variables.get("PEGASUS_NO_UPDATE_CHECK"):
        return None
    cache = _read_update_cache(runtime)
    if cache is not None and _timestamp_is_fresh(
        cache, runtime, key="failure_checked_at", ttl_seconds=UPDATE_CHECK_FAILURE_TTL_SECONDS
    ):
        return cache.get("latest_version")
    if cache is not None and _timestamp_is_fresh(
        cache, runtime, key="success_checked_at", ttl_seconds=UPDATE_CHECK_TTL_SECONDS
    ):
        return cache.get("latest_version")
    try:
        payload = runtime.downloader.fetch(
            runtime.identity.release.latest_release_api_url, timeout_seconds=UPDATE_CHECK_TIMEOUT_SECONDS
        )
        document = json.loads(payload.decode("utf-8"))
        tag = document["tag_name"]
        if not isinstance(tag, str) or not tag:
            raise ValueError("empty or non-string tag_name")
        latest_version = tag[1:] if tag[0] in "vV" else tag
    except Exception:  # noqa: BLE001 -- every failure here means silence, see docstring above.
        previous_version = cache.get("latest_version") if cache is not None else None
        _write_update_cache(runtime, cache, latest_version=previous_version, succeeded=False)
        return previous_version
    _write_update_cache(runtime, cache, latest_version=latest_version, succeeded=True)
    return latest_version


# --- Replacing the running binary -------------------------------------------
#
# `upgrade` is deliberately not `update`: `update` reapplies an installation's
# own recorded selection into a CLI's configuration, and never touches the
# `pegasus` program itself. This replaces the program -- there is no `--cli`,
# because there is no installation to name.
#
# A running process keeps the inode of the file it started from, so the
# process that just reported "upgraded" is still running the old code in
# memory -- restarting is the one thing this can never do for itself, which
# is why every success report says so.


def _running_binary_path(runtime: Runtime) -> Path | None:
    """Where the executing `pegasus` binary actually lives on disk, or
    `None` when this process is not running from one at all.

    `runtime.sys_path0` is `sys.path[0]` as the real interpreter set it (see
    `Runtime.sys_path0`'s own docstring for why it is read through here
    rather than from `sys` directly). For a zipapp -- built by
    `tools/build_zipapp.py`, invoked through its shebang or as `python3
    <path>` -- Python sets this to the exact path the archive was given as,
    and that path is a real zip file `zipfile.is_zipfile` recognises; for
    `python3 -m pegasus` (this repo's own test suite, and a `PYTHONPATH=src`
    manual check) it is the current directory, and for a plain script it is
    the script's own containing directory, neither of which is ever a zip.
    `zipfile.is_zipfile` is what tells the two apart -- not the path's own
    shape, since a relative path, a symlink, or a directory can each appear
    on either side of that question.

    `os.path.realpath` resolves whatever `sys_path0` handed over -- a
    relative path (`./pegasus`), a symlink, or anything else that is not
    already the binary's own canonical location -- to the one real file
    `write_atomic`'s eventual `os.replace` has to land on.
    """
    candidate = runtime.sys_path0
    if not candidate or not zipfile.is_zipfile(candidate):
        return None
    return Path(os.path.realpath(candidate))


def _manual_upgrade_command(
    destination: Path, release: upgrade_module.ReleaseSource, *, choose_version: bool = False
) -> str:
    """The manual fallback for a refusal that will not install anything
    itself.

    `choose_version` exists for exactly one caller: the downgrade refusal.
    That refusal fires because the newest published release is the *older*
    one, so telling that person to "download the newest release" would send
    them straight back to the version they were just refused -- the release
    page lists every version, so this points there to pick one instead of
    repeating "the newest release". The other two refusals (unwritable
    destination, wrong owner) have no such conflict -- the newest release is
    exactly what they would want -- so they keep the original wording.
    """
    source = (
        f"visit {release.release_page_url} and pick whichever release you actually want"
        if choose_version
        else f"download the newest release from {release.release_page_url}"
    )
    return (
        f"{source}, verify it against its published {release.binary_asset}.sha256, then place it over "
        f"{destination} yourself (as whichever user can write there -- root or sudo, if that is "
        f"what installed it)"
    )


_NUMERIC_VERSION = re.compile(r"\A\d+(\.\d+)*\Z")
r"""The one shape `_numeric_version_key` can order: one or more dot-separated
runs of digits, nothing else -- `"6.0.0"`, `"2024.03"`, `"10"`. `SAFE_VERSION`
(`pegasus.core.identity`) is far wider than this on purpose, because
`identity.version` is not semver -- a distribution may call its version
`"beta"`, `"1.0-rc2"`, or anything else `SAFE_VERSION` allows. None of those
match here, and that is intentional: this pattern exists to tell `upgrade`
apart the one shape where "which is newer" can be decided from every other
shape where it cannot."""


def _numeric_version_key(version: str) -> tuple[int, ...] | None:
    """`version` as a tuple of ints for ordering, or `None` when it is not
    the pure `_NUMERIC_VERSION` shape.

    `None` is not "assume equal" or "assume newer" anywhere this is used --
    every caller treats it as "no comparison is possible", full stop.
    """
    if not _NUMERIC_VERSION.match(version):
        return None
    return tuple(int(part) for part in version.split("."))


def _is_older(candidate_version: str, reference_version: str) -> bool:
    """Whether `candidate_version` is provably older than `reference_version`.

    Comparable versions are exactly the ones `_numeric_version_key` accepts:
    pure dot-separated digit runs, the same shape semver's numeric core uses,
    padded on the right with zeros so `"6.0"` and `"6.0.0"` compare equal
    rather than one looking shorter than the other.

    Everything else -- a letter anywhere (`"beta"`), a hyphen or plus
    (`"1.0-rc2"`, `"1.0+build5"`), or any other `SAFE_VERSION`-legal shape
    that is not pure digits-and-dots -- is not comparable, and this returns
    `False` for it rather than guessing. `identity.version` is deliberately
    not semver (see `SAFE_VERSION`'s own docstring), so a distribution's
    `"2024.03"` and a hotfix branch's `"1.0-rc2"` are both legitimate
    versions with no defined order between arbitrary pairs of them. Refusing
    an upgrade on a guess would be worse than the defect this exists to fix:
    it would block every non-numeric distribution's upgrades outright rather
    than catch the one case that is actually provable -- a numeric release
    that is provably behind.
    """
    candidate_key = _numeric_version_key(candidate_version)
    reference_key = _numeric_version_key(reference_version)
    if candidate_key is None or reference_key is None:
        return False
    length = max(len(candidate_key), len(reference_key))
    padded_candidate = candidate_key + (0,) * (length - len(candidate_key))
    padded_reference = reference_key + (0,) * (length - len(reference_key))
    return padded_candidate < padded_reference


def _fetch_latest_version(runtime: Runtime) -> str:
    """The newest published release's version, fetched fresh -- never the
    cache `check_for_update` reads and writes.

    `check_for_update` exists to answer a question nobody asked yet, quietly,
    for a background notice; every one of its failure modes collapses to
    `None` on purpose (see its own docstring). `upgrade` is the opposite: a
    person asked directly, so a network failure here has to say so plainly
    rather than let a stale or absent cache read as "you are already
    current" -- reporting that would be worse than reporting nothing.
    """
    try:
        payload = runtime.downloader.fetch(
            runtime.identity.release.latest_release_api_url, timeout_seconds=UPDATE_CHECK_TIMEOUT_SECONDS
        )
        document = json.loads(payload.decode("utf-8"))
        tag = document["tag_name"]
        if not isinstance(tag, str) or not tag:
            raise ValueError("empty or non-string tag_name")
    except Exception as error:  # noqa: BLE001 -- every shape of failure gets the same honest refusal.
        raise CommandError(
            "could not reach GitHub to check the newest published release -- upgrade refuses to guess, "
            "so it will not report there is nothing new when it simply could not check; try again once "
            "you have network access"
        ) from error
    return tag[1:] if tag[0] in "vV" else tag


def _upgrade(arguments, runtime: Runtime) -> dict[str, Any]:
    return upgrade(runtime, dry_run=arguments.dry_run)


def upgrade(
    runtime: Runtime,
    *,
    dry_run: bool = False,
    on_progress: Callable[["Progress"], None] | None = None,
) -> dict[str, Any]:
    """Replace the running `pegasus` binary with the newest published one.

    Refuses, in this order, before a single byte is ever fetched: not
    running from an installed executable at all; the destination is not
    writable; the destination is owned by someone else; the network cannot
    be reached to learn the newest published version; already at that
    version; the newest published release is provably older than the one
    already running (see `_is_older` for exactly what "provably" means here
    -- when it cannot be proven, this does not refuse, the same as any other
    new tag). Only past every one of those does this fetch anything -- the
    checksum first, then the binary, verified against it
    (`upgrade_module.fetch_and_verify`; "verified" there means
    checksum-matched, not authenticated -- see that module's own docstring
    for exactly what that does and does not protect against) -- and only a
    verified binary ever reaches `upgrade_module.replace_binary`, which
    itself never writes at the final path until one atomic rename, last (see
    that module's own docstring). A mismatch or a failed write leaves the
    binary this process started from untouched -- there is never a moment
    with no working binary on disk.
    """
    destination = _running_binary_path(runtime)
    if destination is None:
        raise CommandError(
            f"{runtime.identity.program_name} is not running from an installed executable -- this looks "
            f"like a source checkout, not the zipapp the release ships, so there is no binary here for "
            f"upgrade to replace"
        )
    if not runtime.filesystem.is_writable(destination):
        raise CommandError(
            f"{destination} is not writable by this process; upgrade refuses to download anything it "
            f"could not then install. Instead, {_manual_upgrade_command(destination, runtime.identity.release)}."
        )
    # `is_writable` only ever asks whether the containing directory would
    # accept the rename (see its own docstring) -- it says nothing about who
    # owns the file already there, so a separate, explicit check is what
    # refuses to silently take over someone else's binary. `os.replace`
    # would otherwise swap it in without a trace of whose file it used to
    # be, handing its ownership to whoever happened to run this upgrade.
    if not runtime.filesystem.owned_by_current_user(destination):
        raise CommandError(
            f"{destination} is not owned by the user running this upgrade; {runtime.identity.program_name} "
            f"refuses to silently take over someone else's file. Instead, "
            f"{_manual_upgrade_command(destination, runtime.identity.release)}."
        )
    current_version = runtime.identity.version
    latest_version = _fetch_latest_version(runtime)
    if latest_version == current_version:
        # Being current already is not a refusal -- it is exactly what asking
        # to be current was for, the same way `install`/`update` count files
        # that needed no change as "already current" rather than a failure,
        # and `models unset` reports `"already-unset"` rather than raising
        # when there was nothing to remove. A person who is already running
        # the newest release did not fail to upgrade; there was simply
        # nothing left to do.
        return {"status": "already-current", "version": current_version, "destination": str(destination)}
    if _is_older(latest_version, current_version):
        # Caught here, before `dry_run` is even consulted: proposing a
        # downgrade in a plan is the same defect wearing a different status.
        # This is what actually happened to the real distribution that
        # measured this defect -- a binary at 6.0.0 whose repository's
        # `latest` release was tagged 2.0.0.
        raise CommandError(
            f"the newest published release ({latest_version}) is older than the version already running "
            f"({current_version}); upgrade refuses to install something older than what is already here. "
            f"If you want {latest_version} anyway, "
            f"{_manual_upgrade_command(destination, runtime.identity.release, choose_version=True)}."
        )
    if dry_run:
        return {
            "status": "planned",
            "old_version": current_version,
            "new_version": latest_version,
            "destination": str(destination),
            "restart_required": True,
        }
    if on_progress is not None:
        on_progress(Progress(done=0, total=3, phase="checksum", unit=""))
    try:
        content = upgrade_module.fetch_and_verify(runtime.downloader, latest_version, runtime.identity.release)
    except upgrade_module.UpgradeError as error:
        raise CommandError(str(error)) from error
    if on_progress is not None:
        on_progress(Progress(done=2, total=3, phase="binary", unit=latest_version))
    try:
        upgrade_module.replace_binary(runtime.filesystem, destination, content)
    except upgrade_module.UpgradeError as error:
        raise CommandError(str(error)) from error
    if on_progress is not None:
        on_progress(Progress(done=3, total=3, phase="replace", unit=str(destination)))
    return {
        "status": "upgraded",
        "old_version": current_version,
        "new_version": latest_version,
        "destination": str(destination),
        "restart_required": True,
        "program_name": runtime.identity.program_name,
    }


def _resolve_model_overrides(
    assignments: model_assignments_module.ModelAssignments,
    adapter,
    environment: Environment,
    content: content_module.Content,
) -> tuple[dict[str, str], tuple[str, ...]]:
    """Which stored model preferences this install can actually honour.

    Soft failure lives entirely in `model_assignments.resolve_for_render`; this
    is only the plumbing that gathers what it needs. An adapter that never
    declared `per_agent_model` has nothing to resolve and nothing to warn
    about -- the capability was never offered, so a preference for it could
    never have been set through `models set` in the first place.

    `assignments` is passed in rather than read off the store here: `install`
    computes it once, as `effective_assignments` -- the stored set with this
    call's own `model_assignments` batch folded in, before any of it is
    written -- so a dry run previews the batch this call would record, not
    only what an earlier call already persisted.
    """
    if not adapter.capabilities().declares(Capability.PER_AGENT_MODEL):
        return {}, ()
    configurable = frozenset(agent.name for agent in content.agents if agent.model_configurable)
    catalog = adapter.model_catalog(environment)
    return model_assignments_module.resolve_for_render(assignments, adapter.id, configurable, catalog)


def _merged(
    journal,
    adapter,
    environment,
    catalog,
    records,
    retired_ids,
    now: str,
    content,
    granted_mcp: tuple[str, ...],
    version: str,
    created_dirs: tuple[Path, ...] = (),
    pruned_dirs: tuple[Path, ...] = (),
    granted_directories: tuple[str, ...] = (),
) -> Install:
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

    ``mcp_bindings`` is not merged the way ``entries`` is: it is replaced
    outright by what this run's own `--mcp` selection binds, from
    ``content.mcp`` after `select_mcp` has already applied it. Unlike an
    artifact, a binding has no persistent identity of its own to carry
    forward when the run that follows falls silent about it -- silence about
    `--mcp` already means "select nothing" (`_select_mcp`), and a binding this
    run did not ask for must not linger just because an earlier run recorded
    it.

    ``version`` is `runtime.identity.version` -- this distribution's own
    release version, threaded in by the caller rather than read here off
    `pegasus.__version__`, which names the pinned engine, never the product a
    person actually installed.

    ``granted_mcp`` is threaded in from the caller rather than read off
    ``content`` for the same reason ``retired_ids`` is threaded in rather
    than recomputed: by the time this function runs, `install()` has already
    resolved the one true answer -- either the caller's own explicit set
    (`mcp_grant`/`mcp_revoke`) or the previous install's own set carried
    forward -- and it is simply recorded here, replaced outright the same way
    ``mcp_bindings`` is, since it is likewise a fact about this run's own
    final choice rather than an artifact with an identity to merge.
    ``granted_directories`` is threaded in and recorded the identical way,
    for `Install.granted_directories`.

    ``created_dirs`` is merged the same way ``entries`` is above, union rather
    than replacement: a directory an earlier install created and this run
    never touched again must stay prunable by a later retirement, not be
    forgotten the moment this run's own journal write supersedes the one that
    recorded it. Unlike ``entries``, nothing here is ever dropped from it --
    see `Install.created_dirs` for why letting this set only grow is the right
    call.
    """
    previous = journal_module.install_for(journal, adapter.id)
    entries = records
    if previous is not None:
        dropped = {record.id for record in records} | set(retired_ids)
        # An id-only comparison misses the one case this merge exists to
        # guard against when a release changes how an id is derived without
        # moving the address it names: the freshly written or reconciled
        # record lands under the *new* id, so `dropped` (built from `records`
        # above) never names the *old* one, and the previous entry would
        # otherwise survive this merge sitting right beside its own
        # replacement -- two journal entries claiming the same file. Address
        # identity is what actually decided, in `planner`, that this previous
        # entry was the same artifact under its old name; the same comparison
        # here is what retires it from the journal now that a record under
        # the new name has taken its place. `planner.record_address` is
        # reused rather than compared inline so the one carve-out it makes --
        # an appended list item has no exclusive slot of its own, several can
        # legitimately share one pointer -- cannot drift between the two call
        # sites.
        #
        # An appended list item is exactly that carve-out, and it still needs
        # an exclusion here: `record_address` returning `None` for it means
        # the address check above can never retire its previous record, so a
        # rename that changes only the `id` -- the value untouched -- would
        # otherwise leave both the old and the new record claiming the same
        # item forever. `planner.record_append_identity` is the read side's
        # own answer to the identical question (see `planner._claimed_appends`
        # and `planner.retirements`), reused here for the same reason
        # `record_address` is: a second, inline version of this exclusion
        # would only be a second place for it to drift from the one `plan`
        # itself already trusted to decide this record was the same item.
        claimed = {
            address for address in (planner.record_address(record) for record in records) if address is not None
        }
        claimed_appends = {
            identity
            for identity in (planner.record_append_identity(record) for record in records)
            if identity is not None
        }
        entries = tuple(
            entry
            for entry in previous.entries
            if entry.id not in dropped
            and planner.record_address(entry) not in claimed
            and planner.record_append_identity(entry) not in claimed_appends
        ) + tuple(records)
    return Install(
        cli=adapter.id,
        # The date Pegasus first landed here, not the date it was topped up.
        installed_at=previous.installed_at if previous is not None else now,
        config_dir=adapter.layout(environment).config_dir,
        release={"version": version, "catalog_digest": catalog.digest},
        entries=entries,
        links=previous.links if previous is not None else (),
        mcp_bindings={server.name: server.bound_to for server in content.mcp if server.is_bound},
        granted_mcp=tuple(granted_mcp),
        granted_directories=tuple(granted_directories),
        # Never recomputed here: nothing in the install/update path produces
        # a quarantined entry -- only a hand edit of the journal does, and
        # only `directory grant`/`directory revoke`'s own validation (still
        # a hard refusal, unchanged) stands between a person's input and
        # `granted_directories` above. Carrying the previous install's
        # quarantine forward unchanged is what keeps a plain `install` or
        # `update` from silently discarding it -- the same silent-loss this
        # change's own journal registry entry says was rejected for
        # `granted_directories` itself. Only `pegasus repair` ever clears it.
        quarantined_directories=previous.quarantined_directories if previous is not None else (),
        created_dirs=_recorded_dirs(previous, created_dirs, pruned_dirs),
    )


def _recorded_dirs(
    previous: Install | None, created: tuple[Path, ...], pruned: tuple[Path, ...]
) -> tuple[Path, ...]:
    """What `Install.created_dirs` should say after this run.

    The union with the previous record is what makes a directory created by one
    run and only emptied by a later one still prunable then. But union alone
    lets the record keep naming directories this very run took away, and that
    is not a harmless surplus: the field's whole claim is "these exist because
    we created them", so a pruned path left in it is the record asserting
    something false about the disk. Worse, it stays claimable -- if the person
    later recreates that directory for their own reasons and Pegasus writes
    into it again, retirement would find it already in the record and prune a
    directory it did not create this time.

    Subtracting what was pruned keeps the claim true in both directions, and
    costs nothing: a directory Pegasus creates again is reported by `make_dir`
    again, so it comes back on its own.
    """
    kept = dict.fromkeys((*(previous.created_dirs if previous is not None else ()), *created))
    for path in pruned:
        kept.pop(path, None)
    return tuple(kept)


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


def _dependency_digest(item) -> str:
    """The fingerprint that identifies *which* release of a materialized
    server this is -- a checksum for `download`, a lockfile integrity hash
    for `npm`. Shared by every place that has to ask "is what is already on
    disk still what this render wants", so the two distributions' different
    notion of "version" never has to be reconciled twice.
    """
    return item.checksum if item.distribution is content_module.Distribution.DOWNLOAD else item.integrity


def _kept_dependency(runtime: Runtime, owned: dict[str, Record], item) -> Record | None:
    """The journal entry for `item` that this run would keep untouched, or
    `None` if this run would have to materialize it.

    "Keep" means exactly: a journal entry exists for this server, its digest
    matches what this render still asks for, and the tree it points at is
    still really there. All three have to hold, or the server gets fetched
    fresh. This is the one place that test is written -- `_materialize_dependencies`,
    `_prospective_dependency_targets` and the Node preflight guard all ask it
    through here rather than each carrying their own copy, so the three can
    never quietly drift apart on what "already there" means.

    Callers still have to check `_materializes(item)` first: a `remote` or
    bound server is never in `owned` under this id, but a caller that skipped
    that check would silently read that as "would fetch it" rather than "the
    question does not apply".
    """
    existing = owned.get(f"dependency:{item.name}")
    if existing is None:
        return None
    if existing.after_digest != _dependency_digest(item):
        return None
    if not runtime.filesystem.exists(existing.target):
        return None
    return existing


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
    The "already kept, nothing to materialize" test itself comes from
    `_kept_dependency`, shared with that function and with the Node preflight
    guard; only what to do with the answer differs here — name the address
    instead of returning the record.
    """
    owned = {entry.id: entry for entry in (installed.entries if installed else ())}
    targets: set[Path] = set()
    for item in content.mcp:
        if not _materializes(item):
            continue
        if _kept_dependency(runtime, owned, item) is not None:
            continue
        targets.add(dependencies_module.target_dir(layout.dependencies_dir, item))
    return targets


def _previewed_dependencies(
    runtime: Runtime, layout, content: content_module.Content, installed: Install | None
) -> tuple[tuple[Record, ...], tuple[dict[str, Any], ...]]:
    """What `_materialize_dependencies` would report, without fetching a byte.

    A `download` or `npm` server is materialized outside the catalog
    pipeline entirely (see this module's own docstring), so `plan` never
    produces a `Step` for one and a dry run that only reads `plan.unchanged`
    /`plan.creations` never counts it at all -- the render this preview
    fixes. `_kept_dependency` already answers the one question that
    matters, read-only: is what this release still asks for already on
    disk. Reused here rather than re-derived, the same way
    `_prospective_dependency_targets` reuses it, so the three can never
    quietly disagree about what "already there" means.

    Returns ``(kept, previewed)``: ``kept`` are journal entries a real run
    would leave untouched, reported exactly the way `_materialize_dependencies`'s
    own `kept` return is -- alongside `plan.unchanged` in the report, never
    counted as a write. ``previewed`` is not a `Record`: nothing has been
    fetched, so there is no digest yet to attach to one, only the id and
    target this run already knows without reaching the network -- the same
    two fields `_recorded` would have read off a real one. `install`'s real
    (non-dry) run reports every server it actually fetches as `created`,
    never `updated`, regardless of whether the journal already held an
    entry under that id (see its own `created_ids`) -- this mirrors that
    same, single bucket, so a dry run predicts the real run it precedes
    rather than a more careful categorization the real run does not make.
    """
    owned = {entry.id: entry for entry in (installed.entries if installed else ())}
    kept: list[Record] = []
    previewed: list[dict[str, Any]] = []
    for item in content.mcp:
        if not _materializes(item):
            continue
        existing = _kept_dependency(runtime, owned, item)
        if existing is not None:
            kept.append(existing)
            continue
        previewed.append(
            {
                "id": f"dependency:{item.name}",
                "kind": "dependency-tree",
                "target": str(dependencies_module.target_dir(layout.dependencies_dir, item)),
            }
        )
    return tuple(kept), tuple(previewed)


def _materialize_dependencies(
    runtime: Runtime,
    layout,
    content: content_module.Content,
    installed: Install | None,
    on_step: Callable[[str], None] | None = None,
    on_download_progress: Callable[[str, int, int | None], None] | None = None,
) -> tuple[tuple[Record, ...], tuple[Record, ...]]:
    """Fetch and place every `download` or `npm` server this run still names.

    Returns ``(kept, created)``: a server already materialized at exactly the
    version and digest this release still asks for costs no fetch at all —
    the record the journal already holds is reused as is. Everything else is
    fetched, verified, and placed fresh; a failure here leaves whatever this
    call already placed for a *previous* server on disk, which the caller
    cleans up alongside everything else once it knows the whole install is
    being undone.

    ``on_step``, when given, is told once per server this call actually
    fetches -- never for one already `kept`, since that one cost no work --
    named by the server's own name, the same one `--mcp` takes.

    ``on_download_progress``, when given, is told the same server's name
    alongside every byte-level tick `HttpDownloader` reports while that one
    server's own bytes are still arriving -- named separately from ``on_step``
    because the two fire at different granularities for the very same fetch:
    many times while it is in flight, once when it is done.
    """
    owned = {entry.id: entry for entry in (installed.entries if installed else ())}
    node_present = shutil.which(NODE_BINARY, path=runtime.variables.get("PATH")) is not None
    kept: list[Record] = []
    created: list[Record] = []
    for item in content.mcp:
        if not _materializes(item):
            continue
        existing = _kept_dependency(runtime, owned, item)
        if existing is not None:
            kept.append(existing)
            continue
        try:
            created.append(_materialize_one(runtime, layout, item, node_present, on_download_progress=on_download_progress))
        except dependencies_module.MaterializeError:
            # A later server's failure must not leave an earlier one of this
            # same run half-recorded: nothing placed here has reached the
            # journal yet, so this is the only chance to take it back out.
            _undo_dependencies(runtime.filesystem, tuple(created))
            raise
        if on_step is not None:
            on_step(item.name)
    return tuple(kept), tuple(created)


def _materialize_one(
    runtime: Runtime,
    layout,
    item,
    node_present: bool,
    *,
    on_download_progress: Callable[[str, int, int | None], None] | None = None,
) -> Record:
    if item.distribution is content_module.Distribution.DOWNLOAD:
        progress = (lambda done, total: on_download_progress(item.name, done, total)) if on_download_progress is not None else None
        return dependencies_module.materialize(
            runtime.filesystem, runtime.downloader, layout.dependencies_dir, item, at=runtime.now, on_progress=progress
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
        raise CommandError(
            f"{runtime.identity.display_name} is not recorded as installed in {adapter.id!r}; "
            f"there is nothing to take back"
        )

    # Same reasoning as install, in reverse: retiring overwrites what the
    # journal claims without asking, and the journal itself is captured
    # alongside the targets being retired for the same reason it is on the
    # way in. A `dependency-tree` target is a directory -- see the matching
    # note in `_install` -- so it is excluded here for the same reason.
    touched = sorted(
        {entry.target for entry in install.entries if entry.kind != "dependency-tree"} | {store.path}, key=str
    )
    try:
        snapshot.save(capture_paths(runtime.filesystem, touched), taken_at=runtime.now, label="uninstall")
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
        "pruned": list(retired.pruned),
        "retention": _retain(snapshot),
    }


def _models(arguments, runtime: Runtime) -> dict[str, Any]:
    if arguments.models_command == "set":
        # `_require_per_agent_model` runs here, ahead of `_model_assignment_specs`,
        # not inside `models_set` alone: `_model_assignment_specs` does its own
        # shape validation on the raw `--assign`/`--effort` strings (a duplicate
        # agent, a spec missing '=', an orphan `--effort`) and can raise before
        # `models_set` is ever called. Left unchecked here, a mistyped argument
        # against a CLI with no per-agent model capability at all would win the
        # race and report the wrong reason -- contradicting `models_set`'s own
        # docstring, which states the capability is checked "ahead of every
        # check below". `models_set` still calls the same guard itself right
        # after, so a caller that reaches it directly (as `models_apply` calls
        # its own copy) is held to the identical rule; this is only about which
        # refusal a person typing a command line sees first.
        _require_per_agent_model(_adapter(arguments.cli))
        specs = _model_assignment_specs(arguments.assign, arguments.effort)
        return models_set(arguments.cli, specs, runtime)
    if arguments.models_command == "unset":
        return models_unset(arguments.cli, arguments.agent, runtime)
    if arguments.models_command == "list":
        return models_list(runtime, cli_id=arguments.cli)
    raise CommandError("models needs a subcommand: set, unset, or list")


def _model_assignment_specs(assign: list[str], effort: list[str]) -> list[ModelAssignmentSpec]:
    """Turn `--assign AGENT=PROVIDER/MODEL` and `--effort AGENT=LEVEL` --
    each repeated independently -- into one `ModelAssignmentSpec` per agent.

    Paired by the agent name each names, never by position: two independent
    repeated flags paired positionally is an implicit relation argparse
    cannot validate, and a misalignment (an `--effort` meant for the third
    `--assign` landing on the second) would pass silently. Naming the agent
    in both flags is the `key=value`-in-a-repeated-flag idiom this product
    already uses for `--mcp id=server-key`; it costs one repeated word per
    flag and buys a batch a mismatched count could never produce by accident.

    Refuses an `--effort` naming an agent no `--assign` named: an effort with
    nothing to attach a model to could otherwise be silently dropped, or
    -- worse -- misread as belonging to a different agent.
    """
    models: dict[str, str] = {}
    order: list[str] = []
    for spelling in assign:
        agent, separator, model = spelling.partition("=")
        if not separator or not agent or not model:
            raise CommandError(f"--assign must be AGENT=PROVIDER/MODEL: {spelling!r}")
        if agent in models:
            raise CommandError(f"--assign named {agent!r} more than once")
        models[agent] = model
        order.append(agent)
    efforts: dict[str, str] = {}
    for spelling in effort:
        agent, separator, level = spelling.partition("=")
        if not separator or not agent or not level:
            raise CommandError(f"--effort must be AGENT=LEVEL: {spelling!r}")
        if agent in efforts:
            raise CommandError(f"--effort named {agent!r} more than once")
        efforts[agent] = level
    unmatched = sorted(set(efforts) - set(models))
    if unmatched:
        raise CommandError(
            f"--effort named agent(s) {', '.join(unmatched)} that --assign never named; an effort has "
            f"nothing to attach a model to without a matching --assign AGENT=PROVIDER/MODEL"
        )
    return [ModelAssignmentSpec(agent=agent, model=models[agent], effort=efforts.get(agent)) for agent in order]


def models_set(
    cli_id: str, assignments: list[ModelAssignmentSpec], runtime: Runtime
) -> dict[str, Any]:
    """Assign a model to one or more agents in a single command, and reapply
    once so the whole batch reaches the rendered configuration in one
    render and one snapshot generation, instead of one per agent.

    Mirrors `mcp_grant`'s shape exactly, and for the same reason: recording a
    decision and applying it are one step everywhere else in this product, so
    this records the preferences and delegates the write to `install` rather
    than placing artifacts a second time. It used to record and then hand
    back a note telling the person to reinstall -- which left the only path
    from the TUI's models screen to the rendered file running through the
    Install menu entry, and so through an MCP selection screen that has
    nothing to do with models.

    `_require_per_agent_model` runs first, ahead of every check below: an
    argument the person just mistyped is more actionable than a fact about
    the machine, which is the ordering the rest of this docstring follows --
    but a missing `per_agent_model` capability is not fixable by editing the
    rest of the command line at all, so it belongs even earlier than that.
    Called again here so any caller that reaches this function directly --
    not only `models set` on the command line -- is held to the same rule.
    The command line itself checks it once more, even earlier still, in
    `_models`'s own dispatch, before `--assign`/`--effort` are even parsed
    into `ModelAssignmentSpec`s: that parsing has shape errors of its own
    (a duplicate agent, a malformed spec, an orphan `--effort`) that used to
    win the race against this refusal when the capability was absent.

    Every item is validated -- through `install`'s own `model_assignments`
    batch handling -- before anything is recorded: an agent nothing will ever
    read a model for, or a model spelling this release cannot parse, refuses
    the *whole* batch and writes nothing, naming which item and why, rather
    than applying the valid ones and silently dropping the rest. Checked
    before a CLI with nothing installed and before an install whose MCP
    selection cannot be reconstructed, the same order `mcp_grant` already
    follows for the same reason: an argument the person just mistyped is more
    actionable than either of those facts about the machine.

    `_mcp_update_selection` is the same reconstruction `update`, `mcp_grant`
    and `directory_grant` already make, for the same reason each of them
    makes it: `install` refuses a bare `mcp=None` against an installation
    that has a selection recorded, and an explicitly empty one would retire
    every server, convention and binding it holds. `granted`/
    `granted_directories` are left `None` on purpose -- nothing here changes
    either set, and `install`'s documented default for silence is to carry
    the previous install's own set forward unchanged.
    """
    adapter = _adapter(cli_id)
    _require_per_agent_model(adapter)
    if not assignments:
        raise CommandError("models set needs at least one --assign AGENT=PROVIDER/MODEL")
    # Validated here too, ahead of the "nothing installed" refusal below --
    # the same order `install`'s own batch handling documents, and the same
    # reason: an argument the person just mistyped is more actionable than a
    # fact about the machine. `install` validates this exact batch again once
    # called, so a caller that reaches it directly is held to the identical
    # rule; this is only about which refusal a person sees first.
    seen_agents: set[str] = set()
    for spec in assignments:
        if spec.agent in seen_agents:
            raise CommandError(f"--assign named {spec.agent!r} more than once")
        seen_agents.add(spec.agent)
        _require_configurable_agent(spec.agent)
        try:
            ModelAssignment.parse(spec.model, spec.effort)
        except ValueError as error:
            raise CommandError(f"invalid model assignment for {spec.agent!r}: {error}") from error
    installed = journal_module.install_for(journal_store(runtime).load(), adapter.id)
    if installed is None:
        raise CommandError(f"{adapter.id} has nothing installed; run install first")
    selection, unresolved = _mcp_update_selection(installed, display_name=runtime.identity.display_name)
    if unresolved:
        raise CommandError(
            unresolved_bindings_message(adapter.id, unresolved, program_name=runtime.identity.program_name)
        )
    report = install(cli_id, runtime, mcp=selection, model_assignments=list(assignments), label="models set")
    return {
        **report,
        "action": "set",
        "assignments": [
            {
                "agent": spec.agent,
                "model": ModelAssignment.parse(spec.model, spec.effort).full_id,
                "effort": spec.effort,
            }
            for spec in assignments
        ],
        "status": "set",
    }


def models_unset(cli_id: str, agents: list[str], runtime: Runtime) -> dict[str, Any]:
    """Remove one or more agents' assignment in a single command, and reapply
    once. Removing an assignment never set is a no-op, not an error -- the
    same `mcp_revoke` precedent, checked in the same order: a CLI with
    nothing installed is refused before the already-unset shortcut, because a
    removal nobody can apply is a refusal whether or not there was anything
    to remove. A batch where *every* named agent is already unset is a whole
    no-op and writes nothing at all; a batch where only *some* are removes
    exactly those, in the one call.

    See `models_set` for why the recorded MCP selection is reconstructed
    before `install` is called at all.
    """
    adapter = _adapter(cli_id)
    _require_per_agent_model(adapter)
    if not agents:
        raise CommandError("models unset needs at least one --agent")
    seen: set[str] = set()
    for agent in agents:
        if agent in seen:
            raise CommandError(f"--agent named {agent!r} more than once")
        seen.add(agent)
    installed = journal_module.install_for(journal_store(runtime).load(), adapter.id)
    if installed is None:
        raise CommandError(f"{adapter.id} has nothing installed; run install first")
    store = model_assignment_store(runtime)
    assignments = store.load()
    to_remove = [agent for agent in agents if model_assignments_module.get(assignments, cli_id, agent) is not None]
    if not to_remove:
        return {"action": "unset", "cli": cli_id, "agents": list(agents), "status": "already-unset"}
    selection, unresolved = _mcp_update_selection(installed, display_name=runtime.identity.display_name)
    if unresolved:
        raise CommandError(
            unresolved_bindings_message(adapter.id, unresolved, program_name=runtime.identity.program_name)
        )
    # The removal is handed to `install` rather than written here first, for
    # the same reason `models_set` hands it its assignments: `install` saves
    # the assignment store last, after the journal write has already
    # succeeded, so a failure anywhere in the render leaves the store exactly
    # as it was. Writing it here first meant a failed `install` reported a
    # failure the person could see while the removal was already on disk --
    # the one state all-or-nothing exists to prevent, and the one this
    # function's own sibling `models_apply` never had.
    report = install(cli_id, runtime, mcp=selection, model_removals=to_remove, label="models unset")
    return {**report, "action": "unset", "agents": list(agents), "removed": to_remove, "status": "unset"}


def models_apply(
    cli_id: str,
    assignments: list[ModelAssignmentSpec],
    removals: list[str],
    runtime: Runtime,
) -> dict[str, Any]:
    """`models_set` and `models_unset`, folded into the one call a mixed
    batch needs -- assignments and removals reaching `install`'s own
    `model_assignments`/`model_removals` together, so a sitting that stages
    both writes exactly once, one snapshot, one render.

    This is the entry point the TUI's models screen confirms through, and
    the reason it exists at all: calling `models_set` for the staged
    assignments and `models_unset` for the staged removals would be two
    `install()` runs and two snapshot generations for what a person
    experienced as one Continue -- precisely the storm `mcp_grant`/
    `mcp_revoke` already learned to avoid for the MCP selection screen (see
    `_grant_mcp_write`'s own docstring in `pegasus.tui.session`). A CLI
    command line has no use for this shape -- `models set` and `models
    unset` are two different subcommands a person types separately -- so
    this is reached only from Python, not from `_models`'s own dispatch.

    Every assignment is validated exactly as `models_set` validates its own
    batch -- the agent is configurable, the model spec parses, no agent is
    named twice within the assignment batch -- before anything is recorded:
    an invalid assignment refuses the *whole* call, naming the offending
    agent and why, and writes nothing. A removal can never be the offending
    item: removing an assignment that was never set is a no-op, the same as
    `models_unset`. An agent named in both `assignments` and `removals`
    is assigned and then immediately removed -- `install`'s own docstring on
    `model_removals` explains why that order, not this function's.

    `assignments` and `removals` may not both be empty -- there would be
    nothing to apply -- but either alone is enough, so a sitting that staged
    only removals, or only assignments, still reaches here rather than
    needing its own call for that case.

    Calls `_require_per_agent_model` first, exactly where `models_set` and
    `models_unset` call it, and for the same reason: this is the function
    that actually writes the assignment, so it is the one place a missing
    guard would matter most. Today its only caller (`_models_screen` in the
    TUI) already filters on the capability before ever reaching this point,
    which made the absence latent rather than harmless -- reachable by any
    future caller (a script, a plugin, a TUI refactor, a test) that calls it
    directly, the same way an adversarial review did.
    """
    adapter = _adapter(cli_id)
    _require_per_agent_model(adapter)
    if not assignments and not removals:
        raise CommandError("models apply needs at least one assignment or removal")
    seen_agents: set[str] = set()
    for spec in assignments:
        if spec.agent in seen_agents:
            raise CommandError(f"--assign named {spec.agent!r} more than once")
        seen_agents.add(spec.agent)
        _require_configurable_agent(spec.agent)
        try:
            ModelAssignment.parse(spec.model, spec.effort)
        except ValueError as error:
            raise CommandError(f"invalid model assignment for {spec.agent!r}: {error}") from error
    seen_removals: set[str] = set()
    for agent in removals:
        if agent in seen_removals:
            raise CommandError(f"--agent named {agent!r} more than once")
        seen_removals.add(agent)
    installed = journal_module.install_for(journal_store(runtime).load(), adapter.id)
    if installed is None:
        raise CommandError(f"{adapter.id} has nothing installed; run install first")
    selection, unresolved = _mcp_update_selection(installed, display_name=runtime.identity.display_name)
    if unresolved:
        raise CommandError(
            unresolved_bindings_message(adapter.id, unresolved, program_name=runtime.identity.program_name)
        )
    report = install(
        cli_id,
        runtime,
        mcp=selection,
        model_assignments=list(assignments) or None,
        model_removals=list(removals) or None,
        label="models apply",
    )
    return {
        **report,
        "action": "apply",
        "assignments": [
            {
                "agent": spec.agent,
                "model": ModelAssignment.parse(spec.model, spec.effort).full_id,
                "effort": spec.effort,
            }
            for spec in assignments
        ],
        "removed": list(removals),
        "status": "applied",
    }


def models_list(runtime: Runtime, *, cli_id: str | None = None) -> dict[str, Any]:
    """Current assignments, optionally narrowed to one CLI.

    Refuses outright when `cli_id` names an adapter that never declared
    `per_agent_model`: any assignment this store still holds for it is
    inert (see `_require_per_agent_model`), so reporting it back would let
    a person read it as a preference in effect. With `set` and `unset`
    already refusing, no *new* one can exist against that CLI going
    forward.

    The unfiltered listing (`cli_id is None`) cannot lean on that refusal --
    it exists precisely to show every CLI at once -- so it cannot simply
    skip this check the way it used to. It does not refuse either: refusing
    an unfiltered listing over one inert entry among possibly many live ones
    would throw out everything to hide one thing. Instead every entry
    belonging to a CLI without `per_agent_model` (including a CLI this
    release no longer recognizes at all, which is the same kind of stale
    record) is reported with `"in_effect": False` and a `"note"` explaining
    why, rather than silently omitted: a person who remembers setting it
    deserves to see why it does nothing, and a record that just vanishes is
    its own small mystery. Every other entry carries `"in_effect": True` for
    the same reason `mcp list`'s own entries are never left to imply a
    status by their mere presence.
    """
    if cli_id is not None:
        _require_per_agent_model(_adapter(cli_id))
    registry = available()
    assignments = model_assignment_store(runtime).load()
    rows: list[dict[str, Any]] = []
    for entry in assignments.entries:
        if cli_id is not None and entry.cli != cli_id:
            continue
        active, note = _model_assignment_in_effect(registry, entry.cli)
        row: dict[str, Any] = {
            "cli": entry.cli,
            "agent": entry.agent,
            "model": entry.assignment.full_id,
            "effort": entry.assignment.effort,
            "in_effect": active,
        }
        if note is not None:
            row["note"] = note
        rows.append(row)
    return {"action": "list", "assignments": rows}


def _model_assignment_in_effect(registry, cli_id: str) -> tuple[bool, str | None]:
    """Whether a stored entry for `cli_id` is honoured by anything today.

    Used only by the unfiltered branch of `models_list`: the filtered
    branch already refused outright through `_require_per_agent_model` if
    `cli_id` lacked the capability, so every row it returns is trivially in
    effect and never reaches here with a false result.
    """
    if cli_id not in registry:
        return False, f"{cli_id!r} is not a CLI this release recognizes; this assignment is not in effect."
    if not registry.get(cli_id).capabilities().declares(Capability.PER_AGENT_MODEL):
        return False, (
            f"{cli_id!r} never declared support for per-agent models; this assignment is not in effect."
        )
    return True, None


def _mcp(arguments, runtime: Runtime) -> dict[str, Any]:
    if arguments.mcp_command == "grant":
        return mcp_grant(arguments.cli, arguments.key, runtime)
    if arguments.mcp_command == "revoke":
        return mcp_revoke(arguments.cli, arguments.key, runtime)
    if arguments.mcp_command == "list":
        return mcp_list(arguments.cli, runtime)
    raise CommandError("mcp needs a subcommand: grant, revoke, or list")


def mcp_grant(cli_id: str, keys: list[str], runtime: Runtime) -> dict[str, Any]:
    """Grant one or more server keys the user administers themselves to
    every agent, in a single command, and reapply once so the whole batch
    reaches the rendered configuration in one render and one snapshot
    generation.

    Peeled the same way `install` and `models_set` are: a plain function an
    agent or another program can call directly, with `_mcp` doing only the
    argparse unpacking.

    Every key is checked against the CLI's own declared keys before any of
    them is granted: a mistyped id would otherwise grant a permission nobody
    notices is missing -- the exact class of bug
    `_require_mcp_convention_referenced` exists to catch for a shipped
    server, and there is no equivalent catch for a key Pegasus never heard
    of, so it has to happen here instead, against the one source of truth
    for what the user actually administers. One bad key in the batch names
    itself and refuses the whole call -- nothing is granted, not even the
    keys that were fine -- rather than granting the valid ones and silently
    leaving the mistyped one out. Granting anyway with a warning was
    considered and rejected: a warning is easy to miss, and a missing tool
    is often invisible until someone goes looking for exactly the moment it
    would have mattered.
    """
    adapter = _adapter(cli_id)
    if not keys:
        raise CommandError("mcp grant needs at least one key")
    declared = _declared_mcp_keys(runtime, adapter)
    unknown = sorted({key for key in keys if key not in declared})
    if unknown:
        raise CommandError(
            f"{', '.join(repr(key) for key in unknown)} not declared in {cli_id}'s own configuration, so "
            f"nothing was granted; the server key(s) it declares are: {', '.join(sorted(declared)) or 'none'}. "
            f"Add the missing key(s) to {cli_id}'s own configuration first, or check for a typo."
        )
    installed = journal_module.install_for(journal_store(runtime).load(), adapter.id)
    if installed is None:
        raise CommandError(f"{adapter.id} has nothing installed; run install first")
    granted = tuple(sorted(set(installed.granted_mcp) | set(keys)))
    selection, unresolved = _mcp_update_selection(installed, display_name=runtime.identity.display_name)
    if unresolved:
        raise CommandError(
            unresolved_bindings_message(adapter.id, unresolved, program_name=runtime.identity.program_name)
        )
    report = install(cli_id, runtime, mcp=selection, granted=list(granted), label="mcp grant")
    return {**report, "action": "grant", "keys": list(keys), "granted": list(granted), "status": "granted"}


def mcp_revoke(cli_id: str, keys: list[str], runtime: Runtime) -> dict[str, Any]:
    """Remove one or more granted keys, in a single command, and reapply
    once. Revoking a key never granted is a no-op, not an error -- the same
    `models unset` / `upgrade` "already-current" precedent: being in the
    desired state already is not a failure. A batch where *every* named key
    is already ungranted is a whole no-op and writes nothing; a batch where
    only *some* are revokes exactly those, in the one call.
    """
    adapter = _adapter(cli_id)
    if not keys:
        raise CommandError("mcp revoke needs at least one key")
    installed = journal_module.install_for(journal_store(runtime).load(), adapter.id)
    if installed is None:
        raise CommandError(f"{adapter.id} has nothing installed; run install first")
    to_revoke = [key for key in keys if key in installed.granted_mcp]
    if not to_revoke:
        return {"action": "revoke", "cli": cli_id, "keys": list(keys), "status": "already-revoked"}
    granted = tuple(sorted(set(installed.granted_mcp) - set(to_revoke)))
    selection, unresolved = _mcp_update_selection(installed, display_name=runtime.identity.display_name)
    if unresolved:
        raise CommandError(
            unresolved_bindings_message(adapter.id, unresolved, program_name=runtime.identity.program_name)
        )
    report = install(cli_id, runtime, mcp=selection, granted=list(granted), label="mcp revoke")
    return {**report, "action": "revoke", "keys": list(keys), "granted": list(granted), "status": "revoked"}


def mcp_list(cli_id: str, runtime: Runtime) -> dict[str, Any]:
    """What is granted now, which of the CLI's own declared server keys
    would actually be accepted by a grant, and which of the rest need none
    because Pegasus already reaches them per-agent.

    `available` used to be simply `declared - granted`, which could name a
    key `mcp_grant` would then refuse -- any key `content.per_agent_mcp_keys`
    already covers, a shipped server this installation chose or one already
    bound. This calls that exact same core rule, non-raising, on the content
    this install's own recorded selection would produce (`_mcp_update_selection`
    plus `_select_mcp`, the identical reconstruction `update` already relies
    on), so `available` here and what `mcp_grant` would accept can never
    drift apart -- there is one rule, `per_agent_mcp_keys`, asked the same
    way from both places. `already_covered` names what was excluded and why,
    rather than letting a declared key a person recognizes simply vanish
    from the report.

    An install with an *unresolved* binding (a bound server whose key was
    never recorded -- see `_mcp_update_selection`) cannot have its selection
    safely reconstructed at all: `mcp_grant`/`mcp_revoke` both refuse
    outright the moment they see one, whatever key was actually asked for,
    because reapplying anything while guessing at the missing binding would
    retire the very binding `update` exists to preserve. Advertising
    anything as `available` here, computed from a selection that quietly
    dropped the unresolved id, would be exactly the promise that refusal
    then breaks -- so in that state `available` and `already_covered` are
    both empty, `unresolved_mcp_bindings` names the blocking id(s), and
    `blocked` carries `unresolved_bindings_message`'s own wording verbatim
    -- the identical text `mcp_grant`, `mcp_revoke`, and `update` already
    raise, never a second phrasing of the same fact.

    Follows `models_list`'s shape: a plain function returning the same
    report `--json` would, callable directly without going through argparse.
    """
    adapter = _adapter(cli_id)
    installed = journal_module.install_for(journal_store(runtime).load(), adapter.id)
    granted = set(installed.granted_mcp) if installed is not None else set()
    declared = _declared_mcp_keys(runtime, adapter)
    ungranted = declared - granted
    per_agent, unresolved = _per_agent_mcp_keys_for(installed, display_name=runtime.identity.display_name)
    if unresolved:
        return {
            "action": "list",
            "cli": cli_id,
            "granted": sorted(granted),
            "available": [],
            "already_covered": [],
            "unresolved_mcp_bindings": sorted(unresolved),
            "blocked": unresolved_bindings_message(
                adapter.id, unresolved, program_name=runtime.identity.program_name
            ),
        }
    already_covered = ungranted & per_agent
    return {
        "action": "list",
        "cli": cli_id,
        "granted": sorted(granted),
        "available": sorted(ungranted - already_covered),
        "already_covered": sorted(already_covered),
        "unresolved_mcp_bindings": [],
        "blocked": None,
    }


def _directory(arguments, runtime: Runtime) -> dict[str, Any]:
    if arguments.directory_command == "grant":
        return directory_grant(arguments.cli, arguments.path, runtime)
    if arguments.directory_command == "revoke":
        return directory_revoke(arguments.cli, arguments.path, runtime)
    raise CommandError("directory needs a subcommand: grant or revoke")


def directory_grant(cli_id: str, paths: list[str], runtime: Runtime) -> dict[str, Any]:
    """Grant one or more working directories of the person's own choosing to
    every agent's `external_directory` permission, in a single command, and
    reapply once so the whole batch reaches the rendered configuration in
    one render and one snapshot generation.

    Mirrors `mcp_grant`'s shape exactly: a plain function an agent or another
    program can call directly, with `_directory` doing only the argparse
    unpacking, and the actual write delegated to `install` the same way
    `mcp_grant` delegates to it rather than placing artifacts a second time.

    Unlike `mcp_grant`, there is no CLI-declared set to check a path against
    first -- a working directory is never declared anywhere in the CLI's own
    configuration the way an MCP server key is, so there is no typo class to
    catch before the fact. The only refusal here is
    `content.validate_granted_directory`'s own validation (absolute, free of
    `..` and of glob metacharacters, not the filesystem root, not the CLI's
    own configuration directory or Pegasus's own data directory, nor an
    ancestor of either) -- surfaced as a `CommandError` the moment it raises,
    for the first offending path found, naming it and why; nothing in the
    batch is recorded until every path in it has validated.

    Each path is normalized through that same validation *before* it is
    stored or reported, not only when `install` renders it: `render.py`
    writes `f"{path}/*": "allow"` from whatever string sits in the journal,
    so the journal, the rendered permission, this report, and whatever a
    person later types to `directory revoke` all have to agree on one
    spelling of the same directory, or a trailing slash or a repeated `/`
    silently produces two directories where the person meant one.

    A path this validation accepts can still be one `render.py`'s own
    `EXTERNAL_DIRECTORY_DENY_FLOOR` shadows -- `.ssh`, `.aws`, `.credentials`,
    `.config/gh`, `secrets`, written last into every rendered
    `external_directory` map so the runtime's last-match resolution always
    lands on the floor's `deny` regardless of a grant naming that exact
    directory. Refusing the grant outright would change this command's
    contract for a case the person did not ask to be blocked on, so it is not
    refused: it is still recorded and still reported as granted, with a
    warning -- one per shadowed path in the batch -- that it can never take
    effect, checked through `opencode_render_module.deny_floor_shadows` --
    the OpenCode-specific fact of which directories the floor covers has no
    business in `content.py` (`core` may not import an adapter), so the
    predicate lives in the adapter and this CLI layer, which already depends
    on everything, is what calls it. Only for `opencode` -- another CLI
    adapter this product ships may have no such floor, and must not inherit a
    warning describing OpenCode's own.
    """
    adapter = _adapter(cli_id)
    if not paths:
        raise CommandError("directory grant needs at least one path")
    installed = journal_module.install_for(journal_store(runtime).load(), adapter.id)
    if installed is None:
        raise CommandError(f"{adapter.id} has nothing installed; run install first")
    layout = adapter.layout(runtime.environment)
    normalized_paths: list[str] = []
    for path in paths:
        try:
            normalized = content_module.validate_granted_directory(
                path, config_dir=layout.config_dir, data_dir=runtime.filesystem.data_dir(runtime.home)
            )
        except content_module.ContentError as error:
            raise CommandError(f"{path!r}: {error}") from error
        normalized_paths.append(normalized)
    granted = tuple(sorted(set(installed.granted_directories) | set(normalized_paths)))
    selection, unresolved = _mcp_update_selection(installed, display_name=runtime.identity.display_name)
    if unresolved:
        raise CommandError(
            unresolved_bindings_message(adapter.id, unresolved, program_name=runtime.identity.program_name)
        )
    report = install(
        cli_id,
        runtime,
        mcp=selection,
        granted=list(installed.granted_mcp),
        granted_directories=list(granted),
        label="directory grant",
    )
    result = {
        **report,
        "action": "grant",
        "paths": normalized_paths,
        "granted_directories": list(granted),
        "status": "granted",
    }
    if adapter.id == OPENCODE_CLI_ID:
        shadowed = [path for path in normalized_paths if opencode_render_module.deny_floor_shadows(path)]
        if shadowed:
            result["warning"] = "\n\n".join(
                f"{path!r} is granted and recorded, but it will never take effect: it falls under "
                f"OpenCode's own always-denied floor (.ssh, .aws, .credentials, .config/gh, secrets), which "
                f"is written after every grant so it always wins the match. This is not the ordinary dormant "
                f"case -- an ordinary grant regains meaning if the baseline ever goes back to \"ask\"; this "
                f"one never will, because the floor is written last regardless of the baseline."
                for path in shadowed
            )
    return result


def directory_revoke(cli_id: str, paths: list[str], runtime: Runtime) -> dict[str, Any]:
    """Remove one or more granted directories, in a single command, and
    reapply once. Revoking a directory never granted is a no-op, not an
    error -- the same `mcp_revoke` precedent. A batch where *every* named
    path is already ungranted is a whole no-op and writes nothing; a batch
    where only *some* are revokes exactly those, in the one call.

    Every argument is normalized through `content.validate_granted_directory`
    before it is compared against `installed.granted_directories` -- see
    `directory_grant`'s own docstring for why the journal only ever holds
    the normalized spelling. Without this, a directory granted as
    `/srv/work/` and revoked as `/srv/work` (or the reverse) would compare
    unequal, report `already-revoked`, and leave the grant rendered.
    """
    adapter = _adapter(cli_id)
    if not paths:
        raise CommandError("directory revoke needs at least one path")
    installed = journal_module.install_for(journal_store(runtime).load(), adapter.id)
    if installed is None:
        raise CommandError(f"{adapter.id} has nothing installed; run install first")
    layout = adapter.layout(runtime.environment)
    normalized_paths: list[str] = []
    for path in paths:
        try:
            normalized = content_module.validate_granted_directory(
                path, config_dir=layout.config_dir, data_dir=runtime.filesystem.data_dir(runtime.home)
            )
        except content_module.ContentError as error:
            raise CommandError(f"{path!r}: {error}") from error
        normalized_paths.append(normalized)
    to_revoke = [path for path in normalized_paths if path in installed.granted_directories]
    if not to_revoke:
        return {"action": "revoke", "cli": cli_id, "paths": normalized_paths, "status": "already-revoked"}
    granted = tuple(sorted(set(installed.granted_directories) - set(to_revoke)))
    selection, unresolved = _mcp_update_selection(installed, display_name=runtime.identity.display_name)
    if unresolved:
        raise CommandError(
            unresolved_bindings_message(adapter.id, unresolved, program_name=runtime.identity.program_name)
        )
    report = install(
        cli_id,
        runtime,
        mcp=selection,
        granted=list(installed.granted_mcp),
        granted_directories=list(granted),
        label="directory revoke",
    )
    return {
        **report,
        "action": "revoke",
        "paths": normalized_paths,
        "granted_directories": list(granted),
        "status": "revoked",
    }


def _repair(arguments, runtime: Runtime) -> dict[str, Any]:
    return repair(arguments.cli, runtime, dry_run=arguments.dry_run)


def repair(cli_id: str, runtime: Runtime, *, dry_run: bool = False) -> dict[str, Any]:
    """Remove hazards `doctor` can only name, and nothing else.

    Two hazards today, both discovered read-only and removed only on
    request:

    - `granted_directories` entries a hand edit put in the journal that
      `content.validate_granted_directory` refused -- quarantined by
      `journal._granted_directories_from_dict` rather than blocking the
      whole journal, named by `doctor` under `directories_quarantined`.
    - Empty directories `planner.empty_directories_never_pruned` names under
      `found` -- exactly what `doctor` reports as
      `unprunable_empty_directories`, reused rather than rediscovered here so
      the two can never name different sets. `planner.remove_orphaned_empty_directories`
      does the actual removal, re-checking emptiness and the symlink chain at
      removal time rather than trusting the discovery pass.

    A subtree the scan could not walk at all because it sits behind a
    symlink (`scan.unwalkable`, `doctor`'s `directories_not_walked`) is never
    silently treated as clean: it is carried into this report too, so a
    caller cannot read "repaired" as "there was nothing left to find" over a
    subtree this never looked at.

    Mirrors `uninstall`'s own shape for the journal write: a snapshot of the
    journal is taken first, so `pegasus restore` can undo the quarantine
    removal the same way it undoes an uninstall, and the journal is written
    at most once, only when there was a quarantined entry to clear. Removing
    an orphaned empty directory is not itself snapshotted -- the same
    precedent `uninstall`'s own pruning already sets, where a pruned empty
    directory is not part of what `restore` brings back either, because an
    empty directory has nothing worth restoring beyond an `mkdir` a person
    can do themselves. Nothing else is read for writing, and nothing else is
    written.

    A journal that cannot be read for a reason quarantine does not cover
    (malformed JSON, a `granted_directories` that is not a list at all) is
    not caught here: `store.load()` raises `JournalStoreError` straight
    through, exactly as it does for the other nine call sites, and `main`
    turns that into the same failure report and the same mention of
    `restore` every other command gives.
    """
    adapter = _adapter(cli_id)
    store = journal_store(runtime)
    journal = store.load()
    install = journal_module.install_for(journal, adapter.id)
    if install is None:
        raise CommandError(
            f"{runtime.identity.display_name} is not recorded as installed in {adapter.id!r}; "
            f"there is nothing to repair"
        )
    quarantined = [repr(item) for item in install.quarantined_directories]
    scan = planner.empty_directories_never_pruned(runtime.filesystem, install.config_dir, install.created_dirs)
    orphaned = list(scan.found)
    extra: dict[str, Any] = {"directories_not_walked": list(scan.unwalkable)} if scan.unwalkable else {}
    if not quarantined and not orphaned:
        return {
            "cli": adapter.id,
            "status": "nothing-to-repair",
            "removed_quarantined_directories": [],
            "removed_orphaned_directories": [],
            **extra,
        }
    if dry_run:
        return {
            "cli": adapter.id,
            "status": "planned",
            "removed_quarantined_directories": quarantined,
            "removed_orphaned_directories": orphaned,
            **extra,
        }
    store.ensure_writable()
    snapshot = snapshot_store(runtime)
    snapshot.ensure_writable()
    try:
        snapshot.save(capture_paths(runtime.filesystem, [store.path]), taken_at=runtime.now, label="repair")
    except SnapshotStoreError as error:
        raise CommandError(
            f"a snapshot of the journal could not be taken, so nothing was repaired: {error}"
        ) from error
    removed_dirs = (
        planner.remove_orphaned_empty_directories(runtime.filesystem, install.config_dir, tuple(orphaned))
        if orphaned
        else ()
    )
    if quarantined:
        store.save(journal_module.with_install(journal, replace(install, quarantined_directories=())))
    return {
        "cli": adapter.id,
        "status": "repaired",
        "removed_quarantined_directories": quarantined,
        "removed_orphaned_directories": list(removed_dirs),
        **extra,
        "retention": _retain(snapshot),
    }


def _per_agent_mcp_keys_for(installed, *, display_name: str) -> tuple[frozenset[str], list[str]]:
    """`content_module.per_agent_mcp_keys`, computed against the content this
    installation's own recorded `--mcp` selection would produce, alongside
    the unresolved binding ids that selection had to leave out -- `(frozenset(),
    [])` for `None`, the same way an uninstalled CLI's own `_declared_mcp_keys`
    reads as nothing declared.

    `_mcp_update_selection` is the same reconstruction `update` already
    trusts to rebuild an install's exact `--mcp` selection from its journal;
    reusing it here, rather than re-deriving the selection a second way, is
    what keeps this in step with whatever `update` (and therefore a fresh
    `install`) would actually apply. Its second half -- the unresolved ids --
    used to be discarded here, which let `mcp_list` compute `per_agent_mcp_keys`
    from a selection quietly missing exactly the binding `mcp_grant`/`update`
    would refuse over; returning it instead is what lets `mcp_list` refuse to
    pretend a selection it cannot safely reconstruct is one it can.
    """
    if installed is None:
        return frozenset(), []
    selection, unresolved = _mcp_update_selection(installed, display_name=display_name)
    return content_module.per_agent_mcp_keys(_select_mcp(selection)), unresolved


def _declared_mcp_keys(runtime: Runtime, adapter) -> frozenset[str]:
    """The MCP server keys already present in the CLI's own configuration --
    put there by the user, since this is read straight off disk rather than
    off anything Pegasus itself journals.

    Absent or unreadable answers "none" rather than raising: a CLI that was
    never opened, or whose settings file does not parse, declares nothing
    the same way an uninstalled CLI's model catalog reads as empty
    (`model_catalog.declared_provider_names`'s own precedent).
    """
    from pegasus.core import codecs

    layout = adapter.layout(runtime.environment)
    settings_file = getattr(layout, "settings_file", None)
    if settings_file is None or not runtime.filesystem.exists(settings_file):
        return frozenset()
    try:
        document = codecs.loads(Codec.JSON, runtime.filesystem.read_bytes(settings_file).decode("utf-8"))
    except (FileSystemError, UnicodeDecodeError, codecs.CodecError):
        return frozenset()
    servers = document.get("mcp") if isinstance(document, dict) else None
    return frozenset(str(key) for key in servers.keys()) if isinstance(servers, dict) else frozenset()


def _require_per_agent_model(adapter) -> None:
    """Refuse outright when `adapter` never declared `Capability.
    PER_AGENT_MODEL` -- before anything else `models_set`, `models_unset`,
    `models_apply`, and a `--cli`-scoped `models_list` check, including
    their own argument validation.

    Mirrors `_require_configurable_agent`'s shape for the same kind of
    precondition, but this one sits even earlier. `models_set`'s own
    docstring states the ordering principle the rest of this module follows:
    an argument the person just mistyped is more actionable than a fact
    about the machine, so a bad `--assign` is checked before "nothing
    installed". A missing capability is not that kind of fact -- it is not
    fixable by editing the rest of the command line at all. Correct every
    argument and there is still no model catalog on this CLI to write a
    preference into. So it is checked first, ahead of every argument check
    and every other precondition -- on the command line, `_models`'s own
    dispatch calls this ahead of even building the `--assign`/`--effort`
    batch for `models set`, since that batch's own shape validation
    (`_model_assignment_specs`) can otherwise raise its own error first.

    `models_list` calls this only when narrowed to one CLI: an unfiltered
    listing has no single adapter to check against and reports every CLI at
    once, including one lacking this capability -- marked as not in effect,
    never refused outright, since refusing the whole listing over one inert
    entry would hide every live one alongside it.

    The message matches the `Placeholder` `tui.session`'s own models screen
    already shows for this exact absence (added in `e747b9f`): a person who
    meets this refusal in the TUI and then on the command line should read
    the same explanation, not two different ones invented independently.
    """
    if not adapter.capabilities().declares(Capability.PER_AGENT_MODEL):
        raise CommandError(
            f"{adapter.id} never declared support for per-agent models -- its adapter carries no "
            "model catalog at all, so there is nothing here to set, unset, or list."
        )


def _require_configurable_agent(agent: str) -> None:
    content = content_module.load()
    for descriptor in content.agents:
        if descriptor.name == agent:
            if not descriptor.model_configurable:
                raise CommandError(f"{agent!r} does not accept a model assignment")
            return
    raise CommandError(f"{agent!r} is not an agent this release ships")


def _restore(arguments, runtime: Runtime) -> dict[str, Any]:
    if getattr(arguments, "list", False):
        if arguments.generation is not None:
            raise CommandError(
                "--list shows what is available to restore; it takes no generation of its own -- "
                "drop --list to restore one"
            )
        return restore_list(runtime)
    return restore(runtime, arguments.generation)


def restore_list(runtime: Runtime) -> dict[str, Any]:
    """Every generation `restore` could still open, most recent first, with
    enough about each to choose one without guessing first.

    `models set`/`unset` picked "a subparser" for their own two verbs because
    `models` is a noun with several actions; `restore` is already a verb, so
    a `restore list` subcommand would read as two verbs stacked on top of
    each other for no gain -- `--list` says the same thing without inventing
    a subparser `restore` has never needed otherwise, and reads the way `git
    stash list` or `docker ps -a` already do for a single-purpose command
    with a listing mode.

    Each row carries: the generation's own number: `taken_at`, exactly as
    the manifest recorded it (this module's other reports are not localized
    either -- only the TUI, which has no `--json` twin to keep in step,
    converts to a wall clock); `label` (see `core.snapshot.Manifest.label`),
    `None` for a generation that predates it; and the same two counts
    `restore`'s own report already uses for what it changed --
    `files_restored`/`paths_cleared` -- so a person sees a generation's size
    in the same units they would see once they actually restored it, rather
    than a raw path list that grows unreadable past a handful of entries.

    A generation `readable_generations` claims but whose manifest fails to
    parse is named under `unreadable` rather than silently dropped -- the
    same asymmetry the TUI's own `_generation_summaries` already draws for
    the identical reason: one bad generation must not make every good one
    next to it disappear without a trace.
    """
    snapshot = snapshot_store(runtime)
    numbers = list(reversed(snapshot.readable_generations()))
    generations: list[dict[str, Any]] = []
    unreadable: list[int] = []
    for generation in numbers:
        try:
            manifest = snapshot.read(generation)
        except SnapshotStoreError:
            unreadable.append(generation)
            continue
        generations.append(
            {
                "generation": generation,
                "taken_at": manifest.taken_at,
                "label": manifest.label,
                "files_restored": sum(1 for entry in manifest.entries if entry.existed),
                "paths_cleared": sum(1 for entry in manifest.entries if not entry.existed),
            }
        )
    return {"action": "list", "generations": generations, "unreadable": unreadable}


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
            capture_paths(runtime.filesystem, touched, directories=directories),
            taken_at=runtime.now,
            label="restore",
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
    store = journal_store(runtime)
    journal_error: dict[str, Any] | None = None
    try:
        journal = store.load()
    except JournalStoreError as error:
        # A malformed journal must not take the rest of the diagnosis down
        # with it. `doctor` is exactly the tool somebody reaches for because
        # something looks wrong -- an unreadable journal is one of the things
        # that can be wrong, and it is the one case where every other command
        # refuses outright. Falling back to an *empty* journal here would
        # make every CLI read as "not installed", which is not the same fact
        # as "we could not check" -- the same distinction `_granted_directories_from_dict`
        # protects on the way in, kept here on the way out.
        journal = None
        journal_error = {"path": str(store.path), "error": str(error)}
    report: dict[str, Any] = {
        "pegasus_version": runtime.identity.version,
        "clis": [
            _health(registry.get(cli_id), environment, journal, runtime, start_mcp_servers=start_mcp_servers)
            for cli_id in registry.ids()
        ],
    }
    if journal_error is not None:
        report["journal_error"] = journal_error
    return report


def _health(
    adapter, environment: Environment, journal, runtime: Runtime, *, start_mcp_servers: bool = False
) -> dict[str, Any]:
    detection = adapter.detect(environment)
    if journal is None:
        # Nothing below this point can be answered without the journal, and
        # guessing would misreport one fact as another: `pegasus_installed:
        # false` claims "nothing is here", when the truth is "its own record
        # could not be read" -- a different fact, and doctor's whole job is
        # not to blur the two together.
        return {
            "cli": adapter.id,
            "display_name": adapter.display_name,
            "tier": adapter.tier().value,
            "detected": bool(detection.installed or detection.config_found),
            "config_dir": str(detection.config_dir) if detection.config_dir else None,
            "journal_unreadable": True,
        }
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
        # Not a fourth way of being wrong: a way of not being checkable. A
        # dependency tree recorded before the program pair existed, or one whose
        # program `npm ci` never wrote where the descriptor said it would, has
        # nothing to compare against — so it reports no drift, and would read as
        # verified if nothing said otherwise. Naming it is the difference
        # between "checked and fine" and "never checked".
        "unverified": [],
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
        if entry.kind == "dependency-tree" and entry.program_digest is None:
            health["unverified"].append(entry.id)
        if current is None:
            health["missing"].append(entry.id)
        elif current != entry.after_digest:
            health["drifted"].append(entry.id)

    # Outside the flag, and deliberately: the flag authorises running someone's
    # configured processes, and this runs nothing at all -- it reads the journal
    # for servers this install granted without configuring. Keeping it inside
    # left a plain `doctor` silent about them, which is the same blind spot the
    # flag's own report was fixed to remove, only for the invocation almost
    # everybody types. Its own key, rather than joining `mcp_servers`: that one
    # is documented as the result of launching things, and would otherwise hold
    # entries nothing launched.
    bound_checks = _bound_checks(install, display_name=runtime.identity.display_name)
    health["mcp_bound"] = [
        {"id": check.id, "status": check.status, "detail": check.detail, "key": install.mcp_bindings.get(check.id)}
        for check in bound_checks
    ]

    # Named rather than left for the prose alone to say: a machine-readable
    # consumer needs the same fact -- which ids, and the exact command that
    # would resolve them -- without parsing a sentence for it. Absent
    # whenever every bound id's key is already known: there is nothing to
    # fix, so there is nothing to say.
    unknown_key_ids = sorted(check.id for check in bound_checks if install.mcp_bindings.get(check.id) is None)
    if unknown_key_ids:
        health["mcp_bound_unknown_keys"] = {
            "ids": unknown_key_ids,
            "command": install_command_for(adapter.id, unknown_key_ids, program_name=runtime.identity.program_name),
        }

    # Its own key, distinct from `mcp_bound`: a granted key is not a binding.
    # Pegasus ships no descriptor for it, grants no convention for it, and
    # never installed or configured it -- the only thing this install did was
    # tell every rendered agent's wildcard to include it. Conflating the two
    # under one heading would say a server was bound (which implies a
    # descriptor's contract travels with it) when nothing here was ever
    # shipped for it at all.
    health["mcp_granted"] = sorted(install.granted_mcp)

    # Its own key, the same reasoning as `mcp_granted` just above, for a
    # different fact the journal alone knows: a directory a person granted
    # through `pegasus directory grant` is invisible anywhere else `doctor`
    # already reports, since it names no artifact, no server, and no binding.
    health["directories_granted"] = sorted(install.granted_directories)

    # Its own key, named only when there is something to name: a
    # `granted_directories` entry a hand edit put there that
    # `content.validate_granted_directory` refused. It grants nothing --
    # `quarantined_directories` never reaches `directories_granted` above,
    # any render, or any other consumer of `Install.granted_directories` --
    # so this reports the fact of its presence without claiming it does
    # anything. `repr` because an entry can be of any JSON type at all
    # (a number, `null`, an object), not only a malformed string.
    if install.quarantined_directories:
        health["directories_quarantined"] = [repr(item) for item in install.quarantined_directories]

    # Named only when there is something to name: an install whose pruning
    # already reaches everything empty under it has nothing here to say, and
    # a report that always carried this key regardless would be one more
    # section a reader has to learn to skim past.
    scan = planner.empty_directories_never_pruned(
        runtime.filesystem, install.config_dir, install.created_dirs
    )
    if scan.found:
        health["unprunable_empty_directories"] = list(scan.found)
    # Its own key, distinct from the one above: "found nothing" and "could
    # not look" used to be the same silent empty result -- a `config_dir`
    # reached only through a symlink (dotfiles under stow or chezmoi) walked
    # nothing and said nothing, which reads as "no orphaned directories" when
    # the honest answer is "this was never checked". Named only when there
    # is something unwalkable to name, the same discipline every other
    # named-only-when-present key in this report already follows.
    if scan.unwalkable:
        health["directories_not_walked"] = list(scan.unwalkable)

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

    A bound server is not here, and that is the point of it living in
    `mcp_bound` instead: this list is what launching produced, and a server
    with no configuration of its own was never launched. It used to be
    appended here as well, so a report with the flag named the same server
    twice under two headings that disagreed about what it was.
    """
    return [_mcp_checks_one(runtime, entry, name) for entry, name in _mcp_entries(install)]


def _bound_checks(install, *, display_name: str) -> list[mcp_handshake.ServerCheck]:
    """The servers this install granted without ever configuring them --
    genuinely, or ambiguously enough that it still has to be said.

    A bound server writes no `/mcp/<id>` key — only its convention — so
    `_mcp_entries` cannot see it, and an install whose servers are all bound
    reported "No MCP servers configured": not a gap in the report but a false
    statement about the machine. A convention entry with no configuration key
    beside it used to be read as exactly the shape a binding leaves behind.
    It no longer is, on its own: `CliAdapter.writes_mcp_config_key` (`False`
    for Claude Code, `True` for OpenCode) is now consulted first, because a
    CLI that answers `False` there writes *no* `/mcp/<id>` key for any
    server it installs, bound or not -- that shape is this CLI's ordinary
    one for a server Pegasus obtained and administers itself, and reporting
    it as "granted but not installed" would be the false statement this
    function exists to avoid, not make.

    The key a genuine binding was bound to travels on `Install.mcp_bindings`
    (`select_mcp` computes it; `_merged` records it), so what is said about
    one no longer stops at "no configuration of its own" the way it used to.
    A binding is still not the only cause of the shape on a CLI that answers
    `True` above -- `retire` walks kinds in sorted order, `config-key` before
    `file`, so an uninstall that removed the configuration key and then
    failed on the convention leaves the journal holding exactly this too --
    but that shape never populates `mcp_bindings`, since nothing but
    `select_mcp`/`_merged` ever writes it. So a present key is proof this
    really is a binding, and the detail says so plainly; an absent key, on
    such a CLI, stays exactly as ambiguous as before, and names both
    readings the same way it always has. Starting the server is out of reach
    either way: bound or half-uninstalled, there is no configuration here to
    start it from.
    """
    writes_mcp_config_key = _adapter(install.cli).writes_mcp_config_key()
    configured = {name for _, name in _mcp_entries(install)}
    checks = []
    for entry in install.entries:
        if not entry.id.startswith(_MCP_CONVENTION_PREFIX):
            continue
        name = entry.id[len(_MCP_CONVENTION_PREFIX):]
        if name in configured:
            continue
        key = install.mcp_bindings.get(name)
        if key is not None:
            detail = (
                f"no configuration of its own in this install: bound to {key!r}, a server you "
                f"administer, whose tools {display_name} grants and whose convention it ships without "
                f"installing or starting it"
            )
        elif not writes_mcp_config_key:
            # This CLI never writes a `/mcp/<id>` key for any server, bound
            # or not, so a bare convention with no key beside it carries no
            # information at all about whether this server is a binding --
            # it is this CLI's normal shape for one Pegasus installed and
            # administers itself. Nothing to hedge, nothing to report.
            continue
        else:
            detail = (
                "no configuration of its own in this install: either bound to a server you "
                f"administer, whose tools {display_name} grants and whose convention it ships without "
                "installing or starting it, or a convention left behind by an uninstall that "
                "did not finish"
            )
        checks.append(mcp_handshake.ServerCheck(name, "bound", detail))
    return checks


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
    """What this can honestly report is bounded by what it would cost to find out.

    Hashing the whole tree would need a recursive read — cheap for a single
    binary, prohibitive for a `node_modules` with tens of thousands of files —
    so this never does that, and `Record.after_digest` says why at length: it
    names the *source* Pegasus fetched, not a hash of the directory as it
    stands, and proves nothing about what is on disk now.

    What this checks instead is smaller and cheaper: the one file inside the
    tree a CLI's configuration is actually told to run — `entry.program_relpath`,
    recorded by `dependencies.materialize` or `materialize_npm` alongside its
    own digest. That is a single read, not a walk, and it proves exactly one
    thing: whether the program Pegasus placed is still the program Pegasus
    placed. It proves nothing about any other file the tree contains — a
    substituted dependency three levels into `node_modules` is invisible to
    this, on purpose, because catching it would cost the walk this function
    exists to avoid.

    A record written before this pair existed carries neither field, and that
    is a different fact from the program having gone missing or been swapped:
    there was never anything to check, so nothing here can be asserted one
    way or the other. Returning ``entry.after_digest`` unconditionally is how
    that distinction survives into `doctor`'s bucketing — the caller compares
    this return value against ``entry.after_digest`` to decide "drifted", so
    a value engineered to always equal it is the only way to say "not proven
    wrong" without also claiming "proven right".
    """
    if entry.program_relpath is None or entry.program_digest is None:
        return entry.after_digest
    program = entry.target / entry.program_relpath
    if not filesystem.exists(program):
        return None
    current = ownership.digest_of_bytes(filesystem.read_bytes(program))
    return entry.after_digest if current == entry.program_digest else current


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
    "update": _update,
    "upgrade": _upgrade,
    "uninstall": _uninstall,
    "repair": _repair,
    "doctor": _doctor,
    "restore": _restore,
    "models": _models,
    "mcp": _mcp,
    "directory": _directory,
}


# --- Shaping the report ----------------------------------------------------


def _adapter(cli_id: str):
    registry = available()
    if cli_id not in registry:
        raise CommandError(f"{cli_id!r} is not a CLI this release supports; try one of: {', '.join(registry.ids())}")
    return registry.get(cli_id)


#: The one `--mcp` spelling this module understands and `content.select_mcp`
#: never sees. `select_mcp`'s empty list already means "choose nothing" --
#: that is its documented default -- so there is no missing concept in the
#: core to add; what is missing is a way for someone typing a command line to
#: reach that empty list *on purpose* rather than by omission, since omission
#: now means something else entirely (see `install`'s guard, below). Kept as
#: a CLI-only spelling, translated away before `content_module.select_mcp`
#: ever runs, so the core stays exactly as unaware of "none" as it is of any
#: other command-line concern.
_MCP_NONE = "none"


def _select_mcp(chosen: list[str] | None) -> content_module.Content:
    """The user's `--mcp` flags, applied to the whole content tree once.

    `ContentError` here means the user's own flag named a server that does not
    exist, which is a clean message rather than the traceback a malformed
    shipped descriptor would still deserve — that case is left to whatever
    already raises `ContentError` unhandled in `main`.

    `--mcp none` is handled here, not in `content_module.select_mcp`: it
    means "select nothing", the same result an empty list already produces,
    so it is translated to `[]` before the core ever sees it rather than
    taught as a second spelling of the same thing down there. `none` is
    refused combined with anything else -- `--mcp none --mcp cbm` is a
    contradiction, not a hint that one of the two wins, so this never guesses
    which.
    """
    chosen = chosen or []
    if _MCP_NONE in chosen:
        if len(chosen) > 1:
            raise CommandError(
                f"--mcp {_MCP_NONE} means selecting no server, on purpose, and cannot be combined "
                f"with any other --mcp value -- pass --mcp {_MCP_NONE} alone, or drop it and name "
                f"only the servers you actually want"
            )
        chosen = []
    try:
        return content_module.select_mcp(content_module.load(), chosen)
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


def _node_present(runtime: Runtime) -> bool:
    """Whether `node` resolves on the `PATH` this run's environment carries.

    The same lookup `_materialize_dependencies` performs, factored out so the
    preflight guard below and the port contract inside `materialize_npm` never
    drift apart on how "present" is decided. It stays here, at the
    application layer, rather than in `core`: an external binary's presence
    on `PATH` is an infrastructure fact, and `shutil` has no business being
    imported by domain code.
    """
    return shutil.which(NODE_BINARY, path=runtime.variables.get("PATH")) is not None


def _require_node_if_needed(
    content: content_module.Content, runtime: Runtime, installed: Install | None
) -> None:
    """Refuse an `npm` selection with no Node on `PATH`, before anything else
    this install would do -- but only for a server this run would actually
    have to fetch.

    `materialize_npm` already refuses this on its own, deep inside
    `_materialize_dependencies` -- that guard stays exactly as it is, as the
    port's own contract and this preflight's defence in depth. What changes
    is when the user finds out: without this, they wait through the whole
    plan, the pre-write snapshot, and every artifact this run places, only to
    have the very last step undo it all. This asks the same question first,
    against the servers `--mcp` actually chose, so a missing runtime costs a
    message instead of a finished-then-reverted install.

    ``installed`` is what makes "actually have to fetch" answerable at all: a
    reinstall that keeps an `npm` server exactly as it already sits on disk
    fetches nothing and needs no Node, and `_kept_dependency` -- the same test
    `_materialize_dependencies` uses to decide the same thing -- is what tells
    the two cases apart. Without it, this guard could only ask "is an `npm`
    server named", which is true on every reinstall regardless of whether
    this run would touch it.

    Fires for a dry run too, and deliberately so: the TUI's plan-preview
    screen *is* a dry run, and raising here is what lets it surface the
    missing runtime at selection time instead of at the point of no return —
    for a server this run would genuinely have to fetch.
    """
    owned = {entry.id: entry for entry in (installed.entries if installed else ())}
    needy = sorted(
        item.name
        for item in content.mcp
        if item.distribution is content_module.Distribution.NPM
        and _materializes(item)
        and _kept_dependency(runtime, owned, item) is None
    )
    if not needy or _node_present(runtime):
        return
    raise CommandError(
        f"{', '.join(needy)} need{'s' if len(needy) == 1 else ''} Node to install, and node is not on "
        f"PATH; installing Node is the user's own responsibility, so change the selection or make node "
        f"available before retrying"
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
    pruned: int = 0,
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
        "pruned": pruned,
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
    pruned: int = 0,
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
        "pruned": pruned,
    }
    return failure


def _placed(step: planner.Step) -> dict[str, Any]:
    return {"id": step.artifact.id, "target": str(step.artifact.path)}


def _recorded(record: Record) -> dict[str, Any]:
    return {"id": record.id, "kind": record.kind, "target": str(record.target)}


def _undo_placements(
    filesystem: FileSystem, applied: planner.Applied, placed: Install
) -> tuple[int, int, list[str]]:
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
        return 0, 0, [f"the rollback could not be completed: {error}"]
    return len(retired.removed), len(retired.pruned), [reason for _, reason in failures]


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


def _prose(report: dict[str, Any], *, identity: Identity | None = None) -> str:
    """The same facts, for a person. Never a subset of them.

    `identity` defaults to the packaged one: `prose_for` (this function's
    public alias) is called from `tui/view.py` with no `Runtime` in reach at
    all, so a distribution's own build still names its own product here
    without that caller needing to change; `main`, which does have a
    `Runtime`, passes `runtime.identity` explicitly instead of relying on it.
    """
    identity = identity if identity is not None else default_identity()
    if report.get("status") == "failed":
        # Joined with ": ", never ". " -- every `CommandError` in this
        # codebase starts lowercase on purpose, so it can be chained after
        # whatever composes it (see `CommandError`'s own docstring), and a
        # `CommandError` can start with a filesystem path (see `upgrade`'s
        # writability refusal). A period would leave a capital sentence
        # butting into a lowercase one; fixing that by upper-casing
        # `report['error']`'s first character would corrupt a path that
        # happened to start with a lowercase segment. A colon reads as one
        # sentence continuing into its own reason, exactly what these are,
        # without ever touching the message it is prefixed to.
        if report.get("rolled_back"):
            return f"The installation was undone: {report['error']}"
        # Claiming nothing changed is only honest when nothing did. A command
        # that got partway through says how far, because the whole point of
        # this output is that a number in it can be trusted.
        changed = len(report.get("written", ())) + len(report.get("removed", ()))
        if changed:
            return f"Stopped after changing {changed}: {report['error']}"
        return f"Nothing was changed: {report['error']}"

    command = report["command"]
    if command == "doctor":
        lines = [_cli_prose(entry, identity=identity) for entry in report["clis"]]
        if report.get("journal_error"):
            lines.append(report["journal_error"]["error"])
            lines.append(
                f"That earlier generation is what `{identity.program_name} restore` reads back."
            )
        return "\n".join(lines)
    if command == "restore" and report.get("action") == "list":
        return _restore_list_prose(report)
    if command == "restore":
        lines = [
            f"generation {report['generation']}: wrote back {len(report['written'])}, "
            f"removed {len(report['removed'])}."
        ]
        return "\n".join(_and_retention(lines, report))
    if command in ("install", "update"):
        planned = report["status"] == "planned"
        lines = [
            f"{report['cli']}: {'would create' if planned else 'created'} {len(report['created'])} artifacts, "
            f"{'would update' if planned else 'updated'} {len(report['updated'])}, "
            f"{len(report['unchanged'])} already current, skipped {len(report['skipped'])}."
        ]
        if report.get("overwritten"):
            lines.append(
                f"Overwritten, because {identity.display_name} owns these and you had changed them:"
                if not planned
                else f"Would be overwritten, because {identity.display_name} owns these and you had changed them:"
            )
            lines.extend(f"  {item['id']} → {item['target']}" for item in report["overwritten"])
            if not planned:
                lines.append(
                    f"`{identity.program_name} restore` can bring back what was just overwritten; "
                    f"`--dry-run` would have shown this list before anything was touched. "
                    f"Up to {RETAIN_GENERATIONS} generations are kept, oldest dropped first."
                )
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
        # Same reasoning as `unaccounted` just above: absent on a dry run,
        # because a plan never asks `retire` anything and so never learns what
        # it left empty behind it.
        if report.get("pruned"):
            n = len(report["pruned"])
            lines.append(f"Pruned {n} empty director{'y' if n == 1 else 'ies'}: {', '.join(report['pruned'])}")
        if report.get("model_warnings"):
            lines.append("Model assignments that could not be honoured:")
            lines.extend(f"  {warning}" for warning in report["model_warnings"])
        if report.get("grant_warnings"):
            lines.append("Carried-forward grants dropped as redundant:")
            lines.extend(f"  {warning}" for warning in report["grant_warnings"])
        if report.get("mcp_warnings"):
            lines.append("Only reported because this is a dry run:")
            lines.extend(f"  {warning}" for warning in report["mcp_warnings"])
        return "\n".join(_and_retention(_and_activation(lines, report), report))
    if command == "upgrade":
        if report["status"] == "planned":
            return (
                f"Would replace {report['destination']} ({report['old_version']}) with "
                f"{report['new_version']}. Nothing was written -- this was a dry run."
            )
        if report["status"] == "already-current":
            return f"Already running the newest published version ({report['version']}) -- nothing to do."
        return (
            f"Replaced {report['destination']}: {report['old_version']} -> {report['new_version']}. "
            f"Restart {report['program_name']} to run the new version -- this process is still "
            f"running {report['old_version']}. This only replaced the program itself: whatever is "
            f"already on disk for each CLI -- agents, skills, commands, prompts -- was not written by "
            f"{report['new_version']} and stays that way until you run "
            f"`{report['program_name']} update --cli <cli>` for it; not every upgrade changes those "
            f"artifacts, so only `update` can tell you whether this one did."
        )
    if command == "models":
        return _models_prose(report)
    if command == "mcp":
        return _mcp_prose(report)
    if command == "directory":
        return _directory_prose(report)
    if command == "repair":
        return _repair_prose(report)

    pruned = report.get("pruned") or []
    lines = [
        f"{report['cli']}: removed {len(report['removed'])}"
        + (f", pruned {len(pruned)} empty director{'y' if len(pruned) == 1 else 'ies'}." if pruned else ".")
    ]
    if report["unaccounted"]:
        lines.append(f"Could not be accounted for: {', '.join(report['unaccounted'])}")
    lines.append(
        f"`{identity.program_name} restore` can put this back exactly as it was before; "
        f"up to {RETAIN_GENERATIONS} generations are kept, oldest dropped first."
    )
    return "\n".join(_and_retention(_and_activation(lines, report), report))


def _models_prose(report: dict[str, Any]) -> str:
    action = report.get("action")
    if action == "set":
        lines = [
            f"{report['cli']}/{entry['agent']}: assigned {entry['model']}"
            + (f", effort {entry['effort']}" if entry.get("effort") else "")
            + "."
            for entry in report["assignments"]
        ]
        return "\n".join(_and_activation(lines, report))
    if action == "unset":
        if report["status"] == "already-unset":
            agents = ", ".join(report["agents"])
            return f"{report['cli']}/{agents}: no assignment to remove."
        lines = [f"{report['cli']}/{agent}: assignment removed." for agent in report["removed"]]
        return "\n".join(_and_activation(lines, report))
    if action == "list":
        if not report["assignments"]:
            return "No model assignments."
        lines = []
        for entry in report["assignments"]:
            line = f"{entry['cli']}/{entry['agent']}: {entry['model']}"
            if entry.get("effort"):
                line += f" (effort {entry['effort']})"
            if not entry.get("in_effect", True):
                line += f" -- not in effect: {entry.get('note', 'this CLI has no per-agent model capability')}"
            lines.append(line)
        return "\n".join(lines)
    return "models: nothing to report."


def _mcp_prose(report: dict[str, Any]) -> str:
    action = report.get("action")
    if action == "grant":
        keys = ", ".join(report["keys"])
        line = f"{report['cli']}: granted {keys} to every agent."
        return "\n".join(_and_activation([line], report))
    if action == "revoke":
        keys = ", ".join(report["keys"])
        if report.get("status") == "already-revoked":
            return f"{report['cli']}: {keys} was not granted; nothing to do."
        line = f"{report['cli']}: revoked {keys}."
        return "\n".join(_and_activation([line], report))
    if action == "list":
        lines = [f"Granted: {', '.join(report['granted']) or 'none'}."]
        if report.get("blocked"):
            lines.append(report["blocked"])
            return "\n".join(lines)
        if report["available"]:
            lines.append(f"Declared but not granted: {', '.join(report['available'])}.")
        if report.get("already_covered"):
            lines.append(
                f"Already covered per-agent, so granting is redundant: {', '.join(report['already_covered'])}."
            )
        return "\n".join(lines)
    return "mcp: nothing to report."


def _directory_prose(report: dict[str, Any]) -> str:
    action = report.get("action")
    if action == "grant":
        paths = ", ".join(report["paths"])
        line = f"{report['cli']}: granted {paths} to every agent."
        lines = [line, report["warning"]] if report.get("warning") else [line]
        return "\n".join(_and_activation(lines, report))
    if action == "revoke":
        paths = ", ".join(report["paths"])
        if report.get("status") == "already-revoked":
            return f"{report['cli']}: {paths} was not granted; nothing to do."
        line = f"{report['cli']}: revoked {paths}."
        return "\n".join(_and_activation([line], report))
    return "directory: nothing to report."


def _restore_list_prose(report: dict[str, Any]) -> str:
    if not report["generations"] and not report["unreadable"]:
        return "there is no snapshot generation to restore."
    lines = [
        f"generation {entry['generation']}: {entry['taken_at']}"
        + (f" ({entry['label']})" if entry["label"] else "")
        + f" -- {entry['files_restored']} to write back, {entry['paths_cleared']} to clear"
        for entry in report["generations"]
    ]
    if report["unreadable"]:
        numbers = ", ".join(str(number) for number in report["unreadable"])
        lines.append(f"could not be read, and left out: {numbers}")
    return "\n".join(lines)


def _repair_prose(report: dict[str, Any]) -> str:
    if report["status"] == "nothing-to-repair":
        line = f"{report['cli']}: nothing to repair."
        return "\n".join(_and_not_walked([line], report))
    verb = "Would remove" if report["status"] == "planned" else "Removed"
    lines: list[str] = []
    quarantined = report["removed_quarantined_directories"]
    if quarantined:
        lines.append(
            f"{report['cli']}: {verb} {len(quarantined)} quarantined granted-directory "
            f"entr{'y' if len(quarantined) == 1 else 'ies'}:"
        )
        lines.extend(f"  {item}" for item in quarantined)
    orphaned = report["removed_orphaned_directories"]
    if orphaned:
        lines.append(
            f"{report['cli']}: {verb.lower()} {len(orphaned)} orphaned empty "
            f"director{'y' if len(orphaned) == 1 else 'ies'}:"
        )
        lines.extend(f"  {item}" for item in orphaned)
    return "\n".join(_and_not_walked(_and_retention(lines, report), report))


def _and_not_walked(lines: list[str], report: dict[str, Any]) -> list[str]:
    """The part `repair` could not check, so its report never reads as
    "clean" over a subtree it never walked -- the same fact `doctor` reports
    under `directories_not_walked`, carried into this command's own output."""
    paths = report.get("directories_not_walked") or []
    if not paths:
        return lines
    return [
        *lines,
        "Could not check for orphaned directories under (a symlink):",
        *(f"  {path}" for path in paths),
    ]


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


def _cli_prose(entry: dict[str, Any], *, identity: Identity | None = None) -> str:
    identity = identity if identity is not None else default_identity()
    if not entry["detected"]:
        return f"{entry['display_name']}: not found on this machine."
    if entry.get("journal_unreadable"):
        return (
            f"{entry['display_name']}: present at {entry['config_dir']}, but {identity.display_name}'s own "
            f"record of what it installed could not be read, so nothing more can be said about it."
        )
    if not entry["pegasus_installed"]:
        return f"{entry['display_name']}: present at {entry['config_dir']}, {identity.display_name} not installed."
    line = f"{entry['display_name']}: {entry['artifacts']} artifacts installed at {entry['config_dir']}."
    for label, key in (
        ("changed by hand", "drifted"),
        ("missing", "missing"),
        ("could not be checked", "unreadable"),
        # Reads next to the others on purpose: the difference between an
        # artifact that came back wrong and one that was never checkable is
        # exactly what this line exists to keep visible.
        ("carrying no record of their own program, so unverified", "unverified"),
    ):
        if entry.get(key):
            line += f" {len(entry[key])} {label}: {', '.join(entry[key])}."
    # A condition rather than an order: whoever already restarted is done, and
    # telling them again every time would turn the notice into noise.
    steps = entry.get("activation") or []
    if steps:
        line += f"\n  If it was already running when {identity.display_name} was installed:"
        line += "".join(f"\n    {step}" for step in steps)
    if entry.get("mcp_bound"):
        # Two headlines, not one, because the per-item `detail` beneath them
        # already hedges when no key was recorded (see `cli._bound_checks`):
        # a single flat "you administer" headline over the whole list used
        # to assert more confidence than that detail ever claimed. A known
        # key is proof of a binding; its absence still names both readings.
        known = [check for check in entry["mcp_bound"] if check.get("key")]
        unknown = [check for check in entry["mcp_bound"] if not check.get("key")]
        if known:
            line += f"\n  MCP servers you administer, granted but not installed by {identity.display_name}:"
            line += "".join(f"\n    {check['id']} (bound to {check['key']!r})" for check in known)
        if unknown:
            line += (
                "\n  MCP servers granted with no configuration of their own here -- each either a "
                "server you administer, or a convention left behind by an uninstall that did not finish:"
            )
            line += "".join(f"\n    {check['id']}" for check in unknown)
    if entry.get("mcp_bound_unknown_keys"):
        line += f"\n  To find out the key(s) above, run this once, {mcp_placeholder_instruction()}:"
        line += f"\n    {entry['mcp_bound_unknown_keys']['command']}"
    if "mcp_servers" in entry:
        if entry["mcp_servers"]:
            line += "\n  MCP servers:"
            line += "".join(
                f"\n    {check['id']}: {check['status']} — {check['detail']}" for check in entry["mcp_servers"]
            )
        else:
            line += "\n  No MCP servers configured."
    if entry.get("directories_quarantined"):
        items = entry["directories_quarantined"]
        n = len(items)
        line += (
            f"\n  {n} granted-directory entr{'y' if n == 1 else 'ies'} in the journal that could not "
            f"be validated and grant nothing to any agent:"
        )
        line += "".join(f"\n    {item}" for item in items)
        line += f"\n    `{identity.program_name} repair --cli {entry['cli']}` removes them."
    if entry.get("directories_not_walked"):
        paths = entry["directories_not_walked"]
        n = len(paths)
        line += (
            f"\n  {n} path{'' if n == 1 else 's'} this could not walk because {'it is' if n == 1 else 'they are'} "
            f"a symlink, so whether there are orphaned empty directories underneath cannot be said:"
        )
        line += "".join(f"\n    {path}" for path in paths)
    if entry.get("unprunable_empty_directories"):
        paths = entry["unprunable_empty_directories"]
        n = len(paths)
        line += (
            f"\n  {n} empty director{'y' if n == 1 else 'ies'} under the configuration directory that this "
            f"installation cannot confirm as its own, and so never prunes:"
        )
        line += "".join(f"\n    {path}" for path in paths)
    return line
