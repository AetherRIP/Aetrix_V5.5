"""The Aetrix V5.5 question-level marking pipeline.

One job marks one submission against one approved blueprint.  The pipeline:

1. re-loads the job in its own session and refuses to touch a cancelled one;
2. proves it has renderable pages, an approved blueprint and an approved scheme;
3. marks each *leaf* question (a sub-question where the paper has them, the
   question itself otherwise) through the audited provider-call service, in the
   mode the job recorded: one whole-paper request, one request per question
   sequentially, or the same per-question requests executed concurrently in
   dependency-aware waves;
4. persists a question result, its components and its quoted evidence;
5. verifies each award and records uncertainty;
6. retries a bounded number of *unusable* responses, never re-running a question
   that already has a decision;
7. stops at ``REVIEW_REQUIRED`` when anything is unproven, otherwise
   ``FINALIZING`` so the runner can complete the job.

Nothing here invents a mark.  A malformed model response, a missing page, an
inconsistent award or a failed mathematical check produces a review item, not a
zero.  A provider outage raises ``RetryablePipelineError`` so the runner parks
the job with a truthful reason.

Three safeguards sit on top of the marking itself:

* every question records an explicit ``processing_state`` (marked, confirmed
  zero, unmarked, needs review) beside the status the API already exposes;
* the model's own award and raw reply are retained when normalisation changes
  anything, so the evidence survives the correction;
* before this run's marks could stand as the submission's result, the result
  guard compares them with the stored one and refuses to replace an approved or
  overridden result, or to replace a good total with a suspicious one.
"""

from __future__ import annotations

import threading
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from ...audit.service import AuditService
from ...core.config import CORRECTION_ENGINE_VERSION, Settings
from ...core.errors import AppError, ErrorCode
from ...core.ids import sha256_hex
from ...core.marking_policy import (
    PRIMARY_MARKING_MODELS,
    PRODUCTION_MARKING_MODEL,
    is_primary_marking_model,
)
from ...db.models import (
    Assignment,
    CorrectionJob,
    CriterionResult,
    DocumentPage,
    ExamBlueprintVersion,
    MarkingEvidence,
    MarkSchemeVersion,
    PageQuestionMapping,
    PromptVersion,
    ProviderResponse,
    ProviderUsage,
    QuestionResult,
    VerificationResult,
)
from ...db.repositories import DocumentRepository, MarkSchemeRepository, ResultRepository
from ...jobs.pipeline import CorrectionPipeline, PipelineOutcome, RetryablePipelineError
from ...jobs.states import JobState
from ...prompts.registry import PromptRegistry
from ...providers.base import LLMInput, LLMProvider
from ...providers.factory import build_provider
from ...providers.json import parse_json_text
from ...schemas.blueprint import BlueprintQuestion, BlueprintStructure
from ...services.provider_calls import ProviderCallService
from ...storage import build_storage
from ...storage.base import Storage, StorageError
from .. import (
    criterion_identity,
    evidence,
    evidence_check,
    page_coverage,
    provenance,
    recovery,
    runs,
    sampling,
    scheme_check,
    transcription,
    transcription_compare,
)
from .. import (
    verification_status as verification_completeness,
)
from ..findings import SEVERITY_DEFINITE, SEVERITY_POSSIBLE
from ..guard import (
    RESULT_SOURCE_AI,
    RESULT_SOURCE_REFUSED,
    PriorResult,
    evaluate_overwrite,
)
from ..integrity import check_mark
from ..processing import (
    ProcessingState,
    ensure_consistent,
    is_scoreable,
    state_for_mark,
    status_for,
)
from ..scheme_criteria import criteria_readiness
from . import parallel
from .parallel import MODE_PARALLEL
from .schema import (
    MARKING_RESPONSE_SCHEMA,
    MarkingResponseInvalid,
    QuestionMark,
    parse_question_mark,
)
from .verification import VerificationOutcome, VerificationRecord, verify_question
from .whole_paper import (
    MAX_WHOLE_PAPER_LEAVES,
    MODE_PER_QUESTION,
    MODE_WHOLE_PAPER,
    WHOLE_PAPER_RESPONSE_SCHEMA,
    WholePaperResponseInvalid,
    detect_truncation,
    paper_sha256,
    parse_whole_paper,
)

#: The page cap one question-level request carries.  It is the transcription
#: request ceiling by construction, so a configured page limit can never promise
#: more pages than the request builder will actually send.
MAX_PAGES_PER_QUESTION = transcription.TRANSCRIPTION_REQUEST_MAX_PAGES


def _coverage_page_cap(marking_mode: str, settings: Settings) -> int:
    """The page limit a request in this mode actually carries.

    Coverage reports a question whose answer spans more pages than one request
    holds.  Judging a whole-paper run against the per-question cap would report
    a truncation that never happened: the paper request carries the whole script
    up to its own, larger limit.  Both the finding and the message a person sees
    must name the limit the award was really read under.
    """

    if marking_mode == MODE_WHOLE_PAPER:
        return settings.marking.whole_paper_max_pages
    return MAX_PAGES_PER_QUESTION
#: The verification kinds a marking reply produces.  They are replaced as a set so
#: a retry cannot leave a verdict from a reply that no longer exists.
MARKING_VERIFICATION_KINDS = (
    "INTEGRITY",
    "MATHEMATICAL",
    "SCHEME_MATHEMATICAL",
    # Derived from the blind reading of the same pages, so it is replaced with
    # the marking verdicts when a reply that produced it is replaced.
    "EVIDENCE",
)
#: The prompt assets this engine uses.  The double check is a separate asset with
#: its own model role, so the second opinion is not the same request repeated.
PROMPT_MARKING = "aetrix_v5_5_marking"
#: The whole-paper asset is a separate identity: it asks for every leaf at once
#: and carries the bounded output contract, so it is not the same experiment as
#: the per-question prompt and must not share its provenance.
PROMPT_MARKING_WHOLE_PAPER = "aetrix_v5_5_marking_whole_paper"
PROMPT_DOUBLE_CHECK = "aetrix_v5_5_double_check"
PROMPT_TRANSCRIPTION = "aetrix_v5_5_transcription"

#: The prompt versions whose reply contract asks for the page each quotation is
#: written on.  Requiring a page from a prompt that never offered one would
#: refuse a reply for something the model could not have supplied, so the
#: requirement belongs to the contract the reply was produced under and not to
#: this build.  A prompt version older than these still has its evidence stored
#: unlocated, which is a real gap but not a reply the model got wrong.
PAGE_ATTRIBUTION_PROMPTS = frozenset(
    {f"{PROMPT_MARKING}:v4", f"{PROMPT_MARKING_WHOLE_PAPER}:v2"}
)


def page_attribution_required(prompt_version: str | None) -> bool:
    """Whether the prompt that produced this reply asked for a page."""

    return str(prompt_version or "") in PAGE_ATTRIBUTION_PROMPTS

#: The transcription reply is small and fixed-shape; asking for a marking-sized
#: response would pay for tokens it cannot use.
TRANSCRIPTION_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "question_id": {"type": "STRING"},
        # The reader states whether it found writing, no writing, or writing it
        # cannot read.  An empty reply is then a finding about the page rather
        # than an absence of a finding, and illegible work is never recorded as
        # an empty answer.
        "evidence_status": {
            "type": "STRING",
            "enum": ["WRITTEN", "ABSENT", "ILLEGIBLE"],
        },
        "transcript": {"type": "STRING", "nullable": True},
        "confidence": {"type": "NUMBER"},
        "review_reasons": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["question_id", "transcript", "confidence"],
}
#: What a blind reader may say it found: writing, no writing, or writing it
#: cannot read.  Illegible is not an empty answer.
_EVIDENCE_STATUSES = frozenset({"WRITTEN", "ABSENT", "ILLEGIBLE"})
_RETRYABLE = {
    ErrorCode.PROVIDER_UNAVAILABLE,
    ErrorCode.SERVICE_NOT_READY,
    ErrorCode.CONFIGURATION_ERROR,
}


def _leaf_questions(structure: BlueprintStructure) -> list[tuple[str, int, str | None, str]]:
    """Return (question_id, max_marks, answer_type, parent_id) for scoreable leaves."""

    leaves: list[tuple[str, int, str | None, str]] = []
    for question in structure.questions:
        if question.excluded:
            continue
        if question.subquestions:
            for sub in question.subquestions:
                if sub.excluded:
                    continue
                leaves.append(
                    (sub.question_id, sub.max_marks, sub.answer_type, question.question_id)
                )
            continue
        leaves.append(
            (question.question_id, question.max_marks, question.answer_type, question.question_id)
        )
    return leaves


def _question_context(
    question_id: str,
    max_marks: int,
    answer_type: str | None,
    blueprint_question: BlueprintQuestion | None,
) -> str:
    lines = [
        f"Question: {question_id}",
        f"Maximum marks: {max_marks}",
        f"Answer type: {answer_type or 'not specified'}",
    ]
    if blueprint_question is not None:
        if blueprint_question.special_instructions:
            lines.append("Special instructions:")
            lines.extend(f"- {item}" for item in blueprint_question.special_instructions)
        if blueprint_question.criteria_refs:
            lines.append(f"Scheme references: {', '.join(blueprint_question.criteria_refs)}")
    return "\n".join(lines)


def _criterion_lines(criteria: list[Any]) -> list[str]:
    """Every field of a criterion that decides or scopes a mark.

    A code, a mark count and a description are not the scheme.  The model also
    has to see the answer the scheme prints, the evidence it demands, which mark
    point a dependent mark needs first, the alternative routes with the criteria
    they replace, and the conditions under which a mark is awarded or withheld.
    Sending the description alone invites an award the scheme does not support,
    and the run would still report the whole paper as marked against it.

    Kept deliberately plain text: the request is one text part, the model reads
    it alongside the pages, and no field is dropped to save tokens.
    """

    lines: list[str] = []
    for position, criterion in enumerate(criteria):
        # The stable identity comes first: two mark points can print the same
        # code, and a reply that can only quote the code cannot say which of
        # them it awarded.  ``M1#2`` names one row and nothing else.
        ordinal = getattr(criterion, "ordinal", None)
        reference = criterion_identity.criterion_reference(
            str(criterion.code), position if ordinal is None else int(ordinal)
        )
        lines.append(
            f"- {reference} ({criterion.marks} mark(s)): {criterion.description}"
        )
        answer = getattr(criterion, "expected_answer", None)
        if answer:
            lines.append(f"    scheme answer: {answer}")
        evidence = getattr(criterion, "required_evidence", None)
        if evidence:
            lines.append(f"    must show: {evidence}")
        dependencies = getattr(criterion, "dependencies", None) or []
        if dependencies:
            lines.append(
                "    only after: " + ", ".join(str(item) for item in dependencies)
            )
        for alternative in getattr(criterion, "alternatives", None) or []:
            if not isinstance(alternative, dict):
                continue
            code = alternative.get("code")
            if code:
                replaces = alternative.get("replaces") or []
                scope = (
                    " replaces " + ", ".join(str(item) for item in replaces)
                    if replaces
                    else ""
                )
                marks = alternative.get("marks")
                counted = f" ({marks} mark(s))" if marks is not None else ""
                rule = alternative.get("rule") or alternative.get("description") or ""
                lines.append(f"    alternative {code}{counted}{scope}: {rule}")
            else:
                method = alternative.get("method") or "alternative"
                expression = alternative.get("expression") or ""
                lines.append(f"    alternative method: {method}: {expression}")
            threshold = alternative.get("term_count")
            if isinstance(threshold, dict):
                lines.append(
                    "    term count: "
                    f"{threshold.get('count')} of a maximum of "
                    f"{threshold.get('required')} terms in "
                    f"{threshold.get('expression')}"
                )
        award = getattr(criterion, "award_conditions", None)
        if award:
            lines.append(f"    award when: {award}")
        withhold = getattr(criterion, "withhold_conditions", None)
        if withhold:
            lines.append(f"    withhold when: {withhold}")
    return lines


def _content_hash(value: Any) -> str | None:
    raw = getattr(value, "content_hash", None)
    return str(raw) if raw else None


def _paper_targets(
    leaves: list[tuple[str, int, str | None, str]],
    results: ResultRepository,
    job_id: uuid.UUID,
) -> list[tuple[str, int, str | None, str]]:
    """The leaves a whole-paper request may cover.

    A question this job already decided is never re-sent: the paper request
    answers the open questions, and the fallback loop answers whatever the paper
    could not.  Re-asking a decided question would replace a decision with a
    second opinion nobody requested.
    """

    targets: list[tuple[str, int, str | None, str]] = []
    for leaf in leaves:
        found = results.get_question(job_id, leaf[0])
        if found is None or _retryable(found):
            targets.append(leaf)
    return targets


def _with_concern(
    row: QuestionResult, *, code: str, message: str, severity: str
) -> None:
    """Replace one concern code on a row, leaving every other finding alone."""

    concerns = [
        concern for concern in (row.scheme_concerns or []) if concern.get("code") != code
    ]
    concerns.append({"code": code, "message": message, "severity": severity})
    row.scheme_concerns = concerns


def _transcription_concern(
    code: str,
    *,
    awarded: int,
    kinds: str,
    recorded: list[str],
    transcript: str | None,
    source: str,
) -> tuple[str, str]:
    """The severity and message a reviewer sees for one transcription concern.

    Kept beside the outcome policy so the wording and the decision cannot drift:
    every concern this stage can raise is explained here, and each one says that
    the award was not changed.
    """

    if code == transcription.CONCERN_DIFFERS:
        return (
            SEVERITY_DEFINITE,
            "An independent reading of the script disagrees with this run's "
            f"transcription ({kinds}). This run read {recorded!r} and the "
            f"independent reading is {transcript!r}. The award was not changed; a "
            "person decides which reading the mark rests on.",
        )
    if code == transcription.CONCERN_UNVERIFIED:
        if awarded:
            return (
                SEVERITY_POSSIBLE,
                "The independent transcription for this question could not be used, "
                f"so the {awarded} mark(s) awarded were not verified. The award was "
                "not changed; a person decides.",
            )
        return (
            SEVERITY_POSSIBLE,
            "The independent transcription for this question could not be used, so "
            "the zero it rests on is unverified.",
        )
    if code == transcription.CONCERN_NO_READING:
        return (
            SEVERITY_POSSIBLE,
            "Neither this run's marking pass nor the independent reading recorded "
            f"any answer for a question awarded {awarded} mark(s), so the award has "
            "no transcription behind it. The award was not changed; a person "
            "decides.",
        )
    return (
        SEVERITY_POSSIBLE,
        "The page for this reading was taken from the marking pass's own "
        f"{source.lower()} attribution rather than from an independent mapping, so "
        "agreement confirms what was read on that page, not that the page is the "
        "right one. A person must confirm the page and the reading.",
    )


def sync_coverage_concerns(
    row: QuestionResult,
    coverage_messages: list[str],
    *,
    integrity_passed: bool,
    min_confidence: float,
) -> dict[str, Any]:
    """Reconcile one row's coverage concerns with the current findings.

    Only concerns with the ``PAGE_COVERAGE`` code are added or removed, so a
    transcription or scheme reason is never disturbed.  A flag that existed
    only because of a coverage gap is cleared only when the integrity verdict
    still passes; if anything else flagged the row, the row stays in review.
    """

    current = {f"PAGE_COVERAGE: {message}" for message in coverage_messages}
    concerns = [
        concern for concern in (row.scheme_concerns or []) if isinstance(concern, dict)
    ]
    coverage = [concern for concern in concerns if concern.get("code") == "PAGE_COVERAGE"]
    others = [concern for concern in concerns if concern.get("code") != "PAGE_COVERAGE"]
    kept = [concern for concern in coverage if concern.get("message") in current]
    present = {concern.get("message") for concern in kept}
    added = sorted(current - present)
    removed = [
        concern.get("message") for concern in coverage if concern.get("message") not in current
    ]
    if not added and not removed:
        return {"added": [], "removed": [], "changed": False}

    row.scheme_concerns = others + kept + [
        {"code": "PAGE_COVERAGE", "message": message} for message in added
    ]
    if added:
        row.review_required = True
        row.status = status_for(ProcessingState.NEEDS_REVIEW)
        row.processing_state = ProcessingState.NEEDS_REVIEW.value
    elif not others and not kept and row.review_required and integrity_passed:
        state = state_for_mark(
            awarded=int(row.awarded_marks or 0),
            review_required=False,
            integrity_failed=False,
            confidence=row.confidence,
            min_confidence=min_confidence,
        )
        row.review_required = state is ProcessingState.NEEDS_REVIEW
        row.status = status_for(state)
        row.processing_state = state.value
    return {"added": added, "removed": removed, "changed": True}


def _sync_coverage(
    session: Session,
    job_id: uuid.UUID,
    rows: list[QuestionResult],
    coverage_messages: list[str],
    *,
    min_confidence: float,
) -> list[dict[str, Any]]:
    """Apply the current coverage findings to rows written by an earlier run."""

    if not rows:
        return []
    integrity = {
        str(item.question_id): str(item.status)
        for item in session.scalars(
            select(VerificationResult).where(
                VerificationResult.job_id == job_id,
                VerificationResult.kind == "INTEGRITY",
            )
        )
    }
    changes: list[dict[str, Any]] = []
    for row in rows:
        change = sync_coverage_concerns(
            row,
            coverage_messages,
            integrity_passed=integrity.get(str(row.question_id)) == "PASS",
            min_confidence=min_confidence,
        )
        if change["changed"]:
            changes.append({"question_id": str(row.question_id), **change})
    return changes


def review_reasons_for(rows: list[QuestionResult]) -> list[str]:
    """An actionable reason for every flagged row, even one that lost its text.

    ``review_required`` is the engine's promise that a person must look.  The
    final state is derived from this list, so deriving it only from stored
    concerns would let a flag with no concern be ignored — the failure would be
    silent, which is the one thing a review flag must never be.  A row with no
    reason gets an explicit one instead of disappearing.
    """

    reasons: list[str] = []
    for row in rows:
        if not row.review_required:
            continue
        concerns = [
            concern
            for concern in (row.scheme_concerns or [])
            if isinstance(concern, dict)
        ]
        if not concerns:
            reasons.append(
                f"Question {row.question_id}: flagged for review without a recorded "
                "reason, so a person must decide it."
            )
            continue
        for concern in concerns:
            reasons.append(
                f"Question {row.question_id}: "
                f"{concern.get('message') or concern.get('code') or 'requires review'}"
            )
    return list(dict.fromkeys(reasons))


def validation_failed_for(
    rows: list[QuestionResult], integrity_findings: list[str]
) -> bool:
    """Whether this run's own validation rejected part of its output.

    A reply the pipeline could not parse, or an award that failed an integrity
    check, means the run did not validate.  The guard must see that instead of
    judging the run on aggregate marks alone.
    """

    if integrity_findings:
        return True
    return any(
        row.normalisation_anomaly == evidence.MODEL_RESPONSE_INVALID for row in rows
    )


def omitted_leaves(
    leaves: list[tuple[str, int, str | None, str]], rows: list[QuestionResult]
) -> list[str]:
    """Scoreable leaves this job wrote no row for.

    A missing row is neither a zero nor a review item: it is part of the paper
    that was never decided.  A run must not present marks as a complete paper
    while the leaves it claims to have marked do not all have a row.
    """

    present = {str(row.question_id) for row in rows}
    return sorted(str(leaf[0]) for leaf in leaves if str(leaf[0]) not in present)


def _retryable(row: QuestionResult) -> bool:
    """Whether a stored row is an unusable response worth another attempt.

    Only a row the engine itself recorded as unusable is retried.  A question
    that was marked, or sent to review for a reason about the student's work, is
    never re-run — that would replace a decision with a second opinion the
    teacher did not ask for.
    """

    if is_scoreable(row.processing_state):
        return False
    return row.normalisation_anomaly == evidence.MODEL_RESPONSE_INVALID


@dataclass
class PaperOutcome:
    """What one whole-paper request produced and what it left to the fallback."""

    #: Question id -> the row written for it, in the order the paper listed it.
    rows: dict[str, QuestionResult] = field(default_factory=dict)
    #: What the stage did, recorded with the run so the request is auditable even
    #: when nothing could be stored.
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class _MarkingRun:
    """The state one execution needs, passed explicitly (the pipeline is shared)."""

    session: Session
    #: The claimed job, or a read-only snapshot of it on a parallel worker, where
    #: touching the orchestrating thread's ORM entity would not be safe.
    job: CorrectionJob | SimpleNamespace
    settings: Settings
    structure: BlueprintStructure
    criteria_by_question: dict[str, list[Any]]
    readable: list[DocumentPage]
    calls: ProviderCallService
    storage: Storage
    quality: list[str]
    engine_version: str
    policy: sampling.ReviewPolicy
    #: A pinned marking prompt version for a controlled experiment; ``None`` uses
    #: the newest manifest version.
    marking_prompt_version: int | None = None
    #: How this paper is marked: one request per question or one for the paper.
    marking_mode: str = MODE_PER_QUESTION
    #: The page limit a request in this mode carries, for truncation messages.
    page_cap: int = MAX_PAGES_PER_QUESTION
    #: The identity of the prompt that produced the most recent reply.
    prompt_version: str | None = None
    #: Every prompt identity this execution called, in order.
    prompt_versions: list[str] = field(default_factory=list)
    integrity_findings: list[str] = field(default_factory=list)
    scheme_findings: list[str] = field(default_factory=list)
    coverage_messages: list[str] = field(default_factory=list)
    leaf_by_question: dict[str, tuple[str, int, str | None, str]] = field(default_factory=dict)
    #: Page numbers of the original student documents, for evidence attribution.
    page_index: provenance.PageIndex = field(default_factory=provenance.PageIndex)
    #: The models that answered this run's marking requests.  A transcription
    #: from one of these verifies the prompt, not the reading.
    marking_models: set[str] = field(default_factory=set)

    # -- helpers ---------------------------------------------------------
    def assert_marking_prompt_stable(self, rows: list[QuestionResult]) -> None:
        """Refuse to add marks from a different prompt than the job already used.

        A retry is a continuation, not a new experiment.  If an operator changes
        the prompt pin (or a new version is released) while a job has stored
        marks, resuming would put two prompt versions in one job and make every
        downstream comparison ambiguous.  The job fails closed instead.
        """

        if not rows:
            return
        allowed = self._allowed_marking_prompts()
        recorded = {str(row.prompt_version) for row in rows}
        unexpected = sorted(version for version in recorded if version not in allowed)
        if unexpected:
            raise AppError(
                ErrorCode.CONFIGURATION_ERROR,
                "This job already contains marks from a different marking prompt "
                "version; refusing to mix prompt versions in one job.",
                details={"expected": sorted(allowed), "found": unexpected},
            )

    def assert_marking_mode_stable(self, rows: list[QuestionResult]) -> None:
        """Refuse to continue a paper in a mode its marks were not produced in.

        The mode is fixed on a job's first marking execution.  A deployment that
        changes ``marking_mode`` afterwards applies it to new jobs; a job that
        already carries rows keeps its recorded mode, and a resumed execution
        that disagrees with those rows fails closed rather than mixing request
        shapes in one paper.
        """

        recorded = {row.response_source for row in rows if row.response_source}
        # ``PER_QUESTION`` is the shape of an individual per-question request, not
        # a second job mode: a whole-paper fallback and every in-run recovery use
        # it while the job keeps its selected mode.  Any other recorded source is
        # a real mode mismatch and still fails closed.
        unexpected = recorded - {self.marking_mode, MODE_PER_QUESTION}
        if unexpected:
            raise AppError(
                ErrorCode.CONFIGURATION_ERROR,
                "This job's marks were produced in a different marking mode; "
                "refusing to continue the paper in another one.",
                details={
                    "job_mode": self.marking_mode,
                    "recorded": sorted(recorded),
                },
            )

    def _allowed_marking_prompts(self) -> set[str]:
        """The marking identities a job may legitimately contain.

        Two assets mark a paper: the per-question prompt and the whole-paper
        prompt.  A job that uses both is normal — the second only ever fills in
        questions the first could not answer — so the stability check compares
        against the set rather than a single expected identity.
        """

        allowed: set[str] = set()
        for prompt_id in (PROMPT_MARKING, PROMPT_MARKING_WHOLE_PAPER):
            pinned = self.marking_prompt_version if prompt_id == PROMPT_MARKING else None
            try:
                asset = self.calls.registry.load(prompt_id, pinned)
            except (AppError, ValueError):
                # A deployment whose manifest predates the whole-paper asset may
                # still resume a per-question job; the missing identity simply
                # cannot appear in its rows.
                continue
            allowed.add(f"{prompt_id}:v{asset.version}")
        return allowed

    def assert_prompt_versions_stable(self, rows: list[QuestionResult]) -> None:
        """Refuse to resume a job whose provider calls used other prompt versions.

        The marking rows carry their version, but double-check and transcription
        verdicts do not.  The append-only usage ledger does: every provider call
        names the prompt version it used.  Comparing those versions with the ones
        this execution would load catches a release (or a pin change) between
        attempts, so no job can silently mix prompt generations.
        """

        self.assert_marking_prompt_stable(rows)
        used = self.session.execute(
            select(PromptVersion.prompt_id, PromptVersion.version)
            .join(ProviderUsage, ProviderUsage.prompt_version_id == PromptVersion.id)
            .where(ProviderUsage.job_id == self.job.id)
            .distinct()
        ).all()
        mismatches: dict[str, dict[str, int]] = {}
        for prompt_id, version in used:
            pinned = self.marking_prompt_version if prompt_id == PROMPT_MARKING else None
            expected = self.calls.registry.load(prompt_id, pinned).version
            if int(version) != expected:
                mismatches[prompt_id] = {"expected": expected, "found": int(version)}
        if mismatches:
            raise AppError(
                ErrorCode.CONFIGURATION_ERROR,
                "This job already used a different prompt version; refusing to mix "
                "prompt generations in one job.",
                details={"prompts": mismatches},
            )

    def _mapped_pages(self, question_id: str) -> list[DocumentPage] | None:
        """The pages explicitly mapped to this question, or ``None`` when none are.

        ``None`` is not the same as an empty list: it means the approved mapping
        says nothing about this question, so the request falls back to the whole
        script and may be truncated.  ``withheld_pages`` reports that.
        """

        tenant_id = self.job.tenant_id
        document_ids = {
            document.id
            for document in DocumentRepository(self.session).list_for_submission(
                tenant_id, self.job.submission_id
            )
        }
        if not document_ids:
            return None
        mapped = set(
            self.session.scalars(
                select(PageQuestionMapping.page_id).where(
                    PageQuestionMapping.tenant_id == tenant_id,
                    PageQuestionMapping.document_id.in_(document_ids),
                    PageQuestionMapping.blueprint_version_id == self.job.blueprint_version_id,
                    PageQuestionMapping.question_id == question_id,
                )
            )
        )
        if not mapped:
            return None
        selected = [page for page in self.readable if page.id in mapped]
        return selected or None

    def _question_pages(self, question_id: str) -> list[DocumentPage]:
        mapped = self._mapped_pages(question_id)
        return mapped if mapped is not None else self.readable

    def withheld_pages(self, question_id: str, *, cap: int | None = None) -> int:
        """How many of this question's pages its request cannot carry.

        A request is capped at ``MAX_PAGES_PER_QUESTION``.  When the pages this
        question needs — its mapped pages, or the whole script when the mapping
        says nothing about it — exceed that cap, the model reads a partial script,
        which is exactly how an answer that is present gets recorded as absent.
        The award is kept as evidence, but it is never presented without a person.
        """

        limit = MAX_PAGES_PER_QUESTION if cap is None else cap
        return max(0, len(self._question_pages(question_id)) - limit)

    def _dependency_context(self, leaf: tuple[str, int, str | None, str]) -> str:
        """The stored decisions of the earlier parts of the same question.

        A later sub-question can carry method marks that follow through from an
        earlier part.  Blocking its dispatch until the earlier part is stored
        keeps the order; this block is what makes the order useful.  Only the
        student's own answer and working are quoted beside the award — the
        earlier part's criteria are not, because this question is marked
        against its own.
        """

        question_id, _max_marks, _answer_type, parent_id = leaf
        if not parent_id or question_id == parent_id:
            return ""
        earlier: list[str] = []
        for question in self.structure.questions:
            if question.question_id != parent_id:
                continue
            for sub in question.subquestions:
                if sub.excluded:
                    continue
                if sub.question_id == question_id:
                    break
                earlier.append(sub.question_id)
            break
        if not earlier:
            return ""
        stored = {
            row.question_id: row
            for row in self.session.scalars(
                select(QuestionResult).where(
                    QuestionResult.job_id == self.job.id,
                    QuestionResult.question_id.in_(earlier),
                )
            )
        }
        lines: list[str] = []
        for earlier_id in earlier:
            row = stored.get(earlier_id)
            if row is None or not is_scoreable(row.processing_state):
                continue
            lines.append(
                f"- Part {earlier_id}: {row.awarded_marks} of {row.max_marks}."
            )
            if (row.student_answer or "").strip():
                lines.append(f"  Student answer: {row.student_answer.strip()[:400]}")
            if (row.working_summary or "").strip():
                lines.append(f"  Working: {row.working_summary.strip()[:400]}")
        if not lines:
            return ""
        return (
            "Earlier parts of this question are already marked. Later parts may "
            "carry method marks that follow through from that work; use it as "
            "context for this part, and do not re-award the earlier part's marks "
            "here.\n" + "\n".join(lines)
        )

    def _blueprint_question(
        self, parent_id: str, question_id: str
    ) -> BlueprintQuestion | None:
        for question in self.structure.questions:
            if question.question_id == question_id:
                return question
            if question.question_id == parent_id:
                for sub in question.subquestions:
                    if sub.question_id == question_id:
                        return BlueprintQuestion(
                            question_id=sub.question_id,
                            label=sub.label,
                            max_marks=sub.max_marks,
                            answer_type=sub.answer_type,
                            special_instructions=sub.special_instructions,
                            criteria_refs=sub.criteria_refs,
                        )
        return None

    # -- model call ------------------------------------------------------
    def _inputs(
        self,
        leaf: tuple[str, int, str | None, str],
        *,
        include_dependencies: bool = False,
    ) -> tuple[LLMInput, ...]:
        """The question, its pages, its criteria and, for marking, earlier parts.

        ``include_dependencies`` is true only for the primary marking request.
        A blind reader and the independent examiner must not be told what the
        first pass decided, and an earlier part's award would anchor them.
        """

        question_id, max_marks, answer_type, parent_id = leaf
        question_pages = self._question_pages(question_id)
        blueprint_question = self._blueprint_question(parent_id, question_id)
        inputs: list[LLMInput] = [
            LLMInput.text_part(
                _question_context(question_id, max_marks, answer_type, blueprint_question)
            )
        ]
        inputs.extend(self._page_inputs(question_pages))

        if include_dependencies:
            earlier = self._dependency_context(leaf)
            if earlier:
                inputs.append(LLMInput.text_part(earlier))

        described = _criterion_lines(self.criteria_by_question.get(question_id) or [])
        if described:
            inputs.append(
                LLMInput.text_part(
                    "Mark scheme criteria for this question. Each line starts with "
                    "the mark point's reference (for example M1#2): that reference, "
                    "not the bare code, identifies the mark point.\n"
                    + "\n".join(described)
                )
            )
        return tuple(inputs)

    def _page_inputs(
        self, pages: list[DocumentPage], *, cap: int | None = None
    ) -> tuple[LLMInput, ...]:
        """The page images, each labelled with the page's own number.

        An image on its own carries no identity: a model shown eight images
        cannot say which one it read, so every quotation it returns is
        unlocatable.  The label states the page's number in the original student
        document, which is what the stored evidence is resolved against — not
        the position of the image inside this request.
        """

        inputs: list[LLMInput] = []
        limit = MAX_PAGES_PER_QUESTION if cap is None else cap
        shown = pages[:limit]
        for page in shown:
            try:
                image = self.storage.read(page.storage_key)
            except StorageError as error:
                raise AppError(
                    ErrorCode.SERVICE_NOT_READY,
                    f"A rendered page is missing from storage (page {page.page_index}).",
                ) from error
            inputs.append(
                LLMInput.text_part(
                    f"Page {page.page_index} of {len(shown)} supplied. This is the "
                    "page's number in the student's own document; cite it as the "
                    "component's page."
                )
            )
            inputs.append(LLMInput.image_part(image, "image/png"))
        return tuple(inputs)

    def _transcription_inputs(
        self, leaf: tuple[str, int, str | None, str], *, pages: list[DocumentPage]
    ) -> tuple[LLMInput, ...]:
        """Pages and the question only — no marks, scheme, award or expected answer.

        The header is built by ``transcription.blind_question_context``, which is
        an allowlist of question id and answer type rather than the marking header
        with fields removed: ``_question_context`` prints maximum marks, special
        instructions and scheme references, and none of that may reach a second
        reader of the page.  The pages are passed in explicitly by the caller, so
        this request can never fall back to the whole script.

        The page set is carried whole: the cap is the number of pages supplied, so
        the builder cannot thin a request the caller decided to send.  A set over
        the request ceiling is refused here rather than silently truncated, which
        is what makes ``TRANSCRIPTION_REQUEST_MAX_PAGES`` true rather than
        advisory.
        """

        question_id, _max_marks, answer_type, _parent_id = leaf
        ceiling = transcription.TRANSCRIPTION_REQUEST_MAX_PAGES
        if len(pages) > ceiling:
            raise AppError(
                ErrorCode.CONFIGURATION_ERROR,
                "A transcription request cannot carry this many pages; the "
                "question must be reported as unavailable instead of being sent "
                "a truncated script.",
                details={"pages": len(pages), "max_pages": ceiling},
            )
        return (
            LLMInput.text_part(
                transcription.blind_question_context(question_id, answer_type)
            ),
            *self._page_inputs(pages, cap=len(pages)),
        )

    def _transcription_page_maps(
        self, rows: list[QuestionResult]
    ) -> tuple[dict[str, list[str]], dict[str, list[str]], dict[str, set[str]]]:
        """Which pages each question is mapped to, and which pages it cited.

        Two *sources of evidence*, not two independent sources: a mapping was
        approved before this run, while a citation is the marking pass naming the
        page it read.  A citation can be the only attribution a paper has, and it
        is useful — but it is the attribution of the very reading under test, so
        it can never make page selection independent of that reading.
        ``owners`` says which question claims a page, so a continuation page is
        only ever added when nobody else claims it.  Page ids are strings and
        ordering is the document's own page order.
        """

        position = {str(page.id): page.page_index for page in self.readable}

        def ordered(page_ids: Any) -> list[str]:
            return sorted(
                {str(page_id) for page_id in page_ids if page_id},
                key=lambda page_id: position.get(page_id, -1),
            )

        tenant_id = self.job.tenant_id
        document_ids = {
            document.id
            for document in DocumentRepository(self.session).list_for_submission(
                tenant_id, self.job.submission_id
            )
        }
        mapped: dict[str, list[str]] = {}
        if document_ids:
            for mapping in self.session.scalars(
                select(PageQuestionMapping).where(
                    PageQuestionMapping.tenant_id == tenant_id,
                    PageQuestionMapping.document_id.in_(document_ids),
                    PageQuestionMapping.blueprint_version_id == self.job.blueprint_version_id,
                )
            ):
                mapped.setdefault(str(mapping.question_id), []).append(
                    str(mapping.page_id)
                )
        cited: dict[str, list[str]] = {}
        row_ids = [row.id for row in rows]
        if row_ids:
            for item in self.session.scalars(
                select(MarkingEvidence).where(
                    MarkingEvidence.question_result_id.in_(row_ids),
                    MarkingEvidence.page_id.is_not(None),
                )
            ):
                owner = next(
                    (row for row in rows if row.id == item.question_result_id), None
                )
                if owner is not None:
                    cited.setdefault(str(owner.question_id), []).append(
                        str(item.page_id)
                    )
        mapped = {question_id: ordered(ids) for question_id, ids in mapped.items()}
        cited = {question_id: ordered(ids) for question_id, ids in cited.items()}
        owners: dict[str, set[str]] = {}
        for source in (mapped, cited):
            for question_id, page_ids in source.items():
                for page_id in page_ids:
                    owners.setdefault(page_id, set()).add(question_id)
        return mapped, cited, owners

    def marking_model_identities(
        self, rows: list[QuestionResult]
    ) -> tuple[set[str], dict[str, str]]:
        """Every model that actually answered a marking request for this job.

        Three sources, because a job is not one execution and a paper is not one
        model:

        * the models that answered in this execution (in memory);
        * the model persisted on the job, which is what a resumed execution sees;
        * the append-only usage ledger, which records the model of every attempt —
          the only source that still knows about a provider fallback that happened
          before a resume.

        A double check re-marks the question with another model, so its model is
        included too: a ``blind`` reading answered by the model that gave the
        second opinion is not a third reader.  The second return value is the model
        that produced each question's *accepted* marking reply, taken from that
        row's own usage record; an attempt that failed is never reported as the
        reader.
        """

        models = set(
            transcription.marking_model_set(
                self.marking_models,
                [self.job.primary_model] if self.job.primary_model else [],
            )
        )
        ledger = list(
            self.session.scalars(
                select(ProviderUsage.model).where(
                    ProviderUsage.job_id == self.job.id,
                    ProviderUsage.purpose.in_(("marking", "double_check")),
                    ProviderUsage.success.is_(True),
                )
            )
        )
        models.update(transcription.marking_model_set(ledger))

        by_question: dict[str, str] = {}
        usage_ids = {
            row.provider_usage_id: row.question_id
            for row in rows
            if row.provider_usage_id is not None
        }
        if usage_ids:
            for usage_id, model in self.session.execute(
                select(ProviderUsage.id, ProviderUsage.model).where(
                    ProviderUsage.id.in_(set(usage_ids))
                )
            ):
                reader = str(model or "").strip()
                if reader:
                    by_question[usage_ids[usage_id]] = reader
        return models, by_question

    def call_model(
        self,
        leaf: tuple[str, int, str | None, str],
        *,
        prompt_id: str,
        purpose: str,
        inputs: tuple[LLMInput, ...] | None = None,
        response_schema: dict | None = None,
        max_output_tokens: int = 8192,
    ):
        """One audited provider call for this question.

        A provider outage becomes ``RetryablePipelineError`` so the runner parks
        the job; a refusal the provider would repeat is raised unchanged.

        A marking request names its model explicitly, so the call has one
        entry and no fallback.  The second opinion and the blind transcription
        keep their own review role and are not marking requests.
        """

        try:
            call = self.calls.call(
                tenant_id=self.job.tenant_id,
                purpose=purpose,
                prompt_id=prompt_id,
                inputs=(
                    inputs
                    if inputs is not None
                    else self._inputs(
                        leaf, include_dependencies=purpose == "marking"
                    )
                ),
                job_id=self.job.id,
                prompt_version=(
                    self.marking_prompt_version if prompt_id == PROMPT_MARKING else None
                ),
                response_schema=response_schema or MARKING_RESPONSE_SCHEMA,
                max_output_tokens=max_output_tokens,
                model=(
                    self._marking_model() if purpose == "marking" else None
                ),
            )
        except AppError as error:
            if error.code in _RETRYABLE:
                raise RetryablePipelineError(str(error)) from error
            raise
        if purpose == "marking":
            self._remember_marking_model(call)
        # The identity of the prompt that actually answered, not the one this
        # class last used: a whole-paper row and a fallback row in one job must
        # each name their own source.
        version = getattr(getattr(call, "prompt", None), "version", None)
        if version is not None:
            identity = f"{prompt_id}:v{version}"
            self.prompt_version = identity
            if identity not in self.prompt_versions:
                self.prompt_versions.append(identity)
        return call

    # -- one question ----------------------------------------------------
    def _marking_model(self) -> str:
        """The model assigned to mark this paper, decided once.

        The scheduler records the assignment on the job before the first paid
        request, so a resumed job keeps the model that started it and a paper is
        never marked by two models.  With no recorded assignment the configured
        default applies.  Either way the answer is one model: the three verified
        primaries are alternatives across papers, never inside one paper.
        """

        assigned = (getattr(self.job, "primary_model", None) or "").strip()
        candidate = assigned or PRODUCTION_MARKING_MODEL
        if not is_primary_marking_model(candidate):
            raise AppError(
                ErrorCode.CONFIGURATION_ERROR,
                f"This paper is assigned to {candidate!r}, which is not a "
                "verified primary marking model. Nothing was sent to the "
                "provider and no other model was tried.",
                details={
                    "assigned_model": candidate,
                    "verified_marking_models": list(PRIMARY_MARKING_MODELS),
                },
            )
        return candidate

    def _remember_marking_model(self, call: Any) -> None:
        """Record which model actually read this paper's script.

        The blind transcription is only independent of the marking if a
        different model answers it, and a resumed job needs that fact after this
        execution has gone.  Populated both by ``call_model`` and by ``accept``:
        in parallel correction the call happens on a worker thread with a replica
        of this run, so the orchestrator's list must be told separately.
        """

        model = (getattr(call.response, "model", None) or "").strip()
        if not model:
            return
        assigned = (getattr(self.job, "primary_model", None) or "").strip()
        if not is_primary_marking_model(model) or (assigned and model != assigned):
            # The request named one model, so a different model answering is a
            # provider or configuration contradiction -- including a silent
            # substitution between two verified primaries.  Record it as a
            # refusal rather than attributing the paper to another model.
            raise AppError(
                ErrorCode.CONFIGURATION_ERROR,
                f"A marking request for this paper was answered by {model!r}, "
                f"but it is assigned to {assigned or PRODUCTION_MARKING_MODEL!r}. "
                "Nothing from that reply was stored.",
                details={
                    "answered_by": model,
                    "assigned_model": assigned or PRODUCTION_MARKING_MODEL,
                    "verified_marking_models": list(PRIMARY_MARKING_MODELS),
                },
            )
        self.marking_models.add(model)
        # The job records the model that actually answered, not merely the one
        # that was configured.  With one explicit entry these are the same; the
        # assignment makes the audit compare the real reply.
        self.job.primary_model = model

    def mark(
        self,
        leaf: tuple[str, int, str | None, str],
        *,
        existing: QuestionResult | None = None,
        source: str = MODE_PER_QUESTION,
    ) -> tuple[QuestionResult | None, str | None]:
        """Mark one leaf; return the row and, when the reply was unusable, why."""

        call = self.call_model(leaf, prompt_id=PROMPT_MARKING, purpose="marking")
        return self.accept(leaf=leaf, call=call, existing=existing, source=source)

    def accept(
        self,
        *,
        leaf: tuple[str, int, str | None, str],
        call: Any,
        existing: QuestionResult | None,
        source: str,
        prompt_version: str | None = None,
    ) -> tuple[QuestionResult | None, str | None]:
        """Parse, validate and persist one paid marking reply.

        Kept separate from ``mark`` so parallel correction can obtain the reply
        on a worker thread and run exactly this single-threaded acceptance on the
        orchestrating thread: one parsed reply, one row, no shared transaction.
        An unusable reply is still a stored, reviewable row, never a zero.
        """

        question_id = leaf[0]
        self._remember_marking_model(call)
        if prompt_version:
            self.prompt_version = prompt_version
            if prompt_version not in self.prompt_versions:
                self.prompt_versions.append(prompt_version)

        captured = evidence.capture_raw_response(call.response.text)
        try:
            mark = parse_question_mark(call.response.text, question_id=question_id)
        except MarkingResponseInvalid as error:
            row = self._persist_invalid(
                question_id,
                leaf[1],
                str(error),
                captured=captured,
                existing=existing,
                usage_id=call.usage_id,
                source=source,
            )
            return row, str(error)

        row = self._persist_mark(
            mark,
            captured=captured,
            max_marks=leaf[1],
            existing=existing,
            withheld_pages=self.withheld_pages(question_id),
            usage_id=call.usage_id,
            source=source,
        )
        return row, None

    def replica(self, session: Session, calls: ProviderCallService) -> _MarkingRun:
        """A worker thread's own view of this run's immutable context.

        Only the session and call service differ, so the provider call writes its
        usage row on the worker's connection.  The accumulators start empty and
        the job is a read-only snapshot: a worker must not mutate the findings or
        the ORM entity the orchestrating thread owns.
        """

        # Every job field the request path reads, because inputs are now built
        # on the worker thread (dependent context must see the stored earlier
        # part).  The snapshot is why no worker touches the orchestrating
        # thread's ORM entity.
        snapshot = SimpleNamespace(
            id=self.job.id,
            tenant_id=self.job.tenant_id,
            submission_id=self.job.submission_id,
            blueprint_version_id=self.job.blueprint_version_id,
            scheme_version_id=self.job.scheme_version_id,
            primary_model=self.job.primary_model,
        )
        return _MarkingRun(
            session=session,
            job=snapshot,
            settings=self.settings,
            structure=self.structure,
            criteria_by_question=self.criteria_by_question,
            readable=self.readable,
            calls=calls,
            storage=self.storage,
            quality=self.quality,
            engine_version=self.engine_version,
            policy=self.policy,
            marking_prompt_version=self.marking_prompt_version,
            marking_mode=self.marking_mode,
            page_cap=self.page_cap,
            leaf_by_question=self.leaf_by_question,
            page_index=self.page_index,
        )

    # -- one paper -------------------------------------------------------
    def _paper_context(self, leaves: list[tuple[str, int, str | None, str]]) -> str:
        """Every question of the paper, with its marks and its scheme criteria.

        The paper request carries the whole script, so it must also carry the
        whole scheme.  Asking for 39 awards while naming one question's criteria
        would invite the model to invent the other 38.
        """

        lines = [
            "This request carries one complete student paper.",
            f"Questions to mark: {len(leaves)}",
            "Mark every question listed below and return every one of them, in "
            "this order.",
            "",
        ]
        for question_id, max_marks, answer_type, parent_id in leaves:
            blueprint_question = self._blueprint_question(parent_id, question_id)
            lines.append(
                _question_context(question_id, max_marks, answer_type, blueprint_question)
            )
            criteria = _criterion_lines(self.criteria_by_question.get(question_id) or [])
            if criteria:
                lines.append(
                    "Mark scheme criteria (each line starts with the mark point's "
                    "reference, e.g. M1#2; the reference identifies the point):"
                )
                lines.extend(criteria)
            lines.append("")
        return "\n".join(lines)

    def _paper_inputs(
        self, leaves: list[tuple[str, int, str | None, str]]
    ) -> tuple[LLMInput, ...] | None:
        """The paper's context and pages, or ``None`` when it cannot be sent whole.

        A script with more pages than one request may carry is refused, not
        thinned: ``run`` turns this into ``REVIEW_REQUIRED`` before any provider
        call.  Dropping pages here would turn an answer nobody read into an
        apparent blank, and marking the rest question by question would report a
        whole paper that was never sent.
        """

        cap = self.settings.marking.whole_paper_max_pages
        if len(self.readable) > cap:
            return None
        return (
            LLMInput.text_part(self._paper_context(leaves)),
            *self._page_inputs(self.readable, cap=cap),
        )

    def mark_paper(
        self,
        leaves: list[tuple[str, int, str | None, str]],
        *,
        existing: dict[str, QuestionResult | None],
    ) -> PaperOutcome:
        """Mark every leaf in one audited request and persist the reply atomically.

        All rows land in one transaction: a paper either lands whole or not at
        all.  A leaf the reply did not answer — missing, invalid, duplicated or
        lost to truncation — keeps no row here, so the caller's per-question
        loop marks exactly those and never repeats the questions this reply
        already decided.
        """

        question_ids = [leaf[0] for leaf in leaves]
        detail: dict[str, Any] = {
            "mode": MODE_WHOLE_PAPER,
            "questions": len(question_ids),
            "output_token_cap": self.settings.marking.whole_paper_max_output_tokens,
        }
        if len(question_ids) > MAX_WHOLE_PAPER_LEAVES:
            detail.update(
                status="SKIPPED",
                reason="TOO_MANY_QUESTIONS",
                leaves=len(question_ids),
                max_leaves=MAX_WHOLE_PAPER_LEAVES,
            )
            return PaperOutcome(detail=detail)
        inputs = self._paper_inputs(leaves)
        if inputs is None:
            detail.update(
                status="SKIPPED",
                reason="PAGES_EXCEED_REQUEST_CAP",
                pages=len(self.readable),
                max_pages=self.settings.marking.whole_paper_max_pages,
            )
            return PaperOutcome(detail=detail)

        # A paper request may already have been paid for by an execution that
        # died before its rows landed.  Its archived reply is reused before any
        # new request, and a paid call with no recoverable archive refuses this
        # execution rather than buying the same paper twice.  The provider offers
        # no idempotency key, so this narrows — it does not eliminate — the window
        # in which an answered request can be lost: a process that dies after the
        # provider replies and before the usage row is committed leaves no trace.
        recovered = self._recoverable_paper_reply(question_ids)
        if recovered is not None:
            archive_row, body, parsed = recovered
            usage_id = archive_row.provider_usage_id
            truncated = detect_truncation(archive_row.finish_reason)
            detail.update(
                status="PARSED",
                recovered_from_archive=True,
                provider_response_id=str(archive_row.id),
                paper_sha256=archive_row.content_sha256,
                finish_reason=archive_row.finish_reason,
                truncated=truncated,
                provider_usage_id=str(usage_id) if usage_id else None,
            )
        else:
            if self._paid_paper_attempt():
                detail.update(
                    status="SKIPPED",
                    reason="PAID_ATTEMPT_UNRECOVERABLE",
                    message=(
                        "A whole-paper request for this job has already been paid for, "
                        "and its reply cannot be recovered from the archive. It is not "
                        "sent again; the unmarked questions are marked individually."
                    ),
                )
                return PaperOutcome(detail=detail)

            call = self.call_model(
                leaves[0],
                prompt_id=PROMPT_MARKING_WHOLE_PAPER,
                purpose="marking",
                inputs=inputs,
                response_schema=WHOLE_PAPER_RESPONSE_SCHEMA,
                max_output_tokens=self.settings.marking.whole_paper_max_output_tokens,
            )
            body = call.response.text or ""
            truncated = detect_truncation(call.response.finish_reason)
            digest = paper_sha256(body)
            # The complete reply is archived once, before anything is parsed, and
            # committed on its own.  The reply is paid for: losing the question
            # rows must not also lose the evidence a retry needs to rebuild them
            # without another request.
            archived = evidence.capture_provider_response(body)
            detail.update(
                status="REQUESTED",
                finish_reason=call.response.finish_reason,
                truncated=truncated,
                output_tokens=call.response.usage.output_tokens,
                paper_sha256=digest,
                provider_usage_id=str(call.usage_id),
                provider_request_id=call.response.provider_request_id,
                # The reply itself lives once, in ``provider_responses``, addressed
                # by ``paper_sha256``.  Copying the body into the run record as well
                # would store every paid reply twice and let the two copies drift.
                archived_response_truncated=archived.truncated,
            )
            try:
                archive_row = self._archive_response(
                    body=body,
                    digest=digest or "",
                    captured=archived,
                    call=call,
                    source=MODE_WHOLE_PAPER,
                )
                self.session.commit()
            except SQLAlchemyError:
                # The paid reply could not be kept at all.  Parking the job is
                # honest; nothing was marked and nothing is re-requested here.
                self.session.rollback()
                detail.update(
                    status="ARCHIVE_FAILED",
                    error="The paid reply could not be archived.",
                )
                return PaperOutcome(detail=detail)
            usage_id = call.usage_id
            detail["provider_response_id"] = str(archive_row.id)
            try:
                parsed = parse_whole_paper(
                    body, expected_ids=question_ids, truncated=truncated
                )
            except WholePaperResponseInvalid as error:
                # The reply is already archived, so a person can read exactly
                # what the model said; the questions fall back individually.
                detail.update(status="UNREADABLE", error=str(error)[:500])
                return PaperOutcome(detail=detail)
            detail.update(status="PARSED", **parsed.describe())
        if parsed.invalid:
            detail["invalid_questions"] = dict(sorted(parsed.invalid.items())[:20])
        if parsed.unknown_ids:
            detail["unknown_ids"] = sorted(set(parsed.unknown_ids))[:20]

        cap = self.settings.marking.whole_paper_max_pages
        rows: dict[str, QuestionResult] = {}
        try:
            # The archive is written inside the same transaction as the rows: a
            # paper whose marks could not be stored leaves no orphan document.
            for sequence, question_id in enumerate(
                item for item in question_ids if item in parsed.marks
            ):
                mark = parsed.marks[question_id]
                leaf = self.leaf_by_question[question_id]
                rows[question_id] = self._persist_mark(
                    mark,
                    captured=evidence.CapturedResponse(
                        value={
                            "format": "WHOLE_PAPER_SLICE",
                            "paper_sha256": archive_row.content_sha256,
                            "provider_usage_id": str(usage_id) if usage_id else None,
                            "sequence": sequence,
                            "question_id": question_id,
                            "item": mark.model_dump(mode="json"),
                        },
                        truncated=False,
                    ),
                    max_marks=leaf[1],
                    existing=existing.get(question_id),
                    withheld_pages=self.withheld_pages(question_id, cap=cap),
                    usage_id=usage_id,
                    source=MODE_WHOLE_PAPER,
                    sequence=sequence,
                    commit=False,
                )
            self.session.commit()
        except SQLAlchemyError as error:
            # Atomic or nothing: a paper that could not be stored whole is not
            # half-stored, and the paid reply stays in the usage ledger.
            self.session.rollback()
            detail.update(
                status="PERSIST_FAILED",
                persisted=0,
                error=f"{type(error).__name__}",
            )
            return PaperOutcome(detail=detail)
        detail["persisted"] = len(rows)
        return PaperOutcome(rows=rows, detail=detail)

    # -- recovery --------------------------------------------------------
    @staticmethod
    def _archived_text(body: Any) -> str | None:
        """The reply text an archived body holds, or ``None`` if it is unusable.

        An archive stores the reply decoded as JSON when it was JSON, and a
        wrapper object when it was not.  A wrapper marked ``TEXT_TRUNCATED`` was
        clipped for storage, so it cannot be re-parsed faithfully.
        """

        if isinstance(body, str):
            return body
        if isinstance(body, dict):
            if body.get("format") == "TEXT_TRUNCATED":
                return None
            text = body.get("text")
            if body.get("format") == "UNPARSEABLE_TEXT" and isinstance(text, str):
                return text
            import json

            return json.dumps(body)
        return None

    def _recoverable_paper_reply(
        self, question_ids: list[str]
    ) -> tuple[ProviderResponse, str, Any] | None:
        """An archived paper reply that still yields marks for these questions.

        Newest first: a job may have archived more than one reply, and only one
        that parses to a mark for a still-missing question is worth reusing.
        """

        rows = self.session.scalars(
            select(ProviderResponse)
            .where(
                ProviderResponse.job_id == self.job.id,
                ProviderResponse.response_source == MODE_WHOLE_PAPER,
            )
            .order_by(
                ProviderResponse.created_at.desc(), ProviderResponse.sequence.desc()
            )
        ).all()
        for row in rows:
            text = self._archived_text(row.body)
            if not text:
                continue
            try:
                parsed = parse_whole_paper(
                    text,
                    expected_ids=question_ids,
                    truncated=detect_truncation(row.finish_reason),
                )
            except WholePaperResponseInvalid:
                continue
            if parsed.marks:
                return row, text, parsed
        return None

    def _paid_paper_attempt(self) -> bool:
        """Whether this job already has a successful whole-paper provider call.

        The usage ledger is append-only and committed when the call returns, so a
        paid request leaves a durable trace even when its reply and rows were
        lost.  That trace is what forbids paying for the same paper twice.
        """

        versions = select(PromptVersion.id).where(
            PromptVersion.prompt_id == PROMPT_MARKING_WHOLE_PAPER
        )
        count = self.session.scalar(
            select(func.count())
            .select_from(ProviderUsage)
            .where(
                ProviderUsage.job_id == self.job.id,
                ProviderUsage.success.is_(True),
                ProviderUsage.prompt_version_id.in_(versions),
            )
        )
        return bool(count)

    # -- persistence -----------------------------------------------------
    def _write_provenance(
        self,
        row: QuestionResult,
        *,
        usage_id: uuid.UUID | None = None,
        source: str | None = None,
        sequence: int | None = None,
    ) -> None:
        row.engine_version = self.engine_version
        row.prompt_version = self.prompt_version
        row.response_source = source
        row.response_sequence = sequence
        row.provider_usage_id = usage_id

    def _archive_response(
        self,
        *,
        body: str,
        digest: str,
        captured: evidence.CapturedResponse,
        call: Any,
        source: str,
        sequence: int = 0,
    ) -> ProviderResponse:
        """Keep one complete reply per audited call and return the archived row.

        The body is addressed by its own SHA-256 and by the audited call that
        received it, so every question row it produced can be traced back to the
        document it came from.  One archive row per call: a retry that receives
        a byte-identical reply stores its own copy, so the archive never claims a
        call is linked to a body it did not receive.
        """

        usage_id = getattr(call, "usage_id", None)
        existing = (
            self.session.scalar(
                select(ProviderResponse).where(
                    ProviderResponse.job_id == self.job.id,
                    ProviderResponse.provider_usage_id == usage_id,
                )
            )
            if usage_id is not None
            else None
        )
        if existing is not None:
            return existing
        row = ProviderResponse(
            tenant_id=self.job.tenant_id,
            job_id=self.job.id,
            provider_usage_id=usage_id,
            prompt_version_id=getattr(call, "prompt_version_id", None),
            response_source=source,
            sequence=sequence,
            content_sha256=digest,
            content_length=len(body),
            body=captured.value,
            body_truncated=captured.truncated,
            finish_reason=getattr(call.response, "finish_reason", None),
            model=getattr(call.response, "model", None),
        )
        self.session.add(row)
        self.session.flush()
        return row

    def _persist_invalid(
        self,
        question_id: str,
        max_marks: int,
        message: str,
        *,
        captured: evidence.CapturedResponse,
        existing: QuestionResult | None,
        usage_id: uuid.UUID | None = None,
        source: str | None = None,
        sequence: int | None = None,
    ) -> QuestionResult:
        row = existing or QuestionResult(
            tenant_id=self.job.tenant_id,
            job_id=self.job.id,
            question_id=question_id,
            max_marks=max_marks,
        )
        if existing is not None:
            # An unusable reply replaces whatever the question carried before: the
            # component, evidence and verification records of an earlier attempt
            # must not outlive it.
            self.session.query(CriterionResult).filter(
                CriterionResult.question_result_id == row.id
            ).delete(synchronize_session=False)
            self.session.query(MarkingEvidence).filter(
                MarkingEvidence.question_result_id == row.id
            ).delete(synchronize_session=False)
            self._clear_marking_verifications(question_id)
        row.max_marks = max_marks
        row.awarded_marks = 0
        row.status = status_for(ProcessingState.NEEDS_REVIEW)
        row.processing_state = ProcessingState.NEEDS_REVIEW.value
        row.student_answer = None
        row.working_summary = None
        row.confidence = None
        row.review_required = True
        row.raw_awarded_marks = None
        row.normalised_awarded_marks = 0
        row.normalisation_anomaly = evidence.MODEL_RESPONSE_INVALID
        row.normalisation_detail = {"reason": message[:1000]}
        row.raw_response = captured.value
        row.raw_response_truncated = captured.truncated
        row.scheme_concerns = [{"code": "MODEL_RESPONSE_INVALID", "message": message}]
        self._write_provenance(
            row, usage_id=usage_id, source=source, sequence=sequence
        )
        if existing is None:
            self.session.add(row)
        self.session.flush()
        self.session.commit()
        return row

    def _persist_mark(
        self,
        mark: QuestionMark,
        *,
        captured: evidence.CapturedResponse,
        max_marks: int,
        existing: QuestionResult | None,
        withheld_pages: int = 0,
        usage_id: uuid.UUID | None = None,
        source: str | None = None,
        sequence: int | None = None,
        commit: bool = True,
    ) -> QuestionResult:
        normalised = evidence.normalise_award(mark.awarded_marks, max_marks=max_marks)
        awarded = normalised.normalised
        findings = check_mark(
            awarded=awarded,
            max_marks=max_marks,
            components=mark.components,
            student_answer=mark.student_answer,
            confidence=mark.confidence,
        )
        verification = verify_question(
            mark,
            max_marks=max_marks,
            min_confidence=self.settings.marking.min_confidence,
            page_quality=self.quality,
        )
        concerns = list(verification.reasons)

        # The approved scheme is independent of the model's reply.  Comparing the
        # two catches an award built on a mark point the scheme does not define, a
        # mark point never considered, an award larger than the scheme's capacity,
        # a dependent mark without its prerequisite, and a final answer that the
        # scheme's stated answer contradicts.
        criteria = self.criteria_by_question.get(mark.question_id, [])
        scheme_findings = scheme_check.check_against_scheme(
            awarded=awarded,
            components=mark.components,
            criteria=criteria,
            question_id=mark.question_id,
            max_marks=max_marks,
        )
        scheme_math = scheme_check.check_answer_against_scheme(
            student_expression=(
                mark.answer_check.student_expression
                if mark.answer_check is not None
                else mark.student_answer
            ),
            criteria=criteria,
        )
        scheme_findings.extend(
            scheme_check.scheme_math_findings(
                scheme_math,
                awarded=awarded,
                max_marks=max_marks,
                components=mark.components,
                criteria=criteria,
                question_id=mark.question_id,
            )
        )
        # A printed term threshold is checked only when the route was awarded and
        # the approved data records the expression and the count.  An expression
        # the check cannot read is reported as unverified, never as satisfied.
        scheme_findings.extend(
            scheme_check.term_count_findings(
                components=mark.components,
                criteria=criteria,
                student_expression=(
                    mark.answer_check.student_expression
                    if mark.answer_check is not None
                    else mark.student_answer
                ),
                question_id=mark.question_id,
            )
        )
        # Every component must name one approved mark point, and every quotation
        # must be attributable to a page of the original student document.  The
        # resolutions are what the stored rows carry as provenance; the findings
        # describe what could not be attributed.
        identity_resolutions, identity_findings = criterion_identity.check_components(
            components=mark.components,
            criteria=criteria,
            question_id=mark.question_id,
            scheme_version_id=self.job.scheme_version_id,
        )
        attributions, evidence_findings = provenance.attribute(
            components=mark.components,
            index=self.page_index,
            question_id=mark.question_id,
            require_page=page_attribution_required(self.prompt_version),
        )
        scheme_findings.extend(identity_findings)
        scheme_findings.extend(evidence_findings)
        scheme_records: list[VerificationRecord] = []
        if scheme_math.status != "SKIPPED":
            scheme_records.append(
                VerificationRecord(
                    kind="SCHEME_MATHEMATICAL",
                    status=scheme_math.status,
                    detail={
                        "student_expression": scheme_math.student_expression,
                        "expected_expression": scheme_math.expected_expression,
                        "expected_criterion": scheme_math.expected_criterion,
                        "awarded_marks": awarded,
                        "max_marks": max_marks,
                    },
                )
            )
        # A definite mismatch is a contradiction with the approved scheme and is
        # always reviewed.  A possible mismatch costs an operator's attention, so
        # ECONOMY records it as evidence without stopping the paper; the wider
        # modes act on it.
        reviewable = [
            finding
            for finding in scheme_findings
            if finding.definite or self.policy.mode != sampling.MODE_ECONOMY
        ]
        for finding in reviewable:
            concerns.append(f"{finding.code}: {finding.message}")
        for finding in scheme_findings:
            self.scheme_findings.append(
                f"{mark.question_id}: {finding.code} ({finding.severity})"
            )
        recorded_only = [finding for finding in scheme_findings if finding not in reviewable]
        for message in self.coverage_messages:
            concerns.append(f"PAGE_COVERAGE: {message}")
        if normalised.anomaly == evidence.OVER_MAX_AWARD:
            # The model's claim is kept in raw_awarded_marks; the stored award is
            # zero and a person decides.  Clamping would invent a mark.
            concerns.append(
                f"The model awarded {normalised.raw} of {max_marks}; the award was not applied."
            )
        for finding in findings:
            concerns.append(f"{finding.code}: {finding.message}")
            self.integrity_findings.append(f"{mark.question_id}: {finding.code}")
        if withheld_pages:
            # The model read a partial script for this question.  Its award is
            # kept as evidence, but it must not be presented as if the whole
            # script had been read.
            concerns.append(
                f"PAGE_LIMIT_TRUNCATED: {withheld_pages} page(s) belonging to this "
                f"question were not supplied because a request carries at most "
                f"{self.page_cap}. The award covers only the pages read, so a "
                "person decides it."
            )

        state = state_for_mark(
            awarded=awarded,
            review_required=bool(concerns),
            integrity_failed=bool(findings),
            confidence=mark.confidence,
            min_confidence=self.settings.marking.min_confidence,
        )
        status = status_for(state)
        ensure_consistent(status, state)

        row = existing or QuestionResult(
            tenant_id=self.job.tenant_id,
            job_id=self.job.id,
            question_id=mark.question_id,
            max_marks=max_marks,
        )
        if existing is not None:
            # Recovery replaces an unusable reply, never a decided question:
            # its dependent rows are cleared so the record has one story.
            self.session.query(CriterionResult).filter(
                CriterionResult.question_result_id == row.id
            ).delete(synchronize_session=False)
            self.session.query(MarkingEvidence).filter(
                MarkingEvidence.question_result_id == row.id
            ).delete(synchronize_session=False)

        row.question_id = mark.question_id
        row.max_marks = max_marks
        row.awarded_marks = awarded
        row.status = status
        row.processing_state = state.value
        row.student_answer = mark.student_answer
        row.working_summary = mark.notes
        row.confidence = mark.confidence
        row.review_required = state is ProcessingState.NEEDS_REVIEW
        row.raw_awarded_marks = normalised.raw
        row.normalised_awarded_marks = awarded
        row.normalisation_anomaly = normalised.anomaly
        row.normalisation_detail = normalised.detail
        row.raw_response = captured.value
        row.raw_response_truncated = captured.truncated
        # Coverage findings keep their own code so a later execution can remove
        # a gap that has since closed without disturbing any other reason.
        coverage_reasons = [
            reason for reason in concerns if reason.startswith("PAGE_COVERAGE: ")
        ]
        other_reasons = [reason for reason in concerns if reason not in coverage_reasons]
        row.scheme_concerns = [
            {"code": "REVIEW", "message": reason} for reason in other_reasons
        ] + [
            {"code": "PAGE_COVERAGE", "message": reason}
            for reason in coverage_reasons
        ] + [
            {
                "code": finding.code,
                "message": finding.message,
                "severity": finding.severity,
            }
            for finding in recorded_only
        ]
        self._write_provenance(
            row, usage_id=usage_id, source=source, sequence=sequence
        )
        if existing is None:
            self.session.add(row)
        self.session.flush()

        # One resolution and one attribution per component, in the reply's own
        # order, so the stored row says which mark point it credited and where
        # the quotation it credited it from is written.
        credited: set[uuid.UUID] = set()
        for component, resolution, attribution in zip(
            mark.components, identity_resolutions, attributions, strict=True
        ):
            criterion = resolution.criterion
            criterion_id = resolution.criterion_id
            if resolution.resolved and criterion_id in credited:
                # The same mark point claimed twice: the scheme check reports
                # it and the row keeps no link, so the store cannot claim one
                # mark point was earned by two awards.
                criterion_id = None
            elif resolution.resolved:
                credited.add(criterion_id)
            quoted = (component.evidence or "").strip()
            located: dict[str, Any] = {}
            if component.reference:
                located["reference"] = component.reference
            if attribution.claimed_page is not None:
                located["page"] = attribution.claimed_page
            if attribution.page_id is not None:
                located["page_resolved"] = attribution.page_number
            if component.bbox_invalid:
                located["bbox_rejected"] = component.bbox_invalid
            self.session.add(
                CriterionResult(
                    tenant_id=self.job.tenant_id,
                    question_result_id=row.id,
                    criterion_id=criterion_id,
                    # The approved code the mark point prints, not the reply's
                    # decorated label: the stored component names the scheme.
                    code=(
                        str(getattr(criterion, "code", component.code)).strip()
                        if criterion_id is not None
                        else component.code
                    ),
                    awarded=component.awarded,
                    reason=component.reason,
                    evidence=(
                        [{"quote": quoted, **located}] if quoted else []
                    ),
                )
            )
            if quoted:
                self.session.add(
                    MarkingEvidence(
                        tenant_id=self.job.tenant_id,
                        question_result_id=row.id,
                        criterion_id=criterion_id,
                        page_id=attribution.page_id,
                        bbox=attribution.bbox,
                        kind="QUOTE",
                        quote=component.evidence,
                    )
                )

        # Replace the marking verdicts wholesale.  Upserting only the kinds this
        # reply produced would leave a stale verdict from an earlier attempt (a
        # mathematical comparison the new reply never made) attached to the
        # current result, and the review screen would show a conclusion the
        # current evidence does not support.
        self._clear_marking_verifications(mark.question_id)
        self._persist_verifications(mark.question_id, verification, scheme_records)
        # A whole-paper reply writes every row in one transaction; a failure part
        # way through must leave no question behind, so the commit is the
        # caller's to make when it persists a paper.
        if commit:
            self.session.commit()
        return row

    def _clear_marking_verifications(self, question_id: str) -> None:
        """Remove the verdicts a marking reply owns, before writing new ones."""

        for existing in self.session.scalars(
            select(VerificationResult).where(
                VerificationResult.job_id == self.job.id,
                VerificationResult.question_id == question_id,
                VerificationResult.kind.in_(MARKING_VERIFICATION_KINDS),
            )
        ):
            self.session.delete(existing)

    def _persist_verifications(
        self,
        question_id: str,
        verification: VerificationOutcome,
        extra: list[VerificationRecord] | None = None,
    ) -> None:
        for record in list(verification.records) + list(extra or []):
            existing = self.session.scalar(
                select(VerificationResult).where(
                    VerificationResult.job_id == self.job.id,
                    VerificationResult.question_id == question_id,
                    VerificationResult.kind == record.kind,
                )
            )
            if existing is not None:
                existing.status = record.status
                existing.detail = record.detail
                continue
            self.session.add(
                VerificationResult(
                    tenant_id=self.job.tenant_id,
                    job_id=self.job.id,
                    question_id=question_id,
                    kind=record.kind,
                    status=record.status,
                    detail=record.detail,
                )
            )


class AetrixPipeline(CorrectionPipeline):
    name = "aetrix_v5_5"

    def __init__(
        self,
        *,
        provider: LLMProvider | None = None,
        registry: PromptRegistry | None = None,
        storage: Storage | None = None,
    ) -> None:
        self._provider = provider
        self._registry = registry
        self._storage = storage

    # -- entry point -----------------------------------------------------
    def run(
        self, job: CorrectionJob, session: Session, settings: Settings
    ) -> PipelineOutcome:
        current = session.get(CorrectionJob, job.id)
        if current is None:
            raise RuntimeError("the claimed job disappeared before marking started")
        if current.cancel_requested:
            return PipelineOutcome(JobState.CANCELLED, {"reason": "cancelled before marking"})

        tenant_id = current.tenant_id
        blueprint = session.get(ExamBlueprintVersion, current.blueprint_version_id)
        scheme = session.get(MarkSchemeVersion, current.scheme_version_id)
        if blueprint is None or scheme is None:
            raise RuntimeError("the job references a missing blueprint or scheme version")
        if blueprint.tenant_id != tenant_id or scheme.tenant_id != tenant_id:
            raise RuntimeError("the job references a version from another workspace")
        if blueprint.status != "APPROVED":
            return PipelineOutcome(
                JobState.REVIEW_REQUIRED,
                {"reason": "BLUEPRINT_NOT_APPROVED", "blueprint_status": blueprint.status},
            )
        if scheme.status != "APPROVED":
            return PipelineOutcome(
                JobState.REVIEW_REQUIRED,
                {"reason": "SCHEME_NOT_APPROVED", "scheme_status": scheme.status},
            )
        if current.primary_model and not is_primary_marking_model(current.primary_model):
            # A job stamped before this policy still names a Lite model, and a
            # job with an unknown id could never be resumed safely.  Continuing
            # would mark it with a different model while the job claimed the old
            # one, so it stops for a person instead of being re-assigned.
            detail = {
                "reason": "MODEL_POLICY_MISMATCH",
                "recorded_model": current.primary_model,
                "verified_marking_models": list(PRIMARY_MARKING_MODELS),
                "message": (
                    f"This job records {current.primary_model!r} as its marking "
                    "model, which is not a verified primary marking model. It was "
                    f"not marked. The verified models are "
                    f"{', '.join(PRIMARY_MARKING_MODELS)}; re-create the job to "
                    "mark this paper with one of them."
                ),
            }
            runs.record_run(
                session,
                job=current,
                stage=runs.STAGE_MARKING,
                outcome=runs.OUTCOME_REVIEW,
                detail=detail,
            )
            session.commit()
            return PipelineOutcome(JobState.REVIEW_REQUIRED, detail)

        structure = BlueprintStructure.model_validate(blueprint.structure)
        pages = self._pages(session, tenant_id, current.submission_id)
        readable = [
            page for page in pages if page.quality_status not in {"UNREADABLE", "EMPTY"}
        ]
        if not readable:
            return PipelineOutcome(
                JobState.REVIEW_REQUIRED,
                {
                    "reason": "NO_RENDERABLE_PAGES",
                    "page_count": len(pages),
                    "message": "No page of this submission can be read, so nothing was marked.",
                },
            )

        storage = self._storage or build_storage(settings)
        calls = ProviderCallService(
            session,
            settings,
            self._provider or build_provider(settings),
            self._registry or PromptRegistry(settings.provider.prompt_root),
        )
        scheme_criteria = MarkSchemeRepository(session).list_criteria(tenant_id, scheme.id)
        criteria_by_question: dict[str, list[Any]] = defaultdict(list)
        for criterion in scheme_criteria:
            criteria_by_question[criterion.question_id].append(criterion)

        leaves = _leaf_questions(structure)
        if not leaves:
            return PipelineOutcome(
                JobState.REVIEW_REQUIRED,
                {
                    "reason": "NO_SCOREABLE_QUESTIONS",
                    "message": "The blueprint has no scoreable questions.",
                },
            )

        # Imported criteria are inert until a person approves them against this
        # blueprint, and the scheme being APPROVED says nothing about them: an
        # approved scheme whose rows were never imported would otherwise be marked
        # with no criteria at all, silently.  The gate runs before anything is
        # paid for, and it is the only thing standing between "rows exist" and
        # "these rows decide marks".
        prepared = criteria_readiness(
            scheme_criteria,
            structure,
            blueprint_version_id=current.blueprint_version_id,
            approved_against=scheme.criteria_blueprint_version_id,
            approved_at=scheme.criteria_approved_at,
            approved_rules_hash=scheme.criteria_rules_hash,
        )
        if not prepared.ready:
            runs.record_run(
                session,
                job=current,
                stage=runs.STAGE_MARKING,
                outcome=runs.OUTCOME_REVIEW,
                detail={
                    "reason": prepared.reason,
                    "problems": list(prepared.problems)[:10],
                    "criteria_marks": prepared.total_marks,
                    "questions": prepared.questions,
                },
            )
            session.commit()
            return PipelineOutcome(
                JobState.REVIEW_REQUIRED,
                {
                    "reason": prepared.reason,
                    "problems": list(prepared.problems)[:10],
                    "questions": prepared.questions,
                    "message": (
                        "This scheme's imported criteria are not approved and complete for "
                        "this blueprint, so nothing was marked and no provider request was "
                        "made."
                    ),
                },
            )

        # The review mode is a property of the assignment, so the job reads it
        # from the tenant-scoped row rather than from a request body.
        assignment = session.get(Assignment, current.assignment_id)
        if assignment is not None and assignment.tenant_id != tenant_id:
            raise RuntimeError("the job references an assignment from another workspace")
        # The assignment is the authority; the configured mode is the fallback
        # for a submission whose assignment row predates review modes.  Without
        # this, `settings.marking.review_mode` would be a second, dead source of
        # truth that silently disagreed with the row.
        policy = sampling.policy_for(
            getattr(assignment, "review_mode", None) or settings.marking.review_mode,
            settings=settings,
        )

        submission_documents = DocumentRepository(session).list_for_submission(
            tenant_id, current.submission_id
        )
        processed_documents = [
            document for document in submission_documents if document.status == "PROCESSED"
        ]
        # A document that failed or never finished processing is not part of the
        # marked script at all.  Reading only the processed pages would turn its
        # answers into apparent blanks, so it is a blocking coverage gap.
        unprocessed_documents = [
            document for document in submission_documents if document.status != "PROCESSED"
        ]
        document_ids = [document.id for document in processed_documents]
        mapping_rows = (
            list(
                session.scalars(
                    select(PageQuestionMapping).where(
                        PageQuestionMapping.tenant_id == tenant_id,
                        PageQuestionMapping.document_id.in_(document_ids),
                        PageQuestionMapping.blueprint_version_id
                        == current.blueprint_version_id,
                    )
                )
            )
            if document_ids
            else []
        )
        # The mode is fixed on the job's first marking execution, and it decides
        # how much of the script one request can carry, so it is resolved before
        # coverage is judged.  A later configuration change applies to new papers
        # only: a resumed paper keeps the mode its rows were produced in, so one
        # paper can never switch strategies half way through.
        configured_mode = settings.marking.marking_mode
        if current.marking_mode is None:
            current.marking_mode = configured_mode
            session.commit()
        marking_mode = current.marking_mode
        coverage = page_coverage.assess_coverage(
            documents=processed_documents,
            pages=pages,
            mappings=mapping_rows,
            question_ids=[leaf[0] for leaf in leaves],
            page_cap=_coverage_page_cap(marking_mode, settings),
            unprocessed_documents=unprocessed_documents,
        )
        blocking_coverage = [finding for finding in coverage if finding.blocking]
        # A review-worthy coverage finding is attached to every stored question:
        # the award is kept as evidence, but it is never presented as if the whole
        # script had been read.
        coverage_messages = [finding.message for finding in coverage if finding.review]
        if blocking_coverage:
            # A page the document declares but storage does not hold may carry the
            # answer to a question.  Marking the pages that did arrive would turn a
            # missing page into an apparent blank, so nothing is marked and nothing
            # is charged to the provider.
            runs.record_run(
                session,
                job=current,
                stage=runs.STAGE_MARKING,
                outcome=runs.OUTCOME_REVIEW,
                detail={
                    "review_mode": policy.mode,
                    "blocked": blocking_coverage[0].code,
                    "messages": [finding.message for finding in blocking_coverage][:10],
                },
            )
            session.commit()
            return PipelineOutcome(
                JobState.REVIEW_REQUIRED,
                {
                    "reason": "PAGE_COVERAGE_INCOMPLETE",
                    "review_mode": policy.mode,
                    "review_reasons": [
                        finding.message for finding in blocking_coverage
                    ][:10],
                    "page_coverage": [
                        {"code": finding.code, "blocking": finding.blocking}
                        for finding in coverage
                    ],
                },
            )

        results = ResultRepository(session)
        quality = [page.quality_status for page in pages]
        working = _MarkingRun(
            session=session,
            job=current,
            settings=settings,
            structure=structure,
            criteria_by_question=criteria_by_question,
            readable=readable,
            calls=calls,
            storage=storage,
            quality=quality,
            engine_version=current.engine_version or CORRECTION_ENGINE_VERSION,
            policy=policy,
            marking_prompt_version=settings.marking.marking_prompt_version,
            marking_mode=marking_mode,
            page_cap=_coverage_page_cap(marking_mode, settings),
            coverage_messages=coverage_messages,
            leaf_by_question={leaf[0]: leaf for leaf in leaves},
            page_index=provenance.PageIndex.build(pages, processed_documents),
        )
        # Prompt provenance is per result row, so a mixed job cannot be detected
        # later by a single job field.  Check it before the first new request.
        working.assert_prompt_versions_stable(
            results.list_for_job(tenant_id, current.id)
        )
        working.assert_marking_mode_stable(results.list_for_job(tenant_id, current.id))

        # Coverage is re-evaluated on every execution.  A gap discovered since
        # the rows were written must reach those rows; a gap that has since
        # closed must stop flagging them, or a stale review would follow the
        # paper forever.  Only coverage concerns are touched.
        coverage_sync = _sync_coverage(
            session,
            current.id,
            results.list_for_job(tenant_id, current.id),
            coverage_messages,
            min_confidence=settings.marking.min_confidence,
        )
        if coverage_sync:
            session.commit()

        current.scheme_hash = _content_hash(scheme)
        current.submission_hash = self._submission_hash(session, tenant_id, current.submission_id)
        session.commit()

        created: list[uuid.UUID] = []
        unresolved: list[tuple[str, int, str | None, str]] = []

        # -- one request for the whole paper, when the deployment asks for it --
        # Only leaves without a decision are sent: a question this job already
        # decided keeps its award, so a resumed execution neither re-asks it nor
        # pays for it again.
        paper_detail: dict[str, Any] | None = None
        parallel_detail: dict[str, Any] | None = None
        if working.marking_mode == MODE_WHOLE_PAPER:
            targets = _paper_targets(leaves, results, current.id)
            if targets and self._cancelled(session, current.id):
                return PipelineOutcome(
                    JobState.CANCELLED, {"reason": "cancelled before marking"}
                )
            if targets:
                outcome = working.mark_paper(
                    targets,
                    existing={
                        leaf[0]: results.get_question(current.id, leaf[0])
                        for leaf in targets
                    },
                )
                paper_detail = outcome.detail
                created.extend(row.id for row in outcome.rows.values())
                paper_status = paper_detail.get("status")
                if paper_status == "SKIPPED" and paper_detail.get("reason") in {
                    "PAGES_EXCEED_REQUEST_CAP",
                    "TOO_MANY_QUESTIONS",
                }:
                    # The job is configured for whole-paper marking and this paper
                    # cannot be sent as one request.  It is refused here rather
                    # than quietly marked question by question: a run that fell
                    # back for this reason would report a complete paper that was
                    # never actually sent as one, and no rule asks for that.  No
                    # request has been made, so nothing is paid for or lost.
                    return PipelineOutcome(
                        JobState.REVIEW_REQUIRED,
                        {
                            "reason": paper_detail.get("reason"),
                            "message": (
                                "This paper does not fit one whole-paper request, so "
                                "it was refused before any provider call instead of "
                                "being marked per question under a whole-paper job."
                            ),
                            "questions": paper_detail.get("questions"),
                            "constraint": {
                                key: paper_detail.get(key)
                                for key in ("pages", "max_pages", "leaves", "max_leaves")
                                if paper_detail.get(key) is not None
                            },
                        },
                    )
                if paper_status == "PERSIST_FAILED":
                    # The reply is archived, so a retry rebuilds the rows from it
                    # without buying the paper again.
                    raise RetryablePipelineError(
                        "The whole-paper marking could not be stored; the reply is "
                        "archived, so a retry rebuilds it without another request."
                    )
                if paper_status == "ARCHIVE_FAILED":
                    # The paid reply is gone and the usage ledger remembers it, so
                    # this execution stops instead of silently paying twice.
                    raise RetryablePipelineError(
                        "The whole-paper reply could not be archived, so none of its "
                        "marks were kept; the paid attempt is recorded and is not "
                        "repeated."
                    )
                current.progress = 0.55
                session.commit()
                if self._cancelled(session, current.id):
                    self._discard(session, current.id, created)
                    return PipelineOutcome(
                        JobState.CANCELLED, {"reason": "cancelled during marking"}
                    )

        # -- independent questions corrected concurrently ------------------
        # The same per-question request and contract as the sequential path, with
        # the questions that share no dependency dispatched together.  Decided
        # questions are never re-sent: a resumed paper keeps its awards.
        if working.marking_mode == MODE_PARALLEL:
            parallel_targets = _paper_targets(leaves, results, current.id)
            if parallel_targets and self._cancelled(session, current.id):
                return PipelineOutcome(
                    JobState.CANCELLED, {"reason": "cancelled before marking"}
                )
            if parallel_targets:
                (
                    parallel_detail,
                    parallel_created,
                    parallel_unresolved,
                ) = self._mark_parallel(
                    session=session,
                    working=working,
                    results=results,
                    targets=parallel_targets,
                    current=current,
                )
                created.extend(parallel_created)
                unresolved.extend(parallel_unresolved)
                if parallel_detail.get("cancelled"):
                    self._discard(session, current.id, created)
                    return PipelineOutcome(
                        JobState.CANCELLED, {"reason": "cancelled during marking"}
                    )
                current.progress = 0.55
                session.commit()

        # The parallel pass has already addressed every open question, so the
        # sequential loop would only repeat its work — and would silently turn a
        # refused question into a second, non-parallel attempt.  It therefore runs
        # for the two sequential paths only (whole-paper uses it for the leaves
        # its reply did not decide).
        if working.marking_mode != MODE_PARALLEL:
            for index, leaf in enumerate(leaves):
                if self._cancelled(session, current.id):
                    self._discard(session, current.id, created)
                    return PipelineOutcome(
                        JobState.CANCELLED, {"reason": "cancelled during marking"}
                    )

                question_id = leaf[0]
                existing = results.get_question(current.id, question_id)
                if existing is not None and not _retryable(existing):
                    # A question with a decision keeps it: the (job, question)
                    # pair is the idempotency key, and re-marking a decided
                    # question would replace a decision with a second opinion.
                    continue

                row, failure = working.mark(leaf, existing=existing)
                if row is not None and row.id is not None:
                    created.append(row.id)
                if failure is not None:
                    unresolved.append(leaf)

                current.progress = min(
                    0.9, 0.55 + (index + 1) / max(len(leaves), 1) * 0.35
                )
                session.commit()

        recovery_detail = self._recover(
            session=session,
            working=working,
            results=results,
            leaves=leaves,
            unresolved=unresolved,
        )

        runs.record_run(
            session,
            job=current,
            stage=runs.STAGE_MARKING,
            outcome=runs.OUTCOME_OK,
            prompt_version=working.prompt_version,
            detail={
                "questions": len(leaves),
                "marked_rows": len(created),
                "unresolved": len(unresolved),
                "review_mode": policy.mode,
                "integrity_findings": list(dict.fromkeys(working.integrity_findings))[:20],
                "scheme_findings": list(dict.fromkeys(working.scheme_findings))[:20],
                "page_coverage": [
                    {"code": finding.code, "blocking": finding.blocking}
                    for finding in coverage
                ],
                "prompt_versions": working.prompt_versions,
                "marking_mode": working.marking_mode,
                "configured_marking_mode": configured_mode,
                # The complete reply is archived here, once per paper, so the
                # request can be re-read after the per-row slices are normalised.
                "whole_paper": paper_detail,
                # The parallel pass records its plan, waves, concurrency and every
                # failed question, so the run is auditable without the workers.
                "parallel": parallel_detail,
            },
        )
        if recovery_detail is not None:
            runs.record_run(
                session,
                job=current,
                stage=runs.STAGE_RECOVERY,
                outcome=(
                    runs.OUTCOME_OK
                    if recovery_detail["still_unresolved"] == 0
                    else runs.OUTCOME_REVIEW
                ),
                prompt_version=working.prompt_version,
                detail=recovery_detail,
            )
        session.commit()

        runs.record_run(
            session,
            job=current,
            stage=runs.STAGE_INTEGRITY,
            outcome=(
                runs.OUTCOME_REVIEW
                if working.integrity_findings
                or working.scheme_findings
                or working.coverage_messages
                else runs.OUTCOME_OK
            ),
            prompt_version=working.prompt_version,
            detail={
                "count": len(working.integrity_findings),
                "findings": list(dict.fromkeys(working.integrity_findings))[:20],
                "scheme_findings": list(dict.fromkeys(working.scheme_findings))[:20],
                "page_coverage": [
                    {"code": finding.code, "blocking": finding.blocking}
                    for finding in coverage
                ],
            },
        )
        session.commit()

        if self._cancelled(session, current.id):
            self._discard(session, current.id, created)
            return PipelineOutcome(JobState.CANCELLED, {"reason": "cancelled during marking"})

        rows = results.list_for_job(tenant_id, current.id)
        transcription_detail = self._transcribe(working, rows)
        if transcription_detail is not None:
            rows = results.list_for_job(tenant_id, current.id)
        # Cancellation must be observed between verification stages too: a
        # cancelled job may not keep spending requests, and the rows it produced
        # are discarded exactly as they are during marking.
        if self._cancelled(session, current.id):
            self._discard(session, current.id, created)
            return PipelineOutcome(
                JobState.CANCELLED, {"reason": "cancelled during verification"}
            )
        double_check = self._double_check(working, rows)
        if self._cancelled(session, current.id):
            self._discard(session, current.id, created)
            return PipelineOutcome(
                JobState.CANCELLED, {"reason": "cancelled during verification"}
            )
        if double_check is not None:
            rows = results.list_for_job(tenant_id, current.id)

        # -- evidence gate ----------------------------------------------------
        # A mark whose evidence was never compared with the script is not a
        # verified mark.  The comparison is bought only for the questions the
        # review mode selects, so without this gate a run can finish with every
        # award resting on an unread page — which is how a full-marks award for
        # an answer that was not on the page reached a teacher as an unflagged
        # result (STUDENT_02, Q37b).  Nothing is deducted and no award is
        # changed: the question is sent to a person instead of being presented
        # as decided.
        ungrounded = (
            verification_completeness.awards_without_evidence(
                rows,
                verification_completeness.records_from_rows(
                    results.verifications(current.id)
                ),
            )
            if settings.marking.require_evidence_for_award
            else ()
        )
        if ungrounded:
            by_question = {str(row.question_id): row for row in rows}
            for question_id in ungrounded:
                row = by_question.get(question_id)
                if row is None:
                    continue
                _with_concern(
                    row,
                    code=verification_completeness.CODE_EVIDENCE_NOT_CHECKED,
                    severity=SEVERITY_POSSIBLE,
                    message=(
                        f"{int(row.awarded_marks or 0)} mark(s) are recorded here and "
                        "no check has compared this question's quoted evidence with "
                        "the script, so the award rests on an unverified reading. "
                        "The award was not changed; a person must confirm what is "
                        "written on the page."
                    ),
                )
                row.review_required = True
                row.status = status_for(ProcessingState.NEEDS_REVIEW)
                row.processing_state = ProcessingState.NEEDS_REVIEW.value
            session.commit()
        evidence_gate = {
            "enabled": settings.marking.require_evidence_for_award,
            "questions": len(rows),
            "unverified_awards": len(ungrounded),
            "ungrounded": list(ungrounded)[:20],
        }

        # Every scoreable leaf must have a row.  A leaf with no row is not a zero
        # and not a review item: it is an omission, and a paper whose marks do
        # not add up to the leaves it claims to have marked must not present
        # itself as complete.
        # -- deterministic paper aggregation --------------------------------
        # Parallel execution makes per-question completion observable, so the
        # totals are recomputed from the stored rows in blueprint order.  A paper
        # is complete only when every scoreable leaf has exactly one row and no
        # award exceeds its validated maximum; a total that does not add up is
        # never presented as a finished correction.
        parallel_totals = (
            parallel.aggregate(parallel.build_plan(leaves), rows)
            if working.marking_mode == MODE_PARALLEL
            else None
        )
        missing = omitted_leaves(leaves, rows)
        inconsistency = parallel_totals is not None and not parallel_totals.complete
        if missing or inconsistency:
            reason = (
                "MISSING_SCOREABLE_LEAF"
                if missing
                else "PARALLEL_AGGREGATION_INCOMPLETE"
            )
            detail = {
                "questions": len(leaves),
                "omitted": missing[:20],
                "omitted_count": len(missing),
                "review_mode": policy.mode,
                "marking_mode": working.marking_mode,
                "parallel": parallel_detail,
                "parallel_aggregation": (
                    parallel_totals.describe() if parallel_totals is not None else None
                ),
            }
            runs.record_run(
                session,
                job=current,
                stage=runs.STAGE_INTEGRITY,
                outcome=runs.OUTCOME_REVIEW,
                detail={"reason": reason, **detail},
            )
            session.commit()
            return PipelineOutcome(
                JobState.REVIEW_REQUIRED,
                {
                    "reason": reason,
                    "message": (
                        "Part of the paper has no stored decision, so the marks "
                        "cannot be presented as a complete paper."
                        if missing
                        else "The stored decisions do not aggregate into a "
                        "consistent paper, so no total was presented."
                    ),
                    **detail,
                },
            )
        review_reasons = review_reasons_for(rows)

        marked = sum(1 for row in rows if is_scoreable(row.processing_state))
        detail = {
            "questions": len(leaves),
            "marked": marked,
            "unmarked": sum(1 for row in rows if not is_scoreable(row.processing_state)),
            "review_mode": policy.mode,
            "review_reasons": review_reasons[:20],
            "scheme_findings": list(dict.fromkeys(working.scheme_findings))[:20],
            "transcription": transcription_detail,
            "double_check": double_check,
            "evidence_gate": evidence_gate,
            "marking_mode": working.marking_mode,
            "parallel": parallel_detail,
            "parallel_aggregation": (
                parallel_totals.describe() if parallel_totals is not None else None
            ),
            "page_coverage": [
                {"code": finding.code, "blocking": finding.blocking}
                for finding in coverage
            ],
            "coverage_sync": coverage_sync,
        }

        # A reply the pipeline could not parse, or a mark that failed its
        # integrity check, means this run did not validate its own output.  The
        # guard must see that instead of judging the run on totals alone.
        # A transcription disagreement is a failure of this run's own reading, so
        # it fails validation exactly as an integrity finding does: a later stage
        # that happens to balance arithmetically cannot hide it.
        validation_failed = validation_failed_for(
            rows, working.integrity_findings
        ) or bool(transcription_detail and transcription_detail.get("differences"))
        # A teacher can cancel while the last stage is finishing.  The guard is the
        # point after which the run would start presenting itself, so a cancelled
        # job must not reach it: its rows are discarded like every other stage's.
        if self._cancelled(session, current.id):
            self._discard(session, current.id, created)
            return PipelineOutcome(
                JobState.CANCELLED, {"reason": "cancelled before the result guard"}
            )
        guard = self._apply_guard(
            session=session,
            current=current,
            rows=rows,
            validation_failed=validation_failed,
        )

        # Verification completeness is derived from what was actually recorded,
        # independently of whether the paper's marks are complete.  It is stored
        # on the job so a later reader cannot mistake "completed" for "fully
        # verified".
        paper_verification = verification_completeness.summarise(
            rows, verification_completeness.records_from_rows(results.verifications(current.id))
        )
        detail["verification"] = paper_verification.describe()
        current.verification_status = paper_verification.status
        if guard is not None:
            # The guard refused to present this run.  The marks may be fully
            # verified, but the result is not the paper's result, so a person
            # decides; presenting it as verified would be false.  A run whose
            # verification already failed keeps that stronger, more specific
            # fact: refusing the marks does not make the contradiction go away.
            if (
                current.verification_status
                != verification_completeness.STATUS_VERIFICATION_FAILED
            ):
                current.verification_status = (
                    verification_completeness.STATUS_REVIEW_REQUIRED
                )
            detail["verification"]["status"] = current.verification_status
            session.commit()
            detail["guard"] = guard
            detail["guard_reason"] = guard_reason_summary(guard)
            return PipelineOutcome(JobState.REVIEW_REQUIRED, detail)
        session.commit()

        if review_reasons:
            return PipelineOutcome(JobState.REVIEW_REQUIRED, detail)
        return PipelineOutcome(JobState.FINALIZING, detail)

    # -- stages ----------------------------------------------------------
    def _recover(
        self,
        *,
        session: Session,
        working: _MarkingRun,
        results: ResultRepository,
        leaves: list[tuple[str, int, str | None, str]],
        unresolved: list[tuple[str, int, str | None, str]],
    ) -> dict[str, Any] | None:
        """Retry unusable replies within a bounded, recorded budget."""

        if not unresolved:
            return None
        current = working.job
        missing = [leaf[0] for leaf in unresolved]
        allowed, refusal = recovery.need_recovery(
            missing=missing,
            already_attempted=current.recovery_rounds,
            max_rounds=working.policy.recovery_rounds,
        )
        plan = recovery.plan_recovery(
            missing=missing,
            already_attempted=current.recovery_rounds,
            scheme_questions=len(leaves),
        )
        blocked = refusal or plan.blocked_reason

        recovered = 0
        covered = 0
        chunks_run = 0
        last_error: str | None = None

        if allowed:
            for chunk in plan.chunks:
                if self._cancelled(session, current.id):
                    break
                current.recovery_rounds += 1
                chunks_run += 1
                covered += len(chunk.questions)
                for question_id in chunk.questions:
                    leaf = next(item for item in unresolved if item[0] == question_id)
                    existing = results.get_question(current.id, question_id)
                    try:
                        # The job's selected mode is the provenance of the row;
                        # a recovery request is one sequential per-question call,
                        # which the recovery run record states separately.
                        row, failure = working.mark(
                            leaf, existing=existing, source=working.marking_mode
                        )
                    except RetryablePipelineError:
                        # A provider outage during recovery is the same outage:
                        # the runner parks the job and the budget is intact.
                        raise
                    if failure is not None:
                        last_error = failure
                        continue
                    if row is not None and is_scoreable(row.processing_state):
                        recovered += 1
                session.commit()

        still_unresolved = 0
        for question_id in missing:
            row = results.get_question(current.id, question_id)
            if row is None or is_scoreable(row.processing_state):
                continue
            still_unresolved += 1
            reason = recovery.unresolved_reason(
                chunks_run=chunks_run,
                questions_covered=covered,
                recovered=recovered,
                blocked_reason=blocked,
                error=last_error,
            )
            concerns = [
                concern
                for concern in (row.scheme_concerns or [])
                if concern.get("code") != "RECOVERY_EXHAUSTED"
            ]
            concerns.append({"code": "RECOVERY_EXHAUSTED", "message": reason})
            row.scheme_concerns = concerns
            row.status = status_for(ProcessingState.NEEDS_REVIEW)
            row.processing_state = ProcessingState.NEEDS_REVIEW.value
            row.review_required = True
        session.flush()
        session.commit()

        return {
            "missing": len(missing),
            "chunks": chunks_run,
            "questions_covered": covered,
            "recovered": recovered,
            "still_unresolved": still_unresolved,
            "blocked_reason": blocked,
            "deferred": list(plan.deferred),
            # The job's mode and the mechanism of these requests are different
            # facts: the paper is still the mode it was created for, while each
            # recovery request is a sequential per-question call.
            "mode": working.marking_mode,
            "execution": "SEQUENTIAL",
            "request_source": working.marking_mode,
        }

    # -- parallel mode ----------------------------------------------------
    def _mark_parallel(
        self,
        *,
        session: Session,
        working: _MarkingRun,
        results: ResultRepository,
        targets: list[tuple[str, int, str | None, str]],
        current: CorrectionJob,
    ) -> tuple[dict[str, Any], list[uuid.UUID], list[tuple[str, int, str | None, str]]]:
        """Correct the open questions concurrently, persisting on this thread.

        The shape is deliberate:

        * inputs are built by each worker from its own replica, at the moment the
          task is dispatched, so a dependent sub-question sees the earlier part
          that was accepted in the previous wave;
        * each worker opens its own session and call service, so the provider's
          usage row and credential lease are written on its own connection;
        * the reply comes back to this thread, where ``accept`` parses, validates
          and persists it — one question at a time, in blueprint order — so
          concurrent replies cannot interleave inside one transaction.

        Concurrency is bounded and the same credential pool, project cooldown and
        append-only ledger apply to every request.  A question that fails is
        recorded as failed and does not cancel the rest of the paper.
        """

        plan = parallel.build_plan(targets)
        detail: dict[str, Any] = {"plan": plan.describe()}
        if plan.duplicates:
            raise AppError(
                ErrorCode.CONFIGURATION_ERROR,
                "The blueprint names the same question more than once, so a "
                "parallel pass could persist two decisions for it.",
                details={"duplicates": list(plan.duplicates)},
            )
        if not plan.tasks:
            return detail, [], []

        leaf_by_id = {leaf[0]: leaf for leaf in targets}
        existing = {
            task.question_id: results.get_question(current.id, task.question_id)
            for task in plan.tasks
        }

        # One prompt-version row is created on this thread before any worker
        # starts: concurrent workers would otherwise race to insert the same
        # (prompt, version) pair and one of them would fail on the unique key.
        asset = working.calls.registry.load(
            PROMPT_MARKING, working.marking_prompt_version
        )
        working.calls.prompt_versions.get_or_create(
            prompt_id=asset.prompt_id,
            version=asset.version,
            content_hash=asset.content_hash,
            path=asset.path,
            model_role=asset.model_role,
        )
        session.commit()

        bind = session.get_bind()
        if not isinstance(bind, Engine):
            raise AppError(
                ErrorCode.CONFIGURATION_ERROR,
                "Parallel correction needs a job session bound to a database "
                "engine; a session bound to one shared connection would run the "
                "questions sequentially while reporting them as parallel.",
            )
        factory = sessionmaker(bind=bind, expire_on_commit=False)
        # Quota is counted in the database; this lock makes the read-and-reserve
        # of one lease atomic across this process's worker threads.
        acquire_lock = threading.Lock()
        provider = working.calls.provider
        registry = working.calls.registry
        settings = working.settings
        created: list[uuid.UUID] = []
        unresolved: list[tuple[str, int, str | None, str]] = []

        def request(task: parallel.QuestionTask) -> Any:
            worker_session = factory()
            try:
                calls = ProviderCallService(
                    worker_session,
                    settings,
                    provider,
                    registry,
                    acquire_lock=acquire_lock,
                )
                replica = working.replica(worker_session, calls)
                try:
                    call = replica.call_model(
                        leaf_by_id[task.question_id],
                        prompt_id=PROMPT_MARKING,
                        purpose="marking",
                    )
                except RetryablePipelineError as error:
                    return parallel.RequestFailure(
                        "RetryablePipelineError",
                        str(error),
                        retryable=True,
                    )
                except AppError as error:
                    return parallel.RequestFailure(
                        type(error).__name__,
                        str(error),
                        retryable=error.code in _RETRYABLE,
                    )
                return call, replica.prompt_version
            finally:
                worker_session.close()

        def accept(task: parallel.QuestionTask, reply: Any) -> parallel.TaskOutcome:
            if isinstance(reply, parallel.RequestFailure):
                # Only a retryable failure is offered to the recovery budget.
                # A refusal the provider would repeat is not retried: the run
                # records it, the question stays undecided, and the paper cannot
                # be presented as complete.
                if reply.retryable:
                    unresolved.append(leaf_by_id[task.question_id])
                return parallel.TaskOutcome(
                    question_id=task.question_id,
                    status=parallel.STATUS_FAILED,
                    detail={
                        "error_class": reply.error_class,
                        "message": reply.message,
                        "retryable": reply.retryable,
                    },
                )
            call, prompt_version = reply
            try:
                row, failure = working.accept(
                    leaf=leaf_by_id[task.question_id],
                    call=call,
                    existing=existing[task.question_id],
                    source=MODE_PARALLEL,
                    prompt_version=prompt_version,
                )
            except Exception:
                # Leave the session usable for the remaining questions.  A failed
                # transaction here must not cascade into every later acceptance.
                session.rollback()
                raise
            if row is not None and row.id is not None:
                created.append(row.id)
            if failure is not None:
                # The reply was paid for and stored as unusable; recovery decides
                # later whether another attempt is within its budget.
                unresolved.append(leaf_by_id[task.question_id])
                return parallel.TaskOutcome(
                    question_id=task.question_id,
                    status=parallel.STATUS_UNUSABLE,
                    detail={"reason": failure[:200]},
                )
            session.commit()
            return parallel.TaskOutcome(
                question_id=task.question_id,
                status=parallel.STATUS_ACCEPTED,
                detail={
                    "awarded": int(row.awarded_marks or 0) if row else None,
                    # Per-question cost evidence: the provider's own time and the
                    # time this question waited for a lease.  Both are also stored
                    # on the append-only usage row the call produced.
                    "latency_ms": getattr(call.response, "latency_ms", None),
                    "queue_wait_ms": getattr(call, "queue_wait_ms", None),
                },
            )

        execution = parallel.execute(
            plan,
            request=request,
            accept=accept,
            max_concurrency=max(1, int(settings.marking.parallel_max_concurrency)),
            should_stop=lambda: self._cancelled(session, current.id),
        )
        detail.update(execution.describe())
        detail["concurrency"] = max(1, int(settings.marking.parallel_max_concurrency))
        detail["cancelled"] = execution.cancelled
        accepted = [
            outcome for outcome in execution.outcomes.values() if outcome.accepted
        ]
        detail["provider_latency_ms_total"] = sum(
            int(outcome.detail.get("latency_ms") or 0) for outcome in accepted
        )
        detail["queue_wait_ms_total"] = sum(
            int(outcome.detail.get("queue_wait_ms") or 0) for outcome in accepted
        )

        if not execution.cancelled and execution.requested and not created:
            # Nothing at all reached the database: the paper is not marked, so the
            # job parks honestly instead of presenting an empty run.
            failures = execution.failures()
            if failures and all(failure.detail.get("retryable") for failure in failures):
                raise RetryablePipelineError(
                    "Every parallel question request failed before a reply could be "
                    "stored; nothing was marked and the paper is retried later."
                )
            raise AppError(
                ErrorCode.PROVIDER_UNAVAILABLE,
                "No question of this paper could be corrected: every request "
                "failed and nothing was stored.",
                details={"failures": [failure.detail for failure in failures][:10]},
            )

        return detail, created, unresolved

    # -- independent double check -----------------------------------------
    def _transcribe(
        self, working: _MarkingRun, rows: list[QuestionResult]
    ) -> dict[str, Any] | None:
        """A blind second reading of selected answers.  It never re-marks.

        The reader sees the pages and the question, not the marks, the scheme or
        the answer the first pass extracted.  A difference is evidence that the
        extraction is unproven; the award stays as recorded and a person decides.
        A question whose pages cannot be established — or whose images would
        exceed the request budget — is recorded as unavailable rather than sent
        an arbitrary page or the whole script.  An unavailable reading is never
        agreement: the zero it would have checked goes to a person.
        """

        settings = working.settings
        policy = working.policy
        session = working.session
        current = working.job
        if not settings.marking.transcription_enabled or policy.transcription_budget <= 0:
            # A skipped stage is recorded, not merely absent: an auditor must be
            # able to tell "not bought" from "crashed before recording".
            runs.record_run(
                session,
                job=current,
                stage=runs.STAGE_TRANSCRIPTION,
                outcome=runs.OUTCOME_SKIPPED,
                detail={
                    "reason": (
                        "transcription is disabled by configuration"
                        if not settings.marking.transcription_enabled
                        else f"review mode {policy.mode} buys no independent reading"
                    ),
                    **policy.describe(),
                },
            )
            session.commit()
            return None
        existing = set(
            session.scalars(
                select(VerificationResult.question_id).where(
                    VerificationResult.job_id == current.id,
                    VerificationResult.kind == "TRANSCRIPTION",
                )
            )
        )
        # What the marking pass claims to have read, per question: its recorded
        # answer and every quotation it awarded against.  A question with no
        # answer line has only quotations, which is exactly the shape of the Q6
        # defect.  Built before selection because those readings are themselves
        # risk evidence: a bare number quoted as the final answer of a zero, or a
        # long signed sum with no bracket, is where a misread hides.
        quotes: dict[str, list[str]] = {}
        row_ids = [row.id for row in rows]
        if row_ids:
            for stored in session.scalars(
                select(MarkingEvidence).where(
                    MarkingEvidence.question_result_id.in_(row_ids),
                    MarkingEvidence.kind == "QUOTE",
                )
            ):
                owner = next(
                    (row for row in rows if row.id == stored.question_result_id), None
                )
                if owner is not None and (stored.quote or "").strip():
                    quotes.setdefault(owner.question_id, []).append(stored.quote or "")
        # One ranking, so the questions that are selected and the ones that are
        # not are ordered by the same evidence and the run can report both.
        ranking = transcription.rank_transcription_targets(
            rows, readings=quotes, skip=existing
        )
        targets = ranking[: policy.transcription_budget]

        counts = {
            "agreements": 0,
            "differences": 0,
            "absent": 0,
            "unverifiable": 0,
            "not_independent": 0,
            "unknown_independence": 0,
            "unavailable": 0,
            "page_unverified": 0,
            "unverified_award": 0,
            "evidence_failures": 0,
            "evidence_unverified": 0,
        }
        if not targets:
            return {
                "enabled": True,
                "checked": 0,
                "disagreements": [],
                **counts,
            }

        disagreements: list[str] = []
        page_sources: dict[str, dict[str, object]] = {}
        prompt_version: str | None = None
        by_id = {row.question_id: row for row in rows}
        pages_by_id = {str(page.id): page for page in working.readable}
        mapped, cited, owners = working._transcription_page_maps(rows)
        page_limit = int(settings.marking.transcription_max_pages)
        request_cap = transcription.TRANSCRIPTION_REQUEST_MAX_PAGES
        # All the models that marked anything in this job, and the one that
        # produced each question's accepted reply: independence is decided from
        # those identities, never from the configured chain.
        marking_models, marking_model_by_question = working.marking_model_identities(
            rows
        )
        for target in targets:
            if self._cancelled(session, current.id):
                break
            row = by_id.get(target.question_id)
            leaf = working.leaf_by_question.get(target.question_id)
            if row is None or leaf is None:
                continue
            recorded = transcription.recorded_readings(
                row.student_answer, quotes.get(target.question_id, ())
            )
            if page_limit > request_cap:
                # Configuration validation rejects this, and a deployment that
                # bypassed it must not be served by silently dropping pages.
                selection = transcription.PageSelection(
                    page_ids=(),
                    page_indices=(),
                    source=transcription.PAGE_SOURCE_UNAVAILABLE,
                    reason=(
                        f"CONFIGURATION_EXCEEDS_REQUEST_CAP:{page_limit}>{request_cap}"
                    ),
                )
            else:
                selection = transcription.resolve_transcription_pages(
                    target.question_id,
                    pages=working.readable,
                    mapped=mapped,
                    citations=cited,
                    owners=owners,
                    max_pages=page_limit,
                )
            page_sources[target.question_id] = selection.as_dict()
            unavailable: str | None = (
                None if selection.available else (selection.reason or "NO_PAGE_MAPPING")
            )
            inputs: tuple[LLMInput, ...] | None = None
            if unavailable is None:
                chosen = [
                    pages_by_id[page_id]
                    for page_id in selection.page_ids
                    if page_id in pages_by_id
                ]
                if not chosen:
                    unavailable = "NO_PAGE_IMAGE"
                else:
                    inputs = working._transcription_inputs(leaf, pages=chosen)
                    image_bytes = sum(len(part.image or b"") for part in inputs)
                    budget_bytes = settings.marking.transcription_max_image_bytes
                    if image_bytes > budget_bytes:
                        unavailable = (
                            f"IMAGE_PAYLOAD_EXCEEDED:{image_bytes}>{budget_bytes}"
                        )
                        inputs = None
            if unavailable is not None or inputs is None:
                # No request is spent on a question nobody can locate, and the
                # question is not silently accepted either: the reading is
                # recorded as unavailable and the award goes to a person.
                counts["unavailable"] += 1
                working._persist_verifications(
                    row.question_id,
                    VerificationOutcome(review_required=False, reasons=[], records=[]),
                    [
                        VerificationRecord(
                            kind="TRANSCRIPTION",
                            status="UNVERIFIABLE",
                            detail={
                                "status": "UNAVAILABLE",
                                "reason": unavailable,
                                "page_source": selection.source,
                                "pages": list(selection.page_indices),
                                "original_answer": row.student_answer,
                                "recorded": recorded,
                                "selection": list(target.reasons),
                                "ranking": {
                                    "rank": target.rank,
                                    "score": target.score,
                                    "signals": list(target.signals),
                                },
                            },
                        )
                    ],
                )
                _with_concern(
                    row,
                    code="TRANSCRIPTION_UNAVAILABLE",
                    severity=SEVERITY_POSSIBLE,
                    message=(
                        "An independent reading of this question could not be "
                        f"taken ({unavailable}). The award rests on an unverified "
                        "extraction, so a person must confirm what is written."
                    ),
                )
                row.review_required = True
                row.status = status_for(ProcessingState.NEEDS_REVIEW)
                row.processing_state = ProcessingState.NEEDS_REVIEW.value
                session.commit()
                continue
            try:
                call = working.call_model(
                    leaf,
                    prompt_id=PROMPT_TRANSCRIPTION,
                    purpose="transcription",
                    inputs=inputs,
                    response_schema=TRANSCRIPTION_RESPONSE_SCHEMA,
                    max_output_tokens=2048,
                )
            except AppError as error:
                # No model is permitted to read a script blindly, so the reading
                # was not bought.  That is a fact about this run, not a reason to
                # discard a paper that was already marked: the question is
                # recorded as unverified and sent to a person, exactly as an
                # unlocatable page is.  Silently borrowing the marking model here
                # would make the "independent" reading the same model that
                # produced the marks.
                if error.code in _RETRYABLE:
                    raise RetryablePipelineError(str(error)) from error
                unavailable = f"TRANSCRIPTION_UNAVAILABLE:{error.code.value}"
                counts["unavailable"] += 1
                working._persist_verifications(
                    row.question_id,
                    VerificationOutcome(review_required=False, reasons=[], records=[]),
                    [
                        VerificationRecord(
                            kind="TRANSCRIPTION",
                            status="UNVERIFIABLE",
                            detail={
                                "status": "UNAVAILABLE",
                                "reason": unavailable,
                                "message": str(error)[:400],
                                "page_source": selection.source,
                                "pages": list(selection.page_indices),
                                "original_answer": row.student_answer,
                                "recorded": recorded,
                                "selection": list(target.reasons),
                            },
                        )
                    ],
                )
                _with_concern(
                    row,
                    code="TRANSCRIPTION_UNAVAILABLE",
                    severity=SEVERITY_POSSIBLE,
                    message=(
                        "An independent reading of this question could not be "
                        "taken, because no model is permitted to perform it. "
                        "The award rests on an unverified extraction, so a "
                        "person must confirm what is written. "
                        f"{error.message}"
                    ),
                )
                row.review_required = True
                row.status = status_for(ProcessingState.NEEDS_REVIEW)
                row.processing_state = ProcessingState.NEEDS_REVIEW.value
                session.commit()
                continue
            if prompt_version is None:
                version = getattr(call.prompt, "version", None)
                prompt_version = (
                    f"{PROMPT_TRANSCRIPTION}:v{version}"
                    if version is not None
                    else PROMPT_TRANSCRIPTION
                )
            transcript: str | None = None
            confidence: float | None = None
            evidence_status = "WRITTEN"
            try:
                payload = parse_json_text(call.response.text)
                if not isinstance(payload, dict):
                    raise ValueError("the transcription reply is not a JSON object")
                declared = payload.get("evidence_status")
                if declared is not None:
                    if str(declared).strip().upper() not in _EVIDENCE_STATUSES:
                        raise ValueError(
                            "the transcription reply's evidence_status is unknown"
                        )
                    evidence_status = str(declared).strip().upper()
                raw = payload.get("transcript")
                if raw is not None and not isinstance(raw, str):
                    raise ValueError("the transcription reply's transcript is not text")
                transcript = raw
                confidence = float(payload.get("confidence") or 0.0)
            except (TypeError, ValueError):
                transcript = None
                evidence_status = "ILLEGIBLE"
            # A reader that says nothing is written and then transcribes
            # something, or says work is written and returns nothing, has
            # contradicted itself; neither reply can verify a mark.
            if evidence_status == "ABSENT" and (transcript or "").strip():
                evidence_status = "ILLEGIBLE"
            if evidence_status == "WRITTEN" and not (transcript or "").strip():
                evidence_status = "ILLEGIBLE"

            if evidence_status == "ILLEGIBLE":
                comparison = transcription_compare.Comparison(
                    transcription.STATUS_UNVERIFIABLE
                )
            else:
                comparison = transcription_compare.compare_readings(recorded, transcript)
            status = comparison.status
            # The quotation is checked against the reading that was taken
            # without the scheme or the award.  This costs no extra request and
            # answers exactly one question: is the quoted text in the script?
            evidence_checks = evidence_check.check_quotes(
                quotes.get(target.question_id, ()),
                transcript,
                evidence_status=evidence_status,
            )
            evidence_verdict = evidence_check.verdict(evidence_checks)
            page_confidence = transcription.page_confidence(selection.source)
            marking_model = (
                marking_model_by_question.get(target.question_id, "")
                or (current.primary_model or "").strip()
            )
            answering_model = (call.response.model or "").strip()
            # The identity of the model that actually answered decides whether
            # this is an independent reading: a different model is independent, a
            # marking model is only a prompt check, and an unreported model is
            # unknown rather than assumed.
            independence = transcription.classify_independence(
                answering_model, marking_models
            )
            if independence == transcription.INDEPENDENCE_PROMPT:
                counts["not_independent"] += 1
            if independence == transcription.INDEPENDENCE_UNKNOWN:
                counts["unknown_independence"] += 1
            working._persist_verifications(
                row.question_id,
                VerificationOutcome(review_required=False, reasons=[], records=[]),
                [
                    VerificationRecord(
                        kind="EVIDENCE",
                        status=evidence_verdict,
                        detail={
                            "quotes": [item.describe() for item in evidence_checks][:20],
                            "quote_count": len(evidence_checks),
                            "evidence_status": evidence_status,
                            "comparison": status,
                            "page_source": selection.source,
                            "pages": list(selection.page_indices),
                            "model": call.response.model,
                            "usage_id": str(call.usage_id) if call.usage_id else None,
                        },
                    ),
                    VerificationRecord(
                        kind="TRANSCRIPTION",
                        status=status,
                        detail={
                            "original_answer": row.student_answer,
                            "recorded": recorded,
                            "transcript": transcript,
                            "evidence_status": evidence_status,
                            "confidence": confidence,
                            "comparison": status,
                            "differences": [
                                difference.as_dict()
                                for difference in comparison.differences
                            ],
                            "independence": independence,
                            "marking_model": marking_model,
                            "marking_models": sorted(marking_models),
                            "selection": list(target.reasons),
                            "ranking": {
                                "rank": target.rank,
                                "score": target.score,
                                "signals": list(target.signals),
                            },
                            "page_source": selection.source,
                            "page_confidence": page_confidence,
                            "pages": list(selection.page_indices),
                            "model": call.response.model,
                            "prompt_version": prompt_version,
                            "usage_id": str(call.usage_id) if call.usage_id else None,
                            # The reply as it arrived, so the finding can be
                            # audited without the provider's logs.
                            "raw_response": call.response.text,
                        },
                    )
                ],
            )
            if independence != transcription.INDEPENDENCE_MODEL:
                # Two calls to one model with different wording is not an
                # independent reading; an unreported model cannot be shown to be
                # one either.  The check is recorded as what it is.
                if independence == transcription.INDEPENDENCE_PROMPT:
                    _with_concern(
                        row,
                        code="TRANSCRIPTION_NOT_INDEPENDENT",
                        severity=SEVERITY_POSSIBLE,
                        message=(
                            "The second reading was given by "
                            f"{answering_model or 'the model that marked this paper'}, "
                            "which is not independent of the marking pass: it verifies "
                            "the prompt, not the reading. A person must confirm the "
                            "transcription."
                        ),
                    )
                else:
                    _with_concern(
                        row,
                        code="TRANSCRIPTION_INDEPENDENCE_UNKNOWN",
                        severity=SEVERITY_POSSIBLE,
                        message=(
                            "The provider did not report which model produced the "
                            "second reading, so this run cannot show that the reading "
                            "is independent of the marking pass. A person must confirm "
                            "the transcription."
                        ),
                    )
                row.review_required = True
                row.status = status_for(ProcessingState.NEEDS_REVIEW)
                row.processing_state = ProcessingState.NEEDS_REVIEW.value
            awarded = int(row.awarded_marks or 0)
            if status == transcription.STATUS_AGREES:
                counts["agreements"] += 1
            elif status == transcription.STATUS_ABSENT:
                counts["absent"] += 1
            elif status == transcription.STATUS_DIFFERS:
                counts["differences"] += 1
                disagreements.append(row.question_id)
            else:
                counts["unverifiable"] += 1
            # The outcome policy is a pure function so it can be read and tested
            # without a provider: it names every concern this outcome raises, and
            # nothing else in this loop can raise one.
            concerns = transcription.outcome_concerns(
                status, awarded=awarded, page_confidence=page_confidence
            )
            if awarded and (
                transcription.CONCERN_UNVERIFIED in concerns
                or transcription.CONCERN_NO_READING in concerns
            ):
                counts["unverified_award"] += 1
            if transcription.CONCERN_PAGE_UNVERIFIED in concerns:
                counts["page_unverified"] += 1
            for code in concerns:
                severity, message = _transcription_concern(
                    code,
                    awarded=awarded,
                    kinds=", ".join(comparison.kinds) or "DIFFERENT_READING",
                    recorded=recorded,
                    transcript=transcript,
                    source=selection.source,
                )
                _with_concern(row, code=code, severity=severity, message=message)
            if concerns:
                # One concern is enough to put the question in front of a person.
                # The award, the student answer and the evidence are untouched: a
                # transcription can only add a reason to look.
                row.review_required = True
                row.status = status_for(ProcessingState.NEEDS_REVIEW)
                row.processing_state = ProcessingState.NEEDS_REVIEW.value
            if evidence_verdict == evidence_check.STATUS_FAIL:
                # The award cites text the independent reading of that page does
                # not contain.  That is a contradiction, not a style difference.
                counts["evidence_failures"] += 1
                _with_concern(
                    row,
                    code="EVIDENCE_NOT_FOUND",
                    severity=SEVERITY_DEFINITE,
                    message=(
                        "At least one quotation this question awarded marks against "
                        "was not found in the independent reading of its page. The "
                        "award was not changed; a person must confirm the evidence or "
                        "the mark."
                    ),
                )
                row.review_required = True
                row.status = status_for(ProcessingState.NEEDS_REVIEW)
                row.processing_state = ProcessingState.NEEDS_REVIEW.value
            elif evidence_verdict == evidence_check.STATUS_UNVERIFIABLE and awarded:
                counts["evidence_unverified"] += 1
                _with_concern(
                    row,
                    code="EVIDENCE_UNVERIFIED",
                    severity=SEVERITY_POSSIBLE,
                    message=(
                        "The evidence behind this award could not be checked against "
                        "an independent reading, so the quotation is unverified."
                    ),
                )
                row.review_required = True
                row.status = status_for(ProcessingState.NEEDS_REVIEW)
                row.processing_state = ProcessingState.NEEDS_REVIEW.value
            # One verdict, one durable record: a crash after this point must not
            # make the next execution pay for the same reading again.
            session.commit()

        session.flush()
        runs.record_run(
            session=session,
            job=current,
            stage=runs.STAGE_TRANSCRIPTION,
            outcome=(
                runs.OUTCOME_REVIEW
                if counts["differences"]
                or counts["unavailable"]
                or counts["page_unverified"]
                or counts["unverified_award"]
                or counts["evidence_failures"]
                or counts["evidence_unverified"]
                else runs.OUTCOME_OK
            ),
            prompt_version=prompt_version,
            detail={
                **policy.describe(),
                "candidates": len(targets),
                **counts,
                "selection": {
                    target.question_id: list(target.reasons) for target in targets
                },
                # The whole queue, not only the questions that were bought: an
                # operator can see why a question was or was not worth a reading.
                "ranking": [
                    {
                        "rank": item.rank,
                        "question_id": item.question_id,
                        "score": item.score,
                        "signals": list(item.signals),
                        "max_marks": item.max_marks,
                    }
                    for item in ranking
                ],
                "page_sources": page_sources,
            },
        )
        session.commit()
        return {
            "enabled": True,
            "checked": len(targets),
            "disagreements": disagreements,
            **counts,
        }

    def _double_check(
        self, working: _MarkingRun, rows: list[QuestionResult]
    ) -> dict[str, Any] | None:
        """Have a second, independent pass re-mark the least certain questions.

        It never replaces the first award.  Agreement is recorded, disagreement
        sends the question to a person with both awards stated, and a reply that
        cannot be parsed is recorded as unverifiable.  Nothing here may turn one
        mark into a different mark.
        """

        current = working.job
        settings = working.settings
        session = working.session
        if not settings.marking.double_check_enabled:
            current.double_check_status = "DISABLED"
            runs.record_run(
                session=session,
                job=current,
                stage=runs.STAGE_DOUBLE_CHECK,
                outcome=runs.OUTCOME_SKIPPED,
                detail={"reason": "double check is disabled by configuration"},
            )
            session.commit()
            return {
                "enabled": False,
                "checked": 0,
                "already_checked": 0,
                "disagreements": 0,
            }

        policy = working.policy
        if policy.double_check_budget <= 0:
            # The assignment asked for economy: no second opinion is bought, and
            # the stage says so rather than looking like it found nothing.
            current.double_check_status = "NOT_REQUIRED"
            runs.record_run(
                session=session,
                job=current,
                stage=runs.STAGE_DOUBLE_CHECK,
                outcome=runs.OUTCOME_SKIPPED,
                detail={
                    "reason": f"review mode {policy.mode} takes no second opinion",
                    **policy.describe(),
                },
            )
            session.commit()
            return {
                "enabled": True,
                "checked": 0,
                "already_checked": 0,
                "disagreements": 0,
                "unverifiable": 0,
            }

        threshold = policy.double_check_threshold
        # A question that already has a second opinion is not asked again.  A
        # resumed execution must not spend another request to re-litigate a
        # verdict that is already recorded, and a human decision that followed
        # it must not be quietly reopened by a retry.
        existing_verdicts = {
            verdict.question_id
            for verdict in session.scalars(
                select(VerificationResult).where(
                    VerificationResult.job_id == current.id,
                    VerificationResult.kind == "DOUBLE_CHECK",
                )
            )
        }
        history = ResultRepository(session).double_check_disagreements(
            current.tenant_id,
            [row.question_id for row in rows],
            exclude_job_id=current.id,
        )
        markable = {
            row.question_id: row
            for row in rows
            if row.processing_state == ProcessingState.MARKED.value
        }
        targets = sampling.select_targets(
            markable.values(),
            policy=policy,
            skip=existing_verdicts,
            history=history,
            seed=str(current.id),
        )
        already_checked = [
            question_id
            for question_id in existing_verdicts
            if question_id in markable
        ]
        selected = [
            (markable[item.question_id], item)
            for item in targets
            if item.question_id in markable
        ]

        checked = 0
        disagreements = 0
        unverifiable = 0
        prompt_version: str | None = None
        for row, suspicion in selected:
            if self._cancelled(session, current.id):
                break
            leaf = working.leaf_by_question.get(row.question_id)
            if leaf is None:
                continue
            try:
                call = working.call_model(
                    leaf, prompt_id=PROMPT_DOUBLE_CHECK, purpose="double_check"
                )
            except AppError as error:
                # The second examiner has no permitted model.  The stage stops
                # and says so; it never re-marks with the marking model, and no
                # award is changed.
                if error.code in _RETRYABLE:
                    raise RetryablePipelineError(str(error)) from error
                runs.record_run(
                    session=session,
                    job=current,
                    stage=runs.STAGE_DOUBLE_CHECK,
                    outcome=runs.OUTCOME_SKIPPED,
                    detail={
                        "reason": "no model is permitted for independent review",
                        "error": str(error)[:400],
                        "checked_before_stop": checked,
                    },
                )
                current.double_check_status = "UNAVAILABLE"
                session.commit()
                break
            if prompt_version is None:
                # Provenance: the verdict names the prompt that produced it, so a
                # later prompt change does not rewrite an old verdict's identity.
                prompt_version = f"{PROMPT_DOUBLE_CHECK}:v{call.prompt.version}"
            captured = evidence.capture_raw_response(call.response.text)
            try:
                second = parse_question_mark(call.response.text, question_id=row.question_id)
            except MarkingResponseInvalid as error:
                unverifiable += 1
                self._record_double_check(
                    session,
                    row,
                    status="UNVERIFIABLE",
                    detail={"error": str(error)[:300], "raw_response": captured.value},
                )
                session.commit()
                continue
            second_award = evidence.normalise_award(
                second.awarded_marks, max_marks=row.max_marks
            )
            if second_award.anomaly is not None:
                # The second examiner returned a value that is not an awardable
                # mark at all.  That is an unusable second opinion, not a
                # legitimate disagreement over a mark between 0 and the maximum.
                unverifiable += 1
                self._record_double_check(
                    session,
                    row,
                    status="UNVERIFIABLE",
                    detail={
                        "error": (
                            f"the second marking returned {second.awarded_marks} of "
                            f"{row.max_marks}, which is not an awardable mark"
                        ),
                        "second_awarded": second.awarded_marks,
                        "max_marks": row.max_marks,
                        "raw_response": captured.value,
                        "raw_response_truncated": captured.truncated,
                    },
                )
                session.commit()
                continue
            checked += 1
            detail = {
                "first_awarded": row.awarded_marks,
                "second_awarded": second_award.normalised,
                "max_marks": row.max_marks,
                "second_confidence": second.confidence,
                "selection": list(suspicion.reasons),
                "raw_response": captured.value,
                "raw_response_truncated": captured.truncated,
            }
            if second_award.normalised == row.awarded_marks:
                self._record_double_check(session, row, status="AGREES", detail=detail)
                session.commit()
                continue
            disagreements += 1
            self._record_double_check(session, row, status="DISAGREES", detail=detail)
            concerns = [
                concern
                for concern in (row.scheme_concerns or [])
                if concern.get("code") != "DOUBLE_CHECK_DISAGREEMENT"
            ]
            concerns.append(
                {
                    "code": "DOUBLE_CHECK_DISAGREEMENT",
                    "message": (
                        "An independent second marking awarded "
                        f"{second_award.normalised} of {row.max_marks} where this run "
                        f"awarded {row.awarded_marks}. A person decides which award stands."
                    ),
                }
            )
            row.scheme_concerns = concerns
            row.review_required = True
            row.status = status_for(ProcessingState.NEEDS_REVIEW)
            row.processing_state = ProcessingState.NEEDS_REVIEW.value
            session.commit()

        session.flush()
        if checked or unverifiable:
            current.double_check_status = "COMPLETED"
            current.disagreement_status = "DISAGREEMENTS" if disagreements else "NONE"
        elif already_checked:
            # The second opinion was taken by an earlier execution of this job.
            # Its recorded status stands; reporting NOT_REQUIRED would erase it.
            current.double_check_status = current.double_check_status or "COMPLETED"
        else:
            current.double_check_status = "NOT_REQUIRED"
        runs.record_run(
            session=session,
            job=current,
            stage=runs.STAGE_DOUBLE_CHECK,
            outcome=(
                runs.OUTCOME_REVIEW
                if disagreements
                else runs.OUTCOME_FAILED
                if unverifiable and not checked
                else runs.OUTCOME_OK
            ),
            prompt_version=prompt_version,
            detail={
                **policy.describe(),
                "threshold": threshold,
                "candidates": len(selected),
                "already_checked": len(already_checked),
                "checked": checked,
                "disagreements": disagreements,
                "unverifiable": unverifiable,
                "selection": {
                    item.question_id: list(item.reasons) for item in targets
                },
            },
        )
        session.commit()
        return {
            "enabled": True,
            "checked": checked,
            "already_checked": len(already_checked),
            "disagreements": disagreements,
            "unverifiable": unverifiable,
        }

    def _record_double_check(
        self,
        session: Session,
        row: QuestionResult,
        *,
        status: str,
        detail: dict[str, Any],
    ) -> None:
        existing = session.scalar(
            select(VerificationResult).where(
                VerificationResult.job_id == row.job_id,
                VerificationResult.question_id == row.question_id,
                VerificationResult.kind == "DOUBLE_CHECK",
            )
        )
        if existing is not None:
            existing.status = status
            existing.detail = detail
            return
        session.add(
            VerificationResult(
                tenant_id=row.tenant_id,
                job_id=row.job_id,
                question_id=row.question_id,
                kind="DOUBLE_CHECK",
                status=status,
                detail=detail,
            )
        )

    def _apply_guard(
        self,
        *,
        session: Session,
        current: CorrectionJob,
        rows: list[QuestionResult],
        validation_failed: bool,
    ) -> str | None:
        """Decide whether this run's marks may stand as the stored result."""

        if not rows:
            return None
        prior_raw = ResultRepository(session).prior_job_totals(
            current.tenant_id, current.submission_id, exclude_job_id=current.id
        )
        prior = (
            PriorResult(
                job_id=prior_raw[0],
                earned=prior_raw[1],
                available=prior_raw[2],
                approved=prior_raw[3],
                teacher_override=prior_raw[4],
            )
            if prior_raw is not None
            else None
        )
        earned = sum(row.awarded_marks for row in rows)
        available = sum(row.max_marks for row in rows)
        decision = evaluate_overwrite(
            prior=prior,
            earned=earned,
            available=available,
            validation_failed=validation_failed,
        )

        runs.record_run(
            session,
            job=current,
            stage=runs.STAGE_GUARD,
            outcome=(
                runs.OUTCOME_BLOCKED
                if decision.action == "BLOCKED"
                else runs.OUTCOME_KEPT_EXISTING
                if decision.action == "KEEP_EXISTING"
                else runs.OUTCOME_OK
            ),
            detail={
                "action": decision.action,
                "confidence": decision.confidence,
                "earned": earned,
                "available": available,
                "prior_job_id": str(prior.job_id) if prior and prior.job_id else None,
                "validation_failed": validation_failed,
            },
        )
        session.commit()

        if decision.may_present:
            # This run may be presented.  A refusal recorded on this same job by
            # an earlier attempt must not keep hiding marks the guard now accepts.
            current.result_source = RESULT_SOURCE_AI
            session.commit()
            return None

        current.result_source = RESULT_SOURCE_REFUSED
        AuditService(session).record(
            tenant_id=current.tenant_id,
            action="result.overwrite_refused",
            entity_type="correction_job",
            entity_id=current.id,
            detail={
                "guard": decision.action,
                "confidence": decision.confidence,
                "reason": decision.reason,
                "earned": earned,
                "available": available,
                "prior_job_id": str(prior.job_id) if prior and prior.job_id else None,
            },
        )
        session.commit()
        return decision.action

    # -- helpers ---------------------------------------------------------
    def _pages(
        self, session: Session, tenant_id: uuid.UUID, submission_id: uuid.UUID
    ) -> list[DocumentPage]:
        documents = DocumentRepository(session).list_for_submission(tenant_id, submission_id)
        pages: list[DocumentPage] = []
        for document in documents:
            if document.status != "PROCESSED":
                continue
            pages.extend(DocumentRepository(session).pages(tenant_id, document.id))
        return pages

    def _submission_hash(
        self, session: Session, tenant_id: uuid.UUID, submission_id: uuid.UUID
    ) -> str | None:
        """A stable digest of the submitted documents, when they have one."""

        digests = sorted(
            str(document.sha256)
            for document in DocumentRepository(session).list_for_submission(
                tenant_id, submission_id
            )
            if getattr(document, "sha256", None)
        )
        return sha256_hex(",".join(digests)) if digests else None

    def _cancelled(self, session: Session, job_id: uuid.UUID) -> bool:
        session.expire_all()
        job = session.get(CorrectionJob, job_id)
        return bool(job and job.cancel_requested)

    def _discard(
        self, session: Session, job_id: uuid.UUID, question_result_ids: list[uuid.UUID]
    ) -> None:
        """A cancelled job must not leave a half-marked paper behind.

        The verification records go with their rows.  Leaving them behind would be
        worse than untidy: the next execution treats a stored verdict as already
        taken, so it would skip a question whose award had been discarded.  The
        archived replies that produced the discarded marks go too; a body whose
        rows are gone is evidence of nothing but itself.
        """

        if not question_result_ids:
            return
        usage_ids = [
            usage_id
            for usage_id in session.scalars(
                select(QuestionResult.provider_usage_id).where(
                    QuestionResult.id.in_(question_result_ids)
                )
            )
            if usage_id is not None
        ]
        if usage_ids:
            session.query(ProviderResponse).filter(
                ProviderResponse.job_id == job_id,
                ProviderResponse.provider_usage_id.in_(usage_ids),
            ).delete(synchronize_session=False)
        question_ids = list(
            session.scalars(
                select(QuestionResult.question_id).where(
                    QuestionResult.id.in_(question_result_ids)
                )
            )
        )
        if question_ids:
            session.query(VerificationResult).filter(
                VerificationResult.job_id == job_id,
                VerificationResult.question_id.in_(question_ids),
            ).delete(synchronize_session=False)
        for model in (CriterionResult, MarkingEvidence):
            session.query(model).filter(
                model.question_result_id.in_(question_result_ids)
            ).delete(synchronize_session=False)
        session.query(QuestionResult).filter(
            QuestionResult.id.in_(question_result_ids)
        ).delete(synchronize_session=False)
        session.commit()


def guard_reason_summary(action: str | None) -> str | None:
    """The sentence the review screen shows for a refused automated result."""

    if action == "BLOCKED":
        return (
            "This run's marks were not presented: the stored result is approved or "
            "the run failed validation. Nothing was overwritten."
        )
    if action == "KEEP_EXISTING":
        return (
            "This run's marks were not presented: they differ from the stored result "
            "by more than the accepted margin, so the stored result was kept for review."
        )
    return None
