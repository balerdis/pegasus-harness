"""`MANUAL.md` describes what the commands do. Three of those descriptions
were describing something else.

This file is `test_manual_mcp_screens.py`'s sibling for the flags rather than
the screens, and it follows the same discipline: every fact it holds the
document to is DERIVED -- from the parser, from an identity, or from running
the command against a real home and looking at what landed on disk. Nothing
here is a literal typed twice, and the Spanish prose around those facts is
deliberately not pattern-matched: a regex over a sentence somebody may
legitimately reword proves nothing and breaks for the wrong reasons.

The three claims, and how each was wrong:

* "Los tres reaplican la configuración renderizada al terminar" said `pegasus
  mcp list` rewrites `opencode.json`. It does not -- it loads the journal and
  reads the settings, and writes nothing at all. Two of the three write; the
  sentence counted all three.
* "Este permiso se renderiza como `"ask"` ... cada vez que un agente lo
  necesite, OpenCode va a preguntar" said a directory you grant still prompts.
  It does not: `render._permission` writes `f"{path}/*": "allow"` for every
  granted directory, *after* the `"*": "ask"` baseline, and the runtime keeps
  the last matching rule. `"ask"` is what a directory you did NOT grant gets.
  Read as written, the paragraph promised a prompt that will never come, on a
  permission whose whole point is that it stops coming.
* "la ausencia del flag ya es la decisión de no instalarlo" was true when it
  was written and is now true only for a first install. A bare `install` over
  an installation that already has a recorded selection is refused outright,
  precisely so that silence cannot retire it -- and `--mcp none` is the
  spelling that revokes it on purpose.

A fourth arrived later and is the same defect in a list rather than a
sentence: the statuses `doctor --start-mcp-servers` reports. The paragraph
named five of them and described a sixth in words, while the code emits
nine. The list was typed by hand, so it could only ever be as current as the
last person who remembered it -- and `bound`, the ordinary state of a server
you administer yourself, was one of the missing ones, which left the normal
report of such an installation looking like a gap.

A fifth is a condition the product does not have and a path it does not
own. "el comando avisa esto mismo **si** el agente no la tiene todavía"
described a notice `models set` and `models unset` emit unconditionally,
with nothing anywhere that looks at what the installation carries. And
`install` is not the only way a stored assignment reaches the rendered
configuration: `update`, `mcp grant` and `directory grant` re-render too, so
a person who ran any of them already has it.

A sixth was an omission rather than a wrong sentence, and it nearly cost a
real installation its bound servers: the section where a person first types
`--mcp` never said the flag has two spellings. Binding was explained in the
selection screen's section and again in the grant section, both far below,
so a reader who stopped after installing had been shown only half of what
the flag accepts.

And one gap, the same surface read the other way round: `pegasus upgrade`
shipped and the manual never learned it existed. The last class here derives
the whole top-level surface from the parser, so the next command cannot go
missing the way that one did -- see its own docstring for what a coverage
check can and cannot prove.

Each corrected paragraph is found by the name of the guard that measures it,
which is the convention `tests/test_manual_figures.py` already established: a
machine-shaped token somebody has to edit on purpose, and the same sentence
that tells a reader where the fact was checked. The coverage class is the
exception and names itself nowhere in the document: it holds no single claim
a sentence could point at.
"""
from __future__ import annotations

import argparse
import ast
import contextlib
import io
import json
import re
import unittest
from pathlib import Path

from fakes import FakeMCPProcess
from pegasus import cli
from pegasus.adapters import available
from pegasus.core import journal as journal_module
from pegasus.core.types import Environment, ModelAssignment
from real_home import RealHomeTestCase as _RealHomeTestCase

REPOSITORY = Path(__file__).resolve().parents[1]
MANUAL = REPOSITORY / "MANUAL.md"
#: `MANUAL.md`'s Claude Code sibling. It documents a different CLI's own
#: surface, never restating a claim `MANUAL.md` already carries, so it gets
#: its own narrow coverage check below rather than joining any of the
#: OpenCode-specific classes above -- those exercise capabilities (`mcp`
#: selection screens, `per_agent_model`, sub-agents declared inside the
#: settings file) this document never claims for Claude Code.
MANUAL_CLAUDE_CODE = REPOSITORY / "MANUAL-claude-code.md"

#: This module, derived rather than retyped, so renaming it fails here and
#: names the document that has to follow.
GUARD_MODULE = Path(__file__).relative_to(REPOSITORY).as_posix()

AT = "2026-08-14T00:00:00+00:00"
# Pinned to OpenCode, not "whichever adapter is registered first": this
# suite exercises capabilities (mcp, per_agent_model, subagents declared
# inside the settings file, ...) that only OpenCode declares today. Since
# Claude Code registered, "available().ids()[0]" resolves alphabetically
# to "claudecode" instead, which cannot support what this file tests.
CLI = "opencode"
NO_BINARY = {"PATH": ""}

#: A server this release ships that needs nothing fetched and no Node on the
#: PATH, so an install can record a real selection without the suite reaching
#: for a network it refuses to have.
REMOTE_SERVER = "context7"

#: A key Pegasus never heard of, standing in for a server the person
#: administers themselves -- the same stand-in `tests/test_cli_mcp.py` uses,
#: and pinned below for the same reason: the day it becomes a shipped server,
#: `mcp grant` starts refusing it and every measurement here silently stops
#: measuring what it says it does.
OWN_KEY = "figma"


def paragraph_naming(guard: str) -> str:
    """The one line of the manual that names ``guard``.

    Empty when there is not exactly one, so every assertion built on it fails
    loudly instead of proving something about nothing.
    """
    lines = [line for line in MANUAL.read_text(encoding="utf-8").splitlines() if f"`{guard}`" in line]
    return lines[0] if len(lines) == 1 else ""


def subcommands_under(dest: str) -> frozenset[str]:
    """Every subcommand the real parser offers under ``dest``.

    Read off `cli._parser` rather than listed here, so a subcommand added or
    removed reaches this file instead of going unnoticed by it.
    """
    found: set[str] = set()

    def walk(parser: argparse.ArgumentParser) -> None:
        for action in parser._actions:
            if not isinstance(action, argparse._SubParsersAction):
                continue
            if action.dest == dest:
                found.update(action.choices)
            for child in action.choices.values():
                walk(child)

    walk(cli._parser(cli.default_identity()))
    return frozenset(found)


#: Where every status a `doctor` report can print is built: the one type the
#: report's status field comes from, wherever in the package it is constructed.
STATUS_TYPE = "ServerCheck"

#: A status as the manual spells one -- alone, in backticks, lower case. The
#: paragraph is held to this in both directions, so the shape is deliberately
#: narrow enough that nothing else in that sentence can match it by accident.
SPELLED_STATUS = re.compile(r"`([a-z][a-z-]*)`")


def server_check_statuses() -> tuple[frozenset[str], tuple[str, ...]]:
    """Every value a server's verdict can carry as its status.

    Derived from the package rather than listed here, which is the whole
    point: the hand-typed list in the manual named five of nine, and nothing
    anywhere could notice. Every `ServerCheck(...)` construction under
    `src/pegasus/` is read out of the source, and its status argument
    resolved -- a literal as itself, a name against the module-level string
    constants of the file it was written in, which is how `mcp_handshake`
    spells its five.

    The source is read and not run because these are constructions spread
    across two functions and a classifier, several of which need a process
    that failed in a particular way to reach; running for the set would mean
    producing every failure mode the product can have, and would still leave
    the ones nobody managed to produce silently missing. Reading finds them
    all. What running is for is where each one lands in the report, and the
    class below runs for exactly that.

    Anything that could not be resolved comes back separately rather than
    being dropped: a status built some way this cannot read is a hole in the
    derivation, and a hole that fails loudly is the only kind worth having.
    """
    found: set[str] = set()
    unresolved: list[str] = []
    for path in sorted((REPOSITORY / "src" / "pegasus").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        constants = {
            target.id: node.value.value
            for node in tree.body
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
            for target in node.targets
            if isinstance(target, ast.Name)
        }
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            called = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", None)
            if called != STATUS_TYPE:
                continue
            status = node.args[1] if len(node.args) > 1 else None
            if isinstance(status, ast.Constant) and isinstance(status.value, str):
                found.add(status.value)
            elif isinstance(status, ast.Name) and status.id in constants:
                found.add(constants[status.id])
            else:
                unresolved.append(f"{path.relative_to(REPOSITORY).as_posix()}:{node.lineno}")
    return frozenset(found), tuple(unresolved)


class RealHomeTestCase(_RealHomeTestCase):
    """The same throwaway-home harness `tests/test_cli_mcp.py` runs on: real
    disk, real journal, the commands driven through `cli.main` exactly as a
    person would type them."""

    def runtime(self) -> cli.Runtime:
        return cli.Runtime(
            filesystem=self.filesystem, home=self.home, now=AT, out=io.StringIO(), variables=NO_BINARY
        )

    def layout(self):
        return available().get(CLI).layout(Environment(home=self.home))

    def present(self) -> None:
        self.layout().config_dir.mkdir(parents=True, exist_ok=True)

    def run_cli(self, *argv) -> tuple[int, dict]:
        context = self.runtime()
        code = cli.main([*argv, "--json"], runtime=context)
        return code, json.loads(context.out.getvalue())

    def rendered(self) -> bytes:
        return self.layout().settings_file.read_bytes()

    def whole_home(self) -> dict[Path, bytes]:
        return {path: path.read_bytes() for path in self.home.rglob("*") if path.is_file()}

    def installed(self):
        return journal_module.install_for(cli.journal_store(self.runtime()).load(), CLI)

    def declare_own_mcp_server(self, key: str) -> None:
        """What a person administering their own MCP server leaves in the
        CLI's own configuration: a key under `/mcp` Pegasus never wrote."""
        settings = self.layout().settings_file
        document = json.loads(settings.read_text(encoding="utf-8"))
        document.setdefault("mcp", {})[key] = {"type": "local", "command": [f"{key}-server"]}
        settings.write_text(json.dumps(document, indent=2), encoding="utf-8")


class ManualSaysWhichMcpSubcommandsRewriteTheConfigurationTest(RealHomeTestCase):
    """Which of `pegasus mcp`'s subcommands write, measured by running them.

    The partition is produced here rather than read out of the source: each
    subcommand is run against a real installation and the rendered
    `opencode.json` is compared byte for byte across the call. A source-level
    check for "this one calls `install`" would approve by a proxy and would
    keep passing the day the call is added somewhere it should not be.

    `list` is also checked against the *whole* home and not just the settings
    file: "no escribe nada" is a claim about the machine, and a command that
    left a snapshot generation or a journal write behind would satisfy a
    narrower check while making the sentence false.
    """

    def setUp(self):
        super().setUp()
        self.present()
        self.run_cli("install", "--cli", CLI, "--mcp", cli._MCP_NONE)
        self.declare_own_mcp_server(OWN_KEY)
        self.offered = subcommands_under("mcp_command")
        self.writes: set[str] = set()
        self.reads: set[str] = set()
        self._measure("list")
        self._measure("grant", OWN_KEY)
        self._measure("revoke", OWN_KEY)

    def _measure(self, name: str, *arguments: str) -> None:
        before_home = self.whole_home()
        before = self.rendered()
        code, _ = self.run_cli("mcp", name, "--cli", CLI, *arguments)
        self.assertEqual(code, 0, f"`mcp {name}` failed, so nothing here measured anything")
        if self.rendered() != before:
            self.writes.add(name)
        else:
            self.reads.add(name)
            self.assertEqual(
                self.whole_home(), before_home, f"`mcp {name}` wrote somewhere outside the rendered configuration"
            )

    def test_the_stand_in_key_is_not_a_shipped_server(self):
        """Or `grant` would refuse it and the measurement above would be of a
        failure, not of a write."""
        from pegasus.core import content as content_module

        self.assertNotIn(OWN_KEY, {item.name for item in content_module.load().mcp})

    def test_every_subcommand_the_parser_offers_was_measured(self):
        """A fourth subcommand must reach this file rather than slip past the
        sentence it would also belong in."""
        self.assertEqual(self.writes | self.reads, self.offered)

    def test_some_rewrite_and_some_do_not(self):
        """Both halves have to be non-empty, or the two assertions below are
        each satisfied by an empty set and prove nothing."""
        self.assertTrue(self.writes)
        self.assertTrue(self.reads)

    def test_the_paragraph_is_found_exactly_once(self):
        self.assertTrue(
            paragraph_naming(type(self).__name__),
            f"no single line of {MANUAL.name} names {type(self).__name__}",
        )

    def test_the_paragraph_names_every_subcommand_that_rewrites(self):
        paragraph = paragraph_naming(type(self).__name__)
        program = cli.default_identity().program_name
        for name in sorted(self.writes):
            self.assertIn(f"`{program} mcp {name}`", paragraph)

    def test_the_paragraph_claims_nothing_for_the_ones_that_do_not(self):
        """The defect itself: `list` was inside the claim, so a reader was
        told a read-only command rewrites their configuration."""
        paragraph = paragraph_naming(type(self).__name__)
        program = cli.default_identity().program_name
        for name in sorted(self.reads):
            self.assertNotIn(f"`{program} mcp {name}`", paragraph)
            self.assertNotIn(f"`{name}`", paragraph)

    def test_the_paragraph_says_where_this_was_measured(self):
        self.assertIn(f"`{GUARD_MODULE}`", paragraph_naming(type(self).__name__))


class ManualSaysHowAGrantedDirectoryIsRenderedTest(RealHomeTestCase):
    """What `pegasus directory grant` actually writes into `opencode.json`.

    The example path is not chosen here: it is read out of the manual's own
    fenced `directory grant` command, whose first two words come from this
    binary's identity. So the directory this grants is the directory the
    reader was told to grant, and the entry asserted below is the entry that
    reader would find on their own machine.

    Run end to end, against real disk, because the claim is about what lands
    in the configuration file -- not about what `render._permission` returns
    on the way there.
    """

    def setUp(self):
        super().setUp()
        self.path = self.example_path()
        self.present()
        self.run_cli("install", "--cli", CLI, "--mcp", cli._MCP_NONE)
        code, _ = self.run_cli("directory", "grant", "--cli", CLI, self.path)
        self.assertEqual(code, 0, "the manual's own example grant failed")
        self.maps = [
            agent["permission"]["external_directory"]
            for agent in json.loads(self.rendered())["agent"].values()
            if "external_directory" in agent.get("permission", {})
        ]

    @staticmethod
    def example_path() -> str:
        """The directory the manual's own fenced command grants."""
        program = cli.default_identity().program_name
        fenced = re.compile(rf"^{re.escape(program)} directory grant --cli \S+ (\S+)$", re.MULTILINE)
        found = fenced.findall(MANUAL.read_text(encoding="utf-8"))
        return found[0] if len(set(found)) == 1 else ""

    def test_the_manual_shows_a_single_example_directory(self):
        """Everything below grants it; two different ones, or none, would
        leave this measuring a path nobody was shown."""
        self.assertTrue(self.example_path(), f"{MANUAL.name} has no single fenced directory grant to read")

    def test_every_agent_carries_the_granted_directory(self):
        """The manual's other claim about this: a grant reaches every agent,
        primary and sub-agent alike."""
        self.assertTrue(self.maps)
        self.assertEqual(len(self.maps), len(json.loads(self.rendered())["agent"]))
        for entry in self.maps:
            self.assertIn(f"{self.path}/*", entry)

    def test_a_grant_is_not_a_prompt(self):
        """Still never a prompt -- but for a different reason than when this
        test was written. The baseline itself is `"allow"` now, a deliberate
        product decision surfaced by upstream #39112 (see `_permission`'s
        own docstring), so a granted directory's own entry is the *same*
        value as the baseline it is written after, not a different one that
        out-ranks it. Asserting equality here, not inequality, is the point:
        it is exactly what makes granting a directory dormant rather than
        useful right now -- the entry is still written and still survives
        every `install`/`update`, and it would regain its own meaning
        without anyone having to grant it again, should the baseline ever
        become `"ask"` for some other reason.
        """
        for entry in self.maps:
            self.assertEqual(entry[f"{self.path}/*"], entry["*"])

    def test_the_paragraph_quotes_the_entry_a_grant_actually_writes(self):
        """Both halves, each attached to what it belongs to."""
        paragraph = paragraph_naming(type(self).__name__)
        entry = self.maps[0]
        granted = json.dumps({f"{self.path}/*": entry[f"{self.path}/*"]})[1:-1]
        baseline = json.dumps({"*": entry["*"]})[1:-1]
        self.assertIn(granted, paragraph)
        self.assertIn(baseline, paragraph)

    def test_the_paragraph_is_found_exactly_once(self):
        self.assertTrue(
            paragraph_naming(type(self).__name__),
            f"no single line of {MANUAL.name} names {type(self).__name__}",
        )

    def test_the_paragraph_says_where_this_was_measured(self):
        self.assertIn(f"`{GUARD_MODULE}`", paragraph_naming(type(self).__name__))


class ManualSaysHowAnMcpSelectionIsRevokedOnPurposeTest(RealHomeTestCase):
    """Silence about `--mcp` stopped meaning "install nothing" for a repeat
    install, and the manual still said it did.

    A first install with no `--mcp` selects nothing, which is what the
    sentence was written for and still true. A *second* one, over an
    installation whose selection is already recorded, is refused before
    anything is written -- a bare reinstall run for an unrelated reason would
    otherwise retire every server, convention and binding it had, and report
    success. `--mcp none` is the one spelling that asks for that retirement on
    purpose.

    All three are run here rather than read: the refusal, the fact that it
    wrote nothing, and that the deliberate spelling really does empty the
    recorded selection.
    """

    def setUp(self):
        super().setUp()
        self.present()
        self.run_cli("install", "--cli", CLI, "--mcp", REMOTE_SERVER)

    def test_the_example_server_is_one_this_release_ships(self):
        from pegasus.core import content as content_module

        self.assertIn(REMOTE_SERVER, {item.name for item in content_module.load().mcp})

    def test_a_bare_reinstall_over_a_recorded_selection_is_refused(self):
        before = self.whole_home()
        code, report = self.run_cli("install", "--cli", CLI)
        self.assertNotEqual(code, 0)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(self.whole_home(), before)

    def recorded_selection(self) -> tuple[str, ...]:
        """What a later `update` would replay -- the installation's own
        recorded selection, reconstructed the one way the engine reconstructs
        it rather than read off a field that does not exist."""
        selection, unresolved = cli._mcp_update_selection(
            self.installed(), display_name=cli.default_identity().display_name
        )
        self.assertEqual(unresolved, [])
        return tuple(selection)

    def test_the_recorded_selection_is_what_the_refusal_is_protecting(self):
        """Or the refusal above would be firing over nothing."""
        self.assertEqual(self.recorded_selection(), (REMOTE_SERVER,))

    def test_the_deliberate_spelling_empties_the_recorded_selection(self):
        code, _ = self.run_cli("install", "--cli", CLI, "--mcp", cli._MCP_NONE)
        self.assertEqual(code, 0)
        self.assertEqual(self.recorded_selection(), ())
        # And with nothing recorded, silence is harmless again: the refusal is
        # about losing a selection, not about the flag being absent.
        self.assertEqual(self.run_cli("install", "--cli", CLI)[0], 0)

    def test_the_paragraph_is_found_exactly_once(self):
        self.assertTrue(
            paragraph_naming(type(self).__name__),
            f"no single line of {MANUAL.name} names {type(self).__name__}",
        )

    def test_the_paragraph_names_the_deliberate_spelling(self):
        """Derived from the flag value the CLI actually understands, so a
        rename of it fails here and names the document that has to follow."""
        self.assertIn(f"`--mcp {cli._MCP_NONE}`", paragraph_naming(type(self).__name__))

    def test_the_paragraph_says_where_this_was_measured(self):
        self.assertIn(f"`{GUARD_MODULE}`", paragraph_naming(type(self).__name__))


class ManualSaysEveryStatusDoctorCanReportTest(RealHomeTestCase):
    """The statuses a `doctor` report can put beside a server's name.

    The manual listed five and described a sixth in prose. The package emits
    nine, so four states a person could be looking at right now had no entry
    anywhere: `unreadable` and `missing`, which `doctor --start-mcp-servers`
    puts in the launched-server list, and `bound`, which is neither a fault
    nor even the result of launching anything -- it is what a server you
    administer yourself gets, under its own heading, in a plain `doctor` too.
    A reader who saw `bound` on a perfectly healthy installation had nothing
    in the document to tell them it was the normal state.

    The set is derived (see `server_check_statuses`) so a status added later
    lands here rather than in a list nobody edits. Where each one is reported
    is RUN, because that is the half a derivation cannot answer and the half
    the old paragraph got wrong: a bound server is installed here for real
    and the report is asked about it, and a remote one likewise -- and both
    runs hold a launcher that raises if anything is ever started, so "no se
    arranca" is proven rather than repeated.
    """

    def setUp(self):
        super().setUp()
        self.present()
        self.launcher = FakeMCPProcess()
        self.statuses, self.unresolved = server_check_statuses()
        self.paragraph = paragraph_naming(type(self).__name__)

    def runtime(self) -> cli.Runtime:
        """The same throwaway runtime the rest of this file uses, holding a
        launcher with no exchange registered for anything: any attempt to
        start a server raises instead of spawning one."""
        return cli.Runtime(
            filesystem=self.filesystem,
            home=self.home,
            now=AT,
            out=io.StringIO(),
            variables=NO_BINARY,
            mcp_process=self.launcher,
        )

    def health(self, *flags: str) -> dict:
        code, report = self.run_cli("doctor", *flags)
        self.assertEqual(code, 0)
        found = [entry for entry in report["clis"] if entry["cli"] == CLI]
        self.assertEqual(len(found), 1, f"the report no longer holds exactly one entry for {CLI}")
        return found[0]

    def test_every_status_the_package_builds_was_resolved(self):
        """A construction this could not read would be a status quietly
        missing from everything below."""
        self.assertEqual(self.unresolved, ())
        self.assertTrue(self.statuses, "no server status found at all, so nothing here proves anything")

    def test_a_server_bound_to_a_key_you_administer_is_reported_and_never_started(self):
        """The defect's own case. This installation is healthy and ordinary,
        and the whole of what the report says about that server is a status
        the manual did not have."""
        code, _ = self.run_cli("install", "--cli", CLI, "--mcp", f"{REMOTE_SERVER}={OWN_KEY}")
        self.assertEqual(code, 0)
        health = self.health("--start-mcp-servers")
        bound = {check["id"]: check["status"] for check in health["mcp_bound"]}
        self.assertEqual(bound, {REMOTE_SERVER: "bound"})
        self.assertEqual(health["mcp_servers"], [])
        self.assertEqual(self.launcher.calls, [])

    def test_the_bound_status_is_reported_without_the_flag_too(self):
        """The paragraph's other half about it: a person who never passes the
        flag still sees this, so it cannot be described as something the flag
        produces."""
        code, _ = self.run_cli("install", "--cli", CLI, "--mcp", f"{REMOTE_SERVER}={OWN_KEY}")
        self.assertEqual(code, 0)
        health = self.health()
        bound = {check["id"]: check["status"] for check in health["mcp_bound"]}
        self.assertEqual(bound, {REMOTE_SERVER: "bound"})
        self.assertNotIn("mcp_servers", health)
        self.assertEqual(self.launcher.calls, [])

    def test_a_server_pegasus_administers_is_reported_in_the_launched_list(self):
        """The other side of the same partition, so the paragraph's two
        halves are each measured against a real installation rather than one
        being inferred from the other."""
        code, _ = self.run_cli("install", "--cli", CLI, "--mcp", REMOTE_SERVER)
        self.assertEqual(code, 0)
        health = self.health("--start-mcp-servers")
        launched = {check["id"]: check["status"] for check in health["mcp_servers"]}
        self.assertEqual(launched, {REMOTE_SERVER: "remote"})
        self.assertEqual(health["mcp_bound"], [])
        self.assertEqual(self.launcher.calls, [])

    def test_the_paragraph_is_found_exactly_once(self):
        self.assertTrue(
            self.paragraph, f"no single line of {MANUAL.name} names {type(self).__name__}"
        )

    def test_the_paragraph_names_every_status_the_package_can_report(self):
        """The defect itself: five of nine, typed by hand."""
        missing = sorted(status for status in self.statuses if f"`{status}`" not in self.paragraph)
        self.assertEqual(missing, [], f"{MANUAL.name} does not name these statuses: {missing}")

    def test_the_paragraph_names_no_status_the_package_no_longer_has(self):
        """The direction the check above cannot see. Dropping a status from
        the package leaves every remaining one still documented, so that
        check stays green while the manual describes a state nobody can ever
        be in."""
        spelled = set(SPELLED_STATUS.findall(self.paragraph))
        self.assertTrue(spelled, "the paragraph spells no status at all, so this proves nothing")
        self.assertEqual(spelled - self.statuses, set())

    def test_the_paragraph_says_where_this_was_measured(self):
        self.assertIn(f"`{GUARD_MODULE}`", self.paragraph)


#: A `--mcp` value as the manual shows one: backticked, whole, with whatever
#: placeholder the document spells an id and a key with.
MCP_SPELLING = re.compile(r"`--mcp ([^`]+)`")


def agents_reached_by(key: str) -> frozenset[str]:
    """Every agent a shipped server's own descriptor reaches, off `reaches`,
    which is where that fact lives: `optional_mcp` is derived from these
    lists, so this is the same set the render works from."""
    from pegasus.core import content as content_module

    server = next((item for item in content_module.load().mcp if item.name == key), None)
    return frozenset(server.reaches) if server is not None else frozenset()


class ManualSaysWhatTheTwoMcpSpellingsAskForTest(RealHomeTestCase):
    """What a bare `--mcp <id>` asks for, and what `--mcp <id>=<clave>` asks
    for instead.

    The section where a person first types the flag did not say there were
    two. The difference is not a detail of spelling: one asks Pegasus to
    obtain and administer the server, the other asks only for the contract --
    the convention and the permissions -- against a server the installation
    already runs under that key, and Pegasus configures nothing for that id
    at all. A reader who never got that far down the document had no way to
    know the second form existed, and a reinstall spelled the first way takes
    over a server somebody else's key was administering.

    Both are RUN against a real installation, and the difference is read off
    the rendered configuration: which servers it configures, and which prefix
    each agent is granted. The set of agents is derived from the shipped
    descriptor's own `reaches`, so the two runs are held to the same reach
    rather than to each other -- a binding that quietly narrowed who gets the
    server would otherwise look identical to one that did not.

    The in-document link the paragraph carries is deliberately not asserted
    here: `tools/check_docs_links.py` already fails the suite over an anchor
    that does not resolve, and a second check of the same fact would only be
    a second thing to update.
    """

    def setUp(self):
        super().setUp()
        self.present()
        self.reached = agents_reached_by(REMOTE_SERVER)
        self.paragraph = paragraph_naming(type(self).__name__)

    def configured_servers(self) -> frozenset[str]:
        return frozenset(json.loads(self.rendered()).get("mcp", {}))

    def agents_granting(self, key: str) -> frozenset[str]:
        document = json.loads(self.rendered())
        return frozenset(
            name
            for name, agent in document["agent"].items()
            if agent.get("permission", {}).get(f"{key}*") == "allow"
        )

    def test_the_two_spellings_are_the_ones_the_flag_actually_reads(self):
        """Straight off the parser the flag's values go through, so a change
        to what `=` means reaches this file."""
        from pegasus.core import content as content_module

        self.assertEqual(content_module.parse_mcp_choice(REMOTE_SERVER), (REMOTE_SERVER, None))
        self.assertEqual(
            content_module.parse_mcp_choice(f"{REMOTE_SERVER}={OWN_KEY}"), (REMOTE_SERVER, OWN_KEY)
        )

    def test_the_example_server_reaches_agents_at_all(self):
        """Or both runs below would be comparing two empty sets."""
        self.assertTrue(self.reached, f"{REMOTE_SERVER} reaches no agent, so nothing here proves anything")

    def test_the_bare_spelling_has_pegasus_obtain_and_administer_the_server(self):
        code, _ = self.run_cli("install", "--cli", CLI, "--mcp", REMOTE_SERVER)
        self.assertEqual(code, 0)
        self.assertIn(REMOTE_SERVER, self.configured_servers())
        self.assertEqual(self.agents_granting(REMOTE_SERVER), self.reached)

    def test_the_bound_spelling_configures_nothing_and_grants_the_key_instead(self):
        code, _ = self.run_cli("install", "--cli", CLI, "--mcp", f"{REMOTE_SERVER}={OWN_KEY}")
        self.assertEqual(code, 0)
        self.assertNotIn(REMOTE_SERVER, self.configured_servers())
        self.assertEqual(self.agents_granting(REMOTE_SERVER), frozenset())
        self.assertEqual(self.agents_granting(OWN_KEY), self.reached)

    def test_the_paragraph_is_found_exactly_once(self):
        self.assertTrue(
            self.paragraph, f"no single line of {MANUAL.name} names {type(self).__name__}"
        )

    def test_the_paragraph_shows_both_spellings_of_the_same_flag(self):
        """The omission itself. Two forms, the second the first plus a key,
        so a paragraph that drifts back to showing one of them fails."""
        shown = MCP_SPELLING.findall(self.paragraph)
        bare = [spelling for spelling in shown if "=" not in spelling]
        bound = [spelling for spelling in shown if "=" in spelling]
        self.assertEqual(len(bare), 1, f"the paragraph shows {len(bare)} bare spellings: {shown}")
        self.assertEqual(len(bound), 1, f"the paragraph shows {len(bound)} bound spellings: {shown}")
        self.assertTrue(
            bound[0].startswith(f"{bare[0]}="),
            f"the two spellings do not name the same id: {bare[0]!r} and {bound[0]!r}",
        )

    def test_the_paragraph_says_where_this_was_measured(self):
        self.assertIn(f"`{GUARD_MODULE}`", self.paragraph)


#: A provider and four models the throwaway machine below is told it can
#: reach. A stored assignment is only honoured when that machine's own catalog
#: lists it, so without this every run there would render no model at all and
#: prove nothing. One model per path measured, so a configuration still
#: carrying the previous one cannot be mistaken for a fresh write.
MODEL_PROVIDER = "anthropic"
MODEL_PREFERENCES = tuple(f"{MODEL_PROVIDER}/claude-preference-{index}" for index in range(4))


class ManualSaysWhenAModelAssignmentReachesTheConfigurationTest(RealHomeTestCase):
    """When an assignment reaches the rendered configuration, and what puts it there.

    The sentence has been wrong twice, in opposite directions, and both are
    worth keeping in view because the guard below is shaped by them.

    It first described the activation notice as conditional -- "avisa esto
    mismo **si** el agente no la tiene todavía" -- when `models set` and
    `models unset` emitted it unconditionally and asked the installation
    nothing. It then said `install` was what wrote the assignment in, when
    three other commands re-render the configuration and carry a stored
    assignment with them.

    Both of those described a product where recording a preference and
    rendering it were two steps. They are one step now: `models set` reapplies
    the configuration itself, the way `mcp grant` and `directory grant` always
    have, so there is no second command for a person to remember and no notice
    telling them to run one. What is left afterwards is the CLI's own
    activation step, which is a fact about the CLI and not about Pegasus.

    Everything here is RUN against a real installation and the rendered file
    read back off disk, because "reaches the configuration" is a claim about a
    file OpenCode opens; a source-level check for "this one calls `install`"
    would approve by a proxy.

    What this cannot prove is that no FIFTH command re-renders the same way:
    the set is the one the sentence names, not one derived from the parser,
    because deriving it would mean running every top-level command against a
    live installation -- `uninstall` and `restore` among them -- and measuring
    the wreckage. The direction that matters to a reader is held: everything
    the sentence names really does write it.
    """

    PROVIDER = MODEL_PROVIDER
    MODELS = MODEL_PREFERENCES

    def setUp(self):
        super().setUp()
        self.present()
        self.write_models_catalog()
        self.run_cli("install", "--cli", CLI, "--mcp", cli._MCP_NONE)
        self.declare_own_mcp_server(OWN_KEY)
        self.agent = self.a_configurable_agent()
        self.paragraph = paragraph_naming(type(self).__name__)

    def write_models_catalog(self) -> None:
        """What a machine with a reachable provider looks like, written the
        same way `tests/test_cli.py` writes one."""
        path = self.home / ".cache" / "opencode" / "models.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        models = {full_id.split("/", 1)[1]: {"tool_call": True} for full_id in self.MODELS}
        path.write_text(
            json.dumps({self.PROVIDER: {"builtin": True, "models": models}}), encoding="utf-8"
        )

    @staticmethod
    def a_configurable_agent() -> str:
        """One agent that accepts an assignment, off the content tree rather
        than named here."""
        from pegasus.core import content as content_module

        found = sorted(agent.name for agent in content_module.load().agents if agent.model_configurable)
        return found[0] if found else ""

    def writers(self) -> tuple[tuple[str, tuple[str, ...]], ...]:
        """Every path the paragraph names as re-rendering the whole
        configuration, and how a person types it. `models set` is not here:
        it is measured on its own below, because what it proves is that
        nothing else has to be run at all."""
        return (
            ("install", ("install", "--cli", CLI)),
            ("update", ("update", "--cli", CLI)),
            ("mcp grant", ("mcp", "grant", "--cli", CLI, OWN_KEY)),
            ("directory grant", ("directory", "grant", "--cli", CLI, str(self.home / "worktrees" / "otro-repo"))),
        )

    def rendered_model(self) -> str | None:
        return json.loads(self.rendered())["agent"][self.agent].get("model")

    def store_without_rendering(self, model: str) -> None:
        """A preference sitting in Pegasus's own state that the rendered
        configuration does not carry.

        `models set` renders what it records, so this state can no longer be
        produced by running it -- and it is exactly the state the four
        commands below exist to rescue (an assignment stored while its
        provider was unreachable, say, or one carried over from a release
        that did not render on assignment). Written straight to the store,
        the same way `tests/test_cli.py` builds a stale preference, so what
        each command is measured against is real rather than arranged.
        """
        from pegasus.core import model_assignments as model_assignments_module

        store = cli.model_assignment_store(self.runtime())
        store.save(model_assignments_module.with_assignment(
            store.load(), CLI, self.agent, ModelAssignment.parse(model, None)
        ))

    def test_there_is_an_agent_to_assign_a_model_to(self):
        """Or every run below would be measuring a refusal."""
        self.assertTrue(self.agent, "this release ships no agent that accepts a model assignment")

    def test_setting_writes_the_assignment_with_no_further_command(self):
        """The claim the corrected sentence makes, read off the file OpenCode
        opens rather than off what the command reported."""
        model = self.MODELS[0]
        self.assertNotEqual(self.rendered_model(), model, "the fixture had nothing left to write")
        code, _ = self.run_cli("models", "set", "--cli", CLI, "--assign", f"{self.agent}={model}")
        self.assertEqual(code, 0)
        self.assertEqual(self.rendered_model(), model)

    def test_removing_takes_the_assignment_back_out_with_no_further_command(self):
        model = self.MODELS[1]
        self.run_cli("models", "set", "--cli", CLI, "--assign", f"{self.agent}={model}")
        self.assertEqual(self.rendered_model(), model)
        code, _ = self.run_cli("models", "unset", "--cli", CLI, "--agent", self.agent)
        self.assertEqual(code, 0)
        self.assertIsNone(self.rendered_model())

    def test_what_is_left_afterwards_is_the_clis_own_activation_step(self):
        """Why the sentence no longer tells a person to run anything: what
        comes back is the CLI's own step, derived from the adapter so a
        rewording there reaches the document instead of going unnoticed."""
        code, report = self.run_cli(
            "models", "set", "--cli", CLI, "--assign", f"{self.agent}={self.MODELS[0]}")
        self.assertEqual(code, 0)
        self.assertEqual(tuple(report["activation"]), available().get(CLI).activation_steps())

    def test_a_cli_with_nothing_installed_is_refused(self):
        """The other half of "lo escribe en el mismo comando": there has to be
        a configuration to write into, so both commands refuse without one --
        the same refusal `mcp grant` and `directory grant` already give. The
        installation is taken back out by running `uninstall`, rather than by
        arranging a home that never had one, so what is measured is the state
        a person actually ends up in."""
        code, _ = self.run_cli("uninstall", "--cli", CLI)
        self.assertEqual(code, 0)
        for argv in (
            ("models", "set", "--cli", CLI, "--assign", f"{self.agent}={self.MODELS[0]}"),
            ("models", "unset", "--cli", CLI, "--agent", self.agent),
        ):
            with self.subTest(command=" ".join(argv[:2])):
                code, report = self.run_cli(*argv)
                self.assertNotEqual(code, 0)
                self.assertIn("nothing installed", report["error"])

    def test_every_path_the_paragraph_names_writes_a_stored_assignment(self):
        """The half that was too narrow, one real installation and one real
        rendered file at a time."""
        for model, (name, argv) in zip(self.MODELS, self.writers()):
            with self.subTest(command=name):
                self.run_cli("models", "unset", "--cli", CLI, "--agent", self.agent)
                self.store_without_rendering(model)
                self.assertNotEqual(self.rendered_model(), model, f"{name} had nothing left to write")
                code, _ = self.run_cli(*argv)
                self.assertEqual(code, 0, f"`{name}` failed, so nothing here measured anything")
                self.assertEqual(self.rendered_model(), model)

    def test_the_paragraph_is_found_exactly_once(self):
        self.assertTrue(
            self.paragraph, f"no single line of {MANUAL.name} names {type(self).__name__}"
        )

    def test_the_paragraph_names_the_commands_that_write_it_themselves(self):
        for command in ("models set", "models unset"):
            self.assertIn(f"`{command}", self.paragraph, f"{MANUAL.name} does not name {command}")

    def test_the_paragraph_names_every_path_measured_here(self):
        program = cli.default_identity().program_name
        for name, _ in self.writers():
            self.assertIn(f"`{program} {name}", self.paragraph, f"{MANUAL.name} does not name {name}")

    def test_the_paragraph_says_where_this_was_measured(self):
        self.assertIn(f"`{GUARD_MODULE}`", self.paragraph)


class ManualDocumentsEveryTopLevelCommandTest(RealHomeTestCase):
    """Every subcommand the flags offer is reachable from this manual.

    `pegasus upgrade` shipped and the manual never learned it existed: the
    document covered `install`, `update`, `uninstall`, `repair`, `doctor`,
    `restore`, `models`, `mcp` and `directory`, and simply stopped there. A
    reader looking for how to replace the binary found nothing, and nothing
    anywhere said the list had gone short.

    What this proves and what it does not, plainly: it proves each command is
    named in the document as something a person can type, derived from the
    real parser so the tenth command cannot slip past the way the ninth did.
    It does not prove that what the manual then says about a command is true
    -- that is held, one claim at a time, by the guards above and by
    `tests/test_manual_figures.py`, and no coverage check can stand in for
    them.

    The version flag is here rather than in a class of its own because it is
    the same gap in the same surface: a way to ask this binary what it is,
    answered by the parser alone, that a person reads about in the same
    breath as replacing it.
    """

    def setUp(self):
        super().setUp()
        self.manual = MANUAL.read_text(encoding="utf-8")
        self.program = cli.default_identity().program_name

    def test_the_parser_offers_a_surface_to_check_against(self):
        """Or every assertion below would pass over an empty set."""
        self.assertGreater(len(subcommands_under("command")), 1)

    def test_every_subcommand_is_named_as_something_a_person_can_type(self):
        for name in sorted(subcommands_under("command")):
            self.assertIn(
                f"{self.program} {name}",
                self.manual,
                f"{MANUAL.name} never names `{self.program} {name}`",
            )

    def version_flags(self) -> list[str]:
        return [
            option
            for action in cli._parser(cli.default_identity())._actions
            if action.dest == "version"
            for option in action.option_strings
        ]

    def test_the_version_flag_is_named_in_the_spelling_the_parser_accepts(self):
        """Both spellings come off the parser's own action, never retyped."""
        flags = self.version_flags()
        self.assertTrue(flags, "the parser no longer offers a version flag")
        for flag in flags:
            self.assertIn(f"`{self.program} {flag}`", self.manual)

    def test_the_manual_names_no_bare_flag_the_parser_would_reject(self):
        """The other direction, which the check above cannot see.

        Dropping a spelling from the parser leaves every remaining one still
        documented, so that check stays green while the manual points at a
        flag that no longer exists. This reads the bare-flag invocations out
        of the document and requires the parser to know each one -- so a
        spelling can be removed or renamed, but not silently left behind
        here.
        """
        named = set(re.findall(rf"`{re.escape(self.program)} (-{{1,2}}[a-zA-Z][\w-]*)`", self.manual))
        self.assertTrue(named, f"{MANUAL.name} names no bare flag at all, so this proves nothing")
        accepted = {
            option
            for action in cli._parser(cli.default_identity())._actions
            for option in action.option_strings
        }
        self.assertEqual(named - accepted, set())

    def test_the_version_flag_answers_with_this_binarys_own_version(self):
        """Run, not read: the manual's reason for naming it is that it answers
        without opening a home or reading a journal, which is exactly when a
        person needs it."""
        printed = io.StringIO()
        # argparse's version action writes straight to `sys.stdout` and exits,
        # never through the runtime's own stream, so this is captured here
        # rather than read off `runtime.out` -- and captured at all so the
        # suite's own output stays the suite's.
        with contextlib.redirect_stdout(printed), self.assertRaises(SystemExit) as raised:
            cli.main(["--version"], runtime=self.runtime())
        self.assertEqual(raised.exception.code, 0)
        self.assertIn(cli.default_identity().version, printed.getvalue())

    def test_the_menu_entry_that_leads_to_the_upgrade_is_quoted_as_drawn(self):
        """The TUI half, derived from the menu itself the same way
        `tests/test_manual_mcp_screens.py` derives the two it documents."""
        from pegasus.tui import navigator

        labels = [entry.label for entry in navigator.main_menu().entries]
        upgrade = [label for label in labels if label.lower() == "upgrade"]
        self.assertEqual(len(upgrade), 1, f"the main menu no longer offers one Upgrade entry: {labels}")
        self.assertIn(f"`{upgrade[0]}`", self.manual)


class ManualClaudeCodeNamesOnlyRealCommandsTest(unittest.TestCase):
    """Every `pegasus <word>`/`<word> <word>` this document names as
    something a person can type is a real subcommand, and every bare flag it
    quotes is one the parser actually accepts.

    `MANUAL-claude-code.md` does not claim the whole top-level surface the
    way `MANUAL.md` does (it is a sibling document for one CLI's own
    differences, not a second copy of the full command reference), so this
    does not reuse `ManualDocumentsEveryTopLevelCommandTest` -- that class
    proves completeness in one direction; this one proves the opposite
    direction, that nothing named here is a command the parser would refuse,
    the same defect class `test_the_manual_names_no_bare_flag_the_parser_
    would_reject` already guards against for `MANUAL.md` itself.
    """

    def setUp(self):
        self.manual = MANUAL_CLAUDE_CODE.read_text(encoding="utf-8")
        self.program = cli.default_identity().program_name
        self.parser = cli._parser(cli.default_identity())

    def test_the_document_exists_and_is_not_empty(self):
        self.assertTrue(self.manual.strip(), f"{MANUAL_CLAUDE_CODE.name} is empty")

    def test_every_top_level_word_named_after_the_program_is_a_real_subcommand(self):
        top_level = subcommands_under("command")
        self.assertGreater(len(top_level), 1)
        named = set(re.findall(rf"\b{re.escape(self.program)} ([a-z][a-z-]*)", self.manual))
        self.assertTrue(named, f"{MANUAL_CLAUDE_CODE.name} names no `{self.program} <word>` at all")
        self.assertEqual(named - top_level, set())

    def test_every_second_level_word_pair_is_a_real_subcommand(self):
        """`mcp grant`, `directory grant`, `models set`, ... -- one nested
        subparser per top-level group this document actually mentions."""
        nested_dests = {"mcp": "mcp_command", "directory": "directory_command", "models": "models_command"}
        checked_any = False
        for group, dest in nested_dests.items():
            for second in re.findall(rf"\b{re.escape(group)} ([a-z][a-z-]*)", self.manual):
                nested = subcommands_under(dest)
                self.assertIn(second, nested, f"`{group} {second}` is not a real `{self.program}` subcommand")
                checked_any = True
        self.assertTrue(checked_any, f"{MANUAL_CLAUDE_CODE.name} names no second-level subcommand at all")

    def test_the_manual_names_no_bare_flag_the_parser_would_reject(self):
        named = set(re.findall(rf"`{re.escape(self.program)} (-{{1,2}}[a-zA-Z][\w-]*)`", self.manual))
        accepted = {
            option
            for action in self.parser._actions
            for option in action.option_strings
        }

        def walk(parser: argparse.ArgumentParser) -> None:
            for action in parser._actions:
                accepted.update(action.option_strings)
                if isinstance(action, argparse._SubParsersAction):
                    for child in action.choices.values():
                        walk(child)

        walk(self.parser)
        self.assertEqual(named - accepted, set())

    def test_every_bare_flag_it_quotes_alongside_a_subcommand_is_accepted_somewhere(self):
        """`--start-mcp-servers`, `--dry-run`, `--mcp`, `--cli`, ... quoted on
        their own, not necessarily right after the program name (e.g. inside
        a longer invocation like `` `pegasus doctor --start-mcp-servers` ``)."""
        named = set(re.findall(r"`(-{1,2}[a-zA-Z][\w-]*)`", self.manual))
        accepted: set[str] = set()

        def walk(parser: argparse.ArgumentParser) -> None:
            for action in parser._actions:
                accepted.update(action.option_strings)
                if isinstance(action, argparse._SubParsersAction):
                    for child in action.choices.values():
                        walk(child)

        walk(self.parser)
        # Only demand this of a flag actually shaped like one of this
        # program's own options (a leading dash followed by a letter):
        # narrows out an unrelated backticked word that happens to start
        # with a dash in someone's own prose, which this regex cannot
        # otherwise tell apart from a real flag.
        self.assertTrue(named & accepted, "no recognizable flag found -- this test would prove nothing")
        self.assertEqual(named - accepted, set())


if __name__ == "__main__":  # pragma: no cover
    import unittest

    unittest.main()
