"""`models set` / `unset` / `list`: the CLI surface for a per-agent preference.

Follows the same discipline as `test_cli.py`: real disk, a throwaway home, and
the double only where a real filesystem condition cannot be produced.
"""
from __future__ import annotations

import io
import json
import unittest
from dataclasses import replace
from pathlib import PurePosixPath
from unittest.mock import patch

from pegasus import cli
from pegasus.adapters import available
from pegasus.core import content as content_module
from pegasus.core import journal as journal_module
from pegasus.core.content import AgentMode, Agent, Content
from pegasus.core.types import Environment
from pegasus.infra.model_assignment_store_file import model_assignment_path
from real_home import RealHomeTestCase as _RealHomeTestCase

AT = "2026-08-14T00:00:00+00:00"
# Pinned to OpenCode, not "whichever adapter is registered first": this
# suite exercises capabilities (mcp, per_agent_model, subagents declared
# inside the settings file, ...) that only OpenCode declares today. Since
# Claude Code registered, "available().ids()[0]" resolves alphabetically
# to "claudecode" instead, which cannot support what this file tests.
CLI = "opencode"
CONFIGURABLE_AGENT = "sdd-apply"


class RealHomeTestCase(_RealHomeTestCase):
    def runtime(self) -> cli.Runtime:
        return cli.Runtime(filesystem=self.filesystem, home=self.home, now=AT, out=io.StringIO())

    def run_cli(self, *argv) -> tuple[int, dict]:
        context = self.runtime()
        code = cli.main([*argv, "--json"], runtime=context)
        return code, json.loads(context.out.getvalue())

    def layout(self):
        return available().get(CLI).layout(Environment(home=self.home))

    def present(self) -> None:
        self.layout().config_dir.mkdir(parents=True, exist_ok=True)

    def install(self, *extra) -> None:
        """A real installation to reapply.

        `models set` and `models unset` render what they record, so they
        refuse a CLI with nothing installed the same way `mcp grant` and
        `directory grant` already do -- every test below that expects one of
        them to succeed has to stand on an installation."""
        self.present()
        code, _ = self.run_cli("install", "--cli", CLI, *extra)
        self.assertEqual(code, 0)


class SetTest(RealHomeTestCase):
    def test_setting_a_configurable_agent_succeeds_and_reports_it(self):
        self.install()
        code, report = self.run_cli(
            "models", "set", "--cli", CLI, "--assign", f"{CONFIGURABLE_AGENT}=anthropic/claude-sonnet-5", "--effort", f"{CONFIGURABLE_AGENT}=high",
        )
        self.assertEqual(code, 0)
        self.assertEqual(report["action"], "set")
        self.assertEqual(report["cli"], CLI)
        self.assertEqual(
            report["assignments"],
            [{"agent": CONFIGURABLE_AGENT, "model": "anthropic/claude-sonnet-5", "effort": "high"}],
        )

    def test_setting_persists_to_the_store(self):
        self.install()
        self.run_cli(
            "models", "set", "--cli", CLI, "--assign", f"{CONFIGURABLE_AGENT}=anthropic/claude-sonnet-5",
        )
        loaded = cli.model_assignment_store(self.runtime()).load()
        from pegasus.core import model_assignments as model_assignments_module

        assignment = model_assignments_module.get(loaded, CLI, CONFIGURABLE_AGENT)
        self.assertIsNotNone(assignment)
        self.assertEqual(assignment.full_id, "anthropic/claude-sonnet-5")

    def test_an_unknown_agent_is_refused_with_a_clear_reason(self):
        code, report = self.run_cli(
            "models", "set", "--cli", CLI, "--assign", "nonexistent-agent=anthropic/claude-sonnet-5",
        )
        self.assertNotEqual(code, 0)
        self.assertEqual(report["status"], "failed")
        self.assertIn("nonexistent-agent", report["error"])
        self.assertFalse(model_assignment_path(self.filesystem, self.home).exists())

    def test_a_non_configurable_agent_is_refused_with_a_clear_reason(self):
        not_configurable = Agent(
            name="static-agent",
            description="an agent nothing ever lets configure a model",
            body="body",
            mode=AgentMode.SUBAGENT,
            source=PurePosixPath("agents/static-agent.md"),
            model_configurable=False,
        )
        with patch("pegasus.core.content.load", return_value=Content(agents=(not_configurable,))):
            code, report = self.run_cli(
                "models", "set", "--cli", CLI, "--assign", "static-agent=anthropic/claude-sonnet-5",
            )
        self.assertNotEqual(code, 0)
        self.assertEqual(report["status"], "failed")
        self.assertIn("static-agent", report["error"])
        self.assertFalse(model_assignment_path(self.filesystem, self.home).exists())

    def test_a_malformed_model_spec_is_refused(self):
        code, report = self.run_cli(
            "models", "set", "--cli", CLI, "--assign", f"{CONFIGURABLE_AGENT}=not-a-provider-slash-model",
        )
        self.assertNotEqual(code, 0)
        self.assertEqual(report["status"], "failed")


class UnsetTest(RealHomeTestCase):
    def test_unsetting_something_never_set_is_a_no_op_not_an_error(self):
        self.install()
        code, report = self.run_cli("models", "unset", "--cli", CLI, "--agent", CONFIGURABLE_AGENT)
        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "already-unset")

    def test_unsetting_a_set_assignment_removes_it(self):
        self.install()
        self.run_cli(
            "models", "set", "--cli", CLI, "--assign", f"{CONFIGURABLE_AGENT}=anthropic/claude-sonnet-5",
        )
        code, report = self.run_cli("models", "unset", "--cli", CLI, "--agent", CONFIGURABLE_AGENT)
        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "unset")

        from pegasus.core import model_assignments as model_assignments_module

        loaded = cli.model_assignment_store(self.runtime()).load()
        self.assertIsNone(model_assignments_module.get(loaded, CLI, CONFIGURABLE_AGENT))


class AppliesTest(RealHomeTestCase):
    """Recording an assignment and rendering it are one step, like every sibling.

    `mcp grant`, `mcp revoke` and `directory grant` all record a decision and
    reapply the configuration in the same command; `models set` and `models
    unset` used to record and then tell the person to reinstall. Everything
    below reads the rendered configuration back off real disk, because "the
    assignment reached the configuration" is a claim about the file OpenCode
    opens -- a return value saying so would only be a proxy for it.
    """

    AGENT = CONFIGURABLE_AGENT
    MODEL = "anthropic/claude-sonnet-5"
    #: A server the user administers under a key of their own. Its selection
    #: cannot be recovered from the rendered configuration (a binding writes
    #: no `/mcp/<id>` key), so it is exactly what an internal `install` that
    #: forgot to reconstruct the recorded selection would retire.
    BOUND = ("cbm", "codebase-memory-mcp")

    def install(self, *extra) -> None:
        """The base's own installation, plus the catalog that makes an
        assignment honourable at all."""
        self.write_models_catalog()
        super().install(*extra)

    def write_models_catalog(self) -> None:
        """What a machine with a reachable provider looks like, written the
        same way `tests/test_cli.py` writes one -- without it no assignment
        is ever honoured and every guard below would measure nothing."""
        path = self.home / ".cache" / "opencode" / "models.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {"anthropic": {"builtin": True, "models": {"claude-sonnet-5": {"tool_call": True, "reasoning": True}}}}
            ),
            encoding="utf-8",
        )

    def installed(self):
        return journal_module.install_for(cli.journal_store(self.runtime()).load(), CLI)

    def rendered_agent(self) -> dict:
        document = json.loads(self.layout().settings_file.read_text(encoding="utf-8"))
        return document["agent"][self.AGENT]

    def convention_path(self):
        return self.layout().skills_dir / content_module.mcp_convention_path(self.BOUND[0])

    def drop_mcp_bindings(self) -> None:
        """An install predating `mcp_bindings` (or one that otherwise lost
        it): a bound convention with no recorded key, the same fixture
        `tests/test_cli_update.py` and `tests/test_cli_mcp.py` already use."""
        store = cli.journal_store(self.runtime())
        journal = store.load()
        install = journal_module.install_for(journal, CLI)
        store.save(journal_module.with_install(journal, replace(install, mcp_bindings={})))

    def test_an_assignment_reaches_the_rendered_agent_with_no_further_command(self):
        self.install()
        code, _ = self.run_cli(
            "models", "set", "--cli", CLI, "--assign", f"{self.AGENT}={self.MODEL}", "--effort", f"{self.AGENT}=high",
        )
        self.assertEqual(code, 0)
        value = self.rendered_agent()
        self.assertEqual(value["model"], self.MODEL)
        self.assertEqual(value["variant"], "high")

    def test_removing_an_assignment_takes_it_back_out_of_the_rendered_agent(self):
        self.install()
        self.run_cli("models", "set", "--cli", CLI, "--assign", f"{self.AGENT}={self.MODEL}")
        self.assertEqual(self.rendered_agent()["model"], self.MODEL)
        code, _ = self.run_cli("models", "unset", "--cli", CLI, "--agent", self.AGENT)
        self.assertEqual(code, 0)
        self.assertNotIn("model", self.rendered_agent())

    def test_setting_against_a_cli_with_nothing_installed_is_refused_and_writes_nothing(self):
        self.present()
        self.write_models_catalog()
        code, report = self.run_cli(
            "models", "set", "--cli", CLI, "--assign", f"{self.AGENT}={self.MODEL}",
        )
        self.assertNotEqual(code, 0)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["error"], f"{CLI} has nothing installed; run install first")
        self.assertFalse(model_assignment_path(self.filesystem, self.home).exists())
        self.assertFalse(self.layout().settings_file.exists())

    def test_removing_against_a_cli_with_nothing_installed_is_refused_and_writes_nothing(self):
        self.present()
        self.write_models_catalog()
        code, report = self.run_cli("models", "unset", "--cli", CLI, "--agent", self.AGENT)
        self.assertNotEqual(code, 0)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["error"], f"{CLI} has nothing installed; run install first")
        self.assertFalse(model_assignment_path(self.filesystem, self.home).exists())
        self.assertFalse(self.layout().settings_file.exists())

    def test_a_bound_mcp_server_survives_an_assignment(self):
        """The regression that matters most: the internal `install` has to
        reconstruct the recorded selection, not drop it."""
        self.install("--mcp", "=".join(self.BOUND))
        self.assertTrue(self.convention_path().exists(), "the fixture never bound a server")
        code, _ = self.run_cli(
            "models", "set", "--cli", CLI, "--assign", f"{self.AGENT}={self.MODEL}",
        )
        self.assertEqual(code, 0)
        self.assertEqual(self.rendered_agent()["model"], self.MODEL)
        self.assertTrue(
            self.convention_path().exists(), "assigning a model retired the bound server's convention"
        )
        self.assertEqual(self.installed().mcp_bindings, {self.BOUND[0]: self.BOUND[1]})

    def test_a_bound_mcp_server_survives_a_removal(self):
        self.install("--mcp", "=".join(self.BOUND))
        self.run_cli("models", "set", "--cli", CLI, "--assign", f"{self.AGENT}={self.MODEL}")
        # Or the removal below would have nothing to take back out and this
        # would approve a configuration that never carried the model at all.
        self.assertEqual(self.rendered_agent()["model"], self.MODEL)
        code, _ = self.run_cli("models", "unset", "--cli", CLI, "--agent", self.AGENT)
        self.assertEqual(code, 0)
        self.assertNotIn("model", self.rendered_agent())
        self.assertTrue(
            self.convention_path().exists(), "removing an assignment retired the bound server's convention"
        )
        self.assertEqual(self.installed().mcp_bindings, {self.BOUND[0]: self.BOUND[1]})

    def test_an_unresolved_binding_is_refused_the_way_its_siblings_refuse_it(self):
        self.install("--mcp", "=".join(self.BOUND))
        self.drop_mcp_bindings()
        code, report = self.run_cli(
            "models", "set", "--cli", CLI, "--assign", f"{self.AGENT}={self.MODEL}",
        )
        self.assertNotEqual(code, 0)
        self.assertEqual(
            report["error"],
            cli.unresolved_bindings_message(
                CLI, [self.BOUND[0]], program_name=cli.default_identity().program_name
            ),
        )
        self.assertFalse(model_assignment_path(self.filesystem, self.home).exists())

    def test_what_is_left_to_do_is_the_adapters_own_activation_step(self):
        """The old note said the installation did not carry the assignment
        yet and told the person to reinstall. It carries it now, so the only
        step left is the one every other write already reports."""
        self.install()
        code, report = self.run_cli(
            "models", "set", "--cli", CLI, "--assign", f"{self.AGENT}={self.MODEL}",
        )
        self.assertEqual(code, 0)
        self.assertEqual(tuple(report["activation"]), available().get(CLI).activation_steps())


class ListTest(RealHomeTestCase):
    def test_no_agent_starts_with_an_assignment(self):
        code, report = self.run_cli("models", "list")
        self.assertEqual(code, 0)
        self.assertEqual(report["assignments"], [])

    def test_listing_shows_what_was_set(self):
        self.install()
        self.run_cli(
            "models", "set", "--cli", CLI, "--assign", f"{CONFIGURABLE_AGENT}=anthropic/claude-sonnet-5",
        )
        code, report = self.run_cli("models", "list")
        self.assertEqual(code, 0)
        self.assertEqual(len(report["assignments"]), 1)
        self.assertEqual(report["assignments"][0]["agent"], CONFIGURABLE_AGENT)

    def test_listing_can_be_narrowed_to_one_cli(self):
        code, report = self.run_cli("models", "list", "--cli", CLI)
        self.assertEqual(code, 0)
        self.assertEqual(report["assignments"], [])

    def test_listing_with_an_unknown_cli_is_refused(self):
        code, report = self.run_cli("models", "list", "--cli", "nonesuch")
        self.assertNotEqual(code, 0)
        self.assertEqual(report["status"], "failed")


class CapabilityRefusalTest(RealHomeTestCase):
    """`models set`/`unset`/`list` refuse outright against any adapter that
    never declared `per_agent_model` -- derived from `available()` itself,
    never a hardcoded adapter id, so a third adapter without the capability
    is covered the day it registers, the same way this suite already pins
    its *positive* fixture (`CLI = "opencode"`) rather than assuming which
    adapter comes first.

    `_resolve_model_overrides` already asks this question in the render
    path and returns `{}` silently when the capability is absent -- so a
    preference recorded through `models set` against such an adapter is
    accepted, remembered, and reported back by `models list`, yet never
    reaches any agent's file. Refusing on all three command surfaces is the
    fix: with `set` blocked no such preference can exist, so `list` has
    nothing false left to report.
    """

    NO_PER_AGENT_MODEL = tuple(
        cli_id
        for cli_id in available().ids()
        if not available().get(cli_id).capabilities().declares(cli.Capability.PER_AGENT_MODEL)
    )

    def install_cli(self, cli_id: str) -> None:
        """A real installation of `cli_id`, so the refusal under test is the
        capability refusal itself, never the unrelated "nothing installed"
        refusal that `models set`/`unset` would otherwise hit first and that
        would make this sweep pass for the wrong reason."""
        layout = available().get(cli_id).layout(Environment(home=self.home))
        layout.config_dir.mkdir(parents=True, exist_ok=True)
        code, report = self.run_cli("install", "--cli", cli_id)
        self.assertEqual(code, 0, f"fixture could not install {cli_id}: {report}")

    def test_every_adapter_without_the_capability_refuses_on_all_three_commands(self):
        self.assertTrue(self.NO_PER_AGENT_MODEL, "fixture assumption broken: no adapter lacks the capability")
        failures = []
        for cli_id in self.NO_PER_AGENT_MODEL:
            self.install_cli(cli_id)

            code, report = self.run_cli(
                "models", "set", "--cli", cli_id, "--assign", f"{CONFIGURABLE_AGENT}=anthropic/claude-sonnet-5",
            )
            if (
                code == 0
                or report.get("status") != "failed"
                or cli_id not in report.get("error", "")
                or "installed" in report.get("error", "")
            ):
                failures.append(f"{cli_id}: models set did not refuse on capability (code={code}, report={report})")

            code, report = self.run_cli("models", "unset", "--cli", cli_id, "--agent", CONFIGURABLE_AGENT)
            if (
                code == 0
                or report.get("status") != "failed"
                or cli_id not in report.get("error", "")
                or "installed" in report.get("error", "")
            ):
                failures.append(f"{cli_id}: models unset did not refuse on capability (code={code}, report={report})")

            code, report = self.run_cli("models", "list", "--cli", cli_id)
            if code == 0 or report.get("status") != "failed" or cli_id not in report.get("error", ""):
                failures.append(f"{cli_id}: models list did not refuse (code={code}, report={report})")

        self.assertFalse(failures, "\n".join(failures))

    def test_the_refusal_names_the_cli_and_says_why_in_the_tui_voice(self):
        """The reason must mean something to the person, never
        implementation-speak restating the boolean that gates it -- so this
        asserts against the one resolved sentence `cli.per_agent_model_reason`
        hands every surface, not a hand-picked substring that would still
        pass for a jargon-y rewrite of it."""
        cli_id = self.NO_PER_AGENT_MODEL[0]
        self.install_cli(cli_id)
        code, report = self.run_cli(
            "models", "set", "--cli", cli_id, "--assign", f"{CONFIGURABLE_AGENT}=anthropic/claude-sonnet-5",
        )
        self.assertNotEqual(code, 0)
        self.assertIn(cli_id, report["error"])
        self.assertIn(cli.per_agent_model_reason(available().get(cli_id)), report["error"])

    def test_the_refusal_is_not_implementation_speak(self):
        """The regression this pins: a reason like "never declared support
        for per-agent models" tells a developer something about the
        manifest, not a person something they can act on."""
        cli_id = self.NO_PER_AGENT_MODEL[0]
        self.install_cli(cli_id)
        code, report = self.run_cli(
            "models", "set", "--cli", cli_id, "--assign", f"{CONFIGURABLE_AGENT}=anthropic/claude-sonnet-5",
        )
        self.assertNotEqual(code, 0)
        self.assertNotIn("declared support", report["error"])
        self.assertNotIn("capability", report["error"])

    def test_the_refusal_is_checked_before_argument_validation(self):
        """A missing capability is not fixable by editing the rest of the
        command line -- correct every argument and the command still cannot
        do this here -- so it is checked ahead of a mistyped `--assign`, the
        same way `models_set`'s own docstring orders "nothing installed"
        ahead of a mistyped argument for the analogous reason."""
        cli_id = self.NO_PER_AGENT_MODEL[0]
        code, report = self.run_cli(
            "models", "set", "--cli", cli_id, "--assign", "nonexistent-agent=not-a-valid-spec",
        )
        self.assertNotEqual(code, 0)
        self.assertIn(cli_id, report["error"])
        self.assertNotIn("nonexistent-agent", report["error"])

    def test_setting_still_works_for_an_adapter_that_declares_the_capability(self):
        """The positive case this fix must not break -- already covered by
        `SetTest.test_setting_a_configurable_agent_succeeds_and_reports_it`
        above, exercised again here for locality with the refusal tests."""
        self.assertNotIn(CLI, self.NO_PER_AGENT_MODEL)
        self.install()
        code, report = self.run_cli(
            "models", "set", "--cli", CLI, "--assign", f"{CONFIGURABLE_AGENT}=anthropic/claude-sonnet-5",
        )
        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "set")


class HelpNamesCapableClisTest(unittest.TestCase):
    """`pegasus models --help` (and the same line in `pegasus --help`'s own
    subcommand listing) names exactly the CLIs whose adapter declares
    `per_agent_model` -- derived from `available()` itself, the same
    discipline `CapabilityRefusalTest` already follows, so a third adapter
    that gains or never declares the capability is named correctly the
    moment it registers, with nothing here to update by hand."""

    def _help_text(self, *argv: str) -> str:
        import contextlib

        buffer = io.StringIO()
        runtime = cli.Runtime(filesystem=None, home=None, now=AT, out=io.StringIO())
        with contextlib.redirect_stdout(buffer):
            with self.assertRaises(SystemExit):
                cli.main([*argv, "--help"], runtime=runtime)
        return buffer.getvalue()

    def _names(self, *, declares: bool) -> list[str]:
        registry = available()
        return [
            registry.get(cli_id).display_name
            for cli_id in registry.ids()
            if registry.manifest(cli_id).declares(cli.Capability.PER_AGENT_MODEL) is declares
        ]

    def test_the_top_level_listing_names_every_capable_cli(self):
        text = self._help_text()
        for name in self._names(declares=True):
            self.assertIn(name, text)

    def test_the_top_level_listing_never_names_an_incapable_cli(self):
        text = self._help_text()
        for name in self._names(declares=False):
            self.assertNotIn(name, text)

    def test_models_own_help_repeats_the_same_names(self):
        text = self._help_text("models")
        for name in self._names(declares=True):
            self.assertIn(name, text)
        for name in self._names(declares=False):
            self.assertNotIn(name, text)

    def test_each_subcommands_own_help_repeats_the_same_names(self):
        """`models set`/`unset`/`list` each build their own help text from
        `cli._per_agent_model_suffix`, the same derived helper `models
        --help` itself uses -- so a person who runs `pegasus models set
        --help` directly, without ever seeing the parent's, still learns
        which CLI it is for."""
        for subcommand in ("set", "unset", "list"):
            text = self._help_text("models", subcommand)
            for name in self._names(declares=True):
                self.assertIn(name, text, f"{subcommand} --help does not name {name!r}")
            for name in self._names(declares=False):
                self.assertNotIn(name, text, f"{subcommand} --help names {name!r}, which lacks the capability")


class UnfilteredListingReportsPhantomEntriesTest(RealHomeTestCase):
    """`models list` without `--cli` must not report an assignment held for
    a CLI that never declared `per_agent_model` as if it were in effect.

    Reproduces the adversarial finding directly: a phantom entry written
    straight into the assignment store, as an earlier release (before
    `f0771bc`'s guard existed) could have left behind, naming a CLI
    (`claudecode`) that has no `per_agent_model` capability at all. The
    filtered path (`--cli claudecode`) already refuses; this covers the
    unfiltered path, which must not let that refusal be bypassed just by
    omitting `--cli`.
    """

    PHANTOM_CLI = "claudecode"

    def write_phantom_entry(self) -> None:
        from pegasus.core import model_assignments as model_assignments_module
        from pegasus.core.types import ModelAssignment

        store = cli.model_assignment_store(self.runtime())
        assignments = model_assignments_module.with_assignment(
            store.load(),
            self.PHANTOM_CLI,
            CONFIGURABLE_AGENT,
            ModelAssignment.parse("anthropic/claude-sonnet-5"),
        )
        store.save(assignments)

    def test_unfiltered_listing_does_not_report_the_phantom_entry_as_in_effect(self):
        self.write_phantom_entry()
        code, report = self.run_cli("models", "list")
        self.assertEqual(code, 0)
        phantom = [
            entry for entry in report["assignments"] if entry["cli"] == self.PHANTOM_CLI and entry["agent"] == CONFIGURABLE_AGENT
        ]
        self.assertTrue(phantom, "the phantom entry vanished instead of being reported as inert")
        self.assertFalse(
            phantom[0].get("in_effect", True),
            f"the phantom entry was reported without any marker that it is not in effect: {phantom[0]}",
        )

    def test_filtered_listing_still_refuses(self):
        self.write_phantom_entry()
        code, report = self.run_cli("models", "list", "--cli", self.PHANTOM_CLI)
        self.assertNotEqual(code, 0)
        self.assertEqual(report["status"], "failed")


class ModelsApplyGuardTest(RealHomeTestCase):
    """`models_apply` is the function that writes to the store -- unlike
    `set`/`unset`/`list`, it never called `_require_per_agent_model` at all.
    Called directly, as any future caller (script, plugin, TUI refactor,
    test) might, it must refuse before writing anything, exactly like its
    siblings.
    """

    def test_models_apply_refuses_for_a_cli_without_the_capability(self):
        ModelAssignmentSpec = cli.ModelAssignmentSpec

        cli_id = "claudecode"
        self.assertFalse(
            available().get(cli_id).capabilities().declares(cli.Capability.PER_AGENT_MODEL)
        )
        layout = available().get(cli_id).layout(Environment(home=self.home))
        layout.config_dir.mkdir(parents=True, exist_ok=True)
        code, report = self.run_cli("install", "--cli", cli_id)
        self.assertEqual(code, 0)

        spec = ModelAssignmentSpec(agent=CONFIGURABLE_AGENT, model="anthropic/claude-sonnet-5", effort=None)
        runtime = self.runtime()
        with self.assertRaises(cli.CommandError) as context:
            cli.models_apply(cli_id, [spec], [], runtime)
        self.assertIn(cli_id, str(context.exception))

        loaded = cli.model_assignment_store(runtime).load()
        from pegasus.core import model_assignments as model_assignments_module

        self.assertIsNone(model_assignments_module.get(loaded, cli_id, CONFIGURABLE_AGENT))


class CapabilityCheckedBeforeArgumentParsingTest(RealHomeTestCase):
    """`models_set`'s own docstring, and `_require_per_agent_model`'s,
    state that the capability refusal runs ahead of *every* argument
    check -- but `_models`'s dispatcher builds the `ModelAssignmentSpec`
    list, via `_model_assignment_specs`, *before* calling `models_set` at
    all. Any shape error `_model_assignment_specs` raises therefore wins
    the race against a capability that was never there to begin with,
    which is exactly backwards from what the docstrings promise.

    Each of these four inputs was demonstrated, against `--cli claudecode`,
    to raise its own argument-shape error instead of the capability
    refusal.
    """

    CLI_ID = "claudecode"

    def test_duplicate_assign_is_still_refused_on_capability(self):
        code, report = self.run_cli(
            "models", "set", "--cli", self.CLI_ID,
            "--assign", f"{CONFIGURABLE_AGENT}=anthropic/claude-sonnet-5",
            "--assign", f"{CONFIGURABLE_AGENT}=anthropic/claude-haiku",
        )
        self.assertNotEqual(code, 0)
        self.assertIn(self.CLI_ID, report["error"])
        self.assertNotIn("more than once", report["error"])

    def test_malformed_assign_is_still_refused_on_capability(self):
        code, report = self.run_cli(
            "models", "set", "--cli", self.CLI_ID,
            "--assign", "sdd-apply-sin-igual",
        )
        self.assertNotEqual(code, 0)
        self.assertIn(self.CLI_ID, report["error"])
        self.assertNotIn("AGENT=PROVIDER/MODEL", report["error"])

    def test_orphan_effort_is_still_refused_on_capability(self):
        code, report = self.run_cli(
            "models", "set", "--cli", self.CLI_ID,
            "--assign", f"{CONFIGURABLE_AGENT}=anthropic/claude-sonnet-5",
            "--effort", "otro-agente=high",
        )
        self.assertNotEqual(code, 0)
        self.assertIn(self.CLI_ID, report["error"])
        self.assertNotIn("otro-agente", report["error"])

    def test_duplicate_effort_is_still_refused_on_capability(self):
        code, report = self.run_cli(
            "models", "set", "--cli", self.CLI_ID,
            "--assign", f"{CONFIGURABLE_AGENT}=anthropic/claude-sonnet-5",
            "--effort", f"{CONFIGURABLE_AGENT}=high",
            "--effort", f"{CONFIGURABLE_AGENT}=low",
        )
        self.assertNotEqual(code, 0)
        self.assertIn(self.CLI_ID, report["error"])
        self.assertNotIn("more than once", report["error"])


class ProseTest(RealHomeTestCase):
    def test_set_reads_as_prose(self):
        self.install()
        context = self.runtime()
        cli.main(
            ["models", "set", "--cli", CLI, "--assign", f"{CONFIGURABLE_AGENT}=anthropic/claude-sonnet-5"],
            runtime=context,
        )
        self.assertIn(CONFIGURABLE_AGENT, context.out.getvalue())

    def test_missing_subcommand_is_an_error(self):
        code, report = self.run_cli("models")
        self.assertNotEqual(code, 0)
        self.assertEqual(report["status"], "failed")


if __name__ == "__main__":
    unittest.main()
