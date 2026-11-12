"""Mark the Chapter 2 Lesson 3 paper that sits in the Downloads folder.

Local operational probe, not part of the product.  It drives the same HTTP
endpoints the site drives:

* create the exam and upload the real mark scheme PDF;
* approve the scheme version;
* ask the engine to extract a blueprint from the scheme's rendered pages;
* dump the extracted structure so a person can check it before it is approved.

``--mark`` continues afterwards: approve the blueprint, create the assignment,
register the submission, upload the student script, queue the correction job and
report exactly what the worker stored, including a failure.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
import time

import httpx

BASE = "http://127.0.0.1:8020/api/v1"
DOWNLOADS = pathlib.Path.home() / "Downloads"
SCRIPT_PDF = DOWNLOADS / "Ch2 L3 (1).pdf"
SCHEME_PDF = DOWNLOADS / "Ch2L3MS- Simplifying Expressions (1).pdf"
OUT = pathlib.Path(__file__).resolve().parents[2] / ".tmp" / "real"
EXAM_TITLE = "Ch2 L3 - Simplifying Expressions"


def step(name: str, response: httpx.Response) -> dict:
    body = response.json() if response.content else {}
    print(f"[{response.status_code}] {name}")
    if response.status_code >= 400:
        print(json.dumps(body, indent=2)[:3000])
        raise SystemExit(f"step failed: {name}")
    return body


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mark", action="store_true", help="continue through marking")
    args = parser.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    for path in (SCRIPT_PDF, SCHEME_PDF):
        if not path.is_file():
            raise SystemExit(f"missing file: {path}")
        print(f"input {path.name} {path.stat().st_size} bytes")

    state_path = OUT / "state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}

    with httpx.Client(base_url=BASE, timeout=300.0) as client:
        if "exam_id" not in state:
            exam = step("create exam", client.post("/exams", json={"title": EXAM_TITLE}))
            state["exam_id"] = exam["id"]

            upload = step(
                "upload scheme",
                client.post(
                    f"/exams/{state['exam_id']}/schemes",
                    data={"title": "Ch2 L3 Simplifying Expressions - mark scheme"},
                    files={
                        "file": (
                            SCHEME_PDF.name,
                            SCHEME_PDF.read_bytes(),
                            "application/pdf",
                        )
                    },
                ),
            )
            state["scheme_version_id"] = upload["version"]["id"]
            print(f"    scheme version {state['scheme_version_id']} status={upload['version']['status']}")
            state_path.write_text(json.dumps(state, indent=2))

        version = step(
            "read scheme version",
            client.get(f"/schemes/{state['scheme_version_id']}"),
        )
        if version["status"] != "APPROVED":
            step(
                "approve scheme",
                client.post(
                    f"/schemes/{state['scheme_version_id']}/approve",
                    json={"reason": "Approved for a local probe of the real scheme PDF."},
                ),
            )
        else:
            print("    scheme already approved")

        if "blueprint_id" not in state:
            extraction = step(
                "extract blueprint",
                client.post(
                    f"/exams/{state['exam_id']}/blueprint/extractions",
                    json={"scheme_version_id": state["scheme_version_id"]},
                ),
            )
            blueprint = extraction["blueprint"]
            state["blueprint_id"] = blueprint["id"]
            state["structure"] = blueprint["structure"]
            state["extraction_provider"] = extraction["provider"]
            state_path.write_text(json.dumps(state, indent=2))
            (OUT / "blueprint.json").write_text(
                json.dumps(blueprint["structure"], indent=2)
            )
            print(f"    blueprint {blueprint['id']} status={blueprint['status']}")
            print(f"    provider {extraction['provider']}")
            for question in blueprint["structure"]["questions"]:
                subs = question.get("subquestions") or []
                print(
                    f"    Q{question['question_id']} {question['max_marks']} mark(s)"
                    f" label={question.get('label')!r} subs={len(subs)}"
                )
                for sub in subs:
                    print(
                        f"      Q{sub['question_id']} {sub['max_marks']} mark(s)"
                        f" label={sub.get('label')!r}"
                    )
            return 0

        if not args.mark:
            print("blueprint already extracted; pass --mark to continue")
            return 0
        return _mark(client, state)


def _mark(client: httpx.Client, state: dict) -> int:
    structure = state["structure"]
    step(
        "approve blueprint",
        client.put(
            f"/exams/{state['exam_id']}/blueprint",
            json={
                "structure": structure,
                "approve": True,
                "reason": "Questions and marks checked against the scheme PDF.",
            },
        ),
    )

    if "assignment_id" not in state:
        assignment = step(
            "create assignment",
            client.post(
                "/assignments",
                json={
                    "exam_id": state["exam_id"],
                    "blueprint_version_id": state["blueprint_id"],
                    "scheme_version_id": state["scheme_version_id"],
                    "name": "Ch2 L3 - Simplifying Expressions",
                },
            ),
        )
        state["assignment_id"] = assignment["id"]

    data = SCRIPT_PDF.read_bytes()
    submission = step(
        "register submission",
        client.post(
            "/submissions",
            json={
                "assignment_id": state["assignment_id"],
                "student_ref": "ch2-l3-script",
                "content_hash": hashlib.sha256(data).hexdigest(),
            },
        ),
    )
    state["submission_id"] = submission["id"]

    document = step(
        "upload script",
        client.post(
            f"/submissions/{state['submission_id']}/documents",
            files={"file": (SCRIPT_PDF.name, data, "application/pdf")},
        ),
    )
    print(
        f"    document status={document['status']} pages={document['page_count']}"
        f" ordering={document['ordering_status']}"
        f" quality={[page['quality_status'] for page in document['pages']]}"
    )
    if document["status"] != "PROCESSED":
        print(f"    document error={document.get('error_code')}")
        return 1

    job = step(
        "queue correction job",
        client.post(
            "/corrections",
            json={
                "assignment_id": state["assignment_id"],
                "submission_id": state["submission_id"],
            },
        ),
    )
    job_id = job["id"]
    state["job_id"] = job_id
    OUT.joinpath("state.json").write_text(json.dumps(state, indent=2))
    print(f"    job {job_id} state={job['state']}")

    deadline = time.time() + 1500
    current = job["state"]
    while time.time() < deadline and current not in {
        "COMPLETED",
        "FAILED",
        "REVIEW_REQUIRED",
        "RETRY_SUSPENDED",
        "CANCELLED",
    }:
        time.sleep(8)
        detail = client.get(f"/corrections/{job_id}").json()
        current = detail["state"]
        print(f"    {current} progress={detail['progress']:.2f} attempts={detail['attempts']}")

    detail = client.get(f"/corrections/{job_id}").json()
    print(
        f"\njob {job_id} state={detail['state']} error={detail.get('error_code')}"
        f" {detail.get('error_message') or ''}"
    )
    (OUT / "job.json").write_text(json.dumps(detail, indent=2))

    if detail["state"] not in {"COMPLETED", "REVIEW_REQUIRED"}:
        print("JOB DID NOT FINISH MARKING")
        return 1

    results = client.get(f"/submissions/{state['submission_id']}/results").json()
    (OUT / "results.json").write_text(json.dumps(results, indent=2))
    totals = results["totals"]
    print(
        f"RESULT awarded={totals['awarded']}/{totals['total']}"
        f" questions={totals['questions']} review_required={totals['review_required']}"
        f" unanswered={totals['unanswered']}"
    )
    for question in results["questions"]:
        print(
            f"  Q{question['question_id']}: {question['awarded_marks']}"
            f"/{question['max_marks']} status={question['status']}"
            f" confidence={question['confidence']}"
        )
        if question.get("student_answer"):
            print(f"      answer: {question['student_answer'][:400]}")
        for criterion in question.get("criteria", []):
            print(
                f"      criterion {criterion['code']} awarded={criterion['awarded']}"
                f" reason={(criterion.get('reason') or '')[:200]}"
            )
        for concern in question.get("scheme_concerns", []):
            print(f"      concern {concern.get('code')}: {concern.get('message')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
