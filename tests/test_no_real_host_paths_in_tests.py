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
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = REPO_ROOT / "tests"

UUID_SHAPE = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
#: Always a leak: the per-user temp root of the agent runtime.
TEMP_ROOT_PATTERN = r"claude-\d+"
#: Always a leak: `<slugged cwd>/<session uuid>/scratchpad`.
SCRATCHPAD_PATTERN = r"-home-[^/\s]+-[^/\s]*/" + UUID_SHAPE + r"/scratchpad"


def _path_pattern(path: Path) -> str | None:
    """Regex for `path` as a whole path prefix, or None when it is too generic to flag."""
    text = path.as_posix().rstrip("/")
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
    out = subprocess.run(
        ["git", "ls-files", "-z", "--", "tests/"],
        cwd=REPO_ROOT, capture_output=True, check=True,
    ).stdout.decode("utf-8")
    return [REPO_ROOT / name for name in out.split("\0") if name]


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
        files = tracked_test_files()
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
