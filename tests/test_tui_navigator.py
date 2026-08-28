"""Navigation as pure logic: what is on screen, and what a key does next.

Every scenario here presses keys and checks where a person ends up. None of
it touches a terminal, because :class:`Navigator` never touches one either.
"""
from __future__ import annotations

import unittest

import pegasus
from pegasus.tui.navigator import Action, Menu, Navigator, Placeholder


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


if __name__ == "__main__":
    unittest.main()
