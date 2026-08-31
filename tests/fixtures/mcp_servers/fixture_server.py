#!/usr/bin/env python3
"""A fixture MCP server, driven by its first argument.

It ships inside the test tree, never inside the package, and it never
touches the network. It exists to let the suite exercise the real launch
path and the real MCP `initialize` handshake against a process that
misbehaves in specific, chosen ways — which is the part Pegasus owns and
the part `tests/no_network.py` cannot let the suite prove against a real
server such as `engram`. It proves nothing about any real MCP server.
"""
from __future__ import annotations

import json
import os
import sys
import time


def _ok() -> None:
    request = json.loads(sys.stdin.readline())
    response = {
        "jsonrpc": "2.0",
        "id": request.get("id"),
        "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "serverInfo": {"name": "fixture-mcp-server", "version": "1"},
        },
    }
    sys.stdout.write(json.dumps(response) + "\n")
    sys.stdout.flush()


def _garbage() -> None:
    sys.stdin.readline()
    sys.stdout.write("not an mcp response\n")
    sys.stdout.flush()


def _silent(pid_file: str | None) -> None:
    """Record its own pid, if asked to, then never answer -- the fixture
    behind the timeout case, and behind proving the child gets killed."""
    if pid_file:
        with open(pid_file, "w", encoding="utf-8") as handle:
            handle.write(str(os.getpid()))
    time.sleep(60)


def main() -> None:
    mode = sys.argv[1]
    if mode == "ok":
        _ok()
    elif mode == "garbage":
        _garbage()
    elif mode == "exit":
        sys.exit(int(sys.argv[2]) if len(sys.argv) > 2 else 1)
    elif mode == "silent":
        _silent(sys.argv[2] if len(sys.argv) > 2 else None)
    else:
        raise SystemExit(f"unknown fixture mode: {mode}")


if __name__ == "__main__":
    main()
