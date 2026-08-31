"""``python -m pegasus`` (or the zipapp built from this fixture): the same entry point."""
from __future__ import annotations

import sys

from pegasus.cli import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
