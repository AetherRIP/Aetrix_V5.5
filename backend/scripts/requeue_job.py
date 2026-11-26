"""Requeue one parked correction job as a workspace reviewer.

The API is the normal way to retry a suspended job.  When it is not running (a
supervised pilot on a laptop) this performs the identical, audited transition
through ``JobService.retry``: the job returns to ``VALIDATING`` with a fresh
attempt budget, the previous state and error are written to the audit trail, and
nothing is marked, resumed in process, or edited in a result row.

Usage::

    python scripts/requeue_job.py <job-id>

Then start a worker (``python -m app.worker --once`` runs exactly one job).
"""

from __future__ import annotations

import argparse
import sys
import uuid

from app.core.config import get_settings
from app.core.security import Principal
from app.db.models import CorrectionJob, User
from app.db.session import get_session_factory
from app.jobs.service import JobService
from sqlalchemy import case, select

#: Roles the retry endpoint accepts, most privileged first.  ``ensure_reviewer``
#: accepts every one of them (``Principal.is_reviewer`` includes
#: ``PLATFORM_OWNER``), so the ordering picks a permitted actor and never widens
#: the permission.  A role the endpoint would refuse must not appear here.
REVIEWER_ROLES = ("PLATFORM_OWNER", "OWNER", "ADMIN", "TEACHER", "REVIEWER")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job_id", help="the parked correction job to requeue")
    arguments = parser.parse_args()

    settings = get_settings()
    factory = get_session_factory(settings)
    with factory() as session:
        job = session.get(CorrectionJob, uuid.UUID(arguments.job_id))
        if job is None:
            print("no such correction job", file=sys.stderr)
            return 2
        print(
            f"before: state={job.state} attempts={job.attempts} "
            f"error={job.error_code} marking_mode={job.marking_mode}",
            flush=True,
        )
        # Deterministic actor selection: most privileged permitted role first,
        # then the oldest account, then the id.  Ordering by ``role`` alone left
        # two REVIEWERs tied and the recorded actor depended on heap order.
        role_rank = case(
            {role: rank for rank, role in enumerate(REVIEWER_ROLES)},
            value=User.role,
            else_=len(REVIEWER_ROLES),
        )
        candidates = list(
            session.scalars(
                select(User)
                .where(User.tenant_id == job.tenant_id, User.role.in_(REVIEWER_ROLES))
                .order_by(role_rank, User.created_at, User.id)
            )
        )
        reviewer = candidates[0] if candidates else None
        if reviewer is None:
            print("this workspace has no reviewer account", file=sys.stderr)
            return 2
        print(
            f"actor: user:{reviewer.id} role={reviewer.role} "
            f"({len(candidates)} permitted account(s))",
            flush=True,
        )
        principal = Principal(
            user_id=reviewer.id,
            tenant_id=reviewer.tenant_id,
            subject=reviewer.subject,
            role=reviewer.role,
        )
        updated = JobService(session, settings).retry(principal, job.id)
        print(
            f"after: state={updated.state} attempts={updated.attempts} "
            f"recorded_as=user:{reviewer.id}",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
