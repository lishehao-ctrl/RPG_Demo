from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AuthLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=2, max_length=20, pattern=r"^[A-Za-z0-9_]+$")


class AuthUserResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(min_length=1, max_length=80)
    display_name: str = Field(min_length=1, max_length=120)


class AuthSessionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    authenticated: bool
    user: AuthUserResponse | None = None


class CurrentActorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(min_length=1, max_length=80)
    display_name: str = Field(min_length=1, max_length=120)
    is_default: bool = False
