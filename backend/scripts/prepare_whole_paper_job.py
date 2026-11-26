"""Arm an existing, still-unmarked job for whole-paper marking.

A job records the marking mode it was created under, and the pipeline never
switches a job that already has marks: a mode change mid-paper would mix two
provenances in one result set.  The pilot jobs were created while the deployment
default was per question, so a job that has produced nothing yet has to be
re-armed before it can be marked as one paper.

This refuses any job that already has question results or a successful
whole-paper provider call, so it cannot rewrite a decision or hide a paid reply.
It writes nothing unless ``--apply`` is given, and it never starts a worker.

Usage::

    python scripts/prepare_whole_paper_job.py <job-id>            # report only
    python scripts/prepare_whole_paper_job.py <job-id> --apply    # record the mode
"""

from __future__ import annotations

import argparse
import sys
import uuid

from app.core.config import get_settings
from app.db.models import CorrectionJob, ProviderUsage, QuestionResult
from app.db.session import get_session_factory
from sqlalchemy import func, select

#: The whole-paper prompt asset identity.  A successful call under it means the
#: paper has already been paid for and re-arming it would invite a second charge.
WHOLE_PAPER_PROMPT = "aetrix_v5_5_marking_whole_paper"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job_id", help="the correction job to arm")
    parser.add_argument(
        "--mode",
        default="WHOLE_PAPER",
        choices=("WHOLE_PAPER", "PER_QUESTION"),
        help="marking mode to record (default: WHOLE_PAPER)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write the mode; without it the script only reports",
    )
    arguments = parser.parse_args()

    settings = get_settings()
    with get_session_factory(settings)() as session:
        job = session.get(CorrectionJob, uuid.UUID(arguments.job_id))
        if job is None:
            print("no such correction job", file=sys.stderr)
            return 2
        results = session.scalar(
            select(func.count())
            .select_from(QuestionResult)
            .where(QuestionResult.job_id == job.id)
        )
        paid = session.scalar(
            select(func.count())
            .select_from(ProviderUsage)
            .where(
                ProviderUsage.job_id == job.id,
                ProviderUsage.success.is_(True),
            )
        )
        print(
            f"job: state={job.state} attempts={job.attempts} "
            f"error={job.error_code} marking_mode={job.marking_mode}",
            flush=True,
        )
        print(f"question_results={results} successful_provider_calls={paid}", flush=True)
        if results:
            print(
                "refused: this job already holds marks; changing its mode would mix "
                "two provenances in one result set.",
                file=sys.stderr,
            )
            return 3
        if job.marking_mode == arguments.mode:
            print(f"already recorded as {arguments.mode}; nothing to do", flush=True)
            return 0
        if not arguments.apply:
            print(
                f"would record marking_mode={arguments.mode} (rerun with --apply)",
                flush=True,
            )
            return 0
        before = job.marking_mode
        job.marking_mode = arguments.mode
        session.commit()
        print(f"recorded marking_mode={arguments.mode} (was {before})", flush=True)
        print(
            "next: python scripts/requeue_job.py "
            f"{job.id}  then  python -m app.worker --once",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
