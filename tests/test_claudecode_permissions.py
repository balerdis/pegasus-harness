"""Claude Code's `settings.json` `permissions.allow`/`permissions.deny`:
external directories allowed by default, with a fixed deny floor -- the same
product decision already taken for OpenCode's `external_directory` baseline,
now applied to this CLI's own permission vocabulary.

Measured live against a throwaway user on 2026-09-27 (not assumed from
Claude Code's documentation):
  - `permissions.allow: ["Read(//**)", "Edit(//**)"]` makes reads AND writes
    outside the working directory proceed without prompts.
  - `permissions.deny` with `Read(//**/<dir>/**)` and `Edit(//**/<dir>/**)`
    for each floor directory blocks Read, Edit/Write, and a Bash `cat` of
    those paths (verified for `.ssh`, `.config/gh` and `secrets`).
  - `Write(path)` rules are never consulted; `additionalDirectories` only
    grants reads, never writes.

These constants and `permission_artifacts` are this adapter's rendering of
`content.DENY_FLOOR_DIRECTORIES`, the one CLI-agnostic floor list both
adapters now derive from.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from pegasus.adapters.claudecode import render as render_module
from pegasus.core.content import DENY_FLOOR_DIRECTORIES
from pegasus.core.types import ConfigKeyArtifact, Layout

LAYOUT = Layout(config_dir=Path("/home/probe/.claude"), settings_file=Path("/home/probe/.claude/settings.json"))


class PermissionsAllowTest(unittest.TestCase):
    def test_allow_grants_read_and_edit_at_the_filesystem_root(self):
        self.assertEqual(render_module.PERMISSIONS_ALLOW, ("Read(//**)", "Edit(//**)"))

    def test_no_write_rule_is_ever_emitted(self):
        """`Write(path)` rules are documented as never consulted -- emitting
        one would be dead configuration mistaken for a real guard."""
        self.assertFalse(any(rule.startswith("Write(") for rule in render_module.PERMISSIONS_ALLOW))
        self.assertFalse(any(rule.startswith("Write(") for rule in render_module.PERMISSIONS_DENY_FLOOR))


class PermissionsDenyFloorTest(unittest.TestCase):
    def test_the_deny_floor_covers_every_core_directory_with_read_and_edit(self):
        expected = set()
        for name in DENY_FLOOR_DIRECTORIES:
            expected.add(f"Read(//**/{name}/**)")
            expected.add(f"Edit(//**/{name}/**)")
        self.assertEqual(set(render_module.PERMISSIONS_DENY_FLOOR), expected)

    def test_two_rules_per_directory_read_then_edit(self):
        rules = render_module.PERMISSIONS_DENY_FLOOR
        for name in DENY_FLOOR_DIRECTORIES:
            read_rule = f"Read(//**/{name}/**)"
            edit_rule = f"Edit(//**/{name}/**)"
            self.assertLess(rules.index(read_rule), rules.index(edit_rule))

    def test_config_gh_keeps_its_two_path_segments(self):
        self.assertIn("Read(//**/.config/gh/**)", render_module.PERMISSIONS_DENY_FLOOR)
        self.assertIn("Edit(//**/.config/gh/**)", render_module.PERMISSIONS_DENY_FLOOR)


class PermissionArtifactsTest(unittest.TestCase):
    def test_every_artifact_is_an_append_at_the_settings_file(self):
        artifacts = render_module.permission_artifacts(LAYOUT)
        self.assertTrue(artifacts)
        for artifact in artifacts:
            self.assertIsInstance(artifact, ConfigKeyArtifact)
            self.assertEqual(artifact.path, LAYOUT.settings_file)
            self.assertIn(artifact.pointer, ("/permissions/allow/-", "/permissions/deny/-", "/permissions/ask/-"))

    def test_allow_values_match_permissions_allow_exactly(self):
        artifacts = render_module.permission_artifacts(LAYOUT)
        allow_values = [a.value for a in artifacts if a.pointer == "/permissions/allow/-"]
        self.assertEqual(allow_values, list(render_module.PERMISSIONS_ALLOW))

    def test_deny_values_match_permissions_deny_floor_exactly(self):
        artifacts = render_module.permission_artifacts(LAYOUT)
        deny_values = [a.value for a in artifacts if a.pointer == "/permissions/deny/-"]
        self.assertEqual(deny_values, list(render_module.PERMISSIONS_DENY_FLOOR))

    def test_a_git_push_asks_through_permissions_ask(self):
        """The 7.5.0 decision: every `git push` in the session asks, the
        plain, option-prefixed and argument-less forms alike."""
        artifacts = render_module.permission_artifacts(LAYOUT)
        ask_values = [a.value for a in artifacts if a.pointer == "/permissions/ask/-"]
        self.assertEqual(ask_values, list(render_module.PERMISSIONS_ASK))
        self.assertIn("Bash(git push *)", ask_values)
        self.assertIn("Bash(git * push *)", ask_values)
        self.assertIn("Bash(git * push)", ask_values)

    def test_every_artifact_id_is_unique(self):
        artifacts = render_module.permission_artifacts(LAYOUT)
        ids = [a.id for a in artifacts]
        self.assertEqual(len(ids), len(set(ids)), ids)

    def test_no_additional_directories_key_is_ever_written(self):
        """`additionalDirectories` only grants reads, never writes -- it must
        never stand in for these two rules anywhere this adapter renders."""
        artifacts = render_module.permission_artifacts(LAYOUT)
        self.assertFalse(any("additionalDirectories" in a.pointer for a in artifacts))


if __name__ == "__main__":
    unittest.main()
