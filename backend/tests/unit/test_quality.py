from __future__ import annotations

from app.core.config import get_settings
from app.documents.quality import assess_png
from app.documents.rendering import render_document
from app.documents.types import DocumentRejected, OrderingStatus, QualityStatus
from app.documents.validation import validate_upload
from tests.support import make_pdf, make_png


def test_blank_page_is_typed_and_not_dropped() -> None:
    status, reasons, width, height = assess_png(
        make_png(), rotation_degrees=0, settings=get_settings().ingestion
    )
    assert status is QualityStatus.EMPTY
    assert any(item["code"] == "BLANK_PAGE" for item in reasons)
    assert (width, height) == (1000, 1400)


def test_pdf_rendering_orders_and_records_page_numbers() -> None:
    data = make_pdf(["Question 1 Page 1 of 2", "Question 2 Page 2 of 2"])
    upload = validate_upload(
        filename="paper.pdf",
        declared_mime="application/pdf",
        data=data,
        settings=get_settings(),
    )
    rendered = render_document(data, upload, get_settings())
    assert rendered.ordering_status is OrderingStatus.ORDERED
    assert [page.printed_page_number for page in rendered.pages] == [1, 2]
    assert all(page.text for page in rendered.pages)
    assert all(page.width > 500 for page in rendered.pages)


def test_duplicate_pdf_pages_are_visible_reasons() -> None:
    data = make_pdf(["Question 1 Page 1 of 2", "Question 1 Page 1 of 2"])
    upload = validate_upload(
        filename="duplicate.pdf",
        declared_mime="application/pdf",
        data=data,
        settings=get_settings(),
    )
    rendered = render_document(data, upload, get_settings())
    assert rendered.ordering_status is OrderingStatus.ORDER_SUSPECT
    assert any(item["code"] == "DUPLICATE_PAGE" for item in rendered.ordering_reasons)
    assert rendered.pages[1].duplicate_of_index == 1


def test_invalid_magic_is_rejected() -> None:
    try:
        validate_upload(
            filename="not-really.pdf",
            declared_mime="application/pdf",
            data=b"this is not a pdf",
            settings=get_settings(),
        )
    except DocumentRejected as error:
        assert error.code == "UNSUPPORTED_TYPE"
    else:  # pragma: no cover
        raise AssertionError("an invalid signature was accepted")
