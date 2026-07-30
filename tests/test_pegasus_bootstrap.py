from __future__ import annotations

import ast
import importlib.machinery
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

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

    def ownership_target(self, root: Path) -> dict[str, Path]:
        return {
            "home": root,
            "config": root / "config" / "opencode",
            "data": root / "data" / "pegasus-harness",
            "state": root / "data" / "pegasus-harness" / ".pegasus-harness-state.json",
            "backup_root": root / "backups",
            "bin": root / "local" / "bin",
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


if __name__ == "__main__":
    unittest.main()
