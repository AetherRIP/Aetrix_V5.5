"""Structured logging.

Two rules are enforced here:

* secrets and credentials are redacted before a record is formatted, and
* every record can carry the request, tenant and job identifiers held in
  context variables, so a log line can be tied to an auditable operation.

The application never logs request bodies or model prompts.  The redaction layer
is a safety net for accidental interpolation, not a licence to log them.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
tenant_id_var: ContextVar[str | None] = ContextVar("tenant_id", default=None)
job_id_var: ContextVar[str | None] = ContextVar("job_id", default=None)

_REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+"), r"\1[REDACTED]"),
    (re.compile(r"AIza[0-9A-Za-z_-]{20,}"), "[REDACTED_GOOGLE_KEY]"),
    (
        re.compile(
            r"(?i)((?:api[_-]?key|access[_-]?token|refresh[_-]?token|secret|password)"
            r"\s*[=:]\s*)[^\s,;\"']+"
        ),
        r"\1[REDACTED]",
    ),
    (
        re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
        "[REDACTED_JWT]",
    ),
    (re.compile(r"\b[0-9a-f]{40,}\b"), "[REDACTED_HEX]"),
)

_SENSITIVE_KEYS = {
    "authorization",
    "api_key",
    "apikey",
    "password",
    "secret",
    "token",
    "access_token",
    "refresh_token",
    "encrypted_secret",
    "jwt",
    "key",
}


def redact(value: str) -> str:
    redacted = value
    for pattern, replacement in _REDACTIONS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def redact_mapping(values: dict[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for key, value in values.items():
        if key.lower() in _SENSITIVE_KEYS:
            clean[key] = "[REDACTED]"
        elif isinstance(value, str):
            clean[key] = redact(value)
        else:
            clean[key] = value
    return clean


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
        }
        for name, variable in (
            ("request_id", request_id_var),
            ("tenant_id", tenant_id_var),
            ("job_id", job_id_var),
        ):
            value = variable.get()
            if value:
                payload[name] = value
        if record.exc_info:
            payload["exception"] = redact(self.formatException(record.exc_info))
        extra = getattr(record, "extra_fields", None)
        if isinstance(extra, dict):
            payload.update(redact_mapping(extra))
        return json.dumps(payload, ensure_ascii=True, default=str)


class PlainFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        prefix = f"{record.levelname:<8} {record.name}: "
        context = " ".join(
            f"{name}={variable.get()}"
            for name, variable in (
                ("request", request_id_var),
                ("tenant", tenant_id_var),
                ("job", job_id_var),
            )
            if variable.get()
        )
        suffix = f" [{context}]" if context else ""
        return redact(f"{prefix}{record.getMessage()}{suffix}")


def configure_logging(level: str = "INFO", *, json_output: bool = True) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if json_output else PlainFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
    for noisy in ("uvicorn.access", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(max(logging.WARNING, root.level))


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


@contextmanager
def log_context(
    *,
    request_id: str | None = None,
    tenant_id: str | None = None,
    job_id: str | None = None,
) -> Iterator[None]:
    tokens = []
    if request_id is not None:
        tokens.append((request_id_var, request_id_var.set(request_id)))
    if tenant_id is not None:
        tokens.append((tenant_id_var, tenant_id_var.set(str(tenant_id))))
    if job_id is not None:
        tokens.append((job_id_var, job_id_var.set(str(job_id))))
    try:
        yield
    finally:
        for variable, token in reversed(tokens):
            variable.reset(token)
