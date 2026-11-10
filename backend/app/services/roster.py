"""Workspace classes and the student roster.

Reads are open to every member of the workspace.  Writes require a role that can
manage exams (owner, administrator or teacher).  Every lookup goes through the
caller's tenant, so a class or student id from another workspace is
indistinguishable from one that does not exist.
"""

from __future__ import annotations

import csv
import io
import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..audit.service import AuditService
from ..core.errors import AppError, ErrorCode
from ..core.security import Principal, ensure_exam_manager
from ..db.models import SchoolClass
from ..db.repositories import ClassRepository, StudentRepository
from ..schemas.roster import (
    ClassCreate,
    ClassRead,
    ClassUpdate,
    StudentCreate,
    StudentImportIssue,
    StudentImportResult,
    StudentRead,
    StudentUpdate,
)

#: A roster is a few hundred rows, not a data migration.  The cap keeps one
#: request bounded; the byte cap keeps a mislabelled binary from being parsed.
MAX_IMPORT_BYTES = 1_000_000
MAX_IMPORT_ROWS = 500

_IMPORT_CLASS_COLUMNS = ("class", "class_name")


class RosterService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.classes = ClassRepository(session)
        self.students = StudentRepository(session)
        self.audit = AuditService(session)

    # -- helpers ---------------------------------------------------------
    def _check(self, principal: Principal, workspace_id: uuid.UUID) -> None:
        if workspace_id != principal.tenant_id:
            raise AppError(ErrorCode.NOT_FOUND, "Workspace not found.")

    def _class(self, tenant_id: uuid.UUID, class_id: uuid.UUID) -> SchoolClass:
        row = self.classes.get(tenant_id, class_id)
        if row is None:
            raise AppError(ErrorCode.NOT_FOUND, "Class not found.")
        return row

    def _class_read(self, row: SchoolClass) -> ClassRead:
        return ClassRead(
            id=row.id,
            name=row.name,
            year_group=row.year_group,
            student_count=self.students.count_for_class(row.tenant_id, row.id),
            created_at=row.created_at,
        )

    def _commit_or_conflict(self, message: str) -> None:
        try:
            self.session.commit()
        except IntegrityError as error:
            self.session.rollback()
            raise AppError(ErrorCode.CONFLICT, message) from error

    # -- classes ---------------------------------------------------------
    def list_classes(self, principal: Principal, workspace_id: uuid.UUID) -> list[ClassRead]:
        self._check(principal, workspace_id)
        return [
            self._class_read(row) for row in self.classes.list(principal.tenant_id)
        ]

    def create_class(
        self, principal: Principal, workspace_id: uuid.UUID, payload: ClassCreate
    ) -> ClassRead:
        self._check(principal, workspace_id)
        ensure_exam_manager(principal)
        if self.classes.get_by_name(principal.tenant_id, payload.name) is not None:
            raise AppError(ErrorCode.CONFLICT, "A class with that name already exists.")
        row = self.classes.create(
            tenant_id=principal.tenant_id,
            name=payload.name,
            year_group=payload.year_group,
        )
        self.audit.record(
            tenant_id=principal.tenant_id,
            action="class.created",
            entity_type="class",
            entity_id=row.id,
            actor_type="USER",
            actor_id=principal.user_id,
            detail={"name": row.name, "year_group": row.year_group},
        )
        self._commit_or_conflict("A class with that name already exists.")
        return self._class_read(row)

    def update_class(
        self, principal: Principal, class_id: uuid.UUID, payload: ClassUpdate
    ) -> ClassRead:
        ensure_exam_manager(principal)
        row = self._class(principal.tenant_id, class_id)
        previous = {"name": row.name, "year_group": row.year_group}
        if "name" in payload.model_fields_set and payload.name is not None:
            row.name = payload.name
        if "year_group" in payload.model_fields_set:
            row.year_group = payload.year_group
        self.audit.record(
            tenant_id=principal.tenant_id,
            action="class.updated",
            entity_type="class",
            entity_id=row.id,
            actor_type="USER",
            actor_id=principal.user_id,
            detail={"before": previous, "after": {"name": row.name, "year_group": row.year_group}},
            before=previous,
            after={"name": row.name, "year_group": row.year_group},
        )
        self._commit_or_conflict("A class with that name already exists.")
        return self._class_read(row)

    def delete_class(self, principal: Principal, class_id: uuid.UUID) -> None:
        ensure_exam_manager(principal)
        row = self._class(principal.tenant_id, class_id)
        name = row.name
        # The student rows stay: their class reference is set null by the
        # foreign key rather than deleting a child record implicitly.
        self.classes.delete(row)
        self.audit.record(
            tenant_id=principal.tenant_id,
            action="class.deleted",
            entity_type="class",
            entity_id=class_id,
            actor_type="USER",
            actor_id=principal.user_id,
            detail={"name": name},
        )
        self.session.commit()

    # -- students --------------------------------------------------------
    def list_students(
        self,
        principal: Principal,
        workspace_id: uuid.UUID,
        *,
        class_id: uuid.UUID | None = None,
    ) -> list[StudentRead]:
        self._check(principal, workspace_id)
        if class_id is not None:
            self._class(principal.tenant_id, class_id)
        return [
            StudentRead.model_validate(row, from_attributes=True)
            for row in self.students.list(principal.tenant_id, class_id=class_id)
        ]

    def create_student(
        self, principal: Principal, workspace_id: uuid.UUID, payload: StudentCreate
    ) -> StudentRead:
        self._check(principal, workspace_id)
        ensure_exam_manager(principal)
        if payload.class_id is not None:
            self._class(principal.tenant_id, payload.class_id)
        if self.students.get_by_ref(principal.tenant_id, payload.student_ref) is not None:
            raise AppError(
                ErrorCode.CONFLICT,
                "A student with that reference already exists in this workspace.",
            )
        row = self.students.create(
            tenant_id=principal.tenant_id,
            student_ref=payload.student_ref,
            display_name=payload.display_name,
            class_id=payload.class_id,
        )
        self.audit.record(
            tenant_id=principal.tenant_id,
            action="student.added",
            entity_type="student",
            entity_id=row.id,
            actor_type="USER",
            actor_id=principal.user_id,
            detail={"student_ref": row.student_ref, "class_id": str(row.class_id or "")},
        )
        self._commit_or_conflict(
            "A student with that reference already exists in this workspace."
        )
        return StudentRead.model_validate(row, from_attributes=True)

    def update_student(
        self, principal: Principal, student_id: uuid.UUID, payload: StudentUpdate
    ) -> StudentRead:
        ensure_exam_manager(principal)
        row = self.students.get(principal.tenant_id, student_id)
        if row is None:
            raise AppError(ErrorCode.NOT_FOUND, "Student not found.")
        if "class_id" in payload.model_fields_set and payload.class_id is not None:
            self._class(principal.tenant_id, payload.class_id)
        previous = {"display_name": row.display_name, "class_id": str(row.class_id or "")}
        if "display_name" in payload.model_fields_set:
            row.display_name = payload.display_name
        if "class_id" in payload.model_fields_set:
            row.class_id = payload.class_id
        self.audit.record(
            tenant_id=principal.tenant_id,
            action="student.updated",
            entity_type="student",
            entity_id=row.id,
            actor_type="USER",
            actor_id=principal.user_id,
            detail={
                "before": previous,
                "after": {"display_name": row.display_name, "class_id": str(row.class_id or "")},
            },
            before=previous,
            after={"display_name": row.display_name, "class_id": str(row.class_id or "")},
        )
        self.session.commit()
        return StudentRead.model_validate(row, from_attributes=True)

    # -- bulk import -----------------------------------------------------
    def import_students(
        self, principal: Principal, workspace_id: uuid.UUID, data: bytes
    ) -> StudentImportResult:
        """Create students from a UTF-8 CSV, reporting every row.

        The whole file is read before anything is written so a bad header or an
        over-long file changes nothing.  Duplicate references — in the file or
        already stored — are skipped and named, never inserted twice, and a
        class name that does not exist yet is created in this workspace rather
        than silently dropping the student's allocation.
        """
        self._check(principal, workspace_id)
        ensure_exam_manager(principal)

        if len(data) > MAX_IMPORT_BYTES:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                "The CSV is larger than the 1 MB import limit.",
                details={"max_bytes": MAX_IMPORT_BYTES, "received_bytes": len(data)},
            )
        if not data.strip():
            raise AppError(ErrorCode.VALIDATION_ERROR, "The CSV file is empty.")
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                "The CSV must be UTF-8 encoded.",
            ) from error
        try:
            parsed = list(csv.reader(io.StringIO(text)))
        except csv.Error as error:
            raise AppError(
                ErrorCode.VALIDATION_ERROR, "The CSV could not be parsed."
            ) from error
        if not parsed:
            raise AppError(ErrorCode.VALIDATION_ERROR, "The CSV file is empty.")

        header = [cell.strip().lower() for cell in parsed[0]]
        if "student_ref" not in header:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                "The CSV needs a student_ref column in its first row.",
                details={"columns": header, "required": ["student_ref"]},
            )
        ref_index = header.index("student_ref")
        name_index = header.index("display_name") if "display_name" in header else None
        class_index = next(
            (header.index(column) for column in _IMPORT_CLASS_COLUMNS if column in header),
            None,
        )

        body = [row for row in parsed[1:] if any(cell.strip() for cell in row)]
        if len(body) > MAX_IMPORT_ROWS:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                f"The CSV has more than the {MAX_IMPORT_ROWS}-row import limit.",
                details={"max_rows": MAX_IMPORT_ROWS, "rows": len(body)},
            )

        existing_classes = {
            row.name.casefold(): row for row in self.classes.list(principal.tenant_id)
        }
        seen: set[str] = set()
        issues: list[StudentImportIssue] = []
        created_refs: list[str] = []
        created = skipped = failed = 0
        classes_created = 0

        for line_number, row in enumerate(body, start=2):
            ref = (row[ref_index] if ref_index < len(row) else "").strip()
            raw_name = (
                row[name_index]
                if name_index is not None and name_index < len(row)
                else ""
            )
            raw_class = (
                row[class_index]
                if class_index is not None and class_index < len(row)
                else ""
            )
            name = raw_name.strip() or None
            class_name = raw_class.strip() or None

            if not ref:
                failed += 1
                issues.append(
                    StudentImportIssue(
                        kind="ERROR", row=line_number, message="student_ref is required."
                    )
                )
                continue
            if len(ref) > 120:
                failed += 1
                issues.append(
                    StudentImportIssue(
                        kind="ERROR",
                        row=line_number,
                        student_ref=ref[:120],
                        message="student_ref is longer than 120 characters.",
                    )
                )
                continue
            if name is not None and len(name) > 200:
                failed += 1
                issues.append(
                    StudentImportIssue(
                        kind="ERROR",
                        row=line_number,
                        student_ref=ref,
                        message="display_name is longer than 200 characters.",
                    )
                )
                continue
            if ref in seen:
                skipped += 1
                issues.append(
                    StudentImportIssue(
                        kind="SKIPPED",
                        row=line_number,
                        student_ref=ref,
                        message="Duplicate reference in this file; the first row was kept.",
                    )
                )
                continue
            seen.add(ref)

            class_id: uuid.UUID | None = None
            if class_name is not None:
                if len(class_name) > 200:
                    failed += 1
                    issues.append(
                        StudentImportIssue(
                            kind="ERROR",
                            row=line_number,
                            student_ref=ref,
                            message="class is longer than 200 characters.",
                        )
                    )
                    continue
                existing = existing_classes.get(class_name.casefold())
                if existing is None:
                    existing = self.classes.create(
                        tenant_id=principal.tenant_id, name=class_name, year_group=None
                    )
                    self.audit.record(
                        tenant_id=principal.tenant_id,
                        action="class.created",
                        entity_type="class",
                        entity_id=existing.id,
                        actor_type="USER",
                        actor_id=principal.user_id,
                        detail={"name": existing.name, "source": "roster_import"},
                    )
                    existing_classes[class_name.casefold()] = existing
                    classes_created += 1
                class_id = existing.id

            try:
                # A savepoint per row isolates a duplicate reference from the
                # rows around it: one conflict must not discard a valid import.
                with self.session.begin_nested():
                    self.students.create(
                        tenant_id=principal.tenant_id,
                        student_ref=ref,
                        display_name=name,
                        class_id=class_id,
                    )
                    self.session.flush()
            except IntegrityError:
                skipped += 1
                issues.append(
                    StudentImportIssue(
                        kind="SKIPPED",
                        row=line_number,
                        student_ref=ref,
                        message="That reference already exists in this workspace.",
                    )
                )
                continue

            created += 1
            created_refs.append(ref)

        self.audit.record(
            tenant_id=principal.tenant_id,
            action="student.imported",
            entity_type="student",
            entity_id=str(workspace_id),
            actor_type="USER",
            actor_id=principal.user_id,
            detail={
                "total_rows": len(body),
                "created": created,
                "skipped": skipped,
                "failed": failed,
                "classes_created": classes_created,
            },
        )
        self.session.commit()
        return StudentImportResult(
            total_rows=len(body),
            created=created,
            skipped=skipped,
            failed=failed,
            classes_created=classes_created,
            issues=issues,
            created_refs=created_refs,
        )

    def delete_student(self, principal: Principal, student_id: uuid.UUID) -> None:
        ensure_exam_manager(principal)
        row = self.students.get(principal.tenant_id, student_id)
        if row is None:
            raise AppError(ErrorCode.NOT_FOUND, "Student not found.")
        ref = row.student_ref
        self.students.delete(row)
        self.audit.record(
            tenant_id=principal.tenant_id,
            action="student.removed",
            entity_type="student",
            entity_id=student_id,
            actor_type="USER",
            actor_id=principal.user_id,
            detail={"student_ref": ref},
        )
        self.session.commit()
