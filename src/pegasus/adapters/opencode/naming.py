"""Deriving OpenCode's own on-disk names from an `Identity`.

`identity.program_name` is already a safe bare filename (see
`core.identity.PROGRAM_NAME_PATTERN`), so most of what this adapter ships --
`f"{identity.program_name}-skill-registry"` and the like -- needs nothing more
than plain string interpolation, spelled inline where it is used. The three
functions here exist because three contexts cannot use `program_name` as-is:
a Python module stem, which cannot contain a hyphen; an exported TypeScript
symbol, which is not a filename at all; and an npm package name, which
`PROGRAM_NAME_PATTERN` permits to contain uppercase letters that npm itself
refuses. Kept together so all three transforms are exercised by one focused
test rather than re-derived at each call site.
"""
from __future__ import annotations

from pegasus.core.identity import Identity


def module_name(identity: Identity) -> str:
    """`program_name` reshaped into a valid Python module stem.

    `PROGRAM_NAME_PATTERN` allows a hyphen, which a bare `import` statement
    does not -- so a distribution whose `program_name` uses one still needs
    an importable name for its own bundled skill-registry module.
    """
    return identity.program_name.replace("-", "_")


def pascal_name(identity: Identity) -> str:
    """`program_name` reshaped into a PascalCase identifier.

    For a bundled plugin's exported symbol (`{{program_pascal_name}}Plugin`,
    say) -- a context that needs a TypeScript identifier, not a filename, so
    neither a hyphen nor an underscore may survive into it.
    """
    return "".join(part[:1].upper() + part[1:] for part in identity.program_name.replace("_", "-").split("-") if part)


def npm_name(identity: Identity) -> str:
    """`program_name` reshaped into a name npm's `package.json` will accept.

    This exists because `PROGRAM_NAME_PATTERN` allows uppercase letters
    (`identity.program_name` is a general program name, not an npm package
    name), but npm rejects any uppercase character in the `name` field of
    `package.json` -- `npm ci` fails outright on one. A distribution whose
    `program_name` is, say, `MyTool` still needs a legal `name` for the
    bundled notifier's own manifest, so this is not redundant with
    `program_name` or with `module_name`/`pascal_name` above: it is the one
    form safe to fold into lowercase.
    """
    return identity.program_name.lower()
