from __future__ import annotations

from app.core.config import get_settings
from app.core.security import Principal
from app.db.models import Document, DocumentPage
from app.documents.service import DocumentService
from app.storage.local import LocalStorage
from sqlalchemy import func, select

from tests.support import make_pdf


def test_ingestion_renders_and_persists_quality_and_order(
    paper, identity, db_session, tmp_path
) -> None:
    service = DocumentService(db_session, get_settings(), LocalStorage(tmp_path / "store"))
    data = make_pdf(["Question 1 Page 1 of 2", "Question 2 Page 2 of 2"])
    document = service.ingest_for_submission(
        Principal(
            user_id=identity.user_a.id,
            tenant_id=identity.tenant_a.id,
            subject=identity.user_a.subject,
            role=identity.user_a.role,
        ),
        paper.submission.id,
        filename="answers.pdf",
        declared_mime="application/pdf",
        data=data,
    )
    assert document.status == "PROCESSED"
    assert document.page_count == 2
    assert document.ordering_status == "ORDERED"
    pages = db_session.scalars(
        select(DocumentPage)
        .where(DocumentPage.document_id == document.id)
        .order_by(DocumentPage.page_index)
    ).all()
    assert [page.printed_page_number for page in pages] == [1, 2]
    assert all(page.quality_reasons is not None for page in pages)
    assert all(page.text_excerpt for page in pages)


def test_api_upload_is_tenant_scoped(client, paper, identity, auth_headers) -> None:
    headers = auth_headers(identity.user_a)
    response = client.post(
        f"/api/v1/submissions/{paper.submission.id}/documents",
        headers=headers,
        files={
            "file": (
                "answers.pdf",
                make_pdf(["Question 1 Page 1 of 1"]),
                "application/pdf",
            )
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "PROCESSED"
    assert body["pages"][0]["page_index"] == 1
    assert body["ordering_status"] == "ORDERED"

    cross = client.get(f"/api/v1/documents/{body['id']}", headers=auth_headers(identity.user_b))
    assert cross.status_code == 404


def test_rejected_upload_is_recorded_with_typed_reasons(
    client, paper, identity, auth_headers, db_session
) -> None:
    response = client.post(
        f"/api/v1/submissions/{paper.submission.id}/documents",
        headers=auth_headers(identity.user_a),
        files={"file": ("broken.pdf", b"not a pdf", "application/pdf")},
    )
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "DOCUMENT_REJECTED"
    assert error["details"]["reasons"][0]["code"] == "UNSUPPORTED_TYPE"

    rejected = db_session.scalar(select(Document).where(Document.status == "REJECTED").limit(1))
    assert rejected is not None
    assert rejected.error_code == "UNSUPPORTED_TYPE"
    assert db_session.scalar(select(func.count()).select_from(DocumentPage)) == 0
