"""Authenticated ingestion, mapping, scheme, extraction and override routes."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile, status
from sqlalchemy.orm import Session

from ...core.config import Settings, get_settings
from ...core.errors import AppError, ErrorCode
from ...core.security import Principal, ensure_exam_manager
from ...db.models import Document
from ...db.session import get_db_session
from ...documents.blueprint_extraction import BlueprintExtractionService
from ...documents.mapping import PageQuestionMapper
from ...documents.service import DocumentService
from ...prompts.registry import PromptRegistry
from ...schemas.blueprint import BlueprintRead
from ...schemas.documents import (
    BlueprintExtractionRead,
    BlueprintExtractionRequest,
    BlueprintOverrideCreate,
    BlueprintOverrideRead,
    DocumentMappingRead,
    DocumentMappingRequest,
    DocumentPageRead,
    DocumentRead,
    ProviderCallSummary,
    SchemeApprove,
    SchemeCriteriaApprove,
    SchemeCriteriaExtractionRead,
    SchemeCriteriaExtractionRequest,
    SchemeCriterionRead,
    SchemeRead,
    SchemeUploadRead,
    SchemeVersionRead,
)
from ...services.blueprint_overrides import BlueprintOverrideService
from ...services.provider_calls import ProviderCallService
from ...services.scheme_criteria import SchemeCriteriaService
from ...services.schemes import SchemeService
from ...storage.base import Storage, StorageError
from ..deps import (
    get_principal,
    get_prompt_registry,
    get_provider_calls,
    get_storage,
)

router = APIRouter(tags=["documents"])


def _document_read(
    service: DocumentService, document: Document, tenant_id: uuid.UUID
) -> DocumentRead:
    pages = service.pages(tenant_id, document.id)
    base = DocumentRead.model_validate(document)
    return base.model_copy(
        update={"pages": [DocumentPageRead.model_validate(page) for page in pages]}
    )


async def _read_upload(file: UploadFile) -> tuple[str, str, bytes]:
    data = await file.read()
    return file.filename or "document", file.content_type or "", data


@router.post(
    "/submissions/{submission_id}/documents",
    response_model=DocumentRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_submission_document(
    submission_id: uuid.UUID,
    file: UploadFile = File(...),
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    storage: Storage = Depends(get_storage),
) -> DocumentRead:
    filename, content_type, data = await _read_upload(file)
    service = DocumentService(session, settings, storage)
    document = service.ingest_for_submission(
        principal,
        submission_id,
        filename=filename,
        declared_mime=content_type,
        data=data,
    )
    return _document_read(service, document, principal.tenant_id)


@router.get("/documents/{document_id}", response_model=DocumentRead)
def get_document(
    document_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    storage: Storage = Depends(get_storage),
) -> DocumentRead:
    service = DocumentService(session, settings, storage)
    document = service.get(principal.tenant_id, document_id)
    return _document_read(service, document, principal.tenant_id)


@router.get("/documents/{document_id}/pages/{page_index}")
def get_document_page_image(
    document_id: uuid.UUID,
    page_index: int,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    storage: Storage = Depends(get_storage),
) -> Response:
    """A rendered page of any document this workspace owns.

    The preview uses this to show the printed mark scheme beside the script; the
    page is served from storage after the tenant check, never by path.
    """

    if page_index < 1:
        raise AppError(ErrorCode.NOT_FOUND, "Page not found.")
    service = DocumentService(session, settings, storage)
    for page in service.pages(principal.tenant_id, document_id):
        if page.page_index != page_index:
            continue
        try:
            image = storage.read(page.storage_key)
        except StorageError as error:
            raise AppError(
                ErrorCode.SERVICE_NOT_READY,
                "This page is missing from storage.",
            ) from error
        return Response(
            content=image,
            media_type="image/png",
            headers={
                "Cache-Control": f"private, max-age={settings.security.signed_url_ttl_seconds}",
                "Content-Disposition": "inline",
            },
        )
    raise AppError(ErrorCode.NOT_FOUND, "Page not found.")


@router.post("/documents/{document_id}/mapping", response_model=DocumentMappingRead)
def map_document(
    document_id: uuid.UUID,
    payload: DocumentMappingRequest,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    storage: Storage = Depends(get_storage),
    provider_calls: ProviderCallService = Depends(get_provider_calls),
) -> DocumentMappingRead:
    ensure_exam_manager(principal)
    mapper = PageQuestionMapper(session, settings, storage, provider_calls=provider_calls)
    result = mapper.map(principal.tenant_id, document_id, payload.blueprint_version_id)
    return DocumentMappingRead(
        document_id=result.document.id,
        blueprint_version_id=result.blueprint_version_id,
        status=result.status,
        reasons=result.reasons,
        mappings=[mapping for mapping in result.mappings],
    )


@router.post(
    "/exams/{exam_id}/schemes",
    response_model=SchemeUploadRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_scheme(
    exam_id: uuid.UUID,
    title: str = Form(...),
    file: UploadFile = File(...),
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    storage: Storage = Depends(get_storage),
) -> SchemeUploadRead:
    filename, content_type, data = await _read_upload(file)
    scheme, version = SchemeService(session, settings, storage).upload(
        principal,
        exam_id,
        title=title,
        filename=filename,
        declared_mime=content_type,
        data=data,
    )
    return SchemeUploadRead(
        scheme=SchemeRead.model_validate(scheme),
        version=SchemeVersionRead.model_validate(version),
    )


@router.get(
    "/exams/{exam_id}/scheme-versions", response_model=list[SchemeVersionRead]
)
def list_scheme_versions(
    exam_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    storage: Storage = Depends(get_storage),
) -> list[SchemeVersionRead]:
    versions = SchemeService(session, settings, storage).list_versions(
        principal.tenant_id, exam_id
    )
    return [SchemeVersionRead.model_validate(version) for version in versions]


@router.get("/schemes/{version_id}", response_model=SchemeVersionRead)
def get_scheme_version(
    version_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    storage: Storage = Depends(get_storage),
) -> SchemeVersionRead:
    version = SchemeService(session, settings, storage).get_version(principal.tenant_id, version_id)
    return SchemeVersionRead.model_validate(version)


@router.post("/schemes/{version_id}/approve", response_model=SchemeVersionRead)
def approve_scheme_version(
    version_id: uuid.UUID,
    payload: SchemeApprove,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    storage: Storage = Depends(get_storage),
) -> SchemeVersionRead:
    version = SchemeService(session, settings, storage).approve(
        principal, version_id, payload.reason
    )
    return SchemeVersionRead.model_validate(version)


@router.get(
    "/schemes/{version_id}/criteria", response_model=list[SchemeCriterionRead]
)
def list_scheme_criteria(
    version_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    storage: Storage = Depends(get_storage),
    registry: PromptRegistry = Depends(get_prompt_registry),
    provider_calls: ProviderCallService = Depends(get_provider_calls),
) -> list[SchemeCriterionRead]:
    """The mark points stored for one scheme version, for review.

    Read-only and tenant-scoped: this is the set a teacher approves, and what
    the engine will award from once it is approved against their blueprint.
    """

    service = SchemeCriteriaService(session, settings, storage, registry, provider_calls)
    version = service.get_version(principal.tenant_id, version_id)
    return [
        SchemeCriterionRead.model_validate(row)
        for row in service.criteria(principal.tenant_id, version.id)
    ]


@router.post(
    "/schemes/{version_id}/criteria/extractions",
    response_model=SchemeCriteriaExtractionRead,
)
def extract_scheme_criteria(
    version_id: uuid.UUID,
    payload: SchemeCriteriaExtractionRequest,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    storage: Storage = Depends(get_storage),
    registry: PromptRegistry = Depends(get_prompt_registry),
    provider_calls: ProviderCallService = Depends(get_provider_calls),
) -> SchemeCriteriaExtractionRead:
    """Transcribe the scheme's printed mark points against one approved paper.

    Storing happens only for a transcription that covers every scoreable leaf
    with exactly the paper's marks; a partial set is refused with the reasons a
    person has to fix.
    """

    result = SchemeCriteriaService(
        session, settings, storage, registry, provider_calls
    ).extract(
        principal,
        version_id,
        blueprint_version_id=payload.blueprint_version_id,
        prompt_version=payload.prompt_version,
    )
    provider = result.provider
    return SchemeCriteriaExtractionRead(
        version=SchemeVersionRead.model_validate(result.version),
        criteria=[SchemeCriterionRead.model_validate(row) for row in result.criteria],
        coverage=result.coverage.describe(),
        provider=ProviderCallSummary(
            usage_id=provider.usage_id,
            provider=provider.provider_name,
            model=provider.response.model,
            prompt_id=provider.prompt.prompt_id,
            prompt_version=provider.prompt.version,
            input_tokens=provider.response.usage.input_tokens,
            output_tokens=provider.response.usage.output_tokens,
            cached_tokens=provider.response.usage.cached_tokens,
            cost_usd=float(provider.cost_usd) if provider.cost_usd is not None else None,
            latency_ms=provider.response.latency_ms,
        ),
    )


@router.post(
    "/schemes/{version_id}/criteria/approval", response_model=SchemeVersionRead
)
def approve_scheme_criteria(
    version_id: uuid.UUID,
    payload: SchemeCriteriaApprove,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    storage: Storage = Depends(get_storage),
    registry: PromptRegistry = Depends(get_prompt_registry),
    provider_calls: ProviderCallService = Depends(get_provider_calls),
) -> SchemeVersionRead:
    """Approve the stored criteria against one exact blueprint version.

    The rows are re-validated and digested here; the approval records what was
    reviewed, so a later change to the rows is detectable rather than silently
    marked with.
    """

    version = SchemeCriteriaService(
        session, settings, storage, registry, provider_calls
    ).approve(
        principal,
        version_id,
        blueprint_version_id=payload.blueprint_version_id,
        reason=payload.reason,
    )
    return SchemeVersionRead.model_validate(version)


@router.post(
    "/exams/{exam_id}/blueprint/extractions",
    response_model=BlueprintExtractionRead,
)
def extract_blueprint(
    exam_id: uuid.UUID,
    payload: BlueprintExtractionRequest,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    storage: Storage = Depends(get_storage),
    registry: PromptRegistry = Depends(get_prompt_registry),
    provider_calls: ProviderCallService = Depends(get_provider_calls),
) -> BlueprintExtractionRead:
    result = BlueprintExtractionService(
        session, settings, storage, registry, provider_calls
    ).extract(
        principal,
        exam_id,
        payload.scheme_version_id,
        prompt_version=payload.prompt_version,
    )
    provider = result.provider
    return BlueprintExtractionRead(
        blueprint=BlueprintRead.model_validate(result.blueprint),
        provider=ProviderCallSummary(
            usage_id=provider.usage_id,
            provider=provider.provider_name,
            model=provider.response.model,
            prompt_id=provider.prompt.prompt_id,
            prompt_version=provider.prompt.version,
            input_tokens=provider.response.usage.input_tokens,
            output_tokens=provider.response.usage.output_tokens,
            cached_tokens=provider.response.usage.cached_tokens,
            cost_usd=float(provider.cost_usd) if provider.cost_usd is not None else None,
            latency_ms=provider.response.latency_ms,
        ),
    )


@router.post(
    "/exams/{exam_id}/blueprint/overrides",
    response_model=BlueprintOverrideRead,
    status_code=status.HTTP_201_CREATED,
)
def create_blueprint_override(
    exam_id: uuid.UUID,
    payload: BlueprintOverrideCreate,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> BlueprintOverrideRead:
    result = BlueprintOverrideService(session).create(principal, exam_id, payload)
    return BlueprintOverrideRead.model_validate(result.override).model_copy(
        update={
            "base_version": BlueprintRead.model_validate(result.base),
            "result_version": BlueprintRead.model_validate(result.result),
        }
    )


@router.get(
    "/exams/{exam_id}/blueprint/overrides",
    response_model=list[BlueprintOverrideRead],
)
def list_blueprint_overrides(
    exam_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> list[BlueprintOverrideRead]:
    return [
        BlueprintOverrideRead.model_validate(row)
        for row in BlueprintOverrideService(session).list(principal.tenant_id, exam_id)
    ]
