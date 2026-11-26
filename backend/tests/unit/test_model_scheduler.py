"""The primary-model scheduler: which verified model takes a paper.

The decision is deterministic and auditable, and it must never invent capacity.
These tests pin the ordering rules, the refusals, and the fact that the pool of
three models is *across* papers — a paper gets one model, chosen once.
"""

from __future__ import annotations

import pytest
from app.core.config import get_settings
from app.services import model_scheduler


@pytest.fixture()
def settings():
    base = get_settings()
    provider = base.provider.model_copy(
        update={
            "scheduler_enabled": True,
            "model_primary": "gemini-3.6-flash",
            "primary_marking_models": [
                "gemini-4-hydrogen",
                "gemini-3.8-flash",
                "gemini-3.6-flash",
            ],
        }
    )
    return base.model_copy(update={"provider": provider})


def _ledger(monkeypatch, *, healthy, in_flight=None, usage=None, recent=None, budget=None):
    # Unless a test says otherwise, every model has a declared Aetrix budget: the
    # engine refuses to spend against an unknown allowance, so a model with no
    # budget is not eligible and a test about distribution must not trip over it.
    if budget is None:
        budget = {
            "gemini-4-hydrogen": 100,
            "gemini-3.8-flash": 100,
            "gemini-3.6-flash": 100,
        }
    monkeypatch.setattr(model_scheduler, "_healthy_credentials", lambda session: healthy)
    monkeypatch.setattr(
        model_scheduler, "_in_flight", lambda session: in_flight or {}
    )
    monkeypatch.setattr(model_scheduler, "_usage_today", lambda session: usage or {})
    recent_map = recent or {
        "gemini-4-hydrogen": (3, 0),
        "gemini-3.8-flash": (3, 0),
        "gemini-3.6-flash": (3, 0),
    }
    monkeypatch.setattr(
        model_scheduler, "_recent_by_model", lambda session, limit=20: recent_map
    )
    monkeypatch.setattr(
        model_scheduler,
        "_daily_budget",
        lambda settings_, model: (budget or {}).get(model),
    )


def test_a_fresh_pool_uses_the_declared_priority(monkeypatch, settings):
    _ledger(
        monkeypatch,
        healthy={"gemini-4-hydrogen": 5, "gemini-3.8-flash": 5, "gemini-3.6-flash": 5},
    )
    assignment = model_scheduler.choose(None, settings)
    assert assignment.model_id == "gemini-4-hydrogen"
    assert "chosen with 0 paper(s) in flight" in assignment.reason
    assert len(assignment.candidates) == 3


def test_work_spreads_away_from_a_busy_model(monkeypatch, settings):
    _ledger(
        monkeypatch,
        healthy={"gemini-4-hydrogen": 5, "gemini-3.8-flash": 5, "gemini-3.6-flash": 5},
        in_flight={"gemini-4-hydrogen": 4, "gemini-3.8-flash": 1, "gemini-3.6-flash": 2},
    )
    assert model_scheduler.choose(None, settings).model_id == "gemini-3.8-flash"


def test_a_model_with_no_healthy_credential_is_skipped(monkeypatch, settings):
    _ledger(
        monkeypatch,
        healthy={"gemini-4-hydrogen": 0, "gemini-3.8-flash": 0, "gemini-3.6-flash": 2},
    )
    assignment = model_scheduler.choose(None, settings)
    assert assignment.model_id == "gemini-3.6-flash"
    reasons = {candidate.model_id: candidate.reason for candidate in assignment.candidates}
    assert "no healthy credential" in reasons["gemini-4-hydrogen"]


def test_a_spent_daily_budget_skips_the_model(monkeypatch, settings):
    _ledger(
        monkeypatch,
        healthy={"gemini-4-hydrogen": 5, "gemini-3.8-flash": 5, "gemini-3.6-flash": 5},
        usage={"gemini-4-hydrogen": (20, 0, 900.0)},
        budget={"gemini-4-hydrogen": 20, "gemini-3.8-flash": 20},
    )
    assignment = model_scheduler.choose(None, settings)
    assert assignment.model_id == "gemini-3.8-flash"
    reasons = {candidate.model_id: candidate.reason for candidate in assignment.candidates}
    assert "budget is spent" in reasons["gemini-4-hydrogen"]


def test_remaining_budget_breaks_a_tie_before_priority(monkeypatch, settings):
    _ledger(
        monkeypatch,
        healthy={"gemini-4-hydrogen": 5, "gemini-3.8-flash": 5, "gemini-3.6-flash": 5},
        usage={"gemini-4-hydrogen": (9, 0, 900.0), "gemini-3.8-flash": (1, 0, 900.0)},
        budget={"gemini-4-hydrogen": 10, "gemini-3.8-flash": 10},
    )
    assert model_scheduler.choose(None, settings).model_id == "gemini-3.8-flash"


def test_a_model_whose_recent_calls_all_failed_is_skipped(monkeypatch, settings):
    _ledger(
        monkeypatch,
        healthy={"gemini-4-hydrogen": 5, "gemini-3.8-flash": 5, "gemini-3.6-flash": 5},
        recent={"gemini-4-hydrogen": (0, 5)},
    )
    assignment = model_scheduler.choose(None, settings)
    assert assignment.model_id != "gemini-4-hydrogen"
    reasons = {candidate.model_id: candidate.reason for candidate in assignment.candidates}
    assert "all failed" in reasons["gemini-4-hydrogen"]


def test_no_eligible_model_refuses_instead_of_substituting(monkeypatch, settings):
    _ledger(
        monkeypatch,
        healthy={"gemini-4-hydrogen": 0, "gemini-3.8-flash": 0, "gemini-3.6-flash": 0},
    )
    with pytest.raises(model_scheduler.NoEligibleModelError) as error:
        model_scheduler.choose(None, settings)
    assert "No verified primary marking model" in str(error.value)
    assert len(error.value.considered) == 3


def test_the_choice_is_deterministic_for_the_same_ledger(monkeypatch, settings):
    _ledger(
        monkeypatch,
        healthy={"gemini-4-hydrogen": 2, "gemini-3.8-flash": 2, "gemini-3.6-flash": 2},
    )
    results = [model_scheduler.choose(None, settings).model_id for _ in range(5)]
    assert len(set(results)) == 1


def test_disabling_the_scheduler_is_the_rollback_path(monkeypatch, settings):
    provider = settings.provider.model_copy(update={"scheduler_enabled": False})
    disabled = settings.model_copy(update={"provider": provider})
    _ledger(monkeypatch, healthy={"gemini-3.6-flash": 3})
    assignment = model_scheduler.choose(None, disabled)
    assert assignment.model_id == "gemini-3.6-flash"
    assert "scheduler disabled" in assignment.reason


def test_an_unregistered_model_is_never_scheduled(monkeypatch, settings):
    provider = settings.provider.model_copy(
        update={
            "model_primary": "gemini-3.6-flash",
            "primary_marking_models": ["gemini-9-imaginary", "gemini-3.6-flash"],
        }
    )
    narrowed = settings.model_copy(update={"provider": provider})
    _ledger(monkeypatch, healthy={"gemini-3.6-flash": 1, "gemini-9-imaginary": 9})
    assignment = model_scheduler.choose(None, narrowed)
    assert assignment.model_id == "gemini-3.6-flash"
    assert all(
        candidate.model_id != "gemini-9-imaginary" for candidate in assignment.candidates
    )


def test_the_report_never_claims_capacity_from_credential_count(monkeypatch, settings):
    """Many healthy credentials are not many Google quotas."""

    _ledger(
        monkeypatch,
        healthy={"gemini-4-hydrogen": 15, "gemini-3.8-flash": 0, "gemini-3.6-flash": 0},
    )
    report = model_scheduler.scheduler_report(None, settings)
    assert report["would_choose"] == "gemini-4-hydrogen"
    top = {row["model_id"]: row for row in report["candidates"]}["gemini-4-hydrogen"]
    # Fifteen pools are recorded, and the budget is Aetrix's own request budget:
    # it does not grow with the number of credentials, because they may all bill
    # one Google project.
    assert top["healthy_credentials"] == 15
    assert top["daily_budget"] == 100
    assert top["remaining_budget"] == 100
    assert "google" not in str(report).lower()
