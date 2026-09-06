"""The block-glyph letters and the two shapes they compose into. Pure text:
no terminal, no curses, nothing that could fail for lack of either.
"""
from __future__ import annotations

import unittest

from pegasus.core import identity
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


class GlyphCoverageMirrorTest(unittest.TestCase):
    """The single most important test in this module: `core.identity`'s
    `ALLOWED_CHARACTERS` names every character a wordmark word may contain,
    and this module's `GLYPHS` names every character it can actually draw.
    If those two sets ever disagree, a valid `identity.json` can name a word
    with a character this renderer has no glyph for -- a build-time-approved
    name that crashes or draws garbage the first time the menu opens. This
    test is the one thing standing between the two staying provably in sync
    and drifting apart silently, the exact shape of bug this project has
    been bitten by before when an invariant was only enforced in one
    direction.
    """

    def test_the_glyph_table_covers_exactly_what_identity_allows(self):
        self.assertEqual(set(wordmark.GLYPHS), identity.ALLOWED_CHARACTERS)

    def test_every_glyph_is_three_rows_of_four_columns(self):
        for letter, rows in wordmark.GLYPHS.items():
            self.assertEqual(len(rows), 3, msg=f"{letter!r} is not three rows")
            for row in rows:
                self.assertEqual(len(row), 4, msg=f"{letter!r} row {row!r} is not four columns")

    def test_the_longest_allowed_word_renders_at_the_documented_width(self):
        """`identity.MAX_WORD_LENGTH` is a stated, documented decision (12
        characters), not a bare magic number: a solo mark of that length is
        59 columns, which still fits an 80-column terminal. This proves the
        two modules agree on that arithmetic, not just on the character set.
        """
        longest = "A" * identity.MAX_WORD_LENGTH
        self.assertEqual(wordmark.word_width(longest), 59)


class MarkWidthTest(unittest.TestCase):
    """`mark_width`/`solo_width` are computed from whatever words they are
    given -- no policy branch on how many there are, per the spec's
    "Wordmark Words Are Rendered, Not Chosen" requirement."""

    def test_solo_width_of_one_word_is_its_own_width(self):
        self.assertEqual(wordmark.solo_width(("DARQ",)), wordmark.word_width("DARQ"))

    def test_mark_width_of_one_word_equals_its_solo_width(self):
        self.assertEqual(wordmark.mark_width(("DARQ",)), wordmark.solo_width(("DARQ",)))

    def test_solo_width_of_two_words_is_only_the_first(self):
        self.assertEqual(wordmark.solo_width(("PEGASUS", "HARNESS")), wordmark.word_width("PEGASUS"))

    def test_mark_width_of_two_words_adds_a_two_space_gap(self):
        words = ("PEGASUS", "HARNESS")
        expected = wordmark.word_width("PEGASUS") + 2 + wordmark.word_width("HARNESS")
        self.assertEqual(wordmark.mark_width(words), expected)

    def test_empty_words_is_zero_width(self):
        self.assertEqual(wordmark.mark_width(()), 0)
        self.assertEqual(wordmark.solo_width(()), 0)


if __name__ == "__main__":
    unittest.main()
