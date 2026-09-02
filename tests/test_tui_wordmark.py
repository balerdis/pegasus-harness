"""The block-glyph letters and the two shapes they compose into. Pure text:
no terminal, no curses, nothing that could fail for lack of either.
"""
from __future__ import annotations

import unittest

from pegasus.tui import wordmark


class WordRowsTest(unittest.TestCase):
    def test_a_word_is_three_rows_tall(self):
        rows = wordmark.word_rows("PEGASUS")
        self.assertEqual(len(rows), 3)

    def test_each_letter_is_looked_up_in_the_glyph_table(self):
        rows = wordmark.word_rows("P")
        self.assertEqual(rows, wordmark.GLYPHS["P"])

    def test_letters_are_joined_by_a_single_space(self):
        rows = wordmark.word_rows("PE")
        p_row, e_row = wordmark.GLYPHS["P"][0], wordmark.GLYPHS["E"][0]
        self.assertEqual(rows[0], f"{p_row} {e_row}")


class WidthTest(unittest.TestCase):
    def test_pegasus_alone_is_thirty_four_columns(self):
        self.assertEqual(wordmark.PEGASUS_WIDTH, 34)
        self.assertTrue(all(len(row) == 34 for row in wordmark.pegasus_rows()))

    def test_the_full_mark_is_seventy_columns(self):
        self.assertEqual(wordmark.WORDMARK_WIDTH, 70)
        self.assertTrue(all(len(row) == 70 for row in wordmark.wordmark_rows()))


class WordmarkRowsTest(unittest.TestCase):
    def test_the_full_mark_starts_with_pegasus_alone(self):
        full = wordmark.wordmark_rows()
        solo = wordmark.pegasus_rows()
        for full_row, solo_row in zip(full, solo):
            self.assertTrue(full_row.startswith(solo_row))

    def test_the_two_words_are_separated_by_two_spaces(self):
        full = wordmark.wordmark_rows()
        solo = wordmark.pegasus_rows()
        for full_row, solo_row in zip(full, solo):
            rest = full_row[len(solo_row):]
            self.assertTrue(rest.startswith("  "))
            self.assertFalse(rest.startswith("   "))


if __name__ == "__main__":
    unittest.main()
