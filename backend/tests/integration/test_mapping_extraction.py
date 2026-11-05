from __future__ import annotations

import json

from app.db.models import ExamBlueprintVersion, ProviderUsage
from app.providers.base import TokenUsage
from sqlalchemy import func, select

from tests.support import FakeProvider, make_image_pdf, make_pdf


def _upload_pdf(client, headers, path: str, data: bytes, mime: str = "application/pdf"):
    return client.post(
        path,
        headers=headers,
        files={"file": ("upload.pdf", data, mime)},
    )


def test_page_mapping_uses_approved_blueprint_and_visible_fallback(
    client, paper, identity, auth_headers, provider_credential
) -> None:
    headers = auth_headers(identity.user_a)
    upload = _upload_pdf(
        client,
        headers,
        f"/api/v1/submissions/{paper.submission.id}/documents",
        make_pdf(["Question 1 Page 1 of 1"]),
    )
    assert upload.status_code == 201, upload.text
    document = upload.json()

    mapped = client.post(
        f"/api/v1/documents/{document['id']}/mapping",
        headers=headers,
        json={"blueprint_version_id": str(paper.blueprint.id)},
    )
    assert mapped.status_code == 200, mapped.text
    body = mapped.json()
    assert body["status"] == "MAPPED"
    assert any(item["question_id"] == "1" for item in body["mappings"])

    draft = client.put(
        f"/api/v1/exams/{paper.exam.id}/blueprint",
        headers=headers,
        json={
            "structure": {
                "questions": [{"question_id": "1", "max_marks": 5}],
                "total_marks": 5,
            }
        },
    )
    assert draft.status_code == 200, draft.text
    rejected = client.post(
        f"/api/v1/documents/{document['id']}/mapping",
        headers=headers,
        json={"blueprint_version_id": draft.json()["id"]},
    )
    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "MAPPING_REQUIRES_APPROVED_BLUEPRINT"

    image_upload = _upload_pdf(
        client,
        headers,
        f"/api/v1/submissions/{paper.submission.id}/documents",
        make_image_pdf(),
    )
    assert image_upload.status_code == 201, image_upload.text
    fake = FakeProvider(
        json.dumps({"question_ids": ["1"], "confidence": 0.8}),
        usage=TokenUsage(input_tokens=50, output_tokens=10, cached_tokens=0),
    )
    client.app.state.provider = fake
    model_mapped = client.post(
        f"/api/v1/documents/{image_upload.json()['id']}/mapping",
        headers=headers,
        json={"blueprint_version_id": str(paper.blueprint.id)},
    )
    assert model_mapped.status_code == 200, model_mapped.text
    assert model_mapped.json()["status"] == "MAPPED"
    assert model_mapped.json()["mappings"][0]["method"] == "MODEL"
    assert fake.requests


def test_scheme_extraction_creates_only_a_draft_and_records_prompt_version(
    client, paper, identity, auth_headers, provider_credential, db_session
) -> None:
    headers = auth_headers(identity.user_a)
    structure = {
        "paper_code": "EXTRACTED-01",
        "questions": [{"question_id": "1", "max_marks": 2}],
        "total_marks": 2,
    }
    upload = client.post(
        f"/api/v1/exams/{paper.exam.id}/schemes",
        headers=headers,
        data={"title": "Extracted scheme"},
        files={
            "file": (
                "scheme.pdf",
                make_pdf(["Question 1 Page 1 of 1"]),
                "application/pdf",
            )
        },
    )
    assert upload.status_code == 201, upload.text
    version_id = upload.json()["version"]["id"]
    approved_scheme = client.post(
        f"/api/v1/schemes/{version_id}/approve",
        headers=headers,
        json={"reason": "checked"},
    )
    assert approved_scheme.status_code == 200, approved_scheme.text

    client.app.state.provider = FakeProvider(json.dumps(structure))
    extracted = client.post(
        f"/api/v1/exams/{paper.exam.id}/blueprint/extractions",
        headers=headers,
        json={"scheme_version_id": version_id},
    )
    assert extracted.status_code == 200, extracted.text
    body = extracted.json()
    assert body["blueprint"]["status"] == "DRAFT"
    assert body["blueprint"]["source"] == "EXTRACTED"
    assert body["provider"]["prompt_id"] == "blueprint_extraction"
    assert body["provider"]["prompt_version"] == 1
    assert body["provider"]["input_tokens"] == 100

    usage = db_session.scalar(
        select(ProviderUsage).where(ProviderUsage.id == body["provider"]["usage_id"])
    )
    assert usage is not None
    assert usage.prompt_version_id is not None
    assert usage.success is True

    approved = client.put(
        f"/api/v1/exams/{paper.exam.id}/blueprint",
        headers=headers,
        json={"structure": structure, "approve": True, "reason": "teacher checked extraction"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "APPROVED"

    count_before = db_session.scalar(select(func.count()).select_from(ExamBlueprintVersion))
    client.app.state.provider = FakeProvider(json.dumps({"questions": [], "total_marks": 999}))
    invalid = client.post(
        f"/api/v1/exams/{paper.exam.id}/blueprint/extractions",
        headers=headers,
        json={"scheme_version_id": version_id},
    )
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "EXTRACTION_INVALID"
    count_after = db_session.scalar(select(func.count()).select_from(ExamBlueprintVersion))
    assert count_after == count_before


def test_scheme_extraction_accepts_prose_and_fenced_json(
    client, paper, identity, auth_headers, provider_credential
) -> None:
    headers = auth_headers(identity.user_a)
    structure = {
        "paper_code": "PROSE-01",
        "questions": [{"question_id": "1", "max_marks": 3}],
        "total_marks": 3,
    }
    upload = client.post(
        f"/api/v1/exams/{paper.exam.id}/schemes",
        headers=headers,
        data={"title": "Fenced scheme"},
        files={
            "file": (
                "scheme.pdf",
                make_pdf(["Question 1 Page 1 of 1"]),
                "application/pdf",
            )
        },
    )
    assert upload.status_code == 201, upload.text
    version_id = upload.json()["version"]["id"]
    approved = client.post(
        f"/api/v1/schemes/{version_id}/approve",
        headers=headers,
        json={"reason": "checked"},
    )
    assert approved.status_code == 200, approved.text

    fenced = (
        "Here is the extracted blueprint:\n```json\n"
        + json.dumps(structure)
        + "\n```\nEnd of result."
    )
    client.app.state.provider = FakeProvider(fenced)
    extracted = client.post(
        f"/api/v1/exams/{paper.exam.id}/blueprint/extractions",
        headers=headers,
        json={"scheme_version_id": version_id},
    )
    assert extracted.status_code == 200, extracted.text
    body = extracted.json()["blueprint"]
    assert body["status"] == "DRAFT"
    assert body["structure"]["total_marks"] == 3
    assert body["structure"]["questions"][0]["max_marks"] == 3

    client.app.state.provider = FakeProvider("Here is the JSON requested")
    malformed = client.post(
        f"/api/v1/exams/{paper.exam.id}/blueprint/extractions",
        headers=headers,
        json={"scheme_version_id": version_id},
    )
    assert malformed.status_code == 422
    assert malformed.json()["error"]["code"] == "EXTRACTION_INVALID"
