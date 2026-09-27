"""The CLI-agnostic half of credential transport: the detection catalog as
data, and the port helper that reads an adapter's own declared capability.

Nothing here names a CLI. The catalog (`credential-transport-catalog.json`,
shipped inside the content core, never inside an adapter's own asset tree) is
read once and handed to whichever adapter implements the capability; how that
adapter ships it -- as a sidecar file next to a plugin, say -- is that
adapter's own business.
"""
from __future__ import annotations

import json
from importlib.resources import files as _package_files
from typing import Any

from pegasus.core.types import CredentialTransportCapability

CATALOG_FILENAME = "credential-transport-catalog.json"

#: Whatever `importlib.resources` hands back -- a real `pathlib.Path` on a
#: filesystem, a `zipfile.Path` read straight out of an archive. Typed `Any`
#: for the same reason every other adapter-facing `AssetNode` alias is.
_CATALOG_ROOT: Any = _package_files("pegasus") / "content" / "security"


def load_catalog_bytes() -> bytes:
    """The catalog file's raw bytes, exactly as shipped -- what an adapter
    copies verbatim into a sidecar next to its plugin."""
    return (_CATALOG_ROOT / CATALOG_FILENAME).read_bytes()


def load_catalog() -> dict[str, Any]:
    """The catalog, parsed -- what a test validates the shape of."""
    return json.loads(load_catalog_bytes().decode("utf-8"))


def capability_of(adapter: Any) -> CredentialTransportCapability:
    """What `adapter` declares it supports, or every operation `False` when
    it never implements `credential_transport()` at all.

    This is the one place the "an adapter that says nothing means none of the
    four" rule is applied -- see `CredentialTransportCapability`'s own
    docstring for why that is the intended way a future adapter opts out with
    zero code written here.
    """
    method = getattr(adapter, "credential_transport", None)
    if method is None:
        return CredentialTransportCapability()
    result = method()
    if not isinstance(result, CredentialTransportCapability):
        raise TypeError(
            f"{adapter!r}.credential_transport() must return a "
            "CredentialTransportCapability, got " + repr(type(result))
        )
    return result
