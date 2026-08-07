from __future__ import annotations

import ast
import copy
import hashlib
import io
import importlib.machinery
import importlib.util
import json
import os
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

    def playwright_acceptance_evidence(self, matrix) -> dict:
        return {
            "version": "0.0.79",
            "registry": "https://registry.npmjs.org/",
            "install": {"argv": ["npm", "ci", "--ignore-scripts"], "result": "PASS"},
            "packages": matrix.PLAYWRIGHT_PACKAGES,
            "direct_entrypoint": {
                "argv": ["/opt/node/bin/node", "/home/fixture/.local/share/pegasus-harness/dependencies/playwright/@playwright/mcp/cli.js", "--version"],
                "stdout": "@playwright/mcp 0.0.79",
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
            "    cli.write_text(f\"if (process.argv.includes('--version')) console.log('@playwright/mcp {version}');\\n\")\n",
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
        for required in ("--profile", "--rc-archive", "--rc-checksum", "--release-manifest", "--staging-dir", "--evidence-file", "--confirm-recreate-user", "--browser", "browser_args", "--release-identity", "release_identity", "acceptance_v3_contract.py", "provision-v3-rc-host.sh", "serg", "declined_no_orphans", "pegasus-harness-journal/v3", "mapped user", '"rc"', "archive_name", "checksum_sha256", "manifest_sha256", "archive_root", "playwright_graph", "https://registry.npmjs.org/", '"npm", "ci", "--ignore-scripts"', "direct_entrypoint", "os.link"):
            self.assertIn(required, source)
        self.assertIn('"$provisioner" --profile "$profile" --rc-archive "$archive" --confirm-recreate-user "$recreate_user"', source)
        provisioner = (ROOT / "scripts/provision-v3-rc-host.sh").read_text(encoding="utf-8")
        self.assertIn("--browser", provisioner)
        for forbidden in ("useradd", "userdel", "rm -rf", "--confirm-clean-home"):
            self.assertNotIn(forbidden, source)
        self.assertIn("Automated tests may inspect this file but must never run it", source)

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

    def test_root_wrapper_delegates_all_target_writes_to_target_user(self) -> None:
        wrapper = (ROOT / "install.sh").read_text(encoding="utf-8")
        self.assertIn('sudo -n -u "$target_user" -H env "HOME=$target_home"', wrapper)
        self.assertIn('--home "$target_home"', wrapper)
        self.assertNotIn('"$python" "$script_dir/bin/pegasus" --target-user "$target_user" --client "$client" plan', wrapper)

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
            output = matrix.aggregate(archive, checksum, manifest, evidence_dir)
            aggregate = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(aggregate["status"], "PASS")
            self.assertEqual(aggregate["profiles"], sorted(matrix.PROFILES))
            self.assertEqual(set(aggregate["playwright_graph"]), matrix.PLAYWRIGHT_PROFILES)

    def test_acceptance_matrix_requires_exact_playwright_graph_and_leaves_no_aggregate_on_failure(self) -> None:
        matrix = load_acceptance_matrix()
        identity = {"tag": "v3.1.0-rc.1"}
        with tempfile.TemporaryDirectory(dir="/var/tmp") as temporary:
            evidence_dir = Path(temporary)
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
                (lambda graph: graph["direct_entrypoint"].__setitem__("stdout", "@playwright/mcp 0.0.80"), "entrypoint"),
            ):
                with self.subTest(error=error):
                    invalid = copy.deepcopy(records)
                    playwright_record = next(record for record in invalid if record["profile"] in matrix.PLAYWRIGHT_PROFILES)
                    mutation(playwright_record["playwright_graph"])
                    with self.assertRaisesRegex(ValueError, error):
                        matrix.verify_records(invalid, identity)
            missing_graph = copy.deepcopy(records)
            del next(record for record in missing_graph if record["profile"] == "playwright")["playwright_graph"]
            with patch.object(matrix, "expected_identity", return_value=identity), \
                    patch.object(matrix, "read_evidence", return_value=missing_graph), \
                    self.assertRaisesRegex(ValueError, "missing"):
                matrix.aggregate(Path("/rc-archive"), Path("/rc-checksum"), Path("/rc-manifest"), evidence_dir)
            self.assertFalse((evidence_dir / matrix.AGGREGATE_NAME).exists())
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

    def test_release_gate_and_spanish_docs_require_rc_evidence_before_final_tag(self) -> None:
        workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
        docs = (ROOT / "docs/release-distribution.md").read_text(encoding="utf-8") + (ROOT / "docs/instalacion-aditiva-v3.md").read_text(encoding="utf-8")
        for required in ("v3.1.0-rc", "validate_snapshot.py", "rc-acceptance-evidence.json", "immutable v3.1.0"):
            self.assertIn(required, workflow)
        for required in ("v3.1.0-rc.N", "evidencia", "v3.1.0", "nunca mutar"):
            self.assertIn(required, docs)

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
            self.assertEqual((destination / "@playwright/mcp/cli.js").is_file(), True)
            self.assertFalse(any(destination.parent.glob(".playwright-npm-*")))
            self.assertEqual((destination.parent / "npm-argv.txt").read_text(), "ci --ignore-scripts")
            source = SCRIPT.read_text(encoding="utf-8")
            self.assertIn('"NPM_CONFIG_REGISTRY": "https://registry.npmjs.org/"', source)
            self.assertIn('"NPM_CONFIG_USERCONFIG": str(user_config)', source)
            self.assertIn('"NPM_CONFIG_GLOBALCONFIG": str(global_config)', source)
            self.assertIn('"NPM_CONFIG_IGNORE_SCRIPTS": "true"', source)

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
        self.assertEqual(set(packages) - {""}, {"node_modules/@playwright/mcp", "node_modules/playwright", "node_modules/playwright-core"})
        self.assertTrue(all(packages[name]["integrity"].startswith("sha512-") for name in packages if name))

    def test_tampered_playwright_lockfile_sri_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            lockfile = Path(temporary) / "package-lock.json"
            value = json.loads((ROOT / "manifests" / "playwright-mcp-package-lock.json").read_text())
            value["packages"]["node_modules/playwright"]["integrity"] = "sha512-tampered"
            lockfile.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "approved package graph"):
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
            result = self.engine.apply(plan, target, set(), browser_ready=True, declined={"cbm", "engram", "playwright"})
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
            result = self.engine.apply(plan, target, set(), browser_ready=True, declined={"engram", "playwright"})
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
            node, cli = target["home"] / "node", target["home"] / "node_modules" / "@playwright" / "mcp" / "cli.js"
            cli.parent.mkdir(parents=True)
            cli.write_text("fixture", encoding="utf-8")
            node.write_text("#!/bin/sh\nif [ \"$1\" = \"--version\" ]; then printf 'v20.0.0\\n'; else printf '@playwright/mcp 0.0.80\\n'; fi\n", encoding="utf-8")
            node.chmod(0o755)
            target["opencode_config"].write_text(json.dumps({"mcp": {"playwright": {"type": "local", "command": [str(node), str(cli)]}}}), encoding="utf-8")
            plan = self.engine.plan(self.engine.detect(target, "opencode"), self.engine.load_catalog(), self.engine.load_contract())
            entry = next(item for item in plan["dependencies"] if item["id"] == "playwright")
            self.assertEqual(entry["action"], "skip-incompatible-existing")
            node.write_text("#!/bin/sh\nif [ \"$1\" = \"--version\" ]; then printf 'v20.0.0\\n'; else printf '@playwright/mcp 0.0.79\\n'; fi\n", encoding="utf-8")
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
            result = self.engine.apply(plan, target, set(), browser_ready=True, declined={"engram", "playwright"})
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
            plan["artifacts"] = []
            result = self.engine.apply(plan, target, set(), browser_ready=True, declined={"cbm", "engram", "playwright", "context7"})
            self.assertNotIn("context7-mcp", result["created"])
            self.assertFalse(target["opencode_config"].exists())
            self.assertFalse(target["journal"].exists())
            result = self.engine.apply(plan, target, {"context7"}, browser_ready=True, declined={"cbm", "engram", "playwright"})
            self.assertIn("context7-mcp", result["created"])
            config = json.loads(target["opencode_config"].read_text())
            self.assertEqual(config["mcp"]["context7"], {"type": "remote", "url": "https://mcp.context7.com/mcp", "enabled": True})
            entry = next(item for item in self.engine.load_journal(target)["entries"] if item["id"] == "context7-mcp")
            self.assertEqual(entry["kind"], "json-mcp-key")

    def test_missing_playwright_browser_blocks_without_writes_and_retry_can_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            target = self.temporary_target(home)
            plan = self.engine.plan(self.engine.detect(target, "opencode"), self.engine.load_catalog(), self.engine.load_contract())
            self.assertFalse(self.engine.browser_preflight(plan, target)["ready"])
            with self.assertRaisesRegex(RuntimeError, "browser"):
                self.engine.apply(plan, target, {"cbm", "engram", "playwright"}, browser_ready=False)
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
            result = self.engine.apply(plan, target, set(), browser_ready=True, declined={"cbm", "engram", "playwright"})
            self.assertTrue(result["created"])
            config = json.loads(target["opencode_config"].read_text())
            self.assertEqual(config["user"], {"keep": True})
            entry = next(item for item in self.engine.load_journal(target)["entries"] if item["id"] == "opencode-agent")
            config[entry["key"]]["changed"] = True
            target["opencode_config"].write_text(json.dumps(config), encoding="utf-8")
            rollback = self.engine.rollback(target)
            self.assertIn(entry["id"], rollback["preserved"])
            self.assertIn(entry["key"], json.loads(target["opencode_config"].read_text()))

    def test_validator_and_documentation_checks_pass(self) -> None:
        ast.parse(SCRIPT.read_text(encoding="utf-8"))
        subprocess.run([sys.executable, str(ROOT / "tools" / "validate_snapshot.py")], cwd=ROOT, check=True)
        subprocess.run([sys.executable, str(ROOT / "tools" / "check_docs_links.py")], cwd=ROOT, check=True)
        subprocess.run(["bash", "-n", str(ROOT / "install.sh")], check=True)
        subprocess.run(["bash", "-n", str(ROOT / "scripts" / "accept-v3-isolated.sh")], check=True)
        subprocess.run(["bash", "-n", str(ROOT / "scripts" / "provision-v3-rc-host.sh")], check=True)


if __name__ == "__main__":
    unittest.main()
