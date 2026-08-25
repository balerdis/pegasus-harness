"""The registry fails closed: an incoherent adapter never reaches an installation."""
from __future__ import annotations

import unittest
from pathlib import Path

from pegasus.core.registry import (
    AdapterScopeError,
    DuplicateAdapterError,
    ManifestMismatchError,
    Registry,
)
from pegasus.core.types import (
    Capability,
    CapabilityManifest,
    Detection,
    Environment,
    FileArtifact,
    Layout,
    SupportTier,
)

CONFIG = Path("/home/probe/.config/probe")


class FakeAdapter:
    """Minimal adapter that declares exactly what the test asks it to declare."""

    def __init__(self, cli_id="probe", *, manifest=None, layout=None, renders=("render_skill",), own=()):
        self.id = cli_id
        self.display_name = cli_id.title()
        self._manifest = manifest or CapabilityManifest(cli_id=cli_id, skills=True)
        self._layout = layout or Layout(config_dir=CONFIG, skills_dir=CONFIG / "skills")
        self._own = own
        for name in renders:
            setattr(self, name, self._render)

    def tier(self):
        return SupportTier.FULL

    def capabilities(self):
        return self._manifest

    def detect(self, environment):
        return Detection()

    def layout(self, environment):
        return self._layout

    def _render(self, layout, item):
        return [FileArtifact(id="x", path=CONFIG / "x", content=b"")]

    def own_artifacts(self, layout):
        return list(self._own)

    def activation_steps(self):
        return ()


ENVIRONMENT = Environment(home=Path("/home/probe"))


class RegistrationTest(unittest.TestCase):
    def test_an_adapter_that_cannot_say_what_is_left_to_do_is_refused(self):
        """The engine asks while reporting, and reporting happens after writing."""
        adapter = FakeAdapter()
        del adapter.__class__.activation_steps
        try:
            with self.assertRaises(ManifestMismatchError) as raised:
                Registry().register(adapter)
            self.assertIn("activation_steps", str(raised.exception))
        finally:
            FakeAdapter.activation_steps = lambda self: ()

    def test_accepts_a_coherent_adapter(self):
        registry = Registry()
        registry.register(FakeAdapter())
        self.assertEqual(registry.ids(), ("probe",))

    def test_returns_the_registered_adapter(self):
        registry = Registry()
        adapter = FakeAdapter()
        registry.register(adapter)
        self.assertIs(registry.get("probe"), adapter)

    def test_unknown_id_raises(self):
        with self.assertRaises(KeyError):
            Registry().get("nope")

    def test_ids_are_sorted(self):
        registry = Registry()
        for cli_id in ("zeta", "alpha"):
            registry.register(FakeAdapter(cli_id))
        self.assertEqual(registry.ids(), ("alpha", "zeta"))

    def test_duplicate_id_is_rejected(self):
        registry = Registry()
        registry.register(FakeAdapter())
        with self.assertRaises(DuplicateAdapterError):
            registry.register(FakeAdapter())


class ManifestCoherenceTest(unittest.TestCase):
    def register(self, adapter):
        Registry().register(adapter)

    def test_manifest_for_another_cli_is_rejected(self):
        adapter = FakeAdapter(manifest=CapabilityManifest(cli_id="other", skills=True))
        with self.assertRaises(ManifestMismatchError):
            self.register(adapter)

    def test_declared_capability_without_its_anchor_is_rejected(self):
        adapter = FakeAdapter(layout=Layout(config_dir=CONFIG))
        with self.assertRaises(ManifestMismatchError) as raised:
            self.register(adapter)
        self.assertIn("skills", str(raised.exception))

    def test_declared_capability_without_its_render_is_rejected(self):
        with self.assertRaises(ManifestMismatchError) as raised:
            self.register(FakeAdapter(renders=()))
        self.assertIn("render_skill", str(raised.exception))

    def test_undeclared_capability_exposing_an_anchor_is_rejected(self):
        """A phantom capability: the path exists but the manifest says the CLI lacks it."""
        adapter = FakeAdapter(
            manifest=CapabilityManifest(cli_id="probe"),
            layout=Layout(config_dir=CONFIG, skills_dir=CONFIG / "skills"),
            renders=(),
        )
        with self.assertRaises(ManifestMismatchError):
            self.register(adapter)

    def test_undeclared_capability_exposing_a_render_is_rejected(self):
        adapter = FakeAdapter(manifest=CapabilityManifest(cli_id="probe"), layout=Layout(config_dir=CONFIG))
        with self.assertRaises(ManifestMismatchError):
            self.register(adapter)

    def test_model_configuration_requires_every_model_method(self):
        adapter = FakeAdapter(
            manifest=CapabilityManifest(cli_id="probe", skills=True, per_agent_model=True),
        )
        adapter.model_catalog = lambda environment: {}
        with self.assertRaises(ManifestMismatchError) as raised:
            self.register(adapter)
        self.assertIn("read_model_assignments", str(raised.exception))

    def test_model_configuration_with_every_method_is_accepted(self):
        adapter = FakeAdapter(
            manifest=CapabilityManifest(cli_id="probe", skills=True, per_agent_model=True),
        )
        for name in ("model_catalog", "read_model_assignments"):
            setattr(adapter, name, lambda *args, **kwargs: None)
        Registry().register(adapter)

    def test_layout_is_probed_without_touching_the_filesystem(self):
        """Registration must work against a home directory that does not exist."""
        registry = Registry()
        registry.register(FakeAdapter())
        self.assertFalse(Path("/home/probe").exists())
        self.assertEqual(registry.get("probe").layout(ENVIRONMENT).config_dir, CONFIG)


class ManifestLookupTest(unittest.TestCase):
    def test_exposes_the_validated_manifest(self):
        registry = Registry()
        registry.register(FakeAdapter())
        self.assertIn(Capability.SKILLS, registry.manifest("probe").enabled)


if __name__ == "__main__":
    unittest.main()


class OwnArtifactsTest(unittest.TestCase):
    """The escape hatch is guarded: an adapter may ship its own files, inside its own root."""

    def test_an_adapter_shipping_nothing_of_its_own_registers(self):
        Registry().register(FakeAdapter())

    def test_own_artifacts_inside_the_config_root_are_accepted(self):
        own = (FileArtifact(id="plugin:x", path=CONFIG / "plugins" / "x.ts", content=b""),)
        Registry().register(FakeAdapter(own=own))

    def test_own_artifacts_outside_the_config_root_are_rejected(self):
        own = (FileArtifact(id="rogue", path=Path("/home/probe/.bashrc"), content=b""),)
        with self.assertRaises(AdapterScopeError) as raised:
            Registry().register(FakeAdapter(own=own))
        self.assertIn(".bashrc", str(raised.exception))

    def test_an_adapter_without_own_artifacts_is_rejected(self):
        class Incomplete(FakeAdapter):
            own_artifacts = None

        with self.assertRaises(ManifestMismatchError) as raised:
            Registry().register(Incomplete())
        self.assertIn("own_artifacts", str(raised.exception))
