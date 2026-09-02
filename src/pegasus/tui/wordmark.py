"""Block-glyph letters wide enough to read across a terminal, and the two
shapes this release ever asks them to spell: the brand alone, and the brand
beside `HARNESS`, letter for letter, in the block-glyph installer-wordmark
style this change was asked to reproduce. Nothing here reads a terminal, a
window, or the environment; picking which shape fits a given width, and what
emphasis to draw it with, is `view`'s job once it knows how much room there
actually is.
"""
from __future__ import annotations

#: One letter, as the three rows of block characters that spell it -- every
#: letter this release's two words need, in the exact glyphs already
#: prototyped for it. Each row is four columns wide, so a word's own width
#: never has to be measured cell by cell; see `word_width`.
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
}

_ROW_COUNT = 3
_GLYPH_WIDTH = 4


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


PEGASUS = "PEGASUS"
HARNESS = "HARNESS"

#: The narrower of the two shapes `view` can choose -- what it falls back to
#: when the full mark does not fit, and the width it must fit for that to
#: happen at all.
PEGASUS_WIDTH = word_width(PEGASUS)

#: The full mark's own width: `PEGASUS`, two spaces, `HARNESS`.
WORDMARK_WIDTH = PEGASUS_WIDTH * 2 + 2


def pegasus_rows() -> tuple[str, ...]:
    """`PEGASUS` alone, the shape `view` draws where the full mark does not
    fit but this still does."""
    return word_rows(PEGASUS)


def wordmark_rows() -> tuple[str, ...]:
    """`PEGASUS`, two spaces, `HARNESS` -- the full mark, its first half
    dim and its second half plain in the shape this was asked to reproduce;
    which half gets which emphasis is `view`'s decision to make, not this
    one's, since dimming is a rendering concern this module has no reason to
    know about."""
    pegasus_part = word_rows(PEGASUS)
    harness_part = word_rows(HARNESS)
    return tuple(f"{p}  {h}" for p, h in zip(pegasus_part, harness_part))
