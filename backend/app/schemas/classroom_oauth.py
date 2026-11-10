"""Contracts for the Google Classroom authorisation and course sync.

Tokens are deliberately absent from every model here.  A response can say that
a workspace is connected, when it last synced and what failed; it cannot hand a
credential back to the browser.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

ConnectionStatus = Literal["NOT_CONNECTED", "CONNECTED", "RECONNECT_REQUIRED"]
SyncStatus = Literal["SUCCEEDED", "FAILED"]
CourseState = Literal["ACTIVE", "ARCHIVED", "DELETED"]


class ClassroomConnectionRead(BaseModel):
    configured: bool
    status: ConnectionStatus
    redirect_uri: str | None
    required_scopes: list[str] = Field(default_factory=list)
    granted_scopes: list[str] = Field(default_factory=list)
    connected_at: datetime | None
    connected_by_subject: str | None
    last_synced_at: datetime | None
    last_sync_status: SyncStatus | None
    last_sync_counts: dict[str, int] = Field(default_factory=dict)
    last_error_code: str | None
    last_error_message: str | None


class ClassroomAuthorizationStart(BaseModel):
    authorization_url: str
    expires_at: datetime
    redirect_uri: str
    scopes: list[str] = Field(default_factory=list)


class ClassroomAuthorizationComplete(BaseModel):
    code: str = Field(min_length=1, max_length=4000)
    state: str = Field(min_length=1, max_length=4000)

    @field_validator("code", "state")
    @classmethod
    def _strip(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("The authorisation parameters cannot be empty.")
        return cleaned


class SyncedCourseRead(BaseModel):
    course_id: str
    name: str
    section: str | None
    course_state: CourseState


class SyncCountsRead(BaseModel):
    discovered: int
    created: int
    updated: int


class ClassroomSyncRead(BaseModel):
    status: Literal["SUCCEEDED"]
    synced_at: datetime
    counts: SyncCountsRead
    truncated: bool
    courses: list[SyncedCourseRead] = Field(default_factory=list)


class ClassroomDisconnectRead(BaseModel):
    status: Literal["RECONNECT_REQUIRED"]
    #: Whether Google confirmed the grant was revoked.  The local tokens are
    #: discarded either way.
    revoked: bool
