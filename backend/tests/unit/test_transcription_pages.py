"""Which pages one blind reading carries.

Mission 5 found that a question with no page mapping was sent the whole script:
eight full-resolution pages, about 20 MB encoded, at the provider's inline
request ceiling.  These tests pin the replacement: mapped pages first, then the
pages this run's own quotations cite, then one page between mapped neighbours,
then nothing — never the whole script and never an arbitrary page.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.correction.transcription import (
    PAGE_CONFIDENCE_CIRCULAR,
    PAGE_CONFIDENCE_INDEPENDENT,
    PAGE_CONFIDENCE_NONE,
    PAGE_SOURCE_EVIDENCE,
    PAGE_SOURCE_INTERPOLATED,
    PAGE_SOURCE_MAPPING,
    PAGE_SOURCE_SINGLE_PAGE,
    PAGE_SOURCE_UNAVAILABLE,
    page_confidence,
    resolve_transcription_pages,
)


def _pages(count: int) -> list[SimpleNamespace]:
    return [
        SimpleNamespace(id=f"p{index}", page_index=index)
        for index in range(1, count + 1)
    ]


def _resolve(
    question_id: str,
    *,
    count: int = 8,
    mapped: dict | None = None,
    citations: dict | None = None,
    owners: dict | None = None,
    max_pages: int = 3,
):
    return resolve_transcription_pages(
        question_id,
        pages=_pages(count),
        mapped=mapped or {},
        citations=citations or {},
        owners=owners or {},
        max_pages=max_pages,
    )


def test_q6_uses_the_page_its_marking_evidence_cited() -> None:
    """Q6 of the pilot has no mapping but its quotations name page 2."""

    selection = _resolve(
        "6", citations={"6": ["p2"]}, owners={"p2": {"6"}, "p3": {"7"}}
    )

    assert selection.available
    assert selection.source == PAGE_SOURCE_EVIDENCE
    assert selection.page_ids == ("p2",)
    assert selection.page_indices == (2,)


def test_q6_no_longer_needs_all_eight_pages() -> None:
    """The Mission 5 payload: eight pages in, one page out."""

    selection = _resolve(
        "6",
        citations={"6": ["p2"]},
        owners={"p2": {"6"}, "p3": {"7"}},
    )

    assert len(selection.page_ids) == 1
    assert 8 not in selection.page_indices


def test_an_explicit_mapping_wins_over_a_citation() -> None:
    selection = _resolve(
        "6",
        mapped={"6": ["p3"]},
        citations={"6": ["p2"]},
        owners={"p2": {"6"}, "p3": {"6"}},
    )

    assert selection.source == PAGE_SOURCE_MAPPING
    assert selection.page_ids[0] == "p3"


def test_a_question_spanning_two_pages_keeps_both_in_document_order() -> None:
    selection = _resolve(
        "6",
        mapped={"6": ["p3", "p2"]},
        owners={"p2": {"6"}, "p3": {"6"}, "p4": {"7"}},
    )

    assert selection.page_indices == (2, 3)


def test_a_continuation_page_is_added_when_nobody_else_claims_it() -> None:
    selection = _resolve(
        "6",
        mapped={"6": ["p2"]},
        owners={"p2": {"6"}},
    )

    assert selection.page_indices == (2, 3)


def test_a_page_another_question_owns_is_not_taken_as_a_continuation() -> None:
    selection = _resolve(
        "6",
        mapped={"6": ["p2"]},
        owners={"p2": {"6"}, "p3": {"7"}},
    )

    assert selection.page_indices == (2,)


def test_multiple_questions_on_one_page_share_it() -> None:
    selection = _resolve(
        "6",
        mapped={"6": ["p2"], "7": ["p2"]},
        owners={"p2": {"6", "7"}},
    )

    assert selection.page_ids[0] == "p2"
    # Page 3 is not claimed by anyone, so it is carried as a continuation.
    assert selection.page_indices == (2, 3)


def test_an_unmapped_question_between_two_mapped_ones_takes_the_page_between() -> None:
    selection = _resolve(
        "6",
        mapped={"5": ["p1"], "7": ["p3"]},
        owners={"p1": {"5"}, "p3": {"7"}},
    )

    assert selection.available
    assert selection.source == PAGE_SOURCE_INTERPOLATED
    assert selection.page_indices == (2,)


def test_an_ambiguous_gap_is_unavailable_rather_than_guessed() -> None:
    selection = _resolve(
        "6",
        mapped={"5": ["p1"], "9": ["p5"]},
        owners={"p1": {"5"}, "p5": {"9"}},
    )

    assert not selection.available
    assert selection.source == PAGE_SOURCE_UNAVAILABLE
    assert selection.reason == "NO_PAGE_MAPPING"
    assert selection.page_ids == ()


def test_a_multi_page_paper_with_no_attribution_at_all_is_unavailable() -> None:
    selection = _resolve("6")

    assert not selection.available
    assert selection.reason == "NO_PAGE_MAPPING"


def test_a_one_page_script_has_no_page_to_choose() -> None:
    selection = _resolve("6", count=1)

    assert selection.available
    assert selection.source == PAGE_SOURCE_SINGLE_PAGE
    assert selection.page_indices == (1,)


def test_a_mapping_to_a_page_outside_the_submission_is_ignored() -> None:
    selection = _resolve(
        "6",
        mapped={"6": ["not-a-page"]},
        citations={"6": ["p4"]},
        owners={"p4": {"6"}, "p5": {"7"}},
    )

    assert selection.source == PAGE_SOURCE_EVIDENCE
    assert selection.page_indices == (4,)


def test_a_question_that_needs_more_pages_than_the_budget_is_unavailable() -> None:
    """A silently thinned script reads as a missing answer, so it is refused."""

    selection = _resolve(
        "6",
        mapped={"6": ["p1", "p2", "p3", "p4"]},
        owners={"p1": {"6"}, "p2": {"6"}, "p3": {"6"}, "p4": {"6"}},
        max_pages=3,
    )

    assert not selection.available
    assert selection.reason == "PAGE_BUDGET_EXCEEDED:5>3"
    assert selection.page_ids == ()


def test_the_selection_is_reported_for_a_reviewer() -> None:
    selection = _resolve("6", citations={"6": ["p2"]}, owners={"p2": {"6"}, "p3": {"7"}})

    assert selection.as_dict() == {
        "source": PAGE_SOURCE_EVIDENCE,
        "confidence": PAGE_CONFIDENCE_CIRCULAR,
        "page_ids": ["p2"],
        "page_indices": [2],
        "available": True,
        "reason": None,
    }


# -- how far the page selection itself is independent -----------------------


def test_a_mapping_is_independent_of_the_marking_pass() -> None:
    assert page_confidence(PAGE_SOURCE_MAPPING) == PAGE_CONFIDENCE_INDEPENDENT


def test_a_one_page_script_has_nothing_to_choose() -> None:
    assert page_confidence(PAGE_SOURCE_SINGLE_PAGE) == PAGE_CONFIDENCE_INDEPENDENT


def test_a_page_taken_from_the_marking_pass_is_circular() -> None:
    """The first pass chose the page; a second reading of it proves nothing."""

    assert page_confidence(PAGE_SOURCE_EVIDENCE) == PAGE_CONFIDENCE_CIRCULAR
    assert page_confidence(PAGE_SOURCE_INTERPOLATED) == PAGE_CONFIDENCE_CIRCULAR


def test_an_unavailable_selection_has_no_confidence() -> None:
    assert page_confidence(PAGE_SOURCE_UNAVAILABLE) == PAGE_CONFIDENCE_NONE
    assert page_confidence(None) == PAGE_CONFIDENCE_NONE


def test_the_source_is_kept_distinct_from_the_confidence() -> None:
    """A reviewer must be able to see both, not a collapsed single label."""

    evidence = _resolve("6", citations={"6": ["p2"]}, owners={"p2": {"6"}, "p3": {"7"}})
    mapped = _resolve("6", mapped={"6": ["p2"]}, owners={"p2": {"6"}, "p3": {"7"}})

    assert evidence.source == PAGE_SOURCE_EVIDENCE
    assert mapped.source == PAGE_SOURCE_MAPPING
    assert evidence.confidence != mapped.confidence
