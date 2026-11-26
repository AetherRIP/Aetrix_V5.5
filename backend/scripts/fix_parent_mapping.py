"""Give a scoreable leaf the pages its parent question number was mapped to.

The mapper reads the printed question numbers off the script.  When a blueprint
splits a question into subquestions, the paper still prints ``16``, so the mapper
records ``16`` — a parent that is never marked — and the leaf ``16b`` ends up with
no page at all.  Whole-paper mode still sends the whole script, but a per-question
request or a coverage report for ``16b`` reads as a question with no pages.

This script adds the missing leaf rows beside the model's mapping.  It never
updates or deletes a mapping: the original row keeps its question id, method,
confidence and provider reference, and each correction names what it was derived
from.  A dry run (the default) prints exactly what would be added, and after an
apply the script re-reads every original mapping to prove it survived.

The correction is scoped to one student by default (``STUDENT_01``, the pilot's
first script).  The same gap exists on the other scripts of the assignment, so
widening the correction is a deliberate act (``--all-students``) rather than the
side effect of a default.

Usage::

    python scripts/fix_parent_mapping.py
    python scripts/fix_parent_mapping.py --student-ref STUDENT_01
    python scripts/fix_parent_mapping.py --student-ref STUDENT_01 --apply
    python scripts/fix_parent_mapping.py --all-students            # every script

Requires migration 0030 (the ``MANUAL`` mapping method).
"""

from __future__ import annotations

import argparse
import sys
import uuid
from collections import defaultdict

from app.core.config import get_settings
from app.correction.scheme_criteria import blueprint_leaves, children_by_parent
from app.db.models import (
    Assignment,
    Document,
    DocumentPage,
    ExamBlueprintVersion,
    PageQuestionMapping,
    Submission,
)
from app.db.session import get_session_factory
from sqlalchemy import select

DEFAULT_ASSIGNMENT = uuid.UUID("c2c0f961-1f81-4187-aeaf-420c98fc3f96")
DEFAULT_STUDENT_REF = "STUDENT_01"


def _submission_state(session, submission, leaves) -> tuple[list, dict, dict]:
    """``(mapping rows, page rows, {leaf: {page_index}})`` for one submission."""

    documents = list(
        session.scalars(
            select(Document).where(
                Document.submission_id == submission.id,
                Document.status == "PROCESSED",
            )
        )
    )
    document_ids = [document.id for document in documents]
    rows = (
        list(
            session.scalars(
                select(PageQuestionMapping).where(
                    PageQuestionMapping.document_id.in_(document_ids)
                )
            )
        )
        if document_ids
        else []
    )
    pages = (
        {
            page.id: page
            for page in session.scalars(
                select(DocumentPage).where(DocumentPage.document_id.in_(document_ids))
            )
        }
        if document_ids
        else {}
    )
    mapped: dict[str, set[int]] = defaultdict(set)
    for row in rows:
        page = pages.get(row.page_id)
        if page is not None:
            mapped[row.question_id].add(int(page.page_index))
    return rows, pages, mapped


def _missing(mapped: dict[str, set[int]], leaves: dict[str, int]) -> list[str]:
    return [leaf for leaf in leaves if not mapped.get(leaf)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assignment", type=uuid.UUID, default=DEFAULT_ASSIGNMENT)
    parser.add_argument(
        "--student-ref",
        default=DEFAULT_STUDENT_REF,
        help=f"the one script to correct (default: {DEFAULT_STUDENT_REF})",
    )
    parser.add_argument(
        "--all-students",
        action="store_true",
        help="correct every script of the assignment instead of one student_ref",
    )
    parser.add_argument(
        "--apply", action="store_true", help="write the correction rows (default: dry run)"
    )
    arguments = parser.parse_args()

    settings = get_settings()
    factory = get_session_factory(settings)
    with factory() as session:
        assignment = session.get(Assignment, arguments.assignment)
        if assignment is None:
            print("no such assignment", file=sys.stderr)
            return 2
        blueprint = session.get(ExamBlueprintVersion, assignment.blueprint_version_id)
        if blueprint is None:
            print("the assignment has no blueprint version", file=sys.stderr)
            return 2
        leaves = blueprint_leaves(blueprint.structure)
        parents = children_by_parent(blueprint.structure)

        submissions = list(
            session.scalars(
                select(Submission)
                .where(Submission.assignment_id == assignment.id)
                .order_by(Submission.student_ref)
            )
        )
        if not arguments.all_students:
            selected = [
                submission
                for submission in submissions
                if submission.student_ref == arguments.student_ref
            ]
            if not selected:
                print(
                    f"no submission of this assignment has student_ref "
                    f"{arguments.student_ref!r}; nothing was read or written",
                    file=sys.stderr,
                )
                return 2
            submissions = selected
        print(
            "scope: "
            + (
                f"every submission of the assignment ({len(submissions)})"
                if arguments.all_students
                else f"student_ref {arguments.student_ref!r} only "
                f"({len(submissions)} submission(s))"
            )
        )

        pending: list[PageQuestionMapping] = []
        original_ids: set[uuid.UUID] = set()
        for submission in submissions:
            rows, pages, mapped = _submission_state(session, submission, leaves)
            original_ids.update(row.id for row in rows)
            missing = _missing(mapped, leaves)
            print(
                f"{submission.student_ref}: {len(leaves) - len(missing)}/{len(leaves)} "
                f"leaves mapped, missing {missing or 'none'}"
            )
            for parent_id, child_ids in parents.items():
                parent_rows = [row for row in rows if row.question_id == parent_id]
                if not parent_rows:
                    continue
                for child_id in child_ids:
                    if child_id not in leaves or mapped.get(child_id):
                        continue
                    for parent_row in parent_rows:
                        page = pages.get(parent_row.page_id)
                        if page is None:
                            continue
                        if any(
                            row.page_id == parent_row.page_id and row.question_id == child_id
                            for row in rows
                        ):
                            continue
                        pending.append(
                            PageQuestionMapping(
                                tenant_id=parent_row.tenant_id,
                                document_id=parent_row.document_id,
                                page_id=parent_row.page_id,
                                blueprint_version_id=parent_row.blueprint_version_id,
                                question_id=child_id,
                                confidence=parent_row.confidence,
                                method="MANUAL",
                                source_ref={
                                    "corrected_from": parent_id,
                                    "original_mapping_id": str(parent_row.id),
                                    "original_method": parent_row.method,
                                    "original_source_ref": parent_row.source_ref,
                                    "reason": (
                                        f"the paper prints {parent_id}; {child_id} is the "
                                        "scoreable leaf of that question"
                                    ),
                                    "script": "scripts/fix_parent_mapping.py",
                                },
                            )
                        )
                        print(
                            f"    + {child_id} <- {parent_id} on page {page.page_index}"
                        )

        if not pending:
            print("nothing to correct: every leaf already has a page mapping")
            return 0
        if not arguments.apply:
            print(f"dry run: {len(pending)} mapping row(s) would be added")
            return 0

        session.add_all(pending)
        try:
            session.commit()
        except Exception as error:
            session.rollback()
            print(
                "the correction could not be stored; migration 0030 (MANUAL mapping "
                f"method) is probably not applied: {type(error).__name__}",
                file=sys.stderr,
            )
            return 5
        print(f"added {len(pending)} mapping row(s)")

        # The correction only ever inserts.  Re-reading every original row turns
        # that into a check rather than a promise: a mapping that is missing here
        # means something updated or deleted it.
        survivors = set(
            session.scalars(
                select(PageQuestionMapping.id).where(
                    PageQuestionMapping.id.in_(original_ids)
                )
            )
        )
        print(f"original mappings preserved: {len(survivors)} of {len(original_ids)}")
        if survivors != original_ids:
            print(
                "an original mapping is missing after the correction; the run did not "
                "preserve the model's mappings",
                file=sys.stderr,
            )
            return 6

        remaining = 0
        for submission in submissions:
            _rows, _pages, mapped = _submission_state(session, submission, leaves)
            missing = _missing(mapped, leaves)
            print(
                f"{submission.student_ref}: {len(leaves) - len(missing)}/{len(leaves)} "
                f"leaves mapped after the correction, missing {missing or 'none'}"
            )
            remaining += len(missing)
        return 1 if remaining else 0


if __name__ == "__main__":
    sys.exit(main())
