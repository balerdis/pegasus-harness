"""Tests for tools/check_docs_links.py.

Everything this tool does is local: `git ls-files` against a repository
already on disk and plain filesystem existence checks. No network is ever
touched, so nothing here needs to be skipped or worked around.

`resolve()` is tested directly, unit-style, since it is the one piece of real
logic (the skills-root exception). `main()` is exercised two ways: once for
real, by subprocess, against this actual repository -- a genuine regression
check that today's tracked Markdown has no broken relative links -- and once
against a small synthetic git repository (with the module's `ROOT` and
`SKILLS_ROOT` monkeypatched) to prove a broken link is actually caught and
reported with a non-zero exit code, which the real repo's passing state alone
cannot demonstrate.

`slug()` and `anchors()` are tested the same two ways, and for the same
reason. The synthetic cases prove the rules; the corpus cases prove the rules
are the ones this repository's documents actually need. Every corpus case
derives its inputs from the tracked Markdown rather than quoting a heading
inline -- a quoted heading stops being evidence the moment someone renames
it -- and asserts first that the shape it is about occurs at all, so it
cannot pass vacuously once the corpus stops containing it.
"""
from __future__ import annotations

import contextlib
import io
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "check_docs_links.py"

sys.path.insert(0, str(ROOT / "tools"))

import check_docs_links as checker  # noqa: E402


def _run() -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _tracked_documents() -> list[Path]:
    """The Markdown the checker itself looks at, read the same way it does."""
    listing = subprocess.run(
        ["git", "ls-files", "-co", "--exclude-standard", "-z"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    )
    return [
        ROOT / item
        for item in listing.stdout.decode().split("\0")
        if item.endswith(".md") and not item.startswith("source/") and (ROOT / item).is_file()
    ]


def _corpus_headings() -> list[str]:
    """Every real heading text in the tracked corpus, fences excluded."""
    texts: list[str] = []
    for document in _tracked_documents():
        fence = None
        for line in document.read_text(encoding="utf-8").splitlines():
            opener = checker.FENCE.match(line)
            if opener:
                character = opener.group(1)[0]
                fence = character if fence is None else (None if fence == character else fence)
                continue
            if fence is not None:
                continue
            heading = checker.HEADING.match(line)
            if heading:
                texts.append(heading.group(2))
    return texts


class ResolveTest(unittest.TestCase):
    """The one real branch: a link inside the skills tree resolves against the
    skills root; everywhere else it resolves against the linking file's own
    directory."""

    def setUp(self):
        self._original_skills_root = checker.SKILLS_ROOT
        self.addCleanup(setattr, checker, "SKILLS_ROOT", self._original_skills_root)

    def test_a_link_outside_the_skills_tree_resolves_against_its_own_directory(self):
        checker.SKILLS_ROOT = Path("/nonexistent/skills/root")
        linking_file = ROOT / "docs" / "some-doc.md"
        self.assertEqual(
            checker.resolve(linking_file, "other-doc.md"),
            ROOT / "docs" / "other-doc.md",
        )

    def test_a_link_inside_the_skills_tree_resolves_against_the_skills_root(self):
        skills_root = ROOT / "src" / "pegasus" / "content" / "skills"
        checker.SKILLS_ROOT = skills_root
        linking_file = skills_root / "some-skill" / "SKILL.md"
        self.assertEqual(
            checker.resolve(linking_file, "some-skill/reference.md"),
            skills_root / "some-skill" / "reference.md",
        )


class SlugTest(unittest.TestCase):
    """One rule -- lowercase, drop what is not a word character, whitespace or
    hyphen, whitespace to hyphens -- applied to the shapes this repository's
    headings really contain. Each case finds its own examples in the tracked
    corpus, so a case that stops being about anything fails instead of
    quietly proving nothing."""

    @classmethod
    def setUpClass(cls):
        cls.headings = _corpus_headings()

    def setUp(self):
        self.assertTrue(self.headings, "no headings in the tracked corpus -- this would pass vacuously")

    def test_every_corpus_heading_slugs_to_something_a_url_can_carry(self):
        for text in self.headings:
            anchor = checker.slug(text)
            self.assertEqual(anchor, anchor.lower())
            self.assertNotRegex(anchor, r"[\s`()\[\]{}:,.\"'/!?*#]")

    def test_an_accent_survives_because_it_is_a_word_character(self):
        accented = [text for text in self.headings if re.search(r"[áéíóúñÁÉÍÓÚÑ]", text)]
        self.assertTrue(accented, "no accented heading in the corpus -- this would pass vacuously")
        for text in accented:
            self.assertRegex(checker.slug(text), r"[áéíóúñ]")

    def test_inline_code_loses_its_backticks_and_keeps_its_text(self):
        coded = [text for text in self.headings if "`" in text]
        self.assertTrue(coded, "no heading with inline code -- this would pass vacuously")
        for text in coded:
            self.assertNotIn("`", checker.slug(text))
            self.assertEqual(checker.slug(text), checker.slug(text.replace("`", "")))

    def test_a_dash_set_off_by_spaces_leaves_the_doubled_hyphen_github_leaves(self):
        dashed = [text for text in self.headings if " — " in text or " – " in text]
        self.assertTrue(dashed, "no heading with a spaced dash -- this would pass vacuously")
        for text in dashed:
            self.assertIn("--", checker.slug(text))

    def test_an_underscore_is_kept_because_a_url_fragment_can_carry_it(self):
        underscored = [text for text in self.headings if re.search(r"\w_\w", text)]
        self.assertTrue(underscored, "no heading with an underscore -- this would pass vacuously")
        for text in underscored:
            self.assertIn("_", checker.slug(text))


class AnchorsTest(unittest.TestCase):
    """What counts as a heading, and what a repeated one is called."""

    def test_repeated_headings_get_githubs_disambiguating_suffixes(self):
        found = checker.anchors("# Fields\n\n## Fields\n\n### Fields\n")
        self.assertEqual(found, ["fields", "fields-1", "fields-2"])

    def test_some_tracked_document_really_does_repeat_a_heading(self):
        """The suffix rule is not hypothetical here: derive the repeats from
        the corpus rather than trusting a slug that merely ends in a number,
        and fail if the corpus ever stops containing one."""
        repeated = []
        for document in _tracked_documents():
            found = checker.anchors(document.read_text(encoding="utf-8"))
            if len(found) != len(set(found)) or len(found) != len({re.sub(r"-\d+$", "", anchor) for anchor in found}):
                repeated.append(document)
        self.assertTrue(repeated, "no tracked document repeats a heading -- the suffix rule would be untested against the corpus")
        for document in repeated:
            found = checker.anchors(document.read_text(encoding="utf-8"))
            self.assertEqual(len(found), len(set(found)), f"{document}: two headings would answer to the same anchor")

    def test_a_hash_line_inside_a_fenced_code_block_is_not_an_anchor(self):
        found = checker.anchors("# Real\n\n```bash\n# Create branch\n```\n")
        self.assertEqual(found, ["real"])

    def test_the_corpus_really_does_hide_hash_lines_inside_fences(self):
        """Without fence handling, a link to a heading that does not exist
        could pass by matching a shell comment or a Markdown template. That
        hazard has to be real in this corpus for the handling to be earned."""
        hidden = 0
        for document in _tracked_documents():
            text = document.read_text(encoding="utf-8")
            all_hash_lines = {checker.slug(match.group(2)) for match in (checker.HEADING.match(line) for line in text.splitlines()) if match}
            hidden += len(all_hash_lines - set(checker.anchors(text)))
        self.assertTrue(hidden, "no hash line hides inside a fence -- this would pass vacuously")

    def test_a_setext_underline_is_not_treated_as_a_heading(self):
        """`---` in this corpus is a YAML frontmatter delimiter, never a
        Setext underline, so reading one as a heading would invent anchors
        out of frontmatter keys."""
        found = checker.anchors("---\nname: thing\n---\n\n# Real\n")
        self.assertEqual(found, ["real"])


class RealRepositoryRegressionTest(unittest.TestCase):
    """The tool actually run, for real, against this repository's own tracked
    Markdown. This is the regression check: today's docs must have no broken
    relative links."""

    def test_the_tracked_documentation_has_no_broken_relative_links(self):
        if not (ROOT / ".git").exists():
            self.skipTest("not a git checkout (e.g. a tarball export) -- `git ls-files` has nothing to read")
        result = _run()
        self.assertEqual(result.returncode, 0, msg=result.stdout)
        self.assertIn("PASS", result.stdout)


class SyntheticRepositoryFailureTest(unittest.TestCase):
    """A broken link must actually fail the check -- proven against a
    throwaway repository, since the real repository's passing state cannot
    demonstrate what happens when a link is broken."""

    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.repo = Path(self._directory.name)
        _git(self.repo, "init", "-q")
        _git(self.repo, "config", "user.email", "test@example.invalid")
        _git(self.repo, "config", "user.name", "Test")

        self._original_root = checker.ROOT
        self._original_skills_root = checker.SKILLS_ROOT
        self.addCleanup(setattr, checker, "ROOT", self._original_root)
        self.addCleanup(setattr, checker, "SKILLS_ROOT", self._original_skills_root)
        checker.ROOT = self.repo
        checker.SKILLS_ROOT = self.repo / "src" / "pegasus" / "content" / "skills"

    def _commit(self, message: str) -> None:
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-q", "-m", message)

    def _call(self) -> int:
        original_argv = sys.argv
        sys.argv = ["check_docs_links.py"]
        try:
            return checker.main()
        finally:
            sys.argv = original_argv

    def _call_capturing_output(self) -> tuple[int, str]:
        """The exit code plus what the report printed, so a failure can be
        read for the file, the line and the fragment it is supposed to name."""
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            exit_code = self._call()
        return exit_code, buffer.getvalue()

    def test_a_broken_relative_link_is_reported_and_fails(self):
        (self.repo / "doc.md").write_text("see [elsewhere](missing-target.md)\n", encoding="utf-8")
        self._commit("synthetic doc with a broken link")

        exit_code, output = self._call_capturing_output()

        self.assertEqual(exit_code, 1)
        self.assertIn("broken link: doc.md:1 -> missing-target.md", output)

    def test_a_resolvable_relative_link_passes(self):
        (self.repo / "doc.md").write_text("see [elsewhere](target.md)\n", encoding="utf-8")
        (self.repo / "target.md").write_text("target\n", encoding="utf-8")
        self._commit("synthetic doc with a resolvable link")

        exit_code = self._call()

        self.assertEqual(exit_code, 0)

    def test_an_absolute_url_is_never_treated_as_a_broken_file(self):
        (self.repo / "doc.md").write_text(
            "see [web](https://example.invalid/page#top) and [mail](mailto:a@b.invalid)\n",
            encoding="utf-8",
        )
        self._commit("synthetic doc with non-file links")

        exit_code = self._call()

        self.assertEqual(exit_code, 0)

    def test_a_link_to_a_heading_that_exists_passes(self):
        (self.repo / "doc.md").write_text("see [there](target.md#la-sección)\n", encoding="utf-8")
        (self.repo / "target.md").write_text("# Target\n\n## La `sección`\n", encoding="utf-8")
        self._commit("synthetic doc with a resolvable anchor")

        exit_code = self._call()

        self.assertEqual(exit_code, 0)

    def test_a_link_to_a_heading_that_does_not_exist_fails_and_names_file_and_fragment(self):
        (self.repo / "doc.md").write_text(
            "intro\n\nsee [there](target.md#missing-heading)\n",
            encoding="utf-8",
        )
        (self.repo / "target.md").write_text("# Target\n\n## Present Heading\n", encoding="utf-8")
        self._commit("synthetic doc with a broken anchor")

        exit_code, output = self._call_capturing_output()

        self.assertEqual(exit_code, 1)
        self.assertIn("doc.md:3", output)
        self.assertIn("target.md", output)
        self.assertIn("missing-heading", output)
        self.assertIn("present-heading", output)

    def test_a_link_to_a_heading_hidden_in_a_fence_fails(self):
        (self.repo / "doc.md").write_text("see [there](target.md#create-branch)\n", encoding="utf-8")
        (self.repo / "target.md").write_text("# Target\n\n```bash\n# Create branch\n```\n", encoding="utf-8")
        self._commit("synthetic doc pointing at a shell comment")

        exit_code = self._call()

        self.assertEqual(exit_code, 1)

    def test_a_same_document_anchor_resolves_against_the_linking_document(self):
        (self.repo / "doc.md").write_text("see [above](#the-section)\n\n## The Section\n", encoding="utf-8")
        self._commit("synthetic doc with a resolvable same-document anchor")

        exit_code = self._call()

        self.assertEqual(exit_code, 0)

    def test_a_same_document_anchor_naming_no_heading_fails(self):
        (self.repo / "doc.md").write_text("see [above](#the-section)\n\n## Another Section\n", encoding="utf-8")
        self._commit("synthetic doc with a broken same-document anchor")

        exit_code, output = self._call_capturing_output()

        self.assertEqual(exit_code, 1)
        self.assertIn("doc.md:1", output)
        self.assertIn("the-section", output)

    def test_a_same_document_anchor_does_not_borrow_another_documents_headings(self):
        (self.repo / "doc.md").write_text("see [above](#only-over-there)\n", encoding="utf-8")
        (self.repo / "target.md").write_text("# Target\n\n## Only Over There\n", encoding="utf-8")
        self._commit("synthetic doc whose anchor exists only elsewhere")

        exit_code = self._call()

        self.assertEqual(exit_code, 1)

    def test_a_broken_file_is_reported_once_and_not_also_as_a_broken_anchor(self):
        (self.repo / "doc.md").write_text("see [there](missing.md#whatever)\n", encoding="utf-8")
        self._commit("synthetic doc with a broken file carrying a fragment")

        exit_code, output = self._call_capturing_output()

        self.assertEqual(exit_code, 1)
        self.assertEqual(output.count("missing.md"), 1, output)
        self.assertIn("broken link", output)
        self.assertNotIn("broken anchor", output)


if __name__ == "__main__":
    unittest.main()
