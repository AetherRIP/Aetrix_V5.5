"""PDF reports built from persisted correction results."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from ...core.security import Principal
from ...db.session import get_db_session
from ...services.student_report import StudentReportService
from ..deps import get_principal

router = APIRouter(tags=["reports"])


@router.get("/submissions/{submission_id}/report")
def get_submission_report(
    submission_id: uuid.UUID,
    detail: Literal["summary", "standard", "detailed"] = "standard",
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> Response:
    """The V5 individual-student correction report for one submission.

    Tenant scoping comes from the verified identity, and the result is read
    through the results service, so a refused or foreign run cannot be turned
    into a report.  The PDF states in its own text whether the result is
    approved; a draft is never presented as a returned result.
    """
    content, filename = StudentReportService(session).render(
        principal, submission_id, detail=detail
    )
    return Response(
        content=content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{filename}"',
            "Cache-Control": "private, no-store",
        },
    )
