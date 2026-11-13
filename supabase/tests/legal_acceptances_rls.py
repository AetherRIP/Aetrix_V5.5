"""Prove the legal_acceptances access rules against the configured database.

The rules are enforced by PostgreSQL, not by the browser, so they are verified
here as the roles a request actually runs as: ``anon`` and ``authenticated`` with
a JWT claim in ``request.jwt.claims``. That is exactly how Supabase's Data API
presents a signed-in request, without needing a real access token.

Run from the repository root with the engine's virtual environment:

    cd backend
    .venv/Scripts/python.exe ../supabase/tests/legal_acceptances_rls.py

It writes rows for two throwaway user ids and removes them at the end. It does
not touch any other table. Exit status 1 means at least one rule failed.
"""

from __future__ import annotations

import json
import sys
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from psycopg import sql as pg_sql
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.core.config import get_settings  # noqa: E402

USER_A = str(uuid.uuid4())
USER_B = str(uuid.uuid4())

failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"{status}  {name}{'' if condition else f'  -> {detail}'}")
    if not condition:
        failures.append(name)


def as_role(
    engine: Engine,
    role: str,
    user_id: str | None,
    action: Callable[[Any], Any],
) -> tuple[str, Any]:
    """Run ``action`` in a transaction as ``role`` and roll it back."""

    raw = engine.raw_connection()
    try:
        cursor = raw.cursor()
        cursor.execute("begin")
        cursor.execute(
            pg_sql.SQL("set local role {}").format(pg_sql.Identifier(role))
        )
        if user_id is not None:
            claims = json.dumps({"sub": user_id, "role": role})
            cursor.execute(
                pg_sql.SQL("set local request.jwt.claims = {}").format(
                    pg_sql.Literal(claims)
                )
            )
        try:
            value = action(cursor)
            raw.rollback()
            return ("ok", value)
        except Exception as error:  # noqa: BLE001 - the error text is the assertion
            raw.rollback()
            return ("error", str(error))
    finally:
        raw.close()


def insert_own(cursor: Any, user_id: str, document: str, version: str) -> Any:
    cursor.execute(
        """
        insert into public.legal_acceptances (user_id, document_type, document_version)
        values (%s, %s, %s)
        returning accepted_at
        """,
        (user_id, document, version),
    )
    return cursor.fetchone()


def main() -> int:
    engine = create_engine(get_settings().database.dsn(), future=True)

    # Seed one row per user as the owner so the reads have something to find.
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                insert into public.legal_acceptances
                    (user_id, document_type, document_version)
                values (:a, 'terms_of_service', '1.0'), (:b, 'terms_of_service', '1.0')
                on conflict do nothing
                """
            ),
            {"a": USER_A, "b": USER_B},
        )

    status, value = as_role(engine, "authenticated", USER_A, lambda c: insert_own(c, USER_A, "privacy_policy", "1.0"))
    check("a user can record their own acceptance", status == "ok", value)

    status, value = as_role(engine, "authenticated", USER_A, lambda c: insert_own(c, USER_B, "privacy_policy", "1.0"))
    check("a user cannot record an acceptance for another user", status == "error" and "row-level security" in value, value)

    def select_own(cursor: Any, user_id: str) -> list[str]:
        cursor.execute("select distinct user_id::text from public.legal_acceptances")
        return [row[0] for row in cursor.fetchall()]

    status, value = as_role(engine, "authenticated", USER_A, lambda c: select_own(c, USER_A))
    check("a user reads only their own records", status == "ok" and value == [USER_A], value)

    status, value = as_role(engine, "authenticated", USER_B, lambda c: select_own(c, USER_B))
    check("a second user cannot see the first user's records", status == "ok" and value == [USER_B], value)

    status, value = as_role(
        engine,
        "authenticated",
        USER_A,
        lambda c: c.execute("update public.legal_acceptances set accepted_at = now()"),
    )
    check("a user cannot rewrite their acceptance history", status == "error" and "permission denied" in value, value)

    status, value = as_role(
        engine,
        "authenticated",
        USER_A,
        lambda c: c.execute("delete from public.legal_acceptances"),
    )
    check("a user cannot delete an acceptance to bypass the gate", status == "error" and "permission denied" in value, value)

    status, value = as_role(engine, "authenticated", USER_A, lambda c: insert_own(c, USER_A, "terms_of_service", "1.0"))
    check("a duplicate acceptance is refused", status == "error" and "duplicate key" in value, value)

    def insert_with_timestamp(cursor: Any, user_id: str) -> Any:
        cursor.execute(
            """
            insert into public.legal_acceptances
                (user_id, document_type, document_version, accepted_at)
            values (%s, 'privacy_policy', '1.1', '2000-01-01T00:00:00Z')
            """,
            (user_id,),
        )
        return "inserted"

    status, value = as_role(engine, "authenticated", USER_A, lambda c: insert_with_timestamp(c, USER_A))
    check("a client cannot supply the acceptance timestamp", status == "error" and "permission denied" in value, value)

    def read_acceptance_time(cursor: Any) -> Any:
        cursor.execute(
            """
            insert into public.legal_acceptances (user_id, document_type, document_version)
            values (%s, 'privacy_policy', '2.0')
            returning accepted_at
            """,
            (USER_A,),
        )
        row = cursor.fetchone()
        return row[0] if row else None

    status, value = as_role(engine, "authenticated", USER_A, read_acceptance_time)
    check("the acceptance time is generated by the server", status == "ok" and value is not None, value)

    status, value = as_role(
        engine,
        "anon",
        None,
        lambda c: c.execute("select count(*) from public.legal_acceptances"),
    )
    check("an anonymous caller cannot read acceptances", status == "error" and "permission denied" in value, value)

    with engine.begin() as connection:
        connection.execute(
            text("delete from public.legal_acceptances where user_id in (:a, :b)"),
            {"a": USER_A, "b": USER_B},
        )
    engine.dispose()

    if failures:
        print(f"\n{len(failures)} rule(s) failed: {', '.join(failures)}")
        return 1
    print("\nAll access rules hold.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
