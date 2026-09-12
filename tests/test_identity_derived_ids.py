"""A guardian derived by execution, not by a hand-written list: any artifact
whose rendered path changes when the running identity changes must also
change its `id`.

This is the structural version of the defect `test_identity_rename_migration`
proves end-to-end for one artifact (the system prompt): its `id` used to be
the constant `"system-prompt"`, so a renamed identity moved the file on disk
but never told the planner anything had moved, and `acme-AGENTS.md` sat
orphaned forever after a rename to `zenith`. That test catches a regression of
that one artifact. This one catches the same shape of bug in *any* artifact,
present or future, without naming a single one by hand: nobody enumerates
"the artifacts whose path is identity-derived" here, because that set is not
something the source can be read for reliably (an adapter can compute a path
from `Identity` through any number of indirections) -- it is *observed*, by
rendering the whole catalog twice, once per identity, and asking which paths
moved.

Reuses `FIRST_IDENTITY` / `SECOND_IDENTITY` from `test_identity_rename_migration`
-- two obviously fictional, distinct identities already built for exactly this
kind of comparison -- rather than inventing a second pair that could drift
from the first.

What this does NOT cover, and cannot: an appended `config-key` (a record whose
pointer ends in `/-`) is deliberately excluded from address-based recognition
in `core.planner` -- several such records legitimately share one address, so
none of them has an exclusive slot an `id` change could be detected against
by address alone. If such an append's own `id` scheme changes *without* its
target ever depending on identity, this guardian has nothing to observe: its
target never moved between the two renders below, so it is never a candidate
for the check at all. That gap is inherent to excluding appends from
address-based recognition, which is itself correct -- and is a real limit on
what "derive the set by execution" can close, not an oversight in this test.
"""
from __future__ import annotations

from pegasus.adapters import available
from pegasus.core import catalog
from pegasus.core.content import load as load_content
from pegasus.core.types import Environment
from test_identity_rename_migration import CLI, FIRST_IDENTITY, SECOND_IDENTITY
from real_home import RealHomeTestCase as _RealHomeTestCase


def _render(identity):
    """The same canonical, environment-independent frame `catalog.build` uses,
    but the raw artifact list `render` produces rather than `Catalog.entries`
    -- entries are sorted by `id`, which is exactly the field a rename may
    change, so pairing "the same artifact" across two renders by position in
    that sorted list would silently mispair whatever this test exists to
    catch. `render`'s own order depends only on the capability manifest and
    the content core, both identical across the two calls below; identity is
    the only thing that varies, so a position in one list is the same
    artifact as that position in the other.
    """
    content = load_content()
    adapter = available().get(CLI)
    canonical = Environment(home=catalog.CANONICAL_HOME, data_dir=catalog.CANONICAL_DATA_DIR)
    return catalog.render(content, adapter, canonical, identity)


class IdentityDerivedArtifactsCarryAnIdentityDerivedIdTest(_RealHomeTestCase):
    """Renders the real, shipped catalog under two identities and asks: for
    every artifact whose rendered path moved, did its `id` move too?
    """

    def setUp(self):
        super().setUp()
        self.first = _render(FIRST_IDENTITY)
        self.second = _render(SECOND_IDENTITY)

    def test_same_number_of_artifacts_either_identity(self):
        """The pairing below is positional. If the two renders ever produced
        a different number of artifacts, that would mean identity itself
        changes *which* artifacts exist, not just what some of them are
        named -- a bigger claim this test does not make and is not built to
        check. Asserted up front so a future change that broke this
        assumption fails here, legibly, rather than via a silent `zip`
        truncation hiding artifacts off the shorter list's end.
        """
        self.assertEqual(len(self.first), len(self.second))

    def test_every_artifact_whose_path_moved_also_changed_its_id(self):
        moved_without_a_new_id = [
            (before.id, after.id, before.path, after.path)
            for before, after in zip(self.first, self.second)
            if before.path != after.path and before.id == after.id
        ]
        self.assertEqual(
            moved_without_a_new_id,
            [],
            "an artifact's rendered path depends on identity, but its id does not -- "
            "the planner would see the same id at a new address and never notice the old "
            "file is now orphaned",
        )

    def test_the_real_catalog_has_at_least_one_identity_derived_artifact(self):
        """A guard against the check above passing only because nothing ever
        moves: if no artifact's path depended on identity, the previous test
        would pass vacuously and prove nothing. The shipped system prompt and
        the OpenCode adapter's own bundled assets are identity-derived today,
        so this must find at least one.
        """
        moved = [
            before.path
            for before, after in zip(self.first, self.second)
            if before.path != after.path
        ]
        self.assertGreater(len(moved), 0)


if __name__ == "__main__":
    import unittest

    unittest.main()
