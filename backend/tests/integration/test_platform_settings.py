"""Platform configuration, retention and audit-access enforcement."""

from __future__ import annotations

from datetime import timedelta

import pytest
from app.core.ids import utcnow
from app.db.models import (
    AuditEvent,
    CorrectionJob,
    Document,
    DocumentPage,
    JobApproval,
    PlatformSettings,
    Tenant,
    User,
)
from app.services.platform_settings import PlatformSettingsService
from app.services.retention import RetentionService
from app.services.workspace_creation import WorkspaceCreationService
from app.storage.base import StorageError
from app.storage.local import LocalStorage
from sqlalchemy import func, select

DEFAULTS = {
    "default_workspace_template": "standard",
    "uploaded_script_retention_days": 365,
    "audit_view_allowed_account_types": ["owner"],
}


def _platform_user(db_session, tenant: Tenant, subject: str, role: str) -> User:
    user = User(tenant_id=tenant.id, subject=subject, role=role)
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def platform_owner(db_session, identity) -> User:
    return _platform_user(db_session, identity.tenant_a, "platform-owner", "PLATFORM_OWNER")


@pytest.fixture
def platform_operator(db_session, identity) -> User:
    return _platform_user(db_session, identity.tenant_a, "platform-operator", "ADMIN")


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def test_first_read_creates_the_documented_defaults(
    client, auth_headers, db_session, platform_owner
):
    response = client.get("/api/v1/admin/settings", headers=auth_headers(platform_owner))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["default_workspace_template"] == "standard"
    assert body["uploaded_script_retention_days"] == 365
    assert body["audit_view_allowed_account_types"] == ["owner"]
    assert body["version"] == 1
    assert body["updated_by_label"] is None
    assert [item["key"] for item in body["available_templates"]] == ["standard"]

    again = client.get("/api/v1/admin/settings", headers=auth_headers(platform_owner))
    assert again.json()["version"] == 1
    assert db_session.scalar(select(func.count(PlatformSettings.id))) == 1

    # Creating the default row is not a settings change, so the platform ledger
    # holds no event for it and stays a record of decisions only.
    assert (
        db_session.scalar(
            select(func.count(AuditEvent.id)).where(
                AuditEvent.action.like("platform.settings.%")
            )
        )
        == 0
    )


def test_settings_survive_a_new_session(client, auth_headers, session_factory, platform_owner):
    client.put(
        "/api/v1/admin/settings",
        headers=auth_headers(platform_owner),
        json={
            "default_workspace_template": "standard",
            "uploaded_script_retention_days": 42,
            "audit_view_allowed_account_types": ["owner"],
            "expected_version": 1,
        },
    )
    with session_factory() as other:
        row = PlatformSettingsService(other).ensure()
        assert row.uploaded_script_retention_days == 42
        assert row.version == 2


def test_unauthorized_reader_is_refused(client, auth_headers, identity):
    response = client.get("/api/v1/admin/settings", headers=auth_headers(identity.user_a))
    assert response.status_code == 403


def test_unauthorized_writer_is_refused(client, auth_headers, identity):
    response = client.put(
        "/api/v1/admin/settings",
        headers=auth_headers(identity.user_a),
        json={
            "default_workspace_template": "standard",
            "uploaded_script_retention_days": 30,
            "audit_view_allowed_account_types": ["owner"],
        },
    )
    assert response.status_code == 403


def test_update_persists_and_audits_each_changed_setting(
    client, auth_headers, db_session, platform_owner
):
    response = client.put(
        "/api/v1/admin/settings",
        headers=auth_headers(platform_owner),
        json={
            "default_workspace_template": "standard",
            "uploaded_script_retention_days": 30,
            "audit_view_allowed_account_types": ["owner", "platform_operator"],
            "expected_version": 1,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["uploaded_script_retention_days"] == 30
    assert body["audit_view_allowed_account_types"] == ["owner", "platform_operator"]
    assert body["version"] == 2
    assert body["updated_by_label"] == platform_owner.subject

    events = db_session.scalars(
        select(AuditEvent).where(AuditEvent.action.like("platform.settings.%"))
    ).all()
    changes = {
        event.detail["setting"]: (event.detail["previous"], event.detail["new"])
        for event in events
        if event.action.endswith(".changed")
    }
    assert changes["uploaded_script_retention_days"] == (365, 30)
    assert changes["audit_view_allowed_account_types"] == (
        ["owner"],
        ["owner", "platform_operator"],
    )
    assert all(event.tenant_id is None for event in events if event.action.endswith(".changed"))
    changed_events = [e for e in events if e.action.endswith(".changed")]
    assert all(e.before_hash and e.after_hash for e in changed_events)


def test_unchanged_save_creates_no_event_and_keeps_version(
    client, auth_headers, db_session, platform_owner
):
    client.get("/api/v1/admin/settings", headers=auth_headers(platform_owner))
    response = client.put(
        "/api/v1/admin/settings",
        headers=auth_headers(platform_owner),
        json={**DEFAULTS, "expected_version": 1},
    )
    assert response.status_code == 200
    assert response.json()["version"] == 1
    assert (
        db_session.scalar(
            select(func.count(AuditEvent.id)).where(
                AuditEvent.action
                == "platform.settings.uploaded_script_retention_days.changed"
            )
        )
        == 0
    )


@pytest.mark.parametrize(
    "payload",
    [
        {**DEFAULTS, "default_workspace_template": "classroom"},
        {**DEFAULTS, "uploaded_script_retention_days": 0},
        {**DEFAULTS, "uploaded_script_retention_days": 4000},
        {**DEFAULTS, "audit_view_allowed_account_types": []},
        {**DEFAULTS, "audit_view_allowed_account_types": ["teacher"]},
    ],
)
def test_invalid_values_are_refused(client, auth_headers, db_session, platform_owner, payload):
    response = client.put(
        "/api/v1/admin/settings",
        headers=auth_headers(platform_owner),
        json={**payload, "expected_version": 1},
    )
    assert response.status_code in {409, 422}, response.text
    row = db_session.scalar(select(PlatformSettings))
    assert row is None or row.version == 1


def test_concurrent_update_loses_instead_of_overwriting(client, auth_headers, platform_owner):
    first = client.put(
        "/api/v1/admin/settings",
        headers=auth_headers(platform_owner),
        json={
            "default_workspace_template": "standard",
            "uploaded_script_retention_days": 90,
            "audit_view_allowed_account_types": ["owner"],
            "expected_version": 1,
        },
    )
    assert first.status_code == 200
    second = client.put(
        "/api/v1/admin/settings",
        headers=auth_headers(platform_owner),
        json={
            "default_workspace_template": "standard",
            "uploaded_script_retention_days": 120,
            "audit_view_allowed_account_types": ["owner"],
            "expected_version": 1,
        },
    )
    assert second.status_code == 409
    current = client.get("/api/v1/admin/settings", headers=auth_headers(platform_owner)).json()
    assert current["uploaded_script_retention_days"] == 90


def test_operator_may_change_retention_but_not_audit_access(
    client, auth_headers, platform_operator
):
    allowed = client.put(
        "/api/v1/admin/settings",
        headers=auth_headers(platform_operator),
        json={
            "default_workspace_template": "standard",
            "uploaded_script_retention_days": 200,
            "audit_view_allowed_account_types": ["owner"],
            "expected_version": 1,
        },
    )
    assert allowed.status_code == 200, allowed.text

    refused = client.put(
        "/api/v1/admin/settings",
        headers=auth_headers(platform_operator),
        json={
            "default_workspace_template": "standard",
            "uploaded_script_retention_days": 200,
            "audit_view_allowed_account_types": ["owner", "platform_operator"],
            "expected_version": 2,
        },
    )
    assert refused.status_code == 403


# ---------------------------------------------------------------------------
# Workspace templates
# ---------------------------------------------------------------------------


def test_new_workspace_records_the_configured_template(db_session, identity):
    tenant = WorkspaceCreationService(db_session).create(name="Gamma", slug="gamma")
    db_session.commit()
    assert tenant.workspace_template == "standard"
    assert tenant.is_active is True
    assert tenant.is_demo is False


def test_existing_workspaces_are_untouched_by_a_template_change(db_session, identity):
    before = (identity.tenant_a.workspace_template, identity.tenant_a.name)
    service = PlatformSettingsService(db_session)
    service.update(
        _owner_principal(identity),
        default_workspace_template="standard",
        uploaded_script_retention_days=30,
        audit_view_allowed_account_types=["owner"],
        expected_version=1,
    )
    db_session.commit()
    db_session.expire_all()
    tenant = db_session.get(Tenant, identity.tenant_a.id)
    assert (tenant.workspace_template, tenant.name) == before


def test_invalid_stored_template_falls_back_and_is_audited(db_session, identity):
    row = PlatformSettingsService(db_session).ensure()
    row.default_workspace_template = "removed-profile"
    db_session.commit()

    tenant = WorkspaceCreationService(db_session).create(name="Delta", slug="delta")
    db_session.commit()
    assert tenant.workspace_template == "standard"
    fallback = db_session.scalars(
        select(AuditEvent).where(
            AuditEvent.action == "platform.settings.workspace_template.fallback"
        )
    ).all()
    assert len(fallback) == 1
    assert fallback[0].detail["configured_template"] == "removed-profile"


def _owner_principal(identity):
    from app.core.security import Principal

    return Principal(
        user_id=identity.user_a.id,
        tenant_id=identity.tenant_a.id,
        subject=identity.user_a.subject,
        role="PLATFORM_OWNER",
        platform_role="PLATFORM_OWNER",
    )


# ---------------------------------------------------------------------------
# Audit-view permissions
# ---------------------------------------------------------------------------


def test_operator_audit_access_follows_the_setting(
    client, auth_headers, platform_owner, platform_operator
):
    denied = client.get("/api/v1/admin/audit", headers=auth_headers(platform_operator))
    assert denied.status_code == 403

    saved = client.put(
        "/api/v1/admin/settings",
        headers=auth_headers(platform_owner),
        json={
            "default_workspace_template": "standard",
            "uploaded_script_retention_days": 365,
            "audit_view_allowed_account_types": ["owner", "platform_operator"],
            "expected_version": 1,
        },
    )
    assert saved.status_code == 200

    permitted = client.get("/api/v1/admin/audit", headers=auth_headers(platform_operator))
    assert permitted.status_code == 200


def test_workspace_member_never_gains_the_cross_tenant_ledger(
    client, auth_headers, identity, platform_owner
):
    client.put(
        "/api/v1/admin/settings",
        headers=auth_headers(platform_owner),
        json={
            "default_workspace_template": "standard",
            "uploaded_script_retention_days": 365,
            "audit_view_allowed_account_types": ["owner", "platform_operator"],
            "expected_version": 1,
        },
    )
    response = client.get("/api/v1/admin/audit", headers=auth_headers(identity.user_a))
    assert response.status_code == 403
    # Their own workspace ledger remains readable.
    own = client.get(
        f"/api/v1/workspaces/{identity.tenant_a.id}/audit",
        headers=auth_headers(identity.user_a),
    )
    assert own.status_code == 200


# ---------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------


def _student_document(db_session, tenant_id, submission_id, *, age_days=400, key=None):
    identifier = key or f"documents/{tenant_id}/script.pdf"
    document = Document(
        tenant_id=tenant_id,
        submission_id=submission_id,
        kind="STUDENT",
        storage_key=identifier,
        original_filename="script.pdf",
        sha256="c" * 64,
        mime_type="application/pdf",
        size_bytes=11,
        page_count=1,
        status="PROCESSED",
        created_at=utcnow() - timedelta(days=age_days),
    )
    db_session.add(document)
    db_session.flush()
    page = DocumentPage(
        tenant_id=tenant_id,
        document_id=document.id,
        page_index=1,
        storage_key=f"{identifier}.p1.png",
        width=100,
        height=100,
        quality_status="READABLE",
        checksum="d" * 64,
    )
    db_session.add(page)
    db_session.commit()
    return document, page


def _job(db_session, paper, *, state: str, tenant_id):
    job = CorrectionJob(
        tenant_id=tenant_id,
        assignment_id=paper.assignment.id,
        submission_id=paper.submission.id,
        blueprint_version_id=paper.blueprint.id,
        scheme_version_id=paper.scheme_version.id,
        state=state,
        idempotency_key=f"job-{state}-{utcnow().timestamp()}",
        request_hash="e" * 64,
    )
    db_session.add(job)
    db_session.commit()
    return job


def test_retention_preview_and_idempotent_purge(db_session, paper, tmp_path):
    storage = LocalStorage(tmp_path)
    document, page = _student_document(db_session, paper.exam.tenant_id, paper.submission.id)
    storage.put(document.storage_key, b"script-bytes", "application/pdf")
    storage.put(page.storage_key, b"page-bytes", "image/png")

    service = RetentionService(db_session, storage)
    preview = service.preview()
    assert preview.eligible_documents == 1
    assert preview.eligible_pages == 1
    assert preview.eligible_bytes == 11
    assert preview.protected == {}

    outcome = service.sweep(
        _owner_principal_from_paper(paper), limit=10, expected_retention_days=365
    )
    db_session.commit()
    assert outcome.purged_documents == 1
    assert outcome.purged_pages == 1
    db_session.refresh(document)
    db_session.refresh(page)
    assert document.storage_purged_at is not None
    assert page.storage_purged_at is not None
    with pytest.raises(StorageError):
        storage.read(document.storage_key)

    # Metadata kept, so the record of what was ingested survives.
    assert db_session.get(Document, document.id) is not None
    events = db_session.scalars(
        select(AuditEvent).where(AuditEvent.action == "document.storage_purged")
    ).all()
    assert len(events) == 1
    assert events[0].detail["sha256"] == document.sha256

    again = service.sweep(_owner_principal_from_paper(paper), limit=10, expected_retention_days=365)
    db_session.commit()
    assert again.purged_documents == 0


def test_active_job_and_approved_grade_are_protected(db_session, paper, tmp_path):
    storage = LocalStorage(tmp_path)
    active_doc, _ = _student_document(
        db_session, paper.exam.tenant_id, paper.submission.id, key="documents/active.pdf"
    )
    _job(db_session, paper, state="CORRECTING", tenant_id=paper.exam.tenant_id)

    preview = RetentionService(db_session, storage).preview()
    assert preview.eligible_documents == 0
    assert preview.protected.get("active correction job") == 1

    # Approve a completed job for a second submission and check it is protected.
    from app.db.models import Submission

    other = Submission(
        tenant_id=paper.exam.tenant_id,
        assignment_id=paper.assignment.id,
        student_ref="student-2",
        status="PROCESSED",
        content_hash="f" * 64,
    )
    db_session.add(other)
    db_session.commit()
    approved_doc, _ = _student_document(
        db_session, paper.exam.tenant_id, other.id, key="documents/approved.pdf"
    )
    completed = CorrectionJob(
        tenant_id=paper.exam.tenant_id,
        assignment_id=paper.assignment.id,
        submission_id=other.id,
        blueprint_version_id=paper.blueprint.id,
        scheme_version_id=paper.scheme_version.id,
        state="COMPLETED",
        idempotency_key="approved-job",
        request_hash="a" * 64,
    )
    db_session.add(completed)
    db_session.flush()
    db_session.add(
        JobApproval(
            tenant_id=paper.exam.tenant_id,
            job_id=completed.id,
            approved_at=utcnow(),
            approved_marks=9,
            total_marks=10,
        )
    )
    db_session.commit()

    preview = RetentionService(db_session, storage).preview()
    assert preview.eligible_documents == 0
    assert preview.protected.get("approved grades") == 1

    outcome = RetentionService(db_session, storage).sweep(
        _owner_principal_from_paper(paper), limit=10, expected_retention_days=365
    )
    assert outcome.purged_documents == 0
    db_session.refresh(active_doc)
    db_session.refresh(approved_doc)
    assert active_doc.storage_purged_at is None
    assert approved_doc.storage_purged_at is None


def test_recent_and_non_student_documents_are_not_eligible(db_session, paper, tmp_path):
    storage = LocalStorage(tmp_path)
    _student_document(
        db_session,
        paper.exam.tenant_id,
        paper.submission.id,
        age_days=1,
        key="documents/recent.pdf",
    )
    scheme = Document(
        tenant_id=paper.exam.tenant_id,
        exam_id=paper.exam.id,
        kind="MARK_SCHEME",
        storage_key="documents/scheme.pdf",
        original_filename="scheme.pdf",
        sha256="b" * 64,
        mime_type="application/pdf",
        size_bytes=3,
        page_count=1,
        status="PROCESSED",
        created_at=utcnow() - timedelta(days=400),
    )
    db_session.add(scheme)
    db_session.commit()

    preview = RetentionService(db_session, storage).preview()
    assert preview.eligible_documents == 0


def test_sweep_refuses_a_stale_retention_window(db_session, paper, tmp_path):
    service = RetentionService(db_session, LocalStorage(tmp_path))
    from app.core.errors import AppError

    with pytest.raises(AppError) as error:
        service.sweep(_owner_principal_from_paper(paper), limit=10, expected_retention_days=30)
    assert error.value.code == "CONFLICT"


def _owner_principal_from_paper(paper):
    from app.core.security import Principal

    return Principal(
        user_id=paper.submission.id,
        tenant_id=paper.exam.tenant_id,
        subject="platform-owner",
        role="PLATFORM_OWNER",
        platform_role="PLATFORM_OWNER",
    )
