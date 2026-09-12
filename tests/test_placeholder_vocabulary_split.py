"""The placeholder vocabulary is split by audience, and the split must mirror
who actually answers each name.

A content body is installed by every adapter and is filled by `render.facts`,
so it may only ask for what that function answers -- today, `skills_root`.
A bundled OpenCode asset (a plugin, a package manifest) is filled by
`adapter._asset_facts`, which extends `render.facts` with facts about a
running distribution's own identity -- `program_name`, `display_name`, and
friends -- that no content body has any business asking for.

These tests fix that split from both directions:

- `placeholders.BODY_NAMES` is exactly what `render.facts` can answer, and
  `placeholders.ASSET_NAMES` is exactly what `_asset_facts` adds on top of
  `render.facts` -- derived from the live dict keys those two functions
  produce, not from a second, hand-written list that could drift.
- A content body asking for an asset-only name is refused at content load,
  before any adapter ever sees it -- not two commands later at install.

`core.placeholders` must not import from `adapters`, so the mirror test lives
here, in `tests`, and reaches into the adapter itself.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path, PurePath

from pegasus import cli
from pegasus.adapters.opencode import adapter as adapter_module
from pegasus.adapters.opencode import render as render_module
from pegasus.core import content as content_module
from pegasus.core import placeholders
from pegasus.core.types import Environment

IDENTITY = cli.default_identity()


def _layout_with_skills():
    home = PurePath("/home/probe")
    environment = Environment(home=home, data_dir=home / ".local/share/pegasus")
    return adapter_module.Adapter().layout(environment)


class BodyVocabularyMirrorsRenderFactsTest(unittest.TestCase):
    """`render.facts` is the only thing that fills a body's placeholders."""

    def test_body_names_equal_what_render_facts_answers(self):
        layout = _layout_with_skills()
        answered = set(render_module.facts(layout))
        self.assertEqual(set(placeholders.BODY_NAMES), answered)


class AssetVocabularyMirrorsAssetFactsTest(unittest.TestCase):
    """`_asset_facts` extends `render.facts`; only the extension is asset-only."""

    def test_asset_names_equal_what_asset_facts_adds_on_top_of_render_facts(self):
        layout = _layout_with_skills()
        body_answered = set(render_module.facts(layout))
        asset_answered = set(adapter_module._asset_facts(layout, "probe-orchestrator", IDENTITY))
        asset_only = asset_answered - body_answered
        self.assertEqual(set(placeholders.ASSET_NAMES), asset_only)


class BodyMayNotAskForAnAssetOnlyNameTest(unittest.TestCase):
    """An asset-only name in a body must be refused at content load."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "agents").mkdir()
        start = self.root / "agents" / f"{content_module.SESSION_STARTS_IN}.md"
        start.write_text(
            f"---\nname: {content_module.SESSION_STARTS_IN}\ndescription: Where a session starts\nmode: primary\n---\n\nNothing to fill.\n",
            encoding="utf-8",
        )

    def tearDown(self):
        self.temporary.cleanup()

    def test_program_name_in_a_body_is_refused_at_content_load(self):
        (self.root / "agents" / "probe-agent.md").write_text(
            "---\nname: probe-agent\ndescription: Probes the split\nmode: primary\n---\n\n"
            "Refer to yourself as {{program_name}}.\n",
            encoding="utf-8",
        )
        with self.assertRaises(content_module.ContentError) as raised:
            content_module.load(self.root)
        message = str(raised.exception)
        self.assertIn("program_name", message)
        self.assertIn("agents/probe-agent.md", message)


if __name__ == "__main__":
    unittest.main()
