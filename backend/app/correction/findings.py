"""The vocabulary a validation finding is reported with.

Kept in its own module so every check — scheme comparison, criterion identity,
evidence provenance — can name a finding without importing the check that
produces it.  The codes are stored on ``question_results.scheme_concerns`` and
read by the review screen, so they are a contract: a code is never renamed, and
a new one is added here once.
"""

from __future__ import annotations

from dataclasses import dataclass

CODE_UNKNOWN_CRITERION = "UNKNOWN_CRITERION"
CODE_MISSING_MARK_POINT = "MISSING_MARK_POINT"
CODE_OVER_SCHEME_CAPACITY = "OVER_SCHEME_CAPACITY"
CODE_UNMET_DEPENDENCY = "UNMET_DEPENDENCY"
CODE_ANSWER_DIFFERENT = "SCHEME_ANSWER_DIFFERENT"
CODE_ANSWER_WITHHELD = "SCHEME_ANSWER_WITHHELD"
CODE_ANSWER_NOT_CAO = "SCHEME_ANSWER_NOT_CAO"
CODE_EXCESS_CRITERION_AWARD = "EXCESS_CRITERION_AWARD"
CODE_ROUTE_CONFLICT = "ROUTE_CONFLICT"
CODE_TERM_COUNT_NOT_MET = "TERM_COUNT_NOT_MET"
CODE_TERM_COUNT_UNVERIFIED = "TERM_COUNT_UNVERIFIED"
CODE_ROUTE_THRESHOLD_UNRECORDED = "ROUTE_THRESHOLD_UNRECORDED"
CODE_AMBIGUOUS_CRITERION = "AMBIGUOUS_CRITERION_CODE"

#: Criterion identity and evidence provenance.  These describe an award the
#: stored scheme cannot receive as stated, independently of the student's
#: mathematics: a mark point that cannot be named, a mark point paid twice, a
#: component worth more than the point it names, and a quotation with no page.
CODE_COMPONENT_ABOVE_CRITERION_MAX = "COMPONENT_ABOVE_CRITERION_MAX"
CODE_CRITERION_REFERENCE_INVALID = "CRITERION_REFERENCE_INVALID"
CODE_DUPLICATE_CRITERION_AWARD = "DUPLICATE_CRITERION_AWARD"
CODE_CRITERION_NOT_IN_APPROVED_SCHEME = "CRITERION_NOT_IN_APPROVED_SCHEME"
CODE_CRITERION_NOT_IN_QUESTION = "CRITERION_NOT_IN_QUESTION"
CODE_EVIDENCE_PAGE_INVALID = "EVIDENCE_PAGE_INVALID"
CODE_EVIDENCE_UNLOCATED = "EVIDENCE_UNLOCATED"
CODE_EVIDENCE_BBOX_INVALID = "EVIDENCE_BBOX_INVALID"

#: What a finding is worth.  ``DEFINITE_MISMATCH`` is a contradiction the stored
#: evidence itself proves: an award above the scheme's capacity, a dependent
#: point without its prerequisite, an accuracy mark awarded for an answer the
#: scheme says is different, or a mark point that cannot be identified.
#: ``POSSIBLE_MISMATCH`` is a reason to look that does not prove an error on its
#: own (notation the scheme does not use, a scheme point nobody named, a
#: quotation with no page).  ``VERIFIED`` means the comparison found nothing to
#: dispute; ``UNVERIFIABLE`` means this build could not compare, which is never a
#: mismatch.
SEVERITY_DEFINITE = "DEFINITE_MISMATCH"
SEVERITY_POSSIBLE = "POSSIBLE_MISMATCH"
SEVERITY_VERIFIED = "VERIFIED"
SEVERITY_UNVERIFIABLE = "UNVERIFIABLE"


@dataclass(frozen=True, slots=True)
class SchemeFinding:
    code: str
    message: str
    severity: str = SEVERITY_POSSIBLE

    @property
    def definite(self) -> bool:
        return self.severity == SEVERITY_DEFINITE
