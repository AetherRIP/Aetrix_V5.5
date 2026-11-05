"""Page ordering assessment.

A PDF's physical order is not proof that the scanned pages are in order.  When a
printed page number is readable, the assessor checks it; when it is not, the
document is marked ``UNVERIFIED`` rather than silently assumed correct.
"""

from __future__ import annotations

import re

from ..core.config import IngestionSettings
from .types import OrderingStatus, PageRender, reason

_PAGE_PATTERNS = (
    re.compile(r"\bpage\s+(\d{1,4})\s*(?:of\s+\d{1,4})?\b", re.IGNORECASE),
    re.compile(r"^\s*(\d{1,4})\s*$", re.MULTILINE),
)


def extracted_page_number(text: str) -> int | None:
    for pattern in _PAGE_PATTERNS:
        match = pattern.search(text or "")
        if match:
            value = int(match.group(1))
            if value > 0:
                return value
    return None


def assess_ordering(
    pages: list[PageRender], settings: IngestionSettings
) -> tuple[OrderingStatus, list[dict[str, str]], dict[int, list[dict[str, str]]]]:
    del settings
    document_reasons: list[dict[str, str]] = []
    page_reasons: dict[int, list[dict[str, str]]] = {}
    numbers = [page.printed_page_number for page in pages]
    present = [number for number in numbers if number is not None]

    if not present:
        document_reasons.append(
            reason(
                "PAGE_NUMBERS_NOT_FOUND",
                "No printed page numbers were found; page order could not be verified.",
                "INFO",
            )
        )
        return OrderingStatus.UNVERIFIED, document_reasons, page_reasons

    missing = [
        page.page_index for page, number in zip(pages, numbers, strict=True) if number is None
    ]
    if missing:
        document_reasons.append(
            reason(
                "PAGE_NUMBER_MISSING",
                "Some pages have no readable printed page number: "
                + ", ".join(str(index) for index in missing)
                + ".",
            )
        )
        for page in pages:
            if page.printed_page_number is None:
                page_reasons.setdefault(page.page_index, []).append(
                    reason(
                        "PAGE_NUMBER_MISSING",
                        "No printed page number was found on this page.",
                        "INFO",
                    )
                )

    out_of_sequence = False
    previous: int | None = None
    for page in pages:
        number = page.printed_page_number
        if number is None:
            continue
        if previous is not None and number != previous + 1:
            out_of_sequence = True
            page_reasons.setdefault(page.page_index, []).append(
                reason(
                    "PAGE_ORDER_OUT_OF_SEQUENCE",
                    f"Printed page number {number} follows {previous}; expected {previous + 1}.",
                )
            )
        previous = number
    if out_of_sequence:
        document_reasons.append(
            reason(
                "PAGE_ORDER_OUT_OF_SEQUENCE",
                "The printed page numbers are not consecutive in the supplied order.",
                "ERROR",
            )
        )

    if missing or out_of_sequence:
        return OrderingStatus.ORDER_SUSPECT, document_reasons, page_reasons
    return OrderingStatus.ORDERED, document_reasons, page_reasons
