"""Audit recording.

Audit rows are written in the same transaction as the change they describe.
The detail payload carries identifiers and decisions, never credentials or full
answers; ``before_hash``/``after_hash`` bind the event to the exact content
without duplicating it.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from ..core.ids import canonical_json, sha256_hex
from ..core.logging import request_id_var
from ..db.repositories import AuditRepository


class AuditService:
    def __init__(self, session: Session) -> None:
        self._repository = AuditRepository(session)

    def record(
        self,
        *,
        tenant_id: uuid.UUID | None,
        action: str,
        entity_type: str,
        entity_id: str | uuid.UUID,
        actor_type: str = "SYSTEM",
        actor_id: str | uuid.UUID | None = None,
        detail: dict[str, Any] | None = None,
        before: Any | None = None,
        after: Any | None = None,
    ) -> None:
        payload = detail or {}
        self._repository.add(
            tenant_id=tenant_id,
            actor_type=actor_type,
            actor_id=str(actor_id) if actor_id is not None else None,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id),
            detail=payload,
            before_hash=sha256_hex(canonical_json(before)) if before is not None else None,
            after_hash=sha256_hex(canonical_json(after)) if after is not None else None,
            request_id=request_id_var.get(),
        )
