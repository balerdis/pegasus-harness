"""`doctor --start-mcp-servers`: launching each configured server for real.

`DoctorTest` in `test_cli.py` already proves `doctor` reads only; this file
is just the flag that changes that. Branch coverage (remote skipped,
malformed entry, handshake outcomes) uses `FakeMCPProcess`; one test uses
the real `SubprocessMCPProcess` against the fixture server, to prove the
wiring launches a real process and not just a double.
"""
from __future__ import annotations

import io
import json
import sys
from dataclasses import replace
from pathlib import Path

from fakes import FakeMCPProcess
from pegasus import cli
from pegasus.adapters import available
from pegasus.core import journal as journal_module
from pegasus.core import mcp_handshake, ownership
from pegasus.core.types import Environment
from pegasus.infra.mcp_process_subprocess import SubprocessMCPProcess
from pegasus.ports.mcp_process import MCPExchange
from real_home import RealHomeTestCase as _RealHomeTestCase

AT = "2026-08-14T00:00:00+00:00"
CLI = available().ids()[0]
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mcp_servers" / "fixture_server.py"


class RealHomeTestCase(_RealHomeTestCase):
    """The real `PosixFileSystem`, against a throwaway home -- the same
    discipline `test_cli.py` holds every CLI surface test to."""

    def runtime(self, *, mcp_process=None, timeout_seconds: float = 5) -> cli.Runtime:
        return cli.Runtime(
            filesystem=self.filesystem,
            home=self.home,
            now=AT,
            out=io.StringIO(),
            variables={"PATH": ""},
            mcp_process=mcp_process or FakeMCPProcess(),
            mcp_handshake_timeout_seconds=timeout_seconds,
        )

    def layout(self):
        return available().get(CLI).layout(Environment(home=self.home))

    def present(self) -> None:
        self.layout().config_dir.mkdir(parents=True, exist_ok=True)

    def store(self):
        return cli.journal_store(self.runtime())


class DoctorStartMcpServersTest(RealHomeTestCase):
    def run_doctor(self, *, mcp_process=None, timeout_seconds: float = 5, start: bool = True) -> dict:
        context = self.runtime(mcp_process=mcp_process, timeout_seconds=timeout_seconds)
        argv = ["doctor", "--json"] + (["--start-mcp-servers"] if start else [])
        code = cli.main(argv, runtime=context)
        self.assertEqual(code, cli.OK)
        return json.loads(context.out.getvalue())

    def install(self) -> None:
        self.present()
        code = cli.main(["install", "--cli", CLI, "--json"], runtime=self.runtime())
        self.assertEqual(code, cli.OK)

    def claim_mcp_entry(self, name: str, value: dict) -> None:
        """The same shape `install --mcp` itself would leave: a value at
        `/mcp/<name>` in the config, claimed in the journal."""
        from pegasus.core import codecs, pointer
        from pegasus.core.types import Codec

        layout = self.layout()
        document = codecs.loads(Codec.JSON, layout.settings_file.read_text(encoding="utf-8"))
        document = pointer.set_at(document, f"/mcp/{name}", value)
        layout.settings_file.write_text(codecs.dumps(Codec.JSON, document), encoding="utf-8")

        store = self.store()
        journal = store.load()
        install = journal_module.install_for(journal, CLI)
        claimed = journal_module.Record(
            id=f"mcp:{name}",
            kind="config-key",
            target=layout.settings_file,
            after_digest=ownership.digest_of_value(value),
            created_at=AT,
            pointer=f"/mcp/{name}",
        )
        grown = replace(install, entries=(*install.entries, claimed))
        store.save(journal_module.with_install(journal, grown))

    def entry(self, report: dict) -> dict:
        return next(item for item in report["clis"] if item["cli"] == CLI)

    def test_the_flag_is_off_by_default(self):
        self.install()
        report = self.run_doctor(start=False)
        self.assertNotIn("mcp_servers", self.entry(report))

    def test_no_servers_configured_reports_an_empty_list(self):
        self.install()
        report = self.run_doctor()
        self.assertEqual(self.entry(report)["mcp_servers"], [])

    def test_a_bound_server_is_named_rather_than_passed_over_in_silence(self):
        """A bound server writes no `/mcp/<id>` key, only its convention.

        `_mcp_entries` looks for the key, so a bound server is invisible to
        this check — and an install whose only servers are bound reports "No
        MCP servers configured", which is not a gap in the report but a false
        statement about the machine. What can honestly be said is that the
        server is the user's own: Pegasus grants its tools and ships its
        convention, and neither installs nor starts it. Which key it was bound
        to is deliberately not claimed here — the journal never recorded it,
        and a report inventing the answer would be the same kind of falsehood
        this test exists to remove.
        """
        self.present()
        code = cli.main(
            ["install", "--cli", CLI, "--mcp", "cbm=codebase-memory-mcp", "--json"], runtime=self.runtime()
        )
        self.assertEqual(code, cli.OK)
        servers = self.entry(self.run_doctor())["mcp_servers"]
        self.assertEqual([check["id"] for check in servers], ["cbm"])
        self.assertEqual(servers[0]["status"], "bound")
        self.assertIn("administered by you", servers[0]["detail"])

    def test_a_remote_server_is_reported_but_never_launched(self):
        self.install()
        self.claim_mcp_entry("context7", {"type": "remote", "url": "https://example.invalid", "enabled": True})
        report = self.run_doctor()
        [check] = self.entry(report)["mcp_servers"]
        self.assertEqual(check["status"], "remote")

    def test_a_malformed_local_entry_is_reported_invalid(self):
        self.install()
        self.claim_mcp_entry("broken", {"type": "local", "enabled": True})
        report = self.run_doctor()
        [check] = self.entry(report)["mcp_servers"]
        self.assertEqual(check["status"], "invalid")

    def test_a_correct_handshake_is_reported_ok(self):
        self.install()
        command = ["fake-server"]
        self.claim_mcp_entry("engram", {"type": "local", "command": command, "enabled": True})
        line = (
            '{"jsonrpc": "2.0", "id": 1, "result": '
            '{"protocolVersion": "2024-11-05", "serverInfo": {"name": "x", "version": "1"}}}'
        )
        process = FakeMCPProcess(
            exchanges={tuple(command): MCPExchange(line=line, exit_code=0, timed_out=False, spawn_error=None)}
        )
        report = self.run_doctor(mcp_process=process)
        [check] = self.entry(report)["mcp_servers"]
        self.assertEqual(check["status"], "ok")
        self.assertEqual(check["id"], "engram")

    def test_a_spawn_error_never_leaks_the_environment_into_the_report(self):
        self.install()
        command = ["fake-server"]
        self.claim_mcp_entry("engram", {"type": "local", "command": command, "enabled": True})
        secret = "sk-super-secret-token"
        process = FakeMCPProcess(
            exchanges={
                tuple(command): MCPExchange(
                    line=None, exit_code=None, timed_out=False, spawn_error="No such file or directory"
                )
            }
        )
        context = self.runtime(mcp_process=process)
        context = replace(context, variables={**context.variables, "SOME_MCP_TOKEN": secret})
        code = cli.main(["doctor", "--json", "--start-mcp-servers"], runtime=context)
        self.assertEqual(code, cli.OK)
        self.assertNotIn(secret, context.out.getvalue())

    def test_the_wiring_launches_a_real_process_not_only_a_double(self):
        self.install()
        command = [sys.executable, str(FIXTURE), "ok"]
        self.claim_mcp_entry("engram", {"type": "local", "command": command, "enabled": True})
        report = self.run_doctor(mcp_process=SubprocessMCPProcess())
        [check] = self.entry(report)["mcp_servers"]
        self.assertEqual(check["status"], mcp_handshake.STATUS_OK)
