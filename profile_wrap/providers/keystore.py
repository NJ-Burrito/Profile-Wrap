"""Where API keys live: the OS keychain through ``keyring``, else an environment variable.

Order for a read: keychain, then ``PROFILE_WRAP_<PROVIDER>_API_KEY``. A key is written only to the
keychain. Without a usable keychain (a headless Linux box has no unlocked Secret Service) ``set_key``
refuses and says to use the variable. Reads never prompt, so a scheduled job cannot hang on an unlock;
a locked or absent keychain reads as "no key" and the job exits non-zero.

A key is never written to a config file, a log, the ledger or an error message.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Mapping, Optional

SERVICE = "profile-wrap"


class KeystoreError(Exception):
    """The keychain cannot be used for this operation. The message says what to do instead."""


@dataclass(frozen=True)
class Found:
    key: str
    source: str  # "keychain" or "env"


def env_name(provider: str) -> str:
    return "PROFILE_WRAP_" + re.sub(r"[^A-Za-z0-9]+", "_", provider).upper() + "_API_KEY"


def mask(key: str) -> str:
    """Show only the last 4 characters."""
    return ("****" + key[-4:]) if len(key) >= 8 else "****"


def _keyring() -> Optional[Any]:
    """The ``keyring`` module when it is installed and has a real backend, else None."""
    try:
        import keyring  # type: ignore
    except Exception:
        return None
    try:
        backend = keyring.get_keyring()
        if getattr(backend, "priority", 1) <= 0 or type(backend).__module__.startswith("keyring.backends.fail"):
            return None
    except Exception:
        return None
    return keyring


def keychain_available() -> bool:
    return _keyring() is not None


def get_key(provider: str, environ: Optional[Mapping[str, str]] = None) -> Optional[Found]:
    kr = _keyring()
    if kr is not None:
        try:
            value = kr.get_password(SERVICE, provider)
        except Exception:
            value = None
        if value:
            return Found(value, "keychain")
    env = environ if environ is not None else os.environ
    value = (env.get(env_name(provider)) or "").strip()
    return Found(value, "env") if value else None


def set_key(provider: str, key: str) -> None:
    key = key.strip()
    if not key:
        raise KeystoreError("the key is empty")
    kr = _keyring()
    if kr is None:
        raise KeystoreError(
            "no usable OS keychain here. Install it with `uv pip install keyring` or, on a headless "
            f"machine, set the environment variable {env_name(provider)} instead (profile-wrap reads it).")
    try:
        kr.set_password(SERVICE, provider, key)
    except Exception as exc:
        raise KeystoreError(f"the keychain refused the key ({type(exc).__name__}); set "
                            f"{env_name(provider)} in the environment instead") from None


def delete_key(provider: str) -> bool:
    kr = _keyring()
    if kr is None:
        return False
    try:
        kr.delete_password(SERVICE, provider)
        return True
    except Exception:
        return False


def missing_key_message(provider: str) -> str:
    return (f"no API key for {provider}. Run `profile-wrap providers set-key {provider}` "
            f"or set the environment variable {env_name(provider)}.")
