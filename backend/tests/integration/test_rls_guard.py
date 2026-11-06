"""Fail the build when a public table becomes reachable through the Data API.

The Supabase Data API reaches PostgreSQL as ``anon`` or ``authenticated``.
Nothing in this repository uses it, so ``0005_rls_lockdown`` revokes their
privileges and enables RLS without policies on every table in ``public``.

That guarantee is only as good as the last table somebody added: the lock-down
names its tables explicitly, so a migration that creates — or grants on — a
table afterwards would re-open the schema without touching that migration.
These tests assert the property globally instead of trusting that list.  They
read ``pg_class``, the effective ACLs and the default privileges, so the next
unprotected table fails CI rather than waiting for the Security Advisor to
report it.

The workflow that runs them (``.github/workflows/ci.yml``) creates the Data API
roles and reproduces Supabase's default grants before the migrations run, so a
missing ``REVOKE`` cannot pass by accident.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration

#: Roles the Data API authenticates as.
DATA_API_ROLES = ("anon", "authenticated")

#: Privileges that would let one of those roles read or write a table.
TABLE_PRIVILEGES = (
    "SELECT",
    "INSERT",
    "UPDATE",
    "DELETE",
    "TRUNCATE",
    "REFERENCES",
    "TRIGGER",
)

#: Privileges that would let them consume a sequence (``nextval``, ``currval``).
SEQUENCE_PRIVILEGES = ("USAGE", "SELECT", "UPDATE")

#: ``defaclobjtype`` codes that matter here.
DEFAULT_ACL_KINDS = {"r": "table", "S": "sequence"}

_TABLES = """
    SELECT c.relname, c.relrowsecurity
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
      AND c.relkind IN ('r', 'p')
    ORDER BY c.relname
"""


def _rows(engine, statement: str, **params: object) -> list[tuple]:
    with engine.connect() as connection:
        return [tuple(row) for row in connection.execute(text(statement), params).all()]


def _listing(lines: list[str]) -> str:
    return "\n".join(f"  - {line}" for line in sorted(lines))


def test_data_api_roles_exist(engine) -> None:
    """Without these roles every other assertion here would pass vacuously."""
    present = {row[0] for row in _rows(engine, "SELECT rolname FROM pg_roles")}
    missing = [role for role in DATA_API_ROLES if role not in present]
    assert not missing, (
        "the Data API roles do not exist, so this check cannot prove anything; "
        "create them before migrating (see .github/workflows/ci.yml): " + ", ".join(missing)
    )


def test_every_public_table_has_rls_enabled(engine) -> None:
    unprotected = [table for table, enabled in _rows(engine, _TABLES) if not enabled]
    assert not unprotected, (
        "public tables without RLS. Enable it in the migration that creates the "
        "table, or add the table to 0005_rls_lockdown:\n" + _listing(unprotected)
    )


def test_data_api_roles_hold_no_table_privileges(engine) -> None:
    offenders = [
        f"{role} holds {privilege} on public.{table}"
        for table, role, privilege in _rows(
            engine,
            """
            SELECT c.relname, r.role, p.privilege
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            CROSS JOIN unnest(CAST(:roles AS text[])) AS r(role)
            CROSS JOIN unnest(CAST(:privileges AS text[])) AS p(privilege)
            WHERE n.nspname = 'public'
              AND c.relkind IN ('r', 'p')
              AND has_table_privilege(r.role, c.oid, p.privilege)
            """,
            roles=list(DATA_API_ROLES),
            privileges=list(TABLE_PRIVILEGES),
        )
    ]
    assert not offenders, (
        "the Data API roles can still reach public tables; revoke them in the "
        "migration that adds the table:\n" + _listing(offenders)
    )


def test_data_api_roles_hold_no_sequence_privileges(engine) -> None:
    offenders = [
        f"{role} holds {privilege} on sequence public.{sequence}"
        for sequence, role, privilege in _rows(
            engine,
            """
            SELECT c.relname, r.role, p.privilege
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            CROSS JOIN unnest(CAST(:roles AS text[])) AS r(role)
            CROSS JOIN unnest(CAST(:privileges AS text[])) AS p(privilege)
            WHERE n.nspname = 'public'
              AND c.relkind = 'S'
              AND has_sequence_privilege(r.role, c.oid, p.privilege)
            """,
            roles=list(DATA_API_ROLES),
            privileges=list(SEQUENCE_PRIVILEGES),
        )
    ]
    assert not offenders, "the Data API roles can still consume public sequences:\n" + _listing(
        offenders
    )


def test_default_privileges_do_not_expose_future_tables(engine) -> None:
    """Catches the re-grant that would silently apply to every later table."""
    offenders = [
        f"{grantee} would be granted {privilege} on new public {DEFAULT_ACL_KINDS.get(kind, kind)}s"
        for kind, grantee, privilege in _rows(
            engine,
            """
            SELECT d.defaclobjtype::text,
                   CASE WHEN a.grantee = 0
                        THEN 'PUBLIC'
                        ELSE pg_get_userbyid(a.grantee)
                   END AS grantee,
                   a.privilege_type
            FROM pg_default_acl d
            JOIN pg_namespace n ON n.oid = d.defaclnamespace
            CROSS JOIN LATERAL aclexplode(d.defaclacl) AS a
            WHERE n.nspname = 'public'
              AND (a.grantee = 0
                   OR pg_get_userbyid(a.grantee) IN ('anon', 'authenticated'))
            """,
        )
    ]
    assert not offenders, (
        "default privileges in schema public still grant the Data API roles, so "
        "every table a later migration creates is exposed on creation:\n" + _listing(offenders)
    )
