"""The rule the architecture states in one sentence: the TUI cannot do
anything the flags cannot. This is the small check that promise reduces to
once parity is structural instead of asserted — every entry a built screen
offers must name a command that actually exists on the CLI surface, and every
entry that does not is still marked as not built rather than pretending to be.
"""
from __future__ import annotations

import unittest

from pegasus import cli
from pegasus.tui.navigator import (
    CliOption,
    InstallTarget,
    Menu,
    ModelsTarget,
    Placeholder,
    RestoreConfirm,
    RestoreTarget,
    StatusRequest,
    UninstallConfirm,
    UninstallTarget,
    main_menu,
    models_menu,
    restore_menu,
    uninstall_menu,
)

SAMPLE = CliOption(id="demo", display_name="Demo CLI", config_dir="/home/x/.demo", tier="full")


class TuiNamesAnExistingCommandTest(unittest.TestCase):
    def test_every_install_choice_names_a_command_the_flags_expose(self):
        install_menu = main_menu(detections=(SAMPLE,)).entries[0].target
        self.assertIsInstance(install_menu, Menu)
        for entry in install_menu.entries:
            self.assertIsInstance(entry.target, InstallTarget)
            self.assertIn(entry.target.command, cli.COMMANDS)

    def test_the_status_entry_names_the_doctor_command(self):
        target = main_menu().entries[2].target
        self.assertIsInstance(target, StatusRequest)
        self.assertIn(target.command, cli.COMMANDS)

    def test_every_uninstall_choice_names_a_command_the_flags_expose(self):
        menu = uninstall_menu(installed=(SAMPLE,))
        self.assertIsInstance(menu, Menu)
        for entry in menu.entries:
            self.assertIsInstance(entry.target, UninstallTarget)
            self.assertIn(entry.target.command, cli.COMMANDS)

    def test_the_uninstall_confirm_entry_names_a_command_the_flags_expose(self):
        confirm = UninstallConfirm(SAMPLE)
        self.assertIn(confirm.command, cli.COMMANDS)

    def test_every_restore_choice_names_a_command_the_flags_expose(self):
        menu = restore_menu(generations=(2, 1))
        self.assertIsInstance(menu, Menu)
        for entry in menu.entries:
            self.assertIsInstance(entry.target, RestoreTarget)
            self.assertIn(entry.target.command, cli.COMMANDS)

    def test_the_restore_confirm_entry_names_a_command_the_flags_expose(self):
        confirm = RestoreConfirm(1)
        self.assertIn(confirm.command, cli.COMMANDS)

    def test_every_models_choice_names_a_command_the_flags_expose(self):
        menu = models_menu(detections=(SAMPLE,))
        self.assertIsInstance(menu, Menu)
        for entry in menu.entries:
            self.assertIsInstance(entry.target, ModelsTarget)
            self.assertIn(entry.target.command, cli.COMMANDS)

    def test_no_menu_entry_still_claims_to_be_unbuilt(self):
        menu = main_menu(detections=(SAMPLE,), installed=(SAMPLE,))
        for entry in menu.entries:
            self.assertNotIsInstance(entry.target, Placeholder)


if __name__ == "__main__":
    unittest.main()
