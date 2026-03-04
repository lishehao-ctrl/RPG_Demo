from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any


@dataclass(frozen=True)
class AccessTokenClaims:
    sub: str
    email: str
    role: str
    iss: str
    iat: int
    exp: int


class TokenValidationError(RuntimeError):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode((data + padding).encode("ascii"))


def _json_dumps(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _sign(message: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).digest()
    return _b64url_encode(digest)


def create_access_token(
    *,
    user_id: str,
    email: str,
    role: str,
    issuer: str,
    secret: str,
    expire_minutes: int,
) -> tuple[str, datetime]:
    now = datetime.now(UTC)
    expires_at = now + timedelta(minutes=int(expire_minutes))
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": str(user_id),
        "email": str(email),
        "role": str(role),
        "iss": str(issuer),
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    encoded_header = _b64url_encode(_json_dumps(header))
    encoded_payload = _b64url_encode(_json_dumps(payload))
    signing_input = f"{encoded_header}.{encoded_payload}".encode("ascii")
    signature = _sign(signing_input, secret)
    token = f"{encoded_header}.{encoded_payload}.{signature}"
    return token, expires_at


def decode_access_token(*, token: str, secret: str, issuer: str) -> AccessTokenClaims:
    raw = (token or "").strip()
    if not raw:
        raise TokenValidationError("token is missing")

    try:
        encoded_header, encoded_payload, encoded_signature = raw.split(".", 2)
    except ValueError as exc:  # pragma: no cover
        raise TokenValidationError("token format is invalid") from exc

    signing_input = f"{encoded_header}.{encoded_payload}".encode("ascii")
    expected_signature = _sign(signing_input, secret)
    if not hmac.compare_digest(expected_signature, encoded_signature):
        raise TokenValidationError("token signature is invalid")

    try:
        header = json.loads(_b64url_decode(encoded_header).decode("utf-8"))
        payload = json.loads(_b64url_decode(encoded_payload).decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise TokenValidationError("token payload is invalid") from exc

    if header.get("alg") != "HS256":
        raise TokenValidationError("token algorithm is not supported")

    token_issuer = str(payload.get("iss") or "")
    if token_issuer != issuer:
        raise TokenValidationError("token issuer is invalid")

    try:
        exp = int(payload.get("exp"))
        iat = int(payload.get("iat"))
    except Exception as exc:  # noqa: BLE001
        raise TokenValidationError("token timestamps are invalid") from exc

    now_ts = int(datetime.now(UTC).timestamp())
    if exp <= now_ts:
        raise TokenValidationError("token is expired")

    sub = str(payload.get("sub") or "")
    email = str(payload.get("email") or "")
    role = str(payload.get("role") or "")
    if not sub or not email or not role:
        raise TokenValidationError("token claims are invalid")

    return AccessTokenClaims(sub=sub, email=email, role=role, iss=token_issuer, iat=iat, exp=exp)
