"""The suite cannot reach the network, and this is what makes that true.

Every test here runs against a throwaway home and a filesystem it built
itself. A test that reached out for real bytes would break that in a way
nothing else here can: it would depend on a host answering, so its failure
would look like a hang or, worse, like a pass that happened to find
something at the other end.

Refusing at the one chokepoint every connection passes through is what makes
this structural instead of a rule each test is trusted to remember. Importing
this module installs the refusal; `installed()` says whether it is in place,
so its disappearance is a failing test rather than a suite that quietly
starts calling out.
"""
from __future__ import annotations

import socket

REFUSAL = "network access is not permitted while running this test suite"


class _RefusingSocket(socket.socket):
    """A socket that refuses to open a connection, ever."""

    def connect(self, *args, **kwargs):
        raise RuntimeError(REFUSAL)

    def connect_ex(self, *args, **kwargs):
        raise RuntimeError(REFUSAL)


def installed() -> bool:
    """Whether the refusal is the socket this process would open."""
    return socket.socket is _RefusingSocket


socket.socket = _RefusingSocket
