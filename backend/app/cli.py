"""Small operational CLI.

``seed-dev`` creates the development tenant and user referenced by
``AETRIX_AUTH__DEV_*``.  It creates identity rows only; it does not create papers
or marks, and it is refused in production.
"""

from __future__ import annotations

import argparse
import uuid

from .core.config import Environment, get_settings
from .db.models import Tenant, User
from .db.repositories import TenantRepository, UserRepository
from .db.session import session_scope


def create_tenant(name: str, slug: str) -> None:
    with session_scope() as session:
        tenant = TenantRepository(session).create(name=name, slug=slug)
        print(f"tenant {tenant.id} {tenant.slug}")


def create_user(tenant_id: uuid.UUID, subject: str, role: str) -> None:
    with session_scope() as session:
        user = UserRepository(session).create(tenant_id=tenant_id, subject=subject, role=role)
        print(f"user {user.id} tenant={user.tenant_id} role={user.role}")


def seed_dev() -> None:
    settings = get_settings()
    if settings.env is Environment.PRODUCTION:
        raise SystemExit("refusing to seed development identity in production")
    tenant_id = settings.auth.dev_tenant_id
    user_id = settings.auth.dev_user_id
    if not tenant_id or not user_id:
        raise SystemExit("AETRIX_AUTH__DEV_TENANT_ID and DEV_USER_ID are required")

    with session_scope() as session:
        tenant = session.get(Tenant, tenant_id)
        if tenant is None:
            tenant = Tenant(id=tenant_id, name="Development workspace", slug="dev")
            session.add(tenant)
            session.flush()
        user = session.get(User, user_id)
        if user is None:
            user = User(
                id=user_id,
                tenant_id=tenant_id,
                subject="dev-user",
                role="OWNER",
                display_name="Development owner",
            )
            session.add(user)
            session.flush()
    print(f"development tenant={tenant_id} user={user_id}")


def show_job(job_id: uuid.UUID) -> None:
    from .db.models import CorrectionJob

    with session_scope() as session:
        job = session.get(CorrectionJob, job_id)
        if job is None:
            raise SystemExit("job not found")
        print(
            f"{job.id} tenant={job.tenant_id} state={job.state} "
            f"attempts={job.attempts}/{job.max_attempts} error={job.error_code}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(prog="aetrix")
    sub = parser.add_subparsers(dest="command", required=True)

    tenant_parser = sub.add_parser("create-tenant")
    tenant_parser.add_argument("--name", required=True)
    tenant_parser.add_argument("--slug", required=True)

    user_parser = sub.add_parser("create-user")
    user_parser.add_argument("--tenant", required=True, type=uuid.UUID)
    user_parser.add_argument("--subject", required=True)
    user_parser.add_argument(
        "--role", default="TEACHER", choices=["OWNER", "ADMIN", "TEACHER", "REVIEWER", "VIEWER"]
    )

    sub.add_parser("seed-dev")

    job_parser = sub.add_parser("show-job")
    job_parser.add_argument("job_id", type=uuid.UUID)

    args = parser.parse_args()
    if args.command == "create-tenant":
        create_tenant(args.name, args.slug)
    elif args.command == "create-user":
        create_user(args.tenant, args.subject, args.role)
    elif args.command == "seed-dev":
        seed_dev()
    elif args.command == "show-job":
        show_job(args.job_id)


if __name__ == "__main__":
    main()
