"""The evaluation harness must refuse anything that is not certified ground truth.

These tests pin the refusal of uncertified or malformed references, the refusal of
a run that omits a certified question, the metric arithmetic and the paired
paper-level comparison, so the harness is proven before any certified paper exists.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "experiment" / "live_validation" / "evaluate.py"
_spec = importlib.util.spec_from_file_location("live_evaluate", MODULE_PATH)
evaluate = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
# The module must be registered before execution so its dataclasses can resolve
# their own annotations through `sys.modules`.
sys.modules["live_evaluate"] = evaluate
_spec.loader.exec_module(evaluate)

CERTIFIED = {
    "status": "teacher_certified",
    "marker_count": 2,
    "adjudicated": True,
    "adjudicator": "adj-1",
    "certified_at": "2026-11-20",
    "source": "reference-set-3",
}


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _item(
    item_id: str,
    *,
    max_marks: int,
    awarded: int,
    first: int | None = None,
    second: int | None = None,
    adjudication: dict | None = None,
) -> dict:
    first = awarded if first is None else first
    second = awarded if second is None else second
    body = {
        "id": item_id,
        "max_marks": max_marks,
        "awarded": awarded,
        "marker_marks": {"m1": first, "m2": second},
    }
    if adjudication is not None:
        body["adjudication"] = adjudication
    return body


def _reference(
    tmp_path: Path,
    *,
    status: str = "teacher_certified",
    marker_count: int = 2,
    adjudicated: bool = True,
    markers: list[dict] | None = None,
) -> Path:
    root = tmp_path / "reference"
    certification = {
        **CERTIFIED,
        "status": status,
        "marker_count": marker_count,
        "adjudicated": adjudicated,
    }
    _write(
        root / "p1.json",
        {
            "paper_id": "p1",
            "certification": certification,
            "markers": markers if markers is not None else [{"id": "m1"}, {"id": "m2"}],
            "items": [
                _item("1a", max_marks=2, awarded=2),
                _item("1b", max_marks=1, awarded=1),
            ],
        },
    )
    _write(
        root / "p2.json",
        {
            "paper_id": "p2",
            "certification": {**CERTIFIED, "status": status},
            "markers": [{"id": "m1"}, {"id": "m2"}],
            "items": [_item("1a", max_marks=1, awarded=1)],
        },
    )
    return root


def _run(
    paper_id: str,
    items: list[dict],
    *,
    config: str = "prompt_v1",
    **overrides,
) -> dict:
    payload = {
        "paper_id": paper_id,
        "config": config,
        "engine": "aetrix_v5_5",
        "prompt_versions": {"marking": "aetrix_v5_5_marking:v1"},
        "items": items,
        "usage": {"requests": 2, "input_tokens": 100, "output_tokens": 20, "cost_usd": 0.01},
    }
    payload.update(overrides)
    # The per-question provenance is what the result row stores.  Tests that need
    # a defect remove or change it after calling this helper.
    marking_version = payload["prompt_versions"].get("marking")
    payload["items"] = [
        {**item, "prompt_version": item.get("prompt_version", marking_version)}
        for item in payload["items"]
    ]
    return payload


def _runs(tmp_path: Path) -> Path:
    root = tmp_path / "runs"
    _write(
        root / "prompt_v1" / "p1.json",
        _run(
            "p1",
            [
                {"id": "1a", "awarded": 2, "review_required": False},
                {"id": "1b", "awarded": 0, "review_required": False},
            ],
        ),
    )
    _write(
        root / "prompt_v1" / "p2.json",
        _run(
            "p2",
            [{"id": "1a", "awarded": 1, "review_required": False}],
            config="prompt_v1",
            usage={"requests": 1, "input_tokens": 50, "output_tokens": 10, "cost_usd": 0.005},
        ),
    )
    _write(
        root / "prompt_v2" / "p1.json",
        _run(
            "p1",
            [
                {"id": "1a", "awarded": 1, "review_required": True},
                {"id": "1b", "awarded": 1, "review_required": False},
            ],
            config="prompt_v2",
            prompt_versions={"marking": "aetrix_v5_5_marking:v2"},
        ),
    )
    _write(
        root / "prompt_v2" / "p2.json",
        _run(
            "p2",
            [{"id": "1a", "awarded": 1, "review_required": True}],
            config="prompt_v2",
            prompt_versions={"marking": "aetrix_v5_5_marking:v2"},
            usage={"requests": 1, "input_tokens": 50, "output_tokens": 10, "cost_usd": 0.005},
        ),
    )
    return root


def _load(tmp_path: Path):
    references = evaluate.load_reference(_reference(tmp_path))
    return references, evaluate.load_runs(_runs(tmp_path), references)


# -- certification ---------------------------------------------------------


def test_a_candidate_reference_is_refused(tmp_path: Path) -> None:
    with pytest.raises(evaluate.NotCertified):
        evaluate.load_reference(_reference(tmp_path, status="candidate_not_teacher_certified"))


def test_a_reference_with_one_marker_is_refused(tmp_path: Path) -> None:
    reference = _reference(tmp_path, marker_count=1, markers=[{"id": "m1"}])
    with pytest.raises(evaluate.ReferenceInvalid, match=r"marker_count|marker"):
        evaluate.load_reference(reference)


def test_a_reference_that_was_not_adjudicated_is_refused(tmp_path: Path) -> None:
    with pytest.raises(evaluate.ReferenceInvalid, match="adjudicated"):
        evaluate.load_reference(_reference(tmp_path, adjudicated=False))


def test_a_reference_without_marker_evidence_is_refused(tmp_path: Path) -> None:
    root = _reference(tmp_path)
    payload = json.loads((root / "p1.json").read_text(encoding="utf-8"))
    del payload["markers"]
    _write(root / "p1.json", payload)
    with pytest.raises(evaluate.ReferenceInvalid, match="markers"):
        evaluate.load_reference(root)


def test_unadjudicated_marker_disagreement_is_refused(tmp_path: Path) -> None:
    root = _reference(tmp_path)
    payload = json.loads((root / "p1.json").read_text(encoding="utf-8"))
    payload["items"][0] = _item("1a", max_marks=2, awarded=2, first=1, second=2)
    _write(root / "p1.json", payload)
    with pytest.raises(evaluate.ReferenceInvalid, match="adjudication"):
        evaluate.load_reference(root)


def test_an_adjudication_by_one_of_the_markers_is_refused(tmp_path: Path) -> None:
    root = _reference(tmp_path)
    payload = json.loads((root / "p1.json").read_text(encoding="utf-8"))
    payload["items"][0] = _item(
        "1a",
        max_marks=2,
        awarded=2,
        first=1,
        second=2,
        adjudication={"adjudicator": "m1", "awarded": 2, "reason": "marker 2 is right"},
    )
    _write(root / "p1.json", payload)
    with pytest.raises(evaluate.ReferenceInvalid, match="independent"):
        evaluate.load_reference(root)


def test_an_adjudication_mark_that_contradicts_the_final_award_is_refused(
    tmp_path: Path,
) -> None:
    root = _reference(tmp_path)
    payload = json.loads((root / "p1.json").read_text(encoding="utf-8"))
    payload["items"][0] = _item(
        "1a",
        max_marks=2,
        awarded=2,
        first=1,
        second=2,
        adjudication={"adjudicator": "adj-1", "awarded": 1, "reason": "one mark"},
    )
    _write(root / "p1.json", payload)
    with pytest.raises(evaluate.ReferenceInvalid, match="adjudication says"):
        evaluate.load_reference(root)


def test_a_marker_disagreement_with_a_matching_adjudication_is_accepted(
    tmp_path: Path,
) -> None:
    root = _reference(tmp_path)
    payload = json.loads((root / "p1.json").read_text(encoding="utf-8"))
    payload["items"][0] = _item(
        "1a",
        max_marks=2,
        awarded=2,
        first=1,
        second=2,
        adjudication={"adjudicator": "adj-1", "awarded": 2, "reason": "answer is correct"},
    )
    _write(root / "p1.json", payload)

    references = evaluate.load_reference(root)

    assert references["p1"]["1a"].awarded == 2


def test_duplicate_item_ids_are_refused(tmp_path: Path) -> None:
    root = _reference(tmp_path)
    payload = json.loads((root / "p1.json").read_text(encoding="utf-8"))
    payload["items"].append(_item("1a", max_marks=2, awarded=2))
    _write(root / "p1.json", payload)
    with pytest.raises(evaluate.ReferenceInvalid, match="duplicate"):
        evaluate.load_reference(root)


def test_a_paper_id_that_does_not_match_its_file_is_refused(tmp_path: Path) -> None:
    root = _reference(tmp_path)
    payload = json.loads((root / "p1.json").read_text(encoding="utf-8"))
    payload["paper_id"] = "p9"
    _write(root / "p1.json", payload)
    with pytest.raises(evaluate.ReferenceInvalid, match="file name"):
        evaluate.load_reference(root)


def test_an_empty_reference_directory_is_refused(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        evaluate.load_reference(tmp_path / "missing")


# -- run completeness and provenance --------------------------------------


def test_a_run_missing_a_certified_question_is_refused(tmp_path: Path) -> None:
    references = evaluate.load_reference(_reference(tmp_path))
    root = _runs(tmp_path)
    _write(
        root / "prompt_v1" / "p1.json",
        _run("p1", [{"id": "1a", "awarded": 2, "review_required": False}]),
    )

    with pytest.raises(evaluate.ReferenceInvalid, match="no result for certified item"):
        evaluate.load_runs(root, references)


def test_a_run_with_an_item_outside_the_reference_is_refused(tmp_path: Path) -> None:
    references = evaluate.load_reference(_reference(tmp_path))
    root = _runs(tmp_path)
    _write(
        root / "prompt_v1" / "p1.json",
        _run(
            "p1",
            [
                {"id": "1a", "awarded": 2, "review_required": False},
                {"id": "1b", "awarded": 1, "review_required": False},
                {"id": "9z", "awarded": 1, "review_required": False},
            ],
        ),
    )

    with pytest.raises(evaluate.ReferenceInvalid, match="not in the certified reference"):
        evaluate.load_runs(root, references)


def test_a_run_without_prompt_provenance_is_refused(tmp_path: Path) -> None:
    references = evaluate.load_reference(_reference(tmp_path))
    root = _runs(tmp_path)
    _write(
        root / "prompt_v1" / "p1.json",
        _run(
            "p1",
            [
                {"id": "1a", "awarded": 2, "review_required": False},
                {"id": "1b", "awarded": 1, "review_required": False},
            ],
            prompt_versions={},
        ),
    )

    with pytest.raises(evaluate.ReferenceInvalid, match="prompt_versions"):
        evaluate.load_runs(root, references)


def test_a_run_without_per_question_prompt_version_is_refused(tmp_path: Path) -> None:
    """The harness records what each result row says it was marked with."""

    references = evaluate.load_reference(_reference(tmp_path))
    root = _runs(tmp_path)
    payload = _run(
        "p1",
        [
            {"id": "1a", "awarded": 2, "review_required": False},
            {"id": "1b", "awarded": 1, "review_required": False},
        ],
    )
    del payload["items"][0]["prompt_version"]
    _write(root / "prompt_v1" / "p1.json", payload)

    with pytest.raises(evaluate.ReferenceInvalid, match="prompt_version"):
        evaluate.load_runs(root, references)


def test_a_run_that_mixes_prompt_versions_is_refused(tmp_path: Path) -> None:
    references = evaluate.load_reference(_reference(tmp_path))
    root = _runs(tmp_path)
    payload = _run(
        "p1",
        [
            {"id": "1a", "awarded": 2, "review_required": False},
            {"id": "1b", "awarded": 1, "review_required": False},
        ],
        prompt_versions={"marking": "aetrix_v5_5_marking:v2"},
    )
    payload["items"][1]["prompt_version"] = "aetrix_v5_5_marking:v1"
    _write(root / "prompt_v1" / "p1.json", payload)

    with pytest.raises(evaluate.ReferenceInvalid, match="must not mix"):
        evaluate.load_runs(root, references)


def test_a_run_without_usage_is_refused(tmp_path: Path) -> None:
    references = evaluate.load_reference(_reference(tmp_path))
    root = _runs(tmp_path)
    _write(
        root / "prompt_v1" / "p1.json",
        _run(
            "p1",
            [
                {"id": "1a", "awarded": 2, "review_required": False},
                {"id": "1b", "awarded": 1, "review_required": False},
            ],
            usage={},
        ),
    )

    with pytest.raises(evaluate.ReferenceInvalid, match="usage"):
        evaluate.load_runs(root, references)


def test_a_run_whose_config_contradicts_its_directory_is_refused(tmp_path: Path) -> None:
    references = evaluate.load_reference(_reference(tmp_path))
    root = _runs(tmp_path)
    _write(
        root / "prompt_v1" / "p1.json",
        _run(
            "p1",
            [
                {"id": "1a", "awarded": 2, "review_required": False},
                {"id": "1b", "awarded": 1, "review_required": False},
            ],
            config="prompt_v2",
        ),
    )

    with pytest.raises(evaluate.ReferenceInvalid, match="directory"):
        evaluate.load_runs(root, references)


# -- metrics ---------------------------------------------------------------


def test_metrics_are_counted_from_the_reference(tmp_path: Path) -> None:
    references, runs = _load(tmp_path)

    report = evaluate.evaluate(references, runs)

    v1 = report["configs"]["prompt_v1"]["summary"]
    assert v1["items"] == 3
    assert v1["exact_item_accuracy_percent"] == 66.67
    assert v1["within_one_item_accuracy_percent"] == 100.0
    assert v1["mark_agreement_percent"] == 75.0
    assert v1["paper_total_exact"] == 1
    assert v1["under_awarded_items"] == 1
    assert v1["under_awarded_marks"] == 1
    assert v1["review_false_negatives"] == 1, "a wrong award presented without review"
    assert v1["requests_per_paper"] == 1.5
    assert v1["usage_recorded"] is True


def test_review_false_positives_are_counted_separately(tmp_path: Path) -> None:
    references, runs = _load(tmp_path)

    report = evaluate.evaluate(references, runs)

    v2 = report["configs"]["prompt_v2"]["summary"]
    assert v2["review_false_positives"] == 1, "a correct award sent to a person"
    assert v2["review_false_negatives"] == 0
    assert v2["wrong_items_caught"] == 1
    assert v2["human_review_rate_percent"] == 66.67


def test_over_and_under_awards_are_separated(tmp_path: Path) -> None:
    references = evaluate.load_reference(_reference(tmp_path))
    root = tmp_path / "runs_over"
    _write(
        root / "prompt_v1" / "p1.json",
        _run(
            "p1",
            [
                {"id": "1a", "awarded": 2, "review_required": False},
                {"id": "1b", "awarded": 1, "review_required": False},
            ],
        ),
    )
    _write(
        root / "prompt_v1" / "p2.json",
        _run("p2", [{"id": "1a", "awarded": 1, "review_required": False}]),
    )
    runs = evaluate.load_runs(root, references)

    summary = evaluate.evaluate(references, runs)["configs"]["prompt_v1"]["summary"]

    assert summary["over_awarded_items"] == 0
    assert summary["under_awarded_items"] == 0
    assert summary["mean_absolute_paper_error"] == 0
    assert summary["mark_agreement_percent"] == 100.0


def test_each_wrong_item_is_reported_with_the_reference_beside_it(tmp_path: Path) -> None:
    references, runs = _load(tmp_path)

    report = evaluate.evaluate(references, runs)
    p1 = next(
        paper for paper in report["configs"]["prompt_v1"]["papers"] if paper["paper_id"] == "p1"
    )

    assert p1["item_errors"] == [
        {
            "id": "1b",
            "awarded": 0,
            "expected": 1,
            "delta": -1,
            "review_required": False,
        }
    ]


def test_the_paired_comparison_names_its_baseline_and_its_unit(tmp_path: Path) -> None:
    references, runs = _load(tmp_path)

    report = evaluate.evaluate(references, runs)

    assert report["paired"]["baseline"] == "prompt_v1"
    comparison = report["paired"]["comparisons"]["prompt_v2"]
    assert comparison["papers"] == 2
    assert comparison["mean_difference"] == 0.0
    assert comparison["candidate_better"] is False
    assert comparison["unit"] == "paper"
    assert comparison["shared_papers"] == ["p1", "p2"]


def test_the_report_records_the_provenance_of_every_configuration(tmp_path: Path) -> None:
    references, runs = _load(tmp_path)

    report = evaluate.evaluate(references, runs)

    assert report["provenance"]["prompt_v1"]["engines"] == ["aetrix_v5_5"]
    assert report["provenance"]["prompt_v1"]["question_prompt_versions"] == [
        "aetrix_v5_5_marking:v1"
    ]
    assert "marking=aetrix_v5_5_marking:v1" in report["provenance"]["prompt_v1"][
        "prompt_versions"
    ]
    assert "marking=aetrix_v5_5_marking:v2" in report["provenance"]["prompt_v2"][
        "prompt_versions"
    ]


def test_every_question_carries_its_actual_provenance_in_the_report(tmp_path: Path) -> None:
    references, runs = _load(tmp_path)

    report = evaluate.evaluate(references, runs)
    p1 = next(
        paper for paper in report["configs"]["prompt_v1"]["papers"] if paper["paper_id"] == "p1"
    )

    assert p1["question_provenance"] == [
        {
            "id": "1a",
            "engine": "aetrix_v5_5",
            "config": "prompt_v1",
            "prompt_version": "aetrix_v5_5_marking:v1",
        },
        {
            "id": "1b",
            "engine": "aetrix_v5_5",
            "config": "prompt_v1",
            "prompt_version": "aetrix_v5_5_marking:v1",
        },
    ]


def test_scoring_the_same_inputs_twice_is_byte_identical(tmp_path: Path) -> None:
    references, runs = _load(tmp_path)

    first = json.dumps(evaluate.evaluate(references, runs), sort_keys=True)
    second = json.dumps(evaluate.evaluate(references, runs), sort_keys=True)

    assert first == second


# -- command behaviour -----------------------------------------------------


def test_an_uncertified_reference_exits_with_a_refusal(tmp_path: Path, capsys) -> None:
    reference = _reference(tmp_path, status="candidate_not_teacher_certified")
    runs = _runs(tmp_path)
    output = tmp_path / "out.json"

    code = evaluate.main(
        ["--references", str(reference), "--runs", str(runs), "--output", str(output)]
    )

    assert code == 2
    assert "refused" in capsys.readouterr().err
    assert not output.exists(), "a refused run must not write a results file"


def test_a_malformed_reference_exits_with_a_refusal(tmp_path: Path, capsys) -> None:
    reference = _reference(tmp_path, marker_count=1, markers=[{"id": "m1"}])
    runs = _runs(tmp_path)
    output = tmp_path / "out.json"

    code = evaluate.main(
        ["--references", str(reference), "--runs", str(runs), "--output", str(output)]
    )

    assert code == 2
    assert "refused" in capsys.readouterr().err
    assert not output.exists()


def test_a_run_for_an_uncertified_paper_is_excluded_and_reported(tmp_path: Path) -> None:
    references = evaluate.load_reference(_reference(tmp_path))
    root = _runs(tmp_path)
    _write(
        root / "prompt_v1" / "p9.json",
        _run("p9", [{"id": "1a", "awarded": 1, "review_required": False}]),
    )
    excluded: list[dict[str, str]] = []

    runs = evaluate.load_runs(root, references, excluded=excluded)

    assert sorted(paper.paper_id for paper in runs["prompt_v1"]) == ["p1", "p2"]
    assert excluded == [
        {
            "config": "prompt_v1",
            "file": "p9.json",
            "paper_id": "p9",
            "reason": "no certified reference for this paper",
        }
    ]
    report = evaluate.evaluate(references, runs, excluded=excluded)
    assert report["excluded_runs"] == excluded
