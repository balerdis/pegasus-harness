"""Unit coverage for the CLI-agnostic half of credential transport
(`pegasus.core.credential_transport`): the port helper that reads an
adapter's own declared capability, and each adapter's own wiring of it into
`own_artifacts`.

Two adapters are registered in this release (`ADAPTERS` in
`src/pegasus/adapters/__init__.py`): OpenCode and Claude Code (supported
since 6.0.0). Both are real here. OpenCode declares every operation; Claude
Code is registered but implements no `credential_transport()` method at all,
so `capability_of` resolves it to every operation `False` by the same
duck-typed default rule `CredentialTransportCapability`'s own docstring
describes -- proven below against the real `claudecode.Adapter`, including a
real install into a throwaway home, not a monkeypatched stand-in.
"""
from __future__ import annotations

import io
import json
import unittest
from pathlib import Path

from pegasus import cli
from pegasus.adapters import available
from pegasus.core import credential_transport
from pegasus.core.types import CredentialTransportCapability, Environment, FileArtifact
from real_home import RealHomeTestCase

ROOT = Path(__file__).resolve().parents[1]


class _NoCredentialTransport:
    """A minimal stand-in for an adapter that never implements
    `credential_transport()` at all -- the shape a future Claude Code
    adapter would have before that work is ever done."""


class _FullCredentialTransport:
    def credential_transport(self) -> CredentialTransportCapability:
        return CredentialTransportCapability(True, True, True, True)


class _WrongReturnType:
    def credential_transport(self):
        return {"detect_and_replace": True}


class CapabilityOfTest(unittest.TestCase):
    def test_an_adapter_with_no_method_gets_every_operation_false(self):
        capability = credential_transport.capability_of(_NoCredentialTransport())
        self.assertEqual(capability, CredentialTransportCapability())
        self.assertFalse(capability.any)

    def test_the_real_claude_code_adapter_resolves_to_every_operation_false(self):
        """Claude Code is a real, registered adapter (`ADAPTERS` in
        `pegasus.adapters`) -- it simply implements no `credential_transport()`
        method, so it resolves through the exact same duck-typed default as
        `_NoCredentialTransport` above, not a special case."""
        from pegasus.adapters.claudecode.adapter import Adapter as ClaudeCodeAdapter

        capability = credential_transport.capability_of(ClaudeCodeAdapter())
        self.assertEqual(capability, CredentialTransportCapability())
        self.assertFalse(capability.any)

    def test_an_adapter_that_declares_everything_gets_it_back(self):
        capability = credential_transport.capability_of(_FullCredentialTransport())
        self.assertTrue(capability.any)
        self.assertTrue(capability.detect_and_replace)
        self.assertTrue(capability.inject_at_execution)
        self.assertTrue(capability.redact_on_output)
        self.assertTrue(capability.redact_before_memory)

    def test_a_malformed_return_value_raises_rather_than_silently_passing_through(self):
        with self.assertRaises(TypeError):
            credential_transport.capability_of(_WrongReturnType())


class CredentialTransportCapabilityAnyTest(unittest.TestCase):
    def test_default_is_falsy_in_every_field(self):
        capability = CredentialTransportCapability()
        self.assertFalse(capability.any)

    def test_one_true_operation_is_enough(self):
        self.assertTrue(CredentialTransportCapability(redact_on_output=True).any)


class LoadCatalogTest(unittest.TestCase):
    def test_load_catalog_bytes_matches_the_file_on_disk(self):
        on_disk = (
            ROOT / "src/pegasus/content/security/credential-transport-catalog.json"
        ).read_bytes()
        self.assertEqual(credential_transport.load_catalog_bytes(), on_disk)

    def test_load_catalog_parses_to_the_same_data(self):
        self.assertEqual(
            credential_transport.load_catalog(),
            json.loads((ROOT / "src/pegasus/content/security/credential-transport-catalog.json").read_text()),
        )


class OpenCodeAdapterCredentialTransportWiringTest(unittest.TestCase):
    """The installer ships the plugin and its sidecar only where the
    capability exists -- proven both ways: OpenCode (declares all four)
    ships both files, and a stand-in adapter that declares none does not."""

    @classmethod
    def setUpClass(cls):
        from pegasus.adapters.opencode.adapter import Adapter

        cls.Adapter = Adapter
        cls.identity = cli.default_identity()
        cls.environment = Environment(home=Path("/home/probe"))

    def test_opencode_declares_every_operation(self):
        capability = self.Adapter().credential_transport()
        self.assertTrue(capability.any)
        self.assertEqual(capability, CredentialTransportCapability(True, True, True, True))

    def test_opencode_ships_the_plugin_and_its_sidecar(self):
        from pegasus.core.types import FileArtifact

        adapter = self.Adapter()
        layout = adapter.layout(self.environment)
        artifacts = adapter.own_artifacts(layout, "pegasus-orchestrator", self.identity, ())
        paths = {item.path for item in artifacts if isinstance(item, FileArtifact)}
        self.assertIn(layout.config_dir / "plugins/pegasus-secret-transport.ts", paths)
        self.assertIn(layout.config_dir / "plugins/pegasus-secret-transport-catalog.json", paths)

class ClaudeCodeAdapterCredentialTransportWiringTest(unittest.TestCase):
    """The real, registered `claudecode.Adapter` -- not a monkeypatched
    stand-in -- declares no credential-transport operation, and its
    `own_artifacts` ships neither the plugin nor the catalog sidecar. Every
    other own_artifacts behavior (the `agent` settings key, the generated
    delegation-capabilities reference) is untouched: `own_artifacts` returns
    exactly those two artifacts, confirmed by a review reading this
    adapter's real output."""

    @classmethod
    def setUpClass(cls):
        from pegasus.adapters.claudecode.adapter import Adapter

        cls.Adapter = Adapter
        cls.identity = cli.default_identity()
        cls.environment = Environment(home=Path("/home/probe"))

    def test_declares_every_operation_false(self):
        capability = credential_transport.capability_of(self.Adapter())
        self.assertFalse(capability.any)

    def test_own_artifacts_ships_neither_the_plugin_nor_the_sidecar(self):
        adapter = self.Adapter()
        layout = adapter.layout(self.environment)
        artifacts = adapter.own_artifacts(layout, "pegasus-orchestrator", self.identity, ())
        file_paths = {item.path for item in artifacts if isinstance(item, FileArtifact)}
        self.assertFalse(any("secret-transport" in str(path) for path in file_paths))
        # Exactly what this adapter's own_artifacts ships: the settings
        # `agent` key (a ConfigKeyArtifact, not a FileArtifact) and the
        # generated delegation-capabilities reference -- nothing else.
        self.assertEqual(
            {path.name for path in file_paths},
            {"delegation-capabilities.md"},
        )


class ClaudeCodeRealInstallShipsNeitherFileTest(RealHomeTestCase):
    """A real install for `claudecode`, into a throwaway home backed by the
    real filesystem -- not the engine called in isolation -- confirms the
    plugin and its sidecar never land on disk for this adapter."""

    CLI = "claudecode"

    def runtime(self) -> cli.Runtime:
        return cli.Runtime(
            filesystem=self.filesystem, home=self.home, now="2026-09-26T00:00:00+00:00", out=io.StringIO()
        )

    def test_install_ships_no_secret_transport_asset(self):
        from pegasus.core.types import Environment as _Environment

        layout = available().get(self.CLI).layout(_Environment(home=self.home))
        layout.config_dir.mkdir(parents=True, exist_ok=True)
        context = self.runtime()
        code = cli.main(["install", "--cli", self.CLI, "--json"], runtime=context)
        report = json.loads(context.out.getvalue())
        self.assertEqual(code, 0, report)

        installed_paths = [
            path for path in layout.config_dir.rglob("*") if path.is_file()
        ]
        self.assertFalse(
            any("secret-transport" in path.name for path in installed_paths),
            [str(p) for p in installed_paths],
        )


if __name__ == "__main__":
    unittest.main()
