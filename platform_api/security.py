"""Password hashing, signed access tokens, and encrypted document storage."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken


PBKDF2_ITERATIONS = 600_000


class SecurityConfigurationError(RuntimeError):
    """Raised when required production secrets are missing."""


def hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    if len(password) < 10:
        raise ValueError("Password must contain at least 10 characters.")
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS
    )
    return (
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, salt_b64: str, digest_b64: str) -> bool:
    try:
        salt = base64.urlsafe_b64decode(salt_b64.encode("ascii"))
        _, candidate = hash_password(password, salt)
        return hmac.compare_digest(candidate, digest_b64)
    except (ValueError, TypeError):
        return False


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


@dataclass(frozen=True)
class TokenClaims:
    user_id: str
    email: str
    expires_at: int


class TokenSigner:
    def __init__(self, secret: str, ttl_seconds: int = 8 * 60 * 60):
        if len(secret) < 32:
            raise SecurityConfigurationError(
                "ATS_AUTH_SECRET must contain at least 32 characters."
            )
        self._secret = secret.encode("utf-8")
        self.ttl_seconds = ttl_seconds

    def issue(self, user_id: str, email: str) -> str:
        payload = {
            "sub": user_id,
            "email": email,
            "iat": int(time.time()),
            "exp": int(time.time()) + self.ttl_seconds,
            "nonce": _b64encode(os.urandom(12)),
        }
        encoded = _b64encode(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        )
        signature = _b64encode(
            hmac.new(self._secret, encoded.encode("ascii"), hashlib.sha256).digest()
        )
        return encoded + "." + signature

    def verify(self, token: str) -> TokenClaims:
        try:
            encoded, signature = token.split(".", 1)
            expected = _b64encode(
                hmac.new(
                    self._secret, encoded.encode("ascii"), hashlib.sha256
                ).digest()
            )
            if not hmac.compare_digest(signature, expected):
                raise ValueError("bad signature")
            payload = json.loads(_b64decode(encoded))
            if int(payload["exp"]) < int(time.time()):
                raise ValueError("expired")
            return TokenClaims(
                user_id=str(payload["sub"]),
                email=str(payload["email"]),
                expires_at=int(payload["exp"]),
            )
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError("Invalid or expired access token.") from exc


class DocumentCipher:
    def __init__(self, secret: str):
        if len(secret) < 32:
            raise SecurityConfigurationError(
                "ATS_DATA_SECRET must contain at least 32 characters."
            )
        key = base64.urlsafe_b64encode(
            hashlib.sha256(secret.encode("utf-8")).digest()
        )
        self._fernet = Fernet(key)

    def encrypt(self, text: str) -> bytes:
        return self._fernet.encrypt(text.encode("utf-8"))

    def decrypt(self, value: bytes | str | None) -> str:
        if value is None:
            return ""
        raw = value.encode("ascii") if isinstance(value, str) else value
        try:
            return self._fernet.decrypt(raw).decode("utf-8")
        except InvalidToken as exc:
            raise ValueError("Stored document could not be decrypted.") from exc

