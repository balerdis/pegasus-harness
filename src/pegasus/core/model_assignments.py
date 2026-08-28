"""Per-agent model preferences, kept apart from the ownership journal.

A model assignment is not a mutation of an installed artifact: it is a
preference that lives in Pegasus's own state and takes part in rendering
later, with a soft-failure posture. The journal never learns of it, so
overwriting an artifact is never a risk to ownership -- see the journal's own
note on this in the architecture document.

Everything here is pure: types, serialization, validation and functional
updates. Reading and writing the file belongs to a store, so this module
stays testable without a filesystem.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from pegasus.core.types import ModelAssignment

SCHEMA = "pegasus/model-assignment/v1"


class ModelAssignmentError(ValueError):
    """The stored assignments are malformed, so none of them may be trusted."""


@dataclass(frozen=True)
class Entry:
    """One agent's preference, scoped to the CLI it was set for."""

    cli: str
    agent: str
    assignment: ModelAssignment


@dataclass(frozen=True)
class ModelAssignments:
    schema: str = SCHEMA
    entries: tuple[Entry, ...] = ()


def empty() -> ModelAssignments:
    return ModelAssignments()


# --- Queries -----------------------------------------------------------------


def get(assignments: ModelAssignments, cli: str, agent: str) -> ModelAssignment | None:
    for entry in assignments.entries:
        if entry.cli == cli and entry.agent == agent:
            return entry.assignment
    return None


# --- Functional updates --------------------------------------------------------


def with_assignment(assignments: ModelAssignments, cli: str, agent: str, assignment: ModelAssignment) -> ModelAssignments:
    """Set or replace the preference for one agent on one CLI."""
    remaining = tuple(entry for entry in assignments.entries if not (entry.cli == cli and entry.agent == agent))
    return replace(assignments, entries=(*remaining, Entry(cli=cli, agent=agent, assignment=assignment)))


def without_assignment(assignments: ModelAssignments, cli: str, agent: str) -> ModelAssignments:
    """Drop the preference for one agent on one CLI. A no-op if it was never set."""
    remaining = tuple(entry for entry in assignments.entries if not (entry.cli == cli and entry.agent == agent))
    return replace(assignments, entries=remaining)


# --- Serialization -------------------------------------------------------------


def to_dict(assignments: ModelAssignments) -> dict[str, Any]:
    return {
        "schema": assignments.schema,
        "assignments": [_entry_to_dict(entry) for entry in assignments.entries],
    }


def _entry_to_dict(entry: Entry) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "cli": entry.cli,
        "agent": entry.agent,
        "provider_id": entry.assignment.provider_id,
        "model_id": entry.assignment.model_id,
    }
    if entry.assignment.effort is not None:
        payload["effort"] = entry.assignment.effort
    return payload


def from_dict(payload: Any) -> ModelAssignments:
    """Parse and validate. Assignments that fail here are not trusted."""
    if not isinstance(payload, dict):
        raise ModelAssignmentError("the model assignments document must be an object")
    schema = payload.get("schema")
    if schema != SCHEMA:
        raise ModelAssignmentError(f"unsupported model assignment schema: {schema!r}; expected {SCHEMA!r}")

    raw_entries = payload.get("assignments", [])
    if not isinstance(raw_entries, list):
        raise ModelAssignmentError("assignments must be a list")
    entries = tuple(_entry_from_dict(item) for item in raw_entries)

    seen: set[tuple[str, str]] = set()
    for entry in entries:
        key = (entry.cli, entry.agent)
        if key in seen:
            raise ModelAssignmentError(f"more than one assignment recorded for {entry.cli!r}/{entry.agent!r}")
        seen.add(key)

    return ModelAssignments(schema=schema, entries=entries)


def _entry_from_dict(payload: Any) -> Entry:
    if not isinstance(payload, dict):
        raise ModelAssignmentError("each assignment must be an object")
    cli = payload.get("cli")
    agent = payload.get("agent")
    provider_id = payload.get("provider_id")
    model_id = payload.get("model_id")
    for name, value in (("cli", cli), ("agent", agent), ("provider_id", provider_id), ("model_id", model_id)):
        if not isinstance(value, str) or not value:
            raise ModelAssignmentError(f"each assignment needs a non-empty {name}")
    effort = payload.get("effort")
    if effort is not None and not isinstance(effort, str):
        raise ModelAssignmentError("effort must be a string when present")
    return Entry(cli=cli, agent=agent, assignment=ModelAssignment(provider_id=provider_id, model_id=model_id, effort=effort))
