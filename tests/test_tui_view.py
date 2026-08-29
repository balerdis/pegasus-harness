"""What a screen looks like, as plain text lines rather than pixels on a
terminal — so the drawing layer never has to decide anything, only copy these
lines onto a window."""
from __future__ import annotations

import unittest

from pegasus import cli
from pegasus.tui.navigator import (
    AgentRow,
    CliOption,
    Entry,
    InstallPlanScreen,
    InstallResultScreen,
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
from pegasus.tui.view import render

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


class InstallResultRenderingTest(unittest.TestCase):
    def test_a_successful_install_says_so_unmistakably(self):
        lines = [line.text for line in render(InstallResultScreen(cli=SAMPLE, report=INSTALLED_REPORT), cursor=0)]
        self.assertIn("INSTALLED.", lines)
        self.assertNotIn("PREVIEW — nothing has been written yet.", lines)

    def test_a_failed_install_says_so_and_carries_no_traceback(self):
        lines = [line.text for line in render(InstallResultScreen(cli=SAMPLE, report=FAILED_REPORT), cursor=0)]
        self.assertIn("INSTALL FAILED.", lines)
        self.assertTrue(any("disk is full" in text for text in lines))
        self.assertFalse(any("Traceback" in text for text in lines))

    def test_it_carries_the_exact_prose_the_flags_would_print(self):
        lines = [line.text for line in render(InstallResultScreen(cli=SAMPLE, report=INSTALLED_REPORT), cursor=0)]
        for expected in cli.prose_for(INSTALLED_REPORT).splitlines():
            self.assertIn(expected, lines)


class UninstallResultRenderingTest(unittest.TestCase):
    def test_a_successful_uninstall_says_so_unmistakably(self):
        lines = [line.text for line in render(UninstallResultScreen(cli=SAMPLE, report=UNINSTALLED_REPORT), cursor=0)]
        self.assertIn("UNINSTALLED.", lines)

    def test_a_failed_uninstall_says_so_and_carries_no_traceback(self):
        lines = [
            line.text for line in render(UninstallResultScreen(cli=SAMPLE, report=UNINSTALL_FAILED_REPORT), cursor=0)
        ]
        self.assertIn("UNINSTALL FAILED.", lines)
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
        self.assertIn("RESTORE FAILED.", lines)
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


if __name__ == "__main__":
    unittest.main()
