"""The status contract must not let one subsystem's health imply another's."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.schemas.status import ComponentHealthRead, SystemStatusRead
from app.services.status import (
    FEATURES,
    WORKER_GRACE_MULTIPLIER,
    WORKER_MIN_GRACE_SECONDS,
    read_system_status,
)
from sqlalchemy.exc import ProgrammingError


class FakeHeartbeat:
    def __init__(self, last_seen_at: datetime) -> None:
        self.last_seen_at = last_seen_at


class FakeSession:
    """A session stand-in: no database, no SQL, only the two calls the probe makes."""

    def __init__(
        self,
        *,
        heartbeat: FakeHeartbeat | None = None,
        database_down: bool = False,
        table_missing: bool = False,
    ) -> None:
        self.heartbeat = heartbeat
        self.database_down = database_down
        self.table_missing = table_missing
        self.rolled_back = 0

    def execute(self, _statement: object) -> None:
        if self.database_down:
            raise RuntimeError("connection refused")

    def get(self, _model: object, _key: str) -> FakeHeartbeat | None:
        if self.table_missing:
            raise ProgrammingError("SELECT 1", {}, Exception("relation does not exist"))
        return self.heartbeat

    def rollback(self) -> None:
        self.rolled_back += 1


def _settings(heartbeat_seconds: int = 20, live_provider: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        worker=SimpleNamespace(heartbeat_seconds=heartbeat_seconds),
        features=SimpleNamespace(live_provider=live_provider),
        env=SimpleNamespace(value="development"),
    )


def _age_seconds() -> int:
    return max(WORKER_MIN_GRACE_SECONDS, 20 * WORKER_GRACE_MULTIPLIER)


def test_a_reachable_api_reports_the_database_and_worker_separately() -> None:
    session = FakeSession(heartbeat=FakeHeartbeat(datetime.now(UTC)))
    status = read_system_status(session, _settings())

    assert status.api.state == "ok"
    assert status.engine.state == "ok"
    assert status.database.state == "ok"
    assert status.readiness.state == "ok"
    assert status.worker.state == "ok"


def test_a_stale_heartbeat_is_reported_as_stopped_not_online() -> None:
    stale = datetime.now(UTC) - timedelta(seconds=_age_seconds() + 30)
    status = read_system_status(FakeSession(heartbeat=FakeHeartbeat(stale)), _settings())

    assert status.worker.state == "unavailable"
    assert status.database.state == "ok"


def test_a_missing_heartbeat_is_unknown_rather_than_online() -> None:
    status = read_system_status(FakeSession(heartbeat=None), _settings())

    assert status.worker.state == "unknown"
    assert "no worker" in status.worker.summary.lower()


def test_a_missing_heartbeat_table_degrades_to_unknown() -> None:
    session = FakeSession(table_missing=True)
    status = read_system_status(session, _settings())

    assert status.worker.state == "unknown"
    assert "migration" in (status.worker.detail or "").lower()
    assert session.rolled_back >= 1


def test_a_database_failure_does_not_claim_readiness() -> None:
    session = FakeSession(database_down=True)
    status = read_system_status(session, _settings())

    assert status.database.state == "unavailable"
    assert status.readiness.state == "unavailable"
    # The API answered this request, so the process itself is not degraded.
    assert status.api.state == "ok"
    assert session.rolled_back >= 1


def test_a_naive_heartbeat_timestamp_is_treated_as_utc() -> None:
    naive = datetime.now(UTC).replace(tzinfo=None)
    status = read_system_status(FakeSession(heartbeat=FakeHeartbeat(naive)), _settings())

    assert status.worker.state == "ok"


def test_provider_availability_is_never_claimed() -> None:
    for live_provider in (False, True):
        status = read_system_status(
            FakeSession(heartbeat=FakeHeartbeat(datetime.now(UTC))),
            _settings(live_provider=live_provider),
        )
        assert status.provider.state == "unknown"


def test_the_engine_names_each_feature_and_its_state() -> None:
    features = {feature.name: feature for feature in FEATURES}

    assert {"Marking", "SymPy verification", "Cohort intelligence"} <= set(features)
    # The worker runs a real marking pipeline and verifies every award, so neither
    # may be reported as absent. Accuracy is a separate claim and stays unverified.
    assert features["Marking"].state == "available"
    assert features["SymPy verification"].state == "available"
    assert "UNVERIFIED" in features["Marking"].reason
    # The capabilities this build genuinely lacks stay named rather than hidden.
    assert features["Cohort intelligence"].state == "not_implemented"
    assert all(feature.reason.strip() for feature in FEATURES)


def test_readiness_describes_the_pipeline_this_build_runs() -> None:
    status = read_system_status(
        EvidenceSession(heartbeat=FakeHeartbeat(datetime.now(UTC))), _settings()
    )

    detail = status.readiness.detail or ""
    assert "not implemented" not in detail.lower()
    assert "UNVERIFIED" in detail


def test_the_response_serialises_every_subsystem() -> None:
    session = FakeSession(heartbeat=FakeHeartbeat(datetime.now(UTC)))
    status = read_system_status(session, _settings())
    payload = status.model_dump(mode="json")

    assert set(payload) >= {
        "checked_at",
        "api",
        "engine",
        "readiness",
        "database",
        "worker",
        "provider",
        "components",
        "features",
    }
    assert payload["api"]["state"] == "ok"


class FakeScalars:
    def __init__(self, row: object | None) -> None:
        self._row = row

    def first(self) -> object | None:
        return self._row


class FakeUsage:
    """A recorded provider call, as the usage ledger stores it."""

    def __init__(
        self,
        *,
        created_at: datetime,
        model: str = "gemini-3.6-flash",
        http_status: int | None = 200,
        latency_ms: int | None = 1298,
        error_class: str | None = None,
    ) -> None:
        self.created_at = created_at
        self.model = model
        self.http_status = http_status
        self.latency_ms = latency_ms
        self.error_class = error_class


class EvidenceSession(FakeSession):
    """A session stand-in that also answers the evidence reads.

    The queues mirror the order ``read_system_status`` reads them: scalar counts
    are credential total, healthy credentials, runnable jobs; row reads are the
    last successful validation, the last failed validation, the last job and the
    last failed job.
    """

    def __init__(
        self,
        *,
        heartbeat: FakeHeartbeat | None = None,
        database_down: bool = False,
        table_missing: bool = False,
        credentials: int = 0,
        healthy: int = 0,
        runnable: int = 0,
        success: FakeUsage | None = None,
        failure: FakeUsage | None = None,
        last_job: object | None = None,
        last_failed: object | None = None,
    ) -> None:
        super().__init__(
            heartbeat=heartbeat, database_down=database_down, table_missing=table_missing
        )
        self._counts = [credentials, healthy, runnable]
        self._rows = [success, failure, last_job, last_failed]

    def scalars(self, _statement: object) -> FakeScalars:
        return FakeScalars(self._rows.pop(0))

    def scalar(self, _statement: object) -> int:
        return self._counts.pop(0)


def _component(status: SystemStatusRead, name: str) -> ComponentHealthRead:
    return next(component for component in status.components if component.name == name)


def test_a_recorded_live_call_verifies_reachability_not_correctness() -> None:
    session = EvidenceSession(
        heartbeat=FakeHeartbeat(datetime.now(UTC)),
        credentials=4,
        healthy=4,
        success=FakeUsage(created_at=datetime.now(UTC)),
    )
    status = read_system_status(session, _settings(live_provider=True))

    assert status.provider.state == "ok"
    provider = _component(status, "AI provider")
    assert provider.deployment == "deployed"
    assert provider.operational == "available"
    # A successful call never makes the provider ready to mark.
    assert provider.readiness == "not_ready"
    assert provider.last_success_at is not None
    assert "UNVERIFIED" in provider.diagnostic


def test_a_newer_failure_degrades_the_provider_even_after_a_success() -> None:
    session = EvidenceSession(
        heartbeat=FakeHeartbeat(datetime.now(UTC)),
        credentials=4,
        healthy=4,
        success=FakeUsage(created_at=datetime.now(UTC) - timedelta(minutes=10)),
        failure=FakeUsage(
            created_at=datetime.now(UTC),
            http_status=503,
            error_class="ProviderTransientError",
        ),
    )
    status = read_system_status(session, _settings(live_provider=True))

    assert status.provider.state == "degraded"
    provider = _component(status, "AI provider")
    assert provider.operational == "degraded"
    assert provider.last_failure is not None and "503" in provider.last_failure


def test_credentials_without_a_recorded_call_are_unverified() -> None:
    session = EvidenceSession(
        heartbeat=FakeHeartbeat(datetime.now(UTC)), credentials=2, healthy=2
    )
    status = read_system_status(session, _settings(live_provider=True))

    provider = _component(status, "AI provider")
    assert provider.deployment == "deployed"
    assert provider.operational == "unverified"
    assert provider.last_success_at is None


def test_no_credentials_is_not_configured_rather_than_unavailable() -> None:
    session = EvidenceSession(heartbeat=FakeHeartbeat(datetime.now(UTC)), credentials=0)
    status = read_system_status(session, _settings(live_provider=True))

    provider = _component(status, "AI provider")
    assert provider.deployment == "not_configured"
    assert provider.operational == "unverified"


def test_worker_deployment_is_reported_separately_from_operation() -> None:
    running = read_system_status(
        EvidenceSession(heartbeat=FakeHeartbeat(datetime.now(UTC))), _settings()
    )
    worker = _component(running, "Background worker")
    assert worker.deployment == "deployed"
    assert worker.operational == "available"
    assert worker.readiness == "not_ready"
    assert worker.last_success_at is not None
    # No job has been processed in this fake, so readiness to mark is unproven.
    assert "unproven" in worker.diagnostic

    stopped = read_system_status(EvidenceSession(heartbeat=None), _settings())
    worker = _component(stopped, "Background worker")
    assert worker.deployment == "not_deployed"
    assert worker.operational == "unavailable"


def test_an_unobservable_worker_is_unknown_not_stopped() -> None:
    status = read_system_status(EvidenceSession(table_missing=True), _settings())
    worker = _component(status, "Background worker")
    assert worker.deployment == "unknown"
    assert worker.operational == "unknown"
    assert "migration" in worker.diagnostic.lower()


def test_the_api_and_database_components_are_reported_separately() -> None:
    healthy = read_system_status(
        EvidenceSession(heartbeat=FakeHeartbeat(datetime.now(UTC))), _settings()
    )
    api = _component(healthy, "HTTP API")
    database = _component(healthy, "PostgreSQL")
    assert (api.deployment, api.operational, api.readiness) == (
        "deployed",
        "available",
        "ready",
    )
    assert (database.deployment, database.operational, database.readiness) == (
        "deployed",
        "available",
        "ready",
    )

    down = read_system_status(EvidenceSession(database_down=True), _settings())
    database = _component(down, "PostgreSQL")
    assert database.operational == "unavailable"
    assert database.readiness == "unavailable"
    assert database.last_failure is not None


def test_every_component_carries_a_diagnostic() -> None:
    status = read_system_status(
        EvidenceSession(heartbeat=FakeHeartbeat(datetime.now(UTC))), _settings()
    )

    assert {component.name for component in status.components} == {
        "HTTP API",
        "PostgreSQL",
        "Background worker",
        "AI provider",
    }
    assert all(component.diagnostic.strip() for component in status.components)
