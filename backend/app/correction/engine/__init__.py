"""Registered correction engines.

Three names exist: ``aetrix_legacy``, the shipped default that marks through the
pre-existing per-question pipeline; ``aetrix_v5_5``, the reviewed V5
implementation; and ``mathchecker_v5``, which is selectable but refuses to mark
until its slice lands.
"""

from __future__ import annotations

from .aetrix import AetrixEngine
from .legacy import LegacyEngine
from .mathchecker import EngineNotImplemented, MathCheckerEngine
from .protocol import CorrectionEngine

__all__ = [
    "AetrixEngine",
    "CorrectionEngine",
    "EngineNotImplemented",
    "LegacyEngine",
    "MathCheckerEngine",
]
