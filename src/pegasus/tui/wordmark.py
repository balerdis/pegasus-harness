"""Block-glyph letters wide enough to read across a terminal.

Nothing here reads a terminal, a window, the environment, a clock, or any
identity data -- this module is data plus arithmetic: a table of glyphs and
the two widths derivable from it. `wordmark_words` -- whatever list of one
or two words a distribution's `identity.json` names -- is handed to
`word_rows`/`mark_width`/`solo_width` by `tui.view`; picking which shape
fits a given width, and what emphasis to draw it with, is `view`'s job once
it knows how much room there actually is, not this one's.

`GLYPHS` MUST cover exactly `core.identity.ALLOWED_CHARACTERS` (A-Z and
0-9) -- see `tests/test_tui_wordmark.py`'s `GlyphCoverageMirrorTest`, the
one test in this change that matters most. `core.identity._word` validates
the charset a wordmark word may contain; this module holds the glyphs that
can actually be drawn. If those two sets ever disagree, a name a build
approved would draw broken or missing art the first time a menu opens --
an invariant this project has been bitten by before when it was only
enforced in one direction. Keeping both sides in one mirror-invariant test
is what makes that drift a test failure instead of a runtime surprise.
"""
from __future__ import annotations

#: One letter or digit, as the three rows of block characters that spell it.
#: Each row is four columns wide, so a word's own width never has to be
#: measured cell by cell; see `word_width`. Covers exactly A-Z and 0-9 --
#: `core.identity.ALLOWED_CHARACTERS` -- so any wordmark word a build
#: accepted can always be drawn.
GLYPHS: dict[str, tuple[str, str, str]] = {
    "P": ("█▀▀█", "█▀▀▀", "▀   "),
    "E": ("█▀▀▀", "█▀▀ ", "▀▀▀▀"),
    "G": ("█▀▀▀", "█░▀█", "▀▀▀▀"),
    "A": ("█▀▀█", "█▀▀█", "▀  ▀"),
    "S": ("█▀▀▀", "▀▀▀█", "▀▀▀▀"),
    "U": ("█  █", "█░░█", "▀▀▀▀"),
    "H": ("█  █", "█▀▀█", "▀  ▀"),
    "R": ("█▀▀█", "█▀▀▄", "▀  ▀"),
    "N": ("█▄ █", "█░▀█", "▀  ▀"),
    "B": ("█▀▀▄", "█▀▀▄", "▀▀▀ "),
    "C": ("█▀▀▀", "█   ", "▀▀▀▀"),
    "D": ("█▀▀▄", "█  █", "▀▀▀ "),
    "F": ("█▀▀▀", "█▀▀ ", "▀   "),
    "I": (" ██ ", " ██ ", " ▀▀ "),
    "J": ("   █", "   █", "▀▀  "),
    "K": ("█ ▄▀", "█▀▄ ", "▀  ▀"),
    "L": ("█   ", "█   ", "▀▀▀▀"),
    "M": ("█▄▄█", "█▀▀█", "▀  ▀"),
    "O": ("█▀▀█", "█  █", "▀▀▀▀"),
    "Q": ("█▀▀█", "█ ▄█", "▀▀▀▀"),
    "T": ("▀██▀", " ██ ", " ▀▀ "),
    "V": ("█  █", "▀▄▄▀", " ▀▀ "),
    "W": ("█  █", "█▄▄█", "▀  ▀"),
    "X": ("█  █", " ██ ", "▀  ▀"),
    "Y": ("█  █", " ██ ", " ▀▀ "),
    "Z": ("▀▀▀█", "  █ ", "█▀▀▀"),
    "0": ("█▀▀█", "█  █", "▀▀▀▀"),
    "1": ("  █ ", "  █ ", "▀▀▀▀"),
    "2": ("▀▀▀█", "█▀▀ ", "▀▀▀▀"),
    "3": ("▀▀▀█", " ▀▀█", "▀▀▀▀"),
    "4": ("█  █", "▀▀▀█", "   ▀"),
    "5": ("█▀▀▀", "▀▀▀█", "▀▀▀▀"),
    "6": ("█▀▀▀", "█▀▀█", "▀▀▀▀"),
    "7": ("▀▀▀█", "   █", "   █"),
    "8": ("█▀▀█", "█▀▀█", "▀▀▀▀"),
    "9": ("█▀▀█", "▀▀▀█", "▀▀▀▀"),
}

_ROW_COUNT = 3
_GLYPH_WIDTH = 4

#: The two-space gap `view` draws between one word and the next on the full
#: mark's own row -- named here, next to the arithmetic that already depends
#: on it, rather than left a bare `2` in `mark_width`.
_WORD_GAP = 2


def word_rows(word: str) -> tuple[str, ...]:
    """`word`'s letters, each looked up in `GLYPHS`, joined one row at a
    time by a single space."""
    letters = [GLYPHS[letter] for letter in word]
    return tuple(" ".join(letter[row] for letter in letters) for row in range(_ROW_COUNT))


def word_width(word: str) -> int:
    """How many columns `word_rows(word)` takes up, without building it --
    every glyph is `_GLYPH_WIDTH` columns, and a single space sits between
    each pair of them."""
    if not word:
        return 0
    return len(word) * _GLYPH_WIDTH + (len(word) - 1)


def solo_width(words: tuple[str, ...]) -> int:
    """The narrower of the two shapes `view` can choose -- the first word
    alone, the shape it falls back to when the full mark does not fit."""
    if not words:
        return 0
    return word_width(words[0])


def mark_width(words: tuple[str, ...]) -> int:
    """The full mark's own width: every word in `words`, in order, each pair
    separated by `_WORD_GAP` columns. Draws whatever list it is given --
    one word, two words, or (structurally) more -- with no policy branch on
    how many there are; `core.identity` is what actually limits a real
    identity to one or two."""
    if not words:
        return 0
    return sum(word_width(word) for word in words) + _WORD_GAP * (len(words) - 1)
