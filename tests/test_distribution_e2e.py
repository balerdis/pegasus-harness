"""End-to-end regression: the build recipe a distribution actually follows, locked in as a test.

This locks in what `sdd/pegasus-distributions/build-recipe-verification` already proved by hand:
extraction tolerates the prepended shebang (`zipfile.is_zipfile()` is true, all entries extract
cleanly), extract-then-rebuild-unmodified reproduces the byte-identical published SHA-256, the
rebuilt binary runs and reports its own identity (never Pegasus's), and overlaid content genuinely
resolves -- a broken `agents/king-pegasus.md` fails a real install on that exact file, while the
unmodified control build succeeds.

Uses `ACME` throughout: an obviously fictional name, never a real organization's, so nothing here
could be mistaken for endorsing or targeting one. Everything lives inside a scratch directory and
a throwaway `$HOME` -- never the real environment this suite runs under.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

import pegasus
from fakes import EXECUTABLE_MODE, FakeDownloader, FakeFileSystem
from pegasus import cli
from pegasus.adapters.opencode import render as render_module
from pegasus.core import identity as identity_module

ROOT = Path(__file__).resolve().parents[1]
BUILD_ZIPAPP = ROOT / "tools" / "build_zipapp.py"
REAL_SOURCE = ROOT / "src" / "pegasus"
REAL_IDENTITY = REAL_SOURCE / "identity.json"

#: An obviously fictional distribution -- never a real organization -- so this test cannot be
#: mistaken for targeting or endorsing one.
ACME_IDENTITY_PAYLOAD = {
    "product_id": "acme-widget",
    "display_name": "Acme",
    "program_name": "acme",
    "version": "1.0.0",
    "wordmark_words": ["ACME"],
    "release": {
        "asset_url_template": "https://example.invalid/acme/releases/download/{tag}/{asset}",
        "binary_asset": "acme",
        "latest_release_api_url": "https://example.invalid/acme/api/releases/latest",
        "release_page_url": "https://example.invalid/acme/releases",
        "install_base_url_default": "https://example.invalid/acme/releases/latest/download",
    },
}


def _build(source: Path, out: Path, identity: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(BUILD_ZIPAPP), "--source", str(source), "--identity", str(identity), "--out", str(out)],
        capture_output=True, text=True,
    )


class DistributionBuildRecipeTest(unittest.TestCase):
    """Not instant -- it builds the real package three times and runs the resulting binaries a
    handful of times, each a real subprocess with real Python startup. Timed at well under 5
    seconds total during development, comfortably inside the default suite's per-test budget, so
    it is not gated behind an environment variable: gating it would have meant either a second,
    shallower version of this test staying in the default run (defeating the point of locking in
    the real recipe) or silently dropping this coverage from CI-equivalent runs entirely.
    """

    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.root = Path(self._directory.name)
        self.home = self.root / "home"
        self.home.mkdir()

    def _run_binary(self, binary: Path, *args: str, home: Path | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            [str(binary), *args],
            env={"HOME": str(home if home is not None else self.home), "PATH": "/usr/bin:/bin"},
            capture_output=True, text=True, timeout=30,
        )

    def test_extract_rebuild_and_overlay_recipe(self):
        # 1. Control build: Pegasus's own identity, from the real pinned source -- stands in for
        # a published release artifact.
        control = self.root / "control" / "pegasus"
        result = _build(REAL_SOURCE, control, REAL_IDENTITY)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        control_sha256 = hashlib.sha256(control.read_bytes()).hexdigest()

        # 2. Extraction tolerates the prepended shebang: `zipfile` reads it as a real zip despite
        # the shebang bytes ahead of the local-file-header signature.
        extracted = self.root / "extracted"
        self.assertTrue(zipfile.is_zipfile(control))
        with zipfile.ZipFile(control) as archive:
            archive.extractall(extracted)
        extracted_package = extracted / "pegasus"
        self.assertTrue((extracted_package / "__main__.py").is_file())
        self.assertTrue((extracted_package / "identity.json").is_file())

        # 3. Extract-then-rebuild-unmodified reproduces the exact published SHA-256: `_normalize`
        # pins mtime/mode after staging, so the noise extraction introduces is erased by
        # construction.
        rebuilt = self.root / "rebuilt" / "pegasus"
        result = _build(extracted_package, rebuilt, extracted_package / "identity.json")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        rebuilt_sha256 = hashlib.sha256(rebuilt.read_bytes()).hexdigest()
        self.assertEqual(
            rebuilt_sha256, control_sha256,
            "extract-then-rebuild-unmodified must reproduce the exact published SHA-256",
        )

        # 4. Build ACME (an obviously fictional distribution, never a real organization's) from
        # the still-unmodified extracted package, before overlaying any content difference --
        # this build proves the identity facets on their own, uncomplicated by the overlay.
        acme_identity = self.root / "acme-identity.json"
        acme_identity.write_text(json.dumps(ACME_IDENTITY_PAYLOAD), encoding="utf-8")

        acme = self.root / "acme" / "ACME"
        result = _build(extracted_package, acme, acme_identity)
        self.assertEqual(result.returncode, 0, msg=result.stderr)

        # 5. The rebuilt binary runs. `schema` is deliberately an identical wire identifier across
        # every distribution (see the spec's wire-format requirement). `pegasus_version` is
        # different: only the KEY is a stable wire identifier -- an existing journal's dataclass
        # field, never renamed -- while the VALUE it reports is each distribution's own version,
        # never the pinned engine's (see `DistributionVersionIdentityTest`, below). What must
        # differ here too is the displayed name, data directory and release source.
        acme_home = self.root / "acme-home"
        acme_home.mkdir()
        # A CLI adapter's own config directory has to look "detected", or `install` (not
        # `--dry-run`) refuses outright -- this stands in for an OpenCode install already there.
        (acme_home / ".config" / "opencode").mkdir(parents=True)
        result = self._run_binary(acme, "doctor", "--json", home=acme_home)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["schema"], "pegasus/cli-report/v1")

        # 6. `--version` prints the program name and version identity supplies, never a
        # hardcoded literal -- proving the displayed name is genuinely ACME's own.
        result = self._run_binary(acme, "--version", home=acme_home)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("acme", result.stdout.lower())
        self.assertNotIn("pegasus", result.stdout.lower())

        # 7. A real (non-dry-run) install creates its own data directory, keyed by its own
        # `product_id` -- never Pegasus's.
        result = self._run_binary(acme, "install", "--cli", "opencode", home=acme_home)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertTrue((acme_home / ".local" / "share" / "acme-widget").exists())
        self.assertFalse((acme_home / ".local" / "share" / "pegasus-harness").exists())

        # 8. Overlay a genuine content difference that breaks an existing file's frontmatter --
        # exactly the overlay the verified recipe used -- and rebuild ACME from it.
        king_pegasus = extracted_package / "content" / "agents" / "king-pegasus.md"
        original_king_pegasus = king_pegasus.read_text(encoding="utf-8")
        king_pegasus.write_text(
            "overlay marker breaking frontmatter\n" + original_king_pegasus, encoding="utf-8"
        )
        acme_overlaid = self.root / "acme-overlaid" / "ACME"
        result = _build(extracted_package, acme_overlaid, acme_identity)
        self.assertEqual(result.returncode, 0, msg=result.stderr)

        # 9. The overlaid content genuinely resolves: the broken `king-pegasus.md` fails this
        # exact install, naming that exact file -- while the unmodified control build succeeds
        # on the same command.
        overlaid_home = self.root / "acme-overlaid-home"
        (overlaid_home / ".config" / "opencode").mkdir(parents=True)
        result = self._run_binary(
            acme_overlaid, "install", "--cli", "opencode", "--dry-run", home=overlaid_home
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("king-pegasus.md", result.stdout + result.stderr)

        control_home = self.root / "control-home"
        (control_home / ".config" / "opencode").mkdir(parents=True)
        control_result = self._run_binary(
            control, "install", "--cli", "opencode", "--dry-run", home=control_home
        )
        self.assertEqual(control_result.returncode, 0, msg=control_result.stderr)


class DistributionVersionIdentityTest(unittest.TestCase):
    """Regression for the defect a real distribution hit: a real distribution
    (pinning this engine at one version, releasing its own product under a
    completely different tag) found `--version` printing the pinned engine's
    own baked-in version instead of its own, and `upgrade` unable to ever
    reach `already-current` against its own releases because the comparison
    was against the engine's version, not the product's own.

    Mirrors that scenario with ACME (the same fictional distribution
    `DistributionBuildRecipeTest` already builds): the engine here is
    whatever `pegasus.__version__` currently is, ACME's own identity
    declares a deliberately different version, and both halves of the bug
    are proven fixed -- `--version` on the actual built binary, and
    `upgrade` reaching `already-current` through the actual `cli.upgrade`
    code path the real bug lived in.
    """

    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.root = Path(self._directory.name)
        self.assertNotEqual(
            ACME_IDENTITY_PAYLOAD["version"], pegasus.__version__,
            "fixture drifted: ACME's own version must differ from the pinned engine's to mean anything",
        )

    def test_the_built_binary_reports_its_own_version_not_the_engines(self):
        acme_identity = self.root / "acme-identity.json"
        acme_identity.write_text(json.dumps(ACME_IDENTITY_PAYLOAD), encoding="utf-8")
        acme = self.root / "acme" / "ACME"
        result = _build(REAL_SOURCE, acme, acme_identity)
        self.assertEqual(result.returncode, 0, msg=result.stderr)

        home = self.root / "home"
        home.mkdir()
        result = subprocess.run(
            [str(acme), "--version"],
            env={"HOME": str(home), "PATH": "/usr/bin:/bin"},
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn(ACME_IDENTITY_PAYLOAD["version"], result.stdout)
        self.assertNotIn(pegasus.__version__, result.stdout)

    def test_upgrade_reports_already_current_against_the_products_own_release(self):
        """Drives the real `cli.upgrade` -- the exact function the real bug
        lived in -- with ACME's own identity and a faked release source
        offering exactly ACME's own version. A subprocess cannot have its
        network faked, so this exercises the same production code in
        process instead, the way `test_cli_upgrade.py` already does for
        every other `upgrade` scenario."""
        acme_identity = identity_module.parse(json.dumps(ACME_IDENTITY_PAYLOAD).encode("utf-8"))

        destination = self.root / "acme-binary"
        with zipfile.ZipFile(destination, "w") as archive:
            archive.writestr("__main__.py", "pass\n")
        filesystem = FakeFileSystem(files={destination: b"old acme bytes"}, modes={destination: EXECUTABLE_MODE})
        release = acme_identity.release
        downloader = FakeDownloader(
            {release.latest_release_api_url: json.dumps({"tag_name": f"v{acme_identity.version}"}).encode("utf-8")}
        )
        runtime = cli.Runtime(
            filesystem=filesystem,
            home=self.root / "acme-home",
            now="2026-09-07T00:00:00+00:00",
            out=io.StringIO(),
            variables={},
            downloader=downloader,
            sys_path0=str(destination),
            identity=acme_identity,
        )

        report = cli.upgrade(runtime)

        self.assertEqual(report["status"], "already-current")
        self.assertEqual(report["version"], acme_identity.version)


_AGENT_FRONTMATTER_FIELD = re.compile(r'^agent:\s*"([^"]+)"\s*$', re.MULTILINE)


class DistributionOrchestratorRenameTest(unittest.TestCase):
    """Regression test for the bug this locks in: `AGENT_FOR_ROLE` used to
    hardcode `"pegasus-orchestrator"` as the `agent:` field for every command
    with `runs_as: orchestrator`, independently of `SESSION_STARTS_IN` --
    content's own declared name for the agent a session starts in. A
    distribution that renamed its orchestrator in content still got that
    literal written into every rendered command, naming an agent absent from
    its own installed agent set.

    Uses `ACME` throughout -- an obviously fictional distribution, never a
    real organization's. Everything lives inside a scratch directory and a
    throwaway `$HOME`, following `DistributionBuildRecipeTest`'s own pattern.
    """

    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.root = Path(self._directory.name)

    def _run_binary(self, binary: Path, *args: str, home: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            [str(binary), *args],
            env={"HOME": str(home), "PATH": "/usr/bin:/bin"},
            capture_output=True, text=True, timeout=30,
        )

    def test_no_installed_command_names_an_agent_absent_from_the_installed_set(self):
        # 1. A private copy of the real source, renaming its orchestrator in
        # content only -- never a change to any engine module.
        renamed_source = self.root / "renamed-source" / "pegasus"
        shutil.copytree(REAL_SOURCE, renamed_source)
        session_start = renamed_source / "content" / "session-start.txt"
        self.assertEqual(session_start.read_text(encoding="utf-8").strip(), "pegasus-orchestrator")
        session_start.write_text("acme-orchestrator\n", encoding="utf-8")

        orchestrator_agent = renamed_source / "content" / "agents" / "pegasus-orchestrator.md"
        original = orchestrator_agent.read_text(encoding="utf-8")
        self.assertIn("name: pegasus-orchestrator\n", original)
        renamed_agent = renamed_source / "content" / "agents" / "acme-orchestrator.md"
        orchestrator_agent.unlink()
        renamed_agent.write_text(
            original.replace("name: pegasus-orchestrator\n", "name: acme-orchestrator\n", 1), encoding="utf-8"
        )

        # An agent-specific MCP override section is keyed by agent name in its
        # own filename (`<id>@<agent>.md`) -- it has to move with the rename
        # too, or the loader rejects it as an override for an agent that no
        # longer ships.
        override = renamed_source / "content" / "agents" / "mcp" / "cbm@pegasus-orchestrator.md"
        override.rename(renamed_source / "content" / "agents" / "mcp" / "cbm@acme-orchestrator.md")

        # 2. Build ACME from that renamed source.
        acme_identity = self.root / "acme-identity.json"
        acme_identity.write_text(json.dumps(ACME_IDENTITY_PAYLOAD), encoding="utf-8")
        acme = self.root / "acme" / "ACME"
        result = _build(renamed_source, acme, acme_identity)
        self.assertEqual(result.returncode, 0, msg=result.stderr)

        # 3. Install it for real.
        home = self.root / "home"
        (home / ".config" / "opencode").mkdir(parents=True)
        result = self._run_binary(acme, "install", "--cli", "opencode", home=home)
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)

        settings = json.loads((home / ".config" / "opencode" / "opencode.json").read_text(encoding="utf-8"))
        installed_agents = set(settings.get("agent", {}))
        self.assertIn("acme-orchestrator", installed_agents)
        self.assertNotIn("pegasus-orchestrator", installed_agents)

        # 4. The assertion that would have caught the original bug: no
        # rendered command's `agent:` field may name an agent absent from the
        # installed agent set -- except OpenCode's own native agents, which
        # the runtime provides regardless of what this install placed (`plan`
        # and `build`; read off `AGENT_FOR_ROLE` itself so this stays in step
        # with whatever this adapter maps `RunsAs.PLANNER`/`RunsAs.BUILDER` to).
        native_agents = {value for value in render_module.AGENT_FOR_ROLE.values() if value}
        commands_dir = home / ".config" / "opencode" / "commands"
        command_files = sorted(commands_dir.glob("*.md"))
        self.assertTrue(command_files, "fixture drifted: no commands were installed")
        checked_any = False
        for command_file in command_files:
            match = _AGENT_FRONTMATTER_FIELD.search(command_file.read_text(encoding="utf-8"))
            if match is None:
                continue
            checked_any = True
            agent_name = match.group(1)
            if agent_name in native_agents:
                continue
            self.assertIn(
                agent_name,
                installed_agents,
                f"{command_file.name}: agent {agent_name!r} is not among the installed "
                f"agents {sorted(installed_agents)}",
            )
        self.assertTrue(checked_any, "fixture drifted: no installed command declares an agent field")

        # 5. A command that runs as the orchestrator names ACME's own agent in
        # its rendered `agent:` field -- never Pegasus's. (The command body's
        # own prose still says "pegasus-orchestrator" here: that is
        # content-authoring debt in the shipped command bodies, orthogonal to
        # this bug, which is only about the rendered frontmatter field.)
        sdd_apply = (commands_dir / "sdd-apply.md").read_text(encoding="utf-8")
        match = _AGENT_FRONTMATTER_FIELD.search(sdd_apply)
        self.assertIsNotNone(match, "sdd-apply.md has no agent: frontmatter field")
        self.assertEqual(match.group(1), "acme-orchestrator")


if __name__ == "__main__":
    unittest.main()
