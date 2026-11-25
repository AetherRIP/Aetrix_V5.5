"""Does a quoted piece of evidence actually appear in the student's script?

The marking reply awards each component against a quotation.  Until this check
existed, the engine verified that a quotation was *present* and that its page
belonged to the script — never that the script contained the words.  A model
that invented a plausible sentence and named a real page passed every
deterministic check.

The blind transcription is the independent reading of that page that the engine
already buys for risk-selected questions.  Comparing the quotation against it
is a deterministic check on data that was read without the scheme or the award,
so it costs no extra request and cannot be influenced by the marking pass.  It
answers one question only: *is this text in the script?*  Whether the text earns
the criterion is a different question, and this module never answers it.

A quotation that is not found is a contradiction, not a style difference: the
award's stated support is not in the document.  A quotation too short to be
distinctive, or a reading that could not be taken, is ``UNVERIFIABLE`` — never
``PASS``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_UNVERIFIABLE = "UNVERIFIABLE"

QUOTE_SUPPORTED = "SUPPORTED"
QUOTE_NOT_FOUND = "NOT_FOUND"
QUOTE_UNVERIFIABLE = "UNVERIFIABLE"

#: A quotation shorter than this many normalised characters occurs everywhere,
#: so finding it proves nothing about the award.  ``x=4`` is three characters
#: and is the shortest answer worth locating; a bare digit is not.
MIN_DISTINCTIVE_CHARS = 3

_TRANSLATION = str.maketrans(
    {
        "\u00d7": "x",
        "\u00b7": ".",
        "\u00f7": "/",
        "\u2212": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
    }
)


def normalise(text: str | None) -> str:
    """Whitespace-free, case-folded, unicode-normalised text for comparison."""

    return (
        (text or "")
        .translate(_TRANSLATION)
        .casefold()
        .replace(" ", "")
        .replace("\n", "")
        .replace("\r", "")
        .replace("\t", "")
        .strip()
        .rstrip(".")
    )


def _tokens(text: str) -> list[str]:
    cleaned = normalise(text)
    tokens: list[str] = []
    current = ""
    for character in cleaned:
        if character.isalnum() or character in "+-*/=^().,":
            current += character
        elif current:
            tokens.append(current)
            current = ""
    if current:
        tokens.append(current)
    return tokens


def _subsequence(needle: list[str], haystack: list[str]) -> bool:
    """Whether every token appears in ``haystack`` in order (gaps allowed)."""

    position = 0
    for token in haystack:
        if position < len(needle) and token == needle[position]:
            position += 1
    return position == len(needle)


@dataclass(frozen=True, slots=True)
class QuoteCheck:
    quote: str
    status: str
    detail: dict[str, Any]

    def describe(self) -> dict[str, Any]:
        return {"quote": self.quote, "status": self.status, **self.detail}


def check_quote(quote: str, transcript: str | None) -> QuoteCheck:
    """Whether one quotation occurs in the independent reading."""

    normalised_quote = normalise(quote)
    normalised_transcript = normalise(transcript)
    if not normalised_quote:
        return QuoteCheck(quote, QUOTE_UNVERIFIABLE, {"reason": "EMPTY_QUOTE"})
    if not normalised_transcript:
        return QuoteCheck(quote, QUOTE_UNVERIFIABLE, {"reason": "NO_TRANSCRIPT"})
    if len(normalised_quote) < MIN_DISTINCTIVE_CHARS:
        return QuoteCheck(
            quote,
            QUOTE_UNVERIFIABLE,
            {"reason": "QUOTE_TOO_SHORT", "length": len(normalised_quote)},
        )
    if normalised_quote in normalised_transcript:
        return QuoteCheck(quote, QUOTE_SUPPORTED, {"reason": "SUBSTRING"})
    tokens = _tokens(quote)
    # A reading can break a line where the quotation does not; requiring the
    # tokens in order catches that without accepting arbitrary words.
    if len(tokens) >= 2 and _subsequence(tokens, _tokens(transcript or "")):
        return QuoteCheck(quote, QUOTE_SUPPORTED, {"reason": "TOKENS_IN_ORDER"})
    return QuoteCheck(quote, QUOTE_NOT_FOUND, {"reason": "NOT_PRESENT"})


def check_quotes(
    quotes: Iterable[str], transcript: str | None, *, evidence_status: str = "WRITTEN"
) -> list[QuoteCheck]:
    """Check every quotation against one independent reading."""

    usable = str(evidence_status or "").upper() == "WRITTEN" and bool(
        normalise(transcript)
    )
    checks: list[QuoteCheck] = []
    for quote in quotes:
        if not usable:
            checks.append(
                QuoteCheck(
                    quote,
                    QUOTE_UNVERIFIABLE,
                    {"reason": "READING_NOT_USABLE", "evidence_status": evidence_status},
                )
            )
            continue
        checks.append(check_quote(quote, transcript))
    return checks


def verdict(checks: Iterable[QuoteCheck]) -> str:
    """One verdict for the question's evidence.

    A single quotation that the script does not contain is a failure: the award
    cites support that is not there.  Otherwise an unverifiable quotation keeps
    the whole verdict unverifiable, because a pass must be earned by every
    quotation the award rests on.
    """

    statuses = [check.status for check in checks]
    if not statuses:
        return STATUS_UNVERIFIABLE
    if QUOTE_NOT_FOUND in statuses:
        return STATUS_FAIL
    if QUOTE_UNVERIFIABLE in statuses:
        return STATUS_UNVERIFIABLE
    return STATUS_PASS


__all__ = [
    "MIN_DISTINCTIVE_CHARS",
    "QUOTE_NOT_FOUND",
    "QUOTE_SUPPORTED",
    "QUOTE_UNVERIFIABLE",
    "STATUS_FAIL",
    "STATUS_PASS",
    "STATUS_UNVERIFIABLE",
    "QuoteCheck",
    "check_quote",
    "check_quotes",
    "normalise",
    "verdict",
]
