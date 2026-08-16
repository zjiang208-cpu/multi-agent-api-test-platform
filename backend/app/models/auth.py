from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.models.projects import StrictModel


AuthProtocolStatus = Literal["explicit", "unknown", "conflict"]


class AuthProtocol(StrictModel):
    """Authentication wire format for the selected API operation.

    This is deliberately operation-scoped.  A project may expose different
    authentication schemes on different APIs, and an absent prefix must not be
    confused with the platform's historical ``Bearer`` default.
    """

    header_name: str = Field(default="Authorization", min_length=1, max_length=200)
    prefix: str | None = Field(default=None, max_length=80)
    status: AuthProtocolStatus = "unknown"
    evidence_ids: list[str] = Field(default_factory=list, max_length=20)
    source: str | None = Field(default=None, max_length=200)
    conflicts: list[str] = Field(default_factory=list, max_length=20)

