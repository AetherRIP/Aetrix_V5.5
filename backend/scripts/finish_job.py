"""Keep resuming one correction job until every question has been marked.

The provider allows a burst of calls and then answers 429, so a long paper stops
part way and must be resumed.  Each retry reuses the marks already committed, so
this loop only asks the engine to continue; it never re-marks a question.
"""

from __future__ import annotations

import json
import sys
import time

import httpx
from sqlalchemy import create_engine, text
from app.core.config import get_settings

API = "http://127.0.0.1:8020/api/v1"
TERMINAL = {"COMPLETED", "FAILED", "REVIEW_REQUIRED", "RETRY_SUSPENDED", "CANCELLED"}


def _cooldown_seconds() -> float:
    settings = get_settings()
    engine = create_engine(
        settings.database.url.get_secret_value(), pool_size=1, max_overflow=0
    )
    with engine.connect() as conn:
        remaining = conn.execute(
            text(
                "select max(cooldown_until) - now() from provider_project_cooldowns "
                "where cooldown_until > now()"
            )
        ).scalar()
    return max(0.0, remaining.total_seconds()) if remaining else 0.0


def _expected_questions() -> int:
    settings = get_settings()
    engine = create_engine(
        settings.database.url.get_secret_value(), pool_size=1, max_overflow=0
    )
    with engine.connect() as conn:
        total = conn.execute(
            text(
                """
                select sum(
                    case
                        when json_array_length(question->'subquestions') > 0
                        then json_array_length(question->'subquestions')
                        else 1
                    end
                )
                from exam_blueprint_versions b,
                     json_array_elements(b.structure->'questions') as question
                where b.id = (
                    select blueprint_version_id from correction_jobs
                    where id = '2b0f182b-e263-4bb8-ad07-36650185bef4'
                )
                  and coalesce((question->>'excluded')::boolean, false) = false
                """
            )
        ).scalar()
    return int(total or 0)


def main() -> int:
    job_id = sys.argv[1]
    expected = _expected_questions()
    print(f"blueprint expects {expected} scoreable questions", flush=True)

    with httpx.Client(base_url=API, timeout=180.0) as client:
        job = client.get(f"/corrections/{job_id}").json()
        submission = job["submission_id"]

        for attempt in range(1, 13):
            wait = _cooldown_seconds()
            if wait:
                print(f"attempt {attempt}: provider cooldown {wait:.0f}s", flush=True)
                time.sleep(wait + 3)

            response = client.post(f"/corrections/{job_id}/retry")
            state = response.json().get("state")
            print(f"attempt {attempt}: [{response.status_code}] retry -> {state}", flush=True)

            deadline = time.time() + 420
            last = None
            while time.time() < deadline and state not in TERMINAL:
                time.sleep(5)
                detail = client.get(f"/corrections/{job_id}").json()
                state = detail["state"]
                progress = round(detail["progress"], 2)
                if (state, progress) != last:
                    print(f"  {state} progress={progress}", flush=True)
                    last = (state, progress)

            detail = client.get(f"/corrections/{job_id}").json()
            results = client.get(f"/submissions/{submission}/results").json()
            marked = results["totals"]["questions"]
            print(
                f"attempt {attempt}: state={state} marked={marked}/{expected} "
                f"awarded={results['totals']['awarded']}/{results['totals']['total']} "
                f"review={results['totals']['review_required']} "
                f"error={detail.get('error_code')}",
                flush=True,
            )

            if marked >= expected or state not in {"RETRY_SUSPENDED"}:
                break
            if detail.get("error_code") != "PROVIDER_UNAVAILABLE":
                break
            time.sleep(20)

        print("=== FINAL ===", flush=True)
        detail = client.get(f"/corrections/{job_id}").json()
        results = client.get(f"/submissions/{submission}/results").json()
        print(f"job state={detail['state']} error={detail.get('error_code')}", flush=True)
        print("totals " + json.dumps(results["totals"]), flush=True)
        for question in sorted(results["questions"], key=lambda q: q["question_id"]):
            concerns = "; ".join(
                f"{c.get('code')}: {c.get('message')}" for c in question.get("scheme_concerns", [])
            )
            print(
                f"  Q{question['question_id']}: {question['awarded_marks']}"
                f"/{question['max_marks']} {question['status']}"
                f" conf={question['confidence']} answer={question.get('student_answer')!r}"
                f"{' | ' + concerns if concerns else ''}",
                flush=True,
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
