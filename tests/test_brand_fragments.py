"""One shared definition of the banned brand-fragment list.

`BANNED_FRAGMENTS` used to be declared three times independently: once in
`tests/test_install_identity.py`, and twice more inside
`tests/test_architecture.py` -- three copies of one rule that could silently
drift apart. This test proves every consumer now imports the same object
from `tests/brand_fragments.py` instead of re-declaring its own tuple.
"""
from __future__ import annotations

import unittest

import test_architecture
import test_install_identity
from brand_fragments import BANNED_FRAGMENTS


class SharedBannedFragmentsTest(unittest.TestCase):
    def test_expected_fragments(self):
        self.assertEqual(BANNED_FRAGMENTS, ("pegasus", "harness", "balerdis"))

    def test_test_install_identity_imports_the_shared_constant(self):
        self.assertIs(test_install_identity.BANNED_FRAGMENTS, BANNED_FRAGMENTS)

    def test_test_architecture_imports_the_shared_constant(self):
        self.assertIs(test_architecture.BANNED_FRAGMENTS, BANNED_FRAGMENTS)


if __name__ == "__main__":
    unittest.main()
