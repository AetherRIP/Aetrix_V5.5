"""Aggregate the v1 routers."""

from __future__ import annotations

from fastapi import APIRouter

from . import (
    admin_contributions,
    admin_providers,
    contributions,
    corrections,
    documents,
    exams,
    usage,
)

router = APIRouter()
router.include_router(admin_contributions.router)
router.include_router(admin_providers.router)
router.include_router(contributions.router)
router.include_router(corrections.router)
router.include_router(documents.router)
router.include_router(exams.router)
router.include_router(usage.router)
