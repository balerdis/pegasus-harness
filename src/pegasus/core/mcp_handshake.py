"""The MCP `initialize` handshake: building the request, reading the answer.

JSON-RPC framing is not a platform detail the way launching a process is --
it is the same three lines of dict-shaping regardless of which OS or which
`MCPProcess` ran the command -- so it lives here, pure, next to the
classification that turns one `MCPExchange` into a verdict a report can show.
Only `MCPProcess.exchange` itself touches a real process.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from pegasus.ports.mcp_process import MCPExchange, MCPProcess

PROTOCOL_VERSION = "2024-11-05"
CLIENT_NAME = "pegasus-doctor"
CLIENT_VERSION = "1"
REQUEST_ID = 1

DEFAULT_TIMEOUT_SECONDS = 5.0

STATUS_OK = "ok"
STATUS_TIMEOUT = "timeout"
STATUS_EXITED = "exited"
STATUS_INVALID = "invalid"
STATUS_NOT_FOUND = "not-found"


@dataclass(frozen=True)
class ServerCheck:
    """One server's verdict, in words a `doctor` report can show as-is."""

    id: str
    status: str
    detail: str


def initialize_request() -> str:
    """The one JSON-RPC line every check sends: an `initialize` call, nothing else."""
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": REQUEST_ID,
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": CLIENT_NAME, "version": CLIENT_VERSION},
            },
        }
    )


def check_server(
    server_id: str, command: tuple[str, ...], process: MCPProcess, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
) -> ServerCheck:
    """Launch `command` through `process` and classify what came back."""
    exchange = process.exchange(command, initialize_request(), timeout_seconds)
    return _classify(server_id, exchange)


def _classify(server_id: str, exchange: MCPExchange) -> ServerCheck:
    if exchange.spawn_error is not None:
        return ServerCheck(server_id, STATUS_NOT_FOUND, f"could not start: {exchange.spawn_error}")
    if exchange.timed_out:
        return ServerCheck(server_id, STATUS_TIMEOUT, "started, but never answered before the timeout")
    if exchange.line is None:
        return ServerCheck(
            server_id, STATUS_EXITED, f"exited before answering (exit code {exchange.exit_code})"
        )
    protocol_version = _protocol_version(exchange.line)
    if protocol_version is None:
        return ServerCheck(server_id, STATUS_INVALID, "answered, but not with a valid MCP initialize result")
    return ServerCheck(server_id, STATUS_OK, f"handshake ok, protocol {protocol_version}")


def _protocol_version(line: str) -> str | None:
    """The `protocolVersion` a well-formed `initialize` result names, or `None`
    for anything that is not one -- malformed JSON, the wrong request id, a
    result missing the fields a real MCP server always sends."""
    try:
        document = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(document, dict) or document.get("jsonrpc") != "2.0" or document.get("id") != REQUEST_ID:
        return None
    result = document.get("result")
    if not isinstance(result, dict):
        return None
    protocol_version = result.get("protocolVersion")
    server_info = result.get("serverInfo")
    if not isinstance(protocol_version, str) or not isinstance(server_info, dict):
        return None
    return protocol_version
