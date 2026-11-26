"""Unit tests for the deterministic part of submission monitoring.

These never touch the network, a database or a model.  They prove that the code
distinguishes an external link from a Drive file, a readable page from a blank
one, a scanned script from a corrupt PDF, and a plausible submission from an
unrelated one.
"""

from __future__ import annotations

import io

import pymupdf
import pytest
from app.classroom_monitoring.attachments import (
    AttachmentRejected,
    assemble_images_to_pdf,
    classify_attachments,
    inspect_bytes,
)
from app.classroom_monitoring.relevance import (
    CANNOT_DETERMINE,
    INSUFFICIENT_EVIDENCE,
    LIKELY_RELEVANT,
    POSSIBLY_UNRELATED,
    assess,
)
from app.classroom_monitoring.states import (
    SubmissionState,
    can_transition,
    transition,
)
from app.core.config import IngestionSettings, get_settings
from app.core.errors import AppError, ErrorCode
from app.core.security import Principal
from PIL import Image, ImageDraw


def _pdf(pages: int = 1, text: str = "Question 1 answer x = 4") -> bytes:
    document = pymupdf.open()
    for _ in range(pages):
        page = document.new_page(width=595, height=842)
        if text:
            page.insert_text((72, 120), text, fontsize=14)
    data = document.tobytes()
    document.close()
    return data


def _blank_pdf() -> bytes:
    document = pymupdf.open()
    document.new_page(width=595, height=842)
    data = document.tobytes()
    document.close()
    return data


def _png(width: int = 1000, height: int = 1400, *, draw: bool = True) -> bytes:
    image = Image.new("RGB", (width, height), "white")
    if draw:
        ImageDraw.Draw(image).line((50, 100, width - 50, 900), fill="black", width=6)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _settings(**overrides) -> IngestionSettings:
    return IngestionSettings(**overrides)


# -- classification --------------------------------------------------------


def test_an_external_link_is_ignored_and_never_downloaded():
    classified = classify_attachments(
        [{"kind": "LINK", "title": "https://example.org/answers", "mime_type": None}]
    )
    assert classified[0].action == "IGNORE"
    assert classified[0].google_file_id is None
    assert "not fetched" in (classified[0].reason or "")


def test_a_pdf_drive_file_is_downloaded():
    classified = classify_attachments(
        [
            {
                "kind": "DRIVE_FILE",
                "title": "script.pdf",
                "drive_file_id": "file-1",
                "mime_type": "application/pdf",
            }
        ]
    )
    assert classified[0].action == "DOWNLOAD"


def test_a_workspace_document_is_exported_not_called_a_pdf():
    classified = classify_attachments(
        [
            {
                "kind": "DRIVE_FILE",
                "title": "Work",
                "drive_file_id": "file-2",
                "mime_type": "application/vnd.google-apps.document",
            }
        ]
    )
    assert classified[0].action == "EXPORT_PDF"


def test_a_google_sheet_is_unsupported_with_a_reason():
    classified = classify_attachments(
        [
            {
                "kind": "DRIVE_FILE",
                "title": "Sheet",
                "drive_file_id": "file-3",
                "mime_type": "application/vnd.google-apps.spreadsheet",
            }
        ]
    )
    assert classified[0].action == "UNSUPPORTED"
    assert "Sheet" in (classified[0].reason or "")


def test_a_drive_file_without_a_reported_type_is_downloaded_for_inspection():
    """Classroom's DriveFile has no mimeType; byte inspection decides instead."""

    classified = classify_attachments(
        [
            {
                "kind": "DRIVE_FILE",
                "title": "script",
                "drive_file_id": "file-5",
                "mime_type": None,
            }
        ]
    )
    assert classified[0].action == "DOWNLOAD"
    assert classified[0].reason is None


def test_an_unsupported_executable_is_refused():
    classified = classify_attachments(
        [
            {
                "kind": "DRIVE_FILE",
                "title": "setup.exe",
                "drive_file_id": "file-4",
                "mime_type": "application/x-msdownload",
            }
        ]
    )
    assert classified[0].action == "UNSUPPORTED"


def test_order_is_preserved():
    classified = classify_attachments(
        [
            {"kind": "DRIVE_FILE", "drive_file_id": "a", "mime_type": "image/png"},
            {"kind": "LINK", "title": "ignored"},
            {"kind": "DRIVE_FILE", "drive_file_id": "c", "mime_type": "image/jpeg"},
        ]
    )
    assert [item.position for item in classified] == [1, 2, 3]
    assert [item.google_file_id for item in classified] == ["a", None, "c"]


# -- inspection ------------------------------------------------------------


def test_a_valid_pdf_is_readable_and_its_text_is_extracted():
    inspection = inspect_bytes(_pdf(), settings=_settings())
    assert inspection.readable is True
    assert inspection.page_count == 1
    assert inspection.has_text is True
    assert "Question 1" in inspection.text_excerpt


def test_an_empty_byte_string_is_rejected():
    with pytest.raises(AttachmentRejected) as caught:
        inspect_bytes(b"", settings=_settings())
    assert caught.value.code == "EMPTY_FILE"


def test_a_disguised_file_is_judged_by_content_not_extension():
    with pytest.raises(AttachmentRejected) as caught:
        inspect_bytes(b"MZ\x90\x00 not a pdf", settings=_settings())
    assert caught.value.code == "UNSUPPORTED_TYPE"


def test_a_corrupt_pdf_is_reported_not_marked():
    with pytest.raises(AttachmentRejected) as caught:
        inspect_bytes(b"%PDF-1.7\nthis is not a pdf body", settings=_settings())
    assert caught.value.code == "CORRUPT_PDF"


def test_an_encrypted_pdf_is_refused():
    document = pymupdf.open()
    document.new_page()
    buffer = io.BytesIO()
    document.save(
        buffer,
        encryption=pymupdf.PDF_ENCRYPT_AES_256,
        owner_pw="owner",
        user_pw="user",
    )
    document.close()
    with pytest.raises(AttachmentRejected) as caught:
        inspect_bytes(buffer.getvalue(), settings=_settings())
    assert caught.value.code == "PDF_ENCRYPTED"


def test_a_blank_pdf_is_not_readable():
    inspection = inspect_bytes(_blank_pdf(), settings=_settings())
    assert inspection.readable is False
    assert inspection.blank_pages == [1]
    codes = {issue["code"] for issue in inspection.issues}
    assert "BLANK_DOCUMENT" in codes


def test_too_many_pages_is_refused():
    with pytest.raises(AttachmentRejected) as caught:
        inspect_bytes(_pdf(pages=3), settings=_settings(), max_pages=2)
    assert caught.value.code == "TOO_MANY_PAGES"


def test_a_valid_image_is_readable():
    inspection = inspect_bytes(_png(), settings=_settings())
    assert inspection.readable is True
    assert inspection.page_count == 1
    assert inspection.has_text is False


def test_a_blank_image_is_flagged():
    inspection = inspect_bytes(_png(draw=False), settings=_settings())
    assert inspection.readable is False
    assert inspection.blank_pages == [1]


def test_a_low_resolution_image_is_not_readable():
    inspection = inspect_bytes(_png(width=120, height=160), settings=_settings())
    assert inspection.readable is False
    codes = {issue["code"] for issue in inspection.issues}
    assert "LOW_RESOLUTION" in codes


def test_an_oversized_image_is_refused():
    with pytest.raises(AttachmentRejected) as caught:
        inspect_bytes(
            _png(width=1200, height=1200),
            settings=_settings(max_image_pixels=1_000_000),
        )
    assert caught.value.code == "IMAGE_TOO_LARGE"


def test_multiple_images_assemble_into_one_ordered_document():
    assembled = assemble_images_to_pdf([_png(), _png(width=900)])
    document = pymupdf.open(stream=assembled, filetype="pdf")
    try:
        assert document.page_count == 2
    finally:
        document.close()


# -- relevance -------------------------------------------------------------


def _assess(**overrides):
    values = {
        "text": "",
        "page_count": 1,
        "readable_pages": 1,
        "assignment_name": "Algebra Practice Paper ALG-12",
        "assignment_description": None,
        "expected_questions": ["1", "1a", "1b", "2"],
        "policy": "STRUCTURAL_ALLOW",
        "has_attachments": True,
    }
    values.update(overrides)
    return assess(**values)


def test_a_scan_is_assessed_structurally_and_says_so():
    result = _assess()
    assert result.relevance == LIKELY_RELEVANT
    codes = {warning["code"] for warning in result.warnings}
    assert "RELEVANCE_TEXT_UNAVAILABLE" in codes


def test_text_required_policy_sends_a_scan_to_a_teacher():
    result = _assess(policy="TEXT_REQUIRED")
    assert result.relevance == CANNOT_DETERMINE


def test_an_assignment_title_in_the_text_is_evidence():
    result = _assess(text="Algebra Practice Paper ALG-12 Question 1 x = 4 and 1a shown")
    assert result.relevance == LIKELY_RELEVANT
    codes = {item["code"] for item in result.evidence}
    assert "TITLE_MATCH" in codes
    assert "QUESTION_MARKER_MATCH" in codes


def test_a_different_paper_code_is_flagged_for_review():
    result = _assess(text="Physics Unit PHY-99 Question 1 answer follows in detail")
    assert result.relevance == POSSIBLY_UNRELATED


def test_readable_text_with_no_matching_evidence_is_not_guessed():
    result = _assess(text="Here is a shopping list with milk bread and apples today")
    assert result.relevance == INSUFFICIENT_EVIDENCE


def test_missing_question_markers_are_recorded_not_rejected():
    result = _assess(text="Algebra Practice Paper ALG-12 Question 1 only")
    assert "2" in result.missing_expected
    assert result.relevance == LIKELY_RELEVANT


# -- state transitions -----------------------------------------------------


class _Row:
    def __init__(self, state: str, correction_state: str = "NOT_QUEUED") -> None:
        self.state = state
        self.correction_state = correction_state


def test_the_submission_state_machine_refuses_an_illegal_move():
    row = _Row(SubmissionState.DETECTED.value)
    assert can_transition("DETECTED", "DOWNLOADING") is True
    assert can_transition("COMPLETED", "READY") is False
    with pytest.raises(AppError) as caught:
        transition(row, SubmissionState.READY)
    assert caught.value.code is ErrorCode.CLASSROOM_SUBMISSION_STATE_INVALID
    assert row.state == "DETECTED"


def test_a_superseded_version_is_final():
    assert can_transition("SUPERSEDED", "READY") is False


def test_identifying_a_detected_submission_is_safe_to_repeat():
    row = _Row(SubmissionState.DETECTED.value)
    assert transition(row, SubmissionState.DETECTED) is False
    assert row.state == "DETECTED"


def test_a_principal_always_carries_its_own_tenant():
    principal = Principal(
        user_id=__import__("uuid").uuid4(),
        tenant_id=__import__("uuid").uuid4(),
        subject="teacher-a",
        role="TEACHER",
    )
    assert principal.tenant_id != principal.user_id
    assert principal.can_upload_documents is True


def test_the_default_settings_keep_monitoring_off():
    assert get_settings().classroom.monitoring_enabled is False
