"""The evaluation harness must refuse anything that is not certified ground truth.

These tests pin the refusal, the metric arithmetic and the paired comparison on a
tiny synthetic holdout, so the harness is proven before any certified paper exists.
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


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _reference(tmp_path: Path, *, status: str = "teacher_certified") -> Path:
    root = tmp_path / "reference"
    _write(
        root / "p1.json",
        {
            "paper_id": "p1",
            "certification": {"status": status, "marker_count": 2, "adjudicated": True},
            "items": [
                {"id": "1a", "max_marks": 2, "awarded": 2},
                {"id": "1b", "max_marks": 1, "awarded": 1},
            ],
        },
    )
    _write(
        root / "p2.json",
        {
            "paper_id": "p2",
            "certification": {"status": "teacher_certified"},
            "items": [{"id": "1a", "max_marks": 1, "awarded": 1}],
        },
    )
    return root


def _runs(tmp_path: Path) -> Path:
    root = tmp_path / "runs"
    _write(
        root / "prompt_v1" / "p1.json",
        {
            "paper_id": "p1",
            "items": [
                {"id": "1a", "awarded": 2, "review_required": False},
                {"id": "1b", "awarded": 0, "review_required": False},
            ],
            "usage": {"requests": 2, "input_tokens": 100, "cost_usd": 0.01},
        },
    )
    _write(
        root / "prompt_v1" / "p2.json",
        {
            "paper_id": "p2",
            "items": [{"id": "1a", "awarded": 1, "review_required": False}],
            "usage": {"requests": 1, "input_tokens": 50, "cost_usd": 0.005},
        },
    )
    _write(
        root / "prompt_v2" / "p1.json",
        {
            "paper_id": "p1",
            "items": [
                {"id": "1a", "awarded": 1, "review_required": True},
                {"id": "1b", "awarded": 1, "review_required": False},
            ],
            "usage": {"requests": 2, "input_tokens": 100, "cost_usd": 0.01},
        },
    )
    _write(
        root / "prompt_v2" / "p2.json",
        {
            "paper_id": "p2",
            "items": [{"id": "1a", "awarded": 1, "review_required": True}],
            "usage": {"requests": 1, "input_tokens": 50, "cost_usd": 0.005},
        },
    )
    return root


def test_a_candidate_reference_is_refused(tmp_path: Path) -> None:
    with pytest.raises(evaluate.NotCertified):
        evaluate.load_reference(_reference(tmp_path, status="candidate_not_teacher_certified"))


def test_an_empty_reference_directory_is_refused(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        evaluate.load_reference(tmp_path / "missing")


def test_metrics_are_counted_from_the_reference(tmp_path: Path) -> None:
    references = evaluate.load_reference(_reference(tmp_path))
    runs = evaluate.load_runs(_runs(tmp_path), references)

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
    references = evaluate.load_reference(_reference(tmp_path))
    runs = evaluate.load_runs(_runs(tmp_path), references)

    report = evaluate.evaluate(references, runs)

    v2 = report["configs"]["prompt_v2"]["summary"]
    assert v2["review_false_positives"] == 1, "a correct award sent to a person"
    assert v2["review_false_negatives"] == 0
    assert v2["wrong_items_caught"] == 1
    assert v2["human_review_rate_percent"] == 66.67


def test_the_paired_comparison_names_its_baseline(tmp_path: Path) -> None:
    references = evaluate.load_reference(_reference(tmp_path))
    runs = evaluate.load_runs(_runs(tmp_path), references)

    report = evaluate.evaluate(references, runs)

    assert report["paired"]["baseline"] == "prompt_v1"
    comparison = report["paired"]["comparisons"]["prompt_v2"]
    assert comparison["papers"] == 2
    assert comparison["mean_difference"] == 0.0
    assert comparison["candidate_better"] is False


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


def test_a_run_for_an_uncertified_paper_is_not_scored(tmp_path: Path) -> None:
    references = evaluate.load_reference(_reference(tmp_path))
    _write(
        tmp_path / "runs" / "prompt_v1" / "p9.json",
        {"paper_id": "p9", "items": [{"id": "1a", "awarded": 1}]},
    )
    runs = evaluate.load_runs(_runs(tmp_path), references)

    assert sorted(paper.paper_id for paper in runs["prompt_v1"]) == ["p1", "p2"]
