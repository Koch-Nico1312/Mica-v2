"""Collision-resistant identifiers for persisted MICA objects."""

from uuid import uuid4


def new_id(prefix: str) -> str:
    """Return an opaque identifier that stays unique across threads/processes."""
    return f"{prefix}_{uuid4().hex}"
