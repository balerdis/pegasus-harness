"""The one thing in the drawing layer worth testing on its own: turning a key
code into an :class:`Action`. It is a lookup table, not a decision, and
reading `curses`'s key constants needs no terminal — only starting one does,
and nothing here does that."""
from __future__ import annotations

import curses
import unittest

from pegasus.tui.app import action_for
from pegasus.tui.navigator import Action


class KeyMappingTest(unittest.TestCase):
    def test_the_arrow_keys_map_to_movement(self):
        self.assertEqual(action_for(curses.KEY_UP), Action.MOVE_UP)
        self.assertEqual(action_for(curses.KEY_DOWN), Action.MOVE_DOWN)

    def test_vi_style_keys_map_to_the_same_movement(self):
        self.assertEqual(action_for(ord("k")), Action.MOVE_UP)
        self.assertEqual(action_for(ord("j")), Action.MOVE_DOWN)

    def test_enter_chooses(self):
        self.assertEqual(action_for(curses.KEY_ENTER), Action.CHOOSE)
        self.assertEqual(action_for(ord("\n")), Action.CHOOSE)

    def test_escape_goes_back(self):
        self.assertEqual(action_for(27), Action.BACK)

    def test_q_quits(self):
        self.assertEqual(action_for(ord("q")), Action.QUIT)

    def test_d_removes(self):
        self.assertEqual(action_for(ord("d")), Action.REMOVE)

    def test_an_unmapped_key_means_nothing(self):
        self.assertIsNone(action_for(ord("z")))


if __name__ == "__main__":
    unittest.main()
