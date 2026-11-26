"""Prepare ONE completely fresh correction of ONE pilot student.

Everything a fresh correction needs is derived from the original sources: the
student's original PDF (re-read from storage and re-hashed), the approved
blueprint, the approved scheme and its approved criteria.  Nothing is copied
from an earlier correction — no marks, no transcriptions, no evidence, no
previous model reply.

The script therefore creates, and only creates:

* a new ``submissions`` row (new id, new student_ref, same source PDF digest);
* a fresh document for it, rendered from the original PDF by the same
  deterministic ingestion the upload route uses (new document id, new pages,
  new page images);
* a new ``correction_jobs`` row with a new idempotency key.

It never writes a mark, never reuses a page mapping or a transcription, and
never touches an existing job or result.  Marking itself is a separate,
supervised step so the job can be inspected before anything is paid for.

Usage::

    python scripts/fresh_pilot_correction.py            # select, verify, prepare
    python scripts/fresh_pilot_correction.py --dry-run  # select and verify only
"""

from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import sys
import uuid

from app.core.config import get_settings
from app.core.security import Principal
from app.correction.aetrix.pipeline import _leaf_questions
from app.db.models import (
    Document,
    ExamBlueprintVersion,
    MarkingCriterion,
    MarkSchemeVersion,
    Submission,
    User,
)
from app.db.session import session_scope
from app.documents.service import DocumentService
from app.jobs.service import JobService
from app.schemas.api import CorrectionCreate
from app.storage import build_storage
from sqlalchemy import func, select

#: The pilot assignment the five students were submitted under.
PILOT_ASSIGNMENT = "c2c0f961-1f81-4187-aeaf-420c98fc3f96"
PILOT_BLUEPRINT = "c371be84-d4a0-46de-a81d-38effccc2d15"
PILOT_SCHEME = "93eece22-864a-4de1-90e8-e37500ff2392"
EXPECTED_STUDENTS = 5
EXPECTED_TOTAL_MARKS = 89


def _select(session) -> list[Submission]:
    students = sorted(
        session.scalars(
            select(Submission).where(Submission.assignment_id == PILOT_ASSIGNMENT)
        ).all(),
        key=lambda row: row.student_ref,
    )
    if len(students) != EXPECTED_STUDENTS:
        raise SystemExit(
            f"expected {EXPECTED_STUDENTS} pilot submissions, found {len(students)}"
        )
    return students


def _source_document(session, submission_id: uuid.UUID) -> Document:
    document = session.scalar(
        select(Document).where(
            Document.submission_id == submission_id,
            Document.kind == "STUDENT",
        )
    )
    if document is None:
        raise SystemExit("the selected student has no student document")
    return document


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    arguments = parser.parse_args()

    settings = get_settings()
    storage = build_storage(settings)
    report: dict = {"selection": {}, "source": {}, "created": {}}

    with session_scope() as session:
        students = _select(session)
        # A uniform random draw over a sorted list: no score, no model result and
        # no difficulty is consulted, and the list order cannot bias the draw.
        chosen = secrets.choice(students)
        report["selection"] = {
            "method": "secrets.choice over the five pilot submissions sorted by student_ref",
            "student_ref": chosen.student_ref,
            "submission_id": str(chosen.id),
            "candidates": [row.student_ref for row in students],
        }

        document = _source_document(session, chosen.id)
        data = storage.read(document.storage_key)
        digest = hashlib.sha256(data).hexdigest()

        blueprint = session.get(ExamBlueprintVersion, PILOT_BLUEPRINT)
        scheme = session.get(MarkSchemeVersion, PILOT_SCHEME)
        structure = blueprint.structure
        leaves = _leaf_questions(_structure(structure))
        criteria_count, criteria_marks = session.execute(
            select(
                func.count(MarkingCriterion.id), func.coalesce(func.sum(MarkingCriterion.marks), 0)
            ).where(MarkingCriterion.scheme_version_id == PILOT_SCHEME)
        ).one()

        leaf_marks = sum(leaf[1] for leaf in leaves)
        ids = [leaf[0] for leaf in leaves]
        report["source"] = {
            "pdf_sha256": digest,
            "pdf_sha256_matches_stored": digest == document.sha256,
            "pdf_bytes": len(data),
            "pdf_pages": document.page_count,
            "original_filename": document.original_filename,
            "blueprint_version": blueprint.version,
            "blueprint_status": blueprint.status,
            "blueprint_total_marks": blueprint.total_marks,
            "blueprint_content_hash": blueprint.content_hash,
            "scheme_version": scheme.version,
            "scheme_status": scheme.status,
            "criteria_approved_at": str(scheme.criteria_approved_at),
            "criteria_rows": criteria_count,
            "criteria_marks": int(criteria_marks),
            "scoreable_leaves": len(leaves),
            "leaf_marks_total": leaf_marks,
            "q16d_present": "16(d)" in ids or "16d" in ids,
            "first_leaves": ids[:5],
            "last_leaves": ids[-5:],
        }

        problems = []
        if digest != document.sha256:
            problems.append("the stored PDF does not match its recorded digest")
        if blueprint.total_marks != EXPECTED_TOTAL_MARKS:
            problems.append("the blueprint total is not the expected 89 marks")
        if leaf_marks != blueprint.total_marks:
            problems.append("the scoreable leaves do not sum to the blueprint total")
        if int(criteria_marks) != blueprint.total_marks:
            problems.append("the approved criteria do not sum to the blueprint total")
        if document.page_count > settings.marking.whole_paper_max_pages:
            problems.append("the paper exceeds the whole-paper page cap")
        report["source"]["problems"] = problems
        if problems:
            print(json.dumps(report, indent=2, default=str))
            raise SystemExit("source verification failed; nothing was created")

        if arguments.dry_run:
            print(json.dumps(report, indent=2, default=str))
            return 0

        user = session.scalar(
            select(User).where(User.tenant_id == chosen.tenant_id).limit(1)
        )
        if user is None:
            raise SystemExit("the pilot workspace has no user to attribute the run to")
        principal = Principal(
            user_id=user.id,
            tenant_id=chosen.tenant_id,
            subject=user.subject,
            role=user.role,
        )

        stamp = uuid.uuid4().hex[:8]
        fresh = Submission(
            tenant_id=chosen.tenant_id,
            assignment_id=uuid.UUID(PILOT_ASSIGNMENT),
            student_ref=f"{chosen.student_ref}#fresh-{stamp}",
            status="REGISTERED",
            content_hash=chosen.content_hash,
        )
        session.add(fresh)
        session.commit()
        # Re-read the row so the job service compares the stored value, not one
        # this script still holds as an un-coerced string.
        session.expire(fresh)

        service = DocumentService(session, settings, storage)
        fresh_document = service.ingest_for_submission(
            principal,
            fresh.id,
            filename=document.original_filename,
            declared_mime=document.mime_type,
            data=data,
        )

        jobs = JobService(session, settings)
        creation = jobs.create(
            principal,
            CorrectionCreate(
                assignment_id=PILOT_ASSIGNMENT,
                submission_id=fresh.id,
                idempotency_key=f"fresh-{chosen.student_ref}-{stamp}",
            ),
        )
        report["created"] = {
            "submission_id": str(fresh.id),
            "student_ref": fresh.student_ref,
            "document_id": str(fresh_document.id),
            "document_pages": fresh_document.page_count,
            "document_sha256": fresh_document.sha256,
            "document_mapping_status": fresh_document.mapping_status,
            "job_id": str(creation.job.id),
            "job_state": creation.job.state,
            "job_marking_mode": creation.job.marking_mode,
            "idempotency_key": creation.job.idempotency_key,
            "created": creation.created,
        }

    print(json.dumps(report, indent=2, default=str))
    return 0


def _structure(raw: dict):
    from app.schemas.blueprint import BlueprintStructure

    return BlueprintStructure.model_validate(raw)


if __name__ == "__main__":
    sys.exit(main())
