"""Application errors and their HTTP representation.

The error code is a closed vocabulary so the frontend and tests can depend on
it.  Internal exception text is logged but never returned: a database error can
contain a connection string or a row value, neither of which belongs in a
client response.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from .logging import get_logger, request_id_var

log = get_logger("aetrix.errors")


class ErrorCode(StrEnum):
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    PROVISIONING_REQUIRED = "PROVISIONING_REQUIRED"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    BLUEPRINT_NOT_APPROVED = "BLUEPRINT_NOT_APPROVED"
    ASSIGNMENT_NOT_READY = "ASSIGNMENT_NOT_READY"
    RESULT_NOT_READY = "RESULT_NOT_READY"
    JOB_NOT_CANCELLABLE = "JOB_NOT_CANCELLABLE"
    JOB_NOT_RETRYABLE = "JOB_NOT_RETRYABLE"
    PIPELINE_UNAVAILABLE = "PIPELINE_UNAVAILABLE"
    SERVICE_NOT_READY = "SERVICE_NOT_READY"
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"
    DOCUMENT_REJECTED = "DOCUMENT_REJECTED"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    EXTRACTION_INVALID = "EXTRACTION_INVALID"
    MAPPING_REQUIRES_APPROVED_BLUEPRINT = "MAPPING_REQUIRES_APPROVED_BLUEPRINT"
    BLUEPRINT_MUTATION_REJECTED = "BLUEPRINT_MUTATION_REJECTED"
    #: Platform account administration needs a Supabase service-role credential
    #: that is not configured.  This is a reported state, never a fake list.
    ADMIN_NOT_CONFIGURED = "ADMIN_NOT_CONFIGURED"
    ADMIN_UPSTREAM_ERROR = "ADMIN_UPSTREAM_ERROR"
    CLASSROOM_NOT_CONFIGURED = "CLASSROOM_NOT_CONFIGURED"
    CLASSROOM_NOT_CONNECTED = "CLASSROOM_NOT_CONNECTED"
    CLASSROOM_RECONNECT_REQUIRED = "CLASSROOM_RECONNECT_REQUIRED"
    CLASSROOM_SCOPE_MISSING = "CLASSROOM_SCOPE_MISSING"
    CLASSROOM_UPSTREAM_ERROR = "CLASSROOM_UPSTREAM_ERROR"
    NOT_SUPPORTED = "NOT_SUPPORTED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


_STATUS_BY_CODE: dict[ErrorCode, int] = {
    ErrorCode.UNAUTHORIZED: 401,
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.PROVISIONING_REQUIRED: 403,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.CONFLICT: 409,
    ErrorCode.VALIDATION_ERROR: 422,
    ErrorCode.BLUEPRINT_NOT_APPROVED: 409,
    ErrorCode.ASSIGNMENT_NOT_READY: 409,
    ErrorCode.RESULT_NOT_READY: 409,
    ErrorCode.JOB_NOT_CANCELLABLE: 409,
    ErrorCode.JOB_NOT_RETRYABLE: 409,
    ErrorCode.PIPELINE_UNAVAILABLE: 503,
    ErrorCode.SERVICE_NOT_READY: 503,
    ErrorCode.CONFIGURATION_ERROR: 500,
    ErrorCode.DOCUMENT_REJECTED: 422,
    ErrorCode.PROVIDER_UNAVAILABLE: 503,
    ErrorCode.EXTRACTION_INVALID: 422,
    ErrorCode.MAPPING_REQUIRES_APPROVED_BLUEPRINT: 409,
    ErrorCode.BLUEPRINT_MUTATION_REJECTED: 409,
    ErrorCode.ADMIN_NOT_CONFIGURED: 503,
    ErrorCode.ADMIN_UPSTREAM_ERROR: 502,
    ErrorCode.CLASSROOM_NOT_CONFIGURED: 503,
    ErrorCode.CLASSROOM_NOT_CONNECTED: 409,
    ErrorCode.CLASSROOM_RECONNECT_REQUIRED: 409,
    ErrorCode.CLASSROOM_SCOPE_MISSING: 403,
    ErrorCode.CLASSROOM_UPSTREAM_ERROR: 502,
    ErrorCode.NOT_SUPPORTED: 501,
    ErrorCode.INTERNAL_ERROR: 500,
}


class AppError(Exception):
    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code or _STATUS_BY_CODE.get(code, 500)
        self.details = details or {}

    def as_body(self) -> dict[str, Any]:
        return {
            "error": {
                "code": str(self.code),
                "message": self.message,
                "details": self.details,
                "request_id": request_id_var.get(),
            }
        }


def _body(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
            "request_id": request_id_var.get(),
        }
    }


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.as_body())

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        problems = [
            {
                "location": list(error.get("loc", ())),
                "type": str(error.get("type", "invalid")),
                "message": str(error.get("msg", "invalid value")),
            }
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content=_body(
                str(ErrorCode.VALIDATION_ERROR),
                "The request did not satisfy the API contract.",
                {"problems": problems},
            ),
        )

    @app.exception_handler(SQLAlchemyError)
    async def _database_error(_: Request, exc: SQLAlchemyError) -> JSONResponse:
        log.exception("database error")
        return JSONResponse(
            status_code=500,
            content=_body(str(ErrorCode.INTERNAL_ERROR), "A database error occurred."),
        )

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error", exc_info=exc)
        return JSONResponse(
            status_code=500,
            content=_body(str(ErrorCode.INTERNAL_ERROR), "An internal error occurred."),
        )
