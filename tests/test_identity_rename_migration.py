"""Renaming an on-disk artifact by switching `Identity` is, to the planner, the
same shape as retiring one artifact and creating another: an artifact's `id`
carries its filename, `planner.retirements` marks any journal entry whose `id`
is absent from the new render as stale, and `install` (which `update`
delegates to) retires those entries after applying the new ones and before
saving the journal.

This is the end-to-end proof that the identity-derived OpenCode artifacts this
module renames (the skill-registry subtree and its binary and module, the
system prompt, and the local plugin files) actually migrate cleanly when a
machine's installed identity changes -- against a real, throwaway `$HOME` and
the real POSIX filesystem, never the in-memory fake: the migration is a real
filesystem event (an old file gone, a new one created, an emptied directory
removed), and nothing about the in-memory double can tell a rename-away from a
rename-into the way a real directory listing can.
"""
from __future__ import annotations

import io
import json
from dataclasses import replace

from pegasus import cli
from pegasus.adapters import available
from pegasus.core import journal as journal_module
from pegasus.core.identity import Identity, ReleaseSource
from pegasus.core.types import Environment
from real_home import RealHomeTestCase as _RealHomeTestCase

AT = "2026-08-14T00:00:00+00:00"
CLI = available().ids()[0]
NO_BINARY = {"PATH": ""}


def _identity(program_name: str, display_name: str) -> Identity:
    return Identity(
        product_id=f"{program_name}-widget",
        display_name=display_name,
        program_name=program_name,
        version="1.0.0",
        wordmark_words=(display_name.upper(),),
        release=ReleaseSource(
            asset_url_template=f"https://example.invalid/{program_name}/releases/download/{{tag}}/{{asset}}",
            binary_asset=program_name,
            latest_release_api_url=f"https://example.invalid/{program_name}/api/releases/latest",
            release_page_url=f"https://example.invalid/{program_name}/releases",
            install_base_url_default=f"https://example.invalid/{program_name}/releases/latest/download",
        ),
    )


#: Two obviously fictional, distinct distributions of the same engine -- never
#: real organizations -- so a rename between them cannot be mistaken for
#: targeting or endorsing one.
FIRST_IDENTITY = _identity("acme", "Acme")
SECOND_IDENTITY = _identity("zenith", "Zenith")


class RealHomeTestCase(_RealHomeTestCase):
    def runtime(self, identity: Identity) -> cli.Runtime:
        return cli.Runtime(
            filesystem=self.filesystem, home=self.home, now=AT, out=io.StringIO(), variables=NO_BINARY, identity=identity
        )

    def layout(self):
        return available().get(CLI).layout(Environment(home=self.home))

    def present(self) -> None:
        self.layout().config_dir.mkdir(parents=True, exist_ok=True)

    def run_cli(self, identity: Identity, *argv) -> tuple[int, dict]:
        context = self.runtime(identity)
        code = cli.main([*argv, "--json"], runtime=context)
        return code, json.loads(context.out.getvalue())

    def journal(self):
        store = cli.journal_store(self.runtime(FIRST_IDENTITY))
        return journal_module.install_for(store.load(), CLI)

    def rewrite_journal_id(self, old_id: str, new_id: str) -> None:
        """Simulate a journal written by a release before an `id`'s derivation
        changed: same address, same digest, only the `id` predates the
        change. This is exactly what every pre-existing installation's own
        journal looks like the moment a new release ships such a change --
        nothing else about the file on disk or the journal entry differs."""
        store = cli.journal_store(self.runtime(FIRST_IDENTITY))
        journal = store.load()
        install = journal_module.install_for(journal, CLI)
        renamed = tuple(
            replace(entry, id=new_id) if entry.id == old_id else entry for entry in install.entries
        )
        store.save(journal_module.with_install(journal, replace(install, entries=renamed)))


class RenamingTheInstalledIdentityMigratesArtifactsTest(RealHomeTestCase):
    def setUp(self):
        super().setUp()
        self.present()
        code, _ = self.run_cli(FIRST_IDENTITY, "install", "--cli", CLI)
        self.assertEqual(code, cli.OK)
        self.config = self.layout().config_dir

        code, self.update_report = self.run_cli(SECOND_IDENTITY, "update", "--cli", CLI)
        self.assertEqual(code, cli.OK, self.update_report)

    def test_the_old_identitys_system_prompt_is_gone(self):
        self.assertFalse((self.config / "acme-AGENTS.md").exists())

    def test_the_new_identitys_system_prompt_exists(self):
        self.assertTrue((self.config / "zenith-AGENTS.md").is_file())

    def test_the_old_identitys_skill_registry_subtree_is_gone(self):
        self.assertFalse((self.config / "acme" / "skill-registry" / "acme-skill-registry").exists())
        self.assertFalse((self.config / "acme" / "skill-registry" / "acme_skill_registry.py").exists())

    def test_the_new_identitys_skill_registry_subtree_exists(self):
        binary = self.config / "zenith" / "skill-registry" / "zenith-skill-registry"
        module = self.config / "zenith" / "skill-registry" / "zenith_skill_registry.py"
        self.assertTrue(binary.is_file())
        self.assertTrue(module.is_file())

    def test_the_old_identitys_emptied_directory_is_pruned_not_left_behind(self):
        """The sibling fact this same rename exposes: `acme/skill-registry`
        loses its only two files to the rename above, which empties
        `acme/skill-registry` and then `acme` itself -- and pruning an emptied
        directory left behind by a retirement is exactly what the directory-
        pruning fix this change ships alongside already does for any
        retirement, not something this rename adds a new mechanism for.
        """
        self.assertFalse((self.config / "acme" / "skill-registry").exists())
        self.assertFalse((self.config / "acme").exists())

    def test_the_old_identitys_local_plugins_are_gone(self):
        plugins = self.config / "plugins"
        self.assertFalse((plugins / "acme-skill-registry.ts").exists())
        self.assertFalse((plugins / "acme-orchestrator-notifier.ts").exists())
        self.assertFalse((plugins / "acme-zellij-state.ts").exists())
        self.assertFalse((plugins / "acme-apply-patch-scope.ts").exists())

    def test_the_new_identitys_local_plugins_exist(self):
        plugins = self.config / "plugins"
        self.assertTrue((plugins / "zenith-skill-registry.ts").is_file())
        self.assertTrue((plugins / "zenith-orchestrator-notifier.ts").is_file())
        self.assertTrue((plugins / "zenith-zellij-state.ts").is_file())
        self.assertTrue((plugins / "zenith-apply-patch-scope.ts").is_file())

    def test_the_old_identitys_skill_registry_contract_is_gone(self):
        self.assertFalse((self.config / "acme-skill-registry.env").exists())

    def test_the_new_identitys_skill_registry_contract_exists(self):
        self.assertTrue((self.config / "zenith-skill-registry.env").is_file())

    def test_the_journal_no_longer_claims_any_old_identity_artifact(self):
        install = self.journal()
        self.assertIsNotNone(install)
        ids = {entry.id for entry in install.entries}
        targets = {str(entry.target) for entry in install.entries}
        for stale in ("acme-AGENTS.md", "acme-skill-registry", "acme_skill_registry.py", "acme-skill-registry.env"):
            self.assertFalse(any(stale in item for item in ids), f"journal id still names {stale!r}: {ids}")
            self.assertFalse(
                any(stale in item for item in targets), f"journal target still names {stale!r}: {targets}"
            )

    def test_the_journal_claims_the_new_identitys_artifacts_instead(self):
        install = self.journal()
        self.assertIsNotNone(install)
        targets = {str(entry.target) for entry in install.entries}
        self.assertTrue(any("zenith-AGENTS.md" in item for item in targets))
        self.assertTrue(any("zenith-skill-registry" in item for item in targets))

    def test_the_update_report_retired_the_old_identitys_artifacts(self):
        retired_ids = {entry["id"] for entry in self.update_report["retired"]}
        self.assertTrue(
            any(entry_id.startswith("own:") for entry_id in retired_ids),
            f"no adapter-owned artifact was retired: {retired_ids}",
        )


class AnIdSchemeChangeOverTheSameAddressSurvivesUpdateTest(RealHomeTestCase):
    """The bug this module used to leave uncovered: `id` and address changing
    *together* (`acme` -> `zenith`, above) is not the shape every existing
    installation actually hits when a release changes how an `id` is derived.
    With the default identity the address never moves -- `pegasus-AGENTS.md`
    is `pegasus-AGENTS.md` before and after -- so what every already-installed
    machine's own journal looks like, the instant such a release ships, is
    exactly what `rewrite_journal_id` produces here: the *old* `id` sitting on
    the *current* address. `install -> update` on the *same* identity is the
    honest reproduction of that; `FIRST_IDENTITY`/`SECOND_IDENTITY` never
    enter into it.
    """

    def setUp(self):
        super().setUp()
        self.present()
        code, _ = self.run_cli(FIRST_IDENTITY, "install", "--cli", CLI)
        self.assertEqual(code, cli.OK)
        self.config = self.layout().config_dir
        self.system_prompt_path = self.config / f"{FIRST_IDENTITY.program_name}-AGENTS.md"
        self.assertTrue(self.system_prompt_path.is_file(), "fixture drifted: no system prompt was installed")
        self.system_prompt_content = self.system_prompt_path.read_bytes()

        # What every installation performed before the `id` started carrying
        # the filename actually has on disk in its journal today.
        self.rewrite_journal_id(f"system-prompt:{self.system_prompt_path.name}", "system-prompt")

        code, self.update_report = self.run_cli(FIRST_IDENTITY, "update", "--cli", CLI)
        self.assertEqual(code, cli.OK, self.update_report)

    def test_the_file_still_exists_with_the_correct_content(self):
        self.assertTrue(self.system_prompt_path.is_file())
        self.assertEqual(self.system_prompt_path.read_bytes(), self.system_prompt_content)

    def test_the_journal_reclaims_it_under_the_new_id(self):
        install = self.journal()
        self.assertIsNotNone(install)
        matching = [entry for entry in install.entries if entry.target == self.system_prompt_path]
        self.assertEqual(len(matching), 1, f"expected exactly one entry for {self.system_prompt_path}: {matching}")
        self.assertEqual(matching[0].id, f"system-prompt:{self.system_prompt_path.name}")

    def test_the_report_does_not_call_it_a_collision(self):
        self.assertEqual(self.update_report["skipped"], [])

    def test_the_report_does_not_call_it_retired(self):
        """The address survived, so nothing was actually taken back -- unlike
        the genuine `acme` -> `zenith` rename above, which does retire."""
        retired_targets = {entry["target"] for entry in self.update_report["retired"]}
        self.assertNotIn(str(self.system_prompt_path), retired_targets)


class AnyArtifactSurvivesAnIdChangeOverTheSameAddressTest(RealHomeTestCase):
    """The general case, deliberately independent of the system prompt: any
    catalog artifact whose `id` a future release derives differently, without
    moving the address it names, must survive an `update` the same way --
    this is what protects every future artifact, not only the one this
    specific defect happened to hit.

    `own:share` is used here only because it is an ordinary, non-appended
    `config-key` artifact with a stable, identity-independent `id` -- it never
    actually renames on its own. The `id` change is injected the same way
    `rewrite_journal_id` injects one for the system prompt above, standing in
    for whatever future release changes this artifact's own `id` scheme.
    """

    def setUp(self):
        super().setUp()
        self.present()
        code, _ = self.run_cli(FIRST_IDENTITY, "install", "--cli", CLI)
        self.assertEqual(code, cli.OK)
        self.settings_file = self.layout().settings_file
        self.settings_before = self.settings_file.read_bytes()

        self.rewrite_journal_id("own:share", "own:share:legacy-scheme")

        code, self.update_report = self.run_cli(FIRST_IDENTITY, "update", "--cli", CLI)
        self.assertEqual(code, cli.OK, self.update_report)

    def test_the_configuration_key_is_still_in_place(self):
        install = self.journal()
        self.assertIsNotNone(install)
        matching = [entry for entry in install.entries if entry.id == "own:share"]
        self.assertEqual(len(matching), 1, f"expected exactly one entry reclaimed as own:share: {matching}")
        self.assertNotIn("own:share:legacy-scheme", {entry.id for entry in install.entries})

    def test_the_report_does_not_call_it_a_collision(self):
        skipped_ids = {entry["id"] for entry in self.update_report["skipped"]}
        self.assertNotIn("own:share", skipped_ids)

    def test_the_settings_file_content_is_unchanged(self):
        """The value was already correct, so this is an `UNCHANGED` step,
        reconciled under the new id without a single byte rewritten."""
        self.assertEqual(self.settings_file.read_bytes(), self.settings_before)

