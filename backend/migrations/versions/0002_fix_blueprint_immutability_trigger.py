"""fix blueprint immutability trigger for json columns

Revision ID: 0002_blueprint_guard_fix
Revises: 2c331690c5f0
Create Date: 2026-11-05

PostgreSQL's ``json`` type has no equality operator, so the first version of the
guard raised ``undefined_function`` instead of rejecting a mutation.  Compare the
canonical text form of the JSON columns instead.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0002_blueprint_guard_fix"
down_revision: str | None = "2c331690c5f0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION aetrix_protect_blueprint() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.status IN ('APPROVED','SUPERSEDED') THEN
                IF NEW.structure::text IS DISTINCT FROM OLD.structure::text
                   OR NEW.total_marks IS DISTINCT FROM OLD.total_marks
                   OR NEW.content_hash IS DISTINCT FROM OLD.content_hash
                   OR NEW.exam_id IS DISTINCT FROM OLD.exam_id
                   OR NEW.version IS DISTINCT FROM OLD.version
                   OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
                   OR NEW.source_document_id IS DISTINCT FROM OLD.source_document_id
                   OR NEW.source IS DISTINCT FROM OLD.source
                   OR NEW.extraction_metadata::text IS DISTINCT FROM OLD.extraction_metadata::text
                   OR NEW.approved_by IS DISTINCT FROM OLD.approved_by
                   OR NEW.approved_at IS DISTINCT FROM OLD.approved_at
                   OR NEW.approval_reason IS DISTINCT FROM OLD.approval_reason THEN
                    RAISE EXCEPTION 'approved blueprint % is immutable', OLD.id;
                END IF;
                IF OLD.status = 'SUPERSEDED' AND NEW.status <> 'SUPERSEDED' THEN
                    RAISE EXCEPTION 'superseded blueprint % is immutable', OLD.id;
                END IF;
                IF OLD.status = 'APPROVED' AND NEW.status NOT IN ('APPROVED','SUPERSEDED') THEN
                    RAISE EXCEPTION 'approved blueprint % cannot return to %', OLD.id, NEW.status;
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )


def downgrade() -> None:
    # Restore the previous (broken for json comparisons) definition.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION aetrix_protect_blueprint() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.status IN ('APPROVED','SUPERSEDED') THEN
                IF NEW.structure IS DISTINCT FROM OLD.structure
                   OR NEW.total_marks IS DISTINCT FROM OLD.total_marks
                   OR NEW.content_hash IS DISTINCT FROM OLD.content_hash
                   OR NEW.exam_id IS DISTINCT FROM OLD.exam_id
                   OR NEW.version IS DISTINCT FROM OLD.version
                   OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
                   OR NEW.source_document_id IS DISTINCT FROM OLD.source_document_id
                   OR NEW.source IS DISTINCT FROM OLD.source
                   OR NEW.extraction_metadata IS DISTINCT FROM OLD.extraction_metadata
                   OR NEW.approved_by IS DISTINCT FROM OLD.approved_by
                   OR NEW.approved_at IS DISTINCT FROM OLD.approved_at
                   OR NEW.approval_reason IS DISTINCT FROM OLD.approval_reason THEN
                    RAISE EXCEPTION 'approved blueprint % is immutable', OLD.id;
                END IF;
                IF OLD.status = 'SUPERSEDED' AND NEW.status <> 'SUPERSEDED' THEN
                    RAISE EXCEPTION 'superseded blueprint % is immutable', OLD.id;
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
