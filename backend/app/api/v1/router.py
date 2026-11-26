"""Aggregate the v1 routers."""

from __future__ import annotations

from fastapi import APIRouter

from . import (
    admin_accounts,
    admin_contributions,
    admin_overview,
    admin_providers,
    admin_settings,
    capabilities,
    classroom_allocations,
    classroom_class_assignments,
    classroom_integration,
    classroom_monitoring,
    contributions,
    corrections,
    documents,
    exams,
    identity,
    manual_corrections,
    messaging,
    reports,
    results,
    roster,
    usage,
    workspace,
)

router = APIRouter()
router.include_router(capabilities.router)
router.include_router(identity.router)
router.include_router(admin_contributions.router)
router.include_router(admin_accounts.router)
router.include_router(admin_overview.router)
router.include_router(classroom_allocations.router)
router.include_router(classroom_class_assignments.router)
router.include_router(classroom_integration.router)
router.include_router(classroom_monitoring.router)
router.include_router(admin_providers.router)
router.include_router(admin_settings.router)
router.include_router(contributions.router)
router.include_router(corrections.router)
router.include_router(documents.router)
router.include_router(exams.router)
router.include_router(manual_corrections.router)
router.include_router(messaging.router)
router.include_router(reports.router)
router.include_router(results.router)
router.include_router(roster.router)
router.include_router(usage.router)
router.include_router(workspace.router)
