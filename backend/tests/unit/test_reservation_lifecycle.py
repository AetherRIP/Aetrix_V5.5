"""Reservation lifecycle, unconfirmed accounting and revision consistency.

`provider_quota_reservations` is the ledger the quota gate reads, so a status
that is written but never counted — or counted twice — is a correctness bug, not
a display bug.  These tests drive the real `ProviderCallService.call` and the
real `QuotaEstimator` with scripted providers and fake repositories, and they
read the migration file itself to catch the two defects a rehearsal found: a
constraint name that does not exist and a revision id longer than the column
Alembic stores it in.
"""

from __future__ import annotations

import ast
import pathlib

import pytest
from app.core.config import ModelChainEntry, get_settings
from app.core.errors import AppError
from app.providers.errors import (
    ProviderAuthenticationError,
    ProviderNetworkError,
    ProviderQuotaError,
    ProviderResponseError,
    ProviderServerError,
    ProviderTruncatedResponse,
)
from app.providers.routing import classify_failure
from app.schemas.provider_admin import QuotaEstimateRead
from app.services import quota as quota_module
from app.services.provider_calls import reservation_status_for
from test_model_fallback import (
    MODEL_A,
    FakePool,
    FakeUsage,
    ScriptedProvider,
    _call,
    _service,
    _settings,
)

BACKEND = pathlib.Path(__file__).resolve().parents[2]
VERSIONS = BACKEND / "migrations" / "versions"
RESERVATION_REVISION = VERSIONS / "0038_reservation_unconfirmed.py"

#: The exact body the ORM declares, which the revision must reproduce.
STATUS_BODY = "status IN ('RESERVED','CONSUMED','RELEASED','UNCONFIRMED')"


# -- one status per failure ---------------------------------------------------


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        # The request was rejected before inference: nothing was metered.
        (ProviderAuthenticationError("401", status_code=401), "RELEASED"),
        # A refused connection is proof the request never left the process.
        (ProviderNetworkError("refused", reached_provider=False), "RELEASED"),
        # A 5xx: Google may or may not have counted it.
        (ProviderServerError("503", status_code=503, reached_provider=True), "UNCONFIRMED"),
        # A timeout: the request was sent and the answer never arrived.
        (ProviderNetworkError("timed out", reached_provider=None), "UNCONFIRMED"),
        # A 429 is a confirmed provider answer; it closes the daily gate.
        (ProviderQuotaError("429", status_code=429, reached_provider=True), "CONSUMED"),
        # A truncated 2xx was generated and billed before it was cut.
        (ProviderTruncatedResponse("cut", reached_provider=True), "CONSUMED"),
        # An unparseable 2xx was generated and billed too.
        (ProviderResponseError("bad json", reached_provider=True), "CONSUMED"),
    ],
)
def test_reservation_status_matches_what_the_failure_proves(error, expected) -> None:
    kind = classify_failure(error)
    assert reservation_status_for(kind, error) == expected


def test_a_timeout_is_not_reported_as_free() -> None:
    """The canonical ambiguity: sent, unanswered, possibly metered."""

    error = ProviderNetworkError("timed out", reached_provider=None)
    assert reservation_status_for(classify_failure(error), error) != "RELEASED"


def test_the_adapter_separates_a_connect_failure_from_a_read_timeout() -> None:
    """One is proof the request never left; the other is not, and the ledger
    must not treat them the same."""

    import httpx
    from test_validation import KEY, _provider, _request

    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    def no_answer(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("read timed out", request=request)

    with pytest.raises(ProviderNetworkError) as refused_error:
        _provider(refused).generate(_request(), KEY)
    assert refused_error.value.reached_provider is False
    assert (
        reservation_status_for(
            classify_failure(refused_error.value), refused_error.value
        )
        == "RELEASED"
    )

    with pytest.raises(ProviderNetworkError) as unanswered:
        _provider(no_answer).generate(_request(), KEY)
    assert unanswered.value.reached_provider is None
    assert (
        reservation_status_for(classify_failure(unanswered.value), unanswered.value)
        == "UNCONFIRMED"
    )


# -- the estimator's windows --------------------------------------------------


class _CountingReservations:
    """CONSUMED+RESERVED = 2; with UNCONFIRMED = 3.  One unconfirmed row."""

    def __init__(self, _session: object) -> None:
        pass

    def count_since_project(
        self, project_id, since, now, *, model=None, include_unconfirmed=False
    ) -> int:
        return 3 if include_unconfirmed else 2

    def unconfirmed_count_project(self, project_id, since, *, model=None) -> int:
        return 1

    def active_cooldowns_for(self, project_ids, now):
        # No project is cooling down in this fixture; the estimator reads the
        # whole set at once so one missing method fails every estimate.
        return {}

    def project_window_counts(
        self, project_ids, *, minute_since, day_since, now, model=None
    ) -> dict[str, dict[str, int]]:
        return {
            project_id: {"minute": 2, "day": 2, "unconfirmed": 1}
            for project_id in project_ids
        }

    def project_cooldown(self, project_id):
        return None


class _CountingUsage:
    def __init__(self, _session: object) -> None:
        pass

    def validation_count(self, project_id, model, since) -> int:
        return 0

    def window_stats(self, since, *, project_id, model) -> dict:
        return {"input_tokens": 0, "output_tokens": 0, "failures": 0}

    def project_pool_usage(
        self, project_ids, *, model, minute_since, day_since
    ) -> dict[str, dict[str, int]]:
        return {
            project_id: {
                "validations_minute": 0,
                "validations_day": 0,
                "tokens_minute": 0,
            }
            for project_id in project_ids
        }


@pytest.fixture()
def counting_estimator(monkeypatch):
    monkeypatch.setattr(
        quota_module, "QuotaReservationRepository", _CountingReservations
    )
    monkeypatch.setattr(quota_module, "UsageRepository", _CountingUsage)
    return quota_module.QuotaEstimator(None, get_settings())


def test_the_minute_window_counts_each_reservation_once(counting_estimator) -> None:
    estimate = counting_estimator.estimate(project_id="project-one", model=MODEL_A)
    # 2 counted + 1 unconfirmed.  Counting the confirmed total and then adding an
    # inclusive total would report 5.
    assert estimate.requests_per_minute.used == 3


def test_the_daily_window_excludes_unconfirmed_but_reports_it(
    counting_estimator,
) -> None:
    estimate = counting_estimator.estimate(project_id="project-one", model=MODEL_A)
    assert estimate.requests_per_day.used == 2
    assert estimate.unconfirmed_requests == 1
    assert any("not against the daily allowance" in note for note in estimate.notes)


def test_the_api_contract_keeps_the_unconfirmed_count(counting_estimator) -> None:
    """``QuotaEstimateRead`` is a typed model: a field it does not declare is
    silently dropped from the response instead of reaching the screen."""

    estimate = counting_estimator.estimate(project_id="project-one", model=MODEL_A)
    payload = QuotaEstimateRead(**estimate.as_dict())
    assert payload.unconfirmed_requests == 1
    assert payload.requests_per_day.used == 2


# -- retry after an unconfirmed attempt ---------------------------------------


class _RecordingPool(FakePool):
    """FakePool that keeps the lease, so reservation identity is checkable."""

    def __init__(self, projects):
        super().__init__(projects)
        self.leases: list[object] = []

    def acquire(self, **kwargs):
        lease = super().acquire(**kwargs)
        self.leases.append(lease)
        return lease


def test_a_503_is_unconfirmed_and_the_retry_takes_a_new_reservation() -> None:
    provider = ScriptedProvider(
        {MODEL_A: [ProviderServerError("503", status_code=503), "{}"]}
    )
    pool = _RecordingPool(["project-one"])
    usage = FakeUsage()
    service = _service(
        provider,
        chain=[ModelChainEntry(model=MODEL_A)],
        pool=pool,
        usage=usage,
        settings=_settings(chain=[ModelChainEntry(model=MODEL_A)], max_attempts=2),
    )

    result = _call(service)

    assert result.response.model == MODEL_A
    # The failed attempt is recorded as ambiguous, never as free.
    assert [failure["reservation_status"] for failure in pool.failures] == [
        "UNCONFIRMED"
    ]
    # One attempt, one reservation: two attempts, two distinct reservations.
    assert len(provider.calls) == 2
    assert len(pool.leases) == 2
    reservations = {lease.reservation_id for lease in pool.leases}
    assert len(reservations) == 2
    # The ledger holds both attempts, in order, and no third row.
    assert [row["success"] for row in usage.rows] == [False, True]


def test_the_operation_budget_bounds_reservations_as_well_as_requests() -> None:
    provider = ScriptedProvider(
        {
            MODEL_A: [
                ProviderServerError("503", status_code=503),
                ProviderServerError("503", status_code=503),
                ProviderServerError("503", status_code=503),
            ]
        }
    )
    base = _settings(chain=[ModelChainEntry(model=MODEL_A)], max_attempts=8)
    provider_settings = base.provider.model_copy(
        update={"max_requests_per_operation": 2}
    )
    settings = base.model_copy(update={"provider": provider_settings})
    pool = _RecordingPool(["project-one"])
    service = _service(
        provider,
        chain=[ModelChainEntry(model=MODEL_A)],
        pool=pool,
        usage=FakeUsage(),
        settings=settings,
    )

    with pytest.raises(AppError):
        _call(service)

    # A model-attempt budget of eight cannot buy more than the operation allows.
    assert len(provider.calls) == 2
    assert len(pool.leases) == 2
    assert all(
        failure["reservation_status"] == "UNCONFIRMED" for failure in pool.failures
    )


def test_a_429_closes_the_day_instead_of_being_treated_as_unconfirmed() -> None:
    provider = ScriptedProvider(
        {MODEL_A: [ProviderQuotaError("429", status_code=429, retry_after_seconds=1)]}
    )
    pool = _RecordingPool(["project-one"])
    service = _service(
        provider,
        chain=[ModelChainEntry(model=MODEL_A)],
        pool=pool,
        usage=FakeUsage(),
    )

    with pytest.raises(AppError):
        _call(service)

    assert [failure["reservation_status"] for failure in pool.failures] == ["CONSUMED"]
    # One project-wide pause, not a reserve-and-retry storm.
    assert len(provider.calls) == 1
    assert len(pool.leases) == 1


# -- the revision itself ------------------------------------------------------

_COUNTED_STATUSES = ("RESERVED", "CONSUMED", "RELEASED", "UNCONFIRMED")


def _revision_ids() -> list[tuple[pathlib.Path, str, str | list[str] | None]]:
    revisions: list[tuple[pathlib.Path, str, str | list[str] | None]] = []
    for path in sorted(VERSIONS.glob("*.py")):
        revision = ""
        down: str | list[str] | None = None
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            name = getattr(targets[0], "id", None)
            value = node.value
            if name == "revision" and isinstance(value, ast.Constant):
                revision = str(value.value)
            elif name == "down_revision":
                if isinstance(value, ast.Tuple):
                    down = [str(item.value) for item in value.elts]
                elif isinstance(value, ast.Constant):
                    down = None if value.value is None else str(value.value)
        revisions.append((path, revision, down))
    return revisions


def test_the_reservation_revision_widens_exactly_the_orm_constraint() -> None:
    source = RESERVATION_REVISION.read_text(encoding="utf-8")
    models = (BACKEND / "app" / "db" / "models.py").read_text(encoding="utf-8")

    # The ORM and the revision must agree character for character.
    assert STATUS_BODY in models
    assert STATUS_BODY in source
    for status in _COUNTED_STATUSES:
        assert status in source

    # The name is the deployed one: models.py declares name="status" under
    # ck_%(table_name)s_%(constraint_name)s, and the live table already carries
    # that plain name.
    assert '"ck_provider_quota_reservations_status"' in source


def test_the_revision_does_not_let_the_naming_convention_rewrite_the_name() -> None:
    """``op.drop_constraint(name, ...)`` renders the name through the convention
    and asks PostgreSQL to drop a doubled, truncated identifier that does not
    exist.  The rehearsal failed on exactly that; raw DDL keeps the name."""

    source = RESERVATION_REVISION.read_text(encoding="utf-8")
    assert "op.drop_constraint(" not in source
    assert "op.create_check_constraint(" not in source
    assert 'ALTER TABLE {_TABLE} ADD CONSTRAINT "{_CONSTRAINT}"' in source
    assert '_TABLE = "provider_quota_reservations"' in source


def test_every_revision_id_fits_the_alembic_version_column() -> None:
    """``alembic_version.version_num`` is varchar(32).  A longer id applies every
    DDL change and then fails to stamp, rolling the whole chain back."""

    too_long = [
        (path.name, revision)
        for path, revision, _ in _revision_ids()
        if len(revision) > 32
    ]
    assert too_long == []


def test_the_revision_chain_has_exactly_one_head() -> None:
    revisions = _revision_ids()
    known = {revision for _, revision, _ in revisions}
    parents = {
        parent
        for _, _, down in revisions
        for parent in (down if isinstance(down, list) else [down])
        if parent
    }
    assert known - parents == {"0046_platform_settings"}
    assert parents <= known, "a down_revision names a revision that does not exist"
