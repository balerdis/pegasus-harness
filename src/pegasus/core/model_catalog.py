"""Which providers and models a machine can actually reach, and nothing else.

Three real files feed this decision, per the architecture document's section
on model configuration: a CLI's own model catalog, its credentials file, and
its own configuration. This module only holds the pure rule for turning those
three, already parsed into plain data, into what gets offered -- no
filesystem, no CLI name, so the rule is testable without touching a real
machine and stays reusable by whichever adapter needs it.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Model:
    """One model a provider exposes, and the two facts that decide its fate.

    Only ``tool_call`` gates whether a model is offered at all: a model that
    cannot call a tool cannot run a phase. ``reasoning`` is carried through so
    a caller can offer an effort choice, but never filters anything on its
    own.
    """

    id: str
    tool_call: bool
    reasoning: bool = False


@dataclass(frozen=True)
class Provider:
    """A provider this machine can reach, with only its tool-capable models."""

    id: str
    models: tuple[Model, ...] = ()


@dataclass(frozen=True)
class ModelCatalog:
    """The full answer: every provider this machine can reach, and its models."""

    providers: tuple[Provider, ...] = ()


def credential_provider_names(payload: object) -> frozenset[str]:
    """The provider ids that have a session in a credentials document.

    Takes names, never values: the contract is in the name of this function,
    and its body never looks past the top-level keys, so a secret buried in
    one of the values has no path out of it.
    """
    if not isinstance(payload, dict):
        return frozenset()
    return frozenset(str(key) for key in payload.keys())


def declared_provider_names(config_payload: object) -> frozenset[str]:
    """The provider ids the user declared themselves, in their own configuration."""
    if not isinstance(config_payload, dict):
        return frozenset()
    provider = config_payload.get("provider")
    if not isinstance(provider, dict):
        return frozenset()
    return frozenset(str(key) for key in provider.keys())


def build(
    raw_catalog: object,
    *,
    credentialed: frozenset[str],
    declared: frozenset[str],
    variables: dict[str, str],
) -> ModelCatalog:
    """Offer a provider when the machine can actually reach it.

    A provider is offered when it has a session, all of its environment
    variables are set, the user declared it themselves, or the catalog marks
    it as the CLI's own built-in provider. A missing or malformed catalog is
    not an error: it yields an empty result, the same way an uninstalled CLI
    that was never opened has no catalog file to read yet.
    """
    if not isinstance(raw_catalog, dict):
        return ModelCatalog()

    providers: list[Provider] = []
    for provider_id, entry in raw_catalog.items():
        if not isinstance(entry, dict):
            continue
        if not _is_reachable(str(provider_id), entry, credentialed, declared, variables):
            continue
        models = _tool_capable_models(entry)
        if not models:
            continue
        providers.append(Provider(id=str(provider_id), models=models))

    return ModelCatalog(providers=tuple(providers))


def _is_reachable(
    provider_id: str,
    entry: dict,
    credentialed: frozenset[str],
    declared: frozenset[str],
    variables: dict[str, str],
) -> bool:
    if provider_id in credentialed:
        return True
    if provider_id in declared:
        return True
    if bool(entry.get("builtin", False)):
        return True
    required = entry.get("env", [])
    if isinstance(required, list) and required:
        return all(variables.get(str(name), "").strip() for name in required)
    return False


def _tool_capable_models(entry: dict) -> tuple[Model, ...]:
    raw_models = entry.get("models", {})
    if not isinstance(raw_models, dict):
        return ()
    models: list[Model] = []
    for model_id, spec in raw_models.items():
        if not isinstance(spec, dict):
            continue
        if not bool(spec.get("tool_call", False)):
            continue
        models.append(
            Model(id=str(model_id), tool_call=True, reasoning=bool(spec.get("reasoning", False)))
        )
    return tuple(models)
