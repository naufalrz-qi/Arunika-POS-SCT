"""Fernet symmetric encryption for MS SQL credentials (PRD §8.1).

The key is read from the POS_FERNET_KEY environment variable — never hardcoded.
Generate one with:  python manage.py generate_key
"""
from __future__ import annotations

import os
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken


class EncryptionKeyMissing(RuntimeError):
    pass


class PasswordDecryptError(RuntimeError):
    """A stored token exists but can't be decrypted with the active POS_FERNET_KEY."""

    pass


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    key = os.environ.get("POS_FERNET_KEY")
    if not key:
        raise EncryptionKeyMissing(
            "POS_FERNET_KEY tidak diset. Jalankan `python manage.py generate_key` "
            "lalu simpan hasilnya di file .env."
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt(plaintext: str) -> str:
    """Encrypt a plaintext string -> Fernet token (str)."""
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    """Decrypt a Fernet token -> plaintext. Raises InvalidToken if tampered."""
    return _fernet().decrypt(token.encode()).decode()


def safe_decrypt(token: str, default: str = "") -> str:
    """Decrypt but never raise — returns `default` on bad/empty token."""
    if not token:
        return default
    try:
        return decrypt(token)
    except (InvalidToken, ValueError):
        return default


def decrypt_checked(token: str) -> str:
    """Decrypt a stored token, raising `PasswordDecryptError` on a corrupt/mismatched key.

    Unlike `safe_decrypt`, a token that exists but fails to decrypt is never
    disguised as a blank password — use this wherever a silent blank password
    would otherwise surface as a confusing downstream auth error.
    """
    if not token:
        return ""
    try:
        return decrypt(token)
    except (InvalidToken, ValueError) as exc:
        raise PasswordDecryptError(
            "Password tersimpan tidak bisa dibaca — kemungkinan POS_FERNET_KEY di .env berubah."
        ) from exc
