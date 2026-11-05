"""Aggregate the v1 routers."""

from __future__ import annotations

from fastapi import APIRouter

from . import corrections, documents, exams, usage

router = APIRouter()
router.include_router(corrections.router)
router.include_router(documents.router)
router.include_router(exams.router)
router.include_router(usage.router)
