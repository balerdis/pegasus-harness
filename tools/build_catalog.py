#!/usr/bin/env python3
"""Generate the artifact catalog for one CLI from the content core.

The catalog is a derived artifact. Nobody edits it by hand: it is regenerated
from `src/pegasus/content/` and the CLI's adapter, and its digest is what a
release uses to prove it distributed what it declared.

    python3 tools/build_catalog.py --cli opencode
    python3 tools/build_catalog.py --cli opencode --out manifests/opencode-catalog.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pegasus.adapters import available  # noqa: E402
from pegasus.core import catalog as catalog_module  # noqa: E402
from pegasus.core import content as content_module  # noqa: E402
from pegasus.core.types import Environment  # noqa: E402

# The catalog carries its own canonical frame, so this tool has no home to pick:
# targets stay relative to each CLI's configuration root and nothing about the
# machine that ran the build reaches the output.


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    registry = available()
    parser.add_argument("--cli", default="opencode", choices=registry.ids())
    parser.add_argument("--out", type=Path, help="write here instead of standard output")
    parser.add_argument("--summary", action="store_true", help="print counts and digest only")
    arguments = parser.parse_args()

    catalog = catalog_module.build(content_module.load(), registry.get(arguments.cli))

    if arguments.summary:
        files = sum(1 for entry in catalog.entries if entry.kind == "file")
        keys = len(catalog) - files
        print(f"{catalog.cli}: {files} files, {keys} configuration keys")
        print(catalog.digest)
        return 0

    rendered = json.dumps(catalog.as_dict(), indent=2, ensure_ascii=False) + "\n"
    if arguments.out:
        arguments.out.parent.mkdir(parents=True, exist_ok=True)
        arguments.out.write_text(rendered, encoding="utf-8")
        print(f"{arguments.out}: {len(catalog)} entries, {catalog.digest}")
    else:
        sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
