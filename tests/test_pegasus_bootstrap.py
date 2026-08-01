from __future__ import annotations

import ast
import importlib.machinery
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bin" / "pegasus"


def load_bootstrap():
    loader = importlib.machinery.SourceFileLoader("pegasus_bootstrap", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class PegasusBootstrapTests(unittest.TestCase):
    def test_installer_is_python_syntax_valid(self) -> None:
        ast.parse(SCRIPT.read_text(encoding="utf-8"))

    def test_install_contract_uses_official_safe_installers(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("https://opencode.ai/install", source)
        self.assertIn("DeusData/codebase-memory-mcp/main/install.sh", source)
        self.assertIn("--skip-config", source)
        self.assertIn("sudo", source)
        self.assertIn("-u", source)

    def test_template_has_portable_prompt_references(self) -> None:
        config = json.loads((ROOT / "source" / "opencode" / "opencode.json").read_text())
        for agent in config["agent"].values():
            prompt = agent.get("prompt")
            if isinstance(prompt, str) and prompt.startswith("{file:"):
                self.assertFalse(prompt.startswith("{file:/"))

    def test_materialized_policy_excludes_legacy_and_native_review_runtime(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('name.startswith(("review-", "jd-"))', source)
        self.assertIn('"forbidden legacy runtime reference:', source)
        self.assertIn('retired_graph = "code" + "graph"', source)

    def test_launcher_resolves_the_official_user_local_opencode_location(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("def resolve_opencode", source)
        self.assertIn('home() / ".opencode" / "bin" / "opencode"', source)
        self.assertIn("OpenCode executable not found", source)
        self.assertIn('if args.run_command[0] == "opencode"', source)

    def test_launcher_resolves_opencode_from_target_login_shell_path(self) -> None:
        module = load_bootstrap()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            executable = root / "nvm" / "bin" / "opencode"
            executable.parent.mkdir(parents=True)
            executable.write_text("#!/bin/sh\nexit 0\n")
            executable.chmod(0o755)
            module.home = lambda: root
            original_run = module.subprocess.run
            try:
                module.subprocess.run = lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=f"{executable}\n")
                resolved, source, discovered = module.resolve_opencode({"PATH": "/missing"})
            finally:
                module.subprocess.run = original_run
            self.assertEqual(source, "target login-shell PATH")
            self.assertEqual(discovered, executable)
            self.assertEqual(resolved, executable.resolve())

    def ownership_target(self, root: Path) -> dict[str, Path]:
        return {
            "home": root,
            "config": root / "config" / "opencode",
            "data": root / "data" / "pegasus-harness",
            "state": root / "data" / "pegasus-harness" / ".pegasus-harness-state.json",
            "backup_root": root / "backups",
            "bin": root / "local" / "bin",
            "claude": root / "claude",
        }

    def materialize_for_ownership_test(self, module, target: dict[str, Path]) -> None:
        backup = target["backup_root"] / "initial"
        backup.mkdir(parents=True)
        cbm = target["bin"] / "codebase-memory-mcp"
        cbm.parent.mkdir(parents=True, exist_ok=True)
        cbm.write_text("placeholder")
        module.materialize(target, backup, cbm)

    def test_uninstall_preserves_post_install_files_in_shared_directories(self) -> None:
        module = load_bootstrap()
        with tempfile.TemporaryDirectory() as temporary:
            target = self.ownership_target(Path(temporary))
            self.materialize_for_ownership_test(module, target)
            agent = target["config"] / "agents" / "user-added.md"
            prompt = target["config"] / "prompts" / "user-added.md"
            agent.write_text("user agent")
            prompt.write_text("user prompt")
            module.paths = lambda: target
            self.assertEqual(module.uninstall_internal(), 0)
            self.assertEqual(agent.read_text(), "user agent")
            self.assertEqual(prompt.read_text(), "user prompt")

    def test_uninstall_restores_preexisting_launcher(self) -> None:
        module = load_bootstrap()
        with tempfile.TemporaryDirectory() as temporary:
            target = self.ownership_target(Path(temporary))
            launcher = target["bin"] / "pegasus"
            launcher.parent.mkdir(parents=True)
            launcher.write_text("previous launcher")
            self.materialize_for_ownership_test(module, target)
            module.paths = lambda: target
            self.assertEqual(module.uninstall_internal(), 0)
            self.assertTrue(launcher.is_file())
            self.assertEqual(launcher.read_text(), "previous launcher")

    def test_refresh_launcher_atomically_updates_owned_stale_launcher(self) -> None:
        module = load_bootstrap()
        with tempfile.TemporaryDirectory() as temporary:
            target = self.ownership_target(Path(temporary))
            installed = target["data"] / "bin" / "pegasus"
            installed.parent.mkdir(parents=True)
            installed.write_text("stale launcher")
            installed.chmod(0o755)
            target["state"].write_text(json.dumps({
                "schema": "pegasus-harness-migration/v1",
                "ownership": [{"path": str(installed), "kind": "file", "sha256": module.digest(installed), "backup": None}],
            }))
            module.paths = lambda: target
            module.ensure_prerequisites = lambda: None
            self.assertEqual(module.refresh_launcher_internal(), 0)
            self.assertEqual(installed.read_bytes(), SCRIPT.read_bytes())
            state = json.loads(target["state"].read_text())
            self.assertEqual(state["ownership"][0]["sha256"], module.digest(installed))

    def test_post_migration_integrity_mode_accepts_exact_manifest_and_integrations(self) -> None:
        module = load_bootstrap()
        with tempfile.TemporaryDirectory() as temporary:
            target = self.ownership_target(Path(temporary))
            config = {
                "default_agent": "pegasus-orchestrator",
                "agent": {name: {} for name in module.JD_AGENT_NAMES},
                "provider": {"preserved-provider": {}},
                "mcp": {"preserved-mcp": {}, "codebase-memory-mcp": {}},
            }
            ownership = []
            for index in range(3):
                asset = Path(temporary) / "owned" / str(index)
                asset.parent.mkdir(parents=True, exist_ok=True)
                asset.write_text(str(index))
                ownership.append({"path": str(asset), "kind": "file", "sha256": module.digest(asset), "backup": None})
            state = {
                "schema": "pegasus-harness-migration/v1", "ownership": ownership,
                "managed_agents": list(module.JD_AGENT_NAMES),
                "preserved_integrations": {"providers": ["preserved-provider"], "mcps": ["preserved-mcp"]},
            }
            self.assertEqual(module.migration_integrity_errors(target, state, config), [])

    def test_claude_code_install_uses_only_adapter_and_canonical_skills(self) -> None:
        module = load_bootstrap()
        with tempfile.TemporaryDirectory() as temporary:
            target = self.ownership_target(Path(temporary))
            backup = target["backup_root"] / "initial"
            backup.mkdir(parents=True)
            module.materialize(target, backup, target["bin"] / "unused", ("claude-code",))
            self.assertTrue((target["claude"] / "CLAUDE.md").is_file())
            self.assertTrue((target["claude"] / "skills" / "laravel-security" / "SKILL.md").is_file())
            self.assertFalse((target["config"] / "opencode.json").exists())

    def test_canonical_skills_include_bundled_references_without_machine_paths(self) -> None:
        module = load_bootstrap()
        assets = {relative.as_posix() for _, relative in module.skill_asset_files()}
        self.assertIn("laravel-security/references/laravel-security-checklist.md", assets)
        matrix = (ROOT / "source/core/skills/skill-versiones-estandar-asi/references/version-matrix.md").read_text()
        self.assertIn("organization-controlled ASI v6.4 standard", matrix)
        self.assertNotIn("/home/serg/", matrix)

    def test_migration_materializes_only_canonical_skills_without_legacy_gentle_literals(self) -> None:
        module = load_bootstrap()
        with tempfile.TemporaryDirectory() as temporary:
            target = self.ownership_target(Path(temporary))
            config_path = target["config"] / "opencode.json"
            config_path.parent.mkdir(parents=True)
            config_path.write_text(json.dumps({"agent": {"king-gentleman": {}}, "mcp": {}, "plugin": []}))
            cbm = target["bin"] / "codebase-memory-mcp"
            cbm.parent.mkdir(parents=True)
            cbm.write_text("placeholder")
            cbm.chmod(0o755)
            module.paths = lambda: target
            module.ensure_prerequisites = lambda: None

            self.assertEqual(module.migrate_internal(), 0)

            skill_root = target["config"] / "skills"
            actual = {path.relative_to(skill_root) for path in skill_root.rglob("*") if path.is_file()}
            canonical = {relative for _, relative in module.skill_asset_files()}
            legacy = {
                path.relative_to(ROOT / "source" / "opencode" / "skills")
                for path in (ROOT / "source" / "opencode" / "skills").rglob("*") if path.is_file()
            }
            self.assertEqual(actual, canonical)
            self.assertFalse(actual & legacy)
            self.assertNotIn("gentle", config_path.read_text().lower())
            for path in skill_root.rglob("*"):
                if path.is_file():
                    self.assertNotIn("gentle", path.read_text().lower())
            self.assertTrue((target["config"] / "commands" / "sdd-apply.md").is_file())
            self.assertTrue((target["config"] / "prompts" / "sdd" / "sdd-apply.md").is_file())
            self.assertTrue((target["config"] / "plugins" / "pegasus-skill-registry.ts").is_file())

    def test_migration_retires_known_legacy_skill_and_preserves_unknown_skill(self) -> None:
        module = load_bootstrap()
        with tempfile.TemporaryDirectory() as temporary:
            target = self.ownership_target(Path(temporary))
            config_path = target["config"] / "opencode.json"
            config_path.parent.mkdir(parents=True)
            config_path.write_text(json.dumps({"agent": {}, "mcp": {}, "plugin": []}))
            legacy_relative = Path("skill-creator") / "SKILL.md"
            legacy = target["config"] / "skills" / legacy_relative
            legacy.parent.mkdir(parents=True)
            legacy.write_text("known legacy skill")
            unknown = target["config"] / "skills" / "user-defined" / "SKILL.md"
            unknown.parent.mkdir(parents=True)
            unknown.write_text("user-defined skill")
            cbm = target["bin"] / "codebase-memory-mcp"
            cbm.parent.mkdir(parents=True)
            cbm.write_text("placeholder")
            cbm.chmod(0o755)
            module.paths = lambda: target
            module.ensure_prerequisites = lambda: None

            self.assertEqual(module.migrate_internal(), 0)

            self.assertFalse(legacy.exists())
            self.assertEqual(unknown.read_text(), "user-defined skill")
            state = json.loads(target["state"].read_text())
            entry = next(item for item in state["ownership"] if item["path"] == str(legacy))
            self.assertEqual(entry["kind"], "retired")
            self.assertEqual(Path(entry["backup"]["path"]).read_text(), "known legacy skill")

    def test_distribution_assets_are_checksum_manifested(self) -> None:
        manifest = json.loads((ROOT / "manifests" / "baseline-manifest.json").read_text())
        expected = {
            "source/adapters/claude-code/CLAUDE.md",
            "source/core/skills/laravel-security/SKILL.md",
            "source/core/skills/laravel-security/references/laravel-security-checklist.md",
            "source/core/skills/skill-versiones-estandar-asi/SKILL.md",
            "source/core/skills/skill-versiones-estandar-asi/references/provenance.md",
            "source/core/skills/skill-versiones-estandar-asi/references/version-matrix.md",
            "tools/build_release_manifest.py",
            "docs/release-distribution.md",
        }
        assets = {item["frozen_path"]: item["frozen_sha256"] for item in manifest["distribution_assets"]}
        self.assertEqual(set(assets), expected)
        for path, expected_digest in assets.items():
            self.assertEqual(load_bootstrap().digest(ROOT / path), expected_digest)

    def test_release_manifest_tool_requires_annotated_semantic_tags(self) -> None:
        tool = (ROOT / "tools/build_release_manifest.py").read_text()
        self.assertIn('git("cat-file", "-t", args.tag) != "tag"', tool)
        self.assertIn("SEMVER", tool)
        self.assertIn(".sha256", tool)

    def test_uninstall_preserves_modified_managed_file_and_keeps_manifest(self) -> None:
        module = load_bootstrap()
        with tempfile.TemporaryDirectory() as temporary:
            target = self.ownership_target(Path(temporary))
            self.materialize_for_ownership_test(module, target)
            config = target["config"] / "opencode.json"
            config.write_text(config.read_text() + "\nuser modification\n")
            module.paths = lambda: target
            self.assertEqual(module.uninstall_internal(), 1)
            self.assertTrue(config.exists())
            self.assertTrue(target["state"].exists())

    def test_migration_merges_config_without_losing_external_integrations(self) -> None:
        module = load_bootstrap()
        with tempfile.TemporaryDirectory() as temporary:
            target = self.ownership_target(Path(temporary))
            config_path = target["config"] / "opencode.json"
            config_path.parent.mkdir(parents=True)
            config_path.write_text(json.dumps({
                "$schema": "https://opencode.ai/config.json",
                "default_agent": "legacy",
                "agent": {"review-risk": {"mode": "subagent"}, "custom": {"mode": "subagent"}},
                "mcp": {
                    "engram": {"type": "local", "command": ["{env:ENGRAM_BIN}", "mcp"]},
                    "third-party": {"type": "remote", "url": "https://example.invalid/mcp", "headers": {"Authorization": "{env:EXTERNAL_TOKEN}"}},
                    "CodeGraph": {"type": "local", "command": ["retired"]},
                },
                "provider": {"external": {"options": {"apiKey": "{env:EXTERNAL_PROVIDER_KEY}"}}},
                "plugin": ["third-party-plugin"],
            }))
            cbm = target["bin"] / "codebase-memory-mcp"
            cbm.parent.mkdir(parents=True)
            cbm.write_text("placeholder")
            cbm.chmod(0o755)
            custom_command = target["config"] / "commands" / "third-party.md"
            custom_command.parent.mkdir(parents=True)
            custom_command.write_text("unrelated command")
            (target["config"] / "pegasus.env").write_text("ENGRAM_BIN=/opt/engram\nEXTERNAL_MCP_TOKEN={env:EXTERNAL_MCP_TOKEN}\n")
            module.paths = lambda: target
            module.ensure_prerequisites = lambda: None
            self.assertEqual(module.migrate_internal(), 0)
            migrated = json.loads(config_path.read_text())
            self.assertEqual(migrated["default_agent"], "pegasus-orchestrator")
            self.assertIn("pegasus-orchestrator", migrated["agent"])
            self.assertIn("custom", migrated["agent"])
            self.assertNotIn("review-risk", migrated["agent"])
            self.assertIn("engram", migrated["mcp"])
            self.assertIn("third-party", migrated["mcp"])
            self.assertNotIn("CodeGraph", migrated["mcp"])
            self.assertEqual(migrated["provider"]["external"]["options"]["apiKey"], "{env:EXTERNAL_PROVIDER_KEY}")
            self.assertIn("third-party-plugin", migrated["plugin"])
            self.assertEqual(custom_command.read_text(), "unrelated command")
            contract = (target["config"] / "pegasus.env").read_text()
            self.assertIn("ENGRAM_BIN=/opt/engram", contract)
            self.assertIn("EXTERNAL_MCP_TOKEN={env:EXTERNAL_MCP_TOKEN}", contract)
            state = json.loads(target["state"].read_text())
            self.assertEqual(state["schema"], "pegasus-harness-migration/v1")
            self.assertEqual(Path(state["backup"]).stat().st_mode & 0o777, 0o700)

    def test_migrate_repairs_missing_frozen_jd_agents_for_existing_migration(self) -> None:
        module = load_bootstrap()
        with tempfile.TemporaryDirectory() as temporary:
            target = self.ownership_target(Path(temporary))
            config_path = target["config"] / "opencode.json"
            config_path.parent.mkdir(parents=True)
            original = {
                "agent": {
                    "pegasus-orchestrator": {
                        "permission": {"task": {name: "allow" for name in module.JD_AGENT_NAMES}}
                    },
                    "custom": {"mode": "subagent"},
                },
                "mcp": {},
                "plugin": [],
                "provider": {"external": {"options": {"apiKey": "{env:EXTERNAL_PROVIDER_KEY}"}}},
            }
            config_path.write_text(json.dumps(original, indent=2) + "\n")
            cbm = target["bin"] / "codebase-memory-mcp"
            cbm.parent.mkdir(parents=True)
            cbm.write_text("placeholder")
            cbm.chmod(0o755)
            backup = target["backup_root"] / "initial"
            backup.mkdir(parents=True)
            backup_file = backup / "owned" / "0"
            backup_file.parent.mkdir()
            backup_file.write_text(config_path.read_text())
            contract_path = target["config"] / "pegasus.env"
            contract_path.write_text("ENGRAM_BIN=/opt/engram\n")
            state = {
                "schema": "pegasus-harness-migration/v1",
                "backup": str(backup),
                "ownership": [{
                    "path": str(config_path), "kind": "file", "sha256": module.digest(config_path),
                    "backup": {"kind": "file", "path": str(backup_file), "sha256": module.digest(backup_file)},
                }, {
                    "path": str(contract_path), "kind": "file", "sha256": module.digest(contract_path), "backup": None,
                }],
            }
            target["state"].parent.mkdir(parents=True)
            target["state"].write_text(json.dumps(state))
            module.paths = lambda: target
            module.ensure_prerequisites = lambda: None

            self.assertEqual(module.migrate_internal(), 0)

            repaired = json.loads(config_path.read_text())
            frozen = json.loads((ROOT / "source" / "opencode" / "opencode.json").read_text())
            self.assertEqual(set(module.JD_AGENT_NAMES) & set(repaired["agent"]), set(module.JD_AGENT_NAMES))
            for name in module.JD_AGENT_NAMES:
                self.assertEqual(repaired["agent"][name], frozen["agent"][name])
            self.assertEqual(repaired["agent"]["custom"], original["agent"]["custom"])
            self.assertEqual(repaired["provider"], original["provider"])
            updated_state = json.loads(target["state"].read_text())
            self.assertEqual(updated_state["managed_agents"], list(module.JD_AGENT_NAMES))
            self.assertEqual(updated_state["ownership"][0]["backup"]["path"], str(backup_file))

    def test_migration_retires_model_variants_and_rollback_restores_it(self) -> None:
        module = load_bootstrap()
        with tempfile.TemporaryDirectory() as temporary:
            target = self.ownership_target(Path(temporary))
            config_path = target["config"] / "opencode.json"
            config_path.parent.mkdir(parents=True)
            config_path.write_text(json.dumps({"agent": {}, "mcp": {}, "plugin": []}))
            legacy = target["config"] / "plugins" / "model-variants.ts"
            legacy.parent.mkdir(parents=True)
            legacy.write_text("legacy cache plugin")
            cbm = target["bin"] / "codebase-memory-mcp"
            cbm.parent.mkdir(parents=True)
            cbm.write_text("placeholder")
            cbm.chmod(0o755)
            module.paths = lambda: target
            module.ensure_prerequisites = lambda: None
            self.assertEqual(module.migrate_internal(), 0)
            self.assertFalse(legacy.exists())
            self.assertEqual(module.uninstall_internal(), 0)
            self.assertEqual(legacy.read_text(), "legacy cache plugin")

    def test_migration_refuses_to_retire_a_plugin_still_referenced_by_config(self) -> None:
        module = load_bootstrap()
        with self.assertRaisesRegex(RuntimeError, "references model-variants"):
            module.assert_retirement_safe({"plugin": ["file://model-variants.ts"]}, Path("/tmp/missing"))


if __name__ == "__main__":
    unittest.main()
