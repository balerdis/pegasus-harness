"""What `doctor`, `install` and `update` say when a CLI is going to read files
that belong to another CLI.

OpenCode falls back to Claude Code's own `~/.claude/CLAUDE.md` as global
instructions when `~/.config/opencode/AGENTS.md` does not exist, and always
scans `~/.claude/skills/**/SKILL.md`. Pegasus ships no global `AGENTS.md`, so
on a machine that has both CLIs the orchestrator silently obeys rules written
for the other one. The fact is the OpenCode adapter's to declare
(`CliAdapter.foreign_loads()`); `core.foreign_loads` evaluates and words it
generically, so no shared code compares an adapter id against a literal.

Every HOME here is a throwaway directory the base class creates; the
environment is controlled through `mock.patch.dict(os.environ, ...)` and read
back into the `Runtime` the way `default_runtime` does.
"""
from __future__ import annotations

import io
import json
import os
from unittest import mock

from pegasus import cli
from pegasus.adapters import available
from pegasus.adapters.claudecode.manifest import CLI_ID as CLAUDECODE_CLI_ID
from pegasus.adapters.opencode.manifest import CLI_ID as OPENCODE_CLI_ID
from pegasus.core import foreign_loads
from pegasus.core.types import ForeignLoad
from real_home import RealHomeTestCase

AT = "2026-08-14T00:00:00+00:00"
ALL = "OPENCODE_DISABLE_CLAUDE_CODE"
PROMPT = "OPENCODE_DISABLE_CLAUDE_CODE_PROMPT"
SKILLS = "OPENCODE_DISABLE_CLAUDE_CODE_SKILLS"
MARKER = "reads the environment of the shell running"


class ForeignLoadsTestCase(RealHomeTestCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.dict(os.environ)
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in (ALL, PROMPT, SKILLS):
            os.environ.pop(name, None)
        self.opencode_dir = self.home / ".config" / "opencode"
        self.opencode_dir.mkdir(parents=True)

    def runtime(self) -> cli.Runtime:
        variables = {**os.environ, "PATH": ""}
        return cli.Runtime(
            filesystem=self.filesystem, home=self.home, now=AT, out=io.StringIO(), variables=variables
        )

    def run_cli(self, *argv):
        context = self.runtime()
        code = cli.main([*argv, "--json"], runtime=context)
        return code, json.loads(context.out.getvalue())

    def run_prose(self, *argv):
        context = self.runtime()
        code = cli.main(list(argv), runtime=context)
        return code, context.out.getvalue()

    def put_claude_md(self):
        claude = self.home / ".claude"
        claude.mkdir(exist_ok=True)
        (claude / "CLAUDE.md").write_text("rules for the other CLI", encoding="utf-8")

    def put_skills(self, *names):
        for name in names:
            directory = self.home / ".claude" / "skills" / name
            directory.mkdir(parents=True)
            (directory / "SKILL.md").write_text("---\nname: x\n---\n", encoding="utf-8")

    def doctor_entry(self, cli_id=OPENCODE_CLI_ID) -> dict:
        code, report = self.run_cli("doctor")
        self.assertEqual(code, 0)
        return next(entry for entry in report["clis"] if entry["cli"] == cli_id)

    def kinds(self, entry) -> dict:
        return {item["kind"]: item for item in entry.get("foreign_loads", [])}


class DoctorForeignLoadsTest(ForeignLoadsTestCase):
    def test_instructions_notice_names_the_variable_that_turns_it_off(self):
        self.put_claude_md()
        item = self.kinds(self.doctor_entry())["instructions"]
        self.assertIn(PROMPT, item["disabled_by"])
        _, prose = self.run_prose("doctor")
        self.assertIn(".claude/CLAUDE.md", prose)
        self.assertIn(PROMPT, prose)
        self.assertIn(MARKER, prose)
        self.assertNotIn("skills from", prose)

    def test_skills_notice_gives_the_count_precedence_and_variable(self):
        self.put_skills("one", "two")
        item = self.kinds(self.doctor_entry())["skills"]
        self.assertEqual(item["count"], 2)
        _, prose = self.run_prose("doctor")
        self.assertIn("2 skills", prose)
        self.assertIn("takes precedence", prose)
        self.assertIn(SKILLS, prose)
        self.assertIn(MARKER, prose)

    def test_one_skill_is_singular(self):
        self.put_skills("one")
        _, prose = self.run_prose("doctor")
        self.assertIn("1 skill from", prose)

    def test_nested_skill_files_are_counted(self):
        nested = self.home / ".claude" / "skills" / "group" / "inner"
        nested.mkdir(parents=True)
        (nested / "SKILL.md").write_text("x", encoding="utf-8")
        self.assertEqual(self.kinds(self.doctor_entry())["skills"]["count"], 1)

    def test_a_skills_directory_without_any_skill_file_is_no_notice(self):
        (self.home / ".claude" / "skills" / "empty").mkdir(parents=True)
        self.assertEqual(self.kinds(self.doctor_entry()), {})

    def test_each_variable_suppresses_only_its_own_part(self):
        self.put_claude_md()
        self.put_skills("one")
        cases = {PROMPT: {"skills"}, SKILLS: {"instructions"}, ALL: set()}
        for variable, remaining in cases.items():
            with self.subTest(variable=variable), mock.patch.dict(os.environ, {variable: "1"}):
                self.assertEqual(set(self.kinds(self.doctor_entry())), remaining)

    def test_both_notices_when_nothing_is_set(self):
        self.put_claude_md()
        self.put_skills("one")
        self.assertEqual(set(self.kinds(self.doctor_entry())), {"instructions", "skills"})

    def test_a_falsy_value_does_not_count_as_set(self):
        self.put_claude_md()
        with mock.patch.dict(os.environ, {PROMPT: "0"}):
            self.assertIn("instructions", self.kinds(self.doctor_entry()))

    def test_an_own_global_agents_file_suppresses_only_the_instructions_notice(self):
        self.put_claude_md()
        self.put_skills("one")
        (self.opencode_dir / "AGENTS.md").write_text("mine", encoding="utf-8")
        self.assertEqual(set(self.kinds(self.doctor_entry())), {"skills"})

    def test_no_claude_directory_at_all_is_no_notice_and_no_key(self):
        self.assertNotIn("foreign_loads", self.doctor_entry())
        _, prose = self.run_prose("doctor")
        self.assertNotIn(MARKER, prose)

    def test_the_claude_code_adapter_yields_nothing(self):
        self.put_claude_md()
        self.put_skills("one")
        self.assertNotIn("foreign_loads", self.doctor_entry(CLAUDECODE_CLI_ID))

    def test_the_files_are_never_read(self):
        self.put_claude_md()
        self.put_skills("one")
        with mock.patch.object(type(self.filesystem), "read_bytes", side_effect=AssertionError("read")):
            self.doctor_entry()


class InstallAndUpdateForeignLoadsTest(ForeignLoadsTestCase):
    def test_install_and_update_report_the_same_notice_as_doctor(self):
        self.put_claude_md()
        self.put_skills("one")
        doctor_lines = foreign_loads.notice_lines(
            self.doctor_entry()["foreign_loads"],
            cli_name="OpenCode",
            program_name="pegasus",
            product_name="Pegasus",
        )
        self.assertTrue(doctor_lines)
        for command in ("install", "update"):
            with self.subTest(command=command):
                argv = (command, "--cli", OPENCODE_CLI_ID)
                code, report = self.run_cli(*argv)
                self.assertEqual(code, 0)
                self.assertEqual({item["kind"] for item in report["foreign_loads"]}, {"instructions", "skills"})
                _, prose = self.run_prose(*argv)
                for line in doctor_lines:
                    self.assertIn(line, prose)
                self.assertEqual(prose.count(MARKER), 1)

    def test_no_notice_when_suppressed(self):
        self.put_claude_md()
        self.put_skills("one")
        with mock.patch.dict(os.environ, {ALL: "1"}):
            code, report = self.run_cli("install", "--cli", OPENCODE_CLI_ID)
            _, prose = self.run_prose("install", "--cli", OPENCODE_CLI_ID)
        self.assertEqual(code, 0)
        self.assertNotIn("foreign_loads", report)
        self.assertNotIn(MARKER, prose)

    def test_claude_code_install_has_no_notice(self):
        self.put_claude_md()
        self.put_skills("one")
        code, report = self.run_cli("install", "--cli", CLAUDECODE_CLI_ID)
        self.assertEqual(code, 0)
        self.assertNotIn("foreign_loads", report)


class PortDeclarationTest(ForeignLoadsTestCase):
    def test_opencode_declares_and_claude_code_does_not(self):
        registry = available()
        opencode = registry.get(OPENCODE_CLI_ID).foreign_loads()
        self.assertEqual({item.kind for item in opencode}, {"instructions", "skills"})
        self.assertTrue(all(isinstance(item, ForeignLoad) for item in opencode))
        self.assertEqual(registry.get(CLAUDECODE_CLI_ID).foreign_loads(), ())

    def test_registry_refuses_an_adapter_that_declares_the_wrong_shape(self):
        from pegasus.core.registry import ManifestMismatchError, Registry

        adapter = available().get(OPENCODE_CLI_ID)

        class Wrong:
            def __getattr__(self, name):
                return getattr(adapter, name)

            def foreign_loads(self):
                return ["not a ForeignLoad"]

        with self.assertRaises(ManifestMismatchError):
            Registry(Wrong())

    def test_registry_refuses_an_adapter_that_does_not_implement_it(self):
        from pegasus.core.registry import ManifestMismatchError, Registry

        adapter = available().get(OPENCODE_CLI_ID)

        class Missing:
            def __getattr__(self, name):
                if name == "foreign_loads":
                    raise AttributeError(name)
                return getattr(adapter, name)

        with self.assertRaises(ManifestMismatchError):
            Registry(Missing())

    def test_evaluate_is_generic_over_any_declaration(self):
        load = ForeignLoad(
            kind="instructions",
            owner="Other",
            path=".other/RULES.md",
            disabled_by=("OFF",),
        )
        (self.home / ".other").mkdir()
        (self.home / ".other" / "RULES.md").write_text("x", encoding="utf-8")
        found = foreign_loads.evaluate(self.filesystem, self.home, {}, (load,))
        self.assertEqual([item["kind"] for item in found], ["instructions"])
        self.assertEqual(foreign_loads.evaluate(self.filesystem, self.home, {"OFF": "1"}, (load,)), [])
