"""Building the catalog: deterministic, addressed portably, and self-checking."""
from __future__ import annotations

import inspect
import json
import os
import tempfile
import unittest
from unittest import mock
from pathlib import Path, PurePosixPath

from pegasus import cli
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

#: A real `Identity`, standing in for `Runtime.identity`: every test here
#: builds a catalog the same way `cli.py`'s composition root does, never a
#: literal invented for the test.
IDENTITY = cli.default_identity()


def build(content, adapter):
    return catalog_module.build(content, adapter, IDENTITY)


#: `render` now derives `orchestrator_name` unconditionally -- `own_artifacts`
#: is called on every build, never only when `SLASH_COMMANDS` is declared --
#: so every synthetic `Content` exercised through `build`/`render` needs a
#: default agent too, exactly as a real release always has one.
_ORCHESTRATOR = content_module.Agent(
    name=content_module.SESSION_STARTS_IN,
    description="d",
    body="body",
    mode=content_module.AgentMode.PRIMARY,
    source=PurePosixPath("agents/orchestrator.md"),
)


def _content(**fields):
    """`Content(**fields)`, plus the default agent every real release carries."""
    agents = fields.pop("agents", ())
    if not any(agent.default for agent in agents):
        agents = agents + (_ORCHESTRATOR,)
    return Content(agents=agents, **fields)


class StubAdapter:
    """An adapter that returns exactly the artifacts a test hands it."""

    id = "probe"
    display_name = "Probe"

    def __init__(self, *, artifacts=(), own=(), manifest=None):
        self._artifacts = artifacts
        self._own = own
        self._manifest = manifest or CapabilityManifest(cli_id="probe", skills=True)
        self.agent_calls = []

    def capabilities(self):
        return self._manifest

    def layout(self, environment):
        return Layout(config_dir=CONFIG, settings_file=CONFIG / "settings.json", skills_dir=CONFIG / "skills")

    def render_skill(self, layout, skill):
        return list(self._artifacts)

    def render_agent(self, layout, agent, model=None):
        self.agent_calls.append((agent.name, model))
        return []

    def own_artifacts(self, layout, orchestrator_name, identity):
        self.own_artifacts_orchestrator_name = orchestrator_name
        self.own_artifacts_identity = identity
        return list(self._own)


def one_skill():
    from pegasus.core.content import Asset, Skill

    return _content(
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
        artifact = FileArtifact(id="skill:alpha", path=CONFIG / "skills/alpha/SKILL.md", content=b"body", executable=False)
        catalog = build(one_skill(), StubAdapter(artifacts=(artifact,)))
        self.assertEqual([entry.id for entry in catalog.entries], ["skill:alpha"])

    def test_includes_what_the_adapter_ships_itself(self):
        own = (FileArtifact(id="own:plugin", path=CONFIG / "plugins/x.ts", content=b"x", executable=False),)
        catalog = build(_content(), StubAdapter(own=own))
        self.assertEqual([entry.id for entry in catalog.entries], ["own:plugin"])

    def test_own_artifacts_receives_the_content_declared_orchestrator(self):
        adapter = StubAdapter()
        build(_content(), adapter)
        self.assertEqual(adapter.own_artifacts_orchestrator_name, content_module.SESSION_STARTS_IN)

    def test_own_artifacts_receives_the_identity_build_was_given(self):
        """The identity an adapter's `own_artifacts` sees must be the exact
        `Identity` `build` was called with -- a distribution's own, not a
        constant this module could have reached for on its own. A `Runtime`
        built for a fictional distribution stands in for `Runtime.identity`,
        the same shape `test_cli.py`'s own distribution sweep uses."""
        distribution_identity = cli.identity_module.parse(
            json.dumps(
                {
                    "product_id": "darq-cli",
                    "display_name": "Darq",
                    "program_name": "darq",
                    "version": "1.0.0",
                    "wordmark_words": ["DARQ"],
                    "release": {
                        "asset_url_template": "https://example.invalid/darq/releases/download/{tag}/{asset}",
                        "binary_asset": "darq",
                        "latest_release_api_url": "https://example.invalid/darq/api/releases/latest",
                        "release_page_url": "https://example.invalid/darq/releases",
                        "install_base_url_default": "https://example.invalid/darq/releases/latest/download",
                    },
                }
            ).encode("utf-8")
        )
        adapter = StubAdapter()
        catalog_module.build(_content(), adapter, distribution_identity)
        self.assertIs(adapter.own_artifacts_identity, distribution_identity)

    def test_targets_are_relative_to_the_configuration_root(self):
        artifact = FileArtifact(id="a", path=CONFIG / "skills/alpha/SKILL.md", content=b"body", executable=False)
        catalog = build(one_skill(), StubAdapter(artifacts=(artifact,)))
        self.assertEqual(catalog.entries[0].target, PurePosixPath("skills/alpha/SKILL.md"))

    def test_entries_are_sorted_by_id(self):
        artifacts = tuple(
            FileArtifact(id=name, path=CONFIG / name, content=b"x", executable=False) for name in ("zeta", "alpha", "mu")
        )
        catalog = build(one_skill(), StubAdapter(artifacts=artifacts))
        self.assertEqual([entry.id for entry in catalog.entries], ["alpha", "mu", "zeta"])

    def test_a_capability_configured_after_installing_contributes_nothing(self):
        manifest = CapabilityManifest(cli_id="probe", skills=True, per_agent_model=True)
        adapter = StubAdapter(manifest=manifest)
        self.assertEqual(len(build(_content(), adapter)), 0)

    def test_every_non_interactive_capability_has_a_content_source(self):
        non_interactive = set(Capability) - catalog_module.INTERACTIVE
        self.assertEqual(non_interactive, set(catalog_module.SOURCES))


def one_agent(name="probe-agent"):
    from pegasus.core.content import Agent, AgentMode

    return _content(
        agents=(
            Agent(
                name=name,
                description="d",
                body="body",
                mode=content_module.AgentMode.SUBAGENT,
                source=PurePosixPath("agents/probe-agent.md"),
                model_configurable=True,
            ),
        )
    )


class RenderModelOverrideTest(unittest.TestCase):
    def test_render_agent_receives_the_matching_override(self):
        manifest = CapabilityManifest(cli_id="probe", sub_agents=True)
        adapter = StubAdapter(manifest=manifest)
        catalog_module.render(
            one_agent("probe-agent"), adapter, ENVIRONMENT, IDENTITY, model_overrides={"probe-agent": "anthropic/x"}
        )
        # `one_agent` now also carries the default orchestrator agent `_content`
        # adds for `own_artifacts`'s sake; membership, not equality, is this
        # test's business -- the override reaching the right name is.
        self.assertIn(("probe-agent", "anthropic/x"), adapter.agent_calls)

    def test_an_agent_with_no_override_gets_none(self):
        manifest = CapabilityManifest(cli_id="probe", sub_agents=True)
        adapter = StubAdapter(manifest=manifest)
        catalog_module.render(one_agent("probe-agent"), adapter, ENVIRONMENT, IDENTITY)
        self.assertIn(("probe-agent", None), adapter.agent_calls)

    def test_build_never_forwards_a_model_override(self):
        """`build` has no `model_overrides` parameter at all, so an assignment
        cannot enter the canonical render that produces release identity."""
        self.assertNotIn("model_overrides", inspect.signature(catalog_module.build).parameters)
        manifest = CapabilityManifest(cli_id="probe", sub_agents=True)
        adapter = StubAdapter(manifest=manifest)
        build(one_agent("probe-agent"), adapter)
        self.assertIn(("probe-agent", None), adapter.agent_calls)


class DigestTest(unittest.TestCase):
    def file_catalog(self, content_bytes):
        artifact = FileArtifact(id="a", path=CONFIG / "a", content=content_bytes, executable=False)
        return build(one_skill(), StubAdapter(artifacts=(artifact,)))

    def test_a_file_digest_covers_its_bytes(self):
        self.assertTrue(self.file_catalog(b"body").entries[0].digest.startswith("sha256:"))

    def test_different_bytes_produce_different_digests(self):
        self.assertNotEqual(
            self.file_catalog(b"one").entries[0].digest, self.file_catalog(b"two").entries[0].digest
        )

    def test_a_configuration_digest_ignores_key_order(self):
        def digest(value):
            artifact = ConfigKeyArtifact(id="k", path=CONFIG / "settings.json", pointer="/a", value=value)
            return build(_content(), StubAdapter(own=(artifact,))).entries[0].digest

        self.assertEqual(digest({"a": 1, "b": 2}), digest({"b": 2, "a": 1}))

    def test_the_catalog_has_one_digest_of_its_own(self):
        self.assertTrue(self.file_catalog(b"body").digest.startswith("sha256:"))

    def test_the_catalog_digest_changes_with_its_content(self):
        self.assertNotEqual(self.file_catalog(b"one").digest, self.file_catalog(b"two").digest)


class CollisionTest(unittest.TestCase):
    def build(self, artifacts):
        return build(one_skill(), StubAdapter(artifacts=artifacts))

    def test_two_files_at_one_path_are_refused(self):
        artifacts = (
            FileArtifact(id="a", path=CONFIG / "same", content=b"one", executable=False),
            FileArtifact(id="b", path=CONFIG / "same", content=b"two", executable=False),
        )
        with self.assertRaises(CatalogError) as raised:
            self.build(artifacts)
        self.assertIn("same", str(raised.exception))

    def test_two_artifacts_with_one_id_are_refused(self):
        artifacts = (
            FileArtifact(id="same", path=CONFIG / "a", content=b"one", executable=False),
            FileArtifact(id="same", path=CONFIG / "b", content=b"two", executable=False),
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
        artifacts = (FileArtifact(id="rogue", path=Path("/home/probe/.bashrc"), content=b"", executable=False),)
        with self.assertRaises(CatalogError) as raised:
            self.build(artifacts)
        self.assertIn(".bashrc", str(raised.exception))

    def test_an_artifact_inside_pegasus_own_directory_is_accepted(self):
        """A materialized dependency lands outside the configuration root, in
        Pegasus's own directory -- a second legitimate territory, not a leak."""
        artifact = FileArtifact(
            id="dep:server",
            path=catalog_module.CANONICAL_DATA_DIR / "deps" / "server" / "1.0.0" / "bin",
            content=b"",
            executable=True,
        )
        catalog = build(one_skill(), StubAdapter(artifacts=(artifact,)))
        self.assertEqual([entry.id for entry in catalog.entries], ["dep:server"])

    def test_an_artifact_outside_every_legitimate_root_is_still_refused(self):
        """Pegasus's own directory widens what is legitimate; it does not remove
        the boundary. A path aiming at neither territory is still a leak."""
        artifacts = (FileArtifact(id="rogue", path=Path("/home/probe/.bashrc"), content=b"", executable=False),)
        with self.assertRaises(CatalogError) as raised:
            self.build(artifacts)
        self.assertIn(".bashrc", str(raised.exception))
        self.assertIn(str(CONFIG), str(raised.exception))
        self.assertIn(str(catalog_module.CANONICAL_DATA_DIR), str(raised.exception))


class McpConventionNamespaceTest(unittest.TestCase):
    """A server id that matches a hand-authored `_shared/` convention stem must
    not collide with it -- that is what the `_shared/mcp/` subdirectory buys.

    `cbm` and `engram` are both real planned servers, and `_shared/cbm-convention.md`
    and `_shared/engram-convention.md` already exist as hand-authored files. Before
    the servers' conventions moved into their own subdirectory, loading both ids
    would have addressed two different writers at the very same path.
    """

    def build_content(self, root: Path):
        skill_dir = root / "skills" / "_shared"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: _shared\ndescription: Shared convention files\n---\n\nShared.\n",
            encoding="utf-8",
        )
        (skill_dir / "cbm-convention.md").write_text("# CBM Convention\n\nHand-authored.\n", encoding="utf-8")
        (skill_dir / "engram-convention.md").write_text(
            "# Engram Convention\n\nHand-authored.\n", encoding="utf-8"
        )
        mcp_dir = root / "mcp"
        mcp_dir.mkdir()
        for server_id in ("cbm", "engram"):
            (mcp_dir / f"{server_id}.md").write_text(
                f"---\nname: {server_id}\ndescription: Probe server\n"
                f"distribution: remote\nendpoint: https://example.test/{server_id}\n"
                f"reaches: [{content_module.SESSION_STARTS_IN}]\n"
                f"---\n\n# {server_id} convention body\n",
                encoding="utf-8",
            )
        agents_dir = root / "agents"
        agents_dir.mkdir()
        # `render` now derives `orchestrator_name` unconditionally, so a content
        # tree used with `build`/`render` needs a default agent, exactly like a
        # real release always has.
        (agents_dir / f"{content_module.SESSION_STARTS_IN}.md").write_text(
            f"---\nname: {content_module.SESSION_STARTS_IN}\ndescription: Probe orchestrator\n"
            "mode: primary\n---\n\nUses {{skills_root}}/_shared/mcp/cbm-convention.md "
            "and {{skills_root}}/_shared/mcp/engram-convention.md.\n",
            encoding="utf-8",
        )
        return content_module.load(root)

    def test_two_colliding_ids_load_and_render_without_a_catalog_error(self):
        with tempfile.TemporaryDirectory() as directory:
            content = self.build_content(Path(directory))
        catalog = build(content, Adapter())
        targets = {str(entry.target) for entry in catalog.entries if entry.kind == "file"}
        self.assertIn("skills/_shared/cbm-convention.md", targets)
        self.assertIn("skills/_shared/engram-convention.md", targets)
        self.assertIn("skills/_shared/mcp/cbm-convention.md", targets)
        self.assertIn("skills/_shared/mcp/engram-convention.md", targets)


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
        return build(content, Adapter())

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
        cls.catalog = build(cls.content, Adapter())

    def test_produces_the_whole_payload(self):
        files = [entry for entry in self.catalog.entries if entry.kind == "file"]
        keys = [entry for entry in self.catalog.entries if entry.kind == "config-key"]
        # 89, not 88: `_shared/context7-convention.md` is the mcp category's own
        # shared file, now that render_mcp exists and mcp is a declared capability.
        # 18, not 17: `/mcp/context7` is the one shipped MCP server's settings key.
        # 90, not 89: `_shared/mcp/engram-convention.md` is the second shipped
        # MCP server's convention file, now that `engram` is a `download`-form
        # descriptor of its own instead of prose inlined into AGENTS.md.
        # 19, not 18: `/mcp/engram` is that second server's settings key.
        # 91, still 91: `cbm` is the third shipped MCP server. Its convention
        # file (`_shared/mcp/cbm-convention.md`) replaces the one hand-authored
        # `_shared/cbm-convention.md` this count used to carry -- one file
        # traded for another, net zero.
        # 20, not 19: `/mcp/cbm` is that third server's settings key.
        # 92, not 91: `_shared/mcp/playwright-convention.md` is the fourth
        # shipped MCP server's convention file.
        # 21, not 20: `/mcp/playwright` is that fourth server's settings key.
        # 91, not 92: the SDD artifact-naming rules in `_shared/engram-convention.md`
        # were engram's, not a shared skill's, and moved into `engram`'s own
        # descriptor body -- folded into the same `_shared/mcp/engram-convention.md`
        # this count already carried, rather than adding a file of its own. One
        # hand-authored file disappears with nothing replacing it, net -1.
        # 87, not 86: `pegasus-general.md` is the thirteenth shipped agent, and its
        # own rendered prompt (`prompt:pegasus-general`) is a file like every other
        # agent's.
        # 88, not 87: `_shared/sub-delegation-criterion.md` is the focused reference
        # the delegation criterion now lives in, lazy-loaded from the phase boundary
        # and from `pegasus-general`'s own body, rather than inlined into either.
        # 22, not 21: `agent:pegasus-general` is the thirteenth agent's own
        # config-key entry, alongside its file.
        # 89, not 88: `_shared/mcp/jira-convention.md` is the fifth shipped
        # MCP server's convention file.
        # 23, not 22: `/mcp/jira` is that fifth server's settings key.
        # 90, not 89: `apply-patch-scope.ts` is a sixth bundled OpenCode plugin,
        # installed under this distribution's own derived name. It carries no
        # settings key of its own -- the plugin directory is appended once, for
        # every plugin at a time -- so the key count does not move with it.
        self.assertEqual((len(files), len(keys)), (90, 23))

    def test_every_target_is_relative(self):
        for entry in self.catalog.entries:
            self.assertFalse(entry.target.is_absolute(), entry.id)

    def test_every_entry_carries_a_digest(self):
        for entry in self.catalog.entries:
            self.assertTrue(entry.digest.startswith("sha256:"), entry.id)

    def test_building_twice_produces_the_same_digest(self):
        again = build(content_module.load(), Adapter())
        self.assertEqual(again.digest, self.catalog.digest)

    def test_the_catalog_does_not_depend_on_the_home_directory(self):
        """Targets are relative to the config root, so the same content travels anywhere."""
        elsewhere = build(self.content, Adapter())
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
        content = _content(
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
                digests.add(build(content, Adapter()).digest)
        self.assertEqual(len(digests), 1, "the build home reached release identity")

        # Varying two variables only catches a build that reads those two. Refusing
        # the parameter outright is the property itself, so it is asserted directly.
        self.assertNotIn("environment", inspect.signature(catalog_module.build).parameters)

    def test_the_system_prompt_is_wired_through_the_instructions_list(self):
        pointers = {entry.pointer for entry in self.catalog.entries if entry.pointer}
        self.assertIn("/instructions/-", pointers)


if __name__ == "__main__":
    unittest.main()
