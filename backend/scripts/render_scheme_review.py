"""Render the human-readable review of a transcribed scheme-criteria document.

``seed/pilot_scheme_v1_review.md`` is generated, not written by hand: every table
row, dependency, alternative and printed allowance in it comes from the payload
the importer validates.  Regenerating it after a correction is how the review
stays evidence of what will be imported, rather than a second copy that can drift
away from it.

Usage::

    python scripts/render_scheme_review.py --check   # fail if the file is stale
    python scripts/render_scheme_review.py           # rewrite it

``--check`` writes nothing and exits non-zero when the review no longer matches
the payload, which is what makes a stale review a test failure instead of a
document nobody notices.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

BACKEND = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_DOCUMENT = BACKEND / "seed" / "pilot_scheme_v1_criteria.json"
DEFAULT_OUTPUT = BACKEND / "seed" / "pilot_scheme_v1_review.md"

#: Review commentary that is not derived from a single field of the payload.
#: Everything factual about the criteria is rendered; only the reading notes are
#: written here.
NOTES = (
    "- Q19's printed answer contains the product `5xy`. The SymPy scheme check reads\n"
    "  `xy` as a single symbol, so a comparison there would be wrong rather than silent;\n"
    "  the check is skipped for Q19 and the model's answer is reviewed by a person.\n"
    "- The two `M1` points of {dependent}\n"
    "  are a method mark and its follow-through. Their dependency is recorded as data, so\n"
    "  the verifier can reject a follow-through award made without the first method mark.\n"
    "- Q13 carries a printed prose alternative (factorise first) rather than a\n"
    "  mark-point code; it describes the same route and adds no marks.\n"
    "- Q16(d) is printed on scheme page 6 with 2 marks, but the blueprint carries only\n"
    "  `16b`. The criteria therefore total the paper's {total} scoreable marks, not the\n"
    "  scheme's 91 printed ones; the exclusion is listed in\n"
    "  `experiment/supervised_pilot/excluded_scheme_entries.csv`.\n"
    "- Q5 and Q14 print typographical slips in their tolerance cells. The intended\n"
    "  expression is recorded and the printed text is kept in `source_quote`; both are\n"
    "  described in the payload's extraction notes.\n"
    "- An independent audit of the printed pages corrected seven transcription faults\n"
    "  (Q1d, Q4, Q6, Q13, Q19, Q27, Q34). Each correction is pinned by\n"
    "  `backend/tests/unit/test_pilot_scheme_criteria.py`, which fails if a printed\n"
    "  tolerance is dropped or an unprinted one is added.\n"
    "- A coded alternative (Q34 `M2`, Q36 `M2`/`B2`, Q37a `B2`) records the codes it\n"
    "  replaces, so the verifier can refuse an award that earns the route and the marks\n"
    "  it stands in for. A route whose scope is missing, undefined or narrower than its\n"
    "  own prerequisites is refused before any paper is marked.\n"
    "- The two no-working routes print `3 out of a maximum of 4 terms`. Each records the\n"
    "  expression and its own threshold, which is counted deterministically; an answer\n"
    "  that cannot be read as a sum of terms is reported for review and never treated as\n"
    "  satisfying the threshold.\n"
    "- Q6, Q11, Q13, Q28 and Q37b print two independent mark points under one code. A\n"
    "  reply that awards that code once names neither of them, so the verifier reports\n"
    "  `AMBIGUOUS_CRITERION_CODE` for a person to attribute; a full award of both points\n"
    "  is not flagged. Where the second point is a follow-through, the dependency makes\n"
    "  a single award the earlier point and no ambiguity is reported.\n"
)


def _plural(marks: int) -> str:
    return "mark" if marks == 1 else "marks"


def _expected_answer(entry: dict) -> str:
    for criterion in entry["criteria"]:
        answer = criterion.get("expected_answer")
        if answer:
            return str(answer)
    return "—"


def _alternative_text(alternative: dict) -> str:
    if alternative.get("code"):
        body = alternative.get("rule") or alternative.get("expression") or ""
        text = f"{alternative['code']}: {body}".strip()
        extras = []
        if alternative.get("replaces"):
            extras.append("replaces " + ", ".join(alternative["replaces"]))
        threshold = alternative.get("term_count")
        if isinstance(threshold, dict):
            extras.append(
                f"threshold {threshold.get('required')} of {threshold.get('count')} "
                f"terms of {threshold.get('expression')}"
            )
        return f"{text} [{'; '.join(extras)}]" if extras else text
    body = alternative.get("expression") or alternative.get("rule") or ""
    return f"{alternative.get('method', 'alternative')}: {body}".strip()


def _details(criterion: dict) -> list[str]:
    parts: list[str] = []
    if criterion.get("award_conditions"):
        parts.append(f"award: {criterion['award_conditions']}")
    if criterion.get("withhold_conditions"):
        parts.append(f"withhold: {criterion['withhold_conditions']}")
    if criterion.get("dependencies"):
        parts.append(f"depends on: {', '.join(criterion['dependencies'])}")
    for alternative in criterion.get("alternatives") or []:
        parts.append(f"alternative {_alternative_text(alternative)}")
    return parts


def render(document: dict) -> str:
    questions = document["questions"]
    source = document["source"]
    extraction = document["extraction"]
    total_marks = sum(int(entry["max_marks"]) for entry in questions)
    total_rows = sum(len(entry["criteria"]) for entry in questions)

    dependencies = [
        (entry["question_id"], criterion["code"], criterion["dependencies"])
        for entry in questions
        for criterion in entry["criteria"]
        if criterion.get("dependencies")
    ]
    alternatives = [
        (entry["question_id"], criterion["code"], criterion["alternatives"])
        for entry in questions
        for criterion in entry["criteria"]
        if criterion.get("alternatives")
    ]
    awards = [
        (entry["question_id"], criterion["code"], criterion["award_conditions"])
        for entry in questions
        for criterion in entry["criteria"]
        if criterion.get("award_conditions")
    ]
    withholds = [
        (entry["question_id"], criterion["code"], criterion["withhold_conditions"])
        for entry in questions
        for criterion in entry["criteria"]
        if criterion.get("withhold_conditions")
    ]

    lines: list[str] = [
        f"# Pilot mark scheme review — {len(questions)} questions, {total_marks} marks",
        "",
        "Generated from `backend/seed/pilot_scheme_v1_criteria.json`, the payload the importer",
        "validates before it writes anything. Every row below is one printed mark point.",
        "",
        f"- **Source:** `{source['filename']}`, {source['pages']} pages, "
        f"sha256 `{source['sha256']}`",
        f"- **Scheme version:** `{document['scheme_version_id']}` · "
        f"**Blueprint version:** `{document['blueprint_version_id']}`",
        f"- **Extraction:** {extraction['method']}, {extraction['extracted_at']}",
        f"- **Totals:** {len(questions)} scoreable questions, {total_marks} marks, "
        f"{total_rows} criteria rows",
        "",
        "## Summary",
        "",
        "| Q | Marks | Scheme page | Paper item | Mark points | Expected answer |",
        "|---|---|---|---|---|---|",
    ]
    for entry in questions:
        points = ", ".join(
            f"{criterion['code']}({criterion['marks']})" for criterion in entry["criteria"]
        )
        lines.append(
            f"| {entry['question_id']} | {entry['max_marks']} "
            f"| {entry['source_ref']['pdf_page']} | {entry['source_ref']['item']} "
            f"| {points} | {_expected_answer(entry)} |"
        )

    lines += [
        "",
        f"Mark points sum to the paper's {total_marks} marks question by question; no mark point",
        "is counted twice and no alternative route adds a row.",
        "",
        "## Conditions the verifier enforces",
        "",
        f"- **Dependent (follow-through) points: "
        f"{sum(len(deps) for _, _, deps in dependencies)}.** A point that the scheme",
        "  labels `dep` or `(dep) ft` is not awarded unless the mark it depends on was awarded.",
        "  Where both points are printed `M1`, the check requires the earlier `M1` to have been",
        "  earned first, which a set of codes alone cannot express.",
    ]
    for question_id, code, deps in dependencies:
        for dependency in deps:
            lines.append(f"  - Q{question_id} {code} depends on {dependency}")

    lines += [
        "",
        f"- **Alternative routes: {sum(len(alts) for _, _, alts in alternatives)}.** "
        "Recorded beside the points they replace,",
        "  never as extra marks. A reply that takes one is not asked to name the points it "
        "replaces.",
    ]
    for question_id, code, alts in alternatives:
        for alternative in alts:
            lines.append(f"  - Q{question_id} {code} → {_alternative_text(alternative)}")

    lines += [
        "",
        f"- **Award conditions: {len(awards)}.** Printed allowances and `oe` variants.",
    ]
    for question_id, code, condition in awards:
        lines.append(f"  - Q{question_id} {code}: {condition}")

    lines += ["", f"- **Withhold conditions: {len(withholds)}.** `isw`/`do not isw` rules."]
    for question_id, code, condition in withholds:
        lines.append(f"  - Q{question_id} {code}: {condition}")

    lines += ["", "## Question by question"]
    for entry in questions:
        lines += [
            "",
            f"### {entry['question_id']} — {entry['max_marks']} "
            f"{_plural(int(entry['max_marks']))} — scheme page {entry['source_ref']['pdf_page']}",
            "",
            f"*Paper item:* {entry['source_ref']['item']}",
            "",
            "| Mark point | Marks | What it is for | Expected answer |",
            "|---|---|---|---|",
        ]
        for criterion in entry["criteria"]:
            answer = criterion.get("expected_answer") or "—"
            lines.append(
                f"| {criterion['code']} | {criterion['marks']} "
                f"| {criterion['description']} | {answer} |"
            )
        lines.append("")
        for criterion in entry["criteria"]:
            details = _details(criterion)
            if details:
                lines.append(f"- `{criterion['code']}` — " + " · ".join(details))
        lines.append(f"- *Printed:* \"{entry['criteria'][0]['source_quote']}\"")

    dependent_questions = "Q18, Q23, Q26, Q27, Q30, Q31, Q32, Q34, Q35, Q36 and Q37a"
    lines += [
        "",
        "## Notes from the review",
        "",
        NOTES.format(dependent=dependent_questions, total=total_marks).rstrip("\n"),
        "",
        f"*{len(questions)} questions · {total_marks} marks · {total_rows} rows.*",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--document", type=pathlib.Path, default=DEFAULT_DOCUMENT)
    parser.add_argument("--output", type=pathlib.Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--check", action="store_true", help="exit non-zero when the review is stale"
    )
    arguments = parser.parse_args()

    document = json.loads(arguments.document.read_text(encoding="utf-8"))
    rendered = render(document)
    if arguments.check:
        current = arguments.output.read_text(encoding="utf-8") if arguments.output.exists() else ""
        if current.replace("\r\n", "\n") != rendered:
            print(
                f"{arguments.output} does not match the payload; run this script to regenerate it",
                file=sys.stderr,
            )
            return 1
        print(f"{arguments.output} matches the payload")
        return 0

    arguments.output.write_text(rendered, encoding="utf-8", newline="\r\n")
    print(f"wrote {arguments.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
