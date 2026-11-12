"""Resume one correction job after the provider project cooldown clears."""

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
        row = conn.execute(
            text(
                "select max(cooldown_until) - now() from provider_project_cooldowns "
                "where cooldown_until > now()"
            )
        ).scalar()
    if row is None:
        return 0.0
    return max(0.0, row.total_seconds())


def main() -> int:
    job_id = sys.argv[1]
    wait = _cooldown_seconds()
    if wait:
        print(f"project cooldown active for {wait:.0f}s; waiting", flush=True)
        time.sleep(wait + 2)

    with httpx.Client(base_url=API, timeout=180.0) as client:
        job = client.get(f"/corrections/{job_id}").json()
        submission = job["submission_id"]
        response = client.post(f"/corrections/{job_id}/retry")
        state = response.json().get("state")
        print(f"[{response.status_code}] retry -> {state}", flush=True)

        deadline = time.time() + 900
        last = None
        while time.time() < deadline and state not in TERMINAL:
            time.sleep(6)
            detail = client.get(f"/corrections/{job_id}").json()
            state = detail["state"]
            progress = round(detail["progress"], 2)
            if (state, progress) != last:
                print(f"  {state} progress={progress}", flush=True)
                last = (state, progress)

        detail = client.get(f"/corrections/{job_id}").json()
        print(
            f"final state={state} error={detail.get('error_code')} "
            f"{detail.get('error_message') or ''}",
            flush=True,
        )
        results = client.get(f"/submissions/{submission}/results").json()
        print("totals " + json.dumps(results["totals"]), flush=True)
        for question in results["questions"]:
            print(
                f"  Q{question['question_id']} {question['awarded_marks']}"
                f"/{question['max_marks']} {question['status']}",
                flush=True,
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
