"""One correction engine, no selection, no fallback.

The build contains ``aetrix_v5_5`` and nothing else.  These tests prove that from
three directions: the engine the worker builds, the settings that cannot name
another one, and the obsolete environment variable that now stops startup.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from app.core.config import (
    CORRECTION_ENGINE_NAME,
    CORRECTION_ENGINE_VERSION,
    DEV_ENCRYPTION_KEY,
    AuthSettings,
    DatabaseSettings,
    SecuritySettings,
    Settings,
    get_settings,
)
from app.core.errors import AppError, ErrorCode
from app.correction import engine as engine_package
from app.correction.engine import AetrixEngine
from app.jobs.pipeline import PipelineOutcome, build_pipeline
from app.jobs.states import JobState
from pydantic import SecretStr, ValidationError

OBSOLETE = "AETRIX_ENGINE__CORRECTION_ENGINE"


def _settings() -> Settings:
    """Settings built without reading the developer's ``backend/.env`` values."""

    return Settings(
        database=DatabaseSettings(
            url=SecretStr("postgresql+psycopg://user:pass@127.0.0.1:5432/aetrix")
        ),
        auth=AuthSettings(jwt_secret=SecretStr("single-engine-test-secret")),
        security=SecuritySettings(encryption_key=SecretStr(DEV_ENCRYPTION_KEY)),
    )


def test_the_build_contains_exactly_one_engine() -> None:
    engine = build_pipeline(get_settings())

    assert isinstance(engine, AetrixEngine)
    assert engine.name == CORRECTION_ENGINE_NAME == "aetrix_v5_5"
    assert engine.version == CORRECTION_ENGINE_VERSION == "5.5.0"


def test_every_settings_path_builds_the_same_engine(monkeypatch) -> None:
    monkeypatch.delenv(OBSOLETE, raising=False)

    assert isinstance(build_pipeline(_settings()), AetrixEngine)
    assert isinstance(build_pipeline(get_settings()), AetrixEngine)


def test_settings_carry_no_engine_selection() -> None:
    settings = _settings()

    assert not hasattr(settings, "engine")
    assert "correction_engine" not in settings.model_dump()


def test_no_other_engine_is_importable() -> None:
    for removed in (
        "LegacyEngine",
        "MathCheckerEngine",
        "EngineNotImplemented",
        "CorrectionEngine",
    ):
        assert not hasattr(engine_package, removed), removed


def test_an_obsolete_selection_of_another_engine_stops_startup(monkeypatch) -> None:
    for selected in ("aetrix_legacy", "mathchecker_v5", "aetrix_v6_0"):
        monkeypatch.setenv(OBSOLETE, selected)

        with pytest.raises(ValidationError) as error:
            _settings()

        message = str(error.value)
        assert OBSOLETE in message
        assert selected in message
        assert "aetrix_v5_5" in message
        assert "falls back" in message


def test_the_obsolete_variable_may_name_the_surviving_engine(monkeypatch) -> None:
    monkeypatch.setenv(OBSOLETE, CORRECTION_ENGINE_NAME)

    assert isinstance(build_pipeline(_settings()), AetrixEngine)


def test_an_obsolete_selection_in_an_env_file_stops_startup(monkeypatch, tmp_path) -> None:
    """A value written to ``.env`` is as real as an exported variable."""

    monkeypatch.delenv(OBSOLETE, raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(f"{OBSOLETE}=aetrix_legacy\n", encoding="utf-8")

    with pytest.raises(ValidationError) as error:
        _settings()

    assert "aetrix_legacy" in str(error.value)


def test_a_historical_job_is_refused_rather_than_remarked() -> None:
    """No fallback and no silent re-mark: the recorded engine wins."""

    class Pipeline:
        def run(self, *args, **kwargs):  # pragma: no cover - the refusal comes first
            raise AssertionError("a historical job must not be marked by this engine")

    job = SimpleNamespace(id=None, engine_name="aetrix_legacy", engine_version="1.0.0")
    session = SimpleNamespace(get=lambda *_args, **_kwargs: job)

    with pytest.raises(AppError) as error:
        AetrixEngine(pipeline=Pipeline()).run(job, session, _settings())

    assert error.value.code is ErrorCode.CONFIGURATION_ERROR
    assert "aetrix_legacy" in error.value.message
    assert job.engine_name == "aetrix_legacy"


def test_the_sole_engine_stamps_its_identity_on_a_new_job() -> None:
    expected = PipelineOutcome(JobState.FINALIZING, {"reason": "stub"})

    class Pipeline:
        def run(self, job, session, settings):
            del job, session, settings
            return expected

    job = SimpleNamespace(
        id=None,
        tenant_id=None,
        engine_name=None,
        engine_version=None,
        result_source=None,
        primary_model=None,
        secondary_model=None,
    )
    session = SimpleNamespace(
        get=lambda *_args, **_kwargs: job,
        commit=lambda: None,
    )

    outcome = AetrixEngine(pipeline=Pipeline()).run(job, session, _settings())

    assert outcome is expected
    assert (job.engine_name, job.engine_version) == (
        CORRECTION_ENGINE_NAME,
        CORRECTION_ENGINE_VERSION,
    )
    assert job.result_source == "AI_PRIMARY"
    assert job.primary_model == _settings().provider.model_primary
