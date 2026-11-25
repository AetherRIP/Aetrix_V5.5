"""Is a transcribed scheme-criteria document complete enough to mark with?

The engine can only be given a mark scheme if the scheme is stored as rows.  Rows
transcribed from a scanned scheme can be wrong in ways that still look plausible:
a question left out, a mark point worth the wrong number, a paper whose criteria
add up to 88 instead of 89.  This module answers those questions in plain Python,
against the approved blueprint, before anything is written to the database.

Nothing here decides a mark or writes a row.  It reports what a person must fix.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from .term_count import validate_spec


@dataclass(frozen=True, slots=True)
class CoverageLine:
    question_id: str
    expected_marks: int
    criteria_marks: int
    criteria_count: int

    @property
    def matches(self) -> bool:
        return self.expected_marks == self.criteria_marks


@dataclass(slots=True)
class CoverageReport:
    """Every question of the paper, with the marks its criteria carry."""

    lines: list[CoverageLine] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    total_expected: int = 0
    total_criteria: int = 0

    @property
    def complete(self) -> bool:
        """True only when every leaf is covered and every sum is exact."""

        return not self.problems

    def describe(self) -> dict[str, Any]:
        return {
            "complete": self.complete,
            "questions": len(self.lines),
            "total_expected": self.total_expected,
            "total_criteria": self.total_criteria,
            "problems": list(self.problems),
            "shortfall": [
                {
                    "question_id": line.question_id,
                    "expected": line.expected_marks,
                    "recorded": line.criteria_marks,
                }
                for line in self.lines
                if not line.matches
            ],
        }


def blueprint_leaves(structure: Any) -> dict[str, int]:
    """``{question_id: max_marks}`` for every scoreable leaf of a blueprint.

    A question with subquestions is marked through its subquestions, so the
    parent is never a leaf: the blueprint's own 39 leaves come from this rule.
    """

    if hasattr(structure, "model_dump"):
        structure = structure.model_dump()
    questions = (structure or {}).get("questions") or []
    leaves: dict[str, int] = {}
    for question in questions:
        subquestions: Iterable[Any] = question.get("subquestions") or []
        if subquestions:
            for subquestion in subquestions:
                if subquestion.get("excluded"):
                    continue
                leaves[str(subquestion["question_id"])] = int(
                    subquestion.get("max_marks") or 0
                )
            continue
        if question.get("excluded"):
            continue
        leaves[str(question["question_id"])] = int(question.get("max_marks") or 0)
    return leaves


def children_by_parent(structure: Any) -> dict[str, list[str]]:
    """``{parent_id: [child_id, ...]}`` for every question that has subquestions.

    The paper prints the parent number, so a page the mapper attributes to ``16``
    is a page that carries ``16b``: the parent is never a scoreable leaf and its
    children are the questions that must end up mapped.
    """

    if hasattr(structure, "model_dump"):
        structure = structure.model_dump()
    mapping: dict[str, list[str]] = {}
    for question in (structure or {}).get("questions") or []:
        subquestions = question.get("subquestions") or []
        if not subquestions:
            continue
        mapping[str(question["question_id"])] = [
            str(sub["question_id"]) for sub in subquestions if not sub.get("excluded")
        ]
    return mapping


def validate(document: dict[str, Any], structure: Any) -> CoverageReport:
    """Compare a criteria document with the blueprint it will be marked against."""

    report = CoverageReport()
    leaves = blueprint_leaves(structure)
    entries = document.get("questions") or []
    seen: dict[str, dict[str, Any]] = {}
    for entry in entries:
        question_id = str(entry.get("question_id", "")).strip()
        if not question_id:
            report.problems.append("an entry has no question_id")
            continue
        if question_id in seen:
            report.problems.append(f"question {question_id!r} appears twice")
            continue
        seen[question_id] = entry

    for question_id in leaves:
        if question_id not in seen:
            report.problems.append(f"question {question_id!r} has no criteria")
    for question_id in seen:
        if question_id not in leaves:
            report.problems.append(
                f"question {question_id!r} is not a scoreable leaf of the blueprint"
            )

    pages = int((document.get("source") or {}).get("pages") or 0)
    for question_id, entry in seen.items():
        criteria = entry.get("criteria") or []
        if not criteria:
            report.problems.append(f"question {question_id!r} has no mark points")
            continue
        recorded = 0
        defined: set[str] = set()
        identities: set[tuple[str, int]] = set()
        for index, criterion in enumerate(criteria):
            code = str(criterion.get("code", "")).strip()
            if code:
                defined.add(code.upper())
            marks = criterion.get("marks")
            if not code:
                report.problems.append(f"question {question_id!r} has a mark point with no code")
            if not isinstance(marks, int) or marks < 0:
                report.problems.append(
                    f"question {question_id!r} mark point {code!r} has invalid marks {marks!r}"
                )
                marks = 0
            recorded += marks
            # A mark point that does not state its ordinal is ordered by its
            # position, which is how the importer numbers it.
            ordinal = criterion.get("ordinal")
            identity = (code, index if ordinal is None else int(ordinal))
            if identity in identities:
                report.problems.append(
                    f"question {question_id!r} repeats mark point {code!r} "
                    f"at ordinal {identity[1]}"
                )
            identities.add(identity)
            page = criterion.get("source_page", (entry.get("source_ref") or {}).get("pdf_page"))
            if pages and isinstance(page, int) and not 1 <= page <= pages:
                report.problems.append(
                    f"question {question_id!r} names page {page}, outside 1..{pages}"
                )
        # A printed dependency has to name a mark point the question actually
        # defines, or the verification code would compare an award against
        # nothing.  Two mark points may share a code (a dependent second ``M1``),
        # so the reference is to the code, not to a unique row.
        for criterion in criteria:
            code = str(criterion.get("code", "")).strip()
            for dependency in criterion.get("dependencies") or []:
                name = str(dependency).strip()
                if not name:
                    report.problems.append(
                        f"question {question_id!r} mark point {code!r} has an empty dependency"
                    )
                    continue
                if name.upper() not in defined:
                    report.problems.append(
                        f"question {question_id!r} mark point {code!r} depends on {name!r}, "
                        "which the question's criteria do not define"
                    )

        # An alternative route is approved data, and the engine uses its
        # ``replaces`` list to refuse an award that earns the route and the
        # criteria it stands in for.  A route with no replacement scope, or one
        # that leaves its own prerequisite active, cannot be enforced, so it is
        # refused here rather than discovered while marking.
        marks_by_code: dict[str, int] = defaultdict(int)
        for criterion in criteria:
            key = str(criterion.get("code", "")).strip().upper()
            if key:
                marks_by_code[key] += int(criterion.get("marks") or 0)
        route_codes: set[str] = set()
        for criterion in criteria:
            host = str(criterion.get("code", "")).strip().upper()
            for alternative in criterion.get("alternatives") or []:
                if not isinstance(alternative, dict):
                    report.problems.append(
                        f"question {question_id!r} has an alternative that is not an object"
                    )
                    continue
                code = str(alternative.get("code") or "").strip().upper()
                if not code:
                    # A printed prose route adds no mark point, so it has no
                    # identity and no replacement to enforce.
                    continue
                if code in route_codes:
                    report.problems.append(
                        f"question {question_id!r} defines alternative route {code} more "
                        "than once"
                    )
                route_codes.add(code)
                replaces = {
                    str(name).strip().upper()
                    for name in (alternative.get("replaces") or [])
                    if str(name).strip()
                }
                if not replaces:
                    report.problems.append(
                        f"question {question_id!r} alternative {code} names no criteria it "
                        "replaces, so a mixed award could not be refused"
                    )
                if host and host not in replaces:
                    report.problems.append(
                        f"question {question_id!r} alternative {code} is recorded on {host} "
                        "but does not replace it"
                    )
                for name in sorted(replaces):
                    if name not in defined:
                        report.problems.append(
                            f"question {question_id!r} alternative {code} replaces {name!r}, "
                            "which the question's criteria do not define"
                        )
                for dependency in criterion.get("dependencies") or []:
                    name = str(dependency).strip().upper()
                    if name and name not in replaces:
                        report.problems.append(
                            f"question {question_id!r} alternative {code} leaves {name!r} "
                            "active, although the mark point it replaces depends on it"
                        )
                marks = alternative.get("marks")
                if not isinstance(marks, int) or marks < 0:
                    report.problems.append(
                        f"question {question_id!r} alternative {code} has invalid marks "
                        f"{marks!r}"
                    )
                elif marks > sum(marks_by_code.get(name, 0) for name in replaces):
                    report.problems.append(
                        f"question {question_id!r} alternative {code} carries {marks} "
                        "mark(s) but replaces only "
                        f"{sum(marks_by_code.get(name, 0) for name in replaces)}"
                    )
                if alternative.get("term_count") is not None:
                    problem = validate_spec(alternative.get("term_count"))
                    if problem:
                        report.problems.append(
                            f"question {question_id!r} alternative {code}: {problem}"
                        )

        expected = leaves.get(question_id)
        if expected is None:
            continue
        line = CoverageLine(
            question_id=question_id,
            expected_marks=expected,
            criteria_marks=recorded,
            criteria_count=len(criteria),
        )
        report.lines.append(line)
        if not line.matches:
            report.problems.append(
                f"question {question_id!r} carries {recorded} mark(s) in its criteria "
                f"but {expected} in the blueprint"
            )

    report.total_expected = sum(leaves.values())
    report.total_criteria = sum(line.criteria_marks for line in report.lines)
    declared = document.get("total_marks")
    if isinstance(declared, int) and declared != report.total_expected:
        report.problems.append(
            f"the document declares {declared} marks but the blueprint carries "
            f"{report.total_expected}"
        )
    if report.total_criteria != report.total_expected:
        report.problems.append(
            f"the criteria carry {report.total_criteria} marks in total, "
            f"not the paper's {report.total_expected}"
        )
    if report.lines and not report.problems:
        report.lines.sort(key=lambda line: line.question_id)
    return report


def _rule_value(row: Any, name: str, default: Any = None) -> Any:
    """Read one mark-rule field from an ORM row or from an imported document row."""

    if isinstance(row, Mapping):
        return row.get(name, default)
    return getattr(row, name, default)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _alternatives(value: Any) -> list[Any]:
    """Alternative routes in an order that does not depend on how they were written."""

    items = list(value or [])
    return sorted(items, key=_canonical)


def criteria_rules_hash(criteria: Iterable[Any], structure: Any) -> str:
    """A digest of the marking rules a person approved, and the paper they mark.

    Approving criteria without recording what was approved leaves the approval
    unable to detect its own drift: a changed mark point, a changed tolerance, a
    new dependency or a re-targeted alternative all leave ``criteria_approved_at``
    looking valid.  This digest covers every field that can change a mark — the
    criterion's identity, marks, description, printed answer, dependencies,
    alternative routes, award and withhold conditions — plus the blueprint leaves
    the rules were reviewed against.

    It is computed from the stored rows, so a verifier recomputes it from the
    database rather than trusting a stored file, and it is order-independent: the
    same rules imported in a different row order produce the same digest.  It
    does not replace ``criteria_blueprint_hash``; it covers the rules themselves.
    """

    rules: list[dict[str, Any]] = []
    for row in criteria:
        rules.append(
            {
                "question_id": str(_rule_value(row, "question_id", "") or ""),
                "code": str(_rule_value(row, "code", "") or ""),
                "ordinal": int(_rule_value(row, "ordinal", 0) or 0),
                "marks": int(_rule_value(row, "marks", 0) or 0),
                "description": str(_rule_value(row, "description", "") or ""),
                "expected_answer": _rule_value(row, "expected_answer"),
                "required_evidence": _rule_value(row, "required_evidence"),
                "dependencies": sorted(
                    str(dependency)
                    for dependency in (_rule_value(row, "dependencies") or [])
                ),
                "alternatives": _alternatives(_rule_value(row, "alternatives")),
                "award_conditions": _rule_value(row, "award_conditions"),
                "withhold_conditions": _rule_value(row, "withhold_conditions"),
            }
        )
    rules.sort(key=lambda rule: (rule["question_id"], rule["ordinal"], rule["code"]))
    payload = {
        "blueprint": sorted(blueprint_leaves(structure).items()),
        "rules": rules,
    }
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


#: Why imported criteria may not be used to mark with.
REASON_CRITERIA_MISSING = "SCHEME_CRITERIA_MISSING"
REASON_CRITERIA_NOT_APPROVED = "SCHEME_CRITERIA_NOT_APPROVED"
REASON_CRITERIA_BLUEPRINT_MISMATCH = "SCHEME_CRITERIA_BLUEPRINT_MISMATCH"
REASON_CRITERIA_RULES_UNVERIFIED = "SCHEME_CRITERIA_RULES_UNVERIFIED"
REASON_CRITERIA_RULES_CHANGED = "SCHEME_CRITERIA_RULES_CHANGED"
REASON_CRITERIA_INCOMPLETE = "SCHEME_CRITERIA_INCOMPLETE"


@dataclass(frozen=True, slots=True)
class CriteriaReadiness:
    """Whether a scheme version's imported criteria may be marked with."""

    ready: bool
    reason: str | None
    problems: tuple[str, ...]
    questions: int
    total_marks: int


def criteria_readiness(
    criteria: Iterable[Any],
    structure: Any,
    *,
    blueprint_version_id: Any,
    approved_against: Any,
    approved_at: Any,
    approved_rules_hash: str | None = None,
) -> CriteriaReadiness:
    """Whether imported criteria may be used to mark a job's blueprint.

    Importing rows is not enough.  A criterion set becomes usable only when all
    five hold: rows exist for the scheme version, a person approved them
    (``criteria_approved_at``), they were approved against the blueprint version
    the job marks, the approval records the rules it approved and those rules are
    still the stored ones, and every scoreable leaf carries its paper marks.
    Anything less means the engine would mark a question with no criteria — or
    with criteria from a different paper, or criteria changed after review — and
    report nothing about it.

    The rule digest is checked rather than assumed.  An approval that records no
    digest cannot show that the rows it approved are the rows being marked with,
    so it is not ready: re-approve the stored criteria to record what was
    reviewed.  That refusal is deliberate and fails closed before any provider
    request.

    This is a read-only comparison: it decides whether marking may start, and
    names what a person must fix when it may not.
    """

    rows = list(criteria)
    leaves = blueprint_leaves(structure)
    problems: list[str] = []
    if not rows:
        problems.append("no mark-scheme criteria are imported for this scheme version")
    if approved_at is None:
        problems.append(
            "the criteria have not been formally approved (criteria_approved_at is null)"
        )
    if approved_against is None:
        problems.append("the criteria name no blueprint version they were reviewed against")
    elif blueprint_version_id is not None and approved_against != blueprint_version_id:
        problems.append(
            f"the criteria were approved against blueprint {approved_against}, but this job "
            f"marks blueprint {blueprint_version_id}"
        )

    stored_hash: str | None = None
    if rows and approved_at is not None:
        stored_hash = criteria_rules_hash(rows, structure)
        if approved_rules_hash is None:
            problems.append(
                "the approval records no digest of the marking rules it approved, so "
                "the stored criteria cannot be shown to be the reviewed ones; "
                "re-approve them to record the digest"
            )
        elif stored_hash != approved_rules_hash:
            problems.append(
                "the marking rules changed after they were approved "
                f"(approved {approved_rules_hash[:16]}, stored {stored_hash[:16]}); "
                "re-approve them before marking with them"
            )

    # Where the coverage analysis starts.  Its findings decide the reason before
    # the approval-digest findings do: a criteria set that does not cover the
    # paper is incomplete whatever its approval says, and re-approving it must
    # fail too (``validate`` refuses the same paper).
    coverage_start = len(problems)

    recorded: dict[str, int] = defaultdict(int)
    for row in rows:
        question_id = str(getattr(row, "question_id", "")).strip()
        recorded[question_id] += int(getattr(row, "marks", 0) or 0)
    for question_id, expected in leaves.items():
        if question_id not in recorded:
            problems.append(f"question {question_id!r} has no criteria")
        elif recorded[question_id] != expected:
            problems.append(
                f"question {question_id!r} carries {recorded[question_id]} mark(s) in its "
                f"criteria but {expected} in the blueprint"
            )
    for question_id in recorded:
        if question_id not in leaves:
            problems.append(f"question {question_id!r} is not a scoreable leaf of the blueprint")

    reason: str | None = None
    if problems:
        if not rows:
            reason = REASON_CRITERIA_MISSING
        elif approved_at is None:
            reason = REASON_CRITERIA_NOT_APPROVED
        elif approved_against is None or approved_against != blueprint_version_id:
            reason = REASON_CRITERIA_BLUEPRINT_MISMATCH
        elif len(problems) > coverage_start:
            reason = REASON_CRITERIA_INCOMPLETE
        elif approved_rules_hash is None:
            reason = REASON_CRITERIA_RULES_UNVERIFIED
        elif stored_hash != approved_rules_hash:
            reason = REASON_CRITERIA_RULES_CHANGED
        else:
            reason = REASON_CRITERIA_INCOMPLETE

    return CriteriaReadiness(
        ready=not problems,
        reason=reason,
        problems=tuple(problems),
        questions=len(leaves),
        total_marks=sum(recorded.get(question_id, 0) for question_id in leaves),
    )


def rows_as_document(rows: Iterable[Any]) -> dict[str, Any]:
    """Rebuild the transcribed document shape from stored criteria rows.

    ``validate`` was written against the model's document.  Approval has to
    re-check the rows that will actually mark, so they are put back into that
    shape.  Nothing is inferred here: a row's stored fields *are* the document,
    which is what makes the re-check cover the rows rather than the reply.
    """

    entries: dict[str, dict[str, Any]] = {}
    for row in rows:
        question_id = str(_rule_value(row, "question_id", "") or "").strip()
        entry = entries.setdefault(
            question_id,
            {"question_id": question_id, "criteria": []},
        )
        entry["criteria"].append(
            {
                "code": str(_rule_value(row, "code", "") or ""),
                "marks": int(_rule_value(row, "marks", 0) or 0),
                "ordinal": int(_rule_value(row, "ordinal", 0) or 0),
                "description": str(_rule_value(row, "description", "") or ""),
                "expected_answer": _rule_value(row, "expected_answer"),
                "required_evidence": _rule_value(row, "required_evidence"),
                "dependencies": list(_rule_value(row, "dependencies") or []),
                "alternatives": list(_rule_value(row, "alternatives") or []),
                "award_conditions": _rule_value(row, "award_conditions"),
                "withhold_conditions": _rule_value(row, "withhold_conditions"),
                "source_page": _rule_value(row, "source_page"),
                "source_quote": _rule_value(row, "source_quote"),
            }
        )
    return {"questions": list(entries.values())}


def iter_criteria(document: dict[str, Any]) -> Iterable[dict[str, Any]]:
    """Flatten the document into one row per printed mark point.

    ``source_page`` and ``source_quote`` are copied onto the row so a reviewer can
    check the transcription without reopening the PDF.
    """

    for entry in document.get("questions") or []:
        question_id = str(entry.get("question_id", "")).strip()
        source_ref = dict(entry.get("source_ref") or {})
        for ordinal, criterion in enumerate(entry.get("criteria") or []):
            yield {
                "question_id": question_id,
                "code": str(criterion.get("code", "")).strip(),
                "marks": int(criterion.get("marks") or 0),
                "ordinal": int(criterion.get("ordinal", ordinal) or ordinal),
                "description": str(criterion.get("description") or "").strip(),
                "expected_answer": criterion.get("expected_answer"),
                "required_evidence": criterion.get("required_evidence"),
                "dependencies": list(criterion.get("dependencies") or []),
                "alternatives": list(criterion.get("alternatives") or []),
                "award_conditions": criterion.get("award_conditions"),
                "withhold_conditions": criterion.get("withhold_conditions"),
                "source_ref": {
                    **source_ref,
                    "source_quote": criterion.get("source_quote"),
                },
                "source_page": criterion.get("source_page", source_ref.get("pdf_page")),
                "source_quote": criterion.get("source_quote"),
            }
