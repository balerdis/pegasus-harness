#!/usr/bin/env python3
"""Check relative Markdown links in tracked Pegasus documentation.

Most documents resolve a relative link the ordinary way: against the
directory the linking file lives in. Skills are the deliberate exception.
`tests/test_skill_references.py` documents why: every reference inside
`src/pegasus/content/skills/` is written relative to that skills root, so the
same reference means the same thing regardless of which skill wrote it, and a
lazily-loaded agent can resolve it with one shared rule instead of a bespoke
one per skill. Resolving those links against the linking file's own
directory -- the rule everywhere else -- flags real, resolvable references as
broken. This checker resolves a link inside the skills tree against the
skills root, the same convention the shipped content and its test already
follow, and still reports a link that resolves nowhere at all.

A link may also carry a `#fragment`, and the fragment is checked too. A link
whose file exists but whose fragment names no heading is exactly as broken as
a link to a missing file -- it lands the reader somewhere arbitrary -- but it
reads green to any checker that splits the fragment off and throws it away.
That is the failure this repository keeps closing: a guard that passes
without proving what its name claims. Renaming a heading must now break every
pointer aimed at it, loudly, with the file and the line that has to change.
"""
from __future__ import annotations

import difflib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"\[[^]]+\]\(([^)]+)\)")
SKILLS_ROOT = ROOT / "src" / "pegasus" / "content" / "skills"

# An ATX heading: up to three leading spaces, one to six hashes, a space, the
# text. Setext headings (`Title` underlined with `===` or `---`) and explicit
# HTML anchors (`<a name=...>`, `id=...`) are NOT handled, on purpose: the
# tracked corpus contains neither, and the only `---` lines are YAML
# frontmatter delimiters, which a Setext reader would misread as headings for
# the frontmatter's last key. Handling is added when a document needs it.
HEADING = re.compile(r"^ {0,3}(#{1,6})\s+(.*?)\s*$")

# A fenced code block opener or closer. This matters more than it looks: the
# corpus is full of skills whose fences hold shell snippets (`# Create
# branch`) and Markdown templates (`#### Scenario: {Name}`). Those lines are
# not headings and GitHub renders no anchor for them, so collecting them
# would let a link to a heading that does not exist pass by matching a shell
# comment. Only the fence character and the toggle are tracked -- not the
# opener's length -- because no document in the corpus nests fences of the
# same character.
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")

# GitHub's slug: lowercase, drop every character that is not a word
# character, whitespace or hyphen, then turn each remaining whitespace
# character into a hyphen. `\w` is Unicode-aware in Python, which is what the
# corpus needs -- `## Instalación` must slug to `instalación`, and
# `mode_of` keeps its underscore. Backticks, parentheses, colons, quotes
# and em dashes all fall to the same one rule rather than a list of
# special cases, which is why inline code in a heading needs no handling of
# its own. Whitespace is replaced one character at a time, not collapsed:
# `A — B` loses the dash and keeps both spaces, so GitHub yields `a--b`.
#
# Deliberately left out, because the corpus has none: Markdown emphasis in a
# heading (`**bold**`, `_em_`), inline links in a heading, and closing-hash
# ATX syntax (`## Title ##`). The first two would need the marker stripped
# but the text kept; the third would need the trailing hashes dropped. Each
# is a guess about a shape no document here writes, and a wrong guess in a
# guard is worse than a gap it reports honestly.
NOT_SLUGGABLE = re.compile(r"[^\w\s-]", re.UNICODE)


def slug(text: str) -> str:
    """The anchor GitHub generates for a heading's text."""
    return re.sub(r"\s", "-", NOT_SLUGGABLE.sub("", text.strip().lower()))


def anchors(text: str) -> list[str]:
    """Every anchor a Markdown document offers, in document order.

    Headings that slug to the same thing get GitHub's disambiguating
    suffixes: the first keeps the bare slug, the next becomes `slug-1`, then
    `slug-2`. The corpus needs this -- `issue-creation/SKILL.md` really does
    carry two `Required Fields` headings -- so a link to the second one has
    somewhere to point.
    """
    found: list[str] = []
    counts: dict[str, int] = {}
    fence: str | None = None
    for line in text.splitlines():
        opener = FENCE.match(line)
        if opener:
            character = opener.group(1)[0]
            if fence is None:
                fence = character
            elif fence == character:
                fence = None
            continue
        if fence is not None:
            continue
        heading = HEADING.match(line)
        if not heading:
            continue
        base = slug(heading.group(2))
        seen = counts.get(base, 0)
        counts[base] = seen + 1
        found.append(base if seen == 0 else f"{base}-{seen}")
    return found


def resolve(path: Path, destination: str) -> Path:
    """Where `destination`, written in `path`, is supposed to point.

    Inside the skills tree that is the skills root; everywhere else it is the
    linking file's own directory.
    """
    if SKILLS_ROOT in path.parents:
        return SKILLS_ROOT / destination
    return path.parent / destination


def suggestions(fragment: str, available: list[str]) -> str:
    """The nearest real anchors, as a hint appended to a failure.

    A guard whose failure does not tell you the fix teaches people to ignore
    it, so the report names what the target document actually offers instead
    of only what it does not.
    """
    if not available:
        return "; it has no headings"
    close = difflib.get_close_matches(fragment, available, n=3, cutoff=0.4)
    return "; nearest: " + ", ".join(f"#{anchor}" for anchor in close or available[:3])


def main() -> int:
    result = subprocess.run(["git", "ls-files", "-co", "--exclude-standard", "-z"], cwd=ROOT, capture_output=True, check=True)
    errors: list[str] = []
    cache: dict[Path, list[str]] = {}

    def anchors_of(target: Path) -> list[str]:
        if target not in cache:
            cache[target] = anchors(target.read_text(encoding="utf-8"))
        return cache[target]

    for item in result.stdout.decode().split("\0"):
        path = ROOT / item
        if not item.endswith(".md") or not path.is_file() or item.startswith("source/"):
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            for target in LINK.findall(line):
                if target.startswith(("http://", "https://", "mailto:")):
                    continue
                destination, _, fragment = target.partition("#")
                # A link written as `#section`, with no path, points into the
                # linking document itself, and it is checked here against
                # that document. It used to be skipped wholesale. Skipping it
                # is the worse half of the deal: a same-document pointer is
                # the one most likely to rot, because it is written next to
                # the heading it names and survives the rename that moves
                # it -- and it is the cheapest to verify, since the file is
                # already open.
                anchor_source = path if not destination else resolve(path, destination)
                if destination and not anchor_source.exists():
                    errors.append(f"broken link: {item}:{number} -> {target}")
                    continue
                if not fragment or anchor_source.suffix != ".md":
                    continue
                available = anchors_of(anchor_source)
                if fragment not in available:
                    where = os.path.relpath(anchor_source, ROOT)
                    errors.append(
                        f"broken anchor: {item}:{number} -> {target}"
                        f" ({where} has no heading slugging to '{fragment}'"
                        f"{suggestions(fragment, available)})"
                    )
    if errors:
        print("FAIL")
        print("\n".join(errors))
        return 1
    print("PASS: relative Markdown links and their anchors resolve")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
