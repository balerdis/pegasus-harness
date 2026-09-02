"""The rule the architecture states in one sentence: the TUI cannot do
anything the flags cannot. This is the small check that promise reduces to
once parity is structural instead of asserted — every entry a built screen
offers must name a command that actually exists on the CLI surface, and every
entry that does not is still marked as not built rather than pretending to be.
"""
from __future__ import annotations

import unittest

from pegasus import cli
from pegasus.core import content as content_module
from pegasus.tui.navigator import (
    Action,
    CliOption,
    GenerationSummary,
    InstallTarget,
    McpOption,
    McpSelectionScreen,
    Menu,
    ModelsTarget,
    Navigator,
    Placeholder,
    RestoreConfirm,
    RestoreTarget,
    StatusRequest,
    UninstallConfirm,
    UninstallTarget,
    UpdateTarget,
    UpgradeTarget,
    main_menu,
    models_menu,
    restore_menu,
    uninstall_menu,
    update_menu,
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
        target = next(entry.target for entry in main_menu().entries if entry.label == "Status and diagnostics")
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
        summaries = (
            GenerationSummary(generation=2, taken_at="2026-08-14T00:00:00+00:00", files_restored=1, paths_cleared=0),
            GenerationSummary(generation=1, taken_at="2026-08-14T00:00:00+00:00", files_restored=1, paths_cleared=0),
        )
        menu = restore_menu(summaries)
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

    def test_every_update_choice_names_a_command_the_flags_expose(self):
        menu = update_menu(installed=(SAMPLE,))
        self.assertIsInstance(menu, Menu)
        for entry in menu.entries:
            self.assertIsInstance(entry.target, UpdateTarget)
            self.assertIn(entry.target.command, cli.COMMANDS)

    def test_the_upgrade_entry_names_the_upgrade_command(self):
        target = next(entry.target for entry in main_menu().entries if entry.label == "Upgrade")
        self.assertIsInstance(target, UpgradeTarget)
        self.assertIn(target.command, cli.COMMANDS)

    def test_no_menu_entry_still_claims_to_be_unbuilt(self):
        menu = main_menu(detections=(SAMPLE,), installed=(SAMPLE,))
        for entry in menu.entries:
            self.assertNotIsInstance(entry.target, Placeholder)

    def test_every_server_the_mcp_selection_screen_could_offer_is_one_the_flag_accepts(self):
        """The screen this change adds must offer nothing `--mcp` itself
        would refuse: every id it could check is a name `select_mcp` -- the
        same function the flag runs through -- recognizes as real."""
        content = content_module.load()
        known = {server.name for server in content.mcp}
        options = tuple(McpOption(id=server.name, description=server.description) for server in content.mcp)
        self.assertTrue(options)
        self.assertEqual({option.id for option in options}, known)
        content_module.select_mcp(content, [option.id for option in options])  # raises on an id the flag would refuse

    def test_reaching_continue_on_the_mcp_selection_screen_does_nothing_by_itself(self):
        """Fetching the plan for what ended up checked is real engine work,
        same as every other member of `_ENGINE_TARGETS` -- `Navigator` alone
        must never invent the report it cannot fetch."""
        options = (McpOption(id="context7", description="docs"),)
        navigator = Navigator.starting().opened(McpSelectionScreen(cli=SAMPLE, options=options, chosen=()))
        navigator = navigator.handle(Action.MOVE_DOWN)  # onto Continue
        before = navigator
        navigator = navigator.handle(Action.CHOOSE)
        self.assertEqual(navigator, before)


if __name__ == "__main__":
    unittest.main()
