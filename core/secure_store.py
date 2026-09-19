"""Small Windows Credential Manager boundary for desktop-only secrets."""
from __future__ import annotations

import os
import re


SERVICE = "MICA"
_NAME = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")


class SecureStoreUnavailable(RuntimeError):
    pass


def _backend():
    if os.name != "nt":
        raise SecureStoreUnavailable("Windows Credential Manager is required")
    try:
        import keyring  # type: ignore[import-not-found]
    except ImportError as error:
        raise SecureStoreUnavailable("The keyring package is not installed") from error
    backend = keyring.get_keyring()
    module = backend.__class__.__module__.casefold()
    if "windows" not in module and "winvault" not in module:
        raise SecureStoreUnavailable("The active keyring is not Windows Credential Manager")
    return keyring


def _valid_name(name: str) -> str:
    normalized = name.strip().upper()
    if not _NAME.fullmatch(normalized):
        raise ValueError("Credential name must be a bounded uppercase identifier")
    return normalized


def get_secret(name: str) -> str | None:
    """Read a secret without copying it into logs or local configuration."""
    return _backend().get_password(SERVICE, _valid_name(name))


def set_secret(name: str, value: str) -> None:
    if not value or len(value) > 8192:
        raise ValueError("Credential value must contain 1 to 8192 characters")
    _backend().set_password(SERVICE, _valid_name(name), value)


def delete_secret(name: str) -> None:
    keyring = _backend()
    try:
        keyring.delete_password(SERVICE, _valid_name(name))
    except keyring.errors.PasswordDeleteError:
        return
