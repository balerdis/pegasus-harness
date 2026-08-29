"""Reading what this machine can actually reach, for the model catalog.

Three real files feed `Adapter.model_catalog`, exactly as the architecture
document's model configuration section describes: the CLI's own catalog of
providers and models, its credentials file, and its own configuration. This
module is the one place that opens them.

`model_catalog` receives an `Environment`, pure data, with no filesystem of
its own to hand it. `detect()` already has this same shape -- it resolves
`shutil.which` and `Path.is_dir()` straight against the real disk instead of
going through the `FileSystem` port, and the architecture document names that
as a known inconsistency it accepts rather than hides. Reading these three
files the same way extends that inconsistency rather than fixing it: routing
through the port would mean changing `CliAdapter.model_catalog`'s signature
across every adapter for a filesystem argument only this one method needs,
which is a larger unit of work than this change. The tests below never touch
a real machine because they build their own throwaway directory and point
XDG variables at it, the same discipline `layout.config_dir` already uses.
"""
from __future__ import annotations

import json
from pathlib import Path

from pegasus.adapters.opencode import layout as layout_module
from pegasus.core.model_catalog import ModelCatalog, build, credential_provider_names, declared_provider_names
from pegasus.core.types import Environment


def read(environment: Environment) -> ModelCatalog:
    """Offer whatever providers and models this machine can actually reach."""
    raw_catalog = _read_json(layout_module.models_catalog_file(environment))
    credentials = _read_json(layout_module.credentials_file(environment))
    config = _read_json(layout_module.config_dir(environment) / layout_module.SETTINGS)
    return build(
        raw_catalog,
        credentialed=credential_provider_names(credentials),
        declared=declared_provider_names(config),
        variables=environment.variables,
    )


def _read_json(path: Path) -> object:
    """Absence and malformed content both answer `None`, never an exception.

    A missing catalog file is not an error -- it is what a CLI that was
    installed but never opened looks like, and the architecture document is
    explicit that the answer is an empty catalog, not a crash.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None
