"""The Aetrix V5.5 correction engine.

One package, one execution path: ``pipeline`` marks a paper question by
question, ``schema`` is the strict contract its replies must satisfy, and
``verification`` classifies each award without changing it.  The engine adapter
in ``app.correction.engine.aetrix`` is the only caller; nothing else in the
platform imports these modules directly.
"""

from __future__ import annotations

from .pipeline import AetrixPipeline
from .schema import MARKING_RESPONSE_SCHEMA, MarkingResponseInvalid, QuestionMark
from .verification import VerificationOutcome, equivalent, verify_question

__all__ = [
    "MARKING_RESPONSE_SCHEMA",
    "AetrixPipeline",
    "MarkingResponseInvalid",
    "QuestionMark",
    "VerificationOutcome",
    "equivalent",
    "verify_question",
]
