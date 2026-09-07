"""Behavioural proof that `cli.py`'s user-facing prose never leaks the
engine's own brand.

Every other test in this suite builds a `Runtime` with no `identity=`
argument at all, which means it silently gets Pegasus's own packaged
`identity.json` back (`Runtime.identity`'s default factory) -- so none of
them can ever notice a stray `"Pegasus"` literal sitting in `cli.py`'s
prose: the fixture and the bug would say the same word by coincidence.

This module builds an obviously-fictional `Identity` (`ACME`, never a real
organization) and drives every top-level command path through it, then
greps the rendered output -- prose and machine-readable report alike -- for
the engine's own brand. A distribution binary is exactly this scenario: its
own packaged `identity.json` is never `pegasus`/`Pegasus`/`Harness`, so if
any of these code paths still says so, a real distribution's user reads a
sentence naming a product they never installed.

The wire-format identifiers that are deliberately identical across every
distribution (`cli.SCHEMA`, `journal-v4.json`, the `pegasus_version`/
`pegasus_installed` JSON *keys*, `PEGASUS_SKILL_REGISTRY_BIN`,
`PEGASUS_SKILL_ROOTS`, `PEGASUS_NO_UPDATE_CHECK`, and
`mcp_handshake.CLIENT_NAME`) are explicitly excluded before the brand check,
since those are supposed to say "pegasus" everywhere, forever.
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
from pegasus.infra.fs_posix import PosixFileSystem
from real_home import RealHomeTestCase as _RealHomeTestCase

AT = "2026-08-14T00:00:00+00:00"
CLI = available().ids()[0]
NO_BINARY = {"PATH": ""}

#: An obviously fictional product -- never a real organization -- so a leak
#: cannot be mistaken for a coincidental match against real-world prose.
ACME_IDENTITY = Identity(
    product_id="acme-widget",
    display_name="Acme",
    program_name="acme",
    version="1.0.0",
    wordmark_words=("ACME",),
    release=ReleaseSource(
        asset_url_template="https://github.com/acme-corp/acme-widget/releases/download/{tag}/{asset}",
        binary_asset="acme-widget",
        latest_release_api_url="https://api.github.com/repos/acme-corp/acme-widget/releases/latest",
        release_page_url="https://github.com/acme-corp/acme-widget/releases",
        install_base_url_default="https://github.com/acme-corp/acme-widget/releases/latest/download",
    ),
)

#: Wire identifiers permitted everywhere, per the spec's own allowlist --
#: stripped out of rendered text before the brand check runs, since some of
#: them contain the brand substring by design (e.g. `pegasus_installed`).
PERMITTED_WIRE_IDENTIFIERS = (
    cli.SCHEMA,
    "journal-v4.json",
    "pegasus_version",
    "pegasus_installed",
    "PEGASUS_SKILL_REGISTRY_BIN",
    "PEGASUS_SKILL_ROOTS",
    "PEGASUS_NO_UPDATE_CHECK",
    "pegasus-doctor",
)


def _scrub_wire_identifiers(text: str) -> str:
    scrubbed = text
    for token in PERMITTED_WIRE_IDENTIFIERS:
        scrubbed = scrubbed.replace(token, "")
    return scrubbed


class BrandAssertionMixin:
    def assertNoEngineBrand(self, text: str) -> None:
        scrubbed = _scrub_wire_identifiers(text).lower()
        for brand in ("pegasus", "harness"):
            self.assertNotIn(brand, scrubbed, f"engine brand {brand!r} leaked in: {text!r}")


class AcmeRuntimeTestCase(BrandAssertionMixin, _RealHomeTestCase):
    """A throwaway home, the real filesystem, and ACME's identity instead of
    Pegasus's own -- everything else follows the same discipline
    `test_cli.py`'s own `RealHomeTestCase` holds every CLI surface test to.
    """

    def setUp(self):
        super().setUp()
        # The base class's own `self.filesystem` is keyed to Pegasus's own
        # product id; a distribution's binary would never share that, so this
        # rebuilds it keyed to ACME's instead, matching what `default_runtime`
        # would actually do for a real ACME build.
        self.filesystem = PosixFileSystem(product_id=ACME_IDENTITY.product_id)

    def runtime(self) -> cli.Runtime:
        return cli.Runtime(
            filesystem=self.filesystem,
            home=self.home,
            now=AT,
            out=io.StringIO(),
            variables=NO_BINARY,
            identity=ACME_IDENTITY,
        )

    def layout(self):
        return available().get(CLI).layout(Environment(home=self.home))

    def present(self) -> None:
        self.layout().config_dir.mkdir(parents=True, exist_ok=True)

    def store(self):
        return cli.journal_store(self.runtime())

    def run_cli(self, *argv) -> tuple[int, dict]:
        context = self.runtime()
        code = cli.main([*argv, "--json"], runtime=context)
        return code, json.loads(context.out.getvalue())

    def run_prose(self, *argv) -> tuple[int, str]:
        context = self.runtime()
        code = cli.main(list(argv), runtime=context)
        return code, context.out.getvalue()

    def install(self, *extra) -> None:
        self.present()
        code, _ = self.run_cli("install", "--cli", CLI, *extra)
        self.assertEqual(code, 0)

    def drop_mcp_bindings(self) -> None:
        journal = self.store().load()
        install = journal_module.install_for(journal, CLI)
        self.store().save(journal_module.with_install(journal, replace(install, mcp_bindings={})))


class InstallBrandLeakTest(AcmeRuntimeTestCase):
    def test_install_prose_has_no_engine_brand(self):
        self.present()
        _code, prose = self.run_prose("install", "--cli", CLI)
        self.assertNoEngineBrand(prose)

    def test_install_json_report_has_no_engine_brand(self):
        """Scoped to the fields `cli.py` itself renders (`schema`, `journal`,
        `activation`) -- not `created`/`updated`, which name catalog content
        (skill/prompt filenames) that is a separate concern from this
        module's identity sweep and out of scope here."""
        self.present()
        _code, report = self.run_cli("install", "--cli", CLI)
        self.assertNoEngineBrand(report["schema"])
        self.assertNoEngineBrand(report["journal"])
        self.assertNoEngineBrand(" ".join(report["activation"]))

    def test_dropped_grant_warning_has_no_engine_brand(self):
        """Covers the `pegasus mcp grant --cli ...` suggested-command literal
        that used to live inside `install`'s own `grant_warnings` message."""
        self.install()
        self.declare_own_mcp_server("jira-mcp")
        self.run_cli("mcp", "grant", "--cli", CLI, "jira-mcp")
        _code, report = self.run_cli("install", "--cli", CLI, "--mcp", "cbm=jira-mcp")
        self.assertTrue(report.get("grant_warnings"))
        self.assertNoEngineBrand(" ".join(report["grant_warnings"]))

    def declare_own_mcp_server(self, key: str) -> None:
        from pegasus.core import codecs, pointer
        from pegasus.core.types import Codec

        layout = self.layout()
        document = codecs.loads(Codec.JSON, layout.settings_file.read_text(encoding="utf-8"))
        document = pointer.set_at(document, f"/mcp/{key}", {"type": "local", "command": ["jira-server"]})
        layout.settings_file.write_text(codecs.dumps(Codec.JSON, document), encoding="utf-8")


class UninstallBrandLeakTest(AcmeRuntimeTestCase):
    def test_not_installed_error_has_no_engine_brand(self):
        self.present()
        _code, report = self.run_cli("uninstall", "--cli", CLI)
        self.assertEqual(report["status"], "failed")
        self.assertNoEngineBrand(report["error"])

    def test_uninstall_prose_has_no_engine_brand(self):
        self.install()
        _code, prose = self.run_prose("uninstall", "--cli", CLI)
        self.assertNoEngineBrand(prose)


class McpBrandLeakTest(AcmeRuntimeTestCase):
    def test_grant_undeclared_key_error_has_no_engine_brand(self):
        self.install()
        _code, report = self.run_cli("mcp", "grant", "--cli", CLI, "no-such-key")
        self.assertEqual(report["status"], "failed")
        self.assertNoEngineBrand(report["error"])

    def test_unresolved_binding_blocks_list_with_no_engine_brand(self):
        """Covers `install_command_for` and `_unresolved_bindings_message`,
        both of which used to hardcode the `pegasus install --cli ...`
        remedy command verbatim."""
        self.present()
        code, _ = self.run_cli("install", "--cli", CLI, "--mcp", "cbm=acme-widget-key")
        self.assertEqual(code, 0)
        self.drop_mcp_bindings()
        _code, report = self.run_cli("mcp", "list", "--cli", CLI)
        self.assertTrue(report["blocked"])
        self.assertIn("cbm", report["blocked"])
        self.assertNoEngineBrand(report["blocked"])

    def test_unresolved_binding_blocks_update_with_no_engine_brand(self):
        self.present()
        code, _ = self.run_cli("install", "--cli", CLI, "--mcp", "cbm=acme-widget-key")
        self.assertEqual(code, 0)
        self.drop_mcp_bindings()
        _code, report = self.run_cli("update", "--cli", CLI)
        self.assertNotEqual(_code, 0)
        self.assertNoEngineBrand(report["error"])


class DoctorBrandLeakTest(AcmeRuntimeTestCase):
    def test_not_installed_prose_has_no_engine_brand(self):
        """Covers `_cli_prose`'s "Pegasus not installed" literal."""
        self.present()
        _code, prose = self.run_prose("doctor")
        self.assertNoEngineBrand(prose)

    def test_installed_prose_has_no_engine_brand(self):
        self.install()
        _code, prose = self.run_prose("doctor")
        self.assertNoEngineBrand(prose)

    def test_bound_server_detail_has_no_engine_brand(self):
        """Covers `_bound_checks`'s "whose tools Pegasus grants" literal."""
        self.present()
        code, _ = self.run_cli("install", "--cli", CLI, "--mcp", "cbm=acme-widget-key")
        self.assertEqual(code, 0)
        _code, report = self.run_cli("doctor")
        entry = next(item for item in report["clis"] if item["cli"] == CLI)
        self.assertTrue(entry["mcp_bound"])
        self.assertNoEngineBrand(entry["mcp_bound"][0]["detail"])

    def test_bound_server_detail_with_unknown_key_has_no_engine_brand(self):
        self.present()
        code, _ = self.run_cli("install", "--cli", CLI, "--mcp", "cbm=acme-widget-key")
        self.assertEqual(code, 0)
        self.drop_mcp_bindings()
        _code, report = self.run_cli("doctor")
        entry = next(item for item in report["clis"] if item["cli"] == CLI)
        self.assertTrue(entry["mcp_bound"])
        self.assertNoEngineBrand(entry["mcp_bound"][0]["detail"])
        self.assertTrue(entry.get("mcp_bound_unknown_keys"))
        self.assertNoEngineBrand(entry["mcp_bound_unknown_keys"]["command"])


class RestoreBrandLeakTest(AcmeRuntimeTestCase):
    def test_no_snapshot_error_has_no_engine_brand(self):
        self.present()
        _code, report = self.run_cli("restore")
        self.assertEqual(report["status"], "failed")
        self.assertNoEngineBrand(report["error"])

    def test_restore_prose_has_no_engine_brand(self):
        self.install()
        _code, prose = self.run_prose("restore")
        self.assertNoEngineBrand(prose)


class UpdateBrandLeakTest(AcmeRuntimeTestCase):
    def test_update_prose_has_no_engine_brand(self):
        self.install()
        _code, prose = self.run_prose("update", "--cli", CLI)
        self.assertNoEngineBrand(prose)


class ModelsBrandLeakTest(AcmeRuntimeTestCase):
    AGENT = "sdd-apply"

    def test_models_set_activation_note_has_no_engine_brand(self):
        """Covers `_NOT_INSTALLED_YET`'s "pegasus install --cli ..." literal."""
        _code, report = self.run_cli(
            "models", "set", "--cli", CLI, "--agent", self.AGENT, "--model", "anthropic/claude-sonnet-5",
        )
        self.assertNoEngineBrand(" ".join(report["activation"]))

    def test_models_unset_activation_note_has_no_engine_brand(self):
        self.run_cli(
            "models", "set", "--cli", CLI, "--agent", self.AGENT, "--model", "anthropic/claude-sonnet-5",
        )
        _code, report = self.run_cli("models", "unset", "--cli", CLI, "--agent", self.AGENT)
        self.assertNoEngineBrand(" ".join(report["activation"]))


class UpgradeBrandLeakTest(AcmeRuntimeTestCase):
    def test_not_an_installed_executable_error_has_no_engine_brand(self):
        _code, report = self.run_cli("upgrade")
        self.assertEqual(report["status"], "failed")
        self.assertNoEngineBrand(report["error"])
