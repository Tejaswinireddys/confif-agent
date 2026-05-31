"""In-memory store for creation sessions between API calls."""

from __future__ import annotations

from dataclasses import dataclass, field

from creation.creation_pipeline import CreationResult, CreationSession


@dataclass
class StoredCreationSession:
    session: CreationSession
    result: CreationResult | None = None
    submitted_inputs: dict[str, dict[str, str]] = field(default_factory=dict)


_store: dict[str, StoredCreationSession] = {}


def save_session(session: CreationSession) -> None:
    _store[session.session_id] = StoredCreationSession(session=session)


def get_session(session_id: str) -> StoredCreationSession | None:
    return _store.get(session_id)


def update_session(session: CreationSession) -> None:
    stored = _store.get(session.session_id)
    if stored is None:
        save_session(session)
        return
    stored.session = session


def set_result(session_id: str, result: CreationResult) -> None:
    stored = _store.get(session_id)
    if stored is None:
        raise KeyError(session_id)
    stored.result = result
    stored.session.plan = result.plan


def set_submitted_inputs(
    session_id: str,
    inputs: dict[str, dict[str, str]],
) -> None:
    stored = _store.get(session_id)
    if stored is None:
        raise KeyError(session_id)
    stored.submitted_inputs = inputs
