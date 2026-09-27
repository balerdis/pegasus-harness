"""The one place engine calls happen for the TUI: proving the screens they
produce describe exactly what `cli.install` did, on real disk.

`Navigator` and `view` are proven pure elsewhere, so everything here is about
`session.step` — the bridge that calls the same `cli.install` the flags call,
through the same `cli.safe_report` `main` uses, and hands the report back to
`Navigator` untouched.
"""
from __future__ import annotations

import io
import json
import os
import tempfile
import time
import unittest
import unittest.mock
from dataclasses import replace
from pathlib import Path

import pegasus
from pegasus import cli
from pegasus.adapters import available
from pegasus.core import codecs, content as content_module, pointer
from pegasus.core import journal as journal_module
from pegasus.core import model_assignments as model_assignments_module
from pegasus.core.registry import Registry
from pegasus.core.types import (
    Capability,
    CapabilityManifest,
    Codec,
    Detection,
    Environment,
    Layout,
    SupportTier,
)
from pegasus.infra.fs_posix import PosixFileSystem
from pegasus.infra.journal_store_file import journal_path
from pegasus.infra.snapshot_store_file import MANIFEST_FILENAME, snapshots_root
from pegasus.tui import navigator as navigator_module
from pegasus.tui import session
from pegasus.tui.navigator import (
    Action,
    CliOption,
    GrantMcpResultScreen,
    GrantMcpScreen,
    GrantMcpTarget,
    InstallPlanScreen,
    InstallResultScreen,
    McpSelectionScreen,
    Menu,
    ModelsScreen,
    ModelsTarget,
    Navigator,
    Placeholder,
    RestoreResultScreen,
    StatusRequest,
    StatusScreen,
    UninstallResultScreen,
)
from pegasus.tui.view import render
from platform_conditions import make_unwritable
from real_home import RealHomeTestCase
from test_cli_identity_sweep import ACME_IDENTITY, BrandAssertionMixin

AT = "2026-08-14T00:00:00+00:00"
# Pinned to OpenCode, not "whichever adapter is registered first": this
# suite exercises capabilities (mcp, per_agent_model, subagents declared
# inside the settings file, ...) that only OpenCode declares today. Since
# Claude Code registered, "available().ids()[0]" resolves alphabetically
# to "claudecode" instead, which cannot support what this file tests.
CLI = "opencode"
NO_BINARY = {"PATH": ""}
CONFIGURABLE_AGENT = "sdd-apply"


def _configurable_agent_names() -> frozenset[str]:
    return frozenset(agent.name for agent in content_module.load().agents if agent.model_configurable)


def _layout(home: Path):
    return available().get(CLI).layout(Environment(home=home))


def _present(home: Path) -> None:
    _layout(home).config_dir.mkdir(parents=True, exist_ok=True)


def _declare_own_mcp_server(home: Path, key: str) -> None:
    """What a user administering their own MCP server leaves behind in the
    CLI's own configuration -- a key under `/mcp` Pegasus never wrote. Same
    fixture `tests/test_cli_mcp.py` already uses for `cli.mcp_grant` itself,
    reproduced here since `GrantMcpScreen` sits on the same seam."""
    layout = _layout(home)
    document = codecs.loads(Codec.JSON, layout.settings_file.read_text(encoding="utf-8"))
    document = pointer.set_at(document, f"/mcp/{key}", {"type": "local", "command": ["probe-server"]})
    layout.settings_file.write_text(codecs.dumps(Codec.JSON, document), encoding="utf-8")


def _drop_mcp_bindings(runtime: cli.Runtime) -> None:
    """An install predating `mcp_bindings` (or one that otherwise lost it)
    has a bound convention with no recorded key -- the same fixture
    `tests/test_cli_update.py` and `tests/test_cli_mcp.py` already use to
    reproduce an unresolved binding."""
    store = cli.journal_store(runtime)
    journal = store.load()
    install = journal_module.install_for(journal, CLI)
    store.save(journal_module.with_install(journal, replace(install, mcp_bindings={})))


def _undeclare_own_mcp_server(home: Path, key: str) -> None:
    """The other half of `_declare_own_mcp_server`: removes a key from the
    CLI's own `/mcp` configuration -- reproduces the race a person can win
    against themselves between opening `GrantMcpScreen` and confirming it,
    by editing that same file out from under the screen."""
    layout = _layout(home)
    document = codecs.loads(Codec.JSON, layout.settings_file.read_text(encoding="utf-8"))
    document = pointer.unset_at(document, f"/mcp/{key}")
    layout.settings_file.write_text(codecs.dumps(Codec.JSON, document), encoding="utf-8")


def _sans(value, needle: str):
    """`value`, with every mention of `needle` (one throwaway home's own
    absolute path) replaced by a placeholder, so a report or a file produced
    against one throwaway home compares equal to the same run against a
    different one."""
    if isinstance(value, str):
        return value.replace(needle, "<home>")
    if isinstance(value, list):
        return [_sans(item, needle) for item in value]
    if isinstance(value, dict):
        return {key: _sans(item, needle) for key, item in value.items()}
    return value


def _tree(home: Path, *, skip: frozenset[str] = frozenset()) -> dict[str, bytes]:
    """Every file under `home`, keyed by its path relative to it, with the
    home's own path scrubbed out of the bytes the same way `_sans` scrubs it
    out of a report."""
    return {
        str(path.relative_to(home)): _sans(path.read_bytes().decode("utf-8", "surrogateescape"), str(home)).encode(
            "utf-8", "surrogateescape"
        )
        for path in home.rglob("*")
        if path.is_file() and str(path.relative_to(home)) not in skip
    }


def _journal_shape(home: Path) -> dict:
    """The journal, home path scrubbed and every digest dropped.

    A digest hashes bytes that themselves quote the installing home's own
    absolute path — a rendered prompt names where its own skills live — so
    two different throwaway homes never produce the same digest for
    otherwise identical content. What the journal claims about *which*
    artifact exists and where is exactly what installing the same thing
    twice, on two different homes, should agree on; whether its bytes happen
    to hash the same is not, and comparing it as raw bytes elsewhere would
    fail the way `test_a_tui_install_matches...` did before this existed.
    """
    document = json.loads(journal_path(PosixFileSystem(product_id="pegasus-harness"), home).read_text())
    return _drop_digests(_sans(document, str(home)))


def _drop_digests(value):
    if isinstance(value, dict):
        return {key: _drop_digests(item) for key, item in value.items() if key != "after_digest"}
    if isinstance(value, list):
        return [_drop_digests(item) for item in value]
    return value


class SessionTestCase(RealHomeTestCase):
    def in_timezone(self, name: str) -> None:
        """Pin the zone these labels are read in, for the length of one test.

        A manifest records UTC; a person reads a wall clock. Any assertion
        about the hour on screen is therefore an assertion about a
        conversion, and left to the machine's own zone it would pass in
        Buenos Aires and fail in Berlin. `time.tzset` is what makes
        `datetime.astimezone` see the change.
        """
        previous = os.environ.get("TZ")
        os.environ["TZ"] = name
        time.tzset()

        def restore() -> None:
            if previous is None:
                del os.environ["TZ"]
            else:
                os.environ["TZ"] = previous
            time.tzset()

        self.addCleanup(restore)

    def runtime(self, home: Path | None = None, *, identity=None) -> cli.Runtime:
        kwargs = {} if identity is None else {"identity": identity}
        return cli.Runtime(
            filesystem=PosixFileSystem(product_id="pegasus-harness"), home=home or self.home, now=AT, out=io.StringIO(), variables=NO_BINARY,
            **kwargs,
        )

    def to_continue(self, navigator: Navigator) -> Navigator:
        """Move the cursor from wherever it sits on an `McpSelectionScreen`
        onto Continue, touching no checkbox along the way."""
        for _ in range(len(navigator.current.options) - navigator.cursor):
            navigator = navigator.handle(Action.MOVE_DOWN)
        return navigator


class DetectClisTest(SessionTestCase):
    def test_a_present_cli_is_offered(self):
        _present(self.home)
        options = session.detect_clis(self.runtime())
        self.assertEqual([option.id for option in options], [CLI])

    def test_an_absent_cli_is_not_offered(self):
        self.assertEqual(session.detect_clis(self.runtime()), ())


class PlanStepTest(SessionTestCase):
    def test_choosing_a_detected_cli_opens_the_mcp_selection_first(self):
        _present(self.home)
        runtime = self.runtime()
        navigator = Navigator.starting(session.detect_clis(runtime)).handle(Action.CHOOSE)
        navigator = session.step(navigator, runtime, Action.CHOOSE)
        self.assertIsInstance(navigator.current, McpSelectionScreen)
        self.assertEqual(navigator.current.chosen, ())
        self.assertEqual([path for path in _layout(self.home).config_dir.rglob("*") if path.is_file()], [])

    def test_continuing_past_the_selection_fetches_a_preview_and_writes_nothing(self):
        _present(self.home)
        runtime = self.runtime()
        navigator = Navigator.starting(session.detect_clis(runtime)).handle(Action.CHOOSE)
        navigator = session.step(navigator, runtime, Action.CHOOSE)  # opens the mcp selection
        navigator = self.to_continue(navigator)
        navigator = session.step(navigator, runtime, Action.CHOOSE)  # fetches the plan
        self.assertIsInstance(navigator.current, InstallPlanScreen)
        self.assertEqual(navigator.current.report["status"], "planned")
        self.assertEqual([path for path in _layout(self.home).config_dir.rglob("*") if path.is_file()], [])


class McpSelectionDefaultsTest(SessionTestCase):
    """What opens pre-checked, and what a person sees to decide with."""

    def test_every_shipped_server_is_offered_with_its_own_description(self):
        _present(self.home)
        runtime = self.runtime()
        navigator = Navigator.starting(session.detect_clis(runtime)).handle(Action.CHOOSE)
        navigator = session.step(navigator, runtime, Action.CHOOSE)
        offered = {option.id: option.description for option in navigator.current.options}
        expected = {server.name: server.description for server in content_module.load().mcp}
        self.assertEqual(offered, expected)
        self.assertTrue(all(description for description in offered.values()))

    def test_a_previously_installed_server_opens_pre_checked(self):
        _present(self.home)
        runtime = self.runtime()
        cli.install(CLI, runtime, mcp=["context7"])

        navigator = Navigator.starting(session.detect_clis(runtime)).handle(Action.CHOOSE)
        navigator = session.step(navigator, runtime, Action.CHOOSE)
        self.assertIsInstance(navigator.current, McpSelectionScreen)
        self.assertEqual(navigator.current.chosen, ("context7",))

    def test_the_default_cursor_sits_on_the_first_server_not_continue(self):
        """Unlike a destructive confirmation, where the safe entry is
        Cancel, nothing here is destroyed by pressing enter on the first
        row -- it only toggles a checkbox that already opened checked or
        unchecked to match the machine's own state. The unsafe move would be
        a cursor that starts on Continue, one keystroke away from silently
        retiring whatever the journal already lists; starting on the first
        server instead makes that impossible by construction."""
        _present(self.home)
        runtime = self.runtime()
        cli.install(CLI, runtime, mcp=["context7"])
        navigator = Navigator.starting(session.detect_clis(runtime)).handle(Action.CHOOSE)
        navigator = session.step(navigator, runtime, Action.CHOOSE)
        self.assertEqual(navigator.cursor, 0)
        self.assertLess(navigator.cursor, len(navigator.current.options))

    def test_leaving_a_previously_installed_server_checked_keeps_it_after_reinstalling(self):
        _present(self.home)
        runtime = self.runtime()
        cli.install(CLI, runtime, mcp=["context7"])

        navigator = Navigator.starting(session.detect_clis(runtime)).handle(Action.CHOOSE)
        navigator = session.step(navigator, runtime, Action.CHOOSE)  # opens the mcp selection, context7 pre-checked
        navigator = self.to_continue(navigator)  # touches nothing
        navigator = session.step(navigator, runtime, Action.CHOOSE)  # fetches the plan
        self.assertEqual(navigator.current.report["retired"], [])
        navigator = session.step(navigator, runtime, Action.CHOOSE)  # confirms it

        self.assertEqual(navigator.current.report["status"], "installed")
        self.assertEqual(session.detect_installed(runtime)[0].id, CLI)
        self.assertEqual(session._recorded_mcp(CLI, runtime), {"context7": None})

    def test_unchecking_a_previously_installed_server_retires_it_on_confirm(self):
        _present(self.home)
        runtime = self.runtime()
        cli.install(CLI, runtime, mcp=["context7"])

        navigator = Navigator.starting(session.detect_clis(runtime)).handle(Action.CHOOSE)
        navigator = session.step(navigator, runtime, Action.CHOOSE)  # opens the mcp selection, context7 pre-checked
        index = next(i for i, option in enumerate(navigator.current.options) if option.id == "context7")
        for _ in range(index):
            navigator = navigator.handle(Action.MOVE_DOWN)
        navigator = navigator.handle(Action.CHOOSE)  # unchecks context7
        self.assertEqual(navigator.current.chosen, ())
        navigator = self.to_continue(navigator)
        navigator = session.step(navigator, runtime, Action.CHOOSE)  # fetches the plan
        self.assertEqual(
            {item["id"] for item in navigator.current.report["retired"]},
            {"mcp:context7", "mcp-convention:context7"},
        )
        navigator = session.step(navigator, runtime, Action.CHOOSE)  # confirms it

        self.assertEqual(navigator.current.report["status"], "installed")
        self.assertEqual(session._recorded_mcp(CLI, runtime), {})


class BoundServerSurvivesTheSelectionScreenTest(SessionTestCase):
    """A bound server is part of the installation exactly as much as one
    Pegasus administers itself, so opening the selection screen and moving
    straight to Continue has to reproduce both of them.

    What is asserted here is the resulting *plan*, never a checkbox: a row
    rendered checked is a proxy for the selection Continue re-emits, and the
    two are only the same thing when the row also carries the key its
    binding resolves under. A plan that retires nothing, and rewrites no
    agent body, is the fact -- the very facts that were false against a real
    installation, where continuing untouched proposed 33 updates (every
    agent stripped of two servers' instructions) instead of 3.
    """

    #: One server Pegasus obtains and administers (`context7`) and one it
    #: only ships the contract for, against a key this installation already
    #: runs it under (`cbm`) -- the two spellings `parse_mcp_choice` reads.
    SELECTION = ["cbm=codebase-memory-mcp", "context7"]

    def installed_runtime(self) -> cli.Runtime:
        _present(self.home)
        runtime = self.runtime()
        cli.install(CLI, runtime, mcp=list(self.SELECTION))
        return runtime

    def to_selection(self, runtime: cli.Runtime) -> Navigator:
        navigator = Navigator.starting(session.detect_clis(runtime)).handle(Action.CHOOSE)
        navigator = session.step(navigator, runtime, Action.CHOOSE)  # opens the mcp selection
        self.assertIsInstance(navigator.current, McpSelectionScreen)
        return navigator

    def plan_untouched(self, runtime: cli.Runtime) -> dict:
        navigator = self.to_continue(self.to_selection(runtime))  # touches no checkbox
        navigator = session.step(navigator, runtime, Action.CHOOSE)  # fetches the plan
        self.assertIsInstance(navigator.current, InstallPlanScreen)
        return navigator.current.report

    def test_continuing_untouched_retires_nothing(self):
        self.assertEqual(self.plan_untouched(self.installed_runtime())["retired"], [])

    def test_continuing_untouched_rewrites_no_agent_body(self):
        self.assertEqual([item["id"] for item in self.plan_untouched(self.installed_runtime())["updated"]], [])

    def plan_from_the_flags(self) -> dict:
        """The same preview asked for through the flags instead, naming both
        bindings the way a person would -- the invocation the TUI's own
        Continue is supposed to be equivalent to."""
        runtime = self.runtime()
        flags = [flag for spelling in self.SELECTION for flag in ("--mcp", spelling)]
        code = cli.main(["install", "--cli", CLI, "--dry-run", *flags, "--json"], runtime=runtime)
        self.assertEqual(code, 0)
        return json.loads(runtime.out.getvalue())

    def test_the_plan_agrees_with_the_equivalent_cli_invocation(self):
        """The CLI already gets this right, so the two surfaces previewing
        the same installation must produce the same document -- not merely
        one that also happens to retire nothing."""
        self.assertEqual(self.plan_untouched(self.installed_runtime()), self.plan_from_the_flags())

    def test_a_binding_whose_key_was_never_recorded_shows_the_specific_blocker(self):
        """The one installation whose selection cannot be reconstructed at
        all. A checklist here could only draw the bound row wrong -- retired
        if left unchecked, silently converted into a server Pegasus obtains
        if checked and re-emitted bare -- so this shows the same refusal
        `update`, `mcp grant` and `mcp revoke` already give, naming the
        one-time command that clears it."""
        runtime = self.installed_runtime()
        _drop_mcp_bindings(runtime)
        navigator = Navigator.starting(session.detect_clis(runtime)).handle(Action.CHOOSE)
        navigator = session.step(navigator, runtime, Action.CHOOSE)
        self.assertIsInstance(navigator.current, Placeholder)
        self.assertEqual(
            navigator.current.note,
            cli.unresolved_bindings_message(CLI, ["cbm"], program_name=runtime.identity.program_name),
        )

    def test_a_bound_row_carries_the_key_continue_re_emits(self):
        screen = self.to_selection(self.installed_runtime()).current
        self.assertEqual({option.id: option.bound_to for option in screen.options}["cbm"], "codebase-memory-mcp")
        self.assertIsNone({option.id: option.bound_to for option in screen.options}["context7"])
        self.assertEqual(set(screen.chosen), {"cbm", "context7"})


class GrantMcpThroughTheTuiTest(SessionTestCase):
    """`GrantMcpScreen`, opened and confirmed the way a person on the TUI
    would: the same `cli.mcp_grant`/`cli.mcp_revoke` seam
    `tests/test_cli_mcp.py` proves against the flags directly, reached here
    through `session.step` instead."""

    def to_screen(self, runtime) -> Navigator:
        navigator = Navigator.starting(installed=session.detect_installed(runtime))
        index = [entry.label for entry in navigator.current.entries].index("Grant MCP servers")
        for _ in range(index):
            navigator = navigator.handle(Action.MOVE_DOWN)
        navigator = session.step(navigator, runtime, Action.CHOOSE)  # opens the CLI choice
        return session.step(navigator, runtime, Action.CHOOSE)  # opens the grant screen (or a placeholder)

    def toggle(self, navigator: Navigator, key: str) -> Navigator:
        index = next(i for i, option in enumerate(navigator.current.options) if option.id == key)
        count = len(navigator.current.options) + 1  # + Continue, matching `Navigator`'s own wraparound.
        for _ in range((index - navigator.cursor) % count):
            navigator = navigator.handle(Action.MOVE_DOWN)
        return navigator.handle(Action.CHOOSE)

    def test_a_cli_with_nothing_declared_shows_a_placeholder_that_explains_the_flow(self):
        _present(self.home)
        runtime = self.runtime()
        cli.install(CLI, runtime)
        navigator = self.to_screen(runtime)
        self.assertIsInstance(navigator.current, Placeholder)
        self.assertIn("install", navigator.current.note.lower())
        self.assertIn("grant", navigator.current.note.lower())

    def test_a_cli_where_everything_declared_is_already_covered_says_so_plainly(self):
        """Distinct from the "nothing declared" case above: a server WAS
        found here, and telling a person to install one they already
        installed and already reached per-agent is advice that does not
        apply to what actually happened."""
        _present(self.home)
        runtime = self.runtime()
        cli.install(CLI, runtime, mcp=["context7"])
        _declare_own_mcp_server(self.home, "context7")
        navigator = self.to_screen(runtime)
        self.assertIsInstance(navigator.current, Placeholder)
        note = navigator.current.note.lower()
        self.assertIn("context7", note)
        self.assertNotIn("no mcp server of your own was found", note)

    def test_a_cli_with_an_unresolved_binding_shows_the_specific_blocker(self):
        """A checklist nobody could actually confirm -- `mcp_grant`/
        `mcp_revoke` refuse every key outright while a binding is unresolved
        -- must never be offered; nor may this fall back to the generic
        empty-case note, which would say nothing about why."""
        _present(self.home)
        runtime = self.runtime()
        code = cli.main(["install", "--cli", CLI, "--mcp", "cbm=codebase-memory-mcp", "--json"], runtime=runtime)
        self.assertEqual(code, 0)
        _drop_mcp_bindings(runtime)
        _declare_own_mcp_server(self.home, "jira")
        navigator = self.to_screen(runtime)
        self.assertIsInstance(navigator.current, Placeholder)
        self.assertIn("cbm", navigator.current.note)
        self.assertEqual(
            navigator.current.note,
            cli.unresolved_bindings_message(CLI, ["cbm"], program_name=runtime.identity.program_name),
        )

    def test_a_shipped_server_is_never_offered_on_this_screen(self):
        """A server Pegasus itself installed is declared in the CLI's own
        configuration too, but it means something different here -- see
        `GrantMcpScreen`'s own docstring -- so it must never appear as a row."""
        _present(self.home)
        runtime = self.runtime()
        cli.install(CLI, runtime, mcp=["context7"])
        _declare_own_mcp_server(self.home, "jira")
        navigator = self.to_screen(runtime)
        self.assertIsInstance(navigator.current, GrantMcpScreen)
        self.assertEqual([option.id for option in navigator.current.options], ["jira"])

    def test_a_declared_server_opens_unchecked_by_default(self):
        _present(self.home)
        runtime = self.runtime()
        cli.install(CLI, runtime)
        _declare_own_mcp_server(self.home, "jira")
        navigator = self.to_screen(runtime)
        self.assertIsInstance(navigator.current, GrantMcpScreen)
        self.assertEqual(navigator.current.chosen, ())
        self.assertEqual(navigator.current.granted, ())

    def test_an_already_granted_server_opens_checked(self):
        _present(self.home)
        runtime = self.runtime()
        cli.install(CLI, runtime)
        _declare_own_mcp_server(self.home, "jira")
        cli.mcp_grant(CLI, ["jira"], runtime)
        navigator = self.to_screen(runtime)
        self.assertEqual(navigator.current.chosen, ("jira",))
        self.assertEqual(navigator.current.granted, ("jira",))

    def test_confirming_with_no_change_calls_neither_grant_nor_revoke(self):
        _present(self.home)
        runtime = self.runtime()
        cli.install(CLI, runtime)
        _declare_own_mcp_server(self.home, "jira")
        navigator = self.to_screen(runtime)  # jira unchecked, matching the journal
        navigator = self.to_continue(navigator)
        navigator = session.step(navigator, runtime, Action.CHOOSE)
        self.assertIsInstance(navigator.current, GrantMcpResultScreen)
        self.assertEqual(navigator.current.granted, ())
        self.assertEqual(navigator.current.revoked, ())
        self.assertEqual(session._recorded_mcp(CLI, runtime), {})
        self.assertEqual(
            journal_module.install_for(cli.journal_store(runtime).load(), CLI).granted_mcp, ()
        )

    def test_confirming_grants_a_newly_checked_server(self):
        _present(self.home)
        runtime = self.runtime()
        cli.install(CLI, runtime)
        _declare_own_mcp_server(self.home, "jira")
        navigator = self.to_screen(runtime)
        navigator = self.toggle(navigator, "jira")
        navigator = self.to_continue(navigator)
        navigator = session.step(navigator, runtime, Action.CHOOSE)
        self.assertIsInstance(navigator.current, GrantMcpResultScreen)
        self.assertEqual(navigator.current.granted, ("jira",))
        self.assertEqual(navigator.current.revoked, ())
        installed = journal_module.install_for(cli.journal_store(runtime).load(), CLI)
        self.assertIn("jira", installed.granted_mcp)

    def test_confirming_revokes_a_newly_unchecked_server(self):
        _present(self.home)
        runtime = self.runtime()
        cli.install(CLI, runtime)
        _declare_own_mcp_server(self.home, "jira")
        cli.mcp_grant(CLI, ["jira"], runtime)
        navigator = self.to_screen(runtime)  # jira opens checked
        navigator = self.toggle(navigator, "jira")  # unchecks it
        navigator = self.to_continue(navigator)
        navigator = session.step(navigator, runtime, Action.CHOOSE)
        self.assertEqual(navigator.current.granted, ())
        self.assertEqual(navigator.current.revoked, ("jira",))
        installed = journal_module.install_for(cli.journal_store(runtime).load(), CLI)
        self.assertNotIn("jira", installed.granted_mcp)

    def test_confirming_can_grant_one_and_revoke_another_in_the_same_confirm(self):
        _present(self.home)
        runtime = self.runtime()
        cli.install(CLI, runtime)
        _declare_own_mcp_server(self.home, "jira")
        _declare_own_mcp_server(self.home, "figma")
        cli.mcp_grant(CLI, ["figma"], runtime)
        navigator = self.to_screen(runtime)  # figma checked, jira unchecked
        navigator = self.toggle(navigator, "jira")  # checks jira
        navigator = self.toggle(navigator, "figma")  # unchecks figma
        navigator = self.to_continue(navigator)
        navigator = session.step(navigator, runtime, Action.CHOOSE)
        self.assertEqual(navigator.current.granted, ("jira",))
        self.assertEqual(navigator.current.revoked, ("figma",))
        installed = journal_module.install_for(cli.journal_store(runtime).load(), CLI)
        self.assertEqual(set(installed.granted_mcp), {"jira"})

    def test_a_key_that_raced_out_from_under_the_screen_fails_the_whole_grant(self):
        """The exact race `GrantMcpResultScreen`'s own docstring anticipates:
        `figma` is checked on screen, but removed from the CLI's own
        configuration before Continue is confirmed. `jira` and `figma` are
        requested in the same batched `cli.mcp_grant` call now (see
        `_grant_mcp_write`), and `mcp_grant`'s own all-or-nothing contract
        means one bad key in that batch refuses the whole call -- so `jira`
        is not granted either, even though nothing raced out from under it.
        The on-disk `granted_mcp` is the proof, not an inference from the
        screen's own claim."""
        _present(self.home)
        runtime = self.runtime()
        cli.install(CLI, runtime)
        _declare_own_mcp_server(self.home, "jira")
        _declare_own_mcp_server(self.home, "figma")
        navigator = self.to_screen(runtime)
        navigator = self.toggle(navigator, "jira")
        navigator = self.toggle(navigator, "figma")
        navigator = self.to_continue(navigator)
        _undeclare_own_mcp_server(self.home, "figma")  # the race: gone by the time Continue runs.
        navigator = session.step(navigator, runtime, Action.CHOOSE)
        self.assertIsInstance(navigator.current, GrantMcpResultScreen)
        self.assertEqual(navigator.current.granted, ())
        self.assertTrue(navigator.current.errors)
        self.assertTrue(any("figma" in error for error in navigator.current.errors))
        installed = journal_module.install_for(cli.journal_store(runtime).load(), CLI)
        self.assertEqual(set(installed.granted_mcp), set())
        # The claim on screen and the disk it claims to describe must agree.
        self.assertEqual(set(navigator.current.granted), set(installed.granted_mcp))

    def test_a_total_failure_reports_nothing_as_granted(self):
        """Every requested key fails its own call: `granted` must be empty,
        not the requested set."""
        _present(self.home)
        runtime = self.runtime()
        cli.install(CLI, runtime)
        _declare_own_mcp_server(self.home, "jira")
        navigator = self.to_screen(runtime)
        navigator = self.toggle(navigator, "jira")
        navigator = self.to_continue(navigator)
        _undeclare_own_mcp_server(self.home, "jira")  # the only requested key races away.
        navigator = session.step(navigator, runtime, Action.CHOOSE)
        self.assertEqual(navigator.current.granted, ())
        self.assertTrue(navigator.current.errors)
        installed = journal_module.install_for(cli.journal_store(runtime).load(), CLI)
        self.assertEqual(installed.granted_mcp, ())

    def test_a_revoke_that_races_out_from_under_the_screen_is_not_reported_as_revoked(self):
        """The revoke half of the same race: `jira` is unchecked on screen,
        but its grant is removed from the journal (by another process, or
        another session) before Continue confirms -- `cli.mcp_revoke` itself
        treats revoking an already-revoked key as success (`already-revoked`,
        not a failure), so this proves that success still lands in
        `revoked`, and is never contradicted by an error line, when nothing
        actually needed to change."""
        _present(self.home)
        runtime = self.runtime()
        cli.install(CLI, runtime)
        _declare_own_mcp_server(self.home, "jira")
        cli.mcp_grant(CLI, ["jira"], runtime)
        navigator = self.to_screen(runtime)
        navigator = self.toggle(navigator, "jira")  # unchecks it
        navigator = self.to_continue(navigator)
        cli.mcp_revoke(CLI, ["jira"], runtime)  # already revoked by the time Continue runs.
        navigator = session.step(navigator, runtime, Action.CHOOSE)
        self.assertEqual(navigator.current.revoked, ("jira",))
        self.assertEqual(navigator.current.errors, ())
        installed = journal_module.install_for(cli.journal_store(runtime).load(), CLI)
        self.assertEqual(installed.granted_mcp, ())

    def test_the_happy_path_still_reports_everything_requested(self):
        """No race, nothing refused: the fix must not turn a clean confirm
        into a partial-looking one."""
        _present(self.home)
        runtime = self.runtime()
        cli.install(CLI, runtime)
        _declare_own_mcp_server(self.home, "jira")
        _declare_own_mcp_server(self.home, "figma")
        cli.mcp_grant(CLI, ["figma"], runtime)
        navigator = self.to_screen(runtime)
        navigator = self.toggle(navigator, "jira")
        navigator = self.toggle(navigator, "figma")
        navigator = self.to_continue(navigator)
        navigator = session.step(navigator, runtime, Action.CHOOSE)
        self.assertEqual(navigator.current.granted, ("jira",))
        self.assertEqual(navigator.current.revoked, ("figma",))
        self.assertEqual(navigator.current.errors, ())
        installed = journal_module.install_for(cli.journal_store(runtime).load(), CLI)
        self.assertEqual(set(installed.granted_mcp), {"jira"})

    def test_the_result_reuses_the_same_activation_wording_update_shows(self):
        _present(self.home)
        runtime = self.runtime()
        cli.install(CLI, runtime)
        _declare_own_mcp_server(self.home, "jira")
        navigator = self.to_screen(runtime)
        navigator = self.toggle(navigator, "jira")
        navigator = self.to_continue(navigator)
        navigator = session.step(navigator, runtime, Action.CHOOSE)
        self.assertEqual(navigator.current.activation, tuple(available().get(CLI).activation_steps()))
        self.assertTrue(navigator.current.activation)

    def test_going_back_from_the_screen_touches_nothing_on_disk(self):
        _present(self.home)
        runtime = self.runtime()
        cli.install(CLI, runtime)
        _declare_own_mcp_server(self.home, "jira")
        before = _tree(self.home)
        navigator = self.to_screen(runtime)
        navigator = self.toggle(navigator, "jira")
        navigator = navigator.handle(Action.BACK)
        self.assertIsInstance(navigator.current, Menu)
        self.assertEqual(_tree(self.home), before)


class ParityWithCliInstallTest(SessionTestCase):
    def test_a_tui_install_matches_the_equivalent_cli_install_on_a_separate_home(self):
        with tempfile.TemporaryDirectory(dir=self.home.parent) as other:
            other_home = Path(other)
            for home in (self.home, other_home):
                _present(home)

            cli_runtime = self.runtime(self.home)
            cli_code = cli.main(["install", "--cli", CLI, "--json"], runtime=cli_runtime)
            cli_report = json.loads(cli_runtime.out.getvalue())

            tui_runtime = self.runtime(other_home)
            navigator = Navigator.starting(session.detect_clis(tui_runtime)).handle(Action.CHOOSE)
            navigator = session.step(navigator, tui_runtime, Action.CHOOSE)  # opens the mcp selection
            navigator = self.to_continue(navigator)  # nothing checked, matching no `--mcp` at all
            navigator = session.step(navigator, tui_runtime, Action.CHOOSE)  # fetches the plan
            navigator = session.step(navigator, tui_runtime, Action.CHOOSE)  # confirms it

            self.assertEqual(cli_code, 0)
            self.assertIsInstance(navigator.current, InstallResultScreen)
            self.assertEqual(navigator.current.report["status"], "installed")
            self.assertEqual(
                _sans(cli_report, str(self.home)), _sans(navigator.current.report, str(other_home))
            )
            journal_relative = str(journal_path(PosixFileSystem(product_id="pegasus-harness"), self.home).relative_to(self.home))
            self.assertEqual(
                _tree(self.home, skip=frozenset({journal_relative})),
                _tree(other_home, skip=frozenset({journal_relative})),
            )
            self.assertEqual(_journal_shape(self.home), _journal_shape(other_home))


class ParityWithCliInstallMcpTest(SessionTestCase):
    """The same proof as `ParityWithCliInstallTest`, but with a server
    actually checked: what a person ticks on this screen must land on disk
    exactly as `--mcp context7` would place it, journal included."""

    def test_choosing_a_server_on_screen_matches_the_equivalent_mcp_flag(self):
        with tempfile.TemporaryDirectory(dir=self.home.parent) as other:
            other_home = Path(other)
            for home in (self.home, other_home):
                _present(home)

            cli_runtime = self.runtime(self.home)
            cli_code = cli.main(["install", "--cli", CLI, "--mcp", "context7", "--json"], runtime=cli_runtime)
            cli_report = json.loads(cli_runtime.out.getvalue())

            tui_runtime = self.runtime(other_home)
            navigator = Navigator.starting(session.detect_clis(tui_runtime)).handle(Action.CHOOSE)
            navigator = session.step(navigator, tui_runtime, Action.CHOOSE)  # opens the mcp selection
            index = next(i for i, option in enumerate(navigator.current.options) if option.id == "context7")
            for _ in range(index):
                navigator = navigator.handle(Action.MOVE_DOWN)
            navigator = navigator.handle(Action.CHOOSE)  # checks context7
            self.assertEqual(navigator.current.chosen, ("context7",))
            navigator = self.to_continue(navigator)
            navigator = session.step(navigator, tui_runtime, Action.CHOOSE)  # fetches the plan
            self.assertEqual(navigator.current.report["status"], "planned")
            navigator = session.step(navigator, tui_runtime, Action.CHOOSE)  # confirms it

            self.assertEqual(cli_code, 0)
            self.assertIsInstance(navigator.current, InstallResultScreen)
            self.assertEqual(navigator.current.report["status"], "installed")
            self.assertEqual(
                _sans(cli_report, str(self.home)), _sans(navigator.current.report, str(other_home))
            )
            journal_relative = str(journal_path(PosixFileSystem(product_id="pegasus-harness"), self.home).relative_to(self.home))
            self.assertEqual(
                _tree(self.home, skip=frozenset({journal_relative})),
                _tree(other_home, skip=frozenset({journal_relative})),
            )
            self.assertEqual(_journal_shape(self.home), _journal_shape(other_home))


class InstallTaskTest(SessionTestCase):
    """`session.install_task` is the seam `app.py` runs on a worker thread:
    a plain callable that performs the real install, reports every tick
    through the sink it is handed, and returns the same `Navigator` update
    `session.step`'s own `InstallPlanScreen` branch produces -- without
    `session` itself ever importing `threading` or `time`.
    """

    def test_it_reports_progress_through_the_given_sink(self):
        _present(self.home)
        runtime = self.runtime()
        navigator = Navigator.starting(session.detect_clis(runtime)).handle(Action.CHOOSE)
        navigator = session.step(navigator, runtime, Action.CHOOSE)  # opens the mcp selection
        navigator = self.to_continue(navigator)
        navigator = session.step(navigator, runtime, Action.CHOOSE)  # fetches the plan
        plan_screen = navigator.current

        run = session.install_task(navigator, runtime, plan_screen)
        events = []
        result = run(events.append)

        self.assertTrue(events, "no Progress event reached the sink")
        self.assertEqual(events[-1].done, events[-1].total)
        self.assertIsInstance(result, Navigator)
        self.assertIsInstance(result.current, InstallResultScreen)
        self.assertEqual(result.current.report["status"], "installed")

    def test_it_matches_session_steps_own_synchronous_result(self):
        with tempfile.TemporaryDirectory(dir=self.home.parent) as other:
            other_home = Path(other)
            for home in (self.home, other_home):
                _present(home)

            sync_runtime = self.runtime(self.home)
            navigator = Navigator.starting(session.detect_clis(sync_runtime)).handle(Action.CHOOSE)
            navigator = session.step(navigator, sync_runtime, Action.CHOOSE)
            navigator = self.to_continue(navigator)
            navigator = session.step(navigator, sync_runtime, Action.CHOOSE)
            sync_result = session.step(navigator, sync_runtime, Action.CHOOSE)

            task_runtime = self.runtime(other_home)
            navigator = Navigator.starting(session.detect_clis(task_runtime)).handle(Action.CHOOSE)
            navigator = session.step(navigator, task_runtime, Action.CHOOSE)
            navigator = self.to_continue(navigator)
            navigator = session.step(navigator, task_runtime, Action.CHOOSE)
            task_result = session.install_task(navigator, task_runtime, navigator.current)(lambda progress: None)

            self.assertEqual(
                _sans(sync_result.current.report, str(self.home)),
                _sans(task_result.current.report, str(other_home)),
            )


class InstallFailureThroughTheTuiTest(SessionTestCase):
    def test_a_real_failure_reaches_the_result_screen_as_a_report_not_a_traceback(self):
        _present(self.home)
        runtime = self.runtime()
        navigator = Navigator.starting(session.detect_clis(runtime)).handle(Action.CHOOSE)
        navigator = session.step(navigator, runtime, Action.CHOOSE)  # opens the mcp selection
        navigator = self.to_continue(navigator)
        navigator = session.step(navigator, runtime, Action.CHOOSE)  # fetches the plan
        self.assertIsInstance(navigator.current, InstallPlanScreen)

        # A real failure: the directory holding the journal refuses the write
        # that would record what this run is about to place -- the same
        # condition test_cli.py drives `_unrecordable` with, produced here
        # rather than mocked.
        snapshots_root(runtime.filesystem, self.home).mkdir(parents=True, exist_ok=True)
        data_dir = journal_path(runtime.filesystem, self.home).parent
        self.addCleanup(make_unwritable(data_dir))

        navigator = session.step(navigator, runtime, Action.CHOOSE)

        self.assertIsInstance(navigator.current, InstallResultScreen)
        report = navigator.current.report
        self.assertEqual(report["status"], "failed")
        self.assertTrue(report["rolled_back"])
        prose = cli.prose_for(report)
        self.assertNotIn("Traceback", prose)
        self.assertIn("taken back out", prose)


class DetectInstalledTest(SessionTestCase):
    def test_nothing_installed_is_offered_nothing(self):
        self.assertEqual(session.detect_installed(self.runtime()), ())

    def test_an_installed_cli_is_offered_even_once_no_longer_detected(self):
        _present(self.home)
        runtime = self.runtime()
        cli.install(CLI, runtime)
        self.assertEqual([option.id for option in session.detect_installed(runtime)], [CLI])


class LocalUpdateNoticeTest(SessionTestCase):
    """`session.local_update_notice`: the local half of `UpdateNotice`, read
    straight off the journal -- no network, always available."""

    def test_nothing_installed_says_nothing(self):
        notice = session.local_update_notice(self.runtime(), installed=())
        self.assertEqual(notice.local_behind, ())
        self.assertEqual(notice.running, pegasus.__version__)

    def test_a_distributions_notice_reports_its_own_running_version(self):
        """Regression: `UpdateNotice.running` used to be `pegasus.__version__`
        unconditionally, so a distribution's own notice compared its own
        recorded install version (now the product's own, per the fix this
        accompanies) against the pinned engine's version instead of its own
        -- the same class of always-mismatched comparison `cli.upgrade` had."""
        self.assertNotEqual(ACME_IDENTITY.version, pegasus.__version__)
        notice = session.local_update_notice(self.runtime(identity=ACME_IDENTITY), installed=())
        self.assertEqual(notice.running, ACME_IDENTITY.version)

    def test_an_install_made_with_an_older_release_is_named(self):
        _present(self.home)
        runtime = self.runtime()
        cli.install(CLI, runtime)
        store = cli.journal_store(runtime)
        journal = store.load()
        install = journal_module.install_for(journal, CLI)
        older_release = {**install.release, "version": "0.0.1"}
        store.save(journal_module.with_install(journal, replace(install, release=older_release)))

        notice = session.local_update_notice(runtime, installed=session.detect_installed(runtime))
        self.assertEqual(len(notice.local_behind), 1)
        behind = notice.local_behind[0]
        self.assertEqual(behind.recorded, "0.0.1")
        self.assertIsNone(behind.remedy_command)

    def test_an_install_made_with_the_running_release_says_nothing(self):
        _present(self.home)
        runtime = self.runtime()
        cli.install(CLI, runtime)
        notice = session.local_update_notice(runtime, installed=session.detect_installed(runtime))
        self.assertEqual(len(notice.local_behind), 1)
        self.assertIsNone(notice.local_behind[0].remedy_command)
        from pegasus.tui.navigator import update_notice_lines

        self.assertEqual(update_notice_lines(notice), ())

    def test_an_install_whose_update_would_refuse_names_the_remedy_not_update(self):
        """The primary fix: an installation with a bound mcp server whose
        key was never recorded (an install made before `mcp_bindings` was
        tracked) makes `update` refuse outright -- the notice must never
        send someone into that refusal by recommending `Update`."""
        _present(self.home)
        runtime = self.runtime()
        cli.install(CLI, runtime, mcp=["cbm=codebase-memory-mcp"])
        store = cli.journal_store(runtime)
        journal = store.load()
        install = journal_module.install_for(journal, CLI)
        older_release = {**install.release, "version": "0.0.1"}
        store.save(
            journal_module.with_install(journal, replace(install, release=older_release, mcp_bindings={}))
        )

        notice = session.local_update_notice(runtime, installed=session.detect_installed(runtime))
        self.assertEqual(len(notice.local_behind), 1)
        behind = notice.local_behind[0]
        self.assertEqual(behind.recorded, "0.0.1")
        self.assertIsNotNone(behind.remedy_command)
        self.assertEqual(
            behind.remedy_command,
            cli.install_command_for(CLI, ["cbm"], program_name=runtime.identity.program_name),
        )

        from pegasus.tui.navigator import update_notice_lines

        lines = update_notice_lines(notice)
        self.assertEqual(len(lines), 1)
        self.assertNotIn("choose Update", lines[0])
        self.assertIn(behind.remedy_command, lines[0])


class LocalUpdateNoticeIdentityTest(BrandAssertionMixin, SessionTestCase):
    """`local_update_notice` is the one impure bridge that used to build its
    remedy command without ever passing `program_name=` down to
    `cli.install_command_for` -- so it silently fell back to the packaged
    identity's own program name instead of `runtime.identity`'s.

    Every other test in this module builds its `Runtime` with no
    `identity=` at all, which means `runtime.identity` and
    `default_identity()` are the same object -- exactly the coincidence
    that let the missing argument hide (see `test_cli_identity_sweep.py`'s
    own module docstring for the same reasoning at the `cli.py` layer).
    This test builds a `Runtime` around ACME -- an obviously fictional
    product, never a real organization -- so a remedy command that quietly
    named Pegasus instead cannot be mistaken for a coincidental match.
    """

    def runtime(self, home: Path | None = None) -> cli.Runtime:
        return cli.Runtime(
            filesystem=PosixFileSystem(product_id=ACME_IDENTITY.product_id),
            home=home or self.home,
            now=AT,
            out=io.StringIO(),
            variables=NO_BINARY,
            identity=ACME_IDENTITY,
        )

    def test_remedy_command_names_acme_never_the_engine(self):
        _present(self.home)
        runtime = self.runtime()
        cli.install(CLI, runtime, mcp=["cbm=acme-widget-key"])
        store = cli.journal_store(runtime)
        journal = store.load()
        install = journal_module.install_for(journal, CLI)
        store.save(journal_module.with_install(journal, replace(install, mcp_bindings={})))

        notice = session.local_update_notice(runtime, installed=session.detect_installed(runtime))
        self.assertEqual(len(notice.local_behind), 1)
        behind = notice.local_behind[0]
        self.assertIsNotNone(behind.remedy_command)
        self.assertIn(ACME_IDENTITY.program_name, behind.remedy_command)
        self.assertNoEngineBrand(behind.remedy_command)


class UpdateThroughTheTuiTest(SessionTestCase):
    """`Update`: mirrors the Install flow's menu-plan-confirm shape, but the
    plan comes from `cli.update` -- an installation's own recorded
    selection reapplied, no fresh choice ever asked for."""

    def to_update_menu(self, runtime) -> Navigator:
        navigator = Navigator.starting(session.detect_clis(runtime), session.detect_installed(runtime))
        update_index = [entry.label for entry in navigator.current.entries].index("Update")
        for _ in range(update_index):
            navigator = navigator.handle(Action.MOVE_DOWN)
        return session.step(navigator, runtime, Action.CHOOSE)  # opens the update submenu

    def test_the_update_entry_offers_only_installed_clis(self):
        _present(self.home)
        runtime = self.runtime()
        cli.install(CLI, runtime)
        navigator = self.to_update_menu(runtime)
        self.assertIsInstance(navigator.current, Menu)
        self.assertEqual([entry.target.cli.id for entry in navigator.current.entries], [CLI])

    def test_choosing_an_installed_cli_fetches_a_plan_preview_and_writes_nothing(self):
        _present(self.home)
        runtime = self.runtime()
        cli.install(CLI, runtime, mcp=["context7"])
        before = _tree(self.home)
        navigator = self.to_update_menu(runtime)
        navigator = session.step(navigator, runtime, Action.CHOOSE)  # fetches the update plan
        self.assertIsInstance(navigator.current, InstallPlanScreen)
        self.assertEqual(navigator.current.command, "update")
        self.assertEqual(navigator.current.report["status"], "planned")
        self.assertEqual(_tree(self.home), before)

    def test_confirming_matches_the_equivalent_cli_update_on_a_separate_home(self):
        with tempfile.TemporaryDirectory(dir=self.home.parent) as other:
            other_home = Path(other)
            for home in (self.home, other_home):
                _present(home)
                cli.install(CLI, self.runtime(home), mcp=["context7"])

            cli_runtime = self.runtime(self.home)
            cli_code = cli.main(["update", "--cli", CLI, "--json"], runtime=cli_runtime)
            cli_report = json.loads(cli_runtime.out.getvalue())

            tui_runtime = self.runtime(other_home)
            navigator = self.to_update_menu(tui_runtime)
            navigator = session.step(navigator, tui_runtime, Action.CHOOSE)  # fetches the plan
            navigator = session.step(navigator, tui_runtime, Action.CHOOSE)  # confirms it

            self.assertEqual(cli_code, 0)
            self.assertIsInstance(navigator.current, InstallResultScreen)
            self.assertEqual(navigator.current.command, "update")
            self.assertEqual(navigator.current.report["status"], "installed")
            self.assertEqual(_sans(cli_report, str(self.home)), _sans(navigator.current.report, str(other_home)))

    def test_an_unresolved_mcp_binding_goes_straight_to_a_result_screen_naming_the_fix(self):
        """No plan to preview and nothing to confirm: `update` refuses before
        ever calling `install`, so this must land directly on a result
        screen carrying the refusal -- not a plan screen that has nothing
        real to show."""
        _present(self.home)
        runtime = self.runtime()
        cli.install(CLI, runtime, mcp=["cbm=codebase-memory-mcp"])
        store = cli.journal_store(runtime)
        journal = store.load()
        install = journal_module.install_for(journal, CLI)
        store.save(journal_module.with_install(journal, replace(install, mcp_bindings={})))

        navigator = self.to_update_menu(runtime)
        navigator = session.step(navigator, runtime, Action.CHOOSE)

        self.assertIsInstance(navigator.current, InstallResultScreen)
        self.assertEqual(navigator.current.command, "update")
        report = navigator.current.report
        self.assertEqual(report["status"], "failed")
        self.assertIn("cbm", report["error"])
        self.assertIn(f"pegasus install --cli {CLI} --mcp cbm=<key>", report["error"])

    def test_update_task_reports_progress_through_the_sink_and_matches_the_synchronous_result(self):
        with tempfile.TemporaryDirectory(dir=self.home.parent) as other:
            other_home = Path(other)
            for home in (self.home, other_home):
                _present(home)
                cli.install(CLI, self.runtime(home), mcp=["context7"])

            sync_runtime = self.runtime(self.home)
            navigator = self.to_update_menu(sync_runtime)
            navigator = session.step(navigator, sync_runtime, Action.CHOOSE)  # fetches the plan
            sync_result = session.step(navigator, sync_runtime, Action.CHOOSE)

            task_runtime = self.runtime(other_home)
            navigator = self.to_update_menu(task_runtime)
            navigator = session.step(navigator, task_runtime, Action.CHOOSE)  # fetches the plan
            plan_screen = navigator.current

            events = []
            run = session.plan_task(navigator, task_runtime, plan_screen)
            task_result = run(events.append)

            self.assertTrue(events, "no Progress event reached the sink")
            self.assertIsInstance(task_result.current, InstallResultScreen)
            self.assertEqual(task_result.current.command, "update")
            self.assertEqual(
                _sans(sync_result.current.report, str(self.home)),
                _sans(task_result.current.report, str(other_home)),
            )


class StatusScreenTest(SessionTestCase):
    def test_choosing_status_from_the_main_menu_matches_doctor(self):
        _present(self.home)
        runtime = self.runtime()
        cli.install(CLI, runtime)
        navigator = Navigator.starting(session.detect_clis(runtime), session.detect_installed(runtime))
        status_index = [entry.label for entry in navigator.current.entries].index("Status and diagnostics")
        for _ in range(status_index):
            navigator = navigator.handle(Action.MOVE_DOWN)
        self.assertIsInstance(navigator.current.entries[navigator.cursor].target, StatusRequest)
        navigator = session.step(navigator, runtime, Action.CHOOSE)
        self.assertIsInstance(navigator.current, StatusScreen)
        _, expected = cli.safe_report("doctor", lambda: cli.doctor(runtime))
        self.assertEqual(_sans(navigator.current.report, str(self.home)), _sans(expected, str(self.home)))

    def test_choosing_restore_from_status_with_nothing_captured_says_so(self):
        runtime = self.runtime()
        navigator = Navigator.starting()
        status_index = [entry.label for entry in navigator.current.entries].index("Status and diagnostics")
        for _ in range(status_index):
            navigator = navigator.handle(Action.MOVE_DOWN)
        navigator = session.step(navigator, runtime, Action.CHOOSE)  # StatusScreen
        navigator = session.step(navigator, runtime, Action.CHOOSE)  # asks for the restore menu
        self.assertIsInstance(navigator.current, Placeholder)


class UninstallThroughTheTuiTest(SessionTestCase):
    def to_preview(self, runtime) -> "Navigator":
        navigator = Navigator.starting(session.detect_clis(runtime), session.detect_installed(runtime))
        uninstall_index = [entry.label for entry in navigator.current.entries].index("Uninstall")
        for _ in range(uninstall_index):
            navigator = navigator.handle(Action.MOVE_DOWN)
        navigator = session.step(navigator, runtime, Action.CHOOSE)  # opens the CLI choice
        navigator = session.step(navigator, runtime, Action.CHOOSE)  # opens the preview
        return navigator

    def test_the_default_cursor_sits_on_cancel_not_confirm(self):
        _present(self.home)
        runtime = self.runtime()
        cli.install(CLI, runtime)
        navigator = self.to_preview(runtime)
        self.assertEqual(navigator.cursor, 0)
        self.assertIn("Cancel", navigator.current.entries[0].label)

    def test_a_person_who_does_not_confirm_leaves_the_home_untouched(self):
        """The preview shows what would be removed — `preface` is not
        empty — but only ever reads, and a person who does not move onto
        Confirm before pressing enter leaves the home exactly as it was."""
        _present(self.home)
        runtime = self.runtime()
        cli.install(CLI, runtime)
        before = _tree(self.home)
        navigator = self.to_preview(runtime)
        self.assertTrue(navigator.current.preface)
        navigator = session.step(navigator, runtime, Action.CHOOSE)  # cursor still on Cancel
        self.assertIsInstance(navigator.current, Menu)  # back on the CLI choice
        self.assertEqual(_tree(self.home), before)
        self.assertEqual([option.id for option in session.detect_installed(runtime)], [CLI])

    def test_confirming_matches_the_equivalent_cli_uninstall_on_a_separate_home(self):
        with tempfile.TemporaryDirectory(dir=self.home.parent) as other:
            other_home = Path(other)
            for home in (self.home, other_home):
                _present(home)
                cli.install(CLI, self.runtime(home))

            cli_runtime = self.runtime(self.home)
            cli_code = cli.main(["uninstall", "--cli", CLI, "--json"], runtime=cli_runtime)
            cli_report = json.loads(cli_runtime.out.getvalue())

            tui_runtime = self.runtime(other_home)
            navigator = self.to_preview(tui_runtime)
            navigator = navigator.handle(Action.MOVE_DOWN)  # onto Confirm
            navigator = session.step(navigator, tui_runtime, Action.CHOOSE)

            self.assertEqual(cli_code, 0)
            self.assertIsInstance(navigator.current, UninstallResultScreen)
            self.assertEqual(navigator.current.report["status"], "uninstalled")
            self.assertEqual(_sans(cli_report, str(self.home)), _sans(navigator.current.report, str(other_home)))

    def test_acknowledging_the_result_returns_to_the_main_menu(self):
        _present(self.home)
        runtime = self.runtime()
        cli.install(CLI, runtime)
        navigator = self.to_preview(runtime)
        navigator = navigator.handle(Action.MOVE_DOWN)
        navigator = session.step(navigator, runtime, Action.CHOOSE)
        navigator = navigator.handle(Action.CHOOSE)
        self.assertIsInstance(navigator.current, Menu)
        self.assertEqual(navigator.current.title, Navigator.starting().current.title)


class RestoreThroughTheTuiTest(SessionTestCase):
    def _installed_then_uninstalled(self, home: Path) -> cli.Runtime:
        _present(home)
        runtime = self.runtime(home)
        cli.install(CLI, runtime)
        cli.uninstall(CLI, runtime)  # leaves exactly one readable generation behind
        return runtime

    def to_generation_preview(self, runtime) -> "Navigator":
        navigator = Navigator.starting()
        status_index = [entry.label for entry in navigator.current.entries].index("Status and diagnostics")
        for _ in range(status_index):
            navigator = navigator.handle(Action.MOVE_DOWN)
        navigator = session.step(navigator, runtime, Action.CHOOSE)  # StatusScreen
        navigator = session.step(navigator, runtime, Action.CHOOSE)  # RestoreMenuScreen
        self.assertIsInstance(navigator.current, Menu)
        navigator = session.step(navigator, runtime, Action.CHOOSE)  # generation preview
        return navigator

    def test_the_confirm_screen_agrees_with_the_menu_it_was_reached_from(self):
        """Found by review: the fix for the menu's labels stopped one screen
        short. This preview read `manifest.taken_at` straight, so a person
        who picked "18:50" off the menu landed on a screen quoting a raw
        `2026-08-13T21:50:00+00:00` -- three hours off, in a shape nobody
        reads, and disagreeing with the row they had just clicked.

        Two screens in one flow describing the same snapshot must not
        describe it differently. The hour is asserted here rather than the
        format alone, because a formatting-only fix would still leave them
        naming different times.
        """
        self.in_timezone("America/Argentina/Buenos_Aires")
        runtime = self._installed_then_uninstalled(self.home)
        navigator = self.to_generation_preview(runtime)

        preface = "\n".join(navigator.current.preface)
        self.assertIn("Taken 13 Aug 2026, 21:00", preface)
        self.assertNotIn("+00:00", preface)
        self.assertNotIn("2026-08-14T00:00:00", preface)

    def test_the_default_cursor_sits_on_cancel_not_confirm(self):
        runtime = self._installed_then_uninstalled(self.home)
        navigator = self.to_generation_preview(runtime)
        self.assertEqual(navigator.cursor, 0)
        self.assertIn("Cancel", navigator.current.entries[0].label)

    def test_a_person_who_does_not_confirm_leaves_the_home_untouched(self):
        """The preview names the generation and what going back to it would
        touch — `preface` is not empty — but only ever reads it back."""
        runtime = self._installed_then_uninstalled(self.home)
        before = _tree(self.home)
        navigator = self.to_generation_preview(runtime)
        self.assertTrue(navigator.current.preface)
        navigator = session.step(navigator, runtime, Action.CHOOSE)  # cursor still on Cancel
        self.assertIsInstance(navigator.current, Menu)  # back on the generation choice
        self.assertEqual(_tree(self.home), before)

    def test_confirming_matches_the_equivalent_cli_restore_on_a_separate_home(self):
        with tempfile.TemporaryDirectory(dir=self.home.parent) as other:
            other_home = Path(other)
            cli_runtime = self._installed_then_uninstalled(self.home)
            tui_runtime = self._installed_then_uninstalled(other_home)

            cli_code = cli.main(["restore", "--json"], runtime=cli_runtime)
            cli_report = json.loads(cli_runtime.out.getvalue())

            navigator = self.to_generation_preview(tui_runtime)
            navigator = navigator.handle(Action.MOVE_DOWN)  # onto Confirm
            navigator = session.step(navigator, tui_runtime, Action.CHOOSE)

            self.assertEqual(cli_code, 0)
            self.assertIsInstance(navigator.current, RestoreResultScreen)
            self.assertEqual(navigator.current.report["status"], "restored")
            self.assertEqual(_sans(cli_report, str(self.home)), _sans(navigator.current.report, str(other_home)))

    def to_restore_menu(self, runtime) -> "Navigator":
        navigator = Navigator.starting()
        status_index = [entry.label for entry in navigator.current.entries].index("Status and diagnostics")
        for _ in range(status_index):
            navigator = navigator.handle(Action.MOVE_DOWN)
        navigator = session.step(navigator, runtime, Action.CHOOSE)  # StatusScreen
        return session.step(navigator, runtime, Action.CHOOSE)  # RestoreMenuScreen

    def test_the_restore_menu_labels_each_generation_with_when_it_was_taken(self):
        """The bug report this closes: a bare "Generation 4" tells nobody
        which snapshot is the one they want. `session.step` now reads each
        generation's own manifest, so the label carries the fact a person
        actually recognises -- when it was taken -- not just its ordinal."""
        self.in_timezone("UTC")
        _present(self.home)
        runtime = self.runtime(self.home)
        cli.install(CLI, runtime)
        cli.install(CLI, runtime)  # a second install captures a second generation

        navigator = self.to_restore_menu(runtime)

        self.assertIsInstance(navigator.current, Menu)
        labels = [entry.label for entry in navigator.current.entries]
        self.assertEqual(len(labels), 2)
        self.assertTrue(labels[0].startswith("Generation 2 — install — 14 Aug 2026, 00:00 (most recent)"), labels[0])
        self.assertTrue(labels[1].startswith("Generation 1 — install — 14 Aug 2026, 00:00"))
        self.assertNotIn("(most recent)", labels[1])

    def test_a_label_reads_the_clock_the_person_was_looking_at(self):
        """Found by running the finished screen against a real installation:
        `taken_at` is recorded in UTC, and the label was printing that wall
        clock verbatim. In Buenos Aires a snapshot taken at 18:50 was
        labelled 21:50 -- not an obviously broken value, which is worse,
        because a plausible wrong hour is one a person believes.

        That defeats the entire reason this label exists. The justification
        for putting a timestamp here at all was that somebody recognises
        what they did at 4am; told it happened at 07:00, they recognise
        nothing. So the conversion belongs where the manifest is read, and
        `AT` here is midnight UTC precisely so the shift crosses a date
        boundary and a half-done fix cannot pass by coincidence.
        """
        self.in_timezone("America/Argentina/Buenos_Aires")
        _present(self.home)
        runtime = self.runtime(self.home)
        cli.install(CLI, runtime)

        navigator = self.to_restore_menu(runtime)

        label = navigator.current.entries[0].label
        self.assertIn("13 Aug 2026, 21:00", label)
        self.assertNotIn("14 Aug 2026", label)

    def test_an_unreadable_generation_is_skipped_without_hiding_a_good_one(self):
        """`readable_generations` only checks a manifest file exists, not
        that it parses (see `ports.snapshot_store`'s module docstring), so a
        generation it still names can raise `SnapshotStoreError` once this
        screen actually reads it. One corrupt folder must not blank out the
        whole recovery screen -- the good generation must still be offered,
        and the screen must say one was left out rather than pretend there
        never was another."""
        _present(self.home)
        runtime = self.runtime(self.home)
        cli.install(CLI, runtime)
        cli.install(CLI, runtime)  # generations 1 and 2
        corrupt_manifest = snapshots_root(runtime.filesystem, self.home) / "000002" / MANIFEST_FILENAME
        corrupt_manifest.write_bytes(b"not json at all")

        navigator = self.to_restore_menu(runtime)

        self.assertIsInstance(navigator.current, Menu)
        self.assertEqual([entry.label.split(" ")[1] for entry in navigator.current.entries], ["1"])
        note = next(line for line in navigator.current.preface if "could not be read" in line)
        # The corrupt folder here is generation 2, the NEWEST one, so the note
        # has to name it and the surviving entry must not claim to be the most
        # recent snapshot Pegasus took -- it is only the most recent it can open.
        self.assertIn("Generation 2", note)
        self.assertNotIn("(most recent)", navigator.current.entries[0].label)


def _write_catalog(home: Path, payload: dict) -> None:
    path = home / ".cache" / "opencode" / "models.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_credentials(home: Path, payload: dict) -> None:
    path = home / ".local" / "share" / "opencode" / "auth.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _cli_option(runtime: cli.Runtime):
    """The CLI this walk ends up on, off the same detection the screen uses."""
    return next(option for option in session.detect_clis(runtime) if option.id == CLI)


def _install_entry_label(runtime: cli.Runtime) -> str:
    """The main menu's own install entry, found by where it leads rather than
    by what it says -- a refusal that sends a person to something the menu no
    longer calls that is a refusal that names nothing."""
    root = Navigator.starting(session.detect_clis(runtime), session.detect_installed(runtime)).current
    return next(
        entry.label
        for entry in root.entries
        if isinstance(entry.target, Menu)
        and any(isinstance(row.target, navigator_module.InstallTarget) for row in entry.target.entries)
    )


ONE_PLAIN_MODEL = {"anthropic": {"builtin": True, "models": {"fast-model": {"tool_call": True}}}}
ONE_REASONING_MODEL = {"anthropic": {"builtin": True, "models": {"deep-thinker": {"tool_call": True, "reasoning": True}}}}


class ModelsScreenTestCase(SessionTestCase):
    def install(self, runtime: cli.Runtime) -> None:
        """An installation for this screen to stand on.

        `cli.models_set`/`cli.models_unset` render what they record, so they
        refuse a CLI with nothing installed exactly the way `cli.mcp_grant`
        already does -- a models screen over an uninstalled CLI could only
        ever collect choices nothing would apply. Idempotent, so a test that
        needs an installation *before* it navigates can ask for one without
        paying for a second install here.
        """
        _present(self.home)
        if journal_module.install_for(cli.journal_store(runtime).load(), CLI) is None:
            cli.install(CLI, runtime)

    def to_models_screen(self, runtime: cli.Runtime, *, installed: bool = True) -> Navigator:
        """The whole walk from the main menu to whatever this CLI's models
        step turns out to be. `installed=False` leaves the CLI detected but
        with nothing installed into it, which is the one case the screen
        itself has an answer for rather than a wizard."""
        if installed:
            self.install(runtime)
        else:
            _present(self.home)
        navigator = Navigator.starting(session.detect_clis(runtime), session.detect_installed(runtime))
        models_index = [entry.label for entry in navigator.current.entries].index("Configure models")
        for _ in range(models_index):
            navigator = navigator.handle(Action.MOVE_DOWN)
        navigator = session.step(navigator, runtime, Action.CHOOSE)  # the per-CLI choice, pure
        return session.step(navigator, runtime, Action.CHOOSE)  # fetches the catalog


class EmptyCatalogTest(ModelsScreenTestCase):
    def test_no_catalog_yet_is_explained_not_an_error(self):
        navigator = self.to_models_screen(self.runtime())
        self.assertIsInstance(navigator.current, Placeholder)
        self.assertNotIn("Traceback", navigator.current.note)


class NothingInstalledTest(ModelsScreenTestCase):
    """A CLI with nothing installed is refused when the screen opens.

    A model assignment is written straight into the rendered configuration
    now, so `cli.models_set`/`cli.models_unset` refuse a CLI with nothing
    installed. Learning that at the confirmation is learning it after
    choosing an agent, a provider, a model and an effort -- four choices that
    could never have applied. The same reasoning `grant_mcp_menu` already
    follows for its own menu, answered here with the `Placeholder` shape this
    very function already uses for the other state it has nothing to offer
    for (a CLI with no model catalog yet).

    What is asserted is that the screen is not a wizard: no agent rows, so
    there is nothing to walk. Asserting only that some string came back would
    pass over a `ModelsScreen` that happened to carry the sentence.
    """

    def test_a_cli_with_nothing_installed_gets_no_menu_of_agents(self):
        _write_catalog(self.home, ONE_PLAIN_MODEL)
        navigator = self.to_models_screen(self.runtime(), installed=False)
        self.assertNotIsInstance(navigator.current, ModelsScreen)
        self.assertIsInstance(navigator.current, Placeholder)

    def test_the_refusal_names_the_cli_and_what_to_do_about_it(self):
        runtime = self.runtime()
        _write_catalog(self.home, ONE_PLAIN_MODEL)
        navigator = self.to_models_screen(runtime, installed=False)
        note = navigator.current.note
        self.assertIn(_cli_option(runtime).display_name, note)
        self.assertIn(_install_entry_label(runtime), note)

    def test_installing_turns_the_same_walk_into_the_wizard(self):
        """Or the refusal above would prove only that this screen is broken
        for everyone."""
        _write_catalog(self.home, ONE_PLAIN_MODEL)
        navigator = self.to_models_screen(self.runtime())
        self.assertIsInstance(navigator.current, ModelsScreen)
        self.assertTrue(navigator.current.rows)


class _NeverDeclaresPerAgentModel:
    """An adapter honest about declaring no capabilities at all -- in
    particular, never `per_agent_model` -- and therefore, per
    `registry._check_capabilities`, carrying no `model_catalog` attribute
    whatsoever. Registrable on its own terms: `Registry.register` also walks
    `id`, manifest/layout agreement, `own_artifacts` territory and
    `activation_steps`, so this fake answers all four the same minimal way
    `test_registry.FakeAdapter` does, rather than only the one capability
    this test cares about."""

    id = "probe-no-models"
    display_name = "Probe No Models"

    def __init__(self):
        self._manifest = CapabilityManifest(cli_id=self.id)

    def tier(self):
        return SupportTier.FULL

    def capabilities(self):
        return self._manifest

    def detect(self, environment):
        layout = self.layout(environment)
        return Detection(config_dir=layout.config_dir, config_found=True)

    def layout(self, environment):
        return Layout(config_dir=Path(environment.home) / ".config" / "probe-no-models")

    def own_artifacts(self, layout, orchestrator_name, identity, delegation_targets):
        return []

    def activation_steps(self):
        return ()

    def directory_grant_behavior(self):
        from pegasus.core.types import DirectoryGrantBehavior

        return DirectoryGrantBehavior(allowed_by_default=True, writes_own_entry=False, has_deny_floor=False)


class NoPerAgentModelCapabilityTest(ModelsScreenTestCase):
    """The most fundamental of the three explanations this screen can show:
    a CLI whose adapter never declared per-agent models has nothing here to
    configure whether or not Pegasus is installed into it -- so this is
    checked ahead of the installation state, not after it."""

    def _installed_cli_option(self, adapter, runtime):
        """Records a fabricated install for `adapter`'s CLI, so
        `journal_module.install_for` finds one -- the state under which the
        old, unguarded code reached `model_catalog` and raised
        `AttributeError`. Real work only what this test needs: a `Journal`
        entry, never a whole `cli.install` run against a fake adapter that
        cannot render anything."""
        layout = adapter.layout(runtime.environment)
        install = journal_module.Install(
            cli=adapter.id,
            installed_at="2026-08-14T00:00:00+00:00",
            config_dir=layout.config_dir,
            release={},
        )
        store = cli.journal_store(runtime)
        store.save(journal_module.with_install(store.load(), install))
        return CliOption(
            id=adapter.id,
            display_name=adapter.display_name,
            config_dir=str(layout.config_dir),
            tier=adapter.tier().value,
        )

    def test_a_cli_that_never_declared_the_capability_gets_an_explanation(self):
        adapter = _NeverDeclaresPerAgentModel()
        registry = Registry(adapter)
        runtime = self.runtime()
        cli_option = self._installed_cli_option(adapter, runtime)
        with unittest.mock.patch.object(session, "available", return_value=registry):
            screen = session._models_screen(cli_option, runtime)
        self.assertIsInstance(screen, Placeholder)
        note = screen.note
        self.assertIn(adapter.display_name, note)
        self.assertIn(cli.per_agent_model_reason(adapter), note)

    def test_it_wins_over_the_installation_explanation(self):
        """Not installed *and* incapable at once still reads as the
        capability explanation -- the more fundamental of the two -- never
        the installation one, which would tell the person to do something
        (install) that could never make this screen configurable."""
        adapter = _NeverDeclaresPerAgentModel()
        registry = Registry(adapter)
        cli_option = CliOption(
            id=adapter.id,
            display_name=adapter.display_name,
            config_dir=str(adapter.layout(Environment(home=self.home)).config_dir),
            tier=adapter.tier().value,
        )
        runtime = self.runtime()
        # no journal entry exists for this CLI at all: nothing installed.
        with unittest.mock.patch.object(session, "available", return_value=registry):
            screen = session._models_screen(cli_option, runtime)
        self.assertIsInstance(screen, Placeholder)
        note = screen.note.lower()
        self.assertIn(cli.per_agent_model_reason(adapter).lower(), note)
        self.assertNotIn("main menu's install entry", note)


class DisabledModelReasonsTest(SessionTestCase):
    """`session.disabled_model_reasons` is what `app.run` hands
    `Navigator.starting` so `models_menu` can mark a CLI lacking the
    capability disabled, with a person-facing reason already resolved,
    before a person ever walks into it -- the one place in this module that
    reads the registry for exactly this fact, derived from whatever is
    registered rather than hand-listed, so a third adapter is covered the
    moment it registers."""

    def test_every_id_returned_actually_lacks_the_capability(self):
        registry = available()
        reasons = session.disabled_model_reasons()
        for cli_id in reasons:
            self.assertFalse(registry.manifest(cli_id).declares(Capability.PER_AGENT_MODEL))

    def test_every_incapable_registered_adapter_is_included(self):
        registry = available()
        expected = {
            cli_id for cli_id in registry.ids() if not registry.manifest(cli_id).declares(Capability.PER_AGENT_MODEL)
        }
        self.assertEqual(set(session.disabled_model_reasons()), expected)

    def test_each_reason_matches_cli_per_agent_model_reason_for_that_adapter(self):
        """One voice: the same string `_require_per_agent_model` and
        `_models_screen`'s own placeholder use, never a second wording
        invented here."""
        registry = available()
        reasons = session.disabled_model_reasons()
        for cli_id, reason in reasons.items():
            self.assertEqual(reason, cli.per_agent_model_reason(registry.get(cli_id)))

    def test_a_registry_with_no_incapable_adapter_returns_nothing(self):
        # Any real adapter that already declares the capability -- picked
        # from the real registry rather than a bespoke fake, since all this
        # needs is one that actually does.
        capable_adapter = next(
            available().get(cli_id)
            for cli_id in available().ids()
            if available().manifest(cli_id).declares(Capability.PER_AGENT_MODEL)
        )
        registry = Registry(capable_adapter)
        with unittest.mock.patch.object(session, "available", return_value=registry):
            self.assertEqual(session.disabled_model_reasons(), {})

    def test_an_adapter_lacking_the_capability_is_mapped_to_its_reason(self):
        adapter = _NeverDeclaresPerAgentModel()
        registry = Registry(adapter)
        with unittest.mock.patch.object(session, "available", return_value=registry):
            reasons = session.disabled_model_reasons()
        self.assertEqual(reasons, {adapter.id: cli.per_agent_model_reason(adapter)})


class AssignmentListTest(ModelsScreenTestCase):
    def test_every_configurable_agent_is_listed_starting_with_no_model(self):
        _write_catalog(self.home, ONE_PLAIN_MODEL)
        navigator = self.to_models_screen(self.runtime())
        self.assertIsInstance(navigator.current, ModelsScreen)
        self.assertEqual({row.agent for row in navigator.current.rows}, _configurable_agent_names())
        self.assertTrue(all(row.current is None for row in navigator.current.rows))

    def test_only_the_reachable_providers_and_their_models_are_offered(self):
        _write_catalog(self.home, ONE_PLAIN_MODEL)
        navigator = self.to_models_screen(self.runtime())
        self.assertEqual([provider.id for provider in navigator.current.providers], ["anthropic"])
        self.assertEqual([model.id for model in navigator.current.providers[0].models], ["fast-model"])


def _to_confirm_row(navigator: Navigator) -> Navigator:
    """Move the cursor from wherever it sits on the rows step onto the
    trailing Confirm row -- the same row `McpSelectionScreen`'s own
    Continue occupies after its last server."""
    count = len(navigator.current.rows)
    while navigator.cursor != count:
        navigator = navigator.handle(Action.MOVE_DOWN)
    return navigator


class WalkTheFourStepsTest(ModelsScreenTestCase):
    def _to_agent_row(self, navigator: Navigator) -> Navigator:
        rows = navigator.current.rows
        index = next(i for i, row in enumerate(rows) if row.agent == CONFIGURABLE_AGENT)
        for _ in range(index):
            navigator = navigator.handle(Action.MOVE_DOWN)
        return navigator.handle(Action.CHOOSE)

    def test_a_plain_model_is_staged_pure_and_only_applied_on_confirm(self):
        _write_catalog(self.home, ONE_PLAIN_MODEL)
        runtime = self.runtime()
        navigator = self.to_models_screen(runtime)
        navigator = self._to_agent_row(navigator)  # agent chosen
        navigator = navigator.handle(Action.CHOOSE)  # the one provider
        navigator = navigator.handle(Action.CHOOSE)  # the one, plain, model: stages, pure -- no engine call

        self.assertIsInstance(navigator.current, ModelsScreen)
        self.assertIsNone(navigator.current.agent)  # back at the rows step
        self.assertEqual(
            navigator.current.staged,
            (navigator_module.StagedChange(agent=CONFIGURABLE_AGENT, model="anthropic/fast-model", effort=None),),
        )
        # Staged only -- nothing reached the store or the rendered rows yet.
        assignments = cli.model_assignment_store(runtime).load()
        self.assertIsNone(model_assignments_module.get(assignments, CLI, CONFIGURABLE_AGENT))
        row = next(row for row in navigator.current.rows if row.agent == CONFIGURABLE_AGENT)
        self.assertIsNone(row.current)

        navigator = _to_confirm_row(navigator)
        navigator = session.step(navigator, runtime, Action.CHOOSE)  # applies the staged batch

        self.assertIsInstance(navigator.current, ModelsScreen)
        self.assertEqual(navigator.current.staged, ())
        assignments = cli.model_assignment_store(runtime).load()
        assignment = model_assignments_module.get(assignments, CLI, CONFIGURABLE_AGENT)
        self.assertEqual(assignment.full_id, "anthropic/fast-model")
        self.assertIsNone(assignment.effort)
        row = next(row for row in navigator.current.rows if row.agent == CONFIGURABLE_AGENT)
        self.assertEqual(row.current, "anthropic/fast-model")

    def test_a_reasoning_model_asks_for_effort_before_it_is_staged(self):
        _write_catalog(self.home, ONE_REASONING_MODEL)
        runtime = self.runtime()
        navigator = self.to_models_screen(runtime)
        navigator = self._to_agent_row(navigator)
        navigator = navigator.handle(Action.CHOOSE)  # the one provider
        navigator = navigator.handle(Action.CHOOSE)  # the one, reasoning, model: only narrows
        self.assertEqual(navigator.current.model_id, "deep-thinker")

        navigator = navigator.handle(Action.CHOOSE)  # the first effort offered: stages, pure
        self.assertIsInstance(navigator.current, ModelsScreen)
        self.assertIsNone(navigator.current.agent)
        [staged] = navigator.current.staged
        self.assertEqual(staged.agent, CONFIGURABLE_AGENT)
        self.assertEqual(staged.model, "anthropic/deep-thinker")
        self.assertIsNotNone(staged.effort)
        assignments = cli.model_assignment_store(runtime).load()
        self.assertIsNone(model_assignments_module.get(assignments, CLI, CONFIGURABLE_AGENT))

        navigator = _to_confirm_row(navigator)
        navigator = session.step(navigator, runtime, Action.CHOOSE)
        assignments = cli.model_assignment_store(runtime).load()
        assignment = model_assignments_module.get(assignments, CLI, CONFIGURABLE_AGENT)
        self.assertEqual(assignment.full_id, "anthropic/deep-thinker")
        self.assertIsNotNone(assignment.effort)


class RemovingAnAssignmentTest(ModelsScreenTestCase):
    def test_d_stages_a_removal_pure_and_only_applies_it_on_confirm(self):
        _write_catalog(self.home, ONE_PLAIN_MODEL)
        runtime = self.runtime()
        self.install(runtime)
        cli.models_set(CLI, [cli.ModelAssignmentSpec(agent=CONFIGURABLE_AGENT, model="anthropic/fast-model")], runtime)

        navigator = self.to_models_screen(runtime)
        index = next(i for i, row in enumerate(navigator.current.rows) if row.agent == CONFIGURABLE_AGENT)
        for _ in range(index):
            navigator = navigator.handle(Action.MOVE_DOWN)
        self.assertEqual(navigator.current.rows[navigator.cursor].current, "anthropic/fast-model")

        navigator = navigator.handle(Action.REMOVE)  # stages, pure -- no engine call
        self.assertEqual(
            navigator.current.staged,
            (navigator_module.StagedChange(agent=CONFIGURABLE_AGENT, model=None),),
        )
        # Still applied on disk -- staging alone must not write.
        assignments = cli.model_assignment_store(runtime).load()
        self.assertIsNotNone(model_assignments_module.get(assignments, CLI, CONFIGURABLE_AGENT))

        navigator = _to_confirm_row(navigator)
        navigator = session.step(navigator, runtime, Action.CHOOSE)

        self.assertIsInstance(navigator.current, ModelsScreen)
        self.assertEqual(navigator.current.staged, ())
        assignments = cli.model_assignment_store(runtime).load()
        self.assertIsNone(model_assignments_module.get(assignments, CLI, CONFIGURABLE_AGENT))
        row = next(row for row in navigator.current.rows if row.agent == CONFIGURABLE_AGENT)
        self.assertIsNone(row.current)


class LeavingWithoutConfirmingTest(ModelsScreenTestCase):
    """The other half of staging's contract: `esc` at the rows step, not
    Confirm, must discard whatever was staged and write nothing at all."""

    def test_staging_then_leaving_without_confirming_writes_nothing_and_moves_no_generation(self):
        _write_catalog(self.home, ONE_PLAIN_MODEL)
        runtime = self.runtime()
        navigator = self.to_models_screen(runtime)
        before = cli.snapshot_store(runtime).readable_generations()

        rows = navigator.current.rows
        index = next(i for i, row in enumerate(rows) if row.agent == CONFIGURABLE_AGENT)
        for _ in range(index):
            navigator = navigator.handle(Action.MOVE_DOWN)
        navigator = navigator.handle(Action.CHOOSE)  # agent chosen
        navigator = navigator.handle(Action.CHOOSE)  # the one provider
        navigator = navigator.handle(Action.CHOOSE)  # the one, plain, model: stages
        self.assertTrue(navigator.current.staged)

        # Through `session.step`, the real dispatcher every key press in
        # `app.py` goes through -- not `navigator.handle` directly -- so a
        # regression that made `_models_write` fire on `BACK` would be
        # caught here, not just a defect in `Navigator`'s own pure pop.
        navigator = session.step(navigator, runtime, Action.BACK)  # esc at the rows step: leaves, discards

        self.assertNotIsInstance(navigator.current, ModelsScreen)
        after = cli.snapshot_store(runtime).readable_generations()
        self.assertEqual(after, before)
        assignments = cli.model_assignment_store(runtime).load()
        self.assertIsNone(model_assignments_module.get(assignments, CLI, CONFIGURABLE_AGENT))


class MixedBatchOneConfirmOneGenerationTest(ModelsScreenTestCase):
    """The definition of done for this whole change: staging several
    assignments and a removal, confirming once, moves the snapshot
    generation count by exactly one -- not once per staged item."""

    OTHER_AGENT = "sdd-verify"

    def test_several_assignments_and_a_removal_confirmed_once_move_one_generation(self):
        _write_catalog(self.home, ONE_PLAIN_MODEL)
        runtime = self.runtime()
        self.install(runtime)
        # A pre-existing assignment on a third agent, staged for removal below.
        cli.models_set(CLI, [cli.ModelAssignmentSpec(agent=self.OTHER_AGENT, model="anthropic/fast-model")], runtime)

        navigator = self.to_models_screen(runtime)
        before = cli.snapshot_store(runtime).readable_generations()

        # Stage a plain-model assignment for CONFIGURABLE_AGENT.
        rows = navigator.current.rows
        index = next(i for i, row in enumerate(rows) if row.agent == CONFIGURABLE_AGENT)
        for _ in range(index):
            navigator = navigator.handle(Action.MOVE_DOWN)
        navigator = navigator.handle(Action.CHOOSE)  # agent chosen
        navigator = navigator.handle(Action.CHOOSE)  # the one provider
        navigator = navigator.handle(Action.CHOOSE)  # the one, plain, model: stages

        # Stage a removal for OTHER_AGENT, in the same sitting -- the cursor
        # sits at 0 after staging the assignment above (`.replaced` resets
        # it), so this walks it down to OTHER_AGENT's own row.
        rows = navigator.current.rows
        index = next(i for i, row in enumerate(rows) if row.agent == self.OTHER_AGENT)
        for _ in range(index):
            navigator = navigator.handle(Action.MOVE_DOWN)
        navigator = navigator.handle(Action.REMOVE)

        self.assertEqual(len(navigator.current.staged), 2)
        self.assertEqual(cli.snapshot_store(runtime).readable_generations(), before)  # nothing written yet

        navigator = _to_confirm_row(navigator)
        navigator = session.step(navigator, runtime, Action.CHOOSE)

        after = cli.snapshot_store(runtime).readable_generations()
        self.assertEqual(len(after), len(before) + 1)
        assignments = cli.model_assignment_store(runtime).load()
        self.assertEqual(
            model_assignments_module.get(assignments, CLI, CONFIGURABLE_AGENT).full_id, "anthropic/fast-model"
        )
        self.assertIsNone(model_assignments_module.get(assignments, CLI, self.OTHER_AGENT))


class ModelsAllOrNothingTest(ModelsScreenTestCase):
    """A staged batch with one invalid item must refuse the whole Confirm
    and write nothing -- the same all-or-nothing contract
    `test_batch_snapshot_atomicity.py` already proves for `cli.models_apply`
    directly, proven again here through the actual TUI confirm path."""

    def test_an_invalid_staged_item_writes_nothing_and_moves_no_generation(self):
        _write_catalog(self.home, ONE_PLAIN_MODEL)
        runtime = self.runtime()
        navigator = self.to_models_screen(runtime)
        before = cli.snapshot_store(runtime).readable_generations()

        rows = navigator.current.rows
        index = next(i for i, row in enumerate(rows) if row.agent == CONFIGURABLE_AGENT)
        for _ in range(index):
            navigator = navigator.handle(Action.MOVE_DOWN)
        navigator = navigator.handle(Action.CHOOSE)  # agent chosen
        navigator = navigator.handle(Action.CHOOSE)  # the one provider
        navigator = navigator.handle(Action.CHOOSE)  # the one, plain, model: stages

        # Corrupt the staged batch with an agent this release does not
        # configure -- `cli.models_apply` refuses this, the same way
        # `models_set` already refuses it for a single-item batch.
        corrupted = navigator.current.staged + (
            navigator_module.StagedChange(agent="nonexistent-agent", model="anthropic/fast-model"),
        )
        navigator = navigator.replaced(replace(navigator.current, staged=corrupted))

        navigator = _to_confirm_row(navigator)
        navigator = session.step(navigator, runtime, Action.CHOOSE)

        after = cli.snapshot_store(runtime).readable_generations()
        self.assertEqual(after, before)
        assignments = cli.model_assignment_store(runtime).load()
        self.assertIsNone(model_assignments_module.get(assignments, CLI, CONFIGURABLE_AGENT))


class ModelsWriteActivationTest(ModelsScreenTestCase):
    """Whatever the engine says is still left to do reaches the screen.

    The bug this started as: the models screen only ever showed what Pegasus's
    own state remembered, never what the running CLI configuration actually
    held, and the two only lined up again after a separate install. Confirming
    now reaches the rendered file in one `cli.models_apply` call for the whole
    staged batch, so what it reports under `activation` is the CLI's own
    activation step -- restarting it, since it reads agent prompts once at
    startup. Either way this screen is the one place that notice reaches a
    person, so every Confirm must carry the report's own `activation` forward
    onto the screen it rebuilds.

    Deliberately not asserting any particular wording -- that string belongs
    to the engine, which this layer does not own and must not pin in a TUI
    test. Asserting instead that whatever `report["activation"]` says survives
    the round trip, whatever its shape, is the mirror: a test pinned to today's
    wording would stay green even if `_models_write` started dropping the
    report and hardcoding its own text instead.
    """

    def _to_agent_row(self, navigator: Navigator) -> Navigator:
        rows = navigator.current.rows
        index = next(i for i, row in enumerate(rows) if row.agent == CONFIGURABLE_AGENT)
        for _ in range(index):
            navigator = navigator.handle(Action.MOVE_DOWN)
        return navigator.handle(Action.CHOOSE)

    def test_confirming_a_staged_plain_model_surfaces_the_engine_s_own_activation_notice(self):
        _write_catalog(self.home, ONE_PLAIN_MODEL)
        runtime = self.runtime()
        navigator = self.to_models_screen(runtime)
        navigator = self._to_agent_row(navigator)  # agent chosen
        navigator = navigator.handle(Action.CHOOSE)  # the one provider
        navigator = navigator.handle(Action.CHOOSE)  # the one, plain, model: stages, pure
        navigator = _to_confirm_row(navigator)
        navigator = session.step(navigator, runtime, Action.CHOOSE)  # applies the staged batch

        expected = cli.models_apply(
            CLI, [cli.ModelAssignmentSpec(agent="sdd-verify", model="anthropic/fast-model")], [], runtime
        )["activation"]
        self.assertIsInstance(navigator.current, ModelsScreen)
        self.assertEqual(navigator.current.activation, tuple(expected))
        self.assertTrue(navigator.current.activation)

    def test_confirming_a_staged_reasoning_model_with_an_effort_surfaces_the_notice(self):
        _write_catalog(self.home, ONE_REASONING_MODEL)
        runtime = self.runtime()
        navigator = self.to_models_screen(runtime)
        navigator = self._to_agent_row(navigator)
        navigator = navigator.handle(Action.CHOOSE)  # the one provider
        navigator = navigator.handle(Action.CHOOSE)  # the one, reasoning, model: only narrows
        navigator = navigator.handle(Action.CHOOSE)  # the first effort offered: stages, pure
        navigator = _to_confirm_row(navigator)
        navigator = session.step(navigator, runtime, Action.CHOOSE)

        expected = cli.models_apply(
            CLI, [cli.ModelAssignmentSpec(agent="sdd-verify", model="anthropic/deep-thinker", effort="low")], [], runtime
        )["activation"]
        self.assertIsInstance(navigator.current, ModelsScreen)
        self.assertEqual(navigator.current.activation, tuple(expected))

    def test_confirming_a_staged_removal_surfaces_the_notice_too(self):
        _write_catalog(self.home, ONE_PLAIN_MODEL)
        runtime = self.runtime()
        self.install(runtime)
        cli.models_set(CLI, [cli.ModelAssignmentSpec(agent=CONFIGURABLE_AGENT, model="anthropic/fast-model")], runtime)

        navigator = self.to_models_screen(runtime)
        index = next(i for i, row in enumerate(navigator.current.rows) if row.agent == CONFIGURABLE_AGENT)
        for _ in range(index):
            navigator = navigator.handle(Action.MOVE_DOWN)
        navigator = navigator.handle(Action.REMOVE)  # stages, pure
        navigator = _to_confirm_row(navigator)

        navigator = session.step(navigator, runtime, Action.CHOOSE)
        self.assertIsInstance(navigator.current, ModelsScreen)
        self.assertTrue(navigator.current.activation)

    def test_confirming_nothing_staged_is_a_no_op_that_asks_no_question(self):
        """Reaching Confirm with nothing staged must not call
        `cli.models_apply` at all -- there is nothing for it to apply."""
        _write_catalog(self.home, ONE_PLAIN_MODEL)
        runtime = self.runtime()
        navigator = self.to_models_screen(runtime)
        navigator = _to_confirm_row(navigator)

        with unittest.mock.patch.object(cli, "models_apply") as mocked:
            navigator = session.step(navigator, runtime, Action.CHOOSE)
        mocked.assert_not_called()
        self.assertIsInstance(navigator.current, ModelsScreen)
        self.assertEqual(navigator.current.activation, ())

    def test_a_failed_confirm_withholds_the_activation_notice(self):
        """The same discipline `_grant_mcp_write` already follows: a failure
        report carries no `activation` key at all (`cli.safe_report` never
        invents one), so a screen rebuilt after a failed Confirm must not
        claim the write landed by showing the notice anyway."""
        _write_catalog(self.home, ONE_PLAIN_MODEL)
        runtime = self.runtime()
        navigator = self.to_models_screen(runtime)
        navigator = self._to_agent_row(navigator)
        navigator = navigator.handle(Action.CHOOSE)  # the one provider
        navigator = navigator.handle(Action.CHOOSE)  # stages, pure
        navigator = _to_confirm_row(navigator)

        with unittest.mock.patch.object(cli, "models_apply", side_effect=cli.CommandError("boom")):
            navigator = session.step(navigator, runtime, Action.CHOOSE)  # confirms, but the write fails

        self.assertIsInstance(navigator.current, ModelsScreen)
        self.assertEqual(navigator.current.activation, ())


class NoCredentialReachesARenderedLineTest(ModelsScreenTestCase):
    """The same guarantee `model_catalog` already proves for itself, proven
    again at the screen level: nothing this screen renders may repeat a
    credential's own value, wherever in the walk it is shown."""

    SECRET = "top-secret-oauth-token"

    def test_a_credential_value_never_appears_in_a_rendered_line(self):
        _write_catalog(self.home, ONE_REASONING_MODEL)
        _write_credentials(self.home, {"anthropic": {"type": "oauth", "access": self.SECRET}})
        runtime = self.runtime()
        navigator = self.to_models_screen(runtime)
        self._assert_secret_free(navigator)

        navigator = self._to_agent_row(navigator)
        self._assert_secret_free(navigator)
        navigator = navigator.handle(Action.CHOOSE)  # the provider
        self._assert_secret_free(navigator)
        navigator = navigator.handle(Action.CHOOSE)  # the model: only narrows, it is a reasoning one
        self._assert_secret_free(navigator)

    def _to_agent_row(self, navigator: Navigator) -> Navigator:
        rows = navigator.current.rows
        index = next(i for i, row in enumerate(rows) if row.agent == CONFIGURABLE_AGENT)
        for _ in range(index):
            navigator = navigator.handle(Action.MOVE_DOWN)
        return navigator.handle(Action.CHOOSE)

    def _assert_secret_free(self, navigator: Navigator) -> None:
        lines = render(navigator.current, navigator.cursor)
        for line in lines:
            self.assertNotIn(self.SECRET, line.text)


if __name__ == "__main__":
    unittest.main()


class ConfirmationFitsOnAScreenTest(RealHomeTestCase):
    """A question with a hundred lines above it is a question nobody can see.

    `draw` clamps to the window, so a preface longer than the terminal pushes
    the answers off the bottom — and the one screen where that matters most is
    the one asking whether to remove everything.
    """

    def test_a_long_list_is_counted_rather_than_listed(self):
        lines = tuple(f"item {number}" for number in range(106))
        preface = session._summarised("About to remove", lines, "nothing")
        self.assertLessEqual(len(preface), session.SHOWN_AT_MOST + 2)
        self.assertIn("106", preface[0])
        self.assertIn("and 100 more", preface[-1])

    def test_a_short_list_is_shown_whole_without_a_tail(self):
        preface = session._summarised("About to remove", ("one", "two"), "nothing")
        self.assertEqual(preface, ("About to remove 2:", "  one", "  two"))

    def test_nothing_to_do_says_so_instead_of_counting_zero(self):
        self.assertEqual(session._summarised("About to remove", (), "Nothing recorded to remove."),
                         ("Nothing recorded to remove.",))
