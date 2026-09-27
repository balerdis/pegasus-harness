"""`pegasus directory grant`/`revoke` across every registered adapter --
derived from `adapters.available()` rather than a hand-written CLI list, so
a third adapter this product ships later is exercised here without anyone
having to remember to add it.

Before this change, Claude Code's own `directory grant` validated the path,
recorded it in the journal, and reported `"claudecode: granted <path> to
every agent."` while rendering nothing at all into `settings.json` -- a
report that claimed an effect the command never had. The product decision
behind this: external directories are already allowed by default outside a
fixed deny floor, in both CLIs alike (see `docs/arquitectura/arquitectura.md`'s
7.3.0 section), so a per-directory Claude Code grant has nothing to add.
`directory_grant`'s `dormant` flag and `_directory_prose`'s wording are what
make the report honest instead of silently wrong.

OpenCode's own report keeps its existing wording (`test_cli_directory.py`
already covers OpenCode end to end, including the deny-floor-shadow warning);
this file only adds what did not exist before: a check that every adapter's
report matches what that adapter's own render actually does.
"""
from __future__ import annotations

import io
import json

from pegasus import cli
from pegasus.adapters import available
from pegasus.adapters.opencode.manifest import CLI_ID as OPENCODE_CLI_ID
from pegasus.adapters.claudecode.manifest import CLI_ID as CLAUDECODE_CLI_ID
from pegasus.core.types import Environment
from real_home import RealHomeTestCase as _RealHomeTestCase

AT = "2026-08-14T00:00:00+00:00"
NO_BINARY = {"PATH": ""}


class RealHomeTestCase(_RealHomeTestCase):
    def runtime(self) -> cli.Runtime:
        return cli.Runtime(
            filesystem=self.filesystem, home=self.home, now=AT, out=io.StringIO(), variables=NO_BINARY
        )

    def layout(self, cli_id: str):
        return available().get(cli_id).layout(Environment(home=self.home))

    def run_cli(self, *argv) -> tuple[int, dict]:
        context = self.runtime()
        code = cli.main([*argv, "--json"], runtime=context)
        return code, json.loads(context.out.getvalue())

    def run_prose(self, *argv) -> tuple[int, str]:
        context = self.runtime()
        code = cli.main(list(argv), runtime=context)
        return code, context.out.getvalue()

    def install(self, cli_id: str) -> None:
        self.layout(cli_id).config_dir.mkdir(parents=True, exist_ok=True)
        code, _ = self.run_cli("install", "--cli", cli_id)
        self.assertEqual(code, 0)

    def own_directory(self, name: str = "extra") -> str:
        target = self.home / "worktrees" / name
        target.mkdir(parents=True, exist_ok=True)
        return str(target)


class GrantSucceedsForEveryRegisteredAdapterTest(RealHomeTestCase):
    def test_grant_records_the_path_for_every_adapter(self):
        for cli_id in available().ids():
            with self.subTest(cli=cli_id):
                self.install(cli_id)
                path = self.own_directory(cli_id)
                code, report = self.run_cli("directory", "grant", "--cli", cli_id, path)
                self.assertEqual(code, 0, report)
                self.assertEqual(report["action"], "grant")
                self.assertIn(path, report["granted_directories"])

    def test_revoke_is_a_no_op_at_exit_0_for_every_adapter_that_never_granted(self):
        for cli_id in available().ids():
            with self.subTest(cli=cli_id):
                self.install(cli_id)
                code, report = self.run_cli(
                    "directory", "revoke", "--cli", cli_id, self.own_directory(f"{cli_id}-revoke")
                )
                self.assertEqual(code, 0, report)
                self.assertEqual(report["status"], "already-revoked")


class ReportTextIsHonestPerAdapterTest(RealHomeTestCase):
    """Both CLIs are "dormido y honesto" now, in the user's own words: every
    adapter registered today already allows external directories by default
    (`CliAdapter.directory_grant_behavior().allowed_by_default`), so a grant
    changes nothing on either of them, and both reports say so. What
    differs is only whether that CLI still writes a rule of its own for the
    path (`writes_own_entry`) -- OpenCode does (dormant, not inert: it would
    regain meaning if its baseline ever asked again), Claude Code does not
    (there is no per-directory permission to write at all).
    """

    def test_opencode_report_says_recorded_wrote_its_own_entry_and_changes_nothing_today(self):
        self.install(OPENCODE_CLI_ID)
        path = self.own_directory("opencode-wording")
        _, output = self.run_prose("directory", "grant", "--cli", OPENCODE_CLI_ID, path)
        self.assertIn(f"recorded {path}", output)
        self.assertIn(f'"{path}/*": "allow"', output)
        self.assertIn("changes nothing today", output)
        self.assertIn("already allowed by default", output)
        self.assertNotIn("granted", output)

    def test_claudecode_report_says_recorded_nothing_needed_writing_and_changes_nothing_today(self):
        self.install(CLAUDECODE_CLI_ID)
        path = self.own_directory("claudecode-wording")
        _, output = self.run_prose("directory", "grant", "--cli", CLAUDECODE_CLI_ID, path)
        self.assertIn(f"recorded {path}", output)
        self.assertIn("nothing needed writing", output)
        self.assertIn("changes nothing today", output)
        self.assertIn("already allowed by default", output)
        self.assertNotIn("granted", output)

    def test_opencode_revoke_says_its_own_entry_was_removed(self):
        self.install(OPENCODE_CLI_ID)
        path = self.own_directory("opencode-revoke-wording")
        self.run_cli("directory", "grant", "--cli", OPENCODE_CLI_ID, path)
        _, output = self.run_prose("directory", "revoke", "--cli", OPENCODE_CLI_ID, path)
        self.assertIn(f"revoked {path}", output)
        self.assertIn("its own permission entry was removed", output)
        self.assertNotIn("nothing was written", output)

    def test_claudecode_revoke_says_nothing_was_written_to_unwrite(self):
        self.install(CLAUDECODE_CLI_ID)
        path = self.own_directory("claudecode-revoke-wording")
        self.run_cli("directory", "grant", "--cli", CLAUDECODE_CLI_ID, path)
        _, output = self.run_prose("directory", "revoke", "--cli", CLAUDECODE_CLI_ID, path)
        self.assertIn(f"{path} removed from the record", output)
        self.assertIn("nothing was written to unwrite", output)
        self.assertNotIn("revoked", output)
        self.assertNotIn("its own permission entry was removed", output)

    def test_claudecode_grant_is_still_recorded_in_the_journal_despite_being_dormant(self):
        from pegasus.core import journal as journal_module

        self.install(CLAUDECODE_CLI_ID)
        path = self.own_directory("claudecode-journal")
        self.run_cli("directory", "grant", "--cli", CLAUDECODE_CLI_ID, path)
        store = cli.journal_store(self.runtime())
        installed = journal_module.install_for(store.load(), CLAUDECODE_CLI_ID)
        self.assertIn(path, installed.granted_directories)

    def test_claudecode_grant_renders_nothing_new_in_settings_json(self):
        self.install(CLAUDECODE_CLI_ID)
        layout = self.layout(CLAUDECODE_CLI_ID)
        before = layout.settings_file.read_bytes()
        self.run_cli("directory", "grant", "--cli", CLAUDECODE_CLI_ID, self.own_directory("claudecode-render"))
        after = layout.settings_file.read_bytes()
        self.assertEqual(before, after, "a dormant grant must not change the rendered settings file")

    def test_the_report_text_is_derived_from_each_adapters_declared_behavior(self):
        """The load-bearing guard: build the expected sentence purely from
        `adapter.directory_grant_behavior()` -- never from `adapter.id` --
        for every registered adapter, and check the real report matches.
        A future adapter registered with a different id, or a different
        `allowed_by_default`/`writes_own_entry` combination, is covered by
        this loop without anyone adding a branch for it."""
        for cli_id in available().ids():
            with self.subTest(cli=cli_id):
                self.install(cli_id)
                path = self.own_directory(f"{cli_id}-derived")
                behavior = available().get(cli_id).directory_grant_behavior()
                _, report = self.run_cli("directory", "grant", "--cli", cli_id, path)
                self.assertEqual(report["allowed_by_default"], behavior.allowed_by_default)
                self.assertEqual(report["writes_own_entry"], behavior.writes_own_entry)
                _, output = self.run_prose("directory", "grant", "--cli", cli_id, self.own_directory(f"{cli_id}-prose"))
                if behavior.allowed_by_default:
                    self.assertIn("changes nothing today", output)
                    if behavior.writes_own_entry:
                        self.assertIn("wrote", output)
                    else:
                        self.assertIn("nothing needed writing", output)
                else:
                    self.assertIn("to every agent", output)
                revoke_path = self.own_directory(f"{cli_id}-derived-revoke")
                self.run_cli("directory", "grant", "--cli", cli_id, revoke_path)
                _, revoke_report = self.run_cli("directory", "revoke", "--cli", cli_id, revoke_path)
                self.assertEqual(revoke_report["writes_own_entry"], behavior.writes_own_entry)
                revoke_text = cli._directory_prose(revoke_report)
                if behavior.writes_own_entry:
                    self.assertIn("its own permission entry was removed", revoke_text)
                else:
                    self.assertIn("nothing was written to unwrite", revoke_text)


class NoAdapterIdComparisonDrivesTheReportTest(RealHomeTestCase):
    """Static guard for the exact regressions this section exists to catch.

    Every fact `directory_grant`/`directory_revoke` report -- whether a
    grant is dormant, whether it writes its own entry, and whether a
    granted path falls under a deny floor -- must come from the adapter's
    own declared `DirectoryGrantBehavior`, never from comparing `adapter.id`
    against a literal. The first cut of the floor-shadow warning still
    special-cased `adapter.id == OPENCODE_CLI_ID`; that was itself the same
    hexagonal violation moved rather than fixed, caught by review before it
    shipped. This guard now forbids the comparison entirely, in both
    functions, with no exemption."""

    def test_directory_grant_never_compares_adapter_id(self):
        import inspect

        source = inspect.getsource(cli.directory_grant)
        self.assertIn("directory_grant_behavior", source)
        self.assertNotIn("adapter.id ==", source)
        self.assertNotIn("adapter.id !=", source)
        self.assertNotIn("OPENCODE_CLI_ID", source)

    def test_directory_revoke_never_compares_adapter_id(self):
        import inspect

        source = inspect.getsource(cli.directory_revoke)
        self.assertIn("directory_grant_behavior", source)
        self.assertNotIn("adapter.id ==", source)
        self.assertNotIn("adapter.id !=", source)
        self.assertNotIn("OPENCODE_CLI_ID", source)

    def test_cli_module_no_longer_imports_the_opencode_render_module_for_this(self):
        """The shared CLI layer must not import an adapter's render module
        to answer a CLI-agnostic question -- `content.deny_floor_shadows`
        is what makes that import unnecessary."""
        import inspect

        source = inspect.getsource(cli)
        self.assertNotIn("opencode_render_module", source)
        self.assertNotIn("from pegasus.adapters.opencode import render", source)

    def test_every_adapter_with_a_deny_floor_warns_on_a_shadowed_grant(self):
        """Derived over `adapters.available()`: a grant under each floor
        directory must warn on every adapter that declares
        `has_deny_floor=True` -- not only OpenCode."""
        from pegasus.core.content import DENY_FLOOR_DIRECTORIES

        for cli_id in available().ids():
            adapter = available().get(cli_id)
            behavior = adapter.directory_grant_behavior()
            if not behavior.has_deny_floor:
                continue
            for name in DENY_FLOOR_DIRECTORIES:
                with self.subTest(cli=cli_id, floor=name):
                    self.install(cli_id)
                    path = str(self.home / f"shadow-{cli_id}-{name.replace('/', '-')}" / name)
                    code, report = self.run_cli("directory", "grant", "--cli", cli_id, path)
                    self.assertEqual(code, 0, report)
                    self.assertIn("warning", report, report)
                    self.assertIn("never take effect", report["warning"])


if __name__ == "__main__":
    import unittest

    unittest.main()
