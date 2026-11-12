"""Drive one sample paper through the local engine, exactly as the site does.

This is a local operational probe, not part of the product: it creates a small
three-question exam, uploads a mark scheme and a student script, approves the
blueprint, registers the submission, queues the correction job and then reports
what the worker stored.  It always prints the engine's own answer, including a
failure, because a probe that hides a refusal is worthless.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import sys
import time

import httpx
import pymupdf

BASE = "http://127.0.0.1:8010/api/v1"
OUT = pathlib.Path(__file__).resolve().parents[2] / ".tmp" / "mark"

STRUCTURE = {
    "paper_code": "SMOKE-3Q",
    "total_marks": 6,
    "questions": [
        {
            "question_id": "1",
            "label": "Linear equation",
            "max_marks": 2,
            "answer_type": "linear equation",
            "special_instructions": [
                "Expected answer: x = 4",
                "Award 1 mark for 2x = 8 and 1 mark for x = 4.",
            ],
        },
        {
            "question_id": "2",
            "label": "Factorisation",
            "max_marks": 2,
            "answer_type": "factorisation",
            "special_instructions": [
                "Expected answer: (x - 3)(x + 3)",
                "Award 2 marks for the fully factorised difference of two squares.",
            ],
        },
        {
            "question_id": "3",
            "label": "Gradient",
            "max_marks": 2,
            "answer_type": "coordinate geometry",
            "special_instructions": [
                "Expected answer: gradient = 3",
                "Award 1 mark for (11 - 2) / (4 - 1) and 1 mark for the value 3.",
            ],
        },
    ],
}

SCHEME_LINES = [
    "Mark scheme - sample paper SMOKE-3Q",
    "",
    "Question 1 (2 marks)",
    "Solve 2x + 5 = 13.",
    "M1: subtract 5 from both sides to reach 2x = 8.",
    "A1: x = 4.",
    "",
    "Question 2 (2 marks)",
    "Factorise x^2 - 9.",
    "B2: (x - 3)(x + 3), fully factorised. Allow B1 for a correct",
    "pair of factors with a sign error.",
    "",
    "Question 3 (2 marks)",
    "Find the gradient of the line through (1, 2) and (4, 11).",
    "M1: (11 - 2) / (4 - 1).",
    "A1: 3.",
    "",
    "Total: 6 marks.",
    "General marking guidance: award method marks for a correct stated",
    "method even when the final arithmetic slips, and award accuracy",
    "marks only for the stated correct value.",
]

SCRIPT_LINES = [
    "Mathematics - sample student script",
    "Paper SMOKE-3Q",
    "",
    "Question 1",
    "Solve 2x + 5 = 13.",
    "2x + 5 = 13",
    "2x = 13 - 5",
    "2x = 8",
    "x = 4",
    "",
    "Question 2",
    "Factorise x^2 - 9.",
    "x^2 - 9 is a difference of two squares.",
    "x^2 - 9 = (x - 3)(x + 3)",
    "",
    "Question 3",
    "Find the gradient of the line through (1, 2) and (4, 11).",
    "gradient = (11 - 2) / (4 - 1)",
    "gradient = 9 / 3",
    "gradient = 3",
]


def make_pdf(path: pathlib.Path, title: str, lines: list[str]) -> pathlib.Path:
    document = pymupdf.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((56, 70), title, fontsize=15, fontname="helv")
    cursor = 110
    for line in lines:
        page.insert_text((56, cursor), line, fontsize=11, fontname="helv")
        cursor += 22
    document.save(path)
    document.close()
    return path


def step(name: str, response: httpx.Response) -> dict:
    body = response.json() if response.content else {}
    print(f"[{response.status_code}] {name}")
    if response.status_code >= 400:
        print(json.dumps(body, indent=2)[:2000])
        raise SystemExit(f"step failed: {name}")
    return body


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    scheme_pdf = make_pdf(OUT / "scheme.pdf", "Sample mark scheme", SCHEME_LINES)
    script_pdf = make_pdf(OUT / "script.pdf", "Sample student script", SCRIPT_LINES)

    with httpx.Client(base_url=BASE, timeout=120.0) as client:
        exam = step(
            "create exam",
            client.post("/exams", json={"title": "Marking smoke test - 3 questions"}),
        )
        exam_id = exam["id"]

        scheme_bytes = scheme_pdf.read_bytes()
        upload = step(
            "upload scheme",
            client.post(
                f"/exams/{exam_id}/schemes",
                data={"title": "Smoke scheme"},
                files={"file": ("scheme.pdf", scheme_bytes, "application/pdf")},
            ),
        )
        version_id = upload["version"]["id"]

        step(
            "approve scheme",
            client.post(
                f"/schemes/{version_id}/approve",
                json={"reason": "Checked question numbers and marks against the scheme."},
            ),
        )

        draft = step(
            "save blueprint draft",
            client.put(
                f"/exams/{exam_id}/blueprint",
                json={"structure": STRUCTURE, "approve": False},
            ),
        )
        approved = step(
            "approve blueprint",
            client.put(
                f"/exams/{exam_id}/blueprint",
                json={
                    "structure": STRUCTURE,
                    "approve": True,
                    "reason": "Three questions, six marks, checked by hand.",
                },
            ),
        )
        assert draft["content_hash"] == approved["content_hash"]

        assignment = step(
            "create assignment",
            client.post(
                "/assignments",
                json={
                    "exam_id": exam_id,
                    "blueprint_version_id": approved["id"],
                    "scheme_version_id": version_id,
                    "name": "Smoke assignment",
                },
            ),
        )

        script_bytes = script_pdf.read_bytes()
        digest = hashlib.sha256(script_bytes).hexdigest()
        submission = step(
            "register submission",
            client.post(
                "/submissions",
                json={
                    "assignment_id": assignment["id"],
                    "student_ref": "sample-student",
                    "content_hash": digest,
                },
            ),
        )

        document = step(
            "upload script",
            client.post(
                f"/submissions/{submission['id']}/documents",
                files={"file": ("script.pdf", script_bytes, "application/pdf")},
            ),
        )
        print(
            f"    document status={document['status']} pages={document['page_count']} "
            f"ordering={document['ordering_status']} quality="
            f"{[page['quality_status'] for page in document['pages']]}"
        )

        job = step(
            "queue correction job",
            client.post(
                "/corrections",
                json={
                    "assignment_id": assignment["id"],
                    "submission_id": submission["id"],
                },
            ),
        )
        job_id = job["id"]
        print(f"    job {job_id} state={job['state']}")

        deadline = time.time() + 600
        state = job["state"]
        while time.time() < deadline and state not in {
            "COMPLETED",
            "FAILED",
            "REVIEW_REQUIRED",
            "RETRY_SUSPENDED",
            "CANCELLED",
        }:
            time.sleep(5)
            detail = client.get(f"/corrections/{job_id}").json()
            state = detail["state"]
            print(f"    {state} progress={detail['progress']:.2f} attempts={detail['attempts']}")

        if state not in {"COMPLETED", "REVIEW_REQUIRED"}:
            detail = client.get(f"/corrections/{job_id}").json()
            print("JOB DID NOT MARK:")
            print(json.dumps(detail, indent=2)[:4000])
            return 1

        results = client.get(f"/submissions/{submission['id']}/results").json()
        print("\nRESULT SUMMARY")
        print(
            f"job_state={results['job_state']} awarded={results['totals']['awarded']}"
            f"/{results['totals']['total']} questions={results['totals']['questions']}"
            f" review_required={results['totals']['review_required']}"
        )
        for question in results["questions"]:
            print(
                f"  Q{question['question_id']}: {question['awarded_marks']}"
                f"/{question['max_marks']} status={question['status']}"
                f" confidence={question['confidence']}"
            )
            if question.get("student_answer"):
                print(f"      answer: {question['student_answer'][:300]}")
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
