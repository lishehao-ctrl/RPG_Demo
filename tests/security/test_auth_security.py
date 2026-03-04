from __future__ import annotations

import pytest

from rpg_backend.security.passwords import hash_password, verify_password
from rpg_backend.security.tokens import TokenValidationError, create_access_token, decode_access_token


def test_password_hash_and_verify_roundtrip() -> None:
    plain = "S3cure!Passw0rd"
    encoded = hash_password(plain)
    assert encoded.startswith("pbkdf2_sha256$")
    assert verify_password(plain, encoded) is True
    assert verify_password("wrong-password", encoded) is False


def test_decode_access_token_rejects_invalid_signature() -> None:
    token, _ = create_access_token(
        user_id="u1",
        email="admin@example.com",
        role="admin",
        issuer="rpg-backend",
        secret="secret-a",
        expire_minutes=60,
    )

    with pytest.raises(TokenValidationError):
        decode_access_token(token=token, secret="secret-b", issuer="rpg-backend")


def test_decode_access_token_rejects_expired_token() -> None:
    token, _ = create_access_token(
        user_id="u1",
        email="admin@example.com",
        role="admin",
        issuer="rpg-backend",
        secret="secret-a",
        expire_minutes=-1,
    )

    with pytest.raises(TokenValidationError):
        decode_access_token(token=token, secret="secret-a", issuer="rpg-backend")
