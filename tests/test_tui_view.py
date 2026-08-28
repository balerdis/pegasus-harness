"""What a screen looks like, as plain text lines rather than pixels on a
terminal — so the drawing layer never has to decide anything, only copy these
lines onto a window."""
from __future__ import annotations

import unittest

from pegasus import cli
from pegasus.tui.navigator import CliOption, Entry, InstallPlanScreen, InstallResultScreen, Menu, Placeholder, QUIT
from pegasus.tui.view import render

SAMPLE = CliOption(id="demo", display_name="Demo CLI", config_dir="/home/x/.demo", tier="full")
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


if __name__ == "__main__":
    unittest.main()
