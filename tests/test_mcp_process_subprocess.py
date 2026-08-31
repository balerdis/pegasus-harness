"""The real launch, against fixture scripts instead of a real MCP server.

`tests/no_network.py` keeps the whole suite off the network; nothing here
reaches out either. It spawns a real, local, throwaway process --
`tests/fixtures/mcp_servers/fixture_server.py`, run with this same
interpreter -- so the launch-and-handshake path Pegasus owns is proven
against something real, without the suite depending on `engram` or any
other shipped server. Whether a real server speaks correctly is a question
only a live run on a test account answers.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

from pegasus.core import mcp_handshake
from pegasus.infra.mcp_process_subprocess import SubprocessMCPProcess

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mcp_servers" / "fixture_server.py"


def command(*args: str) -> tuple[str, ...]:
    return (sys.executable, str(FIXTURE), *args)


class SubprocessMCPProcessTest(unittest.TestCase):
    def setUp(self):
        self.process = SubprocessMCPProcess()

    def test_a_correct_handshake_produces_the_servers_line(self):
        exchange = self.process.exchange(command("ok"), mcp_handshake.initialize_request(), timeout_seconds=5)
        self.assertFalse(exchange.timed_out)
        self.assertIsNone(exchange.spawn_error)
        document = json.loads(exchange.line)
        self.assertEqual(document["result"]["protocolVersion"], "2024-11-05")

    def test_check_server_reports_ok_end_to_end(self):
        check = mcp_handshake.check_server("probe", command("ok"), self.process, timeout_seconds=5)
        self.assertEqual(check.status, mcp_handshake.STATUS_OK)

    def test_a_missing_command_never_becomes_a_process(self):
        missing = (str(FIXTURE.parent / "this-binary-does-not-exist"),)
        check = mcp_handshake.check_server("probe", missing, self.process, timeout_seconds=5)
        self.assertEqual(check.status, mcp_handshake.STATUS_NOT_FOUND)

    def test_a_server_that_exits_immediately_is_reported_exited(self):
        check = mcp_handshake.check_server("probe", command("exit", "7"), self.process, timeout_seconds=5)
        self.assertEqual(check.status, mcp_handshake.STATUS_EXITED)
        self.assertIn("7", check.detail)

    def test_a_response_that_is_not_mcp_is_reported_invalid(self):
        check = mcp_handshake.check_server("probe", command("garbage"), self.process, timeout_seconds=5)
        self.assertEqual(check.status, mcp_handshake.STATUS_INVALID)

    def test_a_silent_server_times_out_instead_of_hanging(self):
        start = time.monotonic()
        check = mcp_handshake.check_server("probe", command("silent"), self.process, timeout_seconds=0.3)
        elapsed = time.monotonic() - start
        self.assertEqual(check.status, mcp_handshake.STATUS_TIMEOUT)
        # Generous margin over the 0.3s deadline: this proves the call
        # returned promptly, not that it is fast to the millisecond.
        self.assertLess(elapsed, 5)

    def test_a_timed_out_child_is_actually_killed_not_abandoned(self):
        with tempfile.TemporaryDirectory() as directory:
            pid_file = Path(directory) / "pid"
            exchange = self.process.exchange(
                command("silent", str(pid_file)), mcp_handshake.initialize_request(), timeout_seconds=0.3
            )
            self.assertTrue(exchange.timed_out)
            pid = int(pid_file.read_text())
            # The fixture is asked to sleep 60s; if it is still alive shortly
            # after `exchange` returned, it was abandoned rather than killed.
            time.sleep(0.3)
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)


if __name__ == "__main__":
    unittest.main()
