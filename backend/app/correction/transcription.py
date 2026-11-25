"""Blind transcription: a second reading of the script that cannot agree by habit.

The marking model is asked for a mark, a scheme comparison and a quoted answer in
one breath.  A transcription pass asks a different question with none of that
context — only the pages and the question — and its answer is compared with the
answer the first pass reported.  Two readers who saw the same script should read
the same characters; when they do not, the award rests on unproven extraction and
a person decides.

Nothing here rewrites evidence.  The first pass's `student_answer` stays exactly
as it was recorded; the transcription is stored beside it, with the comparison,
and only a difference raises a concern.

Three decisions live here, and each is a pure function so it can be tested
without a provider, a database or a page image:

* **what the blind reader is told** — an allowlist of question id and answer
  type, never marks, scheme, criteria, expected answers or any earlier reading;
* **which questions are worth a second reading** — a deterministic risk policy
  (below) that orders the queue by what a misread would cost, not by question id;
* **which pages carry the answer** — the mapped pages, else the pages this run's
  own quotations cite, else a single page between mapped neighbours; when none of
  those is available the question is reported as unavailable instead of being
  sent the whole script.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from . import transcription_compare

STATUS_AGREES = "AGREES"
STATUS_DIFFERS = "DIFFERS"
STATUS_ABSENT = "ABSENT"
STATUS_UNVERIFIABLE = "UNVERIFIABLE"

#: The concerns one finished reading raises.  They are the whole contract between
#: the comparison and the result guard: a concern puts the question in front of a
#: person, and no concern leaves the award exactly as it was recorded.
CONCERN_DIFFERS = "TRANSCRIPTION_DIFFERS"
CONCERN_UNVERIFIED = "TRANSCRIPTION_UNVERIFIED"
CONCERN_NO_READING = "TRANSCRIPTION_NO_READING"
CONCERN_PAGE_UNVERIFIED = "TRANSCRIPTION_PAGE_UNVERIFIED"
CONCERN_NOT_INDEPENDENT = "TRANSCRIPTION_NOT_INDEPENDENT"
CONCERN_INDEPENDENCE_UNKNOWN = "TRANSCRIPTION_INDEPENDENCE_UNKNOWN"
CONCERN_UNAVAILABLE = "TRANSCRIPTION_UNAVAILABLE"

#: How a second reading was classified.  ``MODEL`` is the only value that is an
#: independent reading of the page; the other two say what the check actually
#: was, because a check that cannot be independent must not be reported as one.
INDEPENDENCE_MODEL = "MODEL"
INDEPENDENCE_PROMPT = "PROMPT"
INDEPENDENCE_UNKNOWN = "UNKNOWN"

#: Confidence below which a second reading is worth its request even when the
#: first reading produced text.
LOW_CONFIDENCE = 0.85

#: Confidence at or above which a zero is "confident".  It is recorded as a risk
#: signal, never as evidence that the reading is correct.
CONFIDENT = 0.85

#: How many pages one transcription request may carry, and how large those pages
#: may be.  Both are ceilings, not targets: a question that needs more is
#: reported as unavailable rather than sent a silently thinned script.
TRANSCRIPTION_MAX_PAGES = 3
TRANSCRIPTION_MAX_IMAGE_BYTES = 8 * 1024 * 1024

#: The most page images the request builder can put in one request.  This is the
#: single ceiling the configuration is validated against and the builder refuses
#: to exceed: a configured limit above it would be a promise the transport cannot
#: keep, and honouring it by silently dropping pages is the defect this constant
#: exists to make impossible.
TRANSCRIPTION_REQUEST_MAX_PAGES = 6

_WHITESPACE = re.compile(r"\s+")
#: LaTeX delimiters a reader may or may not copy.
_LATEX_WRAPPERS = re.compile(r"^\$+|\$+$|^\\\(|\\\)$|^\\\[|\\\]$")
_ZERO_STATES = frozenset({"MARKED", "CONFIRMED_ZERO"})

#: What a blind reader may be told.  This is the whole contract: `_question_context`
#: is the *marking* header and carries maximum marks, special instructions and
#: scheme references, none of which a second reader of the page may see.
BLIND_CONTEXT_FIELDS = ("question_id", "answer_type")
_BLIND_HEADER_PREFIXES = ("Question: ", "Answer type: ")

#: Page provenance, so a reviewer can see how the image set was chosen.
PAGE_SOURCE_MAPPING = "MAPPING"
PAGE_SOURCE_EVIDENCE = "EVIDENCE"
PAGE_SOURCE_INTERPOLATED = "INTERPOLATED"
PAGE_SOURCE_SINGLE_PAGE = "SINGLE_PAGE"
PAGE_SOURCE_UNAVAILABLE = "UNAVAILABLE"

#: How far the *page selection* can be trusted, kept separate from whether the
#: two readings agree.  ``INDEPENDENT`` means the page was established without
#: consulting the marking pass; ``CIRCULAR`` means it was taken from that pass's
#: own attribution, so agreement can only show two readers looked at the same
#: page — not that the page was the right one.
PAGE_CONFIDENCE_INDEPENDENT = "INDEPENDENT"
PAGE_CONFIDENCE_CIRCULAR = "CIRCULAR"
PAGE_CONFIDENCE_NONE = "NONE"

_INDEPENDENT_PAGE_SOURCES = frozenset({PAGE_SOURCE_MAPPING, PAGE_SOURCE_SINGLE_PAGE})
_CIRCULAR_PAGE_SOURCES = frozenset({PAGE_SOURCE_EVIDENCE, PAGE_SOURCE_INTERPOLATED})

#: Risk weights.  They order the queue; they are not probabilities.  A signal is
#: only ever added when it is true of the stored row, so a ranking can be
#: explained by reading the reasons attached to it.
_WEIGHT_BLANK_ZERO = 5.0
_WEIGHT_CONFIDENT_ZERO = 4.0
_WEIGHT_BARE_NUMERIC_FINAL = 4.0
_WEIGHT_SIGN_DISTRIBUTION = 3.0
_WEIGHT_WRITTEN_FORM = 2.0
_WEIGHT_EVIDENCE_DISAGREEMENT = 3.0
_WEIGHT_PAGE_RISK = 3.0
_WEIGHT_LOW_CONFIDENCE = 3.0
_WEIGHT_UNCERTAIN_READING = 3.0
_WEIGHT_SCHEME_DOUBT = 2.0
_WEIGHT_MARKS_AT_STAKE = 0.5
_MARKS_AT_STAKE_CAP = 3.0

#: A separate final answer line: a bare number, optionally with a leading ``=``.
_BARE_NUMBER = re.compile(r"^=?\s*-?\d+(?:\.\d+)?$")
#: Signs that a flattened bracket could have absorbed: two or more top-level
#: subtractions in one expression, with or without an exponent.
_SIGN_OPERATORS = re.compile(r"[+\-]")
_WRITTEN_FORM = re.compile(r"\d\s*/\s*\d|\^\s*-|\d\.\d")


@dataclass(frozen=True, slots=True)
class TranscriptionTarget:
    question_id: str
    score: float
    reasons: tuple[str, ...]
    signals: tuple[str, ...] = ()
    max_marks: int = 0
    rank: int = 0


@dataclass(frozen=True, slots=True)
class PageSelection:
    """The pages one transcription request may carry, and why."""

    page_ids: tuple[str, ...]
    page_indices: tuple[int, ...]
    source: str
    reason: str | None = None

    @property
    def available(self) -> bool:
        return bool(self.page_ids) and self.reason is None

    @property
    def confidence(self) -> str:
        """How far the choice of page is independent of the marking pass."""

        return page_confidence(self.source)

    def as_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "confidence": self.confidence,
            "page_ids": list(self.page_ids),
            "page_indices": list(self.page_indices),
            "available": self.available,
            "reason": self.reason,
        }


def page_confidence(source: str | None) -> str:
    """Whether the page set was chosen independently of the first reading.

    A mapping was approved before this run and a one-page script leaves nothing
    to choose, so both are independent of the marking pass.  A page derived from
    this run's own quotations, or interpolated from pages attributed by this
    run, is the marking pass's own attribution: a second reading of it confirms
    the page, not that the page is the right one.  An unavailable selection has
    no confidence at all.
    """

    value = str(source or "").strip()
    if value in _INDEPENDENT_PAGE_SOURCES:
        return PAGE_CONFIDENCE_INDEPENDENT
    if value in _CIRCULAR_PAGE_SOURCES:
        return PAGE_CONFIDENCE_CIRCULAR
    return PAGE_CONFIDENCE_NONE


def normalise_text(text: str | None) -> str:
    """A comparison form: no wrappers, no repeated whitespace, no trailing stop."""

    value = (text or "").strip()
    if not value:
        return ""
    value = _LATEX_WRAPPERS.sub("", value).strip()
    value = _WHITESPACE.sub(" ", value)
    return value.rstrip(".").strip()


def compare_transcripts(original: str | None, transcript: str | None) -> str:
    """``AGREES`` / ``DIFFERS`` / ``ABSENT`` / ``UNVERIFIABLE``.

    Two readers must see the same signs.  The comparison is material, not
    algebraic: whitespace, wrappers and terminal punctuation are normalised
    away, and every other difference — a sign, an exponent, a bracket, a
    numerator, a decimal point, a relation — is reported.  Mathematical
    equivalence is deliberately **not** used: ``3/4`` and ``0.75`` are the same
    number and different working, and a marking decision can rest on exactly
    that difference.

    A difference in either direction is a difference: a reader that finds writing
    where the first pass saw a blank is as informative as the reverse.
    """

    return transcription_compare.compare_readings([original], transcript).status


def recorded_readings(answer: str | None, quotes: Iterable[str | None]) -> list[str]:
    """Everything the marking pass claims to have read for one question.

    The final answer alone is not the marking transcription: for Q6 the marking
    pass recorded no answer and put its reading in the quotation it awarded
    against, so a comparison that ignored quotations would have nothing to check.
    """

    readings = [text for text in [answer, *quotes] if (text or "").strip()]
    return list(dict.fromkeys(readings))


# -- what the blind reader may be told -------------------------------------


def blind_question_context(question_id: str, answer_type: str | None) -> str:
    """The whole header a blind reader receives: the question and its kind.

    This is an allowlist, not the marking header with fields removed.  Maximum
    marks, special instructions, scheme references, criteria, expected answers
    and every earlier reading are absent by construction: no code path here can
    read a field that is not named in ``BLIND_CONTEXT_FIELDS``.
    """

    return "\n".join(
        (
            f"Question: {question_id}",
            f"Answer type: {answer_type or 'not specified'}",
        )
    )


def header_is_blind(text: str) -> bool:
    """Whether a text part carries only the allowlisted header lines."""

    lines = [line for line in (text or "").splitlines() if line.strip()]
    return bool(lines) and all(
        line.startswith(_BLIND_HEADER_PREFIXES) for line in lines
    )


# -- which pages carry the answer ------------------------------------------


def _ordered(page_ids: Iterable[str], position: Mapping[str, int]) -> list[str]:
    unique = {str(page_id) for page_id in page_ids if page_id}
    return sorted(unique, key=lambda page_id: position.get(page_id, -1))


def _natural_key(question_id: str) -> tuple[object, ...]:
    """A stable, human ordering: ``2`` before ``10``, ``16`` before ``16b``."""

    parts = re.split(r"(\d+)", str(question_id))
    return tuple(int(part) if part.isdigit() else part for part in parts)


def resolve_transcription_pages(
    question_id: str,
    *,
    pages: Sequence[Any],
    mapped: Mapping[str, Sequence[str]],
    citations: Mapping[str, Sequence[str]],
    owners: Mapping[str, Iterable[str]],
    max_pages: int = TRANSCRIPTION_MAX_PAGES,
) -> PageSelection:
    """The pages this question's blind reading should carry.

    Four sources, in decreasing order of confidence:

    1. an explicit page→question mapping (``MAPPING`` — independent);
    2. the pages this run's own quotations cite (``EVIDENCE`` — the marking pass
       named the page it read, which is *its own* attribution: a second reading
       of that page confirms the page, not that the page is the right one);
    3. one page between the pages of the preceding and following attributed
       questions (``INTERPOLATED`` — inferred from pages this run attributed);
    4. a one-page script (``SINGLE_PAGE`` — nothing to choose, independent);
    5. nothing (``UNAVAILABLE``), never the whole script.

    The source is returned with the pages so the caller can persist how far the
    *location* of the reading is independent of the reading under test.

    The page after the last selected page is added only when no other question
    claims it, which is how a continuation is carried without sending a page that
    belongs to another question.  Original document page numbers are preserved and
    never renumbered.
    """

    ordered = list(pages)
    position = {str(page.id): index for index, page in enumerate(ordered)}
    by_id = {str(page.id): page for page in ordered}

    def known_pages(page_ids: Iterable[str]) -> list[str]:
        # A mapping can name a page that is not part of this submission's
        # readable pages; it is dropped rather than trusted.
        return [page_id for page_id in _ordered(page_ids, position) if page_id in position]

    own = known_pages(mapped.get(question_id) or ())
    source = PAGE_SOURCE_MAPPING
    if not own:
        own = known_pages(citations.get(question_id) or ())
        source = PAGE_SOURCE_EVIDENCE
    if not own and len(ordered) == 1:
        # A one-page script leaves no page to choose: the question is on it.
        own = [str(ordered[0].id)]
        source = PAGE_SOURCE_SINGLE_PAGE
    if not own:
        # Neighbours are *questions*, not pages: an unmapped question between
        # two attributed ones is the one case a gap can be narrowed to a page.
        known_questions = sorted(
            {
                str(item)
                for item in set(mapped) | set(citations)
                if str(item) != str(question_id)
            },
            key=_natural_key,
        )
        key = _natural_key(question_id)
        previous = [item for item in known_questions if _natural_key(item) < key]
        following = [item for item in known_questions if _natural_key(item) > key]
        if previous and following:
            before = known_pages(
                mapped.get(previous[-1]) or citations.get(previous[-1]) or ()
            )
            after = known_pages(
                mapped.get(following[0]) or citations.get(following[0]) or ()
            )
            if before and after:
                start = position[before[-1]]
                end = position[after[0]]
                between = ordered[start + 1 : end] if end > start else []
                if len(between) == 1:
                    own = [str(between[0].id)]
                    source = PAGE_SOURCE_INTERPOLATED
        if not own:
            return PageSelection(
                page_ids=(),
                page_indices=(),
                source=PAGE_SOURCE_UNAVAILABLE,
                reason="NO_PAGE_MAPPING",
            )

    selected = list(own)
    last = position[selected[-1]]
    if last + 1 < len(ordered):
        candidate = str(ordered[last + 1].id)
        claimed_elsewhere = {
            str(owner) for owner in owners.get(candidate, ()) if str(owner) != question_id
        }
        if not claimed_elsewhere:
            selected.append(candidate)

    if len(selected) > max_pages:
        return PageSelection(
            page_ids=(),
            page_indices=(),
            source=PAGE_SOURCE_UNAVAILABLE,
            reason=f"PAGE_BUDGET_EXCEEDED:{len(selected)}>{max_pages}",
        )
    selected = _ordered(selected, position)
    return PageSelection(
        page_ids=tuple(selected),
        page_indices=tuple(int(by_id[page_id].page_index) for page_id in selected),
        source=source,
    )


# -- independence ----------------------------------------------------------


def outcome_concerns(
    status: str, *, awarded: int, page_confidence: str
) -> tuple[str, ...]:
    """Which concerns one finished reading raises, for any award and any page.

    The policy, in one place, so it can be read and tested without a provider:

    * ``DIFFERS`` — always a definite concern.  Two readers saw different signs;
      nothing about the award decides whether that matters.
    * ``UNVERIFIABLE`` — always a concern.  An unusable reading verifies nothing,
      and a positive award it did not check is as unverified as a zero.
    * ``ABSENT`` — a concern only when marks were awarded.  Two blank readings of
      a zero agree; marks resting on a reading that does not exist do not.
    * ``AGREES`` — no concern about the reading itself, but an agreement on a page
      the marking pass chose only confirms what is on *that* page.

    Nothing here changes an award: the caller raises concerns and leaves the mark,
    the student answer and the evidence exactly as recorded.
    """

    concerns: list[str] = []
    if status == STATUS_DIFFERS:
        concerns.append(CONCERN_DIFFERS)
    elif status == STATUS_UNVERIFIABLE:
        concerns.append(CONCERN_UNVERIFIED)
    elif status == STATUS_ABSENT and int(awarded or 0) != 0:
        # Any non-zero award — including an impossible negative one — is not the
        # "both saw nothing" case; a concern is the safe direction.
        concerns.append(CONCERN_NO_READING)
    if (
        status in {STATUS_AGREES, STATUS_ABSENT}
        and page_confidence == PAGE_CONFIDENCE_CIRCULAR
    ):
        concerns.append(CONCERN_PAGE_UNVERIFIED)
    return tuple(concerns)


def marking_model_set(*sources: Iterable[str | None]) -> tuple[str, ...]:
    """Every distinct model identity that produced a marking, across sources.

    A resumed job's earlier marking, a provider fallback and a double check all
    leave their model in different places; independence is only honest when all
    of them are considered.  Blank identities are dropped rather than counted:
    an unrecorded model cannot make another model independent.
    """

    models = {
        str(model).strip()
        for source in sources
        for model in (source or ())
        if str(model or "").strip()
    }
    return tuple(sorted(models))


def classify_independence(
    answering_model: str | None, marking_models: Iterable[str | None]
) -> str:
    """Whether a second reading is a different model's reading.

    ``MODEL`` requires both identities: a different answering model than every
    model that marked this run.  An unknown answering model, or a run whose
    marking model was never recorded, cannot establish independence and is
    ``UNKNOWN`` — never ``MODEL`` by default.  The same answering model is
    ``PROMPT``: two calls to one model verify the prompt, not the reading.
    """

    answering = (answering_model or "").strip()
    known = {str(model).strip() for model in marking_models if str(model or "").strip()}
    if not answering or not known:
        return INDEPENDENCE_UNKNOWN
    if answering in known:
        return INDEPENDENCE_PROMPT
    return INDEPENDENCE_MODEL


# -- risk-based selection --------------------------------------------------


def _signals_for(
    row: Any, readings: Sequence[str]
) -> tuple[float, list[str], list[str]]:
    """Score one stored result and name every signal that produced the score.

    The signals are facts about the stored row and the text the marking pass
    wrote.  Confidence is only ever a *risk* signal: a confident zero is the
    shape of the Q6 defect, not evidence that its reading is right.
    """

    score = 0.0
    reasons: list[str] = []
    signals: list[str] = []

    def add(weight: float, signal: str, reason: str) -> None:
        nonlocal score
        score += weight
        signals.append(signal)
        reasons.append(f"{signal}: {reason}")

    awarded = int(getattr(row, "awarded_marks", 0) or 0)
    max_marks = int(getattr(row, "max_marks", 0) or 0)
    confidence = getattr(row, "confidence", None)
    answer = (getattr(row, "student_answer", None) or "").strip()
    text = " ".join(item for item in readings if (item or "").strip())

    if awarded == 0 and not answer:
        add(
            _WEIGHT_BLANK_ZERO,
            "BLANK_ZERO",
            "a zero was taken beside a blank answer, which is also the shape of "
            "an answer that was present but unread.",
        )
    if awarded == 0 and confidence is not None and float(confidence) >= CONFIDENT:
        add(
            _WEIGHT_CONFIDENT_ZERO,
            "CONFIDENT_ZERO",
            f"the zero was recorded at {float(confidence):.2f} confidence, which "
            "says how sure the marking pass was, not that it read the page.",
        )
    if awarded == 0 and any(_BARE_NUMBER.match(item.strip()) for item in readings):
        add(
            _WEIGHT_BARE_NUMERIC_FINAL,
            "BARE_NUMERIC_FINAL",
            "the marking pass quoted a separate bare number as the final answer "
            "and still awarded zero, so its own reading contradicts its award.",
        )
    signs = [match.group(0) for match in _SIGN_OPERATORS.finditer(text)]
    if (
        awarded == 0
        and signs.count("-") >= 2
        and len(transcription_compare.tokens(text)) >= 6
        and "(" not in text
    ):
        add(
            _WEIGHT_SIGN_DISTRIBUTION,
            "SIGN_DISTRIBUTION",
            "the reading is a long sum with two or more subtractions and no "
            "bracket, which is what a subtracted bracket looks like after its "
            "sign is lost.",
        )
    if awarded == 0 and _WRITTEN_FORM.search(text.replace(" ", "")):
        add(
            _WEIGHT_WRITTEN_FORM,
            "WRITTEN_FORM",
            "the reading contains a fraction, a negative exponent or a decimal, "
            "where one character changes the value.",
        )
    if answer and readings:
        target = normalise_text(answer)
        if target and not any(
            target in normalise_text(item) for item in readings if item
        ):
            add(
                _WEIGHT_EVIDENCE_DISAGREEMENT,
                "EVIDENCE_DISAGREEMENT",
                "the stored answer does not appear in the quotations this run "
                "awarded against, so its own evidence contradicts it.",
            )
    concerns = getattr(row, "scheme_concerns", None) or []
    codes = " ".join(
        str(concern.get("code") or "") + " " + str(concern.get("message") or "")
        for concern in concerns
    )
    if "PAGE_" in codes:
        add(
            _WEIGHT_PAGE_RISK,
            "PAGE_RISK",
            "the pages this question was marked from are incomplete or partially "
            "mapped.",
        )
    if confidence is None or float(confidence) < LOW_CONFIDENCE:
        add(
            _WEIGHT_LOW_CONFIDENCE,
            "LOW_CONFIDENCE",
            f"the first reading recorded "
            f"{confidence if confidence is not None else 'no'} confidence.",
        )
    if getattr(row, "normalisation_anomaly", None):
        add(
            _WEIGHT_UNCERTAIN_READING,
            "UNCERTAIN_READING",
            "the reply was changed before storage, so the stored reading is not "
            "exactly what the model returned.",
        )
    if getattr(row, "review_required", False):
        add(
            _WEIGHT_SCHEME_DOUBT,
            "SCHEME_DOUBT",
            "the result already carries a concern.",
        )
    if score > 0 and max_marks > 0:
        score += min(max_marks * _WEIGHT_MARKS_AT_STAKE, _MARKS_AT_STAKE_CAP)
        signals.append("MARKS_AT_STAKE")
        reasons.append(
            f"MARKS_AT_STAKE: {max_marks} mark(s) rest on this reading."
        )
    return score, signals, reasons


def rank_transcription_targets(
    rows: Iterable[Any],
    *,
    readings: Mapping[str, Sequence[str]] | None = None,
    skip: set[str] | None = None,
) -> list[TranscriptionTarget]:
    """Every question worth a second reading, best first, with its rank.

    Selection is deterministic and explainable: a row is scored by the risk
    signals that are true of it, then ordered by score, by how many independent
    signals agree, and by the marks at stake.  Question id is the *last*
    tie-break, in natural order, so it can never decide between two questions
    that differ in risk.
    """

    skip = skip or set()
    readings_by_question = readings or {}
    scored: list[tuple[float, int, int, tuple[object, ...], TranscriptionTarget]] = []
    for row in rows:
        question_id = str(row.question_id)
        if question_id in skip:
            continue
        if str(getattr(row, "processing_state", "") or "") not in _ZERO_STATES:
            continue
        score, signals, reasons = _signals_for(
            row, list(readings_by_question.get(question_id) or ())
        )
        if score <= 0:
            continue
        target = TranscriptionTarget(
            question_id=question_id,
            score=round(score, 2),
            reasons=tuple(reasons),
            signals=tuple(signals),
            max_marks=int(getattr(row, "max_marks", 0) or 0),
        )
        scored.append(
            (
                target.score,
                len(set(target.signals)),
                target.max_marks,
                _natural_key(question_id),
                target,
            )
        )
    scored.sort(key=lambda item: (-item[0], -item[1], -item[2], item[3]))
    return [
        TranscriptionTarget(
            question_id=item[4].question_id,
            score=item[4].score,
            reasons=item[4].reasons,
            signals=item[4].signals,
            max_marks=item[4].max_marks,
            rank=index + 1,
        )
        for index, item in enumerate(scored)
    ]


def transcribe_targets(
    rows: Iterable[Any],
    *,
    budget: int,
    skip: set[str] | None = None,
    seed: str = "",
    readings: Mapping[str, Sequence[str]] | None = None,
) -> list[TranscriptionTarget]:
    """Choose the questions whose extraction is worth a second reading.

    ``seed`` is accepted for callers written against the earlier selection and is
    not used: this policy has no sampling, so the same rows always choose the
    same questions.
    """

    del seed
    if budget <= 0:
        return []
    return rank_transcription_targets(rows, readings=readings, skip=skip)[:budget]


__all__ = [
    "BLIND_CONTEXT_FIELDS",
    "CONCERN_DIFFERS",
    "CONCERN_INDEPENDENCE_UNKNOWN",
    "CONCERN_NOT_INDEPENDENT",
    "CONCERN_NO_READING",
    "CONCERN_PAGE_UNVERIFIED",
    "CONCERN_UNAVAILABLE",
    "CONCERN_UNVERIFIED",
    "INDEPENDENCE_MODEL",
    "INDEPENDENCE_PROMPT",
    "INDEPENDENCE_UNKNOWN",
    "PAGE_CONFIDENCE_CIRCULAR",
    "PAGE_CONFIDENCE_INDEPENDENT",
    "PAGE_CONFIDENCE_NONE",
    "PAGE_SOURCE_EVIDENCE",
    "PAGE_SOURCE_INTERPOLATED",
    "PAGE_SOURCE_MAPPING",
    "PAGE_SOURCE_SINGLE_PAGE",
    "PAGE_SOURCE_UNAVAILABLE",
    "STATUS_ABSENT",
    "STATUS_AGREES",
    "STATUS_DIFFERS",
    "STATUS_UNVERIFIABLE",
    "TRANSCRIPTION_MAX_IMAGE_BYTES",
    "TRANSCRIPTION_MAX_PAGES",
    "TRANSCRIPTION_REQUEST_MAX_PAGES",
    "PageSelection",
    "TranscriptionTarget",
    "blind_question_context",
    "classify_independence",
    "compare_transcripts",
    "header_is_blind",
    "marking_model_set",
    "normalise_text",
    "outcome_concerns",
    "page_confidence",
    "rank_transcription_targets",
    "recorded_readings",
    "resolve_transcription_pages",
    "transcribe_targets",
]
