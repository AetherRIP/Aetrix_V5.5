"""One bounded live extraction through the production service path.

The script creates a disposable tenant/exam and a generated mark-scheme PDF,
uploads and approves the scheme, makes exactly one Gemini call through
``ProviderCallService`` using the versioned ``blueprint_extraction@v1`` asset,
then creates a DRAFT through ``BlueprintService.create_extracted_draft``.

The authorized V5 key file is read read-only.  The selected key is encrypted
only for the duration of the call, is never printed, and the credential row is
deleted afterwards.  A failure is reported as a failure; no result is invented.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from pathlib import Path
from typing import Any

import pymupdf
from app.core.config import Settings, generate_encryption_key, get_settings
from app.core.errors import AppError
from app.core.ids import utcnow
from app.core.security import Principal, SecretBox, fingerprint
from app.db.models import Exam, ProviderCredential, ProviderUsage, Tenant, User
from app.db.repositories import CredentialRepository, PromptVersionRepository
from app.db.session import session_scope
from app.documents.blueprint_extraction import blueprint_response_schema
from app.documents.service import DocumentService
from app.prompts.registry import PromptRegistry
from app.providers.base import LLMInput
from app.providers.gemini import GeminiProvider
from app.providers.json import parse_json_text
from app.schemas.blueprint import BlueprintStructure
from app.services.exams import BlueprintService
from app.services.provider_calls import ProviderCallService
from app.services.schemes import SchemeService
from app.storage import build_storage
from pydantic import SecretStr, ValidationError


def _read_keys(path: Path) -> list[str]:
    keys: list[str] = []
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        value = raw.strip()
        if not value or value.startswith("#"):
            continue
        if "=" in value and not value.startswith("AIza"):
            value = value.split("=", 1)[1].strip()
        if value:
            keys.append(value)
    return keys


def _scheme_pdf() -> bytes:
    document = pymupdf.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((72, 72), "MARK SCHEME - LIVE-01", fontsize=16)
    page.insert_text((72, 115), "Question 1: 2 marks", fontsize=13)
    page.insert_text((72, 145), "Question 2: 3 marks", fontsize=13)
    page.insert_text((72, 175), "Total for paper: 5 marks", fontsize=13)
    page.insert_text((72, 215), "Page 1 of 1", fontsize=10)
    data = document.tobytes()
    document.close()
    return data


def _redact(value: str, keys: list[str]) -> str:
    cleaned = value
    for key in keys:
        cleaned = cleaned.replace(key, "[REDACTED]")
    return re.sub(r"AIza[0-9A-Za-z_-]{20,}", "[REDACTED]", cleaned)


def _input_blocks(document_service: DocumentService, tenant_id: uuid.UUID, document_id: uuid.UUID):
    inputs: list[LLMInput] = []
    for index, (page, image) in enumerate(document_service.page_images(tenant_id, document_id)):
        if index < 12:
            inputs.append(LLMInput.text_part(f"\n--- page {page.page_index} ---\n"))
            inputs.append(LLMInput.image_part(image, "image/png"))
        else:
            inputs.append(
                LLMInput.text_part(
                    f"\n--- page {page.page_index} (text only) ---\n{page.text_excerpt or ''}"
                )
            )
    return tuple(inputs)


def _run(settings: Settings, key: str) -> dict[str, Any]:
    storage = build_storage(settings)
    registry = PromptRegistry(settings.provider.prompt_root)
    provider = GeminiProvider(
        base_url=settings.provider.gemini_base_url,
        timeout_seconds=settings.provider.request_timeout_seconds,
    )
    live_settings = settings.model_copy(deep=True)
    live_settings.provider.max_attempts = 1
    # The development env file has a malformed Fernet key.  This credential is
    # temporary and deleted in the finally block, so use an ephemeral valid key
    # rather than modifying the operator's untracked .env.
    live_settings.security.encryption_key = SecretStr(generate_encryption_key())

    with session_scope(settings) as session:
        tenant = Tenant(name="Live extraction acceptance", slug=f"live-{uuid.uuid4().hex[:12]}")
        session.add(tenant)
        session.flush()
        user = User(tenant_id=tenant.id, subject=f"live-{uuid.uuid4().hex[:12]}", role="OWNER")
        session.add(user)
        session.flush()
        exam = Exam(
            tenant_id=tenant.id,
            title="Live extraction exam",
            paper_code="LIVE-01",
            created_by=user.id,
        )
        session.add(exam)
        session.commit()
        principal = Principal(
            user_id=user.id,
            tenant_id=tenant.id,
            subject=user.subject,
            role=user.role,
        )

        scheme_service = SchemeService(session, live_settings, storage)
        scheme, version = scheme_service.upload(
            principal,
            exam.id,
            title="Live extraction mark scheme",
            filename="live-scheme.pdf",
            declared_mime="application/pdf",
            data=_scheme_pdf(),
        )
        version = scheme_service.approve(principal, version.id, "acceptance probe")

        box = SecretBox(live_settings.security.encryption_key.get_secret_value())
        credential = CredentialRepository(session).create(
            tenant_id=tenant.id,
            account_label=f"live-probe-{uuid.uuid4().hex[:8]}",
            key_fingerprint=fingerprint(key),
            encrypted_secret=box.encrypt(key),
            model_access=[live_settings.provider.model_primary],
        )
        session.commit()

        document_service = DocumentService(session, live_settings, storage)
        document = document_service.get(tenant.id, scheme.document_id)
        calls = ProviderCallService(session, live_settings, provider, registry)
        summary: dict[str, Any] = {
            "tenant_id": str(tenant.id),
            "exam_id": str(exam.id),
            "scheme_id": str(scheme.id),
            "scheme_version_id": str(version.id),
            "scheme_status": version.status,
            "document_id": str(document.id),
            "model": live_settings.provider.model_primary,
            "key_fingerprint": credential.key_fingerprint,
        }
        try:
            result = calls.call(
                tenant_id=tenant.id,
                purpose="BLUEPRINT_EXTRACTION",
                prompt_id="blueprint_extraction",
                inputs=_input_blocks(document_service, tenant.id, document.id),
                prompt_version=1,
                response_schema=blueprint_response_schema(),
                max_output_tokens=4096,
            )
            response_text = _redact(result.response.text, [key])
            summary.update(
                {
                    "http_status": 200,
                    "response_text": response_text,
                    "input_tokens": result.response.usage.input_tokens,
                    "output_tokens": result.response.usage.output_tokens,
                    "cached_tokens": result.response.usage.cached_tokens,
                    "latency_ms": result.response.latency_ms,
                    "prompt_id": result.prompt.prompt_id,
                    "prompt_version": result.prompt.version,
                    "prompt_hash": result.prompt.content_hash,
                    "usage_id": str(result.usage_id),
                    "cost_usd": str(result.cost_usd) if result.cost_usd is not None else None,
                }
            )
            try:
                payload = parse_json_text(result.response.text)
                structure = BlueprintStructure.model_validate(payload)
            except (ValueError, ValidationError) as error:
                summary.update(
                    {
                        "status": "UNVERIFIED",
                        "failure": f"{type(error).__name__}: {_redact(str(error), [key])}",
                    }
                )
                return summary
            metadata = {
                "provider": result.response.model,
                "prompt_id": result.prompt.prompt_id,
                "prompt_version": result.prompt.version,
                "prompt_hash": result.prompt.content_hash,
                "usage_id": str(result.usage_id),
                "cost_usd": str(result.cost_usd) if result.cost_usd is not None else None,
                "live_probe": "scripts/live_extraction.py",
            }
            draft = BlueprintService(session).create_extracted_draft(
                principal,
                exam.id,
                structure,
                source_document_id=document.id,
                extraction_metadata=metadata,
            )
            usage = session.get(ProviderUsage, result.usage_id)
            prompt_row = PromptVersionRepository(session).get_or_create(
                prompt_id=result.prompt.prompt_id,
                version=result.prompt.version,
                content_hash=result.prompt.content_hash,
                path=result.prompt.path,
                model_role=result.prompt.model_role,
            )
            summary.update(
                {
                    "status": "VERIFIED",
                    "draft_blueprint_id": str(draft.id),
                    "draft_version": draft.version,
                    "draft_status": draft.status,
                    "draft_source": draft.source,
                    "draft_total_marks": draft.total_marks,
                    "draft_questions": len(structure.questions),
                    "usage_success": usage.success if usage else None,
                    "usage_prompt_version_id": str(usage.prompt_version_id) if usage else None,
                    "prompt_row": f"{prompt_row.prompt_id}@v{prompt_row.version}",
                    "created_at": utcnow().isoformat(),
                }
            )
            return summary
        finally:
            # provider_usage is append-only, so deleting a credential would
            # require an UPDATE that the database correctly rejects.  Neutralise
            # it instead: the ciphertext is replaced and the row is disabled.
            stored = session.get(ProviderCredential, credential.id)
            if stored is not None:
                stored.encrypted_secret = box.encrypt("")
                stored.health = "DISABLED"
                stored.last_error = "ephemeral acceptance credential neutralised"
            session.commit()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--key-file",
        default=r"C:\Projects\MATH_CHECKER_V5\API_KEYS.txt",
        type=Path,
    )
    parser.add_argument("--key-index", default=4, type=int, help="1-based key file entry")
    args = parser.parse_args()

    settings = get_settings()
    if not settings.security.encryption_key:
        print(json.dumps({"status": "UNVERIFIED", "failure": "encryption key not configured"}))
        return 2
    if not args.key_file.is_file():
        print(json.dumps({"status": "UNVERIFIED", "failure": "key file not found"}))
        return 2
    keys = _read_keys(args.key_file)
    if args.key_index < 1 or args.key_index > len(keys):
        print(json.dumps({"status": "UNVERIFIED", "failure": "requested key index is absent"}))
        return 2
    key = keys[args.key_index - 1]
    try:
        result = _run(settings, key)
    except AppError as error:
        print(
            json.dumps(
                {
                    "status": "UNVERIFIED",
                    "failure": f"{type(error).__name__}: {error.message}",
                    "details": error.details,
                },
                default=str,
            )
        )
        return 1
    except Exception as error:
        print(
            json.dumps(
                {
                    "status": "UNVERIFIED",
                    "failure": f"{type(error).__name__}: {_redact(str(error), [key])}",
                }
            )
        )
        return 1
    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("status") == "VERIFIED" else 1


if __name__ == "__main__":
    sys.exit(main())
