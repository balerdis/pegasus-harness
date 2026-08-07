from __future__ import annotations

import ast
import copy
import hashlib
import io
import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import tarfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bin" / "pegasus"


def load_engine():
    loader = importlib.machinery.SourceFileLoader("pegasus_engine", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def load_release_builder():
    path = ROOT / "tools" / "build_release_manifest.py"
    loader = importlib.machinery.SourceFileLoader("pegasus_release_builder", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def load_agent_preflight():
    path = ROOT / "tools" / "agent_install_preflight.py"
    loader = importlib.machinery.SourceFileLoader("pegasus_agent_preflight", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def load_acceptance_contract():
    path = ROOT / "scripts" / "acceptance_v3_contract.py"
    loader = importlib.machinery.SourceFileLoader("pegasus_acceptance_contract", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def load_acceptance_matrix():
    path = ROOT / "scripts" / "verify-v3-acceptance-matrix.py"
    loader = importlib.machinery.SourceFileLoader("pegasus_acceptance_matrix", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def load_rc_acceptance_aggregate_validator():
    path = ROOT / "scripts" / "validate-v3-acceptance-aggregate.py"
    loader = importlib.machinery.SourceFileLoader("pegasus_rc_acceptance_aggregate_validator", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class AdditiveHarnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = load_engine()

    def temporary_target(self, home: Path) -> dict[str, Path]:
        return self.engine.target_paths(home)

    def write_archive(self, archive: Path, members: list[tuple[tarfile.TarInfo, bytes]]) -> None:
        with tarfile.open(archive, "w:gz") as output:
            for info, payload in members:
                info.size = len(payload)
                output.addfile(info, io.BytesIO(payload))

    def regular_member(self, name: str, mode: int = 0o755) -> tarfile.TarInfo:
        info = tarfile.TarInfo(name)
        info.mode = mode
        return info

    def directory_member(self, name: str) -> tarfile.TarInfo:
        info = tarfile.TarInfo(name)
        info.type = tarfile.DIRTYPE
        info.mode = 0o755
        return info

    def fixture_dependency(self, identifier: str, archive: Path, node: Path | None = None) -> dict:
        item = copy.deepcopy(next(item for item in self.engine.load_contract()["dependencies"] if item["id"] == identifier))
        if identifier == "playwright":
            raise ValueError("Playwright fixtures use fake npm, never archive extraction")
        item["integrity"] = {"sha256": hashlib.sha256(archive.read_bytes()).hexdigest()}
        return item

    def engram_archive_members(self, version: str = "1.20.0", standalone_probe: bool = False) -> list[tuple[tarfile.TarInfo, bytes]]:
        guard = "[ \"$#\" -eq 1 ] && [ \"$1\" = \"--version\" ] || exit 17\n" if standalone_probe else ""
        return [
            (self.regular_member("CHANGELOG.md", 0o644), b"changelog\n"),
            (self.regular_member("LICENSE", 0o644), b"license\n"),
            (self.regular_member("README.md", 0o644), b"readme\n"),
            (self.regular_member("engram", 0o755), f"#!/bin/sh\n{guard}printf 'engram {version}\\n'\n".encode()),
        ]

    def extracted_rc_bundle_fixture(self, root: Path) -> tuple[Path, Path]:
        bundle = root / "codebase-memory-mcp-v0.9.0-linux-x86_64.tar.gz"
        self.write_archive(bundle, [(self.regular_member("bin/codebase-memory-mcp"), b"#!/bin/sh\nprintf 'codebase-memory-mcp 0.9.0\\n'\n")])
        engram_bundle = root / "engram_1.20.0_linux_amd64.tar.gz"
        self.write_archive(engram_bundle, self.engram_archive_members(standalone_probe=True))
        archive = root / "pegasus-harness-v3.1.0-rc.1.tar.gz"
        prefix = "pegasus-harness-v3.1.0-rc.1"
        self.write_archive(archive, [
            (self.directory_member(prefix), b""),
            (self.directory_member(prefix + "/dependencies"), b""),
            (self.regular_member(prefix + "/dependencies/codebase-memory-mcp-v0.9.0-linux-x86_64.tar.gz"), bundle.read_bytes()),
            (self.regular_member(prefix + "/dependencies/engram_1.20.0_linux_amd64.tar.gz"), engram_bundle.read_bytes()),
            (self.regular_member(prefix + "/manifests/release-contract.json"), (ROOT / "manifests/release-contract.json").read_bytes()),
            (self.regular_member(prefix + "/manifests/artifact-catalog.json"), (ROOT / "manifests/artifact-catalog.json").read_bytes()),
        ])
        extracted = root / "extracted"
        with tarfile.open(archive, "r:gz") as contents:
            contents.extractall(extracted, filter="data")
        return extracted / prefix, bundle

    def rc_release_identity_fixture(self, release_root: Path) -> dict[str, str]:
        tag = release_root.name.removeprefix("pegasus-harness-")
        return {
            "tag": tag,
            "archive_name": f"pegasus-harness-{tag}.tar.gz",
            "archive_sha256": "a" * 64,
            "manifest_sha256": "b" * 64,
            "archive_root": release_root.name,
        }

    def fixture_command(self, path: Path, output: str, exit_code: int = 0) -> None:
        path.write_text(f"#!/bin/sh\nprintf '%s\\n' '{output}'\nexit {exit_code}\n", encoding="utf-8")
        path.chmod(0o755)

    def release_fixture(self, root: Path, tag: str, final: bool) -> tuple[Path, Path, Path]:
        archive = root / f"pegasus-harness-{tag}.tar.gz"
        archive_root = f"pegasus-harness-{tag}"
        documents = {
            "README.md": b"readme\n",
            "INSTALL.md": b"install\n",
            "INSTALL_BY_AGENT.md": b"agent install\n",
            "MANUAL.md": b"manual\n",
            "docs/release-distribution.md": b"release distribution\n",
        }
        evidence = {
            "manifests/release-contract.json": b"{}",
            "manifests/artifact-catalog.json": b"{}",
            "manifests/cbm-linux-x64-provenance.json": b'{"artifact_sha256":"cbm"}',
            "dependencies/cbm.tar.gz": b"cbm",
            **documents,
        }
        members = [(self.directory_member(archive_root), b"")]
        members.extend((self.regular_member(f"{archive_root}/{path}", 0o644), payload) for path, payload in evidence.items())
        members.extend([
            (self.regular_member(f"{archive_root}/install.sh"), b"#!/bin/sh\n"),
            (self.regular_member(f"{archive_root}/bin/pegasus"), b"#!/usr/bin/env python3\n"),
        ])
        self.write_archive(archive, members)
        archive_digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        checksum = archive.with_name(archive.name + ".sha256")
        checksum.write_text(f"{archive_digest}  {archive.name}\n", encoding="utf-8")
        manifest = root / "release-manifest.json"
        payload = {
            "schema": "pegasus-harness-release/v3",
            "tag": tag,
            "archive_root": archive_root,
            "assets": [{"name": archive.name, "sha256": archive_digest}],
            "curated_dependencies": [{"id": "cbm", "path": "dependencies/cbm.tar.gz"}],
            "archive_evidence": [{"path": path, "sha256": hashlib.sha256(payload).hexdigest()} for path, payload in evidence.items() if path not in documents],
        }
        if final:
            payload.update({
                "release_kind": "final",
                "promotion_rc_tag": "v3.1.1-rc.1",
                "published_assets": [archive.name, checksum.name, manifest.name],
                "documentation_evidence": [{"path": path, "sha256": hashlib.sha256(payload).hexdigest()} for path, payload in documents.items()],
            })
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        return archive, checksum, manifest

    def final_release_fixture(self, root: Path) -> tuple[Path, Path, Path]:
        return self.release_fixture(root, "v3.1.1", final=True)

    def rc_release_fixture(self, root: Path) -> tuple[Path, Path, Path]:
        return self.release_fixture(root, "v3.1.1-rc.1", final=False)

    def playwright_acceptance_evidence(self, matrix) -> dict:
        return {
            "version": "0.0.79",
            "registry": "https://registry.npmjs.org/",
            "install": {"argv": ["npm", "ci", "--ignore-scripts"], "result": "PASS"},
            "packages": matrix.PLAYWRIGHT_PACKAGES,
            "direct_entrypoint": {
                "argv": ["/opt/node/bin/node", "/home/fixture/.local/share/pegasus-harness/dependencies/playwright/node_modules/@playwright/mcp/cli.js", "--version"],
                "stdout": "Version 0.0.79",
                "exit_code": 0,
            },
        }

    def fake_npm(self, path: Path, mode: str = "success") -> None:
        path.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, pathlib, sys\n"
            "root = pathlib.Path.cwd()\n"
            "(root.parent / 'npm-argv.txt').write_text(' '.join(sys.argv[1:]))\n"
            "user_config = pathlib.Path(os.environ['NPM_CONFIG_USERCONFIG'])\n"
            "global_config = pathlib.Path(os.environ['NPM_CONFIG_GLOBALCONFIG'])\n"
            "cache = pathlib.Path(os.environ['NPM_CONFIG_CACHE'])\n"
            "cache.mkdir(parents=True, exist_ok=True)\n"
            "(root.parent / 'npm-environment.json').write_text(json.dumps({\n"
            "    'registry': os.environ.get('NPM_CONFIG_REGISTRY'),\n"
            "    'ignore_scripts': os.environ.get('NPM_CONFIG_IGNORE_SCRIPTS'),\n"
            "    'cache': str(cache),\n"
            "    'user_config': str(user_config),\n"
            "    'global_config': str(global_config),\n"
            "    'config_collision': user_config == global_config,\n"
            "    'configs_exist': user_config.is_file() and global_config.is_file(),\n"
            "    'proxy_variables': sorted(name for name in os.environ if 'proxy' in name.lower()),\n"
            "}))\n"
            f"mode = {mode!r}\n"
            "if mode == 'fail': sys.exit(23)\n"
            "if mode == 'config-collision' and (user_config == global_config or not user_config.is_file() or not global_config.is_file()): sys.exit(24)\n"
            "if mode == 'lock-drift': (root / 'package-lock.json').write_text('{}')\n"
            "if mode in {'wrong-registry', 'wrong-sri'}:\n"
            "    lock = __import__('json').loads((root / 'package-lock.json').read_text())\n"
            "    field = 'resolved' if mode == 'wrong-registry' else 'integrity'\n"
            "    lock['packages']['node_modules/playwright'][field] = 'https://mirror.invalid/playwright.tgz' if mode == 'wrong-registry' else 'sha512-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=='\n"
            "    (root / 'package-lock.json').write_text(__import__('json').dumps(lock))\n"
            "if mode != 'missing-cli':\n"
            "    cli = root / 'node_modules/@playwright/mcp/cli.js'\n"
            "    cli.parent.mkdir(parents=True)\n"
            "    version = '0.0.80' if mode == 'wrong-version' else '0.0.79'\n"
            "    cli.write_text(f\"require('playwright-core/lib/utilsBundle'); if (process.argv.includes('--version')) console.log('Version {version}');\\n\")\n"
            "    for package in ('playwright', 'playwright-core'):\n"
            "        target = root / 'node_modules' / package / 'cli.js'\n"
            "        target.parent.mkdir(parents=True, exist_ok=True)\n"
            "        target.write_text('console.log(\\\"bin\\\");\\n')\n"
            "    utils_bundle = root / 'node_modules/playwright-core/lib/utilsBundle.js'\n"
            "    utils_bundle.parent.mkdir(parents=True, exist_ok=True)\n"
            "    utils_bundle.write_text('module.exports = {};\\n')\n"
            "    bin_dir = root / 'node_modules/.bin'\n"
            "    bin_dir.mkdir()\n"
            "    links = {'playwright-mcp': '../@playwright/mcp/cli.js', 'playwright': '../playwright/cli.js', 'playwright-core': '../playwright-core/cli.js'}\n"
            "    for name, target in links.items(): (bin_dir / name).symlink_to(target)\n",
            encoding="utf-8",
        )
        path.chmod(0o755)

    def test_safe_contract_rejects_mutable_or_shell_installers(self) -> None:
        contract = self.engine.load_contract()
        self.assertEqual(contract["schema"], "pegasus-harness-release-contract/v3")
        self.assertEqual(contract["version"], "3.1.0")
        self.assertEqual({item["id"] for item in contract["dependencies"]}, {"cbm", "engram", "playwright"})
        self.assertTrue(self.engine.validate_contract(contract))
        for dependency in contract["dependencies"]:
            self.assertNotIn("latest", json.dumps(dependency).lower())
            self.assertNotIn("npx", json.dumps(dependency).lower())
            self.assertIsInstance(dependency["install_argv"], list)
            self.assertIsInstance(dependency["runtime_argv"], list)
        broken = json.loads(json.dumps(contract))
        broken["dependencies"][0]["version"] = "latest"
        with self.assertRaisesRegex(RuntimeError, "fixed version"):
            self.engine.validate_contract(broken)
        broken = json.loads(json.dumps(contract))
        playwright = next(item for item in broken["dependencies"] if item["id"] == "playwright")
        playwright["probe_output"] = "@playwright/mcp 0.0.79"
        with self.assertRaisesRegex(RuntimeError, "probe output"):
            self.engine.validate_contract(broken)

    def test_release_executables_are_catalogued_regular_files_only(self) -> None:
        catalog = self.engine.load_catalog()
        self.assertTrue(self.engine.validate_catalog(catalog, ROOT))
        self.assertTrue(all(self.engine.is_allowed_executable(entry["source"]) for entry in catalog["artifacts"] if entry.get("executable")))
        for bad in ("requirements.txt", "CMakeLists.txt", "README.md", "guide.mdx", "README.sh"):
            self.assertFalse(self.engine.is_allowed_executable(bad))

    def test_catalog_contains_only_the_approved_payload_inventory(self) -> None:
        catalog = self.engine.load_catalog()
        sources = {entry["source"] for entry in catalog["artifacts"]}
        commands = {path.name for path in (ROOT / "source" / "opencode" / "commands").glob("*.md")}
        prompts = {path.name for path in (ROOT / "source" / "opencode" / "prompts" / "sdd").glob("*.md")}
        self.assertEqual(len(commands), 16)
        self.assertEqual(len(prompts), 10)
        for command in ("context-load.md", "skill-creator.md", "skill-registry.md"):
            self.assertIn(f"source/opencode/commands/{command}", sources)
        self.assertIn("source/opencode/plugins/pegasus-skill-registry.ts", sources)
        self.assertIn("source/opencode/plugins/engram.ts", sources)
        self.assertIn("source/opencode/notifier/package.json", sources)
        self.assertIn("source/opencode/notifier/package-lock.json", sources)
        self.assertIn("source/opencode/env/pegasus-skill-registry.env.example", sources)
        self.assertIn("source/opencode/plugins/zellij-status.js", sources)
        self.assertNotIn("source/core/skills/lazy-load-prompt-audit/references/deployment-transport.md", sources)
        self.assertFalse((ROOT / "source/core/skills/lazy-load-prompt-audit/references/deployment-transport.md").exists())
        self.assertNotIn("source/opencode/plugins/skill-registry.ts", sources)
        self.assertNotIn("source/opencode/tui.json", sources)
        self.assertFalse((ROOT / "source/opencode/tui.json").exists())
        self.assertFalse(any("judgment-day" in source or "sergio-" in source for source in sources))
        config = json.loads((ROOT / "source" / "opencode" / "opencode.json").read_text())
        self.assertIn("codebase-memory-mcp", config["mcp"])
        self.assertNotIn("cbm", config["mcp"])
        self.assertEqual(config["plugin"], ["@mohak34/opencode-notifier@0.2.4"])
        registry_assets = json.loads((ROOT / "source/opencode/registry/assets.json").read_text())
        self.assertEqual(registry_assets["plugins"], ["zellij-status"])

    def test_catalog_rejects_the_unselected_deployment_transport_reference(self) -> None:
        catalog = self.engine.load_catalog()
        catalog["artifacts"].append({
            "id": "forbidden-deployment-transport",
            "client": "opencode",
            "kind": "file",
            "source": "source/core/skills/lazy-load-prompt-audit/references/deployment-transport.md",
            "target": "skills/lazy-load-prompt-audit/references/deployment-transport.md",
            "merge": "create-absent-file",
            "digest": "unused",
        })
        with self.assertRaisesRegex(RuntimeError, "excluded"):
            self.engine.validate_catalog(catalog, ROOT)

    def test_notifier_is_locked_and_acceptance_uses_no_lifecycle_scripts(self) -> None:
        self.assertTrue(self.engine.validate_notifier_lockfile())
        package = json.loads((ROOT / "source/opencode/notifier/package.json").read_text())
        lockfile = json.loads((ROOT / "source/opencode/notifier/package-lock.json").read_text())
        notifier = lockfile["packages"]["node_modules/@mohak34/opencode-notifier"]
        self.assertNotIn("scripts", package)
        self.assertEqual(notifier["version"], "0.2.4")
        self.assertEqual(notifier["integrity"], self.engine.NOTIFIER_INTEGRITY)
        acceptance = (ROOT / "scripts/accept-v3-isolated.sh").read_text(encoding="utf-8")
        self.assertIn("npm --prefix \"$target_home/.config/opencode/notifier\" ci --ignore-scripts", acceptance)
        self.assertNotIn("npm install", acceptance)

    def test_acceptance_script_is_static_and_refuses_unsafe_defaults(self) -> None:
        script = ROOT / "scripts/accept-v3-isolated.sh"
        source = script.read_text(encoding="utf-8")
        for required in ("--profile", "--rc-archive", "--rc-checksum", "--release-manifest", "--staging-dir", "--evidence-file", "--evidence-verifier", "--confirm-recreate-user", "--browser", "browser_args", "--release-identity", "release_identity", "acceptance_v3_contract.py", "provision-v3-rc-host.sh", "serg", "declined_no_orphans", "pegasus-harness-journal/v3", "mapped user", '"rc"', "archive_name", "checksum_sha256", "manifest_sha256", "archive_root", "playwright_graph", "https://registry.npmjs.org/", '"npm", "ci", "--ignore-scripts"', "direct_entrypoint", "EVIDENCE_VERIFIER_GID", "os.chown", "0o640", "os.link"):
            self.assertIn(required, source)
        self.assertIn('"$provisioner" --profile "$profile" --rc-archive "$archive" --confirm-recreate-user "$recreate_user"', source)
        provisioner = (ROOT / "scripts/provision-v3-rc-host.sh").read_text(encoding="utf-8")
        self.assertIn("--browser", provisioner)
        for forbidden in ("useradd", "userdel", "rm -rf", "--confirm-clean-home"):
            self.assertNotIn(forbidden, source)
        self.assertIn("Automated tests may inspect this file but must never run it", source)
        self.assertIn("stat.S_IMODE(metadata.st_mode) != 0o750", source)

    def test_acceptance_playwright_probe_failure_diagnostics_are_redacted_and_bounded(self) -> None:
        source = (ROOT / "scripts/accept-v3-isolated.sh").read_text(encoding="utf-8")
        embedded = source.split("python3 - <<'PY'\n", 1)[1].rsplit("\nPY\n", 1)[0]
        tree = ast.parse(embedded)
        diagnostic_nodes = [
            node for node in tree.body
            if isinstance(node, ast.Import)
            or (isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id in {
                    "PROBE_DIAGNOSTIC_LIMIT", "SENSITIVE_PROBE_VALUE", "SENSITIVE_BEARER_TOKEN"
                }
                for target in node.targets
            ))
            or (isinstance(node, ast.FunctionDef) and node.name == "sanitized_probe_output")
        ]
        namespace: dict[str, object] = {}
        exec(compile(ast.Module(body=diagnostic_nodes, type_ignores=[]), "accept-v3-isolated diagnostics", "exec"), namespace)
        sanitize = namespace["sanitized_probe_output"]
        self.assertEqual(sanitize("unexpected version\n"), repr("unexpected version\n"))
        secret = "token=do-not-leak " + "x" * (512 + 1)
        diagnostic = sanitize(secret + "\nAuthorization: Bearer also-do-not-leak")
        self.assertIn("token=<redacted>", diagnostic)
        self.assertIn("...<truncated>", diagnostic)
        self.assertNotIn("do-not-leak", diagnostic)
        self.assertNotIn("also-do-not-leak", diagnostic)
        self.assertIn("exit_code={probe.returncode}", embedded)
        self.assertIn("stdout={sanitized_probe_output(probe.stdout)}", embedded)
        self.assertIn("stderr={sanitized_probe_output(probe.stderr)}", embedded)

    def handoff_release_fixture(self, root: Path) -> Path:
        release = root / "verified-release"
        entrypoint = release / "bin" / "pegasus"
        entrypoint.parent.mkdir(parents=True)
        entrypoint.write_text("#!/bin/sh\nprintf executed\\n", encoding="utf-8")
        entrypoint.chmod(0o755)
        (release / "manifest.json").write_text('{"release":"fixture"}', encoding="utf-8")
        return release

    def controlled_handoff_ancestry(self, root: Path):
        def path_from_root(path: Path) -> list[Path]:
            relative = Path(path).relative_to(root)
            components = [root]
            current = root
            for part in relative.parts:
                current /= part
                components.append(current)
            return components

        return path_from_root

    def virtual_handoff_filesystem(self, contract, root: Path):
        ownership = {root: (0, 0)}
        original_lstat = contract.os.lstat

        def chown(path: Path, uid: int, gid: int) -> None:
            ownership[Path(path)] = (uid, gid)

        def lstat(path: Path):
            metadata = original_lstat(path)
            uid, gid = ownership.get(Path(path), (metadata.st_uid, metadata.st_gid))
            values = list(metadata)
            values[4], values[5] = uid, gid
            return os.stat_result(values)

        return ownership, chown, lstat

    def target_has_access(self, lstat, path: Path, target_gid: int, required: int) -> bool:
        metadata = lstat(path)
        permissions = metadata.st_mode & 0o777
        granted = (permissions >> 3) & 0o7 if metadata.st_gid == target_gid else permissions & 0o7
        return granted & required == required

    def test_prepare_handoff_grants_target_access_without_target_replacement_offline(self) -> None:
        contract = load_acceptance_contract()
        target_gid = 42002
        target_user = "pegasus-handoff-fixture"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            root.chmod(0o755)
            release = self.handoff_release_fixture(root)
            handoff_base = root / "pegasus-acceptance"
            ownership, chown, lstat = self.virtual_handoff_filesystem(contract, root)
            with patch.object(contract, "HANDOFF_BASE", handoff_base), \
                    patch.object(contract, "path_from_root", self.controlled_handoff_ancestry(root)), \
                    patch.object(contract.os, "geteuid", return_value=0), \
                    patch.object(contract.os, "chown", side_effect=chown), \
                    patch.object(contract.os, "lstat", side_effect=lstat), \
                    patch.object(contract.pwd, "getpwnam", return_value=SimpleNamespace(pw_gid=target_gid)):
                payload = contract.prepare_handoff(release, target_user, handoff_base)

            entrypoint = payload / "bin" / "pegasus"
            manifest = payload / "manifest.json"
            self.assertEqual(lstat(payload).st_mode & 0o777, 0o750)
            self.assertEqual(lstat(entrypoint).st_mode & 0o777, 0o750)
            self.assertEqual(lstat(manifest).st_mode & 0o777, 0o640)
            self.assertEqual((lstat(entrypoint).st_uid, lstat(entrypoint).st_gid), (0, target_gid))
            self.assertEqual((lstat(manifest).st_uid, lstat(manifest).st_gid), (0, target_gid))
            self.assertTrue(self.target_has_access(lstat, entrypoint, target_gid, 0o5))
            self.assertTrue(self.target_has_access(lstat, manifest, target_gid, 0o4))
            for directory in (entrypoint.parent, payload, payload.parent, payload.parent.parent):
                with self.subTest(directory=directory):
                    self.assertTrue(self.target_has_access(lstat, directory, target_gid, 0o1))
                    self.assertFalse(self.target_has_access(lstat, directory, target_gid, 0o3))
            for protected, parent in {
                "payload file": entrypoint.parent,
                "payload directory": payload.parent,
                "handoff ancestor": payload.parent.parent,
            }.items():
                with self.subTest(protected=protected):
                    self.assertFalse(self.target_has_access(lstat, parent, target_gid, 0o3))

    def test_prepare_handoff_refuses_unsafe_ancestors_offline(self) -> None:
        contract = load_acceptance_contract()
        target_user = "pegasus-handoff-fixture"
        target_uid, target_gid = 42001, 42002
        for scenario in ("target-owned", "symlink", "world-writable"):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                root.chmod(0o755)
                release = self.handoff_release_fixture(root)
                handoff_base = root / "pegasus-acceptance"
                ownership, chown, lstat = self.virtual_handoff_filesystem(contract, root)
                if scenario == "target-owned":
                    handoff_base.mkdir()
                    ownership[handoff_base] = (target_uid, 0)
                elif scenario == "symlink":
                    target = root / "linked-target"
                    target.mkdir()
                    handoff_base.symlink_to(target, target_is_directory=True)
                else:
                    root.chmod(0o777)
                with patch.object(contract, "HANDOFF_BASE", handoff_base), \
                        patch.object(contract, "path_from_root", self.controlled_handoff_ancestry(root)), \
                        patch.object(contract.os, "geteuid", return_value=0), \
                        patch.object(contract.os, "chown", side_effect=chown), \
                        patch.object(contract.os, "lstat", side_effect=lstat), \
                        patch.object(contract.pwd, "getpwnam", return_value=SimpleNamespace(pw_gid=target_gid)):
                    with self.assertRaisesRegex(ValueError, "unsafe|root-controlled|real directory|handoff base"):
                        contract.prepare_handoff(release, target_user, handoff_base)

    def test_current_user_wrapper_rejects_root_and_legacy_target_selection(self) -> None:
        wrapper = (ROOT / "install.sh").read_text(encoding="utf-8")
        self.assertIn('[[ $(id -u) -ne 0 ]]', wrapper)
        self.assertIn('--target-user is no longer supported', wrapper)
        self.assertIn('current_user=$(id -un)', wrapper)
        self.assertIn('current_home=${HOME:-}', wrapper)
        self.assertNotIn('sudo -n -u', wrapper)
        self.assertNotIn('getent passwd', wrapper)

        with tempfile.TemporaryDirectory() as temporary:
            fake_id = Path(temporary) / "id"
            fake_id.write_text("#!/bin/sh\nprintf '0\\n'\n", encoding="utf-8")
            fake_id.chmod(0o755)
            root_result = subprocess.run(
                ["bash", str(ROOT / "install.sh"), "--decline", "cbm"],
                env=os.environ | {"PATH": f"{temporary}:{os.environ['PATH']}"},
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertNotEqual(root_result.returncode, 0)
        self.assertIn("must not run as root", root_result.stderr)

    def test_current_user_wrapper_help_and_legacy_flag_contract(self) -> None:
        help_result = subprocess.run(["bash", str(ROOT / "install.sh"), "--help"], text=True, capture_output=True, check=False)
        self.assertEqual(help_result.returncode, 0)
        self.assertIn("Usage: ./install.sh", help_result.stdout)
        self.assertNotIn("--target-user <linux-user>", help_result.stdout)

        legacy_result = subprocess.run(["bash", str(ROOT / "install.sh"), "--target-user", "someone"], text=True, capture_output=True, check=False)
        self.assertNotEqual(legacy_result.returncode, 0)
        self.assertIn("no longer supported", legacy_result.stderr)

    def test_current_user_wrapper_runs_plan_then_apply_in_simulated_home(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            environment = os.environ | {"HOME": str(home), "USER": "ignored-by-wrapper"}
            result = subprocess.run(
                ["bash", str(ROOT / "install.sh"), "--client", "opencode",
                 "--decline", "cbm", "--decline", "engram", "--decline", "playwright", "--decline", "context7"],
                cwd=ROOT,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertGreaterEqual(result.stdout.count('"schema": "pegasus-harness-plan/v3"'), 1)
            self.assertTrue((home / ".config" / "opencode" / "opencode.json").is_file())

    def test_rc_host_provisioner_is_profile_scoped_pinned_and_explicitly_destructive(self) -> None:
        script = ROOT / "scripts" / "provision-v3-rc-host.sh"
        source = script.read_text(encoding="utf-8")
        for profile in ("cbm", "engram", "playwright", "context7", "final"):
            self.assertIn(profile, source)
        self.assertIn("472655581fb851559730c48763e0c9d3bc25975c59d518003fc0849d3e4ba0f6", source)
        self.assertIn("sha512-WVB/FwFdG4NLqEdraW264/q5WFiUDTwU4hDN/6qSLamsCV+SUurZhDOrmXC/5atNWZE1B6xEq5E8V60dAduKZg==", source)
        for required in ("--confirm-recreate-user", "userdel -r", "useradd --create-home", "target_user != serg", "v3\\.1\\.0-rc"):
            self.assertIn(required, source)
        for forbidden in ("rm -rf", "npm install", "nvm", "opencode-ai"):
            self.assertNotIn(forbidden, source.lower())

    def test_acceptance_profiles_have_exact_confirmation_and_decline_matrix(self) -> None:
        contract = load_acceptance_contract()
        expected = {
            "cbm": ("pegasus-harness", ("cbm",), ("engram", "playwright", "context7")),
            "engram": ("pegasus-harness-engram", ("engram",), ("cbm", "playwright", "context7")),
            "playwright": ("pegasus-harness-playwright", ("playwright",), ("cbm", "engram", "context7")),
            "context7": ("pegasus-harness-context7", ("context7",), ("cbm", "engram", "playwright")),
            "final": ("pegasus-harness-final", ("cbm", "engram", "playwright", "context7"), ()),
        }
        self.assertEqual(set(contract.PROFILE_PLANS), set(expected))
        for profile, (user, confirmed, declined) in expected.items():
            with self.subTest(profile=profile):
                plan = contract.profile_plan(profile)
                self.assertEqual((plan["user"], plan["confirm"], plan["decline"]), (user, confirmed, declined))

    def test_acceptance_preflight_validates_rc_checksum_manifest_and_safe_refusals_offline(self) -> None:
        contract = load_acceptance_contract()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tag = "v3.1.0-rc.1"
            prefix = f"pegasus-harness-{tag}/"
            evidence = {
                "manifests/release-contract.json": b"{}",
                "manifests/artifact-catalog.json": b"{}",
                "manifests/cbm-linux-x64-provenance.json": b'{"artifact_sha256":"cbm"}',
                "dependencies/cbm.tar.gz": b"cbm",
            }
            manifest = root / "release-manifest.json"
            for root_member in (prefix[:-1], prefix):
                with self.subTest(root_member=root_member):
                    archive = root / f"{prefix[:-1]}.tar.gz"
                    members = [(self.directory_member(root_member), b"")]
                    members.extend((self.regular_member(prefix + path), payload) for path, payload in evidence.items())
                    members.extend([(self.regular_member(prefix + "bin/pegasus"), b"#!/usr/bin/env python3\n"), (self.regular_member(prefix + "install.sh"), b"#!/bin/sh\n")])
                    self.write_archive(archive, members)
                    archive_digest = hashlib.sha256(archive.read_bytes()).hexdigest()
                    checksum = root / f"{archive.name}.sha256"
                    checksum.write_text(f"{archive_digest}  {archive.name}\n", encoding="utf-8")
                    manifest.write_text(json.dumps({
                        "schema": "pegasus-harness-release/v3", "tag": tag, "archive_root": prefix[:-1],
                        "assets": [{"name": archive.name, "sha256": archive_digest}],
                        "curated_dependencies": [{"id": "cbm", "path": "dependencies/cbm.tar.gz"}],
                        "archive_evidence": [{"path": path, "sha256": hashlib.sha256(payload).hexdigest()} for path, payload in evidence.items()],
                    }), encoding="utf-8")
                    self.assertEqual(contract.validate_rc_inputs("cbm", archive, checksum, manifest), prefix[:-1])
                    self.assertEqual(contract.rc_release_identity(archive, manifest, prefix[:-1]), {
                        "tag": tag, "archive_name": archive.name, "archive_sha256": archive_digest,
                        "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(), "archive_root": prefix[:-1],
                    })
            checksum.write_text("0" * 64 + f"  {archive.name}\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "checksum"):
                contract.validate_rc_inputs("cbm", archive, checksum, manifest)
            with self.assertRaisesRegex(ValueError, "unknown acceptance profile"):
                contract.validate_rc_inputs("serg", archive, checksum, manifest)

    def test_acceptance_preflight_rejects_adversarial_archive_roots_offline(self) -> None:
        contract = load_acceptance_contract()
        root = "pegasus-harness-v3.1.0-rc.1"
        self.assertFalse(contract.archive_member_in_root("pegasus-harness-v3.1.0-rc.2", root))
        self.assertFalse(contract.archive_member_in_root(root + "/../escape", root))
        self.assertFalse(contract.archive_member_in_root("/" + root + "/escape", root))
        self.assertFalse(contract.archive_member_in_root(root + "//escape", root))

    def test_verified_extraction_keeps_root_staging_private_offline(self) -> None:
        contract = load_acceptance_contract()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "archive.tar.gz"
            prefix = "pegasus-harness-v3.1.0-rc.1"
            self.write_archive(archive, [
                (self.directory_member(prefix), b""),
                (self.regular_member(prefix + "/bin/pegasus"), b"#!/usr/bin/env python3\n"),
                (self.regular_member(prefix + "/install.sh"), b"#!/bin/sh\n"),
            ])
            staging = root / "root-staging"
            release_root = contract.extract_verified_archive(archive, staging, prefix)
            self.assertEqual(staging.stat().st_mode & 0o777, 0o700)
            self.assertTrue((release_root / "bin" / "pegasus").is_file())

    def test_acceptance_preflight_refuses_unsafe_archive_permission_bits_offline(self) -> None:
        contract = load_acceptance_contract()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tag = "v3.1.0-rc.1"
            prefix = f"pegasus-harness-{tag}/"
            archive = root / f"pegasus-harness-{tag}.tar.gz"
            evidence = {
                "manifests/release-contract.json": b"{}",
                "manifests/artifact-catalog.json": b"{}",
                "manifests/cbm-linux-x64-provenance.json": b'{"artifact_sha256":"cbm"}',
                "dependencies/cbm.tar.gz": b"cbm",
            }
            unsafe = self.regular_member(prefix + "bin/pegasus")
            unsafe.mode = 0o4755
            members = [(self.directory_member(prefix), b"")]
            members.extend((self.regular_member(prefix + path), payload) for path, payload in evidence.items())
            members.extend([(unsafe, b"#!/usr/bin/env python3\n"), (self.regular_member(prefix + "install.sh"), b"#!/bin/sh\n")])
            self.write_archive(archive, members)
            archive_digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            checksum = root / f"{archive.name}.sha256"
            checksum.write_text(f"{archive_digest}  {archive.name}\n", encoding="utf-8")
            manifest = root / "release-manifest.json"
            manifest.write_text(json.dumps({
                "schema": "pegasus-harness-release/v3", "tag": tag, "archive_root": prefix[:-1],
                "assets": [{"name": archive.name, "sha256": archive_digest}],
                "curated_dependencies": [{"id": "cbm", "path": "dependencies/cbm.tar.gz"}],
                "archive_evidence": [{"path": path, "sha256": hashlib.sha256(payload).hexdigest()} for path, payload in evidence.items()],
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unsafe permission bits"):
                contract.validate_rc_inputs("cbm", archive, checksum, manifest)

    def test_acceptance_matrix_aggregates_only_the_five_passing_profiles_for_one_rc_offline(self) -> None:
        matrix = load_acceptance_matrix()
        with tempfile.TemporaryDirectory(dir="/var/tmp") as temporary:
            root = Path(temporary)
            tag = "v3.1.0-rc.1"
            archive = root / f"pegasus-harness-{tag}.tar.gz"
            prefix = f"pegasus-harness-{tag}/"
            payloads = {
                "manifests/release-contract.json": b"{}",
                "manifests/artifact-catalog.json": b"{}",
                "manifests/cbm-linux-x64-provenance.json": b'{}',
                "dependencies/cbm.tar.gz": b"cbm",
            }
            members = [(self.directory_member(prefix), b"")]
            members.extend((self.regular_member(prefix + path), payload) for path, payload in payloads.items())
            members.extend([(self.regular_member(prefix + "bin/pegasus"), b"#!/usr/bin/env python3\n"), (self.regular_member(prefix + "install.sh"), b"#!/bin/sh\n")])
            self.write_archive(archive, members)
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            checksum = root / f"{archive.name}.sha256"
            checksum.write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
            manifest = root / "release-manifest.json"
            manifest.write_text(json.dumps({"schema": "pegasus-harness-release/v3", "tag": tag, "archive_root": prefix[:-1], "assets": [{"name": archive.name, "sha256": digest}], "curated_dependencies": [{"id": "cbm", "path": "dependencies/cbm.tar.gz"}], "archive_evidence": [{"path": path, "sha256": hashlib.sha256(payload).hexdigest()} for path, payload in payloads.items()]}), encoding="utf-8")
            identity = matrix.expected_identity(archive, checksum, manifest)
            evidence_dir = root / "evidence"
            evidence_dir.mkdir()
            for profile in sorted(matrix.PROFILES):
                record = {"schema": matrix.SCHEMA, "status": "PASS", "profile": profile, "rc": identity, "journal": {"path": f"/{profile}", "sha256": profile, "entries": 1}}
                if profile in matrix.PLAYWRIGHT_PROFILES:
                    record["playwright_graph"] = self.playwright_acceptance_evidence(matrix)
                (evidence_dir / f"{profile}.json").write_text(json.dumps(record), encoding="utf-8")
            output_dir = root / "aggregate"
            output_dir.mkdir(mode=0o700)
            output = matrix.aggregate(archive, checksum, manifest, evidence_dir, output_dir / matrix.AGGREGATE_NAME)
            aggregate = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(aggregate["status"], "PASS")
            self.assertEqual(aggregate["profiles"], sorted(matrix.PROFILES))
            self.assertEqual(set(aggregate["playwright_graph"]), matrix.PLAYWRIGHT_PROFILES)
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)

    def test_documented_handoff_creates_a_verifier_owned_private_aggregate_output_offline(self) -> None:
        output_setup = "sudo -n -u serg -H install -d -m 0700 /var/tmp/pegasus-v3.1.0-rc.1-aggregate-serg"
        for document in ("docs/aceptacion-rc-v3.1.md", "docs/instalacion-aditiva-v3.md"):
            with self.subTest(document=document):
                self.assertIn(output_setup, (ROOT / document).read_text(encoding="utf-8"))

        matrix = load_acceptance_matrix()
        with tempfile.TemporaryDirectory(dir="/var/tmp") as temporary:
            root = Path(temporary)
            tag = "v3.1.0-rc.1"
            archive = root / f"pegasus-harness-{tag}.tar.gz"
            prefix = f"pegasus-harness-{tag}/"
            payloads = {
                "manifests/release-contract.json": b"{}",
                "manifests/artifact-catalog.json": b"{}",
                "manifests/cbm-linux-x64-provenance.json": b"{}",
                "dependencies/cbm.tar.gz": b"cbm",
            }
            members = [(self.directory_member(prefix), b"")]
            members.extend((self.regular_member(prefix + path), payload) for path, payload in payloads.items())
            members.extend([(self.regular_member(prefix + "bin/pegasus"), b"#!/usr/bin/env python3\n"), (self.regular_member(prefix + "install.sh"), b"#!/bin/sh\n")])
            self.write_archive(archive, members)
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            checksum = root / f"{archive.name}.sha256"
            checksum.write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
            manifest = root / "release-manifest.json"
            manifest.write_text(json.dumps({"schema": "pegasus-harness-release/v3", "tag": tag, "archive_root": prefix[:-1], "assets": [{"name": archive.name, "sha256": digest}], "curated_dependencies": [{"id": "cbm", "path": "dependencies/cbm.tar.gz"}], "archive_evidence": [{"path": path, "sha256": hashlib.sha256(payload).hexdigest()} for path, payload in payloads.items()]}), encoding="utf-8")
            identity = matrix.expected_identity(archive, checksum, manifest)
            evidence_dir = root / "evidence"
            evidence_dir.mkdir()
            for profile in sorted(matrix.PROFILES):
                record = {"schema": matrix.SCHEMA, "status": "PASS", "profile": profile, "rc": identity, "journal": {}}
                if profile in matrix.PLAYWRIGHT_PROFILES:
                    record["playwright_graph"] = self.playwright_acceptance_evidence(matrix)
                (evidence_dir / f"{profile}.json").write_text(json.dumps(record), encoding="utf-8")
            output_dir = root / "aggregate-serg"
            output_dir.mkdir(mode=0o700)
            self.assertEqual((output_dir.stat().st_uid, output_dir.stat().st_mode & 0o777), (os.geteuid(), 0o700))
            output_file = output_dir / matrix.AGGREGATE_NAME
            result = subprocess.run([
                sys.executable, str(ROOT / "scripts/verify-v3-acceptance-matrix.py"),
                "--rc-archive", str(archive), "--rc-checksum", str(checksum),
                "--release-manifest", str(manifest), "--evidence-dir", str(evidence_dir),
                "--output-file", str(output_file),
            ], capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("PASS: aggregate acceptance evidence recorded at", result.stdout)
            self.assertEqual(json.loads(output_file.read_text(encoding="utf-8"))["status"], "PASS")
            self.assertEqual(output_file.stat().st_mode & 0o777, 0o600)

    def test_acceptance_matrix_requires_exact_playwright_graph_and_leaves_no_aggregate_on_failure(self) -> None:
        matrix = load_acceptance_matrix()
        identity = {"tag": "v3.1.0-rc.1"}
        with tempfile.TemporaryDirectory(dir="/var/tmp") as temporary:
            root = Path(temporary)
            evidence_dir = root / "evidence"
            evidence_dir.mkdir()
            records = []
            for profile in sorted(matrix.PROFILES):
                record = {"schema": matrix.SCHEMA, "status": "PASS", "profile": profile, "rc": identity, "journal": {}}
                if profile in matrix.PLAYWRIGHT_PROFILES:
                    record["playwright_graph"] = self.playwright_acceptance_evidence(matrix)
                records.append(record)
            for mutation, error in (
                (lambda graph: graph.__setitem__("version", "0.0.80"), "version"),
                (lambda graph: graph.__setitem__("registry", "https://mirror.invalid/"), "registry"),
                (lambda graph: graph["packages"]["playwright"].__setitem__("integrity", "sha512-tampered"), "package graph"),
                (lambda graph: graph["install"].__setitem__("argv", ["npm", "install"]), "install"),
                (lambda graph: graph["direct_entrypoint"].__setitem__("stdout", "Version 0.0.80"), "entrypoint"),
            ):
                with self.subTest(error=error):
                    invalid = copy.deepcopy(records)
                    playwright_record = next(record for record in invalid if record["profile"] in matrix.PLAYWRIGHT_PROFILES)
                    mutation(playwright_record["playwright_graph"])
                    with self.assertRaisesRegex(ValueError, error):
                        matrix.verify_records(invalid, identity)
            missing_graph = copy.deepcopy(records)
            del next(record for record in missing_graph if record["profile"] == "playwright")["playwright_graph"]
            output_dir = root / "aggregate"
            output_dir.mkdir(mode=0o700)
            with patch.object(matrix, "expected_identity", return_value=identity), \
                    patch.object(matrix, "read_evidence", return_value=missing_graph), \
                    self.assertRaisesRegex(ValueError, "missing"):
                matrix.aggregate(Path("/rc-archive"), Path("/rc-checksum"), Path("/rc-manifest"), evidence_dir, output_dir / matrix.AGGREGATE_NAME)
            self.assertFalse((output_dir / matrix.AGGREGATE_NAME).exists())
            records_by_profile = {record["profile"]: record for record in records}
            records_by_profile["cbm"]["playwright_graph"] = self.playwright_acceptance_evidence(matrix)
            with self.assertRaisesRegex(ValueError, "unexpected"):
                matrix.verify_records(list(records_by_profile.values()), identity)

    def test_acceptance_matrix_rejects_missing_duplicate_invalid_failed_mismatched_or_unsafe_evidence(self) -> None:
        matrix = load_acceptance_matrix()
        identity = {"tag": "v3.1.0-rc.1"}
        valid = {"schema": matrix.SCHEMA, "status": "PASS", "profile": "cbm", "rc": identity, "journal": {}}
        with self.assertRaisesRegex(ValueError, "exactly"):
            matrix.verify_records([valid], identity)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            matrix.verify_records([valid, valid], identity)
        records = [dict(valid, profile=profile) for profile in matrix.PROFILES]
        records[0]["status"] = "FAIL"
        with self.assertRaisesRegex(ValueError, "did not pass"):
            matrix.verify_records(records, identity)
        records = [dict(valid, profile=profile) for profile in matrix.PROFILES]
        records[0]["rc"] = {"tag": "v3.1.0-rc.2"}
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            matrix.verify_records(records, identity)
        with self.assertRaisesRegex(ValueError, "outside /home"):
            matrix.safe_evidence_dir(Path("/home"))
        with tempfile.TemporaryDirectory() as temporary:
            evidence_dir = Path(temporary)
            (evidence_dir / "broken.json").write_text("{", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "invalid JSON"):
                matrix.read_evidence(evidence_dir)
        with tempfile.TemporaryDirectory(dir="/var/tmp") as temporary:
            root = Path(temporary)
            evidence_dir = root / "evidence"
            evidence_dir.mkdir()
            with self.assertRaisesRegex(ValueError, "separate from evidence"):
                matrix.safe_output_file(evidence_dir / matrix.AGGREGATE_NAME, evidence_dir)
            public_output = root / "public-output"
            public_output.mkdir(mode=0o755)
            with self.assertRaisesRegex(ValueError, "inaccessible"):
                matrix.safe_output_file(public_output / matrix.AGGREGATE_NAME, evidence_dir)

    def test_acceptance_laboratory_is_not_a_pegasus_catalog_artifact(self) -> None:
        catalog = self.engine.load_catalog()
        sources = {entry["source"] for entry in catalog["artifacts"]}
        self.assertFalse(any(source.startswith("scripts/") for source in sources))
        self.assertNotIn("scripts/accept-v3-isolated.sh", sources)
        self.assertNotIn("scripts/provision-v3-rc-host.sh", sources)

    def test_release_builder_requires_and_records_curated_cbm_bundle(self) -> None:
        source = (ROOT / "tools" / "build_release_manifest.py").read_text(encoding="utf-8")
        self.assertNotIn("--cbm-artifact", source)
        self.assertIn('source_url.removeprefix("release-bundle:")', source)
        self.assertIn('"curated_dependencies"', source)
        self.assertIn('RC_TAG = re.compile', source)
        self.assertIn('"archive_evidence"', source)

    def test_curated_cbm_bundle_is_a_safe_tracked_release_source(self) -> None:
        contract = self.engine.load_contract()
        dependency = next(item for item in contract["dependencies"] if item["id"] == "cbm")
        provenance = json.loads((ROOT / "manifests" / "cbm-linux-x64-provenance.json").read_text())
        bundle = ROOT / dependency["source_url"].removeprefix("release-bundle:")
        self.assertTrue(bundle.is_file())
        self.assertFalse(bundle.is_symlink())
        self.assertEqual(bundle.stat().st_mode & 0o777, 0o644)
        self.assertEqual(hashlib.sha256(bundle.read_bytes()).hexdigest(), dependency["integrity"]["sha256"])
        self.assertEqual(dependency["integrity"]["sha256"], provenance["artifact_sha256"])

    def test_rc_archive_generation_records_curated_membership_and_evidence_consistency(self) -> None:
        builder = load_release_builder()
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Path(temporary)
            (fixture / "manifests").mkdir()
            (fixture / "bin").mkdir()
            (fixture / "dependencies").mkdir()
            installer = fixture / "install.sh"
            installer.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            installer.chmod(0o755)
            (fixture / "bin" / "pegasus").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            curated = fixture / "dependencies" / "curated-cbm.tar.gz"
            curated.write_bytes(b"curated CBM artifact fixture")
            curated_digest = hashlib.sha256(curated.read_bytes()).hexdigest()
            (fixture / "manifests" / "release-contract.json").write_text(json.dumps({"schema": "pegasus-harness-release-contract/v3", "version": "3.1.0", "dependencies": [{"id": "cbm", "source_url": "release-bundle:dependencies/curated-cbm.tar.gz"}]}), encoding="utf-8")
            (fixture / "manifests" / "artifact-catalog.json").write_text(json.dumps({"schema": "pegasus-harness-artifact-catalog/v3", "artifacts": []}), encoding="utf-8")
            build_command = "canonical build command"
            (fixture / "manifests" / "cbm-linux-x64-provenance.json").write_text(json.dumps({"artifact_sha256": curated_digest, "build_command": build_command, "build_command_sha256": hashlib.sha256(build_command.encode("utf-8")).hexdigest()}), encoding="utf-8")
            for command in (("git", "init", "-q"), ("git", "config", "user.email", "tests@example.invalid"), ("git", "config", "user.name", "Pegasus tests"), ("git", "add", "install.sh", "bin", "manifests", "dependencies"), ("git", "commit", "-qm", "RC fixture"), ("git", "tag", "-am", "RC fixture", "v3.1.0-rc.1")):
                subprocess.run(command, cwd=fixture, check=True)
            archive = fixture / "dist" / "pegasus-harness-v3.1.0-rc.1.tar.gz"
            output = fixture / "dist" / "release-manifest.json"
            with patch.object(builder, "ROOT", fixture), patch.object(sys, "argv", ["build_release_manifest.py", "--tag", "v3.1.0-rc.1", "--archive", str(archive), "--output", str(output)]):
                self.assertEqual(builder.main(), 0)
            manifest = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(manifest["tag"], "v3.1.0-rc.1")
            self.assertEqual(manifest["assets"][0]["sha256"], hashlib.sha256(archive.read_bytes()).hexdigest())
            checksum = archive.with_name(archive.name + ".sha256")
            self.assertEqual(
                checksum.read_text(encoding="utf-8"),
                f"{hashlib.sha256(archive.read_bytes()).hexdigest()}  {archive.name}\n",
            )
            self.assertNotIn(str(archive), checksum.read_text(encoding="utf-8"))
            self.assertEqual(
                load_acceptance_contract().validate_rc_inputs("cbm", archive, checksum, output),
                "pegasus-harness-v3.1.0-rc.1",
            )
            self.assertEqual(manifest["curated_dependencies"], [{"id": "cbm", "path": "dependencies/curated-cbm.tar.gz", "sha256": curated_digest, "provenance": "manifests/cbm-linux-x64-provenance.json"}])
            self.assertEqual(json.loads((fixture / "manifests" / "release-contract.json").read_text())["dependencies"][0]["source_url"], "release-bundle:" + manifest["curated_dependencies"][0]["path"])
            self.assertEqual({item["path"] for item in manifest["archive_evidence"]}, {"manifests/release-contract.json", "manifests/artifact-catalog.json", "manifests/cbm-linux-x64-provenance.json", "dependencies/curated-cbm.tar.gz"})
            with tarfile.open(archive, "r:gz") as contents:
                names = {member.name for member in contents.getmembers()}
                root = "pegasus-harness-v3.1.0-rc.1/"
                self.assertTrue({root + "install.sh", root + "bin/pegasus", root + "manifests/release-contract.json", root + "manifests/artifact-catalog.json", root + "manifests/cbm-linux-x64-provenance.json", root + "dependencies/curated-cbm.tar.gz"}.issubset(names))
                bundle = contents.getmember(root + "dependencies/curated-cbm.tar.gz")
                self.assertEqual(bundle.mode & 0o777, 0o644)
                self.assertEqual(hashlib.sha256(contents.extractfile(bundle).read()).hexdigest(), curated_digest)

    def test_release_gate_and_spanish_docs_require_same_commit_rc_evidence_before_final_tag(self) -> None:
        workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
        docs = (ROOT / "docs/release-distribution.md").read_text(encoding="utf-8") + (ROOT / "docs/instalacion-aditiva-v3.md").read_text(encoding="utf-8")
        for required in ("v3.1.1-rc.1", "validate_snapshot.py", "rc-acceptance-evidence.json", "accepted_v311_rc1_aggregate_b64"):
            self.assertIn(required, workflow)
        for required in ("v3.1.1-rc.1", "evidencia", "mismo commit", "nunca mutar"):
            self.assertIn(required, docs)

    def test_final_release_builder_records_v311_identity_promotion_and_documentation(self) -> None:
        builder = load_release_builder()
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Path(temporary)
            (fixture / "manifests").mkdir()
            (fixture / "bin").mkdir()
            (fixture / "dependencies").mkdir()
            (fixture / "docs").mkdir()
            (fixture / "install.sh").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            (fixture / "install.sh").chmod(0o755)
            (fixture / "bin" / "pegasus").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            curated = fixture / "dependencies" / "curated-cbm.tar.gz"
            curated.write_bytes(b"curated CBM artifact fixture")
            curated_digest = hashlib.sha256(curated.read_bytes()).hexdigest()
            (fixture / "manifests" / "release-contract.json").write_text(json.dumps({"schema": "pegasus-harness-release-contract/v3", "version": "3.1.0", "dependencies": [{"id": "cbm", "source_url": "release-bundle:dependencies/curated-cbm.tar.gz"}]}), encoding="utf-8")
            (fixture / "manifests" / "artifact-catalog.json").write_text(json.dumps({"schema": "pegasus-harness-artifact-catalog/v3", "artifacts": []}), encoding="utf-8")
            (fixture / "manifests" / "cbm-linux-x64-provenance.json").write_text(json.dumps({"artifact_sha256": curated_digest, "build_command": "canonical", "build_command_sha256": hashlib.sha256(b"canonical").hexdigest()}), encoding="utf-8")
            for path in ("README.md", "INSTALL.md", "INSTALL_BY_AGENT.md", "MANUAL.md", "docs/release-distribution.md"):
                (fixture / path).write_text(path + "\n", encoding="utf-8")
            for command in (("git", "init", "-q"), ("git", "config", "user.email", "tests@example.invalid"), ("git", "config", "user.name", "Pegasus tests"), ("git", "add", "."), ("git", "commit", "-qm", "final fixture"), ("git", "tag", "-am", "accepted RC", "v3.1.1-rc.1"), ("git", "tag", "-am", "final", "v3.1.1")):
                subprocess.run(command, cwd=fixture, check=True)
            archive = fixture / "dist" / "pegasus-harness-v3.1.1.tar.gz"
            output = fixture / "dist" / "release-manifest.json"
            argv = ["build_release_manifest.py", "--tag", "v3.1.1", "--promotion-rc-tag", "v3.1.1-rc.1", "--archive", str(archive), "--output", str(output)]
            with patch.object(builder, "ROOT", fixture), patch.object(sys, "argv", argv):
                self.assertEqual(builder.main(), 0)
            manifest = json.loads(output.read_text(encoding="utf-8"))
            checksum = archive.with_name(archive.name + ".sha256")
            self.assertEqual(manifest["release_kind"], "final")
            self.assertEqual(manifest["promotion_rc_tag"], "v3.1.1-rc.1")
            self.assertEqual(manifest["published_assets"], [archive.name, checksum.name, "release-manifest.json"])
            self.assertEqual({item["path"] for item in manifest["documentation_evidence"]}, {"README.md", "INSTALL.md", "INSTALL_BY_AGENT.md", "MANUAL.md", "docs/release-distribution.md"})
            self.assertEqual(manifest["assets"], [{"name": archive.name, "sha256": hashlib.sha256(archive.read_bytes()).hexdigest()}])

    def test_final_preflight_refuses_mismatched_or_unsafe_release_identity(self) -> None:
        preflight = load_agent_preflight()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive, checksum, manifest = self.final_release_fixture(root)
            with patch.object(preflight.os, "geteuid", return_value=1000), patch.object(preflight, "discover_executable", return_value="/usr/bin/true"), patch.object(preflight, "probe", return_value="1.2.3"):
                result = preflight.collect_preflight(archive, checksum, manifest, [])
            self.assertEqual(result["status"], "ready")
            self.assertEqual(result["release"]["tag"], "v3.1.1")
            checksum.write_text("0" * 64 + f"  {archive.name}\n", encoding="utf-8")
            with self.assertRaisesRegex(preflight.PreflightError, "checksum"):
                preflight.collect_preflight(archive, checksum, manifest, [])
            checksum.write_text(f"{hashlib.sha256(archive.read_bytes()).hexdigest()}  {archive.name}\n", encoding="utf-8")
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            payload["tag"] = "v3.1.0-rc.26"
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(preflight.PreflightError, "final identity"):
                preflight.collect_preflight(archive, checksum, manifest, [])
            manifest.unlink()
            manifest.symlink_to(root / "missing.json")
            with self.assertRaisesRegex(preflight.PreflightError, "regular"):
                preflight.collect_preflight(archive, checksum, manifest, [])

    def test_preflight_accepts_only_matching_immutable_rc_assets(self) -> None:
        preflight = load_agent_preflight()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rc_root, final_root = root / "rc", root / "final"
            rc_root.mkdir()
            final_root.mkdir()
            rc_archive, rc_checksum, rc_manifest = self.rc_release_fixture(rc_root)
            final_archive, _, final_manifest = self.final_release_fixture(final_root)
            with patch.object(preflight.os, "geteuid", return_value=1000), patch.object(preflight, "discover_executable", return_value="/usr/bin/true"), patch.object(preflight, "probe", return_value="1.2.3"):
                result = preflight.collect_preflight(rc_archive, rc_checksum, rc_manifest, [])
            self.assertEqual(result["release"]["tag"], "v3.1.1-rc.1")
            with self.assertRaisesRegex(preflight.PreflightError, "final identity"):
                preflight.collect_preflight(rc_archive, rc_checksum, final_manifest, [])
            final_checksum = final_archive.with_name(final_archive.name + ".sha256")
            with self.assertRaisesRegex(preflight.PreflightError, "RC identity"):
                preflight.collect_preflight(final_archive, final_checksum, rc_manifest, [])

    def test_v311_rc1_aggregate_validator_refuses_invalid_evidence_before_final_publish(self) -> None:
        validator = load_rc_acceptance_aggregate_validator()
        matrix = load_acceptance_matrix()
        with tempfile.TemporaryDirectory(dir="/var/tmp") as temporary:
            root = Path(temporary)
            tag = "v3.1.1-rc.1"
            archive = root / f"pegasus-harness-{tag}.tar.gz"
            prefix = f"pegasus-harness-{tag}/"
            payloads = {
                "manifests/release-contract.json": b"{}",
                "manifests/artifact-catalog.json": b"{}",
                "manifests/cbm-linux-x64-provenance.json": b"{}",
                "dependencies/cbm.tar.gz": b"cbm",
            }
            members = [(self.directory_member(prefix), b"")]
            members.extend((self.regular_member(prefix + path), payload) for path, payload in payloads.items())
            members.extend([
                (self.regular_member(prefix + "bin/pegasus"), b"#!/usr/bin/env python3\n"),
                (self.regular_member(prefix + "install.sh"), b"#!/bin/sh\n"),
            ])
            self.write_archive(archive, members)
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            checksum = root / f"{archive.name}.sha256"
            checksum.write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
            manifest = root / "release-manifest.json"
            manifest.write_text(json.dumps({
                "schema": "pegasus-harness-release/v3", "tag": tag,
                "archive_root": prefix[:-1], "assets": [{"name": archive.name, "sha256": digest}],
                "curated_dependencies": [{"id": "cbm", "path": "dependencies/cbm.tar.gz"}],
                "archive_evidence": [{"path": path, "sha256": hashlib.sha256(payload).hexdigest()} for path, payload in payloads.items()],
            }), encoding="utf-8")
            identity = matrix.expected_identity(archive, checksum, manifest)
            graph = self.playwright_acceptance_evidence(matrix)
            aggregate = root / "rc-acceptance-aggregate.json"
            payload = {
                "schema": matrix.AGGREGATE_SCHEMA, "status": "PASS", "rc": identity,
                "profiles": sorted(matrix.PROFILES),
                "profile_evidence": {profile: {} for profile in matrix.PROFILES},
                "playwright_graph": {profile: graph for profile in matrix.PLAYWRIGHT_PROFILES},
                "purpose": "promotion-gate-input-only",
            }
            aggregate.write_text(json.dumps(payload), encoding="utf-8")
            self.assertEqual(validator.validate(aggregate, archive, checksum, manifest), identity)
            payload["status"] = "FAIL"
            aggregate.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "PASS"):
                validator.validate(aggregate, archive, checksum, manifest)
            payload["status"] = "PASS"
            payload["rc"] = {**identity, "archive_sha256": "0" * 64}
            aggregate.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "identity"):
                validator.validate(aggregate, archive, checksum, manifest)

    def test_agent_preflight_is_json_only_allowlisted_and_redacted(self) -> None:
        preflight = load_agent_preflight()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive, checksum, manifest = self.final_release_fixture(root)
            commands = {name: root / name for name in ("python", "opencode", "codebase-memory-mcp", "engram", "browser")}
            for path in commands.values():
                self.fixture_command(path, "private-token=never-disclose 1.2.3")
            def discover(name: str) -> str | None:
                return str(commands["python"]) if name.startswith("python") else (str(commands[name]) if name in commands else None)
            with patch.object(preflight.os, "geteuid", return_value=1000), patch.object(preflight, "discover_executable", side_effect=discover):
                result = preflight.collect_preflight(archive, checksum, manifest, ["cbm", "engram", "playwright", "context7"], commands["browser"])
            rendered = json.dumps(result)
            self.assertEqual(result["status"], "ready")
            self.assertEqual(result["mcps"]["context7"]["status"], "decision-required")
            self.assertNotIn("private-token", rendered)
            self.assertNotIn("opencode debug config", (ROOT / "tools" / "agent_install_preflight.py").read_text(encoding="utf-8"))
            with self.assertRaisesRegex(preflight.PreflightError, "duplicate"):
                preflight.collect_preflight(archive, checksum, manifest, ["cbm", "cbm"])
            with self.assertRaisesRegex(preflight.PreflightError, "unknown"):
                preflight.collect_preflight(archive, checksum, manifest, ["unknown"])
            with patch.object(preflight.os, "geteuid", return_value=0):
                with self.assertRaisesRegex(preflight.PreflightError, "non-root"):
                    preflight.collect_preflight(archive, checksum, manifest, [])
            calls = []
            with patch.object(preflight.subprocess, "run", side_effect=lambda argv, **_: calls.append(argv) or SimpleNamespace(returncode=0, stdout="1.2.3")):
                self.assertEqual(preflight.probe("/safe/executable", "--help"), "1.2.3")
            self.assertEqual(calls, [["/safe/executable", "--help"]])

    def test_agent_preflight_cli_emits_only_redacted_json_on_failure(self) -> None:
        preflight = load_agent_preflight()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive, checksum, manifest = self.final_release_fixture(root)
            with patch.object(preflight.os, "geteuid", return_value=0), patch("sys.stdout", new_callable=io.StringIO) as stdout:
                self.assertEqual(preflight.main(["--archive", str(archive), "--checksum", str(checksum), "--release-manifest", str(manifest)]), 2)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload, {"schema": "pegasus-harness-agent-preflight/v3", "status": "blocked", "reason": "a non-root Linux account is required"})

    def test_final_release_workflow_and_agent_docs_define_latest_contract_without_config_dump(self) -> None:
        workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
        agent = (ROOT / "INSTALL_BY_AGENT.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        install = (ROOT / "INSTALL.md").read_text(encoding="utf-8")
        release_docs = (ROOT / "docs/release-distribution.md").read_text(encoding="utf-8")
        for required in ("v3.1.1", "v3.1.1-rc.1", "prerelease: false", "pegasus-harness-v3.1.1.tar.gz", "release-manifest.json", "promotion_rc_tag", "accepted_v311_rc1_aggregate_b64", "validate-v3-acceptance-aggregate.py", "gh release download"):
            self.assertIn(required, workflow)
        self.assertLess(workflow.index("validate-v3-acceptance-aggregate.py"), workflow.rindex("softprops/action-gh-release@v2"))
        self.assertLess(workflow.index("validate-v3-acceptance-aggregate.py"), workflow.index("git tag -a v3.1.1"))
        self.assertIn("! git rev-parse -q --verify refs/tags/v3.1.1", workflow)
        self.assertIn("git push origin refs/tags/v3.1.1", workflow)
        self.assertIn('test "$(git rev-list -n 1 v3.1.1)" = "$rc_commit"', workflow)
        self.assertNotIn("v3.1.0-rc.26", workflow)
        for required in ("v3.1.1-rc.1", "releases/download/v3.1.1", "releases/latest/download", "agent_install_preflight.py", "--opencode", "cbm", "engram", "playwright", "context7", "/connect", "/models"):
            self.assertIn(required, agent)
        preflight_block = next(block for block in agent.split("```sh\n")[1:]
                               if "agent_install_preflight.py" in block)
        for required in ('RELEASE_TAG="v3.1.1-rc.1"', 'ARCHIVE="pegasus-harness-${RELEASE_TAG}.tar.gz"',
                         'CHECKSUM="${ARCHIVE}.sha256"', 'RELEASE_MANIFEST="release-manifest.json"',
                         '--archive "$ARCHIVE"', '--checksum "$CHECKSUM"',
                         '--release-manifest "$RELEASE_MANIFEST"'):
            self.assertIn(required, preflight_block)
        self.assertNotIn("--archive pegasus-harness-v3.1.1.tar.gz", preflight_block)
        self.assertNotIn("opencode debug config", agent)
        self.assertIn("INSTALL_BY_AGENT.md", readme)
        self.assertIn("INSTALL_BY_AGENT.md", install)
        self.assertIn("v3.1.1", release_docs)

    def test_safe_archive_extraction_rejects_all_unsafe_member_classes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cases = []
            absolute = self.regular_member("/escape")
            cases.append(("absolute", absolute, {"/escape"}, "unsafe"))
            traversal = self.regular_member("../escape")
            cases.append(("traversal", traversal, {"../escape"}, "unsafe"))
            symlink = tarfile.TarInfo("bin/codebase-memory-mcp")
            symlink.type, symlink.linkname = tarfile.SYMTYPE, "target"
            cases.append(("symlink", symlink, {"bin/codebase-memory-mcp"}, "unsafe"))
            hardlink = tarfile.TarInfo("bin/codebase-memory-mcp")
            hardlink.type, hardlink.linkname = tarfile.LNKTYPE, "target"
            cases.append(("hard-link", hardlink, {"bin/codebase-memory-mcp"}, "unsafe"))
            directory = tarfile.TarInfo("bin")
            directory.type = tarfile.DIRTYPE
            cases.append(("directory", directory, {"bin"}, "unsafe"))
            unexpected = self.regular_member("bin/unexpected")
            cases.append(("unexpected-layout", unexpected, {"bin/codebase-memory-mcp"}, "layout"))
            for name, member, expected, message in cases:
                with self.subTest(name=name):
                    archive, destination = root / f"{name}.tar.gz", root / name
                    self.write_archive(archive, [(member, b"fixture")])
                    with self.assertRaisesRegex(RuntimeError, message):
                        self.engine.safe_extract_archive(archive, destination, expected)
                    self.assertFalse(destination.exists())
                    self.assertFalse(destination.with_name(destination.name + ".partial").exists())

    def test_local_dependency_fixtures_extract_expected_layout_and_probe(self) -> None:
        fixtures = {
            "cbm": {"bin/codebase-memory-mcp": b"#!/bin/sh\nprintf 'codebase-memory-mcp 0.9.0\\n'\n"},
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for identifier, files in fixtures.items():
                with self.subTest(dependency=identifier):
                    archive = root / f"{identifier}.tar.gz"
                    self.write_archive(archive, [(self.regular_member(name), content) for name, content in files.items()])
                    destination = root / identifier
                    self.engine.install_dependency(self.fixture_dependency(identifier, archive), destination, archive)
                    self.assertEqual({path.relative_to(destination).as_posix() for path in destination.rglob("*") if path.is_file()}, set(files))
                    self.assertFalse((root / f"{identifier}.download.partial").exists())

            archive = root / "engram.tar.gz"
            self.write_archive(archive, self.engram_archive_members())
            destination = root / "engram"
            self.engine.install_dependency(self.fixture_dependency("engram", archive), destination, archive)
            self.assertEqual({path.relative_to(destination).as_posix() for path in destination.rglob("*") if path.is_file()},
                             {"CHANGELOG.md", "LICENSE", "README.md", "engram"})
            self.assertEqual((destination / "engram").stat().st_mode & 0o777, 0o755)
            self.assertFalse((root / "engram.download.partial").exists())

    def test_engram_archive_requires_the_fixed_linux_amd64_member_set(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            item = copy.deepcopy(next(item for item in self.engine.load_contract()["dependencies"] if item["id"] == "engram"))
            expected = self.engine.expected_archive_members(item)
            executables = self.engine.expected_archive_executables(item)
            unsafe = tarfile.TarInfo("engram")
            unsafe.type, unsafe.linkname = tarfile.SYMTYPE, "target"
            cases = [
                ("actual", self.engram_archive_members(), None),
                ("missing", self.engram_archive_members()[:-1], "layout"),
                ("extra", self.engram_archive_members() + [(self.regular_member("NOTICE", 0o644), b"notice\n")], "layout"),
                ("unsafe", [(unsafe, b"")], "unsafe"),
                ("wrong-mode", self.engram_archive_members()[:-1] + [(self.regular_member("engram", 0o644), b"#!/bin/sh\nprintf 'engram 1.20.0\\n'\n")], "permissions"),
            ]
            for name, members, error in cases:
                with self.subTest(name=name):
                    archive, destination = root / f"{name}.tar.gz", root / name
                    self.write_archive(archive, members)
                    if error:
                        with self.assertRaisesRegex(RuntimeError, error):
                            self.engine.safe_extract_archive(archive, destination, expected, executables)
                        self.assertFalse(destination.exists())
                        self.assertFalse(destination.with_name(destination.name + ".partial").exists())
                    else:
                        self.engine.safe_extract_archive(archive, destination, expected, executables)
                        self.assertEqual({path.name for path in destination.iterdir()}, expected)
                        self.assertEqual((destination / "engram").stat().st_mode & 0o777, 0o755)

    def test_release_bundle_installs_from_verified_extracted_rc_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            release_root, bundle = self.extracted_rc_bundle_fixture(root)
            item = self.fixture_dependency("cbm", bundle)
            self.assertEqual(item["source_url"], "release-bundle:dependencies/codebase-memory-mcp-v0.9.0-linux-x86_64.tar.gz")
            target = self.temporary_target(root / "home")
            plan = self.engine.plan(self.engine.detect(target, "opencode"), self.engine.load_catalog(), self.engine.load_contract())
            next(entry for entry in plan["dependencies"] if entry["id"] == "cbm")["metadata"] = item
            with patch.object(self.engine.urllib.request, "urlopen", side_effect=AssertionError("release bundle must stay offline")) as urlopen:
                result = self.engine.apply(plan, target, {"cbm"}, browser_ready=True, declined={"engram", "playwright", "context7"}, release_root=release_root, release_identity=self.rc_release_identity_fixture(release_root))
            urlopen.assert_not_called()
            self.assertIn("opencode-mcp", result["created"])
            self.assertTrue((target["dependencies"] / "cbm" / "bin/codebase-memory-mcp").is_file())
            self.assertIn("codebase-memory-mcp", json.loads(target["opencode_config"].read_text())["mcp"])
            journal = self.engine.load_journal(target)
            self.assertTrue(target["journal"].is_file())
            self.assertEqual(target["journal"], target["home"] / ".local/share/pegasus-harness/journal-v3.json")
            self.assertEqual(target["journal"].stat().st_uid, target["home"].stat().st_uid)
            self.assertNotEqual(target["journal"].stat().st_uid, 0)
            self.assertEqual(journal["release"]["tag"], "v3.1.0-rc.1")
            self.assertEqual(journal["release"]["archive_name"], "pegasus-harness-v3.1.0-rc.1.tar.gz")
            self.assertEqual(journal["release"]["archive_sha256"], "a" * 64)
            self.assertEqual(journal["release"]["manifest_sha256"], "b" * 64)
            self.assertEqual(journal["release"]["version"], "3.1.0")
            dependency = next(entry for entry in journal["entries"] if entry["id"] == "dependency-cbm")
            self.assertEqual(dependency["target"], str(target["dependencies"] / "cbm"))
            self.assertEqual(dependency["source_digest"], hashlib.sha256(bundle.read_bytes()).hexdigest())
            self.assertEqual(dependency["baseline_digest"], self.engine.directory_digest(target["dependencies"] / "cbm"))
            self.assertTrue(all(entry["ownership"] == "owned" for entry in journal["entries"]))
            self.assertEqual(self.engine.validate(target), 0)
            self.assertTrue(target["journal"].is_file())
            rollback = self.engine.rollback(target)
            self.assertIn("dependency-cbm", rollback["removed"])
            self.assertFalse(target["journal"].exists())
            self.assertFalse((target["dependencies"] / "cbm").exists())

    def test_extracted_rc_fixture_uses_standalone_engram_probe_without_changing_runtime_argv(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            release_root, _ = self.extracted_rc_bundle_fixture(root)
            contract = json.loads((release_root / "manifests" / "release-contract.json").read_text(encoding="utf-8"))
            item = next(dependency for dependency in contract["dependencies"] if dependency["id"] == "engram")
            archive = release_root / "dependencies" / "engram_1.20.0_linux_amd64.tar.gz"
            item["integrity"] = {"sha256": hashlib.sha256(archive.read_bytes()).hexdigest()}
            self.assertEqual(item["runtime_argv"], ["{dependency}/engram", "mcp", "--tools=agent"])
            self.assertEqual(item["probe_argv"], ["{dependency}/engram", "--version"])
            destination = root / "dependencies" / "engram"
            self.engine.install_dependency(item, destination, archive, release_root)
            self.assertTrue((destination / "engram").is_file())

    def test_external_rc_apply_rejects_missing_or_wrong_identity_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            release_root, _ = self.extracted_rc_bundle_fixture(root)
            target = self.temporary_target(root / "home")
            plan = self.engine.plan(self.engine.detect(target, "opencode"), self.engine.load_catalog(), self.engine.load_contract())
            arguments = {"declined": {"engram", "playwright", "context7"}, "release_root": release_root}
            with self.assertRaisesRegex(RuntimeError, "identity is required"):
                self.engine.apply(plan, target, {"cbm"}, browser_ready=True, **arguments)
            wrong = self.rc_release_identity_fixture(release_root)
            wrong["tag"] = "v3.1.0-rc.2"
            wrong["archive_name"] = "pegasus-harness-v3.1.0-rc.2.tar.gz"
            wrong["archive_root"] = "pegasus-harness-v3.1.0-rc.2"
            with self.assertRaisesRegex(RuntimeError, "does not match"):
                self.engine.apply(plan, target, {"cbm"}, browser_ready=True, release_identity=wrong, **arguments)
            with self.assertRaisesRegex(RuntimeError, "identity is malformed"):
                self.engine.apply(plan, target, {"cbm"}, browser_ready=True,
                                  release_identity={"tag": "invalid"}, **arguments)
            self.assertFalse(target["journal"].exists())
            self.assertFalse(target["opencode_config"].exists())
            self.assertFalse((target["dependencies"] / "cbm").exists())

    def test_atomic_journal_failure_leaves_no_partial_or_published_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            release_root, _ = self.extracted_rc_bundle_fixture(root)
            target = self.temporary_target(root / "home")
            target["home"].mkdir()
            journal = {"schema": "pegasus-harness-journal/v3", "version": "3.1.0",
                       "release": self.engine.journal_release(release_root), "entries": [], "links": []}
            with patch.object(self.engine.os, "replace", side_effect=OSError("disk error")):
                with self.assertRaisesRegex(OSError, "disk error"):
                    self.engine.write_journal(target, journal)
            self.assertFalse(target["journal"].exists())
            self.assertFalse(list(target["journal"].parent.glob(".journal-v3.*.partial")))

    def test_root_cannot_write_an_ownership_journal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = self.temporary_target(Path(temporary))
            with patch.object(self.engine.os, "geteuid", return_value=0):
                with self.assertRaisesRegex(RuntimeError, "non-root target user"):
                    self.engine.write_journal(target, {"schema": "pegasus-harness-journal/v3", "version": "3.1.0", "entries": [], "links": []})

    def test_journal_records_existing_dependencies_as_non_owning_links(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = self.temporary_target(Path(temporary))
            target["opencode_config"].parent.mkdir(parents=True)
            executable = target["home"] / "safe-cbm"
            self.fixture_command(executable, "codebase-memory-mcp 0.9.0")
            target["opencode_config"].write_text(json.dumps({"mcp": {"codebase-memory-mcp": {"type": "local", "command": [str(executable)]}}}), encoding="utf-8")
            plan = self.engine.plan(self.engine.detect(target, "opencode"), self.engine.load_catalog(), self.engine.load_contract())
            self.engine.apply(plan, target, {"context7"}, browser_ready=True, declined={"engram", "playwright"})
            journal = self.engine.load_journal(target)
            self.assertIn({"id": "cbm", "target": str(executable), "ownership": "non-owning-link"}, journal["links"])
            self.assertNotIn("dependency-cbm", {entry["id"] for entry in journal["entries"]})
            self.assertEqual(self.engine.validate(target), 0)

    def test_release_bundle_rejects_unsafe_missing_and_symlinked_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            release_root, _ = self.extracted_rc_bundle_fixture(root)
            linked = release_root / "dependencies" / "linked.tar.gz"
            linked.symlink_to(release_root / "dependencies" / "codebase-memory-mcp-v0.9.0-linux-x86_64.tar.gz")
            for source in (
                "release-bundle:/etc/passwd",
                "release-bundle:../outside.tar.gz",
                "release-bundle:dependencies/../outside.tar.gz",
                "release-bundle:dependencies/missing.tar.gz",
                "release-bundle:dependencies/linked.tar.gz",
            ):
                with self.subTest(source=source), self.assertRaisesRegex(RuntimeError, "release bundle"):
                    self.engine.resolve_release_bundle(source, release_root)

    def test_release_bundle_sha_mismatch_leaves_no_dependency_journal_or_config(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            release_root, bundle = self.extracted_rc_bundle_fixture(root)
            item = self.fixture_dependency("cbm", bundle)
            self.assertEqual(item["source_url"], "release-bundle:dependencies/codebase-memory-mcp-v0.9.0-linux-x86_64.tar.gz")
            item["integrity"]["sha256"] = "0" * 64
            target = self.temporary_target(root / "home")
            plan = self.engine.plan(self.engine.detect(target, "opencode"), self.engine.load_catalog(), self.engine.load_contract())
            next(entry for entry in plan["dependencies"] if entry["id"] == "cbm")["metadata"] = item
            with patch.object(self.engine.urllib.request, "urlopen", side_effect=AssertionError("release bundle must stay offline")) as urlopen:
                with self.assertRaisesRegex(RuntimeError, "integrity"):
                    self.engine.apply(plan, target, {"cbm"}, browser_ready=True, declined={"engram", "playwright", "context7"}, release_root=release_root, release_identity=self.rc_release_identity_fixture(release_root))
            urlopen.assert_not_called()
            self.assertFalse(target["dependencies"].exists())
            self.assertFalse(target["journal"].exists())
            self.assertFalse(target["opencode_config"].exists())
            self.assertFalse((target["dependencies"].parent / "cbm.download.partial").exists())

    def test_fixed_remote_dependency_still_uses_its_https_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "engram.tar.gz"
            self.write_archive(archive, self.engram_archive_members())
            item = self.fixture_dependency("engram", archive)
            destination = root / "dependencies" / "engram"
            with patch.object(self.engine.urllib.request, "urlopen", return_value=io.BytesIO(archive.read_bytes())) as urlopen:
                self.engine.install_dependency(item, destination)
            urlopen.assert_called_once_with(item["source_url"], timeout=30)
            self.assertTrue((destination / "engram").is_file())

    def test_tampered_dependency_bytes_and_integrity_leave_no_staging_or_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for identifier, files in {
                "cbm": {"bin/codebase-memory-mcp": b"#!/bin/sh\nprintf '0.9.0\\n'\n"},
            }.items():
                with self.subTest(dependency=identifier):
                    archive = root / f"{identifier}.tar.gz"
                    self.write_archive(archive, [(self.regular_member(name), content) for name, content in files.items()])
                    item = self.fixture_dependency(identifier, archive)
                    item["integrity"]["sha256"] = "0" * 64
                    error = "integrity"
                    destination = root / f"{identifier}-failed"
                    with self.assertRaisesRegex(RuntimeError, error):
                        self.engine.install_dependency(item, destination, archive)
                    self.assertFalse(destination.exists())
                    self.assertFalse(destination.with_name(destination.name + ".partial").exists())
                    self.assertFalse(destination.with_name(destination.name + ".download.partial").exists())
            archive = root / "engram.tar.gz"
            self.write_archive(archive, self.engram_archive_members())
            item = self.fixture_dependency("engram", archive)
            item["integrity"]["sha256"] = "0" * 64
            destination = root / "engram-failed"
            with self.assertRaisesRegex(RuntimeError, "integrity"):
                self.engine.install_dependency(item, destination, archive)
            self.assertFalse(destination.exists())
            self.assertFalse(destination.with_name(destination.name + ".partial").exists())
            self.assertFalse(destination.with_name(destination.name + ".download.partial").exists())

    def test_playwright_npm_staging_promotes_only_verified_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            npm, destination = root / "npm", root / "dependencies" / "playwright"
            self.fake_npm(npm)
            item = copy.deepcopy(next(item for item in self.engine.load_contract()["dependencies"] if item["id"] == "playwright"))
            self.engine.install_playwright(item, destination, str(npm))
            self.assertEqual((destination / "node_modules/@playwright/mcp/cli.js").is_file(), True)
            self.assertTrue((destination / "node_modules/.bin/playwright").is_symlink())
            self.engine.directory_digest(destination, allow_playwright_npm_bins=True)
            self.assertFalse(any(destination.parent.glob(".playwright-npm-*")))
            self.assertEqual((destination.parent / "npm-argv.txt").read_text(), "ci --ignore-scripts")
            source = SCRIPT.read_text(encoding="utf-8")
            self.assertIn('"NPM_CONFIG_REGISTRY": "https://registry.npmjs.org/"', source)
            self.assertIn('"NPM_CONFIG_USERCONFIG": str(user_config)', source)
            self.assertIn('"NPM_CONFIG_GLOBALCONFIG": str(global_config)', source)
            self.assertIn('"NPM_CONFIG_IGNORE_SCRIPTS": "true"', source)

    def test_playwright_runtime_fixture_requires_the_core_utils_bundle(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node is required to execute the realistic Playwright runtime fixture")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            npm, destination = root / "npm", root / "dependencies" / "playwright"
            self.fake_npm(npm)
            item = copy.deepcopy(next(item for item in self.engine.load_contract()["dependencies"] if item["id"] == "playwright"))
            self.engine.install_playwright(item, destination, str(npm))
            command = [str(Path(node).resolve()), str(destination / "node_modules/@playwright/mcp/cli.js"), "--version"]
            probe = subprocess.run(command, text=True, capture_output=True, check=False)
            self.assertEqual((probe.returncode, (probe.stdout + probe.stderr).strip()), (0, "Version 0.0.79"))
            (destination / "node_modules/playwright-core/lib/utilsBundle.js").unlink()
            missing_core = subprocess.run(command, text=True, capture_output=True, check=False)
            self.assertNotEqual(missing_core.returncode, 0)
            self.assertIn("playwright-core/lib/utilsBundle", missing_core.stderr)

    def test_playwright_npm_uses_distinct_disposable_configs_for_npm_24(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            npm, destination = root / "npm", root / "dependencies" / "playwright"
            self.fake_npm(npm, "config-collision")
            item = copy.deepcopy(next(item for item in self.engine.load_contract()["dependencies"] if item["id"] == "playwright"))
            self.engine.install_playwright(item, destination, str(npm))
            environment = json.loads((destination.parent / "npm-environment.json").read_text(encoding="utf-8"))
            self.assertEqual(environment["registry"], "https://registry.npmjs.org/")
            self.assertEqual(environment["ignore_scripts"], "true")
            self.assertFalse(environment["config_collision"])
            self.assertTrue(environment["configs_exist"])
            self.assertEqual(environment["proxy_variables"], [])
            self.assertNotEqual(environment["user_config"], os.devnull)
            self.assertNotEqual(environment["global_config"], os.devnull)
            self.assertFalse(any(destination.parent.glob(".playwright-npm-*")))

    def test_playwright_npm_failures_leave_no_runtime_or_staging(self) -> None:
        item = copy.deepcopy(next(item for item in self.engine.load_contract()["dependencies"] if item["id"] == "playwright"))
        for mode, error in (("fail", "npm ci failed"), ("lock-drift", "lockfile"), ("wrong-registry", "approved package graph"), ("wrong-sri", "approved package graph"), ("missing-cli", "expected CLI"), ("wrong-version", "probe")):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                npm, destination = root / "npm", root / "dependencies" / "playwright"
                self.fake_npm(npm, mode)
                with self.assertRaisesRegex(RuntimeError, error):
                    self.engine.install_playwright(item, destination, str(npm))
                self.assertFalse(destination.exists())
                self.assertFalse(any(destination.parent.glob(".playwright-npm-*")))
                self.assertFalse((root / ".config").exists())
                self.assertFalse((root / ".local").exists())

    def test_directory_digest_accepts_only_expected_in_root_playwright_bins(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for relative in self.engine.PLAYWRIGHT_BIN_LINKS.values():
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("cli\n", encoding="utf-8")
            bin_dir = root / "node_modules/.bin"
            bin_dir.mkdir()
            for link, target in self.engine.PLAYWRIGHT_BIN_LINKS.items():
                (root / link).symlink_to(Path("..") / Path(target).relative_to("node_modules"))
            self.assertTrue(self.engine.directory_digest(root, allow_playwright_npm_bins=True))
            with self.assertRaisesRegex(RuntimeError, "unsafe artifact"):
                self.engine.directory_digest(root)

    def test_directory_digest_rejects_unsafe_playwright_bin_links(self) -> None:
        cases = {
            "escaping": (".bin/playwright", "../../outside", "file"),
            "dangling": (".bin/playwright", "../missing", None),
            "directory": (".bin/playwright", "../playwright", "directory"),
            "unexpected": (".bin/unexpected", "../playwright/cli.js", "file"),
        }
        for name, (link, target, target_type) in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                if target_type == "file":
                    destination = root / "node_modules/playwright/cli.js"
                    destination.parent.mkdir(parents=True)
                    destination.write_text("cli\n", encoding="utf-8")
                elif target_type == "directory":
                    (root / "node_modules/playwright").mkdir(parents=True)
                (root / "node_modules" / link).parent.mkdir(parents=True, exist_ok=True)
                (root / "node_modules" / link).symlink_to(target)
                with self.assertRaisesRegex(RuntimeError, "unsafe artifact"):
                    self.engine.directory_digest(root, allow_playwright_npm_bins=True)

    def test_playwright_lock_failures_leave_no_staging_destination_config_or_journal(self) -> None:
        for mode in ("wrong-registry", "wrong-sri"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                target = self.temporary_target(root / "home")
                plan = self.engine.plan(self.engine.detect(target, "opencode"), self.engine.load_catalog(), self.engine.load_contract())
                npm = root / "npm"
                self.fake_npm(npm, mode)
                install_playwright = self.engine.install_playwright
                with patch.object(self.engine, "install_playwright", side_effect=lambda item, destination: install_playwright(item, destination, str(npm))):
                    with self.assertRaisesRegex(RuntimeError, "approved package graph"):
                        self.engine.apply(plan, target, {"playwright"}, browser_ready=True,
                                          declined={"cbm", "engram", "context7"})
                self.assertFalse((target["dependencies"] / "playwright").exists())
                self.assertFalse(any(target["dependencies"].parent.glob(".playwright-npm-*")))
                self.assertFalse(target["opencode_config"].exists())
                self.assertFalse(target["journal"].exists())

    def test_playwright_npm_failure_leaves_no_artifact_config_or_journal_residue(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = self.temporary_target(root / "home")
            plan = self.engine.plan(self.engine.detect(target, "opencode"), self.engine.load_catalog(), self.engine.load_contract())
            npm = root / "npm"
            self.fake_npm(npm, "fail")
            install_playwright = self.engine.install_playwright
            with patch.object(self.engine, "install_playwright", side_effect=lambda item, destination: install_playwright(item, destination, str(npm))):
                with self.assertRaisesRegex(RuntimeError, "npm ci failed"):
                    self.engine.apply(plan, target, {"playwright"}, browser_ready=True,
                                      declined={"cbm", "engram", "context7"})
            self.assertFalse((target["dependencies"] / "playwright").exists())
            self.assertFalse(any(target["dependencies"].parent.glob(".playwright-npm-*")))
            self.assertFalse(target["opencode_config"].exists())
            self.assertFalse(target["journal"].exists())
            environment = json.loads((target["dependencies"] / "npm-environment.json").read_text(encoding="utf-8"))
            for path in (environment["user_config"], environment["global_config"], environment["cache"]):
                self.assertFalse(Path(path).exists())

    def test_offline_playwright_apply_emits_absolute_node_acceptance_evidence_for_matrix(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = self.temporary_target(root / "home")
            plan = self.engine.plan(self.engine.detect(target, "opencode"), self.engine.load_catalog(), self.engine.load_contract())
            npm = root / "npm"
            node = root / "provisioned-node" / "bin" / "node"
            node.parent.mkdir(parents=True)
            self.fixture_command(node, "Version 0.0.79")
            self.fake_npm(npm)
            install_playwright = self.engine.install_playwright
            with patch.object(self.engine.shutil, "which", return_value=str(node)), \
                    patch.object(self.engine, "install_playwright", side_effect=lambda item, destination: install_playwright(item, destination, str(npm))):
                self.engine.apply(plan, target, {"playwright"}, browser_ready=True,
                                  declined={"cbm", "engram", "context7"})
            command = json.loads(target["opencode_config"].read_text(encoding="utf-8"))["mcp"]["playwright"]["command"]
            self.assertEqual(command, [
                str(node.resolve()), str(target["dependencies"] / "playwright" / "node_modules" / "@playwright" / "mcp" / "cli.js")
            ])
            self.assertNotIn("{env:PEGASUS_PLAYWRIGHT_MCP_BIN}", command)
            self.assertNotEqual(command[0], "node")

            probe = subprocess.run(command + ["--version"], text=True, capture_output=True, check=False)
            self.assertEqual((probe.returncode, (probe.stdout + probe.stderr).strip()), (0, "Version 0.0.79"))
            matrix = load_acceptance_matrix()
            graph = self.playwright_acceptance_evidence(matrix)
            graph["direct_entrypoint"] = {"argv": command + ["--version"], "stdout": (probe.stdout + probe.stderr).strip(), "exit_code": probe.returncode}
            records = []
            for profile in sorted(matrix.PROFILES):
                record = {"schema": matrix.SCHEMA, "status": "PASS", "profile": profile, "rc": {"tag": "v3.1.0-rc.1"}, "journal": {}}
                if profile in matrix.PLAYWRIGHT_PROFILES:
                    record["playwright_graph"] = copy.deepcopy(graph)
                records.append(record)
            self.assertEqual(set(matrix.verify_records(records, {"tag": "v3.1.0-rc.1"})), matrix.PROFILES)

    def test_fresh_owned_local_mcps_render_absolute_commands_without_environment_templates(self) -> None:
        """A new target can launch every owned local MCP with an empty environment."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            release_root, cbm_archive = self.extracted_rc_bundle_fixture(root)
            engram_archive = release_root / "dependencies" / "engram_1.20.0_linux_amd64.tar.gz"
            engram_script = (
                b"#!/bin/sh\n"
                b"if [ \"$#\" -eq 1 ] && [ \"$1\" = \"--version\" ]; then printf 'engram 1.20.0\\n'; "
                b"elif [ \"$#\" -eq 2 ] && [ \"$1\" = \"mcp\" ] && [ \"$2\" = \"--tools=agent\" ]; then "
                b"printf 'engram mcp started\\n'; else exit 17; fi\n"
            )
            self.write_archive(engram_archive, [
                (self.regular_member("CHANGELOG.md", 0o644), b"changelog\n"),
                (self.regular_member("LICENSE", 0o644), b"license\n"),
                (self.regular_member("README.md", 0o644), b"readme\n"),
                (self.regular_member("engram", 0o755), engram_script),
            ])
            target = self.temporary_target(root / "fresh-home")
            plan = self.engine.plan(self.engine.detect(target, "opencode"), self.engine.load_catalog(), self.engine.load_contract())
            cbm = next(item for item in plan["dependencies"] if item["id"] == "cbm")
            engram = next(item for item in plan["dependencies"] if item["id"] == "engram")
            cbm["metadata"] = self.fixture_dependency("cbm", cbm_archive)
            engram["metadata"]["integrity"] = {"sha256": hashlib.sha256(engram_archive.read_bytes()).hexdigest()}
            node = root / "provisioned-node" / "bin" / "node"
            node.parent.mkdir(parents=True)
            self.fixture_command(node, "Version 0.0.79")
            npm = root / "npm"
            self.fake_npm(npm)
            install_playwright = self.engine.install_playwright
            with patch.object(self.engine.urllib.request, "urlopen", return_value=io.BytesIO(engram_archive.read_bytes())), \
                    patch.object(self.engine.shutil, "which", return_value=str(node)), \
                    patch.object(self.engine, "install_playwright", side_effect=lambda item, destination: install_playwright(item, destination, str(npm))):
                self.engine.apply(
                    plan,
                    target,
                    {"cbm", "engram", "playwright", "context7"},
                    browser_ready=True,
                    release_root=release_root,
                    release_identity=self.rc_release_identity_fixture(release_root),
                )

            config = json.loads(target["opencode_config"].read_text(encoding="utf-8"))
            commands = {key: config["mcp"][key]["command"] for key in ("codebase-memory-mcp", "engram", "playwright")}
            self.assertNotIn("{env:", json.dumps(commands))
            self.assertEqual(commands["codebase-memory-mcp"], [str(target["dependencies"] / "cbm" / "bin" / "codebase-memory-mcp")])
            self.assertEqual(commands["engram"], [str(target["dependencies"] / "engram" / "engram"), "mcp", "--tools=agent"])
            self.assertEqual(commands["playwright"], [str(node.resolve()), str(target["dependencies"] / "playwright" / "node_modules" / "@playwright" / "mcp" / "cli.js")])
            self.assertEqual(config["mcp"]["context7"], {"type": "remote", "url": "https://mcp.context7.com/mcp", "enabled": True})
            expected_output = {
                "codebase-memory-mcp": "codebase-memory-mcp 0.9.0",
                "engram": "engram mcp started",
                "playwright": "Version 0.0.79",
            }
            for name, command in commands.items():
                with self.subTest(mcp=name):
                    result = subprocess.run(command, text=True, capture_output=True, check=False, env={})
                    self.assertEqual((result.returncode, (result.stdout + result.stderr).strip()), (0, expected_output[name]))

    def test_playwright_rejects_lifecycle_scripts_and_lock_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = json.loads(self.engine.PLAYWRIGHT_PACKAGE_PATH.read_text())
            package["scripts"] = {"install": "exit 1"}
            package_path = root / "package.json"
            package_path.write_text(json.dumps(package), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "lifecycle"):
                self.engine.validate_playwright_lockfile(self.engine.PLAYWRIGHT_LOCK_PATH, package_path)
            package.pop("scripts")
            package["dependencies"]["@playwright/mcp"] = "0.0.80"
            package_path.write_text(json.dumps(package), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "fixed dependency"):
                self.engine.validate_playwright_lockfile(self.engine.PLAYWRIGHT_LOCK_PATH, package_path)

    def test_probe_failure_after_staging_removes_final_dependency_and_temporary_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, archive = Path(temporary), Path(temporary) / "cbm.tar.gz"
            self.write_archive(archive, [(self.regular_member("bin/codebase-memory-mcp"), b"#!/bin/sh\nexit 1\n")])
            item = self.fixture_dependency("cbm", archive)
            destination = root / "cbm"
            with self.assertRaisesRegex(RuntimeError, "probe"):
                self.engine.install_dependency(item, destination, archive)
            self.assertFalse(destination.exists())
            self.assertFalse(destination.with_name(destination.name + ".partial").exists())
            self.assertFalse(destination.with_name(destination.name + ".download.partial").exists())
            engram_archive = root / "engram.tar.gz"
            self.write_archive(engram_archive, self.engram_archive_members("1.20.1", standalone_probe=True))
            engram_item = self.fixture_dependency("engram", engram_archive)
            engram_destination = root / "engram"
            with self.assertRaisesRegex(RuntimeError, "probe"):
                self.engine.install_dependency(engram_item, engram_destination, engram_archive)
            self.assertFalse(engram_destination.exists())
            self.assertFalse(engram_destination.with_name(engram_destination.name + ".partial").exists())
            self.assertFalse(engram_destination.with_name(engram_destination.name + ".download.partial").exists())

    def test_probe_failure_reports_sanitized_bounded_nonzero_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, archive = Path(temporary), Path(temporary) / "cbm.tar.gz"
            stdout = "token=do-not-leak " + "x" * (self.engine.PROBE_DIAGNOSTIC_LIMIT + 1)
            script = f"#!/bin/sh\nprintf '%s\\n' '{stdout}'\nprintf '%s\\n' 'Authorization: Bearer do-not-leak' >&2\nexit 7\n"
            self.write_archive(archive, [(self.regular_member("bin/codebase-memory-mcp"), script.encode())])
            item = self.fixture_dependency("cbm", archive)
            destination = root / "cbm"
            with self.assertRaisesRegex(RuntimeError, r"exit_code=7") as raised:
                self.engine.install_dependency(item, destination, archive)
            message = str(raised.exception)
            self.assertIn("stdout=", message)
            self.assertIn("stderr=", message)
            self.assertIn("...<truncated>", message)
            self.assertIn("token=<redacted>", message)
            self.assertIn("Authorization:<redacted>", message)
            self.assertNotIn("do-not-leak", message)
            self.assertFalse(destination.exists())

    def test_probe_failure_reports_wrong_output_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, archive = Path(temporary), Path(temporary) / "cbm.tar.gz"
            self.write_archive(archive, [
                (self.regular_member("bin/codebase-memory-mcp"), b"#!/bin/sh\nprintf 'codebase-memory-mcp unexpected\\n'\n")
            ])
            item = self.fixture_dependency("cbm", archive)
            destination = root / "cbm"
            with self.assertRaisesRegex(RuntimeError, r"exit_code=0") as raised:
                self.engine.install_dependency(item, destination, archive)
            self.assertIn("stdout='codebase-memory-mcp unexpected\\n'", str(raised.exception))
            self.assertIn("stderr=''", str(raised.exception))
            self.assertFalse(destination.exists())

    def test_release_integrity_records_are_real_and_complete(self) -> None:
        provenance = json.loads((ROOT / "manifests" / "cbm-linux-x64-provenance.json").read_text())
        self.assertEqual(provenance["commit"], "b637e3330c96cfe452da623db068c241aaa3ec01")
        self.assertEqual(provenance["tree"], "67ea1cdff279b0cfe0292640c624388ed9db6dce")
        self.assertEqual(provenance["builder_image_digest"], "debian@sha256:abd67ffcfa541b485a3dff59865ab629aa048a6c613e639d36e7456b0b229241")
        self.assertEqual(provenance["build_command_sha256"], "81104017f3f7c1a3cb83afc72a9491b5edd7486ba348dcd87db5df0ff93b2ff8")
        self.assertEqual(provenance["build_command_sha256"], hashlib.sha256(provenance["build_command"].encode("utf-8")).hexdigest())
        self.assertEqual(provenance["output_sha256"], "192eb13dbbd858e0363e4cd24b889bd7c08381d81553a6bb863772d7450938f8")
        self.assertIn("unavailable", provenance["signature_verification"])
        contract = self.engine.load_contract()
        self.assertEqual(contract["dependencies"][1]["integrity"]["sha256"], "7dc3003318e303bee269a4772144f3ce01c8ec700bfd524aaec76770acd389ca")
        self.assertEqual(contract["dependencies"][1]["archive_layout"], {"members": ["CHANGELOG.md", "LICENSE", "README.md", "engram"], "executables": {"engram": "0755"}})
        packages = json.loads((ROOT / "manifests" / "playwright-mcp-package-lock.json").read_text())["packages"]
        self.assertEqual(set(packages) - {""}, {"node_modules/@playwright/mcp", "node_modules/fsevents", "node_modules/playwright", "node_modules/playwright-core"})
        self.assertTrue(all(packages[name]["integrity"].startswith("sha512-") for name in packages if name))

    def test_tampered_playwright_lockfile_sri_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            lockfile = Path(temporary) / "package-lock.json"
            value = json.loads((ROOT / "manifests" / "playwright-mcp-package-lock.json").read_text())
            value["packages"]["node_modules/playwright"]["integrity"] = "sha512-tampered"
            lockfile.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "approved package graph"):
                self.engine.validate_playwright_lockfile(lockfile)

    def test_playwright_lockfile_rejects_missing_optional_closure_and_non_npmjs_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            lockfile = Path(temporary) / "package-lock.json"
            value = json.loads((ROOT / "manifests" / "playwright-mcp-package-lock.json").read_text())
            cases = {
                "missing-fsevents": lambda lock: lock["packages"].pop("node_modules/fsevents"),
                "missing-optional-edge": lambda lock: lock["packages"]["node_modules/playwright"].pop("optionalDependencies"),
                "non-npmjs-fsevents": lambda lock: lock["packages"]["node_modules/fsevents"].__setitem__("resolved", "https://mirror.invalid/fsevents.tgz"),
            }
            for name, mutate in cases.items():
                with self.subTest(name=name):
                    candidate = copy.deepcopy(value)
                    mutate(candidate)
                    lockfile.write_text(json.dumps(candidate), encoding="utf-8")
                    with self.assertRaisesRegex(RuntimeError, "approved package graph|fixed package graph"):
                        self.engine.validate_playwright_lockfile(lockfile)

    def test_detect_and_plan_are_read_only_and_expose_collisions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            target = self.temporary_target(home)
            config = target["opencode_config"]
            config.parent.mkdir(parents=True)
            config.write_text(json.dumps({"agent": {"pegasus-orchestrator": {"user": True}}}), encoding="utf-8")
            before = config.read_bytes()
            state = self.engine.detect(target, "opencode")
            plan = self.engine.plan(state, self.engine.load_catalog(), self.engine.load_contract())
            self.assertEqual(config.read_bytes(), before)
            collision = next(entry for entry in plan["artifacts"] if entry["id"] == "opencode-agent")
            self.assertEqual(collision["action"], "skip-collision")
            self.assertIn("id", collision)
            self.assertIn("target", collision)

    def test_unconfirmed_or_declined_dependencies_cannot_apply_or_leave_orphans(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            target = self.temporary_target(home)
            plan = self.engine.plan(self.engine.detect(target, "opencode"), self.engine.load_catalog(), self.engine.load_contract())
            with self.assertRaisesRegex(RuntimeError, "confirmation"):
                self.engine.apply(plan, target, set(), browser_ready=True)
            result = self.engine.apply(plan, target, set(), browser_ready=True, declined={"cbm", "engram", "playwright", "context7"})
            self.assertNotIn("opencode-mcp", result["created"])
            self.assertNotIn("opencode-mcp", {entry["id"] for entry in self.engine.load_journal(target)["entries"]})
            self.assertFalse(target["dependencies"].exists())

    def test_existing_mcp_is_non_owning_link(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = self.temporary_target(Path(temporary))
            target["opencode_config"].parent.mkdir(parents=True)
            executable = target["home"] / "safe-cbm"
            executable.write_text("#!/bin/sh\nprintf 'codebase-memory-mcp 0.9.0\\n'\n", encoding="utf-8")
            executable.chmod(0o755)
            target["opencode_config"].write_text(json.dumps({"mcp": {"codebase-memory-mcp": {"type": "local", "command": [str(executable)]}}}), encoding="utf-8")
            plan = self.engine.plan(self.engine.detect(target, "opencode"), self.engine.load_catalog(), self.engine.load_contract())
            link = next(item for item in plan["dependencies"] if item["id"] == "cbm")
            self.assertEqual(link["action"], "link-existing")
            self.assertFalse(link["ownership"])
            result = self.engine.apply(plan, target, set(), browser_ready=True, declined={"engram", "playwright", "context7"})
            self.assertNotIn("opencode-mcp", result["created"])
            self.assertEqual(json.loads(target["opencode_config"].read_text())["mcp"]["codebase-memory-mcp"]["command"], [str(executable)])
            self.assertNotIn("opencode-mcp", {entry["id"] for entry in self.engine.load_journal(target)["entries"]})

    def test_existing_mcp_requires_exact_shape_path_and_probe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = self.temporary_target(Path(temporary))
            target["opencode_config"].parent.mkdir(parents=True)
            executable = target["home"] / "safe-cbm"
            self.fixture_command(executable, "codebase-memory-mcp 0.9.0")
            cases = {
                "valid": {"type": "local", "command": [str(executable)]},
                "string-command": {"type": "local", "command": str(executable)},
                "extra-argv": {"type": "local", "command": [str(executable), "serve"]},
                "wrong-version": {"type": "local", "command": [str(executable)]},
            }
            wrong = target["home"] / "wrong-cbm"
            self.fixture_command(wrong, "codebase-memory-mcp 0.9.1")
            cases["wrong-version"]["command"] = [str(wrong)]
            for name, value in cases.items():
                with self.subTest(name=name):
                    target["opencode_config"].write_text(json.dumps({"mcp": {"codebase-memory-mcp": value}}), encoding="utf-8")
                    plan = self.engine.plan(self.engine.detect(target, "opencode"), self.engine.load_catalog(), self.engine.load_contract())
                    entry = next(item for item in plan["dependencies"] if item["id"] == "cbm")
                    self.assertEqual(entry["action"], "link-existing" if name == "valid" else "skip-incompatible-existing")
                    self.assertEqual(entry["resolved_path"], str(executable) if name == "valid" else None)

    def test_existing_mcp_rejects_symlink_nonzero_and_timeout_probes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = self.temporary_target(Path(temporary))
            target["opencode_config"].parent.mkdir(parents=True)
            valid = target["home"] / "valid-cbm"
            self.fixture_command(valid, "codebase-memory-mcp 0.9.0")
            symlink = target["home"] / "linked-cbm"
            symlink.symlink_to(valid)
            failing = target["home"] / "failing-cbm"
            self.fixture_command(failing, "codebase-memory-mcp 0.9.0", exit_code=1)
            waiting = target["home"] / "waiting-cbm"
            waiting.write_text("#!/bin/sh\nsleep 1\nprintf 'codebase-memory-mcp 0.9.0\\n'\n", encoding="utf-8")
            waiting.chmod(0o755)
            for name, command in {"symlink": symlink, "nonzero": failing, "timeout": waiting}.items():
                with self.subTest(name=name):
                    target["opencode_config"].write_text(json.dumps({"mcp": {"codebase-memory-mcp": {"type": "local", "command": [str(command)]}}}), encoding="utf-8")
                    original_timeout = self.engine.PROBE_TIMEOUT
                    self.engine.PROBE_TIMEOUT = 0.01 if name == "timeout" else original_timeout
                    try:
                        plan = self.engine.plan(self.engine.detect(target, "opencode"), self.engine.load_catalog(), self.engine.load_contract())
                    finally:
                        self.engine.PROBE_TIMEOUT = original_timeout
                    entry = next(item for item in plan["dependencies"] if item["id"] == "cbm")
                    self.assertEqual(entry["action"], "skip-incompatible-existing")

    def test_existing_engram_requires_its_exact_entrypoint_and_probe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = self.temporary_target(Path(temporary))
            target["opencode_config"].parent.mkdir(parents=True)
            executable = target["home"] / "engram"
            self.fixture_command(executable, "engram 1.20.0")
            for suffix, action in ((["mcp", "--tools=agent"], "link-existing"), (["mcp"], "skip-incompatible-existing")):
                with self.subTest(suffix=suffix):
                    target["opencode_config"].write_text(json.dumps({"mcp": {"engram": {"type": "local", "command": [str(executable), *suffix]}}}), encoding="utf-8")
                    plan = self.engine.plan(self.engine.detect(target, "opencode"), self.engine.load_catalog(), self.engine.load_contract())
                    entry = next(item for item in plan["dependencies"] if item["id"] == "engram")
                    self.assertEqual(entry["action"], action)

    def test_existing_playwright_requires_node_20_browser_and_exact_probe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = self.temporary_target(Path(temporary))
            target["opencode_config"].parent.mkdir(parents=True)
            node, cli = target["home"] / "node", target["home"] / "playwright" / "node_modules" / "@playwright" / "mcp" / "cli.js"
            cli.parent.mkdir(parents=True)
            cli.write_text("fixture", encoding="utf-8")
            node.write_text("#!/bin/sh\nif [ \"$1\" = \"--version\" ]; then printf 'v20.0.0\\n'; else printf 'Version 0.0.80\\n'; fi\n", encoding="utf-8")
            node.chmod(0o755)
            target["opencode_config"].write_text(json.dumps({"mcp": {"playwright": {"type": "local", "command": [str(node), str(cli)]}}}), encoding="utf-8")
            plan = self.engine.plan(self.engine.detect(target, "opencode"), self.engine.load_catalog(), self.engine.load_contract())
            entry = next(item for item in plan["dependencies"] if item["id"] == "playwright")
            self.assertEqual(entry["action"], "skip-incompatible-existing")
            node.write_text("#!/bin/sh\nif [ \"$1\" = \"--version\" ]; then printf 'v20.0.0\\n'; else printf 'Version 0.0.79\\n'; fi\n", encoding="utf-8")
            plan = self.engine.plan(self.engine.detect(target, "opencode"), self.engine.load_catalog(), self.engine.load_contract())
            entry = next(item for item in plan["dependencies"] if item["id"] == "playwright")
            self.assertEqual(entry["action"], "link-existing")
            self.assertFalse(self.engine.browser_preflight(plan, target)["ready"])
            browser = target["home"] / ".cache" / "ms-playwright" / "chromium"
            browser.parent.mkdir(parents=True)
            browser.write_text("external browser", encoding="utf-8")
            self.assertTrue(self.engine.browser_preflight(plan, target)["ready"])

    def test_incompatible_existing_mcp_is_reported_but_never_configured_or_journaled(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = self.temporary_target(Path(temporary))
            target["opencode_config"].parent.mkdir(parents=True)
            target["opencode_config"].write_text(json.dumps({"mcp": {"codebase-memory-mcp": {"type": "local", "command": "bad"}}}), encoding="utf-8")
            plan = self.engine.plan(self.engine.detect(target, "opencode"), self.engine.load_catalog(), self.engine.load_contract())
            result = self.engine.apply(plan, target, set(), browser_ready=True, declined={"engram", "playwright", "context7"})
            self.assertEqual(json.loads(target["opencode_config"].read_text())["mcp"]["codebase-memory-mcp"]["command"], "bad")
            self.assertNotIn("opencode-mcp", result["created"])
            self.assertFalse(target["dependencies"].joinpath("cbm").exists())

    def test_context7_requires_explicit_confirmation_and_decline_leaves_no_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = self.temporary_target(Path(temporary))
            plan = self.engine.plan(self.engine.detect(target, "opencode"), self.engine.load_catalog(), self.engine.load_contract())
            context7 = plan["remote_mcps"][0]
            self.assertEqual(context7["endpoint"], "https://mcp.context7.com/mcp")
            self.assertTrue(context7["provider_managed"])
            self.assertIsNone(context7["integrity"])
            plan["artifacts"] = [item for item in plan["artifacts"] if item["id"] == "opencode-mcp"]
            with self.assertRaisesRegex(RuntimeError, "confirmation"):
                self.engine.apply(plan, target, set(), browser_ready=True, declined={"cbm", "engram", "playwright"})
            result = self.engine.apply(plan, target, set(), browser_ready=True, declined={"cbm", "engram", "playwright", "context7"})
            self.assertNotIn("context7-mcp", result["created"])
            self.assertFalse(target["opencode_config"].exists())
            self.assertFalse(target["journal"].exists())
            result = self.engine.apply(plan, target, {"context7"}, browser_ready=True, declined={"cbm", "engram", "playwright"})
            self.assertIn("context7-mcp", result["created"])
            self.assertNotIn("opencode-mcp", result["created"])
            config = json.loads(target["opencode_config"].read_text())
            self.assertEqual(config["mcp"]["context7"], {"type": "remote", "url": "https://mcp.context7.com/mcp", "enabled": True})
            journal = self.engine.load_journal(target)
            self.assertNotIn("opencode-mcp", {item["id"] for item in journal["entries"]})
            entry = next(item for item in journal["entries"] if item["id"] == "context7-mcp")
            self.assertEqual(entry["kind"], "json-mcp-key")

    def test_missing_playwright_browser_blocks_without_writes_and_retry_can_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            target = self.temporary_target(home)
            plan = self.engine.plan(self.engine.detect(target, "opencode"), self.engine.load_catalog(), self.engine.load_contract())
            self.assertFalse(self.engine.browser_preflight(plan, target)["ready"])
            with self.assertRaisesRegex(RuntimeError, "browser"):
                self.engine.apply(plan, target, {"cbm", "engram", "playwright"}, browser_ready=False, declined={"context7"})
            self.assertFalse(target["journal"].exists())
            browser = home / ".cache" / "ms-playwright" / "chromium"
            browser.parent.mkdir(parents=True)
            browser.write_text("external browser", encoding="utf-8")
            self.assertTrue(self.engine.browser_preflight(plan, target)["ready"])

    def test_external_playwright_browser_preflight_requires_root_control_offline(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "target-home"
            target = self.temporary_target(home)
            plan = self.engine.plan(self.engine.detect(target, "opencode"), self.engine.load_catalog(), self.engine.load_contract())
            browser = Path(temporary) / "google-chrome"
            self.fixture_command(browser, "Chrome")
            root_mode = SimpleNamespace(st_uid=0, st_mode=0o755)
            with patch.object(self.engine, "path_stat", return_value=root_mode):
                result = self.engine.browser_preflight(plan, target, browser)
            self.assertTrue(result["ready"])
            self.assertEqual(result["browser"], str(browser))
            self.assertIn("external", result["reason"])

            self.assertFalse(self.engine.browser_preflight(plan, target, Path(temporary) / "missing-chrome")["ready"])
            linked = Path(temporary) / "linked-chrome"
            linked.symlink_to(browser)
            with patch.object(self.engine, "path_stat", return_value=root_mode):
                self.assertFalse(self.engine.browser_preflight(plan, target, linked)["ready"])

            unsafe_mode = SimpleNamespace(st_uid=0, st_mode=0o775)
            with patch.object(self.engine, "path_stat", return_value=unsafe_mode):
                self.assertFalse(self.engine.browser_preflight(plan, target, browser)["ready"])

            controlled = home / "bin" / "google-chrome"
            controlled.parent.mkdir(parents=True)
            self.fixture_command(controlled, "Chrome")
            with patch.object(self.engine, "path_stat", return_value=root_mode):
                self.assertFalse(self.engine.browser_preflight(plan, target, controlled)["ready"])

    def test_granular_apply_and_rollback_preserve_user_content(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = self.temporary_target(Path(temporary))
            target["opencode_config"].parent.mkdir(parents=True)
            target["opencode_config"].write_text(json.dumps({"user": {"keep": True}}), encoding="utf-8")
            plan = self.engine.plan(self.engine.detect(target, "opencode"), self.engine.load_catalog(), self.engine.load_contract())
            result = self.engine.apply(plan, target, set(), browser_ready=True, declined={"cbm", "engram", "playwright", "context7"})
            self.assertTrue(result["created"])
            config = json.loads(target["opencode_config"].read_text())
            self.assertEqual(config["user"], {"keep": True})
            entry = next(item for item in self.engine.load_journal(target)["entries"] if item["id"] == "opencode-agent")
            config[entry["key"]]["changed"] = True
            target["opencode_config"].write_text(json.dumps(config), encoding="utf-8")
            rollback = self.engine.rollback(target)
            self.assertIn(entry["id"], rollback["preserved"])
            self.assertIn(entry["key"], json.loads(target["opencode_config"].read_text()))

    def test_installed_opencode_file_prompts_resolve_inside_global_config_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = self.temporary_target(Path(temporary))
            plan = self.engine.plan(self.engine.detect(target, "opencode"), self.engine.load_catalog(), self.engine.load_contract())
            self.engine.apply(plan, target, set(), browser_ready=True, declined={"cbm", "engram", "playwright", "context7"})

            config = json.loads(target["opencode_config"].read_text(encoding="utf-8"))
            prompts = {
                name: agent["prompt"]
                for name, agent in config["agent"].items()
                if isinstance(agent.get("prompt"), str)
                and agent["prompt"].startswith("{file:")
                and agent["prompt"].endswith("}")
            }
            self.assertEqual(prompts["pegasus-orchestrator"], "{file:./agents/pegasus-orchestrator.md}")
            self.assertTrue(prompts)
            for name, prompt in prompts.items():
                with self.subTest(agent=name):
                    resolved = target["opencode_config"].parent / prompt.removeprefix("{file:").removesuffix("}")
                    self.assertTrue(resolved.is_file(), f"OpenCode resolves {prompt} to a missing file: {resolved}")

    def test_installed_opencode_agents_defer_model_selection_to_the_user(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = self.temporary_target(Path(temporary))
            plan = self.engine.plan(self.engine.detect(target, "opencode"), self.engine.load_catalog(), self.engine.load_contract())
            self.engine.apply(plan, target, set(), browser_ready=True, declined={"cbm", "engram", "playwright", "context7"})

            config = json.loads(target["opencode_config"].read_text(encoding="utf-8"))
            self.assertNotIn("model", config)
            self.assertTrue(config["agent"])
            for name, agent in config["agent"].items():
                with self.subTest(agent=name):
                    self.assertNotIn("model", agent)

    def test_validator_and_documentation_checks_pass(self) -> None:
        ast.parse(SCRIPT.read_text(encoding="utf-8"))
        subprocess.run([sys.executable, str(ROOT / "tools" / "validate_snapshot.py")], cwd=ROOT, check=True)
        subprocess.run([sys.executable, str(ROOT / "tools" / "check_docs_links.py")], cwd=ROOT, check=True)
        subprocess.run(["bash", "-n", str(ROOT / "install.sh")], check=True)
        subprocess.run(["bash", "-n", str(ROOT / "scripts" / "accept-v3-isolated.sh")], check=True)
        subprocess.run(["bash", "-n", str(ROOT / "scripts" / "provision-v3-rc-host.sh")], check=True)


if __name__ == "__main__":
    unittest.main()
