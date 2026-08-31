"""A tiny CLI, just enough to prove the archive this fixture is staged into actually runs."""
from __future__ import annotations

import json
import sys

from . import __version__


def main(argv: list[str]) -> int:
    if argv and argv[0] == "doctor":
        print(json.dumps({"pegasus_version": __version__}))
        return 0
    print("usage: pegasus doctor", file=sys.stderr)
    return 1
