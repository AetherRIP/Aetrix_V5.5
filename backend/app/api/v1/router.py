"""Aggregate the v1 routers."""

from __future__ import annotations

from fastapi import APIRouter

from . import (
    admin_accounts,
    admin_contributions,
    admin_overview,
    admin_providers,
    classroom_allocations,
    classroom_oauth,
    contributions,
    corrections,
    documents,
    exams,
    identity,
    results,
    roster,
    usage,
    workspace,
)

router = APIRouter()
router.include_router(identity.router)
router.include_router(admin_contributions.router)
router.include_router(admin_accounts.router)
router.include_router(admin_overview.router)
router.include_router(classroom_allocations.router)
router.include_router(classroom_oauth.router)
router.include_router(admin_providers.router)
router.include_router(contributions.router)
router.include_router(corrections.router)
router.include_router(documents.router)
router.include_router(exams.router)
router.include_router(results.router)
router.include_router(roster.router)
router.include_router(usage.router)
router.include_router(workspace.router)
