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
