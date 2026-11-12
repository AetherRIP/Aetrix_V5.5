from __future__ import annotations

from types import SimpleNamespace

import pytest
from app.core.config import (
    DEV_ENCRYPTION_KEY,
    AuthSettings,
    DatabaseSettings,
    EngineSettings,
    SecuritySettings,
    Settings,
    get_settings,
)
from app.core.errors import AppError, ErrorCode
from app.correction.engine import (
    AetrixEngine,
    EngineNotImplemented,
    LegacyEngine,
    MathCheckerEngine,
)
from app.correction.registry import build_engine, engine_names
from app.jobs.pipeline import PipelineOutcome
from app.jobs.states import JobState
from pydantic import SecretStr, ValidationError


def _settings(name: str):
    settings = get_settings()
    engine = EngineSettings.model_construct(correction_engine=name)
    return settings.model_copy(update={"engine": engine})


def test_the_default_engine_is_the_legacy_pipeline() -> None:
    assert EngineSettings().correction_engine == "aetrix_legacy"
    assert get_settings().engine.correction_engine == "aetrix_legacy"
    assert engine_names() == ("aetrix_legacy", "aetrix_v5_5", "mathchecker_v5")
    assert isinstance(build_engine(get_settings()), LegacyEngine)


def test_shipped_defaults_resolve_to_a_runnable_legacy_engine(monkeypatch) -> None:
    """No environment override at all: the shipped default must still be runnable."""

    monkeypatch.delenv("AETRIX_ENGINE__CORRECTION_ENGINE", raising=False)
    settings = Settings(
        database=DatabaseSettings(
            url=SecretStr("postgresql+psycopg://user:pass@127.0.0.1:5432/aetrix")
        ),
        auth=AuthSettings(jwt_secret=SecretStr("shipped-default-test-secret")),
        security=SecuritySettings(encryption_key=SecretStr(DEV_ENCRYPTION_KEY)),
    )

    assert settings.engine.correction_engine == "aetrix_legacy"
    engine = build_engine(settings)
    assert isinstance(engine, LegacyEngine)
    assert engine.name == "aetrix_legacy"


def test_v5_is_selectable_but_refuses_to_mark() -> None:
    engine = build_engine(_settings("mathchecker_v5"))

    assert isinstance(engine, MathCheckerEngine)
    assert engine.name == "mathchecker_v5"
    with pytest.raises(EngineNotImplemented):
        engine.run(SimpleNamespace(id=None), SimpleNamespace(), get_settings())


def test_an_unknown_engine_name_is_refused_not_fallen_back() -> None:
    with pytest.raises(AppError) as error:
        build_engine(_settings("aetrix_v6_0"))

    assert error.value.code is ErrorCode.CONFIGURATION_ERROR
    assert "aetrix_v6_0" in error.value.message
    assert "aetrix_legacy" in error.value.message
    assert "aetrix_v5_5" in error.value.message
    assert "mathchecker_v5" in error.value.message


def test_settings_rejects_any_other_engine_name() -> None:
    for name in ("aetrix_v6_0", "MathChecker", ""):
        with pytest.raises(ValidationError):
            EngineSettings(correction_engine=name)


def test_the_legacy_engine_stamps_provenance_and_delegates_unchanged(monkeypatch) -> None:
    calls: list[tuple] = []
    expected = PipelineOutcome(JobState.REVIEW_REQUIRED, {"reason": "sentinel"})

    class Pipeline:
        def run(self, job, session, settings):
            calls.append((job, session, settings))
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
        is_active=True,
        scalars=lambda *_args, **_kwargs: SimpleNamespace(all=lambda: []),
    )
    settings = get_settings()
    installed: list[tuple] = []
    monkeypatch.setattr(
        "app.correction.engine.legacy.install_processing_state_hook",
        lambda session, *, engine_version: installed.append((session, engine_version)),
    )

    outcome = LegacyEngine(pipeline=Pipeline()).run(job, session, settings)

    assert outcome is expected
    assert calls == [(job, session, settings)]
    assert installed == [(session, "1.0.0")]
    assert job.engine_name == "aetrix_legacy"
    assert job.engine_version == "1.0.0"
    assert job.result_source == "AI_PRIMARY"
    assert job.primary_model == settings.provider.model_primary
    assert LegacyEngine.name == "aetrix_legacy"


def test_aetrix_v5_5_is_registered_and_selected_by_configuration() -> None:
    engine = build_engine(_settings("aetrix_v5_5"))

    assert isinstance(engine, AetrixEngine)
    assert (engine.name, engine.version) == ("aetrix_v5_5", "5.5.0")
    assert AetrixEngine.name in engine_names()


def test_settings_accepts_the_v5_5_engine_name() -> None:
    assert EngineSettings(correction_engine="aetrix_v5_5").correction_engine == "aetrix_v5_5"
