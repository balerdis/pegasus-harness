"""The one shared list of case-insensitive brand fragments that must never
leak outside a distribution's own composition root.

Imported by `tests/test_install_identity.py` (which scans `install.sh`) and
`tests/test_architecture.py` (which scans the Python source) so the rule
cannot silently drift into two different lists for the same concern. This
module stays under `tests/`, never `src/`, on purpose: brand knowledge
belongs only to distribution-time data (`identity.json`) and to the tests
that check the engine never hardcodes one -- never to the engine itself.
"""
from __future__ import annotations

BANNED_FRAGMENTS = ("pegasus", "harness", "balerdis")

#: Build-time implementation detail -- `tools/build_installer.py` reading a
#: distribution's `identity.json` to fill in the `install.sh` template -- that
#: must never reach a generated installer's own `--help` output. The person
#: running the installer is not its maintainer: they need to know what the
#: product is and what it installs, never how the installer script itself was
#: produced. Scanned case-insensitively, the same way `BANNED_FRAGMENTS` is.
#: "plantilla" is Spanish for "template", the word `install.sh`'s own
#: identity-header comment uses for itself.
BUILD_MECHANISM_FRAGMENTS = ("build_installer.py", "identity.json", "plantilla")
