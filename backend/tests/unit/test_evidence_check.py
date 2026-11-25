"""A quotation is checked against the blind reading, not taken on trust."""

from __future__ import annotations

from app.correction import evidence_check


def test_a_verbatim_quotation_is_supported() -> None:
    check = evidence_check.check_quote("x = 4", "so x = 4 is the answer")

    assert check.status == evidence_check.QUOTE_SUPPORTED


def test_spacing_case_and_a_unicode_minus_do_not_create_a_false_alarm() -> None:
    check = evidence_check.check_quote("X \u2212 3", "x-3")

    assert check.status == evidence_check.QUOTE_SUPPORTED


def test_a_quotation_broken_across_lines_is_supported_by_its_tokens() -> None:
    check = evidence_check.check_quote("2x + 3 = 11", "2x\n+ 3\n= 11")

    assert check.status == evidence_check.QUOTE_SUPPORTED


def test_an_invented_quotation_is_not_found() -> None:
    check = evidence_check.check_quote("the gradient is 7", "y = 3x + 2")

    assert check.status == evidence_check.QUOTE_NOT_FOUND
    assert check.detail["reason"] == "NOT_PRESENT"


def test_a_short_quotation_proves_nothing() -> None:
    check = evidence_check.check_quote("2", "2 + 3 = 5")

    assert check.status == evidence_check.QUOTE_UNVERIFIABLE
    assert check.detail["reason"] == "QUOTE_TOO_SHORT"


def test_a_missing_reading_is_unverifiable_not_a_pass() -> None:
    checks = evidence_check.check_quotes(["x = 4"], None)

    assert checks[0].status == evidence_check.QUOTE_UNVERIFIABLE
    assert evidence_check.verdict(checks) == evidence_check.STATUS_UNVERIFIABLE


def test_an_illegible_reading_is_unverifiable_even_with_a_transcript() -> None:
    checks = evidence_check.check_quotes(
        ["x = 4"], "x = 4", evidence_status="ILLEGIBLE"
    )

    assert checks[0].status == evidence_check.QUOTE_UNVERIFIABLE
    assert evidence_check.verdict(checks) == evidence_check.STATUS_UNVERIFIABLE


def test_one_missing_quotation_fails_the_whole_question() -> None:
    checks = evidence_check.check_quotes(
        ["x = 4", "y = 9"], "x = 4 and that is all"
    )

    assert evidence_check.verdict(checks) == evidence_check.STATUS_FAIL


def test_every_quotation_found_is_a_pass() -> None:
    checks = evidence_check.check_quotes(["x = 4", "x - 1"], "x = 4 so x - 1 = 3")

    assert evidence_check.verdict(checks) == evidence_check.STATUS_PASS


def test_no_quotation_at_all_is_not_a_pass() -> None:
    assert evidence_check.verdict([]) == evidence_check.STATUS_UNVERIFIABLE
