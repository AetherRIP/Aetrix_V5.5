# ruff: noqa: E402 - the environment must be configured before app imports
"""Test configuration.

Integration tests run against a real PostgreSQL database — the same Supabase
project during development, or ``AETRIX_TEST_DATABASE_URL`` in CI.  There is no
SQLite fallback: the lease query uses PostgreSQL's ``FOR UPDATE SKIP LOCKED``,
and testing it on another dialect would not test the thing that matters.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import jwt

BACKEND = Path(__file__).resolve().parents[1]


def _dotenv_database_url() -> str:
    path = BACKEND / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("AETRIX_DATABASE__URL="):
                return line.split("=", 1)[1].strip()
    return ""


os.environ["AETRIX_ENV"] = "test"
if os.environ.get("AETRIX_TEST_DATABASE_URL"):
    os.environ["AETRIX_DATABASE__URL"] = os.environ["AETRIX_TEST_DATABASE_URL"]
elif not os.environ.get("AETRIX_DATABASE__URL"):
    os.environ["AETRIX_DATABASE__URL"] = _dotenv_database_url()
os.environ["AETRIX_AUTH__DEV_MODE"] = "false"
os.environ["AETRIX_AUTH__JWKS_URL"] = ""
os.environ["AETRIX_AUTH__JWT_SECRET"] = "test-secret-not-used-outside-tests"
os.environ["AETRIX_AUTH__JWT_AUDIENCE"] = "authenticated"
os.environ["AETRIX_AUTH__DEV_TENANT_ID"] = ""
os.environ["AETRIX_AUTH__DEV_USER_ID"] = ""
os.environ["AETRIX_SECURITY__ENCRYPTION_KEY"] = "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA="
os.environ["AETRIX_WORKER__HEARTBEAT_SECONDS"] = "5"
os.environ["AETRIX_WORKER__LEASE_SECONDS"] = "15"

import pytest
from alembic import command
from alembic.config import Config
from app.core.config import get_settings
from app.core.ids import content_hash, utcnow
from app.core.security import SecretBox, fingerprint
from app.db.base import Base
from app.db.models import (
    Assignment,
    Exam,
    ExamBlueprintVersion,
    MarkScheme,
    MarkSchemeVersion,
    ProviderCredential,
    Submission,
    Tenant,
    User,
)
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

BLUEPRINT_STRUCTURE = {
    "paper_code": "TEST-01",
    "questions": [
        {
            "question_id": "1",
            "label": "Question 1",
            "max_marks": 5,
            "answer_type": "numeric",
            "subquestions": [
                {"question_id": "1a", "max_marks": 2},
                {"question_id": "1b", "max_marks": 3},
            ],
        },
        {
            "question_id": "2",
            "label": "Question 2",
            "max_marks": 5,
            "answer_type": "working",
            "subquestions": [],
        },
    ],
    "total_marks": 10,
    "notes": [],
}


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> None:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    config.set_main_option("sqlalchemy.url", get_settings().database.dsn().replace("%", "%%"))
    command.upgrade(config, "head")


@pytest.fixture(scope="session")
def engine(migrated_database):
    database_engine = create_engine(get_settings().database.dsn(), pool_pre_ping=True)
    yield database_engine
    database_engine.dispose()


@pytest.fixture(autouse=True)
def clean_tables(engine):
    names = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
    statement = text(f"TRUNCATE TABLE {names} RESTART IDENTITY CASCADE")
    with engine.begin() as connection:
        connection.execute(statement)
    yield
    with engine.begin() as connection:
        connection.execute(statement)


@pytest.fixture
def db_session(engine, clean_tables):
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def session_factory(engine, clean_tables):
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture
def identity(db_session):
    tenant_a = Tenant(name="Alpha", slug="alpha")
    tenant_b = Tenant(name="Beta", slug="beta")
    db_session.add_all([tenant_a, tenant_b])
    db_session.flush()

    user_a = User(tenant_id=tenant_a.id, subject="teacher-a", role="OWNER")
    user_b = User(tenant_id=tenant_b.id, subject="teacher-b", role="OWNER")
    viewer = User(tenant_id=tenant_a.id, subject="viewer-a", role="VIEWER")
    db_session.add_all([user_a, user_b, viewer])
    db_session.commit()
    return SimpleNamespace(
        tenant_a=tenant_a,
        tenant_b=tenant_b,
        user_a=user_a,
        user_b=user_b,
        viewer=viewer,
    )


def _token_for(user: User) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": user.subject,
            "aud": "authenticated",
            "iat": now,
            "exp": now + timedelta(hours=1),
            "app_metadata": {"tenant_id": str(user.tenant_id)},
        },
        os.environ["AETRIX_AUTH__JWT_SECRET"],
        algorithm="HS256",
    )


@pytest.fixture
def auth_headers():
    def build(user: User) -> dict[str, str]:
        return {"Authorization": f"Bearer {_token_for(user)}"}

    return build


@pytest.fixture
def client(clean_tables, tmp_path):
    from app.core.config import StorageSettings
    from app.main import create_app
    from fastapi.testclient import TestClient

    settings = get_settings().model_copy(
        update={"storage": StorageSettings(root=tmp_path / "documents")}
    )
    application = create_app(settings)
    with TestClient(application) as test_client:
        yield test_client


@pytest.fixture
def provider_credential(identity, db_session) -> ProviderCredential:
    box = SecretBox(get_settings().security.encryption_key.get_secret_value())
    credential = ProviderCredential(
        tenant_id=identity.tenant_a.id,
        account_label="fixture-key",
        key_fingerprint=fingerprint("fixture-provider-key"),
        encrypted_secret=box.encrypt("fixture-provider-key"),
        model_access=[],
        health="HEALTHY",
    )
    db_session.add(credential)
    db_session.commit()
    return credential


@pytest.fixture
def paper(db_session, identity):
    exam = Exam(tenant_id=identity.tenant_a.id, title="Fixture paper")
    db_session.add(exam)
    db_session.flush()

    blueprint = ExamBlueprintVersion(
        tenant_id=identity.tenant_a.id,
        exam_id=exam.id,
        version=1,
        status="APPROVED",
        structure=BLUEPRINT_STRUCTURE,
        total_marks=10,
        content_hash=content_hash(BLUEPRINT_STRUCTURE),
        created_by=identity.user_a.id,
        approved_by=identity.user_a.id,
        approved_at=utcnow(),
        approval_reason="fixture",
    )
    db_session.add(blueprint)
    db_session.flush()

    scheme = MarkScheme(tenant_id=identity.tenant_a.id, exam_id=exam.id, title="Fixture scheme")
    db_session.add(scheme)
    db_session.flush()
    scheme_version = MarkSchemeVersion(
        tenant_id=identity.tenant_a.id,
        mark_scheme_id=scheme.id,
        version=1,
        status="APPROVED",
        source="FIXTURE",
        content_hash="a" * 64,
        approved_at=utcnow(),
    )
    db_session.add(scheme_version)
    db_session.flush()

    assignment = Assignment(
        tenant_id=identity.tenant_a.id,
        exam_id=exam.id,
        blueprint_version_id=blueprint.id,
        scheme_version_id=scheme_version.id,
        name="Fixture assignment",
        completion_threshold=0.8,
        review_mode="BALANCED",
        created_by=identity.user_a.id,
    )
    db_session.add(assignment)
    db_session.flush()

    submission = Submission(
        tenant_id=identity.tenant_a.id,
        assignment_id=assignment.id,
        student_ref="student-1",
        status="REGISTERED",
        content_hash="b" * 64,
    )
    db_session.add(submission)
    db_session.commit()

    return SimpleNamespace(
        exam=exam,
        blueprint=blueprint,
        scheme=scheme,
        scheme_version=scheme_version,
        assignment=assignment,
        submission=submission,
    )
