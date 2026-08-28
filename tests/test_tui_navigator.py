"""Navigation as pure logic: what is on screen, and what a key does next.

Every scenario here presses keys and checks where a person ends up. None of
it touches a terminal, because :class:`Navigator` never touches one either.
"""
from __future__ import annotations

import unittest

import pegasus
from pegasus.tui.navigator import (
    CANCEL,
    Action,
    CliOption,
    Entry,
    InstallPlanScreen,
    InstallResultScreen,
    InstallTarget,
    Menu,
    Navigator,
    Placeholder,
    RestoreConfirm,
    RestoreResultScreen,
    RestoreTarget,
    StatusRequest,
    UninstallConfirm,
    UninstallResultScreen,
    UninstallTarget,
    main_menu,
    restore_menu,
    uninstall_menu,
)

SAMPLE = CliOption(id="demo", display_name="Demo CLI", config_dir="/home/x/.demo", tier="full")


class MainMenuTest(unittest.TestCase):
    def test_the_session_starts_on_the_main_menu(self):
        navigator = Navigator.starting()
        self.assertIsInstance(navigator.current, Menu)

    def test_the_main_menu_has_the_five_documented_entries_in_order(self):
        navigator = Navigator.starting()
        labels = [entry.label for entry in navigator.current.entries]
        self.assertEqual(
            labels,
            ["Install", "Configure models", "Status and diagnostics", "Uninstall", "Exit"],
        )

    def test_the_title_names_the_running_release(self):
        navigator = Navigator.starting()
        self.assertEqual(navigator.current.title, f"Pegasus Harness {pegasus.__version__}")

    def test_the_cursor_starts_on_the_first_entry(self):
        navigator = Navigator.starting()
        self.assertEqual(navigator.cursor, 0)


class MovementTest(unittest.TestCase):
    def test_moving_down_advances_the_cursor(self):
        navigator = Navigator.starting().handle(Action.MOVE_DOWN)
        self.assertEqual(navigator.cursor, 1)

    def test_moving_up_from_the_first_entry_wraps_to_the_last(self):
        navigator = Navigator.starting().handle(Action.MOVE_UP)
        self.assertEqual(navigator.cursor, len(navigator.current.entries) - 1)

    def test_moving_down_from_the_last_entry_wraps_to_the_first(self):
        navigator = Navigator.starting()
        for _ in range(len(navigator.current.entries) - 1):
            navigator = navigator.handle(Action.MOVE_DOWN)
        navigator = navigator.handle(Action.MOVE_DOWN)
        self.assertEqual(navigator.cursor, 0)

    def test_moving_never_changes_which_screen_is_current(self):
        navigator = Navigator.starting()
        before = navigator.current
        navigator = navigator.handle(Action.MOVE_DOWN)
        self.assertIs(navigator.current, before)


class EnteringAndLeavingAScreenTest(unittest.TestCase):
    def test_choosing_an_entry_enters_the_screen_it_names(self):
        expected = Navigator.starting().current.entries[0].target
        navigator = Navigator.starting().handle(Action.CHOOSE)
        self.assertEqual(navigator.current, expected)

    def test_a_screen_not_built_yet_is_a_placeholder_that_says_so(self):
        navigator = Navigator.starting().handle(Action.CHOOSE)
        self.assertIsInstance(navigator.current, Placeholder)
        self.assertTrue(navigator.current.note)

    def test_going_back_returns_to_the_main_menu(self):
        navigator = Navigator.starting().handle(Action.CHOOSE)
        navigator = navigator.handle(Action.BACK)
        self.assertIsInstance(navigator.current, Menu)

    def test_going_back_restores_the_cursor_that_was_left_on_the_menu(self):
        navigator = Navigator.starting()
        navigator = navigator.handle(Action.MOVE_DOWN).handle(Action.MOVE_DOWN)
        remembered = navigator.cursor
        navigator = navigator.handle(Action.CHOOSE).handle(Action.BACK)
        self.assertEqual(navigator.cursor, remembered)

    def test_choosing_a_placeholder_screen_also_returns_to_the_menu(self):
        """Nothing to configure there yet, so acknowledging it is the same as leaving it."""
        navigator = Navigator.starting().handle(Action.CHOOSE)
        navigator = navigator.handle(Action.CHOOSE)
        self.assertIsInstance(navigator.current, Menu)

    def test_going_back_at_the_root_menu_stays_put(self):
        navigator = Navigator.starting()
        after = navigator.handle(Action.BACK)
        self.assertEqual(after, navigator)


class QuittingTest(unittest.TestCase):
    def test_the_session_does_not_start_quit(self):
        self.assertFalse(Navigator.starting().quit)

    def test_choosing_exit_quits(self):
        navigator = Navigator.starting()
        exit_index = [entry.label for entry in navigator.current.entries].index("Exit")
        for _ in range(exit_index):
            navigator = navigator.handle(Action.MOVE_DOWN)
        navigator = navigator.handle(Action.CHOOSE)
        self.assertTrue(navigator.quit)

    def test_the_quit_action_works_from_a_nested_screen_too(self):
        navigator = Navigator.starting().handle(Action.CHOOSE).handle(Action.QUIT)
        self.assertTrue(navigator.quit)

    def test_a_quit_session_ignores_further_keys(self):
        quit_navigator = Navigator.starting().handle(Action.QUIT)
        self.assertEqual(quit_navigator.handle(Action.MOVE_DOWN), quit_navigator)


class InstallMenuTest(unittest.TestCase):
    """The `¿Dónde instalar Pegasus?` screen: built from whichever CLIs were
    detected present, with nothing here doing any of that detecting."""

    def test_a_detected_cli_opens_a_menu_naming_it(self):
        navigator = Navigator.starting(detections=(SAMPLE,)).handle(Action.CHOOSE)
        self.assertIsInstance(navigator.current, Menu)
        self.assertEqual(navigator.current.entries[0].target, InstallTarget(SAMPLE))

    def test_the_entry_names_the_install_command(self):
        navigator = Navigator.starting(detections=(SAMPLE,)).handle(Action.CHOOSE)
        self.assertEqual(navigator.current.entries[0].target.command, "install")

    def test_no_detected_cli_still_shows_a_placeholder_that_says_why(self):
        navigator = Navigator.starting(detections=()).handle(Action.CHOOSE)
        self.assertIsInstance(navigator.current, Placeholder)
        self.assertIn("No supported CLI", navigator.current.note)

    def test_going_back_from_the_cli_choice_returns_to_the_main_menu(self):
        navigator = Navigator.starting(detections=(SAMPLE,)).handle(Action.CHOOSE).handle(Action.BACK)
        self.assertIsInstance(navigator.current, Menu)
        self.assertEqual(navigator.current, Navigator.starting(detections=(SAMPLE,)).current)

    def test_choosing_a_cli_directly_does_nothing_by_itself(self):
        """Fetching a plan is real engine work only `session` can do; asking
        `Navigator` alone for it must never invent a screen to stand in for
        the report it cannot fetch."""
        navigator = Navigator.starting(detections=(SAMPLE,)).handle(Action.CHOOSE)
        before = navigator
        navigator = navigator.handle(Action.CHOOSE)
        self.assertEqual(navigator, before)


class InstallPlanAndResultScreensTest(unittest.TestCase):
    """Once `session` has fetched a report, `Navigator` treats the screen it
    becomes like any other leaf: an acknowledgement returns to whatever
    opened it."""

    def plan(self) -> Navigator:
        return Navigator.starting(detections=(SAMPLE,)).handle(Action.CHOOSE).opened(
            InstallPlanScreen(cli=SAMPLE, report={"status": "planned"})
        )

    def result(self) -> Navigator:
        return self.plan().opened(InstallResultScreen(cli=SAMPLE, report={"status": "installed"}))

    def test_backing_out_of_a_plan_returns_to_the_cli_choice(self):
        navigator = self.plan().handle(Action.BACK)
        self.assertIsInstance(navigator.current, Menu)
        self.assertEqual(navigator.current.entries[0].target, InstallTarget(SAMPLE))

    def test_acknowledging_a_result_leaves_it(self):
        navigator = self.result().handle(Action.CHOOSE)
        self.assertIsInstance(navigator.current, Menu)


class StatusEntryTest(unittest.TestCase):
    """`Status and diagnostics` always leads somewhere real — `doctor` never
    needs a CLI detected first the way `install` does — but building its
    report is real engine work, so `Navigator` alone treats choosing it the
    same inert way it treats an `InstallTarget`."""

    def test_the_main_menu_names_a_status_request(self):
        self.assertIsInstance(main_menu().entries[2].target, StatusRequest)

    def test_choosing_it_directly_does_nothing_by_itself(self):
        navigator = Navigator.starting()
        for _ in range(2):
            navigator = navigator.handle(Action.MOVE_DOWN)
        before = navigator
        navigator = navigator.handle(Action.CHOOSE)
        self.assertEqual(navigator, before)


class UninstallMenuTest(unittest.TestCase):
    def test_nothing_installed_shows_a_placeholder_that_says_why(self):
        navigator = Navigator.starting(installed=()).handle(Action.MOVE_DOWN).handle(Action.MOVE_DOWN).handle(
            Action.MOVE_DOWN
        )
        navigator = navigator.handle(Action.CHOOSE)
        self.assertIsInstance(navigator.current, Placeholder)

    def test_an_installed_cli_opens_a_menu_naming_it(self):
        menu = uninstall_menu(installed=(SAMPLE,))
        self.assertIsInstance(menu, Menu)
        self.assertEqual(menu.entries[0].target, UninstallTarget(SAMPLE))

    def test_choosing_an_installed_cli_directly_does_nothing_by_itself(self):
        navigator = Navigator.starting(installed=(SAMPLE,))
        for _ in range(3):
            navigator = navigator.handle(Action.MOVE_DOWN)
        navigator = navigator.handle(Action.CHOOSE)
        before = navigator
        navigator = navigator.handle(Action.CHOOSE)
        self.assertEqual(navigator, before)


class RestoreMenuTest(unittest.TestCase):
    def test_no_generation_shows_a_placeholder_that_says_why(self):
        self.assertIsInstance(restore_menu(generations=()), Placeholder)

    def test_a_generation_opens_a_menu_naming_it(self):
        menu = restore_menu(generations=(3, 2, 1))
        self.assertIsInstance(menu, Menu)
        self.assertEqual([entry.target for entry in menu.entries], [RestoreTarget(3), RestoreTarget(2), RestoreTarget(1)])

    def test_choosing_a_generation_directly_does_nothing_by_itself(self):
        navigator = Navigator.starting().opened(restore_menu(generations=(1,)))
        before = navigator
        navigator = navigator.handle(Action.CHOOSE)
        self.assertEqual(navigator, before)


class ConfirmTargetsTest(unittest.TestCase):
    """`UninstallConfirm` and `RestoreConfirm` name real engine work too,
    just like their outer counterparts — choosing either directly is inert
    until `session` acts on it."""

    def confirm_menu(self, target) -> Menu:
        return Menu(title="Confirm?", entries=(Entry("Cancel", CANCEL), Entry("Confirm", target)))

    def test_choosing_a_confirm_target_directly_does_nothing_by_itself(self):
        for target in (UninstallConfirm(SAMPLE), RestoreConfirm(1)):
            navigator = Navigator.starting().opened(self.confirm_menu(target)).handle(Action.MOVE_DOWN)
            before = navigator
            navigator = navigator.handle(Action.CHOOSE)
            self.assertEqual(navigator, before)

    def test_choosing_cancel_leaves_the_screen_without_touching_anything(self):
        navigator = Navigator.starting().opened(self.confirm_menu(UninstallConfirm(SAMPLE)))
        navigator = navigator.handle(Action.CHOOSE)
        self.assertIsInstance(navigator.current, Menu)
        self.assertEqual(navigator.current, Navigator.starting().current)

    def test_the_default_cursor_on_a_confirm_menu_sits_on_cancel(self):
        navigator = Navigator.starting().opened(self.confirm_menu(UninstallConfirm(SAMPLE)))
        self.assertEqual(navigator.cursor, 0)
        self.assertEqual(navigator.current.entries[navigator.cursor].label, "Cancel")


class ResultScreensReturnToTheMainMenuTest(unittest.TestCase):
    def test_acknowledging_an_uninstall_result_leaves_it(self):
        navigator = Navigator.starting().opened(UninstallResultScreen(cli=SAMPLE, report={"status": "uninstalled"}))
        navigator = navigator.handle(Action.CHOOSE)
        self.assertIsInstance(navigator.current, Menu)

    def test_acknowledging_a_restore_result_leaves_it(self):
        navigator = Navigator.starting().opened(RestoreResultScreen(report={"status": "restored"}))
        navigator = navigator.handle(Action.BACK)
        self.assertIsInstance(navigator.current, Menu)


class MenuPrefaceTest(unittest.TestCase):
    def test_a_menu_with_no_preface_behaves_exactly_as_before(self):
        menu = Menu(title="t", entries=(Entry("a", CANCEL),))
        self.assertEqual(menu.preface, ())


if __name__ == "__main__":
    unittest.main()
