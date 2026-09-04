"""What a screen looks like, as plain text lines rather than pixels on a
terminal — so the drawing layer never has to decide anything, only copy these
lines onto a window."""
from __future__ import annotations

import unittest

from pegasus import cli
from pegasus.tui.navigator import (
    PEGASUS_PROGRAM,
    AgentRow,
    CliOption,
    Entry,
    GrantMcpOption,
    GrantMcpResultScreen,
    GrantMcpScreen,
    InstallPlanScreen,
    InstallResultScreen,
    McpOption,
    McpSelectionScreen,
    Menu,
    ModelOption,
    ModelsScreen,
    Placeholder,
    ProviderOption,
    QUIT,
    RestoreResultScreen,
    StatusScreen,
    UninstallResultScreen,
)
from pegasus.tui import view, wordmark
from pegasus.tui.view import Line, Span, Style, render, render_busy, render_progress

SAMPLE = CliOption(id="demo", display_name="Demo CLI", config_dir="/home/x/.demo", tier="full")
DOCTOR_REPORT = {
    "schema": cli.SCHEMA,
    "command": "doctor",
    "pegasus_version": "4.0.0",
    "clis": [
        {
            "cli": "demo",
            "display_name": "Demo CLI",
            "tier": "full",
            "detected": True,
            "config_dir": "/x/.demo",
            "pegasus_installed": True,
            "artifacts": 3,
            "drifted": ["a"],
            "missing": ["b"],
            "unreadable": ["c"],
            "activation": [],
        }
    ],
}
UNINSTALLED_REPORT = {
    "schema": cli.SCHEMA, "command": "uninstall", "cli": "demo", "status": "uninstalled",
    "activation": [], "removed": ["/x/a"], "unaccounted": [], "kept_links": [],
}
UNINSTALL_FAILED_REPORT = {
    "schema": cli.SCHEMA, "command": "uninstall", "status": "failed", "error": "permission denied",
}
RESTORED_REPORT = {
    "schema": cli.SCHEMA, "command": "restore", "status": "restored", "generation": 2,
    "written": ["/x/a"], "removed": [],
}
RESTORE_FAILED_REPORT = {
    "schema": cli.SCHEMA, "command": "restore", "status": "failed", "error": "generation 2 cannot be restored",
}
PLANNED_REPORT = {
    "schema": cli.SCHEMA, "command": "install", "cli": "demo", "status": "planned", "activation": [],
    "created": [{"id": "a", "target": "/x/a"}], "updated": [], "unchanged": [], "skipped": [], "retired": [],
}
INSTALLED_REPORT = {**PLANNED_REPORT, "status": "installed", "placed": 1, "unaccounted": [], "journal": "/x/j"}
FAILED_REPORT = {
    "schema": cli.SCHEMA, "command": "install", "status": "failed", "error": "disk is full", "rolled_back": True,
}
UPDATE_PLANNED_REPORT = {**PLANNED_REPORT, "command": "update"}
UPDATED_REPORT = {**INSTALLED_REPORT, "command": "update"}
MULTI_LINE_ERROR = (
    "demo has bound mcp server(s) x whose server key was never recorded (an install made before this was "
    "tracked); update cannot reapply them without guessing, and guessing would retire the very binding it "
    "exists to preserve. Run this once instead:\n"
    "  pegasus install --cli demo --mcp x=<key>\n"
    "After that one run, update needs no flags ever again. doctor lists the bound ids; the keys themselves "
    "live in the CLI's own configuration."
)
UPDATE_UNRESOLVED_BINDINGS_REPORT = {
    "schema": cli.SCHEMA, "command": "update", "status": "failed", "error": MULTI_LINE_ERROR,
}
UPGRADE_PLANNED_REPORT = {
    "schema": cli.SCHEMA, "command": "upgrade", "status": "planned",
    "old_version": "5.10.0", "new_version": "5.11.0", "destination": "/opt/pegasus/pegasus",
    "restart_required": True,
}
UPGRADED_REPORT = {
    "schema": cli.SCHEMA, "command": "upgrade", "status": "upgraded",
    "old_version": "5.10.0", "new_version": "5.11.0", "destination": "/opt/pegasus/pegasus",
    "restart_required": True,
}
UPGRADE_FAILED_REPORT = {
    "schema": cli.SCHEMA, "command": "upgrade", "status": "failed", "error": "5.10.0 is not writable",
}
UPGRADE_ALREADY_CURRENT_REPORT = {
    "schema": cli.SCHEMA, "command": "upgrade", "status": "already-current",
    "version": "5.11.0", "destination": "/opt/pegasus/pegasus",
}


class MenuRenderingTest(unittest.TestCase):
    def menu(self) -> Menu:
        return Menu(
            title="Pegasus Harness",
            entries=(
                Entry("Install", Placeholder("Install", "not built")),
                Entry("Exit", QUIT),
            ),
        )

    def test_the_first_line_is_the_title(self):
        lines = render(self.menu(), cursor=0)
        self.assertEqual(lines[0].text, "Pegasus Harness")

    def test_the_selected_entry_carries_the_documented_pointer(self):
        lines = render(self.menu(), cursor=0)
        entry_lines = [line.text for line in lines if "Install" in line.text or "Exit" in line.text]
        self.assertEqual(entry_lines[0], "  ▸ Install")

    def test_an_unselected_entry_is_indented_to_the_same_width_as_the_pointer(self):
        lines = render(self.menu(), cursor=0)
        entry_lines = [line.text for line in lines if "Install" in line.text or "Exit" in line.text]
        self.assertEqual(entry_lines[1], "    Exit")

    def test_moving_the_cursor_moves_which_line_is_highlighted(self):
        lines = render(self.menu(), cursor=1)
        highlighted = [line.text for line in lines if line.highlighted]
        self.assertEqual(highlighted, ["  ▸ Exit"])

    def test_exactly_one_line_is_highlighted(self):
        lines = render(self.menu(), cursor=0)
        self.assertEqual(sum(1 for line in lines if line.highlighted), 1)


class MenuPrefaceRenderingTest(unittest.TestCase):
    def test_preface_lines_appear_between_the_title_and_the_entries(self):
        menu = Menu(title="Confirm?", preface=("About to remove:", "  a → /x/a"), entries=(Entry("Cancel", QUIT),))
        lines = [line.text for line in render(menu, cursor=0)]
        self.assertEqual(lines[0], "Confirm?")
        self.assertIn("About to remove:", lines)
        self.assertIn("  a → /x/a", lines)
        self.assertLess(lines.index("  a → /x/a"), lines.index("  ▸ Cancel"))

    def test_no_preface_adds_no_extra_lines(self):
        with_preface = Menu(title="t", preface=(), entries=(Entry("a", QUIT),))
        without_preface = Menu(title="t", entries=(Entry("a", QUIT),))
        self.assertEqual(render(with_preface, cursor=0), render(without_preface, cursor=0))


class StatusScreenRenderingTest(unittest.TestCase):
    def test_it_carries_the_exact_prose_the_flags_would_print(self):
        lines = [line.text for line in render(StatusScreen(report=DOCTOR_REPORT), cursor=0)]
        for expected in cli.prose_for(DOCTOR_REPORT).splitlines():
            self.assertTrue(any(expected in text for text in lines), expected)

    def test_missing_and_unreadable_are_named_and_kept_apart(self):
        prose = cli.prose_for(DOCTOR_REPORT)
        self.assertIn("missing: b", prose)
        self.assertIn("could not be checked: c", prose)
        self.assertNotIn("missing: c", prose)
        self.assertNotIn("could not be checked: b", prose)


class PlaceholderRenderingTest(unittest.TestCase):
    def test_a_placeholder_shows_its_title_and_its_note(self):
        screen = Placeholder("Install", "This screen has not been built yet.")
        lines = [line.text for line in render(screen, cursor=0)]
        self.assertIn("Install", lines)
        self.assertIn("This screen has not been built yet.", lines)

    def test_a_placeholder_names_no_line_as_highlighted(self):
        screen = Placeholder("Install", "This screen has not been built yet.")
        lines = render(screen, cursor=0)
        self.assertFalse(any(line.highlighted for line in lines))


class InstallPlanRenderingTest(unittest.TestCase):
    def test_it_says_nothing_has_been_written_yet(self):
        lines = [line.text for line in render(InstallPlanScreen(cli=SAMPLE, report=PLANNED_REPORT), cursor=0)]
        self.assertIn("PREVIEW — nothing has been written yet.", lines)

    def test_it_carries_the_exact_prose_the_flags_would_print(self):
        lines = [line.text for line in render(InstallPlanScreen(cli=SAMPLE, report=PLANNED_REPORT), cursor=0)]
        for expected in cli.prose_for(PLANNED_REPORT).splitlines():
            self.assertIn(expected, lines)


MCP_OPTIONS = (
    McpOption(id="cbm", description="Knowledge graph of the codebase"),
    McpOption(id="context7", description="Up-to-date third-party docs"),
)


class McpSelectionRenderingTest(unittest.TestCase):
    def screen(self, **overrides) -> McpSelectionScreen:
        fields = {"cli": SAMPLE, "options": MCP_OPTIONS, "chosen": ()}
        fields.update(overrides)
        return McpSelectionScreen(**fields)

    def test_every_server_shows_its_own_description(self):
        lines = [line.text for line in render(self.screen(), cursor=0)]
        self.assertTrue(any("cbm" in text and "Knowledge graph" in text for text in lines))
        self.assertTrue(any("context7" in text and "third-party docs" in text for text in lines))

    def test_a_checked_server_is_marked_and_an_unchecked_one_is_not(self):
        lines = [line.text for line in render(self.screen(chosen=("cbm",)), cursor=0)]
        cbm_line = next(text for text in lines if "cbm" in text)
        context7_line = next(text for text in lines if "context7" in text)
        self.assertIn("[x]", cbm_line)
        self.assertIn("[ ]", context7_line)

    def test_a_continue_row_follows_the_last_server(self):
        lines = [line.text for line in render(self.screen(), cursor=0)]
        self.assertTrue(any("Continue" in text for text in lines))

    def test_the_continue_row_can_be_highlighted_like_any_other(self):
        lines = render(self.screen(), cursor=len(MCP_OPTIONS))
        highlighted = [line.text for line in lines if line.highlighted]
        self.assertEqual(len(highlighted), 1)
        self.assertIn("Continue", highlighted[0])

    def test_exactly_one_line_is_highlighted(self):
        lines = render(self.screen(), cursor=0)
        self.assertEqual(sum(1 for line in lines if line.highlighted), 1)

    def test_the_footer_names_both_ways_to_toggle(self):
        lines = [line.text for line in render(self.screen(), cursor=0)]
        self.assertIn("enter/space: toggle a server, or continue · esc: back", lines)


GRANT_OPTIONS = (
    GrantMcpOption(id="figma"),
    GrantMcpOption(id="jira"),
)


class GrantMcpRenderingTest(unittest.TestCase):
    """`GrantMcpScreen`'s own rendering: a checklist of bare keys, unlike
    `McpSelectionScreen`'s own rows, which each carry a shipped description
    this screen's servers never have (see `GrantMcpOption`'s docstring)."""

    def screen(self, **overrides) -> GrantMcpScreen:
        fields = {"cli": SAMPLE, "options": GRANT_OPTIONS, "chosen": (), "granted": ()}
        fields.update(overrides)
        return GrantMcpScreen(**fields)

    def test_every_server_shows_its_own_key(self):
        lines = [line.text for line in render(self.screen(), cursor=0)]
        self.assertTrue(any("figma" in text for text in lines))
        self.assertTrue(any("jira" in text for text in lines))

    def test_a_granted_server_is_marked_and_an_ungranted_one_is_not(self):
        lines = [line.text for line in render(self.screen(chosen=("figma",)), cursor=0)]
        figma_line = next(text for text in lines if "figma" in text)
        jira_line = next(text for text in lines if "jira" in text)
        self.assertIn("[x]", figma_line)
        self.assertIn("[ ]", jira_line)

    def test_a_continue_row_follows_the_last_server(self):
        lines = [line.text for line in render(self.screen(), cursor=0)]
        self.assertTrue(any("Continue" in text for text in lines))

    def test_the_continue_row_can_be_highlighted_like_any_other(self):
        lines = render(self.screen(), cursor=len(GRANT_OPTIONS))
        highlighted = [line.text for line in lines if line.highlighted]
        self.assertEqual(len(highlighted), 1)
        self.assertIn("Continue", highlighted[0])


class GrantMcpEmptyRenderingTest(unittest.TestCase):
    """The empty case: a placeholder that explains the actual flow rather
    than one that reads as broken."""

    def test_the_placeholder_explains_installing_it_yourself_first(self):
        screen = Placeholder(
            f"Grant MCP servers · {SAMPLE.display_name}",
            "No MCP server of your own was found here. This screen grants access to a server "
            "you install and administer yourself, outside Pegasus -- it does not install one. "
            f"Add a server under {SAMPLE.display_name}'s own mcp configuration the way you always "
            "would, then come back to this screen to grant it to every agent.",
        )
        lines = [line.text for line in render(screen, cursor=0)]
        joined = " ".join(lines)
        self.assertIn("install", joined.lower())
        self.assertIn("grant", joined.lower())
        self.assertIn(SAMPLE.display_name, joined)


class GrantMcpResultRenderingTest(unittest.TestCase):
    def test_it_names_what_was_granted_and_revoked(self):
        screen = GrantMcpResultScreen(cli=SAMPLE, granted=("jira",), revoked=("figma",), activation=("Restart it.",))
        lines = [line.text for line in render(screen, cursor=0)]
        self.assertTrue(any("jira" in text for text in lines))
        self.assertTrue(any("figma" in text for text in lines))
        self.assertIn("Restart it.", lines)

    def test_no_change_says_so(self):
        screen = GrantMcpResultScreen(cli=SAMPLE)
        lines = [line.text for line in render(screen, cursor=0)]
        self.assertIn("Nothing changed.", lines)

    def test_a_failure_uses_the_failed_banner_and_names_the_error(self):
        screen = GrantMcpResultScreen(cli=SAMPLE, errors=("could not grant 'jira'",))
        lines = [line.text for line in render(screen, cursor=0)]
        self.assertIn(view.GRANT_MCP_FAILED_BANNER, lines)
        self.assertIn("could not grant 'jira'", lines)

    def test_a_success_uses_the_success_banner(self):
        screen = GrantMcpResultScreen(cli=SAMPLE, granted=("jira",))
        lines = [line.text for line in render(screen, cursor=0)]
        self.assertIn(view.GRANT_MCP_BANNER, lines)


class InstallResultRenderingTest(unittest.TestCase):
    def test_a_successful_install_says_so_unmistakably(self):
        lines = [line.text for line in render(InstallResultScreen(cli=SAMPLE, report=INSTALLED_REPORT), cursor=0)]
        self.assertIn("INSTALLED.", lines)
        self.assertNotIn("PREVIEW — nothing has been written yet.", lines)

    def test_a_failed_install_says_so_and_carries_no_traceback(self):
        lines = [line.text for line in render(InstallResultScreen(cli=SAMPLE, report=FAILED_REPORT), cursor=0)]
        self.assertIn("Install didn't succeed.", lines)
        self.assertTrue(any("disk is full" in text for text in lines))
        self.assertFalse(any("Traceback" in text for text in lines))

    def test_it_carries_the_exact_prose_the_flags_would_print(self):
        lines = [line.text for line in render(InstallResultScreen(cli=SAMPLE, report=INSTALLED_REPORT), cursor=0)]
        for expected in cli.prose_for(INSTALLED_REPORT).splitlines():
            self.assertIn(expected, lines)


class UpdatePlanRenderingTest(unittest.TestCase):
    """`InstallPlanScreen` with `command="update"`: the same preview screen,
    worded for the flow it is actually previewing."""

    def test_the_title_and_footer_name_update_not_install(self):
        screen = InstallPlanScreen(cli=SAMPLE, report=UPDATE_PLANNED_REPORT, command="update")
        lines = [line.text for line in render(screen, cursor=0)]
        self.assertIn(f"Update · {SAMPLE.display_name}", lines)
        self.assertIn("enter: update now · esc: back, nothing written", lines)
        self.assertFalse(any("Install ·" in text for text in lines))

    def test_it_still_says_nothing_has_been_written_yet(self):
        screen = InstallPlanScreen(cli=SAMPLE, report=UPDATE_PLANNED_REPORT, command="update")
        lines = [line.text for line in render(screen, cursor=0)]
        self.assertIn("PREVIEW — nothing has been written yet.", lines)


class UpdateResultRenderingTest(unittest.TestCase):
    """`InstallResultScreen` with `command="update"`: same shape as an
    install result, its own banners and title."""

    def test_a_successful_update_says_so_unmistakably(self):
        screen = InstallResultScreen(cli=SAMPLE, report=UPDATED_REPORT, command="update")
        lines = [line.text for line in render(screen, cursor=0)]
        self.assertIn(f"Update · {SAMPLE.display_name}", lines)
        self.assertIn("UPDATED.", lines)
        self.assertNotIn("INSTALLED.", lines)

    def test_a_failed_update_says_so_and_carries_no_traceback(self):
        report = {**FAILED_REPORT, "command": "update"}
        screen = InstallResultScreen(cli=SAMPLE, report=report, command="update")
        lines = [line.text for line in render(screen, cursor=0)]
        self.assertIn("Update didn't succeed.", lines)
        self.assertNotIn("Install didn't succeed.", lines)
        self.assertFalse(any("Traceback" in text for text in lines))

    def test_the_multi_line_unresolved_bindings_refusal_is_not_flattened_to_one_line(self):
        """`update`'s refusal for an install with unrecorded mcp binding keys
        is several lines long -- the command to run, and why. Each embedded
        newline in the report's own `error` string must become its own
        `Line`, not one giant row that gets clipped by `draw`'s own window
        width the way a single overlong line would be."""
        screen = InstallResultScreen(cli=SAMPLE, report=UPDATE_UNRESOLVED_BINDINGS_REPORT, command="update")
        lines = [line.text for line in render(screen, cursor=0)]
        self.assertIn("Update didn't succeed.", lines)
        prose = cli.prose_for(UPDATE_UNRESOLVED_BINDINGS_REPORT)
        for expected in prose.splitlines():
            self.assertIn(expected, lines, f"line {expected!r} was flattened into a longer one")
        # And no rendered line is the whole multi-line message glued together.
        self.assertFalse(any("\n" in text for text in lines))
        self.assertIn("pegasus install --cli demo --mcp x=<key>", "\n".join(lines))


class UpgradePlanRenderingTest(unittest.TestCase):
    """`InstallPlanScreen` with `command="upgrade"`: the preview `pegasus
    upgrade --dry-run` would report, worded for its own flow rather than
    borrowing Install's or Update's."""

    def test_the_title_and_footer_name_upgrade_not_install_or_update(self):
        screen = InstallPlanScreen(cli=PEGASUS_PROGRAM, report=UPGRADE_PLANNED_REPORT, command="upgrade")
        lines = [line.text for line in render(screen, cursor=0)]
        self.assertIn(f"Upgrade · {PEGASUS_PROGRAM.display_name}", lines)
        self.assertIn("enter: upgrade now · esc: back, nothing written", lines)
        self.assertFalse(any("Install ·" in text or "Update ·" in text for text in lines))

    def test_it_still_says_nothing_has_been_written_yet(self):
        screen = InstallPlanScreen(cli=PEGASUS_PROGRAM, report=UPGRADE_PLANNED_REPORT, command="upgrade")
        lines = [line.text for line in render(screen, cursor=0)]
        self.assertIn("PREVIEW — nothing has been written yet.", lines)

    def test_it_carries_the_exact_prose_the_flag_would_print(self):
        screen = InstallPlanScreen(cli=PEGASUS_PROGRAM, report=UPGRADE_PLANNED_REPORT, command="upgrade")
        lines = [line.text for line in render(screen, cursor=0)]
        for expected in cli.prose_for(UPGRADE_PLANNED_REPORT).splitlines():
            self.assertIn(expected, lines)


class UpgradeResultRenderingTest(unittest.TestCase):
    """`InstallResultScreen` with `command="upgrade"`: says a restart is
    required and never claims the running process itself is now the new
    version -- it is still running the code it started with."""

    def test_a_successful_upgrade_says_so_and_names_a_restart(self):
        screen = InstallResultScreen(cli=PEGASUS_PROGRAM, report=UPGRADED_REPORT, command="upgrade")
        lines = [line.text for line in render(screen, cursor=0)]
        self.assertIn(f"Upgrade · {PEGASUS_PROGRAM.display_name}", lines)
        joined = "\n".join(lines)
        self.assertIn("restart", joined.lower())
        self.assertNotIn("INSTALLED.", lines)
        self.assertNotIn("UPDATED.", lines)

    def test_a_successful_upgrade_never_claims_this_process_is_now_the_new_version(self):
        """The process that reports success is still running the old code --
        `write_atomic`'s replace only changes what a *future* launch runs."""
        screen = InstallResultScreen(cli=PEGASUS_PROGRAM, report=UPGRADED_REPORT, command="upgrade")
        lines = [line.text for line in render(screen, cursor=0)]
        joined = "\n".join(lines)
        self.assertIn("5.10.0", joined)  # the old version this process is still running.
        self.assertIn("5.11.0", joined)  # the new version now on disk.

    def test_a_failed_upgrade_says_so_and_carries_no_traceback(self):
        screen = InstallResultScreen(cli=PEGASUS_PROGRAM, report=UPGRADE_FAILED_REPORT, command="upgrade")
        lines = [line.text for line in render(screen, cursor=0)]
        self.assertTrue(any("not writable" in text for text in lines))
        self.assertFalse(any("Traceback" in text for text in lines))
        self.assertNotIn("Install didn't succeed.", lines)
        self.assertNotIn("Update didn't succeed.", lines)

    def test_already_current_gets_its_own_banner_not_failed_or_upgraded(self):
        """Nothing happened, but nothing was asked to happen and did not --
        this is neither the failure banner nor the one that celebrates a
        completed install."""
        screen = InstallResultScreen(cli=PEGASUS_PROGRAM, report=UPGRADE_ALREADY_CURRENT_REPORT, command="upgrade")
        lines = [line.text for line in render(screen, cursor=0)]
        self.assertNotIn("UPGRADE FAILED.", lines)
        self.assertFalse(any("UPGRADED" in text for text in lines))
        self.assertTrue(any("already" in text.lower() and "up to date" in text.lower() for text in lines))

    def test_already_current_does_not_draw_the_success_wordmark(self):
        """The wordmark celebrates a completed install; nothing happened
        here, so it must not appear even when there is ample width for it."""
        screen = InstallResultScreen(cli=PEGASUS_PROGRAM, report=UPGRADE_ALREADY_CURRENT_REPORT, command="upgrade")
        lines = [line.text for line in render(screen, cursor=0, width=200)]
        self.assertNotIn(wordmark.wordmark_rows()[0], lines)
        self.assertNotIn(wordmark.pegasus_rows()[0], lines)

    def test_already_current_carries_the_exact_prose_the_flag_would_print(self):
        screen = InstallResultScreen(cli=PEGASUS_PROGRAM, report=UPGRADE_ALREADY_CURRENT_REPORT, command="upgrade")
        lines = [line.text for line in render(screen, cursor=0)]
        for expected in cli.prose_for(UPGRADE_ALREADY_CURRENT_REPORT).splitlines():
            self.assertIn(expected, lines)


class UninstallResultRenderingTest(unittest.TestCase):
    def test_a_successful_uninstall_says_so_unmistakably(self):
        lines = [line.text for line in render(UninstallResultScreen(cli=SAMPLE, report=UNINSTALLED_REPORT), cursor=0)]
        self.assertIn("UNINSTALLED.", lines)

    def test_a_failed_uninstall_says_so_and_carries_no_traceback(self):
        lines = [
            line.text for line in render(UninstallResultScreen(cli=SAMPLE, report=UNINSTALL_FAILED_REPORT), cursor=0)
        ]
        self.assertIn("Uninstall didn't succeed.", lines)
        self.assertTrue(any("permission denied" in text for text in lines))
        self.assertFalse(any("Traceback" in text for text in lines))

    def test_it_carries_the_exact_prose_the_flags_would_print(self):
        lines = [line.text for line in render(UninstallResultScreen(cli=SAMPLE, report=UNINSTALLED_REPORT), cursor=0)]
        for expected in cli.prose_for(UNINSTALLED_REPORT).splitlines():
            self.assertIn(expected, lines)


class RestoreResultRenderingTest(unittest.TestCase):
    def test_a_successful_restore_says_so_unmistakably(self):
        lines = [line.text for line in render(RestoreResultScreen(report=RESTORED_REPORT), cursor=0)]
        self.assertIn("RESTORED.", lines)

    def test_a_failed_restore_says_so_and_carries_no_traceback(self):
        lines = [line.text for line in render(RestoreResultScreen(report=RESTORE_FAILED_REPORT), cursor=0)]
        self.assertIn("Restore didn't succeed.", lines)
        self.assertTrue(any("cannot be restored" in text for text in lines))
        self.assertFalse(any("Traceback" in text for text in lines))

    def test_it_carries_the_exact_prose_the_flags_would_print(self):
        lines = [line.text for line in render(RestoreResultScreen(report=RESTORED_REPORT), cursor=0)]
        for expected in cli.prose_for(RESTORED_REPORT).splitlines():
            self.assertIn(expected, lines)


PROVIDERS = (
    ProviderOption(id="anthropic", models=(ModelOption(id="deep-thinker", reasoning=True),)),
    ProviderOption(id="openai", models=(ModelOption(id="fast-model", reasoning=False),)),
)


def _models_screen(**overrides) -> ModelsScreen:
    fields = {
        "cli": SAMPLE,
        "providers": PROVIDERS,
        "rows": (AgentRow(agent="sdd-apply", current=None), AgentRow(agent="sdd-verify", current="anthropic/x")),
    }
    fields.update(overrides)
    return ModelsScreen(**fields)


class ModelsRowsRenderingTest(unittest.TestCase):
    def test_an_agent_with_no_model_says_so_plainly(self):
        lines = [line.text for line in render(_models_screen(), cursor=0)]
        self.assertTrue(any("sdd-apply" in text and "(no model)" in text for text in lines))

    def test_an_agent_with_a_model_shows_it(self):
        lines = [line.text for line in render(_models_screen(), cursor=1)]
        self.assertTrue(any("sdd-verify" in text and "anthropic/x" in text for text in lines))

    def test_the_footer_names_both_configuring_and_removing(self):
        lines = [line.text for line in render(_models_screen(), cursor=0)]
        self.assertIn("enter: configure · d: remove current model · esc: back", lines)

    def test_no_configurable_agent_is_explained_not_shown_as_an_empty_table(self):
        lines = [line.text for line in render(_models_screen(rows=()), cursor=0)]
        self.assertTrue(any("no agent" in text.lower() for text in lines))


class ModelsProviderStepRenderingTest(unittest.TestCase):
    def test_every_reachable_provider_is_offered(self):
        lines = [line.text for line in render(_models_screen(agent="sdd-apply"), cursor=0)]
        self.assertTrue(any("anthropic" in text for text in lines))
        self.assertTrue(any("openai" in text for text in lines))


class ModelsModelStepRenderingTest(unittest.TestCase):
    def test_only_the_chosen_providers_models_are_offered(self):
        lines = [line.text for line in render(_models_screen(agent="sdd-apply", provider_id="anthropic"), cursor=0)]
        self.assertTrue(any("deep-thinker" in text for text in lines))
        self.assertFalse(any("fast-model" in text for text in lines))


class ModelsEffortStepRenderingTest(unittest.TestCase):
    def test_the_effort_step_only_shows_up_once_a_model_is_chosen(self):
        lines = [
            line.text
            for line in render(
                _models_screen(agent="sdd-apply", provider_id="anthropic", model_id="deep-thinker"), cursor=0
            )
        ]
        self.assertTrue(any("low" in text for text in lines))
        self.assertTrue(any("medium" in text for text in lines))
        self.assertTrue(any("high" in text for text in lines))


class ModelsLongListRenderingTest(unittest.TestCase):
    def test_a_long_list_of_choices_stays_navigable_instead_of_spilling_past_the_terminal(self):
        many_rows = tuple(AgentRow(agent=f"agent-{i}", current=None) for i in range(40))
        lines = render(_models_screen(rows=many_rows), cursor=0)
        self.assertLess(len(lines), 40)

    def test_the_cursor_stays_inside_the_visible_window_as_it_moves(self):
        many_rows = tuple(AgentRow(agent=f"agent-{i}", current=None) for i in range(40))
        lines = render(_models_screen(rows=many_rows), cursor=39)
        highlighted = [line for line in lines if line.highlighted]
        self.assertEqual(len(highlighted), 1)
        self.assertIn("agent-39", highlighted[0].text)

    def test_a_short_list_names_no_more_above_or_below(self):
        lines = [line.text for line in render(_models_screen(), cursor=0)]
        self.assertFalse(any("more" in text for text in lines))


class BusyRenderingTest(unittest.TestCase):
    def test_the_message_becomes_the_one_line_shown(self):
        lines = render_busy("Installing into Demo CLI…")
        self.assertEqual([line.text for line in lines], ["Installing into Demo CLI…"])

    def test_nothing_on_it_is_highlighted(self):
        lines = render_busy("Running diagnostics…")
        self.assertFalse(any(line.highlighted for line in lines))


class LineSpanTest(unittest.TestCase):
    """`Line` carries a tuple of styled `Span`s so one physical row can mix
    emphases -- the wordmark's own bicolor split needs exactly this. A bare
    `str` is still accepted and normalized into a single `NORMAL` span, so
    every construction that predates spans still works."""

    def test_a_bare_string_becomes_a_single_normal_span(self):
        line = Line("text")
        self.assertEqual(line.spans, (Span("text", Style.NORMAL),))

    def test_the_text_property_concatenates_every_span(self):
        line = Line((Span("PEGASUS", Style.DIM), Span("HARNESS", Style.NORMAL)))
        self.assertEqual(line.text, "PEGASUSHARNESS")

    def test_a_span_defaults_to_normal_style(self):
        self.assertEqual(Span("text").style, Style.NORMAL)

    def test_a_line_can_carry_a_dim_span(self):
        line = Line((Span("text", Style.DIM),))
        self.assertEqual(line.spans[0].style, Style.DIM)

    def test_a_line_can_carry_an_accent_span(self):
        line = Line((Span("text", Style.ACCENT),))
        self.assertEqual(line.spans[0].style, Style.ACCENT)

    def test_highlighted_still_defaults_to_false(self):
        self.assertFalse(Line("text").highlighted)


class MenuWordmarkTest(unittest.TestCase):
    """The main menu's title becomes the wordmark once something is actually
    installed -- an empty machine keeps the plain title it always had."""

    def menu(self, *, installed: bool) -> Menu:
        return Menu(
            title="Pegasus Harness 9.9.9",
            entries=(Entry("Exit", QUIT),),
            installed=installed,
            version="9.9.9",
        )

    def test_nothing_installed_keeps_the_plain_title(self):
        lines = [line.text for line in render(self.menu(installed=False), cursor=0, width=200)]
        self.assertEqual(lines[0], "Pegasus Harness 9.9.9")
        self.assertNotIn(wordmark.wordmark_rows()[0], lines)

    def test_something_installed_draws_the_wordmark_when_it_fits(self):
        lines = [line.text for line in render(self.menu(installed=True), cursor=0, width=200)]
        for row in wordmark.wordmark_rows():
            self.assertIn(row, lines)
        self.assertNotIn("Pegasus Harness 9.9.9", lines)

    def test_the_version_sits_on_its_own_line_right_aligned_to_the_art(self):
        lines = [line.text for line in render(self.menu(installed=True), cursor=0, width=200)]
        version_line = lines[len(wordmark.wordmark_rows())]
        self.assertEqual(version_line, "9.9.9".rjust(wordmark.WORDMARK_WIDTH))

    def test_installed_but_too_narrow_for_the_full_mark_falls_back_to_pegasus_alone(self):
        lines = [line.text for line in render(self.menu(installed=True), cursor=0, width=40)]
        for row in wordmark.pegasus_rows():
            self.assertIn(row, lines)
        for row in wordmark.wordmark_rows():
            self.assertNotIn(row, lines)

    def test_installed_but_too_narrow_for_any_mark_keeps_the_plain_title(self):
        lines = [line.text for line in render(self.menu(installed=True), cursor=0, width=20)]
        self.assertEqual(lines[0], "Pegasus Harness 9.9.9")

    def test_the_full_marks_pegasus_half_is_dim_and_harness_half_is_normal(self):
        """The reference banner dims only `PEGASUS`, leaving `HARNESS` beside
        it in plain text on the very same row -- the whole reason `Line`
        gained spans. Each art row is exactly two spans: the dim `PEGASUS`
        glyph columns, then the normal `HARNESS` ones (the two-space gap
        travels with the first span, matching how `wordmark.wordmark_rows`
        joins them)."""
        lines = render(self.menu(installed=True), cursor=0, width=200)
        art_lines = lines[: len(wordmark.wordmark_rows())]
        for index, line in enumerate(art_lines):
            self.assertEqual(len(line.spans), 2)
            dim_span, normal_span = line.spans
            self.assertEqual(dim_span.style, Style.DIM)
            self.assertEqual(normal_span.style, Style.NORMAL)
            self.assertEqual(dim_span.text + normal_span.text, wordmark.wordmark_rows()[index])
            self.assertEqual(dim_span.text, wordmark.pegasus_rows()[index] + "  ")

    def test_the_solo_mark_is_entirely_dim(self):
        """The narrow variant is `PEGASUS` alone -- the brand mark on its
        own, without the second word there is nothing to split, and dim is
        the emphasis the full mark already gives that half."""
        lines = render(self.menu(installed=True), cursor=0, width=40)
        art_lines = lines[: len(wordmark.pegasus_rows())]
        for line in art_lines:
            self.assertEqual(len(line.spans), 1)
            self.assertEqual(line.spans[0].style, Style.DIM)


class InstallResultWordmarkTest(unittest.TestCase):
    def test_a_successful_install_draws_the_wordmark_above_the_banner(self):
        lines = render(InstallResultScreen(cli=SAMPLE, report=INSTALLED_REPORT), cursor=0, width=200)
        texts = [line.text for line in lines]
        self.assertIn(wordmark.wordmark_rows()[0], texts)
        self.assertLess(texts.index(wordmark.wordmark_rows()[0]), texts.index("INSTALLED."))

    def test_a_failed_install_draws_no_wordmark_at_all(self):
        lines = [line.text for line in render(InstallResultScreen(cli=SAMPLE, report=FAILED_REPORT), cursor=0, width=200)]
        self.assertNotIn(wordmark.wordmark_rows()[0], lines)
        self.assertNotIn(wordmark.pegasus_rows()[0], lines)

    def test_no_room_for_any_mark_still_shows_the_banner_plainly(self):
        lines = [line.text for line in render(InstallResultScreen(cli=SAMPLE, report=INSTALLED_REPORT), cursor=0, width=20)]
        self.assertIn("INSTALLED.", lines)
        self.assertNotIn(wordmark.wordmark_rows()[0], lines)
        self.assertNotIn(wordmark.pegasus_rows()[0], lines)


class ProgressRenderingTest(unittest.TestCase):
    """`render_progress` turns one `cli.Progress` snapshot plus a frame
    counter into the busy-install layout: the message and a spinner, the
    bar in `Style.ACCENT`, and the current unit's name dimmed underneath.
    The clock and the engine call both live outside this function -- `frame`
    and `progress` are handed in as plain data.
    """

    def test_the_message_and_a_spinner_glyph_appear_on_the_first_line(self):
        progress = cli.Progress(done=5, total=10, phase="artifacts", unit="a.md")
        lines = render_progress("Installing into Demo CLI…", progress, frame=0, width=80)
        self.assertIn("Installing into Demo CLI…", lines[0].text)

    def test_the_spinner_glyph_changes_with_the_frame(self):
        progress = cli.Progress(done=5, total=10, phase="artifacts", unit="a.md")
        first = render_progress("Installing…", progress, frame=0, width=80)[0].text
        second = render_progress("Installing…", progress, frame=1, width=80)[0].text
        self.assertNotEqual(first, second)

    def test_the_bar_row_is_accent_styled(self):
        progress = cli.Progress(done=5, total=10, phase="artifacts", unit="a.md")
        lines = render_progress("Installing…", progress, frame=0, width=80)
        bar_line = lines[1]
        self.assertTrue(all(span.style is Style.ACCENT for span in bar_line.spans))

    def test_the_bar_shows_filled_and_empty_cells_and_a_percentage(self):
        progress = cli.Progress(done=5, total=10, phase="artifacts", unit="a.md")
        bar_text = render_progress("Installing…", progress, frame=0, width=80)[1].text
        self.assertIn("■", bar_text)
        self.assertIn("･", bar_text)
        self.assertIn(" 50%", bar_text)

    def test_a_full_bar_shows_a_hundred_percent(self):
        progress = cli.Progress(done=10, total=10, phase="journal", unit="")
        bar_text = render_progress("Installing…", progress, frame=0, width=80)[1].text
        self.assertIn("100%", bar_text)

    def test_the_current_unit_is_shown_dim_beneath_the_bar(self):
        progress = cli.Progress(done=5, total=10, phase="dependencies", unit="some-package")
        lines = render_progress("Installing…", progress, frame=0, width=80)
        unit_line = next(line for line in lines if "some-package" in line.text)
        self.assertTrue(all(span.style is Style.DIM for span in unit_line.spans))

    def test_a_done_greater_than_total_still_draws_a_bar_at_most_full(self):
        """`done`/`total` come from arithmetic this layer did not perform --
        a miscounted `Progress` must never draw past a full bar."""
        progress = cli.Progress(done=15, total=10, phase="artifacts", unit="a.md")
        bar_text = render_progress("Installing…", progress, frame=0, width=80)[1].text
        self.assertIn("100%", bar_text)
        self.assertNotIn("150%", bar_text)

    def test_a_zero_total_does_not_divide_by_zero(self):
        progress = cli.Progress(done=0, total=0, phase="snapshot", unit="")
        lines = render_progress("Installing…", progress, frame=0, width=80)
        self.assertIn("0%", lines[1].text)

    def test_a_narrow_width_shrinks_the_bar_instead_of_overflowing(self):
        progress = cli.Progress(done=5, total=10, phase="artifacts", unit="a.md")
        lines = render_progress("Installing…", progress, frame=0, width=20)
        for line in lines:
            self.assertLessEqual(len(line.text), 20)


class DownloadProgressRenderingTest(unittest.TestCase):
    """The byte/rate line under the bar for a `download` server's fetch --
    degrading honestly when the total or the rate is not yet known, and
    changing nothing at all for a unit that carries no byte fields."""

    def test_a_non_download_unit_renders_exactly_as_before(self):
        """The regression guard: a unit with no byte fields must render the
        same bare, dimmed unit line this already drew before bytes existed."""
        progress = cli.Progress(done=5, total=10, phase="artifacts", unit="a.md")
        lines = render_progress("Installing…", progress, frame=0, width=80)
        unit_line = next(line for line in lines if "a.md" in line.text)
        self.assertEqual(unit_line.text, "a.md")
        self.assertTrue(all(span.style is Style.DIM for span in unit_line.spans))

    def test_a_known_total_shows_downloaded_over_total(self):
        progress = cli.Progress(
            done=2, total=10, phase="dependencies", unit="engram", bytes_downloaded=4404019, bytes_total=7236400
        )
        lines = render_progress("Installing…", progress, frame=0, width=80)
        unit_line = next(line for line in lines if "engram" in line.text)
        self.assertIn("4.2 MB / 6.9 MB", unit_line.text)

    def test_an_unknown_total_never_shows_a_fake_one(self):
        progress = cli.Progress(
            done=2, total=10, phase="dependencies", unit="engram", bytes_downloaded=4404019, bytes_total=None
        )
        lines = render_progress("Installing…", progress, frame=0, width=80)
        unit_line = next(line for line in lines if "engram" in line.text)
        self.assertIn("4.2 MB", unit_line.text)
        self.assertNotIn("/", unit_line.text)

    def test_no_rate_yet_omits_the_rate_entirely(self):
        progress = cli.Progress(
            done=2, total=10, phase="dependencies", unit="engram", bytes_downloaded=4404019, bytes_total=7236400
        )
        lines = render_progress("Installing…", progress, frame=0, width=80)
        unit_line = next(line for line in lines if "engram" in line.text)
        self.assertNotIn("/s", unit_line.text)

    def test_a_known_rate_is_shown_beside_the_amount(self):
        progress = cli.Progress(
            done=2, total=10, phase="dependencies", unit="engram", bytes_downloaded=4404019, bytes_total=7236400
        )
        lines = render_progress("Installing…", progress, frame=0, width=80, rate_bytes_per_second=1153433.6)
        unit_line = next(line for line in lines if "engram" in line.text)
        self.assertIn("4.2 MB / 6.9 MB · 1.1 MB/s", unit_line.text)

    def test_the_download_line_is_dimmed_like_every_other_unit_line(self):
        progress = cli.Progress(
            done=2, total=10, phase="dependencies", unit="engram", bytes_downloaded=4404019, bytes_total=7236400
        )
        lines = render_progress("Installing…", progress, frame=0, width=80, rate_bytes_per_second=1153433.6)
        unit_line = next(line for line in lines if "engram" in line.text)
        self.assertTrue(all(span.style is Style.DIM for span in unit_line.spans))


class RenderWidthDefaultTest(unittest.TestCase):
    def test_render_without_a_width_still_works_for_ordinary_screens(self):
        lines = render(Menu(title="t", entries=(Entry("a", QUIT),)), cursor=0)
        self.assertEqual(lines[0].text, "t")


if __name__ == "__main__":
    unittest.main()
