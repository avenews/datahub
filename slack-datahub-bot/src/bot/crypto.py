"""Symmetric encryption for DataHub personal access tokens at rest.

Uses Fernet (AES-128-CBC + HMAC) with a key supplied via the ENCRYPTION_KEY
environment variable. The key never touches disk or logs.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken


class DecryptionError(Exception):
    """Raised when a stored token cannot be decrypted with the current key."""


def _derive_fernet_key(raw_key: str) -> bytes:
    """Accept any non-empty secret string, not just a valid Fernet key.

    Fernet requires a 32-byte urlsafe-base64 key. We derive one deterministically
    via SHA-256 so operators can set ENCRYPTION_KEY to any sufficiently random
    secret (e.g. output of `openssl rand -hex 32`) without worrying about the
    exact Fernet key format.
    """
    digest = hashlib.sha256(raw_key.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


class TokenCipher:
    def __init__(self, encryption_key: str):
        if not encryption_key:
            raise ValueError("encryption_key must not be empty")
        self._fernet = Fernet(_derive_fernet_key(encryption_key))

    def encrypt(self, plaintext_token: str) -> bytes:
        return self._fernet.encrypt(plaintext_token.encode("utf-8"))

    def decrypt(self, ciphertext: bytes) -> str:
        try:
            return self._fernet.decrypt(ciphertext).decode("utf-8")
        except InvalidToken as exc:
            raise DecryptionError(
                "Could not decrypt stored token; ENCRYPTION_KEY may have changed"
            ) from exc
