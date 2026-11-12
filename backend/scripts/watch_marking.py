"""Watch the local engine while a paper is uploaded and marked.

Local operational helper.  It polls the database for new submissions, uploaded
documents and correction jobs, prints every state change it sees, and tails the
worker log for errors, so a live attempt can be diagnosed while it happens.  It
never writes anything.
"""

from __future__ import annotations

import argparse
import pathlib
import sys
import time

from sqlalchemy import create_engine, text

from app.core.config import get_settings


def _tables(conn) -> dict[str, str]:
    rows = conn.execute(
        text(
            """
            select table_name from information_schema.tables
            where table_schema = 'public'
            """
        )
    ).scalars()
    names = set(rows)
    picked: dict[str, str] = {}
    for name in names:
        columns = set(
            conn.execute(
                text(
                    """
                    select column_name from information_schema.columns
                    where table_schema = 'public' and table_name = :name
                    """
                ),
                {"name": name},
            ).scalars()
        )
        if {"state", "progress", "error_code"} <= columns:
            picked["jobs"] = name
        if {"status", "original_filename"} <= columns:
            picked["documents"] = name
        if {"student_ref", "assignment_id"} <= columns:
            picked["submissions"] = name
    return picked


def _jobs(conn, table: str) -> list:
    return conn.execute(
        text(
            f"""
            select id, state, progress, attempts, error_code,
                   coalesce(error_message, ''), created_at
            from {table}
            order by created_at desc
            limit 4
            """
        )
    ).all()


def _documents(conn, table: str) -> list:
    return conn.execute(
        text(
            f"""
            select id, kind, original_filename, status, coalesce(error_code, ''),
                   coalesce(mapping_status, ''), page_count, created_at
            from {table}
            order by created_at desc
            limit 4
            """
        )
    ).all()


def _tail(path: pathlib.Path, offset: int) -> tuple[list[str], int]:
    if not path.exists():
        return [], offset
    with path.open("rb") as handle:
        handle.seek(offset)
        chunk = handle.read()
        return chunk.decode("utf-8", "replace").splitlines(), handle.tell()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=int, default=240)
    parser.add_argument("--interval", type=int, default=4)
    parser.add_argument("--log", type=str, default="")
    args = parser.parse_args()

    settings = get_settings()
    engine = create_engine(
        settings.database.url.get_secret_value(), pool_size=1, max_overflow=0
    )
    log = pathlib.Path(args.log) if args.log else None
    offset = log.stat().st_size if log and log.exists() else 0

    with engine.connect() as conn:
        tables = _tables(conn)
        print(f"tables: {tables}")
        baseline_jobs = {row[0] for row in _jobs(conn, tables["jobs"])}
        baseline_docs = {row[0] for row in _documents(conn, tables["documents"])}
        print(f"baseline: {len(baseline_jobs)} jobs, {len(baseline_docs)} documents known")

    seen: dict[str, tuple] = {}
    deadline = time.time() + args.seconds
    try:
        while time.time() < deadline:
            time.sleep(args.interval)
            with engine.connect() as conn:
                for row in reversed(_jobs(conn, tables["jobs"])):
                    if row[0] in baseline_docs:
                        continue
                    previous = seen.get(row[0])
                    fingerprint = (row[1], round(float(row[2] or 0), 2), row[3], row[4], row[5])
                    if previous == fingerprint:
                        continue
                    seen[row[0]] = fingerprint
                    marker = "NEW" if row[0] not in baseline_jobs else "job"
                    print(
                        f"[{marker}] {row[0]} state={row[1]} progress={float(row[2] or 0):.2f}"
                        f" attempts={row[3]} error={row[4]} {row[5]}"
                    )
                if "documents" in tables:
                    for row in reversed(_documents(conn, tables["documents"])):
                        key = f"doc:{row[0]}"
                        previous = seen.get(key)
                        fingerprint = (row[3], row[4], row[5])
                        if previous == fingerprint:
                            continue
                        seen[key] = fingerprint
                        marker = "NEW" if row[0] not in baseline_docs else "doc"
                        print(
                            f"[{marker}] {row[0]} {row[1]} {row[2]} status={row[3]}"
                            f" error={row[4]} mapping={row[5]} pages={row[6]}"
                        )
            if log is not None:
                lines, offset = _tail(log, offset)
                for line in lines:
                    lowered = line.lower()
                    if "error" in lowered or "exception" in lowered or "traceback" in lowered:
                        print(f"LOG {line[:400]}")
    except KeyboardInterrupt:
        return 0
    print("watch window ended")
    return 0


if __name__ == "__main__":
    sys.exit(main())
