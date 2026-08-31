"""Building the `initialize` request and classifying what came back.

Pure framing and classification, proven against `FakeMCPProcess` -- no real
process, no real network, nothing platform-specific. What actually launches
a process is proven separately, in `test_mcp_process_subprocess.py`, against
fixture scripts.
"""
from __future__ import annotations

import json
import unittest

from fakes import FakeMCPProcess

from pegasus.core import mcp_handshake
from pegasus.ports.mcp_process import MCPExchange

COMMAND = ("fixture", "--stdio")


class InitializeRequestTest(unittest.TestCase):
    def test_the_request_is_a_well_formed_jsonrpc_initialize_call(self):
        document = json.loads(mcp_handshake.initialize_request())
        self.assertEqual(document["jsonrpc"], "2.0")
        self.assertEqual(document["method"], "initialize")
        self.assertEqual(document["id"], mcp_handshake.REQUEST_ID)
        self.assertEqual(document["params"]["protocolVersion"], mcp_handshake.PROTOCOL_VERSION)


class CheckServerTest(unittest.TestCase):
    def check(self, exchange: MCPExchange) -> mcp_handshake.ServerCheck:
        process = FakeMCPProcess(exchanges={COMMAND: exchange})
        return mcp_handshake.check_server("probe", COMMAND, process, timeout_seconds=1)

    def test_a_correct_handshake_is_reported_ok(self):
        line = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": mcp_handshake.REQUEST_ID,
                "result": {"protocolVersion": "2024-11-05", "serverInfo": {"name": "x", "version": "1"}},
            }
        )
        check = self.check(MCPExchange(line=line, exit_code=0, timed_out=False, spawn_error=None))
        self.assertEqual(check.status, mcp_handshake.STATUS_OK)

    def test_a_command_that_could_not_start_is_reported_not_found(self):
        check = self.check(
            MCPExchange(line=None, exit_code=None, timed_out=False, spawn_error="No such file or directory")
        )
        self.assertEqual(check.status, mcp_handshake.STATUS_NOT_FOUND)

    def test_a_silent_server_is_reported_as_a_timeout(self):
        check = self.check(MCPExchange(line=None, exit_code=None, timed_out=True, spawn_error=None))
        self.assertEqual(check.status, mcp_handshake.STATUS_TIMEOUT)

    def test_a_server_that_exits_before_answering_is_reported_exited(self):
        check = self.check(MCPExchange(line=None, exit_code=3, timed_out=False, spawn_error=None))
        self.assertEqual(check.status, mcp_handshake.STATUS_EXITED)
        self.assertIn("3", check.detail)

    def test_a_response_that_is_not_valid_mcp_is_reported_invalid(self):
        check = self.check(
            MCPExchange(line="not json at all", exit_code=0, timed_out=False, spawn_error=None)
        )
        self.assertEqual(check.status, mcp_handshake.STATUS_INVALID)

    def test_valid_json_missing_the_mcp_result_shape_is_still_invalid(self):
        line = json.dumps({"jsonrpc": "2.0", "id": mcp_handshake.REQUEST_ID, "result": {}})
        check = self.check(MCPExchange(line=line, exit_code=0, timed_out=False, spawn_error=None))
        self.assertEqual(check.status, mcp_handshake.STATUS_INVALID)

    def test_a_spawn_errors_detail_carries_nothing_this_module_added(self):
        check = self.check(
            MCPExchange(line=None, exit_code=None, timed_out=False, spawn_error="[Errno 2] No such file")
        )
        self.assertEqual(check.detail, "could not start: [Errno 2] No such file")


if __name__ == "__main__":
    unittest.main()
