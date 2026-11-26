"""Run the one authorised pilot correction through the production engine.

This is a supervised operational step, not part of the product:

1. it re-checks the pilot's own gates (approved blueprint and scheme, seven
   readable pages);
2. it maps the document's questions to pages with the same ``PageQuestionMapper``
   the API route uses;
3. it creates ONE correction job in ``WHOLE_PAPER`` mode — one paid request
   instead of thirty-nine — and runs it with ``AetrixEngine()``, the object the
   worker itself builds, so the pinned credential, the role permissions and the
   quota ledger all apply exactly as in production.

It refuses to run if a job for this submission already produced marks, and it
never rewrites, approves or publishes anything.  A provider refusal is printed
as the engine reported it, because a pilot that hides a 429 proves nothing.

Usage::

    python scripts/pilot_controlled_correction.py            # map and mark
    python scripts/pilot_controlled_correction.py --dry-run  # check gates only
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid

from app.core.config import get_settings
from app.core.security import Principal
from app.correction.engine.aetrix import AetrixEngine
from app.db.models import Assignment, CorrectionJob, Submission, User
from app.db.session import get_session_factory
from app.documents.mapping import PageQuestionMapper
from app.jobs.service import JobService
from app.prompts.registry import PromptRegistry
from app.providers import build_provider
from app.schemas.api import CorrectionCreate
from app.services.provider_calls import ProviderCallService
from app.storage import build_storage
from sqlalchemy import select, text

#: The pilot student's already-ingested submission and document.
SUBMISSION = uuid.UUID("3fcdb919-10c9-4c25-b154-833227b48c8d")
DOCUMENT = uuid.UUID("9cf7da67-e920-4962-9960-25ae50d333b4")

#: Hard ceiling on paid generation requests for this pilot.
REQUEST_BUDGET = 20

#: The pilot's approved scheme total, used as a gate rather than a claim.
EXPECTED_MARKS = 89


def _refuse(message: str) -> int:
    print(f"REFUSED: {message}", file=sys.stderr)
    return 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="check gates only")
    arguments = parser.parse_args()

    settings = get_settings()
    if not settings.features.live_provider:
        return _refuse("features.live_provider is off; nothing would be sent")
    pinned = settings.provider.pinned_credential_id
    if pinned is None:
        return _refuse(
            "no pinned credential: set AETRIX_PROVIDER__PINNED_CREDENTIAL_ID so "
            "the pilot cannot rotate keys"
        )

    factory = get_session_factory(settings)
    with factory() as session:
        submission = session.get(Submission, SUBMISSION)
        if submission is None:
            return _refuse("the pilot submission does not exist")
        assignment = session.get(Assignment, submission.assignment_id)
        if assignment is None:
            return _refuse("the pilot submission has no assignment")

        pages = session.execute(
            text(
                "select page_index, quality_status from document_pages "
                "where document_id = :d order by page_index"
            ),
            {"d": DOCUMENT},
        ).all()
        readable = [row for row in pages if row[1] == "READABLE"]
        if len(pages) != 7 or len(readable) != 7:
            return _refuse(
                f"expected 7 readable pages, found {len(readable)} readable of {len(pages)}"
            )

        blueprint = session.execute(
            text(
                "select id, status, total_marks from exam_blueprint_versions where id = :i"
            ),
            {"i": assignment.blueprint_version_id},
        ).one()
        scheme = session.execute(
            text(
                "select id, status, criteria_approved_at, criteria_rules_hash "
                "from mark_scheme_versions where id = :i"
            ),
            {"i": assignment.scheme_version_id},
        ).one()
        if blueprint[1] != "APPROVED" or scheme[1] != "APPROVED":
            return _refuse(f"blueprint {blueprint[1]}, scheme {scheme[1]}")
        if scheme[2] is None or scheme[3] is None:
            return _refuse("the scheme's criteria are not approved for marking")
        awarded = session.execute(
            text(
                "select count(*), coalesce(sum(marks), 0) from marking_criteria "
                "where scheme_version_id = :i"
            ),
            {"i": assignment.scheme_version_id},
        ).one()
        if int(awarded[1]) != EXPECTED_MARKS:
            return _refuse(f"scheme totals {awarded[1]} marks, expected {EXPECTED_MARKS}")

        existing = session.execute(
            text(
                "select j.id, (select count(*) from question_results q "
                "where q.job_id = j.id) from correction_jobs j "
                "where j.submission_id = :s"
            ),
            {"s": SUBMISSION},
        ).all()
        if any(row[1] for row in existing):
            return _refuse("this submission already has marks; refusing to re-mark")

        owner = session.scalars(
            select(User)
            .where(User.tenant_id == assignment.tenant_id)
            .where(User.role.in_(("OWNER", "TEACHER")))
            .limit(1)
        ).first()
        if owner is None:
            return _refuse("no marker-capable user in the pilot workspace")
        principal = Principal(
            user_id=owner.id, tenant_id=owner.tenant_id,
            subject=owner.subject, role=owner.role,
        )

        storage = build_storage(settings)
        mapped = session.execute(
            text("select count(*) from page_question_mappings where document_id = :d"),
            {"d": DOCUMENT},
        ).scalar()

        print(
            json.dumps(
                {
                    "submission": str(submission.id),
                    "student_ref": submission.student_ref,
                    "pages_readable": len(readable),
                    "blueprint_total_marks": blueprint[2],
                    "criteria": int(awarded[0]),
                    "existing_mappings": int(mapped),
                    "existing_jobs": len(existing),
                    "pinned_credential": str(pinned),
                    "request_budget": REQUEST_BUDGET,
                },
                indent=2,
            )
        )
        if arguments.dry_run:
            return 0

        if not mapped:
            provider = build_provider(settings)
            calls = ProviderCallService(
                session, settings, provider, PromptRegistry(settings.provider.prompt_root)
            )
            mapper = PageQuestionMapper(session, settings, storage, provider_calls=calls)
            result = mapper.map(
                principal.tenant_id, DOCUMENT, assignment.blueprint_version_id
            )
            session.commit()
            print(
                json.dumps(
                    {
                        "mapping_status": result.status,
                        "mapping_reasons": result.reasons,
                        "mappings": len(result.mappings),
                    },
                    indent=2,
                    default=str,
                )
            )
            if not result.mappings:
                return _refuse("mapping produced nothing; refusing to mark unmapped pages")

        created = JobService(session, settings).create(
            principal,
            CorrectionCreate(
                assignment_id=assignment.id,
                submission_id=submission.id,
                idempotency_key=f"pilot-0039-{uuid.uuid4().hex[:8]}",
                marking_mode="WHOLE_PAPER",
            ),
        )
        job_id = created.job.id
        print(json.dumps({"job_id": str(job_id), "mode": "WHOLE_PAPER"}))

    with factory() as session:
        job = session.get(CorrectionJob, job_id)
        job.state = "CORRECTING"
        session.commit()
        failure = None
        try:
            AetrixEngine().run(job, session, settings)
        except Exception as error:  # the operator must see the engine's own refusal
            failure = f"{type(error).__name__}: {error}"
        session.expire_all()
        stored = session.get(CorrectionJob, job.id)
        results = session.execute(
            text(
                "select status, count(*) from question_results where job_id = :j "
                "group by 1 order by 1"
            ),
            {"j": job_id},
        ).all()
        usage = session.execute(
            text(
                "select model, success, http_status, error_class, provider_code "
                "from provider_usage where job_id = :j order by created_at"
            ),
            {"j": job_id},
        ).all()
        print(
            json.dumps(
                {
                    "failure": failure,
                    "state": stored.state,
                    "error_code": stored.error_code,
                    "error_message": stored.error_message,
                    "verification_status": stored.verification_status,
                    "double_check_status": stored.double_check_status,
                    "results": {row[0]: row[1] for row in results},
                    "generation_requests": len(usage),
                    "budget_remaining": max(0, REQUEST_BUDGET - len(usage)),
                    "usage": [
                        {
                            "model": row[0],
                            "success": row[1],
                            "http_status": row[2],
                            "error_class": row[3],
                            "provider_code": row[4],
                        }
                        for row in usage
                    ],
                },
                indent=2,
                default=str,
            )
        )
        if len(usage) > REQUEST_BUDGET:
            print(
                f"BUDGET EXCEEDED: {len(usage)} requests against {REQUEST_BUDGET}",
                file=sys.stderr,
            )
            return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
