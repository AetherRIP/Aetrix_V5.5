"""Page coverage: is every page of a script accounted for?

Marking reads page images.  If a page is missing from storage, or a page exists
that no question mapping mentions, the marks were decided on an incomplete
picture of the script.  This module answers that question before marking starts,
in plain Python, from the stored document, page and mapping rows.

It does not map pages to questions (that is a model-assisted step with its own
cost); it audits the mapping a job already has and reports what a person must
know.  Ordering is preserved: a question's pages are always offered in page order.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

CODE_UNPROCESSED_DOCUMENT = "UNPROCESSED_DOCUMENT"
CODE_MISSING_PAGE = "MISSING_PAGE"
CODE_UNMAPPED_PAGE = "UNMAPPED_PAGE"
CODE_PAGE_LIMIT = "PAGE_LIMIT"
CODE_PAGE_SEQUENCE = "PAGE_SEQUENCE"
CODE_DUPLICATE_PAGE = "DUPLICATE_PAGE"

#: Pages a request could not read at all.  An unreadable page is already a review
#: reason on its own; it is not a coverage gap.
_UNREADABLE = frozenset({"UNREADABLE", "EMPTY"})


@dataclass(frozen=True, slots=True)
class PageCoverageFinding:
    code: str
    message: str
    blocking: bool
    #: Every finding worth an operator's attention, whether or not it stops the
    #: run.  A blocking finding is necessarily review-worthy.
    review: bool = True


def ordered_pages(pages: Iterable[Any]) -> list[Any]:
    """Pages in reading order: by page index, then by id for stability."""

    return sorted(pages, key=lambda page: (int(page.page_index), str(page.id)))


def assess_coverage(
    *,
    documents: Iterable[Any],
    pages: Iterable[Any],
    mappings: Iterable[Any],
    question_ids: Iterable[str],
    page_cap: int,
    unprocessed_documents: Iterable[Any] = (),
) -> list[PageCoverageFinding]:
    """Return every coverage finding for one submission.

    ``documents`` are the processed documents whose pages were read.
    ``unprocessed_documents`` are the submission's other documents: a document
    that failed or never finished processing is not part of the marked script at
    all, so its answers are absent from every request.  That is a gap a person
    must see, not an empty answer.
    """

    page_rows = list(pages)
    mapping_rows = list(mappings)
    findings: list[PageCoverageFinding] = []

    for document in unprocessed_documents:
        status = str(getattr(document, "status", "") or "UNKNOWN")
        findings.append(
            PageCoverageFinding(
                CODE_UNPROCESSED_DOCUMENT,
                f"Document {getattr(document, 'original_filename', '?')!r} is {status} "
                "and was not read. Its pages may carry answers to marked questions, "
                "so no award can stand without a person.",
                blocking=True,
            )
        )

    by_document: dict[Any, list[Any]] = {}
    for page in page_rows:
        by_document.setdefault(page.document_id, []).append(page)

    for document in documents:
        stored = by_document.get(document.id, [])
        expected = int(getattr(document, "page_count", 0) or 0)
        if expected and len(stored) < expected:
            findings.append(
                PageCoverageFinding(
                    CODE_MISSING_PAGE,
                    f"Document {document.original_filename!r} reports {expected} page(s) "
                    f"but only {len(stored)} are stored. The script is incomplete, so no "
                    "award read from it can stand without a person.",
                    blocking=True,
                )
            )
        elif expected:
            indexes = sorted(int(page.page_index) for page in stored)
            if indexes != list(range(1, expected + 1)):
                findings.append(
                    PageCoverageFinding(
                        CODE_PAGE_SEQUENCE,
                        f"Document {document.original_filename!r} reports {expected} page(s) "
                        f"but its stored page numbers are {indexes}. The reading order is "
                        "not the one the document declares, so a person decides the run.",
                        blocking=False,
                    )
                )

    checksums = [
        str(getattr(page, "checksum", "") or "")
        for page in page_rows
        if str(getattr(page, "checksum", "") or "")
    ]
    duplicated = sorted({checksum for checksum in checksums if checksums.count(checksum) > 1})
    if duplicated:
        findings.append(
            PageCoverageFinding(
                CODE_DUPLICATE_PAGE,
                f"{len(duplicated)} page image(s) appear more than once in this submission. "
                "A duplicated page makes the reading order ambiguous, so the run is flagged "
                "for a person rather than marked as if the script were unique.",
                blocking=False,
            )
        )

    mapped_pages = {mapping.page_id for mapping in mapping_rows}
    readable = [page for page in page_rows if page.quality_status not in _UNREADABLE]
    if mapping_rows and readable:
        unmapped = ordered_pages(page for page in readable if page.id not in mapped_pages)
        if unmapped:
            mapped_questions = {mapping.question_id for mapping in mapping_rows}
            missing_questions = [
                str(question_id)
                for question_id in question_ids
                if str(question_id) not in mapped_questions
            ]
            indexes = ", ".join(str(page.page_index) for page in unmapped[:10])
            findings.append(
                PageCoverageFinding(
                    CODE_UNMAPPED_PAGE,
                    f"{len(unmapped)} readable page(s) are not mapped to any question "
                    f"(page(s) {indexes})."
                    + (
                        f" {len(missing_questions)} question(s) have no page mapping at "
                        "all, so a mapped question's answer may continue onto one of "
                        "these pages; the run is flagged for a person."
                        if missing_questions
                        else " Every question is mapped, so these pages carry no part of "
                        "a marked answer; the mapping is recorded as complete."
                    ),
                    blocking=False,
                    review=bool(missing_questions),
                )
            )

    mapped_questions = {mapping.question_id for mapping in mapping_rows}
    readable_count = len(readable)
    if readable_count > page_cap:
        unmapped_questions = [
            str(question_id)
            for question_id in question_ids
            if str(question_id) not in mapped_questions
        ]
        if unmapped_questions:
            findings.append(
                PageCoverageFinding(
                    CODE_PAGE_LIMIT,
                    f"The script has {readable_count} readable pages and a request carries "
                    f"at most {page_cap}; {len(unmapped_questions)} question(s) have no page "
                    "mapping, so their award can only cover the pages actually read.",
                    blocking=False,
                )
            )

    for question_id, page_ids in pages_by_question(mapping_rows).items():
        if len(page_ids) > page_cap:
            findings.append(
                PageCoverageFinding(
                    CODE_PAGE_LIMIT,
                    f"Question {question_id!r} is mapped to {len(page_ids)} pages and a "
                    f"request carries at most {page_cap}; the award covers only the pages "
                    "read, so a person decides it.",
                    blocking=False,
                )
            )

    return findings


def pages_by_question(mappings: Iterable[Any]) -> dict[str, set[Any]]:
    """``{question_id: {page_id, ...}}`` from stored mapping rows."""

    grouped: dict[str, set[Any]] = {}
    for mapping in mappings:
        grouped.setdefault(str(mapping.question_id), set()).add(mapping.page_id)
    return grouped
