"""No test may name a real path of the machine that runs the suite.

An agent once baked a session scratchpad path (with its session UUID) into a
shipped test, and that test then ran `mkdir` on it. Tests that need a path must
build it under a temp dir, or use an obviously fictitious one that they only
touch in memory (`/home/probe/...`, `/home/me/...`).

The "real" values are derived at runtime, so the guard works on any machine.
Only two shapes are static, because they are a leak wherever they appear: the
`claude-<digits>` temp root and a session UUID directly under `scratchpad`.

This module holds no real path literal: the patterns are built from runtime
values and the samples are assembled from fragments, so the guard scans its own
source like any other test and no file is exempt.
"""
from __future__ import annotations

import re
import subprocess
import unittest
import uuid
from unittest import mock
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = REPO_ROOT / "tests"

UUID_SHAPE = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
#: Always a leak: the per-user temp root of the agent runtime.
#: Anchored to path context (a `/` before, a separator or end after) so a model
#: id such as `claude-3-5-sonnet` is not taken for it.
TEMP_ROOT_PATTERN = r"(?<=/)claude-\d+(?=/|$|[\"'\s])"
#: Always a leak: `<slugged cwd>/<session uuid>/scratchpad`.
SCRATCHPAD_PATTERN = r"-home-[^/\s]+-[^/\s]*/" + UUID_SHAPE + r"/scratchpad"


#: Final names of the fictitious homes the tests use on purpose. When the suite
#: runs under one of them, its HOME is not a real machine path to protect.
FICTITIOUS_HOME_NAMES = frozenset({"probe", "me", "u", "x", "person", "someone", "one", "two"})


def _path_pattern(path: Path) -> str | None:
    """Regex for `path` as a whole path prefix, or None when it is too generic to flag."""
    text = path.as_posix().rstrip("/")
    if path.name in FICTITIOUS_HOME_NAMES:
        return None  # a stand-in home used deliberately by the tests
    if len(path.parts) < 3:  # "/", "/root": a literal that short is not a machine-specific path
        return None
    return re.escape(text) + r"(?![\w.-])"


def build_matcher(home: Path, repo_root: Path) -> re.Pattern[str]:
    parts = [TEMP_ROOT_PATTERN, SCRATCHPAD_PATTERN]
    for real in (home, repo_root):
        pattern = _path_pattern(real)
        if pattern is not None:
            parts.append(pattern)
    return re.compile("|".join(parts))


def find_offenders(name: str, text: str, matcher: re.Pattern[str]) -> list[str]:
    return [
        f"{name}:{number}: {match.group(0)}"
        for number, line in enumerate(text.splitlines(), start=1)
        for match in matcher.finditer(line)
    ]


def tracked_test_files() -> list[Path]:
    """Tracked files under tests/, or raise `GitUnavailable` (no git, or no checkout)."""
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z", "--", "tests/"],
            cwd=REPO_ROOT, capture_output=True, check=True,
        ).stdout.decode("utf-8")
    except (OSError, subprocess.CalledProcessError) as error:
        raise GitUnavailable(str(error)) from error
    return [REPO_ROOT / name for name in out.split("\0") if name]


class GitUnavailable(Exception):
    pass


def read_text_or_none(path: Path) -> str | None:
    try:
        data = path.read_bytes()
    except OSError:
        return None  # listed by git but absent from the working tree
    if b"\0" in data:
        return None  # binary
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


class MatcherBitesTest(unittest.TestCase):
    """Mutation proof: the matcher flags real shapes and lets fictitious ones through."""

    HOME = Path.home()
    MATCHER = build_matcher(HOME, REPO_ROOT)

    def flagged(self, text: str) -> bool:
        return bool(find_offenders("sample", text, self.MATCHER))

    def test_flags_real_home(self) -> None:
        if _path_pattern(self.HOME) is None:
            self.skipTest("home directory too generic to flag on this machine")
        self.assertTrue(self.flagged(f"{self.HOME.as_posix()}/work/x"))
        self.assertTrue(self.flagged(f'"{self.HOME.as_posix()}"'))

    def test_flags_real_repo_root(self) -> None:
        self.assertTrue(self.flagged(f"{REPO_ROOT.as_posix()}/src"))

    def test_flags_agent_temp_root(self) -> None:
        root = "/tmp/" + "claude-" + "1000"
        self.assertTrue(self.flagged(root))
        self.assertTrue(self.flagged("/some/where/" + "claude-" + "20001/x"))

    def test_flags_scratchpad_shape(self) -> None:
        sample = "-home-" + "someone-proj/" + str(uuid.uuid4()) + "/scratch" + "pad"
        self.assertTrue(self.flagged(sample))

    def test_temp_root_is_anchored_to_path_context(self) -> None:
        for sample in ("claude-" + "3-5-sonnet", '"claude-' + '3"', "model claude-" + "3 x", "/a/claude-" + "12x"):
            with self.subTest(sample=sample):
                self.assertFalse(self.flagged(sample))
        for sample in ("/a/claude-" + "1000", '"/a/claude-' + '1000"', "/a/claude-" + "1000/x"):
            with self.subTest(sample=sample):
                self.assertTrue(self.flagged(sample))

    def test_a_fictitious_running_home_is_not_flagged_as_real(self) -> None:
        for name in sorted(FICTITIOUS_HOME_NAMES):
            with self.subTest(name=name):
                self.assertIsNone(_path_pattern(Path("/home") / name))
                matcher = build_matcher(Path("/home") / name, REPO_ROOT)
                self.assertFalse(find_offenders("s", "/home/" + name + "/x", matcher))

    def test_a_generic_running_home_is_not_flagged(self) -> None:
        self.assertIsNone(_path_pattern(Path("/root")))
        self.assertIsNone(_path_pattern(Path("/")))

    def test_missing_git_is_reported_as_unavailable(self) -> None:
        with mock.patch.object(subprocess, "run", side_effect=FileNotFoundError("git")):
            with self.assertRaises(GitUnavailable):
                tracked_test_files()
        failure = subprocess.CalledProcessError(128, "git")
        with mock.patch.object(subprocess, "run", side_effect=failure):
            with self.assertRaises(GitUnavailable):
                tracked_test_files()

    def test_allows_fictitious_paths(self) -> None:
        for sample in ("/home/" + "probe/x", "/home/" + "me/x", "/home/me/.config/tool"):
            with self.subTest(sample=sample):
                self.assertFalse(self.flagged(sample))

    def test_home_match_respects_path_boundary(self) -> None:
        if _path_pattern(self.HOME) is None:
            self.skipTest("home directory too generic to flag on this machine")
        self.assertFalse(self.flagged(self.HOME.as_posix() + "other/x"))

    def test_reports_file_line_and_text(self) -> None:
        text = "ok\n" + "x = '" + self.HOME.as_posix() + "/a'\n"
        if _path_pattern(self.HOME) is None:
            self.skipTest("home directory too generic to flag on this machine")
        found = find_offenders("tests/t.py", text, self.MATCHER)
        self.assertEqual(found, [f"tests/t.py:2: {self.HOME.as_posix()}"])


class NoRealHostPathsInTestsTest(unittest.TestCase):
    def test_no_tracked_test_file_names_a_real_host_path(self) -> None:
        matcher = build_matcher(Path.home(), REPO_ROOT)
        try:
            files = tracked_test_files()
        except GitUnavailable as error:
            self.skipTest(f"git or a git checkout is not available: {error}")
        self.assertTrue(files, "git ls-files returned no files under tests/")
        offenders: list[str] = []
        for path in files:
            text = read_text_or_none(path)
            if text is not None:
                offenders.extend(find_offenders(path.relative_to(REPO_ROOT).as_posix(), text, matcher))
        self.assertEqual(
            offenders, [],
            "tests must not name real paths of the machine; use a temp dir or a fictitious path:\n"
            + "\n".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()
