"""Load a transcribed scheme-criteria document into ``marking_criteria``.

The engine can only mark against a scheme it holds as rows.  This imports a
prepared, validated document (see ``seed/pilot_scheme_v1_criteria.json``) for one
approved scheme version, after checking it against the approved blueprint.

It refuses to overwrite: a scheme version that already has criteria is left
untouched, and the blueprint a version was already reviewed against cannot be
silently replaced.  Imported rows are inert until a person approves them with
``--approve-by``: the marking pipeline refuses to start on a scheme version whose
``criteria_approved_at`` is null, so importing without approving changes nothing
about how a paper is marked.  Nothing here marks a paper, resumes a job, or edits
an award.

Usage::

    python scripts/import_scheme_criteria.py --dry-run
    python scripts/import_scheme_criteria.py
    python scripts/import_scheme_criteria.py --approve-by <user-id> \
        --reason "reviewed against the printed scheme"

The blueprint hash recorded on the scheme version is SHA-256 over the canonical
JSON of the blueprint structure (sorted keys, no spaces), so a later verifier can
recompute it from ``exam_blueprint_versions.structure``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
import uuid
from datetime import UTC, datetime

from app.core.config import get_settings
from app.correction.scheme_criteria import criteria_rules_hash, iter_criteria, validate
from app.db.models import ExamBlueprintVersion, MarkingCriterion, MarkSchemeVersion
from app.db.session import get_session_factory
from sqlalchemy import func, select

BACKEND = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_DOCUMENT = BACKEND / "seed" / "pilot_scheme_v1_criteria.json"


def blueprint_hash(structure: object) -> str:
    canonical = json.dumps(structure, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--document", type=pathlib.Path, default=DEFAULT_DOCUMENT)
    parser.add_argument("--dry-run", action="store_true", help="validate and print, write nothing")
    parser.add_argument("--approve-by", type=uuid.UUID, default=None)
    parser.add_argument("--reason", default="")
    parser.add_argument(
        "--approve-existing",
        action="store_true",
        help=(
            "re-approve criteria that are already imported, after checking the "
            "document still describes them exactly; imports and edits no row"
        ),
    )
    arguments = parser.parse_args()

    document = json.loads(arguments.document.read_text(encoding="utf-8"))
    settings = get_settings()
    factory = get_session_factory(settings)

    with factory() as session:
        version = session.get(MarkSchemeVersion, uuid.UUID(document["scheme_version_id"]))
        if version is None:
            print("the scheme version in the document does not exist", file=sys.stderr)
            return 2
        if str(version.tenant_id) != document["tenant_id"]:
            print("the document's tenant does not own that scheme version", file=sys.stderr)
            return 2
        blueprint = session.get(
            ExamBlueprintVersion, uuid.UUID(document["blueprint_version_id"])
        )
        if blueprint is None:
            print("the blueprint in the document does not exist", file=sys.stderr)
            return 2

        report = validate(document, blueprint.structure)
        print(json.dumps(report.describe(), indent=2))
        if not report.complete:
            print("refusing to import: the criteria do not cover the paper", file=sys.stderr)
            return 3

        # The digest the approval will record, computed from the document.  A
        # re-approval compares it with the stored rows instead of trusting that
        # the two agree.
        document_rules_hash = criteria_rules_hash(iter_criteria(document), blueprint.structure)

        existing = session.scalar(
            select(func.count())
            .select_from(MarkingCriterion)
            .where(MarkingCriterion.scheme_version_id == version.id)
        )
        if existing and not arguments.approve_existing:
            print(
                f"refusing to import: scheme version {version.id} already has {existing} "
                "criteria; nothing is overwritten",
                file=sys.stderr,
            )
            return 4
        if (
            version.criteria_blueprint_version_id is not None
            and version.criteria_blueprint_version_id != blueprint.id
        ):
            print(
                "refusing to import: this scheme version was reviewed against a "
                f"different blueprint ({version.criteria_blueprint_version_id})",
                file=sys.stderr,
            )
            return 4
        if arguments.approve_by is not None and not arguments.reason.strip():
            print("--approve-by needs --reason", file=sys.stderr)
            return 2

        if arguments.approve_existing:
            # Re-approval records which stored rules were reviewed.  It changes
            # no criterion row: if the document and the rows differ, the only
            # honest answer is to refuse and let a person reconcile them.
            stored = list(
                session.scalars(
                    select(MarkingCriterion).where(
                        MarkingCriterion.scheme_version_id == version.id
                    )
                )
            )
            if not stored:
                print(
                    "--approve-existing needs criteria that are already imported",
                    file=sys.stderr,
                )
                return 4
            stored_rules_hash = criteria_rules_hash(stored, blueprint.structure)
            if stored_rules_hash != document_rules_hash:
                print(
                    "refusing to approve: the document and the stored criteria differ "
                    f"(stored {stored_rules_hash[:16]}, document "
                    f"{document_rules_hash[:16]}); reconcile them before approving",
                    file=sys.stderr,
                )
                return 5
            if arguments.approve_by is None or not arguments.reason.strip():
                print(
                    "--approve-existing needs --approve-by and --reason",
                    file=sys.stderr,
                )
                return 2
            version.criteria_blueprint_version_id = blueprint.id
            version.criteria_blueprint_hash = blueprint_hash(blueprint.structure)
            version.criteria_rules_hash = stored_rules_hash
            version.criteria_approved_at = datetime.now(UTC)
            version.criteria_approved_by = arguments.approve_by
            version.criteria_approval_reason = arguments.reason.strip()
            session.commit()
            print(
                f"re-approved {len(stored)} existing criteria for scheme version "
                f"{version.id}; rules hash {stored_rules_hash[:16]}"
            )
            return 0

        rows = [
            MarkingCriterion(
                tenant_id=version.tenant_id,
                scheme_version_id=version.id,
                blueprint_version_id=blueprint.id,
                question_id=row["question_id"],
                code=row["code"],
                marks=row["marks"],
                ordinal=row["ordinal"],
                description=row["description"],
                expected_answer=row["expected_answer"],
                required_evidence=row["required_evidence"],
                dependencies=row["dependencies"],
                alternatives=row["alternatives"],
                award_conditions=row["award_conditions"],
                withhold_conditions=row["withhold_conditions"],
                source_ref=row["source_ref"],
                source_page=row["source_page"],
                source_quote=row["source_quote"],
                question_text=None,
            )
            for row in iter_criteria(document)
        ]
        print(f"prepared {len(rows)} criteria across {len(report.lines)} questions")

        if arguments.dry_run:
            for row in rows:
                print(f"  Q{row.question_id:>3} {row.code:<3} {row.marks}  {row.description[:70]}")
            print("dry run: nothing written")
            return 0

        session.add_all(rows)
        version.criteria_blueprint_version_id = blueprint.id
        version.criteria_blueprint_hash = blueprint_hash(blueprint.structure)
        version.criteria_rules_hash = criteria_rules_hash(rows, blueprint.structure)
        if arguments.approve_by is not None:
            version.criteria_approved_at = datetime.now(UTC)
            version.criteria_approved_by = arguments.approve_by
            version.criteria_approval_reason = arguments.reason.strip()
        session.commit()
        print(
            f"imported {len(rows)} criteria for scheme version {version.id}; "
            f"blueprint hash {version.criteria_blueprint_hash[:16]}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
