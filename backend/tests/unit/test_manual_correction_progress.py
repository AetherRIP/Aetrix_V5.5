from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

from app.core.security import Principal
from app.schemas.blueprint import BlueprintStructure
from app.services.manual_corrections import ManualCorrectionInput, ManualCorrectionService
from app.services.progress import ProgressService


def _input(student: bytes = b"student", scheme: bytes = b"scheme") -> ManualCorrectionInput:
    return ManualCorrectionInput(
        student_ref="Script A",
        board="Edexcel",
        subject="Mathematics",
        qualification="A Level",
        paper_code="9MA0/01",
        marking_mode="PER_QUESTION",
        student_filename="script.pdf",
        student_mime="application/pdf",
        student_bytes=student,
        scheme_filename="scheme.pdf",
        scheme_mime="application/pdf",
        scheme_bytes=scheme,
    )


def test_manual_idempotency_is_stable_and_content_sensitive() -> None:
    principal = Principal(
        user_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        subject="subject",
        role="REVIEWER",
    )
    service = ManualCorrectionService.__new__(ManualCorrectionService)
    first = service._idempotency_key(principal, _input())
    second = service._idempotency_key(principal, _input())
    changed = service._idempotency_key(principal, _input(student=b"other"))

    assert first == second
    assert first.startswith("manual:")
    assert changed != first


def test_manual_assignment_uses_a_supported_review_mode() -> None:
    assert ManualCorrectionService._review_mode("PER_QUESTION") == "BALANCED"
    assert ManualCorrectionService._review_mode("WHOLE_PAPER") == "BALANCED"
    assert ManualCorrectionService._review_mode("PARALLEL") == "BALANCED"


def test_progress_leaf_marks_follow_the_engine_leaf_enumeration() -> None:
    structure = BlueprintStructure.model_validate(
        {
            "questions": [
                {"question_id": "1", "max_marks": 3},
                {
                    "question_id": "2",
                    "max_marks": 5,
                    "subquestions": [
                        {"question_id": "2a", "max_marks": 2},
                        {"question_id": "2b", "max_marks": 3},
                    ],
                },
                {
                    "question_id": "3",
                    "max_marks": 4,
                    "excluded": True,
                    "exclusion_reason": "not sat",
                },
            ],
            "total_marks": 8,
        }
    )

    leaves = ProgressService._leaf_marks(structure)

    assert leaves == {"1": 3, "2a": 2, "2b": 3}
    assert list(leaves) == structure.scoreable_leaf_ids


def test_progress_elapsed_uses_stored_timestamps_only() -> None:
    start = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    end = datetime(2026, 1, 1, 12, 1, 42, tzinfo=UTC)
    job = SimpleNamespace(started_at=start, finished_at=end, created_at=start)

    assert ProgressService._elapsed(job) == 102


def test_progress_elapsed_reports_nothing_when_start_is_absent() -> None:
    job = SimpleNamespace(started_at=None, finished_at=None, created_at=None)

    assert ProgressService._elapsed(job) is None
