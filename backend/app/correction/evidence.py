"""Keeping the evidence a mark was made from.

A normalised mark is a decision; the model's own words are the evidence for it.
Both are stored.  When the engine changes what the model said (an award above
the maximum, an unusable response), the original value and the reason for the
change survive in ``raw_awarded_marks`` / ``normalisation_detail`` rather than
being overwritten by the corrected one.

The raw response is capped so one verbose model reply cannot bloat the row; the
cap is recorded explicitly, because a silently truncated response would look
complete when it is not.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

#: 32 KiB per question is far above a real marking response and small enough
#: that a whole paper stays a reasonable row size.
RAW_RESPONSE_LIMIT = 32_768

#: Why a stored mark differs from what the model returned.
OVER_MAX_AWARD = "OVER_MAX_AWARD"
MODEL_RESPONSE_INVALID = "MODEL_RESPONSE_INVALID"
LEGACY_BACKFILL = "LEGACY_BACKFILL"


@dataclass(frozen=True, slots=True)
class CapturedResponse:
    #: JSON-able value for the ``raw_response`` column.  Never None when the
    #: model returned anything at all.
    value: Any
    truncated: bool


def capture_raw_response(text: str | None) -> CapturedResponse:
    """Store the model's reply as faithfully as JSON allows.

    A reply that parses is stored as the parsed document.  A reply that does not
    is stored as text under a stated format, so an unusable response is still
    inspectable instead of being reduced to an error string.
    """

    raw = text or ""
    if not raw.strip():
        return CapturedResponse(value=None, truncated=False)
    truncated = len(raw) > RAW_RESPONSE_LIMIT
    clipped = raw[:RAW_RESPONSE_LIMIT]
    if truncated:
        return CapturedResponse(
            value={"format": "TEXT_TRUNCATED", "text": clipped}, truncated=True
        )
    try:
        return CapturedResponse(value=json.loads(clipped), truncated=False)
    except ValueError:
        return CapturedResponse(
            value={"format": "UNPARSEABLE_TEXT", "text": clipped}, truncated=False
        )


@dataclass(frozen=True, slots=True)
class NormalisedAward:
    raw: int
    normalised: int
    anomaly: str | None
    detail: dict[str, Any] | None


def normalise_award(raw: int, *, max_marks: int) -> NormalisedAward:
    """Apply the one normalisation the engine performs, and say so.

    An award above the maximum is not clamped into a plausible number: the
    stored mark becomes 0 and the row is sent to review, while the model's
    claimed value is preserved.  Clamping would quietly invent a mark the model
    never justified.
    """

    if raw < 0:
        return NormalisedAward(
            raw=raw,
            normalised=0,
            anomaly=OVER_MAX_AWARD,
            detail={"reason": "negative award", "raw_awarded_marks": raw},
        )
    if raw > max_marks:
        return NormalisedAward(
            raw=raw,
            normalised=0,
            anomaly=OVER_MAX_AWARD,
            detail={
                "reason": "award exceeded the question maximum and was not applied",
                "raw_awarded_marks": raw,
                "max_marks": max_marks,
            },
        )
    return NormalisedAward(raw=raw, normalised=raw, anomaly=None, detail=None)
