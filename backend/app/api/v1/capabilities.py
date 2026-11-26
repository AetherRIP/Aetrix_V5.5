"""Runtime capability advertisement.

The browser cannot know which engine build it is talking to, and a frontend
control that calls an endpoint the deployed engine does not have is a broken
control. This route states, in one small unauthenticated payload, which optional
engine features exist in *this* build. It exposes no tenant, user or secret data
— only booleans about the code that is running.

A frontend must default to "absent" when this route is unreachable or returns
anything other than a matching flag: an old engine answers 404 here, and a
control that would 404 is worse than a control that is not shown.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["capabilities"])


class CapabilitiesRead(BaseModel):
    #: Manual authoring of mark-scheme criteria (add / edit / remove / revise).
    scheme_criteria_authoring: bool
    #: Messaging stream events carry the persisted message body and sender.
    messaging_stream_payloads: bool


@router.get("/capabilities", response_model=CapabilitiesRead)
def capabilities() -> CapabilitiesRead:
    return CapabilitiesRead(
        scheme_criteria_authoring=True,
        messaging_stream_payloads=True,
    )
