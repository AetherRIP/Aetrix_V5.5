"""Workspace creation through the registered template.

Every code path that creates a workspace goes through this service, so the
platform's ``default_workspace_template`` is applied at creation and the chosen
template is recorded on the tenant.  Existing workspaces are never touched:
nothing here updates a tenant that already exists.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..audit.service import AuditService
from ..core.security import Principal
from ..core.workspace_templates import (
    DEFAULT_WORKSPACE_TEMPLATE,
    WorkspaceTemplate,
    get_workspace_template,
)
from ..db.models import Tenant
from .platform_settings import PlatformSettingsService


class WorkspaceCreationService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.audit = AuditService(session)

    def template(self) -> tuple[WorkspaceTemplate, str, bool]:
        """The configured template, the configuration value, and whether it fell back."""

        configured = PlatformSettingsService(self.session).ensure().default_workspace_template
        template = get_workspace_template(configured)
        if template is not None:
            return template, configured, False
        # A row edited outside this API (or a template removed from the registry)
        # must not stop workspace creation.  The fallback is recorded rather than
        # hidden so the configuration drift is visible in the ledger.
        fallback = get_workspace_template(DEFAULT_WORKSPACE_TEMPLATE)
        assert fallback is not None
        return fallback, configured, True

    def create(
        self, *, name: str, slug: str, actor: Principal | None = None
    ) -> Tenant:
        template, configured, fell_back = self.template()
        tenant = Tenant(
            name=name,
            slug=slug,
            is_active=template.is_active,
            is_demo=template.is_demo,
            workspace_template=template.key,
        )
        self.session.add(tenant)
        self.session.flush()
        if fell_back:
            self.audit.record(
                tenant_id=None,
                action="platform.settings.workspace_template.fallback",
                entity_type="tenant",
                entity_id=tenant.id,
                actor_type="SYSTEM",
                actor_id=actor.subject if actor is not None else None,
                detail={
                    "configured_template": configured,
                    "applied_template": template.key,
                    "workspace_slug": slug,
                },
            )
        return tenant
