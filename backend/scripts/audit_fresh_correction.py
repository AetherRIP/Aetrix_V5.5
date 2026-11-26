"""Audit one correction job against the sources and the ledger.

Reads only.  It answers the questions a green HTTP 200 cannot:

* is every scoreable leaf present, and does it have a max and an award?
* does the award reconcile with the question's own component marks?
* do the maxima sum to the approved blueprint, and the awards to the stored total?
* is there stored evidence, and does it name a page?
* what did each provider attempt cost, and which model produced each row?

Usage::

    python scripts/audit_fresh_correction.py <job-id>
"""

from __future__ import annotations

import json
import sys
import uuid
from collections import Counter

from app.core.config import get_settings
from app.correction.aetrix.pipeline import _leaf_questions
from app.db.models import (
    CriterionResult,
    Document,
    DocumentPage,
    ExamBlueprintVersion,
    MarkingEvidence,
    ProviderResponse,
    ProviderUsage,
    QuestionResult,
)
from app.db.session import session_scope
from app.schemas.blueprint import BlueprintStructure
from sqlalchemy import select


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: audit_fresh_correction.py <job-id>")
    job_id = uuid.UUID(sys.argv[1])

    with session_scope() as session:
        from app.db.models import CorrectionJob, Submission

        job = session.get(CorrectionJob, job_id)
        if job is None:
            raise SystemExit("no such job")
        submission = session.get(Submission, job.submission_id)
        blueprint = session.get(ExamBlueprintVersion, job.blueprint_version_id)
        structure = BlueprintStructure.model_validate(blueprint.structure)
        leaves = _leaf_questions(structure)
        expected = {leaf[0]: leaf[1] for leaf in leaves}

        rows = session.scalars(
            select(QuestionResult)
            .where(QuestionResult.job_id == job_id)
            .order_by(QuestionResult.question_id)
        ).all()
        by_question = {row.question_id: row for row in rows}
        row_ids = [row.id for row in rows]

        criteria = session.scalars(
            select(CriterionResult).where(CriterionResult.question_result_id.in_(row_ids))
        ).all()
        from app.db.models import MarkingCriterion

        criterion_marks = {
            item.id: item.marks
            for item in session.scalars(
                select(MarkingCriterion).where(
                    MarkingCriterion.scheme_version_id == job.scheme_version_id
                )
            ).all()
        }
        criteria_by_row: dict[uuid.UUID, list[CriterionResult]] = {}
        for criterion in criteria:
            criteria_by_row.setdefault(criterion.question_result_id, []).append(criterion)

        evidence = session.scalars(
            select(MarkingEvidence).where(MarkingEvidence.question_result_id.in_(row_ids))
        ).all()
        evidence_by_row: dict[uuid.UUID, list[MarkingEvidence]] = {}
        for item in evidence:
            evidence_by_row.setdefault(item.question_result_id, []).append(item)

        usage = session.scalars(
            select(ProviderUsage)
            .where(ProviderUsage.job_id == job_id)
            .order_by(ProviderUsage.created_at)
        ).all()
        archives = session.scalars(
            select(ProviderResponse).where(ProviderResponse.job_id == job_id)
        ).all()

        pages = {
            page.id: page
            for page in session.scalars(
                select(DocumentPage).where(
                    DocumentPage.document_id.in_(
                        select(Document.id).where(Document.submission_id == job.submission_id)
                    )
                )
            ).all()
        }

        table = []
        component_mismatches = []
        over_max = []
        zero_mark = 0
        partial = 0
        with_evidence = 0
        evidence_missing_page = 0
        unlinked_rows = 0

        for question_id, max_marks in expected.items():
            row = by_question.get(question_id)
            if row is None:
                table.append(
                    {
                        "question": question_id,
                        "max": max_marks,
                        "awarded": None,
                        "model": None,
                        "validation": "MISSING",
                        "evidence": "none",
                        "review": "no row stored",
                    }
                )
                continue
            row_criteria = criteria_by_row.get(row.id, [])
            # A component's value is the scheme criterion's own mark value.  A
            # whole-paper reply names criterion *codes*, so the stored rows can
            # carry no criterion_id; when that is the case the component total
            # cannot be recomputed from the links and the engine's own integrity
            # finding is the authority.  Reporting a guessed zero as a mismatch
            # would invent 38 defects.
            linked = [item for item in row_criteria if item.criterion_id is not None]
            unlinked_rows += 1 if row_criteria and not linked else 0
            component_sum = (
                sum(
                    criterion_marks.get(item.criterion_id, 0)
                    for item in linked
                    if item.awarded
                )
                if linked
                else None
            )
            if component_sum is not None and component_sum != row.awarded_marks:
                component_mismatches.append(
                    {
                        "question": question_id,
                        "awarded": row.awarded_marks,
                        "components": component_sum,
                    }
                )
            if row.awarded_marks > row.max_marks:
                over_max.append(
                    {"question": question_id, "awarded": row.awarded_marks, "max": row.max_marks}
                )
            if row.awarded_marks == 0:
                zero_mark += 1
            elif row.awarded_marks < row.max_marks:
                partial += 1

            row_evidence = evidence_by_row.get(row.id, [])
            if row_evidence:
                with_evidence += 1
                if any(item.page_id is None for item in row_evidence):
                    evidence_missing_page += 1

            usage_row = next((u for u in usage if u.id == row.provider_usage_id), None)
            table.append(
                {
                    "question": question_id,
                    "max": row.max_marks,
                    "awarded": row.awarded_marks,
                    "model": usage_row.model if usage_row else None,
                    "validation": row.status,
                    "processing_state": row.processing_state,
                    "anomaly": row.normalisation_anomaly,
                    "evidence": (
                        f"{len(row_evidence)} item(s)"
                        + (
                            ""
                            if not row_evidence
                            else ", p"
                            + ",".join(
                                str(pages[item.page_id].page_index + 1)
                                for item in row_evidence
                                if item.page_id in pages
                            )
                        )
                    ),
                    "review": row.review_required,
                    "confidence": float(row.confidence or 0),
                    "component_sum": component_sum,
                    "components": len(row_criteria),
                    "source": row.response_source,
                }
            )

        awarded_total = sum(row.awarded_marks for row in rows)
        max_total = sum(row.max_marks for row in rows)
        expected_total = sum(expected.values())

        report = {
            "job": {
                "id": str(job.id),
                "state": job.state,
                "submission_id": str(job.submission_id),
                "student_ref": submission.student_ref if submission else None,
                "marking_mode": job.marking_mode,
                "engine": f"{job.engine_name}:{job.engine_version}",
                "primary_model": job.primary_model,
                "secondary_model": job.secondary_model,
                "result_source": job.result_source,
                "idempotency_key": job.idempotency_key,
                "created_at": str(job.created_at),
                "started_at": str(job.started_at),
                "finished_at": str(job.finished_at),
                "error_code": job.error_code,
            },
            "scores": {
                "scoreable_leaves": len(expected),
                "rows_stored": len(rows),
                "missing_leaves": len(expected) - len(rows),
                "expected_max_total": expected_total,
                "stored_max_total": max_total,
                "awarded_total": awarded_total,
                "blueprint_total_marks": blueprint.total_marks,
                "max_matches_blueprint": max_total == blueprint.total_marks,
                # There is no stored job total column in this schema, so the
                # reconciliation is between the rows' awards and their own
                # normalised values, plus the maxima against the blueprint.
                "awarded_equals_normalised": awarded_total
                == sum(int(row.normalised_awarded_marks or 0) for row in rows),
                "normalised_differs_from_raw": sum(
                    1 for row in rows if row.raw_awarded_marks != row.awarded_marks
                ),
                "full_mark_rows": sum(1 for r in rows if r.awarded_marks == r.max_marks),
                "partial_rows": partial,
                "zero_rows": zero_mark,
                "review_required_rows": sum(1 for r in rows if r.review_required),
            },
            "component_mismatches": component_mismatches,
            "component_check": (
                "UNAVAILABLE" if unlinked_rows else "COMPARED"
            ),
            "rows_without_criterion_id": unlinked_rows,
            "over_max_awards": over_max,
            "evidence": {
                "rows_with_evidence": with_evidence,
                "rows_without_evidence": len(rows) - with_evidence,
                "rows_whose_evidence_names_no_page": evidence_missing_page,
            },
            "provider_requests": [
                {
                    "model": item.model,
                    "role": item.model_role,
                    "chain_position": item.model_chain_position,
                    "attempt": item.attempt_index,
                    "decision": item.routing_decision,
                    "success": item.success,
                    "http": item.http_status,
                    "in": item.input_tokens,
                    "out": item.output_tokens,
                    "cached": item.cached_tokens,
                    "cost_usd": float(item.cost_usd) if item.cost_usd is not None else None,
                    "cost_status": item.cost_status,
                    "latency_ms": item.latency_ms,
                    "purpose": item.purpose,
                    "request_id": item.request_id,
                    "at": str(item.created_at),
                }
                for item in usage
            ],
            "archives": [
                {
                    "id": str(item.id),
                    "source": item.response_source,
                    "sequence": item.sequence,
                    "sha256": item.content_sha256,
                    "bytes": item.content_length,
                    "model": item.model,
                    "truncated": item.body_truncated,
                    "finish_reason": item.finish_reason,
                }
                for item in archives
            ],
            "status_counts": dict(Counter(row.status for row in rows)),
            "questions": table,
        }

    tokens_in = sum(item.input_tokens or 0 for item in usage)
    tokens_out = sum(item.output_tokens or 0 for item in usage)
    report["totals"] = {
        "requests": len(usage),
        "successful": sum(1 for item in usage if item.success),
        "failed": sum(1 for item in usage if not item.success),
        "input_tokens": tokens_in,
        "output_tokens": tokens_out,
        "cost_usd_known": sum(float(item.cost_usd) for item in usage if item.cost_usd),
        "cost_unknown_requests": sum(1 for item in usage if item.cost_status == "COST_UNKNOWN"),
    }
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
