"""Page coverage: a mark taken from an incomplete script is not a result.

The audit is plain Python over stored rows, so it can be proven here without a
database: what counts as a missing page, what counts as a partial mapping, and
what is deliberately *not* reported.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.correction.page_coverage import (
    CODE_DUPLICATE_PAGE,
    CODE_MISSING_PAGE,
    CODE_PAGE_LIMIT,
    CODE_PAGE_SEQUENCE,
    CODE_UNMAPPED_PAGE,
    CODE_UNPROCESSED_DOCUMENT,
    assess_coverage,
    ordered_pages,
    pages_by_question,
)


def _document(page_count: int, *, name: str = "script.pdf", document_id: str = "doc-1"):
    return SimpleNamespace(
        id=document_id,
        page_count=page_count,
        original_filename=name,
        status="PROCESSED",
    )


def _page(index: int, *, document_id: str = "doc-1", quality: str = "READABLE"):
    return SimpleNamespace(
        id=f"page-{index}", document_id=document_id, page_index=index, quality_status=quality
    )


def _mapping(page_id: str, question_id: str):
    return SimpleNamespace(page_id=page_id, question_id=question_id)


def _codes(findings) -> list[str]:
    return [finding.code for finding in findings]


def test_a_script_whose_pages_are_all_stored_is_clean() -> None:
    findings = assess_coverage(
        documents=[_document(2)],
        pages=[_page(1), _page(2)],
        mappings=[],
        question_ids=["1a"],
        page_cap=6,
    )

    assert findings == []


def test_a_page_the_document_claims_but_storage_lacks_blocks_the_result() -> None:
    findings = assess_coverage(
        documents=[_document(3)],
        pages=[_page(1), _page(2)],
        mappings=[],
        question_ids=["1a"],
        page_cap=6,
    )

    assert _codes(findings) == [CODE_MISSING_PAGE]
    assert findings[0].blocking is True
    assert "script.pdf" in findings[0].message


def test_a_document_with_no_page_count_carries_no_opinion() -> None:
    findings = assess_coverage(
        documents=[_document(0)],
        pages=[_page(1)],
        mappings=[],
        question_ids=["1a"],
        page_cap=6,
    )

    assert findings == []


def test_a_readable_page_no_question_is_mapped_to_is_reported() -> None:
    findings = assess_coverage(
        documents=[_document(2)],
        pages=[_page(1), _page(2)],
        mappings=[_mapping("page-1", "1a")],
        question_ids=["1a", "1b"],
        page_cap=6,
    )

    assert CODE_UNMAPPED_PAGE in _codes(findings)
    unmapped = next(f for f in findings if f.code == CODE_UNMAPPED_PAGE)
    assert unmapped.blocking is False
    assert "page(s) 2" in unmapped.message


def test_without_any_mapping_there_is_no_partial_mapping_to_report() -> None:
    findings = assess_coverage(
        documents=[_document(2)],
        pages=[_page(1), _page(2)],
        mappings=[],
        question_ids=["1a"],
        page_cap=6,
    )

    assert CODE_UNMAPPED_PAGE not in _codes(findings)


def test_an_unreadable_page_is_not_a_coverage_gap() -> None:
    findings = assess_coverage(
        documents=[_document(2)],
        pages=[_page(1), _page(2, quality="UNREADABLE")],
        mappings=[_mapping("page-1", "1a")],
        question_ids=["1a"],
        page_cap=6,
    )

    assert findings == []


def test_a_script_whose_page_numbers_do_not_match_its_count_is_flagged() -> None:
    findings = assess_coverage(
        documents=[_document(2)],
        pages=[_page(1), _page(3)],
        mappings=[],
        question_ids=["1a"],
        page_cap=6,
    )

    assert CODE_PAGE_SEQUENCE in _codes(findings)
    assert all(finding.blocking is False for finding in findings)


def test_the_same_page_image_twice_is_flagged() -> None:
    first = _page(1)
    first.checksum = "abc"
    second = _page(2)
    second.checksum = "abc"

    findings = assess_coverage(
        documents=[_document(2)],
        pages=[first, second],
        mappings=[],
        question_ids=["1a"],
        page_cap=6,
    )

    assert CODE_DUPLICATE_PAGE in _codes(findings)


def test_an_unmapped_page_is_informative_when_every_question_is_mapped() -> None:
    findings = assess_coverage(
        documents=[_document(2)],
        pages=[_page(1), _page(2)],
        mappings=[_mapping("page-1", "1a")],
        question_ids=["1a"],
        page_cap=6,
    )

    unmapped = next(f for f in findings if f.code == CODE_UNMAPPED_PAGE)
    assert unmapped.blocking is False
    assert unmapped.review is False, "a cover page cannot hide a marked answer"


def test_an_unmapped_page_is_reviewed_when_a_question_has_no_mapping() -> None:
    """A mapped question's answer can continue onto a page nobody claimed."""

    findings = assess_coverage(
        documents=[_document(2)],
        pages=[_page(1), _page(2)],
        mappings=[_mapping("page-1", "1a")],
        question_ids=["1a", "1b"],
        page_cap=6,
    )

    unmapped = next(f for f in findings if f.code == CODE_UNMAPPED_PAGE)
    assert unmapped.review is True


def test_a_question_mapped_beyond_the_request_limit_reports_page_limit() -> None:
    pages = [_page(index) for index in range(1, 9)]
    findings = assess_coverage(
        documents=[_document(8)],
        pages=pages,
        mappings=[_mapping(f"page-{index}", "1a") for index in range(1, 9)],
        question_ids=["1a"],
        page_cap=6,
    )

    assert CODE_PAGE_LIMIT in _codes(findings)
    assert all(finding.blocking is False for finding in findings)


def test_a_long_script_with_unmapped_questions_reports_the_page_limit() -> None:
    findings = assess_coverage(
        documents=[_document(7)],
        pages=[_page(index) for index in range(1, 8)],
        mappings=[_mapping(f"page-{index}", "1a") for index in range(1, 7)],
        question_ids=["1a", "1b"],
        page_cap=6,
    )

    assert CODE_PAGE_LIMIT in _codes(findings)


def test_a_question_mapped_beyond_the_cap_reports_the_page_limit() -> None:
    """A full mapping does not remove truncation when the question needs 7 pages."""

    findings = assess_coverage(
        documents=[_document(7)],
        pages=[_page(index) for index in range(1, 8)],
        mappings=[_mapping(f"page-{index}", "1a") for index in range(1, 8)],
        question_ids=["1a"],
        page_cap=6,
    )

    assert _codes(findings) == [CODE_PAGE_LIMIT]
    assert findings[0].review is True
    assert findings[0].blocking is False


def test_a_document_that_was_not_processed_blocks_the_result() -> None:
    """Its pages were never read, so an answer on them would look absent."""

    unprocessed = _document(2, name="continuation.pdf", document_id="doc-2")
    unprocessed.status = "FAILED"

    findings = assess_coverage(
        documents=[_document(1)],
        pages=[_page(1)],
        mappings=[],
        question_ids=["1a"],
        page_cap=6,
        unprocessed_documents=[unprocessed],
    )

    assert _codes(findings) == [CODE_UNPROCESSED_DOCUMENT]
    assert findings[0].blocking is True
    assert "FAILED" in findings[0].message
    assert "continuation.pdf" in findings[0].message


def test_a_submission_whose_documents_all_processed_has_no_unprocessed_gap() -> None:
    findings = assess_coverage(
        documents=[_document(1)],
        pages=[_page(1)],
        mappings=[],
        question_ids=["1a"],
        page_cap=6,
        unprocessed_documents=[],
    )

    assert CODE_UNPROCESSED_DOCUMENT not in _codes(findings)


def test_pages_are_ordered_by_index_for_reading() -> None:
    pages = [_page(3), _page(1), _page(2)]

    assert [page.page_index for page in ordered_pages(pages)] == [1, 2, 3]


def test_mappings_are_grouped_by_question() -> None:
    grouped = pages_by_question(
        [_mapping("page-1", "1a"), _mapping("page-2", "1a"), _mapping("page-2", "1b")]
    )

    assert grouped == {"1a": {"page-1", "page-2"}, "1b": {"page-2"}}
