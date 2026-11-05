"""Typed ingestion results and user-visible quality reasons."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class QualityStatus(StrEnum):
    READABLE = "READABLE"
    LOW_QUALITY = "LOW_QUALITY"
    ROTATED = "ROTATED"
    PARTIALLY_UNREADABLE = "PARTIALLY_UNREADABLE"
    UNREADABLE = "UNREADABLE"
    EMPTY = "EMPTY"


class OrderingStatus(StrEnum):
    ORDERED = "ORDERED"
    ORDER_SUSPECT = "ORDER_SUSPECT"
    UNVERIFIED = "UNVERIFIED"


class MappingStatus(StrEnum):
    UNMAPPED = "UNMAPPED"
    MAPPED = "MAPPED"
    PARTIAL = "PARTIAL"
    UNVERIFIED = "UNVERIFIED"


class DocumentFormat(StrEnum):
    PDF = "PDF"
    PNG = "PNG"
    JPEG = "JPEG"


def reason(code: str, message: str, severity: str = "WARNING") -> dict[str, str]:
    return {"code": code, "message": message, "severity": severity}


class DocumentRejected(Exception):
    def __init__(self, code: str, message: str, reasons: list[dict[str, str]]) -> None:
        super().__init__(message)
        self.code = code
        self.reasons = reasons


@dataclass(frozen=True, slots=True)
class PageRender:
    page_index: int
    png: bytes
    width: int
    height: int
    rotation_degrees: int
    text: str
    quality_status: QualityStatus
    quality_reasons: list[dict[str, str]]
    checksum: str
    printed_page_number: int | None = None
    duplicate_of_index: int | None = None


@dataclass(frozen=True, slots=True)
class RenderedDocument:
    pages: list[PageRender]
    ordering_status: OrderingStatus
    ordering_reasons: list[dict[str, str]] = field(default_factory=list)
    page_ordering_reasons: dict[int, list[dict[str, str]]] = field(default_factory=dict)

    @property
    def page_count(self) -> int:
        return len(self.pages)

    def validation_reasons(self) -> list[dict[str, Any]]:
        return list(self.ordering_reasons)
