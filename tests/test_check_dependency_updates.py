"""Tests for tools/check_dependency_updates.py.

Every test injects a fake `fetch` that serves JSON fixtures from memory; nothing here reaches the
network. `main` is driven by patching the module's `default_fetch`.
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

import check_dependency_updates as tool  # noqa: E402

GITHUB_URL = "https://api.github.com/repos/acme/widget/releases?per_page=100"
NPM_URL = "https://registry.npmjs.org/@scope%2Fpkg"


def _github(*releases: tuple[str, bool, bool]) -> bytes:
    return json.dumps(
        [{"tag_name": tag, "draft": draft, "prerelease": pre} for tag, draft, pre in releases]
    ).encode()


def _npm(*versions: str) -> bytes:
    return json.dumps({"versions": {v: {} for v in versions}}).encode()


def _fake_fetch(responses: dict[str, bytes | Exception]):
    def fetch(url: str, timeout: float) -> bytes:
        if url not in responses:
            raise OSError(f"no fixture for {url}")
        value = responses[url]
        if isinstance(value, Exception):
            raise value
        return value

    return fetch


def _download(version: str) -> dict[str, str]:
    return {
        "name": "widget",
        "distribution": "download",
        "endpoint": f"https://github.com/acme/widget/releases/download/v{version}/w.tar.gz",
        "version": version,
    }


def _npm_descriptor(version: str) -> dict[str, str]:
    return {"name": "pkg", "distribution": "npm", "package": "@scope/pkg", "version": version}


def _check(descriptor: dict[str, str], body: bytes) -> dict:
    url = GITHUB_URL if descriptor["distribution"] == "download" else NPM_URL
    return tool.check_descriptor(descriptor, _fake_fetch({url: body}), 5)


class ClassifyTests(unittest.TestCase):
    def test_drafts_and_prereleases_are_skipped(self) -> None:
        body = _github(("v2.0.0", True, False), ("v1.9.0", False, True), ("v1.1.0", False, False))
        row = _check(_download("1.0.0"), body)
        self.assertEqual((row["status"], row["latest"], row["latest_major"]), ("update-available", "1.1.0", None))

    def test_npm_versions_with_dash_are_skipped(self) -> None:
        row = _check(_npm_descriptor("1.0.0"), _npm("1.0.0", "1.1.0-alpha.1", "2.0.0-rc.1"))
        self.assertEqual(row["status"], "up-to-date")

    def test_same_major_update_picks_latest_in_major(self) -> None:
        row = _check(_download("1.2.0"), _github(("v1.2.5", False, False), ("v1.10.0", False, False)))
        self.assertEqual((row["status"], row["latest"]), ("update-available", "1.10.0"))

    def test_same_major_update_also_reports_higher_major(self) -> None:
        row = _check(_download("1.2.0"), _github(("v1.3.0", False, False), ("v2.0.0", False, False)))
        self.assertEqual((row["status"], row["latest"], row["latest_major"]), ("update-available", "1.3.0", "2.0.0"))

    def test_major_only(self) -> None:
        row = _check(_download("1.2.0"), _github(("v2.0.0", False, False), ("v1.2.0", False, False)))
        self.assertEqual((row["status"], row["latest"], row["latest_major"]), ("major-available", None, "2.0.0"))

    def test_zero_x_any_newer_is_review(self) -> None:
        row = _check(_npm_descriptor("0.0.79"), _npm("0.0.79", "0.0.83", "0.1.0"))
        self.assertEqual((row["status"], row["latest"]), ("review-0.x", "0.1.0"))

    def test_up_to_date(self) -> None:
        row = _check(_download("1.2.0"), _github(("v1.2.0", False, False), ("v1.1.0", False, False)))
        self.assertEqual(row["status"], "up-to-date")

    def test_remote_is_unversioned_without_fetching(self) -> None:
        descriptor = {"name": "ctx", "distribution": "remote", "endpoint": "https://example.com/mcp"}
        row = tool.check_descriptor(descriptor, _fake_fetch({}), 5)
        self.assertEqual(row["status"], "unversioned")

    def test_fetch_error_marks_row_and_continues(self) -> None:
        fetch = _fake_fetch({GITHUB_URL: OSError("boom"), NPM_URL: _npm("0.0.79")})
        rows = tool.check_all([_download("1.0.0"), _npm_descriptor("0.0.79")], fetch, 5)
        self.assertEqual([row["status"] for row in rows], ["error", "up-to-date"])
        self.assertIn("boom", rows[0]["detail"])


class ParseTests(unittest.TestCase):
    def test_real_descriptors_parse(self) -> None:
        descriptors = tool.load_descriptors(REPO_ROOT / "src" / "pegasus" / "content" / "mcp")
        by_name = {d["name"]: d for d in descriptors}
        self.assertEqual({"cbm", "context7", "engram", "jira", "playwright"}, set(by_name))
        self.assertEqual(by_name["context7"]["distribution"], "remote")
        self.assertNotIn("version", by_name["jira"])
        self.assertEqual(by_name["playwright"]["package"], "@playwright/mcp")
        for name in ("cbm", "engram", "playwright"):
            self.assertIsNotNone(tool.version_key(by_name[name]["version"]))
        for name in ("cbm", "engram"):
            self.assertIsNotNone(tool.GITHUB_ENDPOINT.match(by_name[name]["endpoint"]))

    def test_default_mcp_dir_is_discovered_from_the_tool_location(self) -> None:
        found = tool.discover_mcp_dir()
        self.assertEqual(found.parent.name, "content")
        self.assertEqual(found, tool.discover_mcp_dir(REPO_ROOT))

    def test_discovery_works_for_any_product_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "src" / "darq" / "content" / "mcp").mkdir(parents=True)
            self.assertEqual(tool.discover_mcp_dir(Path(tmp)), Path(tmp) / "src" / "darq" / "content" / "mcp")

    def test_discovery_needs_exactly_one_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(tool.DescriptorError):
                tool.discover_mcp_dir(Path(tmp))
            for product in ("a", "b"):
                (Path(tmp) / "src" / product / "content" / "mcp").mkdir(parents=True)
            with self.assertRaises(tool.DescriptorError):
                tool.discover_mcp_dir(Path(tmp))

    def test_unparseable_tags_are_counted_in_the_row_note(self) -> None:
        row = _check(_download("1.0.0"), _github(("engram-v1.2", False, False), ("nightly", False, False), ("v1.0.0", False, False)))
        self.assertEqual(row["status"], "up-to-date")
        self.assertIn("2 unparseable", row["detail"])
        self.assertIn("engram-v1.2", row["detail"])

    def test_missing_frontmatter_is_an_error(self) -> None:
        with self.assertRaises(tool.DescriptorError):
            tool.parse_descriptor("no frontmatter", "x.md")


class MainTests(unittest.TestCase):
    def _run(self, argv: list[str], responses: dict[str, bytes | Exception]) -> tuple[int, str]:
        out = io.StringIO()
        with (
            mock.patch.object(tool, "default_fetch", _fake_fetch(responses)),
            mock.patch.object(sys, "argv", ["check_dependency_updates.py", *argv]),
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            return tool.main(), out.getvalue()

    def _mcp_dir(self, tmp: str, version: str) -> str:
        (Path(tmp) / "widget.md").write_text(
            "---\nname: widget\ndistribution: download\n"
            f"endpoint: https://github.com/acme/widget/releases/download/v{version}/w.tar.gz\n"
            f"version: {version}\n---\nbody\n",
            encoding="utf-8",
        )
        (Path(tmp) / "remote.md").write_text(
            "---\nname: remote\ndistribution: remote\nendpoint: https://example.com\n---\n", encoding="utf-8"
        )
        return tmp

    def test_report_only_exits_zero_even_with_updates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            code, out = self._run(
                ["--mcp-dir", self._mcp_dir(tmp, "1.0.0")], {GITHUB_URL: _github(("v1.1.0", False, False))}
            )
        self.assertEqual(code, 0)
        self.assertIn("update-available", out)
        self.assertIn("unversioned", out)

    def test_strict_exit_codes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mcp_dir = self._mcp_dir(tmp, "1.0.0")
            code, _ = self._run(["--strict", "--mcp-dir", mcp_dir], {GITHUB_URL: _github(("v1.1.0", False, False))})
            self.assertEqual(code, 1)
            code, _ = self._run(["--strict", "--mcp-dir", mcp_dir], {GITHUB_URL: _github(("v1.0.0", False, False))})
            self.assertEqual(code, 0)
            code, _ = self._run(["--strict", "--mcp-dir", mcp_dir], {GITHUB_URL: OSError("down")})
            self.assertEqual(code, 1)

    def test_bad_dir_exits_two(self) -> None:
        code, _ = self._run(["--mcp-dir", "/nonexistent/dir"], {})
        self.assertEqual(code, 2)

    def test_ambiguous_default_dir_exits_two(self) -> None:
        with mock.patch.object(tool, "discover_mcp_dir", side_effect=tool.DescriptorError("two found")):
            code, _ = self._run([], {})
        self.assertEqual(code, 2)

    def test_unparseable_descriptor_exits_two(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "bad.md").write_text("not a descriptor", encoding="utf-8")
            code, _ = self._run(["--mcp-dir", tmp], {})
        self.assertEqual(code, 2)

    def test_json_output_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            code, out = self._run(
                ["--format", "json", "--mcp-dir", self._mcp_dir(tmp, "1.0.0")],
                {GITHUB_URL: _github(("v2.0.0", False, False))},
            )
        self.assertEqual(code, 0)
        payload = json.loads(out)
        rows = {row["name"]: row for row in payload["dependencies"]}
        self.assertEqual(set(rows["widget"]), {"name", "distribution", "current", "status", "latest", "latest_major", "detail"})
        self.assertEqual(rows["widget"]["status"], "major-available")
        self.assertEqual(rows["remote"]["status"], "unversioned")

    def test_text_notes_for_zero_x_npm(self) -> None:
        text = tool.render_text([tool.check_descriptor(_npm_descriptor("0.0.1"), _fake_fetch({NPM_URL: _npm("0.0.2")}), 5)])
        self.assertIn("playwright-package-lock.json", text)
        self.assertIn("checksum", text)


if __name__ == "__main__":
    unittest.main()
