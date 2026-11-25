"""Where a quoted piece of evidence came from.

A quote without a page is not evidence a person can check: the reader has to
search the whole script again.  The engine therefore keeps three separate facts
about every quotation and never conflates them:

* the page the model says it read, in the numbering of the **original student
  document** (``document_pages.page_index``), not the position of an image in a
  request;
* the page row that number resolves to, which gives the document identity and
  the page number together; ``None`` when the number names no page, or names
  more than one page across the submission's documents;
* the bounding box, **only** when the extraction produced a usable one.  A box
  the check cannot read is dropped, never repaired and never invented.

Marking reads images, and an image carries no coordinates.  This build therefore
does not ask a model for a bounding box: it asks only for the page it read.
A box that arrives anyway is validated and kept only if it is well formed.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from .bbox import check_bbox
from .findings import (
    CODE_EVIDENCE_BBOX_INVALID,
    CODE_EVIDENCE_PAGE_INVALID,
    CODE_EVIDENCE_UNLOCATED,
    SEVERITY_DEFINITE,
    SEVERITY_POSSIBLE,
    SchemeFinding,
)

STATUS_LOCATED = "LOCATED"
STATUS_UNLOCATED = "UNLOCATED"
STATUS_UNKNOWN_PAGE = "UNKNOWN_PAGE"
STATUS_AMBIGUOUS_PAGE = "AMBIGUOUS_PAGE"
STATUS_NOT_STUDENT_DOCUMENT = "NOT_STUDENT_DOCUMENT"

@dataclass(frozen=True, slots=True)
class PageLocation:
    page_id: Any | None
    document_id: Any | None
    page_number: int | None
    status: str
    reason: str | None = None

    @property
    def located(self) -> bool:
        return self.status == STATUS_LOCATED


@dataclass(slots=True)
class PageIndex:
    """Page numbers of the original student documents, with their identities.

    ``by_number`` maps a page number to every stored page carrying it.  More
    than one is possible when a submission has two documents (a script and a
    continuation, say), and then a bare number does **not** identify a page: the
    evidence is recorded as unlocated rather than attached to the wrong scan.
    """

    by_number: dict[int, tuple[Any, ...]] = field(default_factory=dict)
    kinds: dict[Any, str] = field(default_factory=dict)

    @classmethod
    def build(cls, pages: Iterable[Any], documents: Iterable[Any] = ()) -> PageIndex:
        grouped: dict[int, list[Any]] = {}
        for page in pages:
            try:
                number = int(page.page_index)
            except (TypeError, ValueError, AttributeError):
                continue
            grouped.setdefault(number, []).append(page)
        kinds = {
            getattr(document, "id", None): str(getattr(document, "kind", "") or "")
            for document in documents
        }
        return cls(
            by_number={
                number: tuple(
                    sorted(rows, key=lambda page: str(getattr(page, "id", "")))
                )
                for number, rows in grouped.items()
            },
            kinds=kinds,
        )

    @property
    def numbers(self) -> list[int]:
        return sorted(self.by_number)

    @property
    def count(self) -> int:
        return sum(len(rows) for rows in self.by_number.values())

    def locate(self, number: Any) -> PageLocation:
        """Resolve one page number to a page of the original student document."""

        if number is None:
            return PageLocation(
                page_id=None,
                document_id=None,
                page_number=None,
                status=STATUS_UNLOCATED,
                reason="the reply did not say which page the evidence is on",
            )
        if isinstance(number, bool) or not isinstance(number, int):
            return PageLocation(
                page_id=None,
                document_id=None,
                page_number=None,
                status=STATUS_UNKNOWN_PAGE,
                reason=f"the page {number!r} is not a page number",
            )
        rows = self.by_number.get(number, ())
        if not rows:
            available = ", ".join(str(item) for item in self.numbers[:12]) or "none"
            return PageLocation(
                page_id=None,
                document_id=None,
                page_number=number,
                status=STATUS_UNKNOWN_PAGE,
                reason=(
                    f"the script has no page {number} (its pages are {available})"
                ),
            )
        if len(rows) > 1:
            return PageLocation(
                page_id=None,
                document_id=None,
                page_number=number,
                status=STATUS_AMBIGUOUS_PAGE,
                reason=(
                    f"page {number} exists in more than one document of this "
                    "submission, so the number alone does not identify a page"
                ),
            )
        page = rows[0]
        document_id = getattr(page, "document_id", None)
        kind = self.kinds.get(document_id)
        if kind and kind.upper() != "STUDENT":
            return PageLocation(
                page_id=None,
                document_id=document_id,
                page_number=number,
                status=STATUS_NOT_STUDENT_DOCUMENT,
                reason=(
                    f"page {number} belongs to a {kind.lower()} document, not to the "
                    "student's script"
                ),
            )
        return PageLocation(
            page_id=getattr(page, "id", None),
            document_id=document_id,
            page_number=number,
            status=STATUS_LOCATED,
        )


@dataclass(frozen=True, slots=True)
class EvidenceAttribution:
    """The provenance stored for one component's quotation."""

    component_code: str
    page_id: Any | None
    page_number: int | None
    document_id: Any | None
    bbox: list[float] | None
    status: str
    #: The page number the reply claimed, even when it did not resolve.
    claimed_page: int | None = None


def attribute(
    *,
    components: Iterable[Any],
    index: PageIndex,
    question_id: str | None = None,
    require_page: bool = False,
) -> tuple[list[EvidenceAttribution], list[SchemeFinding]]:
    """Attach every quotation to its page, and report what cannot be attached.

    A quotation whose page number names no page is a **definite** contradiction:
    the reply claims a page the script does not have.  A quotation with no page
    at all is a reason to look, not proof of an error, so it is a possible
    finding; under a review mode that acts on possible findings, the question is
    sent to a person.  A withheld component has no quotation and is not judged.

    ``require_page`` is true only for a reply whose prompt asked for the page.
    Judging an older prompt's reply against a field it was never offered would
    refuse it for something the model could not have supplied; the engine keeps
    such a quotation unlocated and stops there.
    """

    attributions: list[EvidenceAttribution] = []
    findings: list[SchemeFinding] = []
    for component in components:
        code = str(getattr(component, "code", "") or "")
        quote = str(getattr(component, "evidence", "") or "").strip()
        box, box_problem = check_bbox(getattr(component, "bbox", None))
        location = index.locate(getattr(component, "page", None))
        attributions.append(
            EvidenceAttribution(
                component_code=code,
                page_id=location.page_id,
                page_number=location.page_number,
                document_id=location.document_id,
                bbox=box,
                status=location.status,
                claimed_page=(
                    location.page_number
                    if isinstance(getattr(component, "page", None), int)
                    else None
                ),
            )
        )
        if not quote:
            # Nothing is quoted, so there is nothing to locate.
            continue
        if location.status in {
            STATUS_UNKNOWN_PAGE,
            STATUS_AMBIGUOUS_PAGE,
            STATUS_NOT_STUDENT_DOCUMENT,
        }:
            findings.append(
                SchemeFinding(
                    CODE_EVIDENCE_PAGE_INVALID,
                    f"The quotation for {code!r} is attributed to a page that cannot "
                    f"belong to this script: {location.reason}.",
                    SEVERITY_DEFINITE,
                )
            )
        elif location.status == STATUS_UNLOCATED and require_page:
            findings.append(
                SchemeFinding(
                    CODE_EVIDENCE_UNLOCATED,
                    f"The quotation for {code!r} names no page of the script, so a "
                    "reader cannot find it without searching the whole document.",
                    SEVERITY_POSSIBLE,
                )
            )
        if box_problem is not None:
            findings.append(
                SchemeFinding(
                    CODE_EVIDENCE_BBOX_INVALID,
                    f"The position given for {code!r} was not stored: {box_problem}.",
                    SEVERITY_POSSIBLE,
                )
            )
    return attributions, findings
