"""One page limit, from configuration to the request that is sent.

Mission 6.1 reproduced a configuration that allowed twelve pages while the
request builder kept six.  Eight supplied pages produced six images, no error
and no finding: a silently thinned script, which is exactly what the page budget
exists to prevent.

These tests pin one explicit limit.  The configuration cannot accept a value
above the builder's ceiling, a page set over the limit is refused before a
request is built, and an accepted request carries every page it lists.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from app.core.config import MarkingSettings
from app.core.errors import AppError
from app.correction.aetrix.pipeline import MAX_PAGES_PER_QUESTION, _MarkingRun
from app.correction.transcription import (
    PAGE_SOURCE_MAPPING,
    TRANSCRIPTION_REQUEST_MAX_PAGES,
    resolve_transcription_pages,
)
from app.providers.gemini import GeminiProvider
from pydantic import ValidationError


def _pages(count: int) -> list[SimpleNamespace]:
    return [
        SimpleNamespace(
            id=f"p{index}", page_index=index, storage_key=f"pages/{index}.png"
        )
        for index in range(1, count + 1)
    ]


class _Storage:
    def read(self, key: str) -> bytes:
        return b"\x89PNG\r\n\x1a\n" + key.encode("ascii")


def _run() -> _MarkingRun:
    settings = SimpleNamespace(
        marking=MarkingSettings(marking_mode="PER_QUESTION", transcription_enabled=True)
    )
    return _MarkingRun(
        session=None,  # type: ignore[arg-type]
        job=SimpleNamespace(),  # type: ignore[arg-type]
        settings=settings,  # type: ignore[arg-type]
        structure=None,  # type: ignore[arg-type]
        criteria_by_question={},
        readable=[],
        calls=None,  # type: ignore[arg-type]
        storage=_Storage(),  # type: ignore[arg-type]
        quality=[],
        engine_version="test",
        policy=None,  # type: ignore[arg-type]
    )


def _request_parts(pages: list[SimpleNamespace]) -> list[dict]:
    inputs = _run()._transcription_inputs(("2", 5, "working", "2"), pages=pages)
    payload = {
        "contents": [
            {"role": "user", "parts": [GeminiProvider._part(item) for item in inputs]}
        ]
    }
    return payload["contents"][0]["parts"]


def test_the_marking_cap_is_the_transcription_request_ceiling() -> None:
    """One limit, not two constants that happen to agree."""

    assert MAX_PAGES_PER_QUESTION == TRANSCRIPTION_REQUEST_MAX_PAGES


def test_the_configuration_rejects_a_limit_the_builder_cannot_carry() -> None:
    with pytest.raises(ValidationError):
        MarkingSettings(transcription_max_pages=TRANSCRIPTION_REQUEST_MAX_PAGES + 1)

    # The largest honest value is still accepted, and the default is unchanged.
    assert (
        MarkingSettings(transcription_max_pages=TRANSCRIPTION_REQUEST_MAX_PAGES)
        .transcription_max_pages
        == TRANSCRIPTION_REQUEST_MAX_PAGES
    )
    assert MarkingSettings().transcription_max_pages == 3


def test_six_pages_within_a_six_page_limit_are_accepted() -> None:
    selection = resolve_transcription_pages(
        "2",
        pages=_pages(6),
        mapped={"2": [f"p{index}" for index in range(1, 7)]},
        citations={},
        owners={f"p{index}": {"2"} for index in range(1, 7)},
        max_pages=TRANSCRIPTION_REQUEST_MAX_PAGES,
    )

    assert selection.available
    assert selection.source == PAGE_SOURCE_MAPPING
    assert selection.page_indices == (1, 2, 3, 4, 5, 6)


def test_seven_pages_are_refused_rather_than_thinned() -> None:
    selection = resolve_transcription_pages(
        "2",
        pages=_pages(8),
        mapped={"2": [f"p{index}" for index in range(1, 8)]},
        citations={},
        owners={f"p{index}": {"2"} for index in range(1, 8)},
        max_pages=TRANSCRIPTION_REQUEST_MAX_PAGES,
    )

    assert not selection.available
    assert selection.page_ids == ()
    assert selection.reason.startswith("PAGE_BUDGET_EXCEEDED:")
    assert selection.confidence == "NONE"


def test_a_request_over_the_ceiling_cannot_be_built() -> None:
    """The backstop: the builder refuses instead of dropping a page."""

    with pytest.raises(AppError):
        _run()._transcription_inputs(("2", 5, "working", "2"), pages=_pages(7))


def test_an_accepted_request_lists_every_page_it_carries() -> None:
    parts = _request_parts(_pages(6))

    labels = [part["text"] for part in parts if "text" in part and part["text"].startswith("Page ")]
    images = [part for part in parts if "inlineData" in part]

    assert len(labels) == 6
    assert len(images) == 6
    assert all(
        label.startswith(f"Page {index} of 6 supplied")
        for index, label in enumerate(labels, start=1)
    )
    # Every page in the request is listed exactly once: nothing was thinned.
    assert json.dumps(parts).count("Page ") == 6
