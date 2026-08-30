"""Installing and retiring an `npm`-distributed MCP server, end to end.

Proving the mechanism does not depend on the network reaching npmjs.org any
more than `test_cli_downloads.py`'s equivalent depends on a real release
host: `FakeNpmInstaller` stands in for the real `npm ci`. The form is proven
with a descriptor built by the test itself, patched in for `content.load()`,
against the real POSIX filesystem and a throwaway home -- the same
discipline `test_cli_downloads.py` already holds `download` to.
"""
from __future__ import annotations

import io
import json
import stat
import tempfile
import unittest
from pathlib import Path, PurePosixPath
from unittest.mock import patch

from fakes import FakeNpmInstaller
from pegasus import cli
from pegasus.adapters import available
from pegasus.core import journal as journal_module
from pegasus.core.content import Content, Distribution, Mcp
from pegasus.core.types import Environment
from real_home import RealHomeTestCase as _RealHomeTestCase

AT = "2026-08-14T00:00:00+00:00"
CLI = available().ids()[0]
INTEGRITY = "sha512-" + "a" * 86 + "=="

#: The real lockfile this server ships beside its descriptor, read into
#: memory by the loader in production; this test builds a `Mcp` directly, so
#: it supplies the same bytes the loader would have read.
PROBE_LOCKFILE = json.dumps(
    {
        "name": "pegasus-probe",
        "lockfileVersion": 3,
        "requires": True,
        "packages": {
            "": {"name": "pegasus-probe", "dependencies": {"probe-mcp": "1.2.3"}},
            "node_modules/probe-mcp": {
                "version": "1.2.3",
                "resolved": "https://registry.npmjs.org/probe-mcp/-/probe-mcp-1.2.3.tgz",
                "integrity": INTEGRITY,
            },
        },
    }
).encode("utf-8")

PROBE = Mcp(
    name="probe",
    description="An npm-distributed probe server",
    body="Convention body.",
    distribution=Distribution.NPM,
    endpoint="https://registry.npmjs.org/probe-mcp/-/probe-mcp-1.2.3.tgz",
    source=PurePosixPath("mcp/probe.md"),
    version="1.2.3",
    package="probe-mcp",
    integrity=INTEGRITY,
    entry="cli.js",
    npm_lockfile=PROBE_LOCKFILE,
    npm_package_name="pegasus-probe",
)
PROBE_CONTENT = Content(mcp=(PROBE,))


class RealHomeTestCase(_RealHomeTestCase):
    def setUp(self):
        super().setUp()
        # A real, executable stub `shutil.which` can find on a real PATH.
        self.node_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.node_dir.cleanup)
        node = Path(self.node_dir.name) / "node"
        node.write_text("")
        node.chmod(node.stat().st_mode | stat.S_IEXEC)

    def path_with_node(self) -> str:
        return self.node_dir.name

    def runtime(self, npm_installer=None, *, node_on_path=True) -> cli.Runtime:
        return cli.Runtime(
            filesystem=self.filesystem,
            home=self.home,
            now=AT,
            out=io.StringIO(),
            variables={"PATH": self.path_with_node() if node_on_path else ""},
            npm_installer=npm_installer or FakeNpmInstaller(),
        )

    def environment(self) -> Environment:
        return Environment(home=self.home, data_dir=self.filesystem.data_dir(self.home))

    def layout(self):
        return available().get(CLI).layout(self.environment())

    def present(self) -> None:
        self.layout().config_dir.mkdir(parents=True, exist_ok=True)

    def run_cli(self, *argv, npm_installer=None, node_on_path=True) -> tuple[int, dict]:
        context = self.runtime(npm_installer, node_on_path=node_on_path)
        code = cli.main([*argv, "--json"], runtime=context)
        return code, json.loads(context.out.getvalue())

    def installed_entries(self):
        store = cli.journal_store(self.runtime())
        install = journal_module.install_for(store.load(), CLI)
        return install.entries if install is not None else ()

    def target(self):
        return self.layout().dependencies_dir / "probe" / "1.2.3"


@patch("pegasus.core.content.load", return_value=PROBE_CONTENT)
class InstallNpmTest(RealHomeTestCase):
    def test_naming_the_server_writes_a_lockfile_and_runs_npm_ci(self, _load):
        self.present()
        installer = FakeNpmInstaller()
        code, _ = self.run_cli("install", "--cli", CLI, "--mcp", "probe", npm_installer=installer)
        self.assertEqual(code, cli.OK)
        self.assertEqual(installer.calls, [self.target()])
        self.assertTrue((self.target() / "package.json").exists())
        self.assertTrue((self.target() / "package-lock.json").exists())
        manifest = json.loads((self.target() / "package.json").read_text())
        self.assertEqual(manifest["name"], "pegasus-probe")
        self.assertEqual(
            (self.target() / "package-lock.json").read_bytes(), PROBE_LOCKFILE
        )

    def test_the_journal_records_a_dependency_tree_identified_by_the_integrity(self, _load):
        self.present()
        self.run_cli("install", "--cli", CLI, "--mcp", "probe")
        entry = next(e for e in self.installed_entries() if e.kind == "dependency-tree")
        self.assertEqual(entry.id, "dependency:probe")
        self.assertEqual(entry.after_digest, INTEGRITY)
        self.assertEqual(entry.target, self.target())

    def test_not_naming_the_server_never_installs_it(self, _load):
        self.present()
        installer = FakeNpmInstaller()
        self.run_cli("install", "--cli", CLI, npm_installer=installer)
        self.assertEqual(installer.calls, [])
        self.assertFalse(self.target().exists())

    def test_a_missing_node_fails_the_install_before_anything_is_written(self, _load):
        self.present()
        installer = FakeNpmInstaller()
        code, report = self.run_cli(
            "install", "--cli", CLI, "--mcp", "probe", npm_installer=installer, node_on_path=False
        )
        self.assertEqual(code, cli.FAILED)
        self.assertIn("node", report["error"].lower())
        self.assertEqual(installer.calls, [])
        self.assertFalse(self.target().exists())
        self.assertFalse(any(e.kind == "dependency-tree" for e in self.installed_entries()))

    def test_a_failed_npm_ci_leaves_the_directory_as_it_found_it_and_records_nothing(self, _load):
        self.present()
        installer = FakeNpmInstaller(failures={self.target(): "registry unreachable"})
        code, report = self.run_cli("install", "--cli", CLI, "--mcp", "probe", npm_installer=installer)
        self.assertEqual(code, cli.FAILED)
        self.assertIn("registry unreachable", report["error"])
        self.assertFalse(self.target().exists())
        self.assertFalse(self.target().parent.exists())
        self.assertFalse(any(e.kind == "dependency-tree" for e in self.installed_entries()))

    def test_reinstalling_the_same_version_does_not_reinvoke_npm(self, _load):
        self.present()
        installer = FakeNpmInstaller()
        self.run_cli("install", "--cli", CLI, "--mcp", "probe", npm_installer=installer)
        self.run_cli("install", "--cli", CLI, "--mcp", "probe", npm_installer=installer)
        self.assertEqual(installer.calls, [self.target()])


@patch("pegasus.core.content.load", return_value=PROBE_CONTENT)
class UninstallNpmTest(RealHomeTestCase):
    def test_uninstalling_removes_the_whole_materialized_tree(self, _load):
        self.present()
        self.run_cli("install", "--cli", CLI, "--mcp", "probe")
        self.assertTrue((self.target() / "package.json").exists())
        code, report = self.run_cli("uninstall", "--cli", CLI)
        self.assertEqual(code, cli.OK)
        self.assertFalse(self.target().exists())
        self.assertIn("dependency:probe", report["removed"])

    def test_uninstalling_leaves_no_journal_entry_behind(self, _load):
        self.present()
        self.run_cli("install", "--cli", CLI, "--mcp", "probe")
        self.run_cli("uninstall", "--cli", CLI)
        journal = cli.journal_store(self.runtime()).load()
        self.assertIsNone(journal_module.install_for(journal, CLI))

    def test_dropping_the_flag_on_reinstall_retires_it_without_uninstalling(self, _load):
        # `--mcp` still decides what installs: not naming it on a later run
        # retires just this server, and the rest of the installation stays.
        self.present()
        self.run_cli("install", "--cli", CLI, "--mcp", "probe")
        code, report = self.run_cli("install", "--cli", CLI)
        self.assertEqual(code, cli.OK)
        self.assertFalse(self.target().exists())
        self.assertIn("dependency:probe", [item["id"] for item in report["retired"]])
        self.assertNotIn("dependency:probe", [e.id for e in self.installed_entries()])
        self.assertTrue(self.layout().config_dir.is_dir())


if __name__ == "__main__":
    unittest.main()
