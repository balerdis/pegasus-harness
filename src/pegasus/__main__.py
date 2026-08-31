"""``python -m pegasus``: the same entry point the launcher will call.

This is also, verbatim, the `__main__.py` `zipapp` finds at the archive root -- `tools/build_zipapp.py`
stages it there unmodified rather than letting `zipapp` synthesize its own wrapper, so there is only
ever one entry point to keep correct. That is why the version guard below has to live here and run
before `pegasus.cli` (or anything it imports) does: this is the first line of Pegasus code an old
interpreter ever reaches, whether run from a checkout or from the built artifact.
"""
from __future__ import annotations

import sys

#: The floor `tarfile.data_filter` (PEP 706, used by `pegasus.core.dependencies`) needs. Kept in
#: lockstep with `requires-python` in pyproject.toml -- see tests/test_version_guard.py.
MINIMUM_PYTHON = (3, 12)


def _too_old_message(version_info, minimum=MINIMUM_PYTHON):
    """The one line to print and exit on, or ``None`` when the interpreter is new enough.

    Written with only the plainest syntax on purpose: this runs before anything else in the
    process, on whatever interpreter happens to be invoking it, so it must not itself depend on
    the very floor it is checking for.
    """
    if tuple(version_info[:2]) >= minimum:
        return None
    return "pegasus requires Python %s.%s or newer; this is Python %s.%s" % (
        minimum[0], minimum[1], version_info[0], version_info[1],
    )


_guard_message = _too_old_message(sys.version_info)
if _guard_message is not None:
    sys.stderr.write(_guard_message + "\n")
    raise SystemExit(1)

from pegasus.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
