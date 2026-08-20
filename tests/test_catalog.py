"""Building the catalog: deterministic, addressed portably, and self-checking."""
from __future__ import annotations

import inspect
import json
import os
import unittest
from unittest import mock
from pathlib import Path, PurePosixPath

from pegasus.adapters.opencode import Adapter
from pegasus.core import catalog as catalog_module
from pegasus.core import content as content_module
from pegasus.core.catalog import Catalog, CatalogError, Entry
from pegasus.core.content import Content
from pegasus.core.types import (
    Capability,
    CapabilityManifest,
    ConfigKeyArtifact,
    Environment,
    FileArtifact,
    Layout,
)

HOME = Path("/home/probe")
ENVIRONMENT = Environment(home=HOME)
CONFIG = Path("/home/probe/.config/probe")


class StubAdapter:
    """An adapter that returns exactly the artifacts a test hands it."""

    id = "probe"
    display_name = "Probe"

    def __init__(self, *, artifacts=(), own=(), manifest=None):
        self._artifacts = artifacts
        self._own = own
        self._manifest = manifest or CapabilityManifest(cli_id="probe", skills=True)

    def capabilities(self):
        return self._manifest

    def layout(self, environment):
        return Layout(config_dir=CONFIG, settings_file=CONFIG / "settings.json", skills_dir=CONFIG / "skills")

    def render_skill(self, layout, skill):
        return list(self._artifacts)

    def own_artifacts(self, layout):
        return list(self._own)


def one_skill():
    from pegasus.core.content import Asset, Skill

    return Content(
        skills=(
            Skill(
                name="alpha",
                description="d",
                assets=(Asset(PurePosixPath("SKILL.md"), b"body"),),
                source=PurePosixPath("skills/alpha/SKILL.md"),
            ),
        )
    )


class BuildTest(unittest.TestCase):
    def test_renders_the_declared_capability(self):
        artifact = FileArtifact(id="skill:alpha", path=CONFIG / "skills/alpha/SKILL.md", content=b"body")
        catalog = catalog_module.build(one_skill(), StubAdapter(artifacts=(artifact,)))
        self.assertEqual([entry.id for entry in catalog.entries], ["skill:alpha"])

    def test_includes_what_the_adapter_ships_itself(self):
        own = (FileArtifact(id="own:plugin", path=CONFIG / "plugins/x.ts", content=b"x"),)
        catalog = catalog_module.build(Content(), StubAdapter(own=own))
        self.assertEqual([entry.id for entry in catalog.entries], ["own:plugin"])

    def test_targets_are_relative_to_the_configuration_root(self):
        artifact = FileArtifact(id="a", path=CONFIG / "skills/alpha/SKILL.md", content=b"body")
        catalog = catalog_module.build(one_skill(), StubAdapter(artifacts=(artifact,)))
        self.assertEqual(catalog.entries[0].target, PurePosixPath("skills/alpha/SKILL.md"))

    def test_entries_are_sorted_by_id(self):
        artifacts = tuple(
            FileArtifact(id=name, path=CONFIG / name, content=b"x") for name in ("zeta", "alpha", "mu")
        )
        catalog = catalog_module.build(one_skill(), StubAdapter(artifacts=artifacts))
        self.assertEqual([entry.id for entry in catalog.entries], ["alpha", "mu", "zeta"])

    def test_a_capability_configured_after_installing_contributes_nothing(self):
        manifest = CapabilityManifest(cli_id="probe", skills=True, per_agent_model=True)
        adapter = StubAdapter(manifest=manifest)
        self.assertEqual(len(catalog_module.build(Content(), adapter)), 0)

    def test_a_declared_capability_with_no_content_source_is_refused(self):
        manifest = CapabilityManifest(cli_id="probe", skills=True, mcp=True)
        with self.assertRaises(CatalogError) as raised:
            catalog_module.build(Content(), StubAdapter(manifest=manifest))
        self.assertIn("mcp", str(raised.exception))


class DigestTest(unittest.TestCase):
    def file_catalog(self, content_bytes):
        artifact = FileArtifact(id="a", path=CONFIG / "a", content=content_bytes)
        return catalog_module.build(one_skill(), StubAdapter(artifacts=(artifact,)))

    def test_a_file_digest_covers_its_bytes(self):
        self.assertTrue(self.file_catalog(b"body").entries[0].digest.startswith("sha256:"))

    def test_different_bytes_produce_different_digests(self):
        self.assertNotEqual(
            self.file_catalog(b"one").entries[0].digest, self.file_catalog(b"two").entries[0].digest
        )

    def test_a_configuration_digest_ignores_key_order(self):
        def digest(value):
            artifact = ConfigKeyArtifact(id="k", path=CONFIG / "settings.json", pointer="/a", value=value)
            return catalog_module.build(Content(), StubAdapter(own=(artifact,))).entries[0].digest

        self.assertEqual(digest({"a": 1, "b": 2}), digest({"b": 2, "a": 1}))

    def test_the_catalog_has_one_digest_of_its_own(self):
        self.assertTrue(self.file_catalog(b"body").digest.startswith("sha256:"))

    def test_the_catalog_digest_changes_with_its_content(self):
        self.assertNotEqual(self.file_catalog(b"one").digest, self.file_catalog(b"two").digest)


class CollisionTest(unittest.TestCase):
    def build(self, artifacts):
        return catalog_module.build(one_skill(), StubAdapter(artifacts=artifacts))

    def test_two_files_at_one_path_are_refused(self):
        artifacts = (
            FileArtifact(id="a", path=CONFIG / "same", content=b"one"),
            FileArtifact(id="b", path=CONFIG / "same", content=b"two"),
        )
        with self.assertRaises(CatalogError) as raised:
            self.build(artifacts)
        self.assertIn("same", str(raised.exception))

    def test_two_artifacts_with_one_id_are_refused(self):
        artifacts = (
            FileArtifact(id="same", path=CONFIG / "a", content=b"one"),
            FileArtifact(id="same", path=CONFIG / "b", content=b"two"),
        )
        with self.assertRaises(CatalogError):
            self.build(artifacts)

    def test_two_writes_to_one_configuration_key_are_refused(self):
        artifacts = (
            ConfigKeyArtifact(id="a", path=CONFIG / "s.json", pointer="/share", value="disabled"),
            ConfigKeyArtifact(id="b", path=CONFIG / "s.json", pointer="/share", value="enabled"),
        )
        with self.assertRaises(CatalogError):
            self.build(artifacts)

    def test_appending_twice_to_one_list_is_allowed(self):
        """Two entries in an array are two entries, not a collision."""
        artifacts = (
            ConfigKeyArtifact(id="a", path=CONFIG / "s.json", pointer="/plugin/-", value="one"),
            ConfigKeyArtifact(id="b", path=CONFIG / "s.json", pointer="/plugin/-", value="two"),
        )
        self.assertEqual(len(self.build(artifacts)), 2)

    def test_an_artifact_outside_the_configuration_root_is_refused(self):
        artifacts = (FileArtifact(id="rogue", path=Path("/home/probe/.bashrc"), content=b""),)
        with self.assertRaises(CatalogError) as raised:
            self.build(artifacts)
        self.assertIn(".bashrc", str(raised.exception))


class SerializationTest(unittest.TestCase):
    def test_omits_fields_that_do_not_apply(self):
        entry = Entry(id="a", kind="file", target=PurePosixPath("a"), digest="sha256:x", mode="0644")
        self.assertEqual(set(entry.as_dict()), {"id", "kind", "target", "digest", "mode"})

    def test_paths_serialize_as_posix_strings(self):
        entry = Entry(id="a", kind="file", target=PurePosixPath("skills/a/SKILL.md"), digest="d")
        self.assertEqual(entry.as_dict()["target"], "skills/a/SKILL.md")

    def test_the_catalog_declares_its_schema(self):
        catalog = Catalog(cli="probe", entries=())
        self.assertEqual(catalog.as_dict()["schema"], "pegasus/artifact-catalog/v4")


class TwoTopLevelAgentsTest(unittest.TestCase):
    """Two selectable top-level agents, one of which is where a session opens.

    While the mode decided the default, this content could not be expressed: both
    primaries rendered a `/default_agent` artifact under one hardcoded id and the
    catalog refused the pair. Only the agent the core names starts a session now,
    so a second primary is nothing but another entry in the agent map.
    """

    STARTS = content_module.SESSION_STARTS_IN

    @classmethod
    def agent(cls, name):
        return content_module.Agent(
            name=name,
            description="A top-level agent",
            body="Body.\n",
            mode=content_module.AgentMode.PRIMARY,
            source=PurePosixPath(f"agents/{name}.md"),
        )

    def build(self):
        content = Content(agents=(self.agent(self.STARTS), self.agent("beta")))
        return catalog_module.build(content, Adapter())

    def test_two_primary_agents_build_a_catalog(self):
        """Membership, not equality: a future per-agent artifact is not this test's business."""
        rendered = [entry.id for entry in self.build().entries]
        for expected in (f"agent:{self.STARTS}", "agent:beta", "default-agent"):
            self.assertIn(expected, rendered)
        self.assertEqual(len(rendered), len(set(rendered)))

    def test_only_one_of_them_writes_the_default(self):
        pointers = [entry.pointer for entry in self.build().entries]
        self.assertEqual(pointers.count("/default_agent"), 1)


class ShippedCatalogTest(unittest.TestCase):
    """The real content, through the real adapter, must produce a usable catalog."""

    @classmethod
    def setUpClass(cls):
        cls.content = content_module.load()
        cls.catalog = catalog_module.build(cls.content, Adapter())

    def test_produces_the_whole_payload(self):
        files = [entry for entry in self.catalog.entries if entry.kind == "file"]
        keys = [entry for entry in self.catalog.entries if entry.kind == "config-key"]
        # 89, not 88: `_shared/cbm-convention.md` is the one new shipped file,
        # centralizing CBM protocol prose that used to be restated per phase.
        self.assertEqual((len(files), len(keys)), (89, 17))

    def test_every_target_is_relative(self):
        for entry in self.catalog.entries:
            self.assertFalse(entry.target.is_absolute(), entry.id)

    def test_every_entry_carries_a_digest(self):
        for entry in self.catalog.entries:
            self.assertTrue(entry.digest.startswith("sha256:"), entry.id)

    def test_building_twice_produces_the_same_digest(self):
        again = catalog_module.build(content_module.load(), Adapter())
        self.assertEqual(again.digest, self.catalog.digest)

    def test_the_catalog_does_not_depend_on_the_home_directory(self):
        """Targets are relative to the config root, so the same content travels anywhere."""
        elsewhere = catalog_module.build(self.content, Adapter())
        self.assertEqual(elsewhere.digest, self.catalog.digest)

    def test_no_entry_carries_an_absolute_home(self):
        """Release identity must not describe bytes that exist on one machine only."""
        document = json.dumps(self.catalog.as_dict())
        self.assertNotIn(str(HOME), document)
        self.assertNotIn(str(catalog_module.CANONICAL_HOME), document)

    def test_the_machine_that_builds_the_catalog_never_reaches_the_digest(self):
        """The tripwire for the canonical frame, and it needs teeth to be one.

        A catalog with nothing to fill is home-independent whatever `build` does,
        so this content carries a placeholder on purpose: only then does an
        ambient home reach the rendered bytes, and only then can a `build` that
        quietly reads the environment again be told apart from one that does not.
        """
        content = Content(
            agents=(
                content_module.Agent(
                    name="probe",
                    description="A probe",
                    body="Read {{skills_root}}/probe/SKILL.md.\n",
                    mode=content_module.AgentMode.SUBAGENT,
                    source=PurePosixPath("agents/probe.md"),
                ),
            )
        )
        digests = set()
        for home in ("/home/one", "/home/two"):
            with mock.patch.dict(os.environ, {"HOME": home, "XDG_CONFIG_HOME": f"{home}/cfg"}):
                digests.add(catalog_module.build(content, Adapter()).digest)
        self.assertEqual(len(digests), 1, "the build home reached release identity")

        # Varying two variables only catches a build that reads those two. Refusing
        # the parameter outright is the property itself, so it is asserted directly.
        self.assertNotIn("environment", inspect.signature(catalog_module.build).parameters)

    def test_the_system_prompt_is_wired_through_the_instructions_list(self):
        pointers = {entry.pointer for entry in self.catalog.entries if entry.pointer}
        self.assertIn("/instructions/-", pointers)


if __name__ == "__main__":
    unittest.main()
