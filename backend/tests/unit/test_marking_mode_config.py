"""Selecting the marking mode is configuration, and it fails closed.

Whole-paper marking is the product and therefore the default: one request for
the complete paper, with the per-question engine as the fallback for leaves that
reply did not decide.  An impossible output budget or page cap is refused at
boot rather than discovered mid-paper.
"""

from __future__ import annotations

import pytest
from app.core.config import MarkingSettings
from pydantic import ValidationError


def test_the_default_mode_is_the_whole_paper_engine() -> None:
    """The default must be the product, not the fallback.

    Per-question marking is what answers the leaves a paper reply missed; making
    it the default would mean no deployment ever sends the paper as a whole, and
    a green per-question run would be mistaken for proof that whole-paper marking
    works.
    """

    assert MarkingSettings().marking_mode == "WHOLE_PAPER"


def test_the_whole_paper_mode_is_selectable() -> None:
    settings = MarkingSettings(marking_mode="WHOLE_PAPER")

    assert settings.marking_mode == "WHOLE_PAPER"
    assert settings.whole_paper_max_output_tokens == 32768
    assert settings.whole_paper_max_pages == 12


def test_an_unknown_marking_mode_is_refused() -> None:
    with pytest.raises(ValidationError):
        MarkingSettings(marking_mode="WHOLE_SCRIPT")


def test_the_paper_output_budget_cannot_exceed_the_model_ceiling() -> None:
    settings = MarkingSettings(whole_paper_max_output_tokens=65536)

    assert settings.whole_paper_max_output_tokens == 65536

    with pytest.raises(ValidationError):
        MarkingSettings(whole_paper_max_output_tokens=65_537)
    with pytest.raises(ValidationError):
        MarkingSettings(whole_paper_max_output_tokens=1024)


def test_the_paper_page_cap_is_bounded() -> None:
    with pytest.raises(ValidationError):
        MarkingSettings(whole_paper_max_pages=0)
    with pytest.raises(ValidationError):
        MarkingSettings(whole_paper_max_pages=41)


def test_coverage_judges_pages_against_the_limit_the_mode_carries() -> None:
    """A 7-page script is not truncated by a paper request that carries 12.

    Coverage used to compare every script against the per-question cap, so a
    whole-paper run reported a truncation that never happened and flagged every
    question for review.  The limit reported must be the one the award was read
    under.
    """

    from types import SimpleNamespace

    from app.correction.aetrix.pipeline import (
        MAX_PAGES_PER_QUESTION,
        _coverage_page_cap,
    )

    per_question = SimpleNamespace(marking=MarkingSettings(marking_mode="PER_QUESTION"))
    paper = SimpleNamespace(
        marking=MarkingSettings(marking_mode="WHOLE_PAPER", whole_paper_max_pages=12)
    )

    assert _coverage_page_cap("PER_QUESTION", per_question) == MAX_PAGES_PER_QUESTION
    assert _coverage_page_cap("WHOLE_PAPER", paper) == 12
