from __future__ import annotations

import ast
import hashlib
import importlib.machinery
import importlib.util
import json
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bin" / "pegasus"


def load_bootstrap():
    loader = importlib.machinery.SourceFileLoader("pegasus_bootstrap", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class PegasusBootstrapTests(unittest.TestCase):
    def test_python_and_shell_entrypoints_are_valid(self) -> None:
        ast.parse(SCRIPT.read_text(encoding="utf-8"))
        subprocess.run(["bash", "-n", str(ROOT / "install.sh")], check=True)

    def test_release_wrapper_has_required_boundary_checks(self) -> None:
        source = (ROOT / "install.sh").read_text(encoding="utf-8")
        self.assertIn("[[ $(id -u) -eq 0 ]]", source)
        self.assertIn("--target-user <linux-user> is required", source)
        self.assertIn("sys.version_info < (3, 12)", source)
        self.assertIn('sudo -n -u "$target_user" -H true', source)
        self.assertNotIn("curl", source.lower())

    def test_installer_has_no_remote_dependency_or_skip_install_behavior(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8").lower()
        for forbidden in ("curl", "wget", "bash -c", "opencode_installer", "cbm_installer", "skip-opencode-install", "skip-cbm-install"):
            self.assertNotIn(forbidden, source)
        self.assertIn("discover_prerequisites", source)
        self.assertIn("--version", source)
        self.assertIn("--help", source)
        self.assertNotIn("command -v", source)

    def test_clean_config_has_only_v2_agents_and_cbm(self) -> None:
        config = json.loads((ROOT / "source" / "opencode" / "opencode.json").read_text())
        self.assertEqual(set(config["agent"]), {"pegasus-orchestrator", "sdd-verify"})
        self.assertEqual(set(config["mcp"]), {"codebase-memory-mcp"})
        self.assertEqual(config["default_agent"], "pegasus-orchestrator")

    def test_materialization_has_no_plugins_and_uses_canonical_skills(self) -> None:
        module = load_bootstrap()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = {"home": root, "config": root / "config", "data": root / "data", "state": root / "data" / ".pegasus-harness-state.json", "bin": root / "bin", "claude": root / "claude"}
            cbm = target["bin"] / "codebase-memory-mcp"
            cbm.parent.mkdir()
            cbm.write_text("placeholder")
            module.materialize(target, cbm, ("opencode", "claude-code"))
            self.assertFalse((target["config"] / "plugins").exists())
            self.assertTrue((target["config"] / "skills" / "laravel-security" / "SKILL.md").is_file())
            self.assertTrue((target["claude"] / "skills" / "laravel-security" / "SKILL.md").is_file())

    def test_install_refuses_existing_client_configuration(self) -> None:
        module = load_bootstrap()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = {"home": root, "config": root / "config", "data": root / "data", "state": root / "data" / ".pegasus-harness-state.json", "bin": root / "bin", "claude": root / "claude"}
            target["config"].mkdir()
            module.paths = lambda: target
            module.ensure_prerequisites = lambda: None
            with self.assertRaisesRegex(RuntimeError, "clean installation"):
                module.install(type("Args", (), {"client": "opencode"})())

    def test_prerequisites_use_target_home_supported_paths_and_probes(self) -> None:
        module = load_bootstrap()
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            for relative in module.PREREQUISITE_PATHS["opencode"][:1] + module.PREREQUISITE_PATHS["codebase-memory-mcp"]:
                executable = home / relative
                executable.parent.mkdir(parents=True, exist_ok=True)
                executable.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
                executable.chmod(0o755)
            target = {"home": home}
            with patch.object(module.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as probe:
                discovered = module.discover_prerequisites(target, ("opencode",))
            self.assertEqual(discovered["opencode"], home / ".opencode/bin/opencode")
            self.assertEqual(discovered["codebase-memory-mcp"], home / ".local/bin/codebase-memory-mcp")
            self.assertEqual([call.args[0][-1] for call in probe.call_args_list], ["--version", "--help", "--version", "--help"])

    def test_validation_uses_the_same_prerequisite_discovery_as_installation(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertEqual(source.count("discover_prerequisites(target, clients)"), 2)

    def test_release_contract_hashes_the_installer(self) -> None:
        contract = json.loads((ROOT / "manifests" / "release-contract.json").read_text())
        installer = next(asset for asset in contract["distribution_assets"] if asset["path"] == "install.sh")
        self.assertEqual(installer["sha256"], hashlib.sha256((ROOT / "install.sh").read_bytes()).hexdigest())
        self.assertEqual(contract["version"], "2.0.1")
        self.assertEqual(contract["installation"]["remote_dependency_installation"], "forbidden")

    def test_release_tool_builds_an_annotated_tag_archive_with_an_executable_installer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Path(temporary)
            (fixture / "tools").mkdir()
            (fixture / "manifests").mkdir()
            installer = fixture / "install.sh"
            installer.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            installer.chmod(0o755)
            digest = hashlib.sha256(installer.read_bytes()).hexdigest()
            (fixture / "manifests" / "release-contract.json").write_text(json.dumps({"distribution_assets": [{"path": "install.sh", "sha256": digest}]}), encoding="utf-8")
            tool = fixture / "tools" / "build_release_manifest.py"
            tool.write_bytes((ROOT / "tools" / "build_release_manifest.py").read_bytes())
            for command in (("git", "init", "-q"), ("git", "config", "user.email", "tests@example.invalid"), ("git", "config", "user.name", "Pegasus tests"), ("git", "add", "."), ("git", "commit", "-qm", "fixture"), ("git", "tag", "-am", "fixture", "v2.0.1")):
                subprocess.run(command, cwd=fixture, check=True)
            archive = fixture / "dist" / "pegasus-harness-v2.0.1.tar.gz"
            output = fixture / "dist" / "release-manifest.json"
            subprocess.run([sys.executable, str(tool), "--tag", "v2.0.1", "--archive", str(archive), "--output", str(output)], cwd=fixture, check=True)
            with tarfile.open(archive, "r:gz") as contents:
                member = contents.getmember("pegasus-harness-v2.0.1/install.sh")
                self.assertEqual(member.mode & 0o777, 0o755)
            self.assertEqual(json.loads(output.read_text())["distribution_assets"][0]["sha256"], digest)

    def test_product_validator_passes(self) -> None:
        subprocess.run([sys.executable, str(ROOT / "tools" / "validate_snapshot.py")], cwd=ROOT, check=True)

    def test_documentation_links_resolve(self) -> None:
        subprocess.run([sys.executable, str(ROOT / "tools" / "check_docs_links.py")], cwd=ROOT, check=True)


if __name__ == "__main__":
    unittest.main()
