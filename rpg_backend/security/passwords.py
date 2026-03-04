from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

PBKDF2_PREFIX = "pbkdf2_sha256"
PBKDF2_ITERATIONS = 200_000
PBKDF2_SALT_BYTES = 16


class PasswordHashError(RuntimeError):
    pass


def _b64encode(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.b64decode(value.encode("ascii"), validate=True)


def hash_password(plain_password: str) -> str:
    password = (plain_password or "").encode("utf-8")
    if not password:
        raise PasswordHashError("password is empty")

    salt = secrets.token_bytes(PBKDF2_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password, salt, PBKDF2_ITERATIONS)
    return f"{PBKDF2_PREFIX}${PBKDF2_ITERATIONS}${_b64encode(salt)}${_b64encode(digest)}"


def verify_password(plain_password: str, encoded_hash: str) -> bool:
    try:
        prefix, iterations_raw, salt_raw, digest_raw = (encoded_hash or "").split("$", 3)
        if prefix != PBKDF2_PREFIX:
            return False
        iterations = int(iterations_raw)
        salt = _b64decode(salt_raw)
        expected_digest = _b64decode(digest_raw)
    except Exception:  # noqa: BLE001
        return False

    password = (plain_password or "").encode("utf-8")
    if not password:
        return False

    calculated_digest = hashlib.pbkdf2_hmac("sha256", password, salt, iterations)
    return hmac.compare_digest(expected_digest, calculated_digest)
