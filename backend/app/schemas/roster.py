"""Contracts for workspace classes and the student roster."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


class ClassCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    year_group: str | None = Field(default=None, max_length=40)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("A class name is required.")
        return cleaned

    @field_validator("year_group")
    @classmethod
    def _year_group(cls, value: str | None) -> str | None:
        return _clean(value)


class ClassUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    year_group: str | None = Field(default=None, max_length=40)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("A class name cannot be empty.")
        return cleaned

    @field_validator("year_group")
    @classmethod
    def _year_group(cls, value: str | None) -> str | None:
        return _clean(value)


class ClassRead(BaseModel):
    id: UUID
    name: str
    year_group: str | None
    student_count: int
    created_at: datetime


class StudentCreate(BaseModel):
    student_ref: str = Field(min_length=1, max_length=120)
    display_name: str | None = Field(default=None, max_length=200)
    class_id: UUID | None = None

    @field_validator("student_ref")
    @classmethod
    def _ref(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("A student reference is required.")
        return cleaned

    @field_validator("display_name")
    @classmethod
    def _display_name(cls, value: str | None) -> str | None:
        return _clean(value)


class StudentUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=200)
    class_id: UUID | None = None

    @field_validator("display_name")
    @classmethod
    def _display_name(cls, value: str | None) -> str | None:
        return _clean(value)


class StudentRead(BaseModel):
    id: UUID
    student_ref: str
    display_name: str | None
    class_id: UUID | None
    created_at: datetime


class StudentImportIssue(BaseModel):
    """One row the import did not create, and why.

    ``row`` is the CSV line number including the header, so a teacher can open
    the file and find the exact line rather than counting data rows.
    """

    kind: Literal["SKIPPED", "ERROR"]
    row: int
    student_ref: str | None = None
    message: str


class StudentImportResult(BaseModel):
    """A per-row account of an import, never a blanket success."""

    total_rows: int
    created: int
    skipped: int
    failed: int
    classes_created: int
    issues: list[StudentImportIssue] = Field(default_factory=list)
    created_refs: list[str] = Field(default_factory=list)
