"""``python -m pegasus``: the same entry point the launcher will call."""
from __future__ import annotations

import sys

from pegasus.cli import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
