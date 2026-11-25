"""A dataset gate that accepts only complete, independently marked references.

The harness refuses bad input while scoring; this validator is what an operator
runs first, and these tests pin the failures it must catch before any request is
spent.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "experiment" / "live_validation" / "validate_dataset.py"
_spec = importlib.util.spec_from_file_location("dataset_validator", MODULE_PATH)
validator = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
sys.modules["dataset_validator"] = validator
_spec.loader.exec_module(validator)


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _item(item_id: str, *, max_marks: int, awarded: int, first: int | None = None,
          second: int | None = None, adjudication: dict | None = None) -> dict:
    body = {
        "id": item_id,
        "max_marks": max_marks,
        "awarded": awarded,
        "marker_marks": {
            "m1": awarded if first is None else first,
            "m2": awarded if second is None else second,
        },
    }
    if adjudication is not None:
        body["adjudication"] = adjudication
    return body


def _dataset(tmp_path: Path, *, papers: dict[str, list[dict]] | None = None) -> Path:
    root = tmp_path / "reference"
    payloads = papers or {
        "p1": [
            _item("1a", max_marks=2, awarded=2),
            _item("1b", max_marks=1, awarded=0),
        ],
        "p2": [_item("1a", max_marks=1, awarded=1)],
    }
    for paper_id, items in payloads.items():
        _write(
            root / f"{paper_id}.json",
            {
                "paper_id": paper_id,
                "certification": {
                    "status": "teacher_certified",
                    "marker_count": 2,
                    "adjudicated": True,
                    "adjudicator": "adj-1",
                    "certified_at": "2026-11-20",
                    "source": "reference-set-3",
                },
                "markers": [{"id": "m1"}, {"id": "m2"}],
                "items": items,
            },
        )
    return root


def test_a_complete_dataset_is_valid(tmp_path: Path) -> None:
    manifest = validator.build_manifest(_dataset(tmp_path))

    assert manifest["format"] == validator.MANIFEST_FORMAT
    assert manifest["paper_count"] == 2
    assert manifest["item_count"] == 3
    assert manifest["papers"]["p1.json"]["markers"] == 2
    assert len(manifest["papers"]["p1.json"]["sha256"]) == 64


def test_the_manifest_round_trips_and_detects_no_change(tmp_path: Path) -> None:
    root = _dataset(tmp_path)
    manifest_path = tmp_path / "dataset_manifest.json"

    assert validator.main(
        ["--references", str(root), "--write-manifest", str(manifest_path)]
    ) == 0
    assert manifest_path.is_file()

    assert validator.validate_dataset(root, manifest_path)["paper_count"] == 2


def test_a_modified_reference_is_rejected_by_the_manifest(tmp_path: Path) -> None:
    root = _dataset(tmp_path)
    manifest_path = tmp_path / "dataset_manifest.json"
    validator.main(["--references", str(root), "--write-manifest", str(manifest_path)])
    payload = json.loads((root / "p1.json").read_text(encoding="utf-8"))
    payload["items"][1]["awarded"] = 1
    payload["items"][1]["marker_marks"] = {"m1": 1, "m2": 1}
    _write(root / "p1.json", payload)

    with pytest.raises(validator.DatasetInvalid, match="sha256"):
        validator.validate_dataset(root, manifest_path)


def test_an_extra_reference_not_in_the_manifest_is_rejected(tmp_path: Path) -> None:
    root = _dataset(tmp_path)
    manifest_path = tmp_path / "dataset_manifest.json"
    validator.main(["--references", str(root), "--write-manifest", str(manifest_path)])
    _write(
        root / "p3.json",
        json.loads((root / "p2.json").read_text(encoding="utf-8")) | {"paper_id": "p3"},
    )

    with pytest.raises(validator.DatasetInvalid, match="not in the manifest"):
        validator.validate_dataset(root, manifest_path)


def test_a_missing_reference_is_rejected_by_the_manifest(tmp_path: Path) -> None:
    root = _dataset(tmp_path)
    manifest_path = tmp_path / "dataset_manifest.json"
    validator.main(["--references", str(root), "--write-manifest", str(manifest_path)])
    (root / "p2.json").unlink()

    with pytest.raises(validator.DatasetInvalid, match="missing from the directory"):
        validator.validate_dataset(root, manifest_path)


def test_an_empty_dataset_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "reference"
    root.mkdir()

    with pytest.raises(validator.DatasetInvalid, match="no reference files"):
        validator.build_manifest(root)


def test_a_file_whose_paper_id_does_not_match_its_name_is_rejected(tmp_path: Path) -> None:
    root = _dataset(tmp_path)
    payload = json.loads((root / "p1.json").read_text(encoding="utf-8"))
    _write(root / "p1-copy.json", payload)

    with pytest.raises(validator.DatasetInvalid, match="paper_id"):
        validator.build_manifest(root)


def test_unadjudicated_disagreement_fails_the_dataset(tmp_path: Path) -> None:
    root = _dataset(
        tmp_path,
        papers={
            "p1": [
                _item("1a", max_marks=2, awarded=2, first=1, second=2),
            ]
        },
    )

    with pytest.raises(validator.DatasetInvalid, match="adjudication"):
        validator.build_manifest(root)


def test_the_command_exits_two_and_writes_nothing_when_invalid(
    tmp_path: Path, capsys
) -> None:
    root = _dataset(
        tmp_path,
        papers={"p1": [_item("1a", max_marks=2, awarded=2, first=1, second=2)]},
    )
    manifest_path = tmp_path / "dataset_manifest.json"

    code = validator.main(
        ["--references", str(root), "--write-manifest", str(manifest_path)]
    )

    assert code == 2
    assert "invalid" in capsys.readouterr().err
    assert not manifest_path.exists()


def test_a_missing_manifest_is_an_error(tmp_path: Path) -> None:
    root = _dataset(tmp_path)

    with pytest.raises(validator.DatasetInvalid, match="not readable"):
        validator.validate_dataset(root, tmp_path / "absent.json")
