"""What one whole-paper request actually contains.

A test that only checks ``marking_mode == "WHOLE_PAPER"`` proves that a flag was
set, not that the paper was sent.  These tests read the constructed request: every
page in order, every scoreable leaf, and the whole of the approved scheme — the
printed answer, the required evidence, dependent marks, the alternative routes and
what they replace, and the award/withhold conditions.  A paper request that names
the questions but withholds the scheme would invite invented awards while still
reporting the paper as marked.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from types import SimpleNamespace

from app.correction.aetrix.pipeline import _criterion_lines, _MarkingRun
from app.storage.base import StorageError

SEED = Path(__file__).resolve().parents[2] / "seed" / "pilot_scheme_v1_criteria.json"


class _Storage:
    def __init__(self, *, missing: int | None = None) -> None:
        self.read_keys: list[str] = []
        self.missing = missing

    def read(self, key: str) -> bytes:
        self.read_keys.append(key)
        index = int(key.rsplit("-", 1)[-1])
        if self.missing is not None and index == self.missing:
            raise StorageError("gone")
        return f"png-{index}".encode()


def _criterion(
    code: str,
    marks: int = 1,
    *,
    description: str = "awarded for the stated work",
    expected_answer: str | None = None,
    required_evidence: str | None = None,
    dependencies: list[str] | None = None,
    alternatives: list[dict] | None = None,
    award_conditions: str | None = None,
    withhold_conditions: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        code=code,
        marks=marks,
        description=description,
        expected_answer=expected_answer,
        required_evidence=required_evidence,
        dependencies=dependencies or [],
        alternatives=alternatives or [],
        award_conditions=award_conditions,
        withhold_conditions=withhold_conditions,
    )


def _run(
    *,
    pages: int = 5,
    page_cap: int = 12,
    criteria: dict[str, list] | None = None,
    storage: _Storage | None = None,
) -> _MarkingRun:
    run = object.__new__(_MarkingRun)
    run.job = SimpleNamespace(id=uuid.uuid4())
    run.settings = SimpleNamespace(
        marking=SimpleNamespace(
            whole_paper_max_pages=page_cap,
            whole_paper_max_output_tokens=32768,
        )
    )
    run.readable = [
        SimpleNamespace(page_index=index, storage_key=f"page-{index}")
        for index in range(pages)
    ]
    run.criteria_by_question = criteria or {}
    run.storage = storage or _Storage()
    run._blueprint_question = lambda parent, question_id: None  # type: ignore[method-assign]
    return run


def _leaves(ids: list[str], max_marks: int = 2) -> list[tuple[str, int, str | None, str]]:
    return [(question_id, max_marks, "MATHEMATICAL", question_id) for question_id in ids]


def test_every_page_of_the_script_is_sent_once_and_in_order() -> None:
    storage = _Storage()
    run = _run(pages=7, storage=storage)

    parts = run._paper_inputs(_leaves(["1a", "1b", "1c"]))

    assert parts is not None
    text, *rest = parts
    assert text.text is not None
    images = [part for part in rest if part.image is not None]
    labels = [part.text for part in rest if part.image is None]
    assert len(images) == 7, "a page of the script was dropped from the request"
    assert [part.image for part in images] == [
        f"png-{index}".encode() for index in range(7)
    ]
    assert storage.read_keys == [f"page-{index}" for index in range(7)]
    assert all(part.mime_type == "image/png" for part in images)
    # Each image is preceded by its own page number, and the number is the
    # page's index in the original document — not its position in this request,
    # which is what allows a quotation to be attributed to a real page later.
    assert len(labels) == 7
    for index, label in enumerate(labels):
        assert label is not None
        assert label.startswith(f"Page {index} of 7 supplied"), label


def test_a_script_over_the_page_cap_is_refused_instead_of_thinned() -> None:
    storage = _Storage()
    run = _run(pages=13, page_cap=12, storage=storage)

    assert run._paper_inputs(_leaves(["1a"])) is None
    assert storage.read_keys == [], "a refused paper must not be partially read"


def test_the_request_names_every_leaf_it_asks_for() -> None:
    run = _run(criteria={})

    context = run._paper_context(_leaves(["1a", "2", "3b"], max_marks=4))

    assert "Questions to mark: 3" in context
    for question_id in ("Question: 1a", "Question: 2", "Question: 3b"):
        assert question_id in context
    assert "Maximum marks: 4" in context


def test_the_request_carries_the_whole_scheme_not_just_codes_and_marks() -> None:
    criteria = {
        "18": [
            _criterion(
                "M1",
                description="expands both brackets",
                expected_answer="8x^2 + 64x + 120",
                required_evidence="all eight terms written out",
                alternatives=[
                    {
                        "code": "M2",
                        "marks": 2,
                        "rule": "complete expansion with the eight terms present",
                        "replaces": ["M1"],
                    }
                ],
                award_conditions="accept any order of terms",
                withhold_conditions="do not award if a bracket is missing",
            ),
            _criterion(
                "A1",
                description="correct simplified answer",
                dependencies=["M1"],
                expected_answer="(2x + 3)(x + 8)",
            ),
        ],
        "13": [
            _criterion(
                "M1",
                description="factorises",
                alternatives=[
                    {
                        "method": "factorise first",
                        "expression": "(2x + 3)[(2x + 3) - (x - 5)]",
                    }
                ],
            )
        ],
    }
    run = _run(criteria=criteria)

    context = run._paper_context(_leaves(["18", "13"]))

    assert "M1#1 (1 mark(s)): expands both brackets" in context
    assert "A1#2 (1 mark(s)): correct simplified answer" in context
    assert "scheme answer: 8x^2 + 64x + 120" in context
    assert "must show: all eight terms written out" in context
    assert "alternative M2 (2 mark(s)) replaces M1: complete expansion" in context
    assert "award when: accept any order of terms" in context
    assert "withhold when: do not award if a bracket is missing" in context
    assert "only after: M1" in context
    assert "alternative method: factorise first" in context
    assert "(2x + 3)[(2x + 3) - (x - 5)]" in context
    assert "M1#1 (1 mark(s)): factorises" in context


def test_a_conditional_alternative_states_its_term_threshold() -> None:
    lines = _criterion_lines(
        [
            _criterion(
                "M1",
                alternatives=[
                    {
                        "code": "M2",
                        "marks": 2,
                        "rule": "at least 6 of the 8 terms correct",
                        "replaces": ["M1"],
                        "term_count": {
                            "count": 6,
                            "required": 8,
                            "expression": "(2x + 3)(4x + 5)",
                        },
                    }
                ],
            )
        ]
    )

    rendered = "\n".join(lines)
    assert "at least 6 of the 8 terms correct" in rendered
    assert "term count: 6 of a maximum of 8 terms in (2x + 3)(4x + 5)" in rendered


def test_the_shipped_pilot_scheme_renders_completely() -> None:
    """The real 39-leaf, 89-mark scheme fits one text part with nothing dropped."""

    data = json.loads(SEED.read_text(encoding="utf-8"))
    criteria: dict[str, list] = {}
    leaves: list[tuple[str, int, str | None, str]] = []
    for question in data["questions"]:
        question_id = question["question_id"]
        leaves.append((question_id, question["max_marks"], "MATHEMATICAL", question_id))
        criteria[question["question_id"]] = [
            _criterion(
                item["code"],
                item["marks"],
                description=item["description"],
                expected_answer=item.get("expected_answer"),
                required_evidence=item.get("required_evidence"),
                dependencies=item.get("dependencies") or [],
                alternatives=item.get("alternatives") or [],
                award_conditions=item.get("award_conditions"),
                withhold_conditions=item.get("withhold_conditions"),
            )
            for item in question["criteria"]
        ]

    run = _run(criteria=criteria, pages=8)

    context = run._paper_context(leaves)

    assert len(leaves) == 39
    assert sum(leaf[1] for leaf in leaves) == 89
    for question in data["questions"]:
        for position, item in enumerate(question["criteria"], start=1):
            assert (
                f"{item['code']}#{position} ({item['marks']} mark(s)): "
                f"{item['description']}"
            ) in context, (question["question_id"], item["code"], position)
            if item.get("expected_answer"):
                assert f"scheme answer: {item['expected_answer']}" in context
            if item.get("dependencies"):
                assert f"only after: {', '.join(item['dependencies'])}" in context
            for alternative in item.get("alternatives") or []:
                if alternative.get("code"):
                    assert f"alternative {alternative['code']}" in context
                else:
                    assert f"alternative method: {alternative['method']}" in context
    # The scheme is text alone; the pages are the only images in the request.
    assert len(context) < 40_000
