"""The rule the architecture states in one sentence: the TUI cannot do
anything the flags cannot. This is the small check that promise reduces to
once parity is structural instead of asserted — every entry a built screen
offers must name a command that actually exists on the CLI surface, and every
entry that does not is still marked as not built rather than pretending to be.
"""
from __future__ import annotations

import unittest

from pegasus import cli
from pegasus.tui.navigator import CliOption, InstallTarget, Menu, Placeholder, main_menu

SAMPLE = CliOption(id="demo", display_name="Demo CLI", config_dir="/home/x/.demo", tier="full")


class TuiNamesAnExistingCommandTest(unittest.TestCase):
    def test_every_install_choice_names_a_command_the_flags_expose(self):
        install_menu = main_menu(detections=(SAMPLE,)).entries[0].target
        self.assertIsInstance(install_menu, Menu)
        for entry in install_menu.entries:
            self.assertIsInstance(entry.target, InstallTarget)
            self.assertIn(entry.target.command, cli.COMMANDS)

    def test_every_entry_still_marked_unbuilt_says_so_rather_than_naming_a_command(self):
        menu = main_menu(detections=(SAMPLE,))
        unbuilt = {"Configure models", "Status and diagnostics", "Uninstall"}
        for entry in menu.entries:
            if entry.label in unbuilt:
                self.assertIsInstance(entry.target, Placeholder)


if __name__ == "__main__":
    unittest.main()
