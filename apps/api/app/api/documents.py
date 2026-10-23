"""Documents: upload, list, download, delete. Visibility is decided by acl_roles in SQL; tenant
isolation by RLS. Uploads are queued for the worker; progress arrives over /api/ws/documents."""

import hashlib
import re
import uuid
from datetime import datetime
from pathlib import PurePath
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import audit
from app.api.chats import any_role
from app.auth.deps import require
from app.auth.principal import Principal
from app.chat import repo as chat_repo
from app.db.models import ALL_ROLES, Document
from app.db.session import tenant_session
from app.documents.progress import ProgressEvent, publish
from app.errors import AppError, NotFound
from app.jobs import INGEST_DOCUMENT

router = APIRouter(prefix="/api/documents", tags=["documents"])
editor_role = require("editor", "admin")

PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
# Decided by the bytes, not the browser's Content-Type or the file name.
_SIGNATURES = {b"%PDF-": PDF, b"PK\x03\x04": DOCX}
_EXTENSIONS = {PDF: ".pdf", DOCX: ".docx"}
_UNSAFE = re.compile(r"[^\w.\-]+", re.UNICODE)


class UnsupportedFile(AppError):
    status_code = 415
    code = "unsupported_file"


class FileTooLarge(AppError):
    status_code = 413
    code = "file_too_large"


class DuplicateDocument(AppError):
    status_code = 409
    code = "duplicate_document"


class BadRoles(AppError):
    status_code = 422
    code = "validation_error"


class DocumentUpdate(BaseModel):
    title: Annotated[str, Field(min_length=1, max_length=300)] | None = None
    acl_roles: list[str] | None = Field(
        default=None, description="Who can see it; admins are always added."
    )


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    filename: str
    content_type: str
    size_bytes: int
    lang: str | None
    status: Literal["uploaded", "processing", "ready", "failed"]
    progress: int
    error: str | None
    page_count: int | None
    chunk_count: int | None
    acl_roles: list[str]
    created_at: datetime
    updated_at: datetime


def _detect_type(head: bytes) -> str:
    for signature, content_type in _SIGNATURES.items():
        if head.startswith(signature):
            return content_type
    raise UnsupportedFile("Upload a PDF or a Word (.docx) file.")


def _safe_filename(name: str, content_type: str) -> str:
    stem = _UNSAFE.sub("_", PurePath(name).stem).strip("._")[:120] or "document"
    return f"{stem}{_EXTENSIONS[content_type]}"


def _acl(requested: list[str] | None) -> list[str]:
    if not requested:
        return list(ALL_ROLES)
    unknown = set(requested) - set(ALL_ROLES)
    if unknown:
        raise BadRoles(f"Unknown roles: {', '.join(sorted(unknown))}.")
    # Admins can always see everything, so a document can't become unmanageable.
    return [r for r in ALL_ROLES if r in requested or r == "admin"]


async def _visible(session: AsyncSession, document_id: uuid.UUID, roles: list[str]) -> Document:
    document = await session.scalar(
        select(Document).where(Document.id == document_id, Document.acl_roles.overlap(roles))
    )
    if document is None:
        raise NotFound("Document not found.")
    return document


@router.post("", status_code=202)
async def upload(
    request: Request,
    file: Annotated[UploadFile, File()],
    title: Annotated[str | None, Form(max_length=300)] = None,
    acl_roles: Annotated[list[str] | None, Form()] = None,
    principal: Principal = Depends(editor_role),
) -> DocumentOut:
    """Stores the file and queues it for ingestion. Watch progress on /api/ws/documents."""
    state = request.app.state
    limit = state.settings.upload_max_bytes
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise FileTooLarge(f"Files can be up to {limit // (1024 * 1024)} MB.")
    content_type = _detect_type(data[:8])
    filename = _safe_filename(file.filename or "document", content_type)
    roles = _acl(acl_roles)
    document_id = uuid.uuid4()
    key = f"{principal.tenant_id}/{document_id}/{filename}"

    await state.store.put(key, data, content_type)
    try:
        async with tenant_session(state.sessions, principal.tenant_id) as session:
            user_id = await chat_repo.ensure_user_id(session, principal)
            document = Document(
                id=document_id,
                tenant_id=principal.tenant_id,
                uploaded_by=user_id,
                title=(title or "").strip() or PurePath(file.filename or filename).stem,
                filename=filename,
                content_type=content_type,
                size_bytes=len(data),
                sha256=hashlib.sha256(data).hexdigest(),
                s3_key=key,
                acl_roles=roles,
            )
            session.add(document)
            await session.flush()
            await session.refresh(document)
            await audit.record(
                session,
                tenant_id=principal.tenant_id,
                actor_id=user_id,
                actor=principal.username,
                action="document.uploaded",
                target_type="document",
                target_id=document.id,
                details={"title": document.title, "acl_roles": roles, "sha256": document.sha256},
            )
            out = DocumentOut.model_validate(document)
    except IntegrityError as exc:
        await state.store.delete(key)
        raise DuplicateDocument("This file has already been uploaded.") from exc

    await state.arq.enqueue_job(INGEST_DOCUMENT, str(document_id), str(principal.tenant_id))
    await publish(
        state.redis,
        principal.tenant_id,
        ProgressEvent(
            document_id=document_id,
            status="uploaded",
            stage="queued",
            progress=0,
            acl_roles=roles,
        ),
    )
    return out


@router.get("")
async def list_(request: Request, principal: Principal = Depends(any_role)) -> list[DocumentOut]:
    async with tenant_session(request.app.state.sessions, principal.tenant_id) as session:
        rows = await session.scalars(
            select(Document)
            .where(Document.acl_roles.overlap(list(principal.roles)))
            .order_by(Document.created_at.desc())
            .limit(200)
        )
        return [DocumentOut.model_validate(d) for d in rows]


@router.get("/{document_id}")
async def get(
    document_id: uuid.UUID, request: Request, principal: Principal = Depends(any_role)
) -> DocumentOut:
    async with tenant_session(request.app.state.sessions, principal.tenant_id) as session:
        return DocumentOut.model_validate(
            await _visible(session, document_id, list(principal.roles))
        )


@router.get("/{document_id}/file", response_class=Response)
async def download(
    document_id: uuid.UUID, request: Request, principal: Principal = Depends(any_role)
) -> Response:
    """The original file, for the citation viewer."""
    async with tenant_session(request.app.state.sessions, principal.tenant_id) as session:
        document = await _visible(session, document_id, list(principal.roles))
    data = await request.app.state.store.get(document.s3_key)
    return Response(
        content=data,
        media_type=document.content_type,
        headers={
            "Content-Disposition": f"inline; filename*=UTF-8''{quote(document.filename)}",
            "Cache-Control": "private, max-age=3600",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.patch("/{document_id}")
async def update(
    document_id: uuid.UUID,
    body: DocumentUpdate,
    request: Request,
    principal: Principal = Depends(editor_role),
) -> DocumentOut:
    """Renames a document or changes who can see it (answers stop citing it at once)."""
    async with tenant_session(request.app.state.sessions, principal.tenant_id) as session:
        user_id = await chat_repo.ensure_user_id(session, principal)
        document = await _visible(session, document_id, list(principal.roles))
        before = {"title": document.title, "acl_roles": list(document.acl_roles)}
        if body.title is not None:
            document.title = body.title.strip()
        if body.acl_roles is not None:
            document.acl_roles = _acl(body.acl_roles)
        document.updated_at = func.now()
        await audit.record(
            session,
            tenant_id=principal.tenant_id,
            actor_id=user_id,
            actor=principal.username,
            action="document.updated",
            target_type="document",
            target_id=document.id,
            details={
                "before": before,
                "after": {"title": document.title, "acl_roles": list(document.acl_roles)},
            },
        )
        await session.flush()
        await session.refresh(document)
        return DocumentOut.model_validate(document)


@router.delete("/{document_id}", status_code=204)
async def delete(
    document_id: uuid.UUID, request: Request, principal: Principal = Depends(editor_role)
) -> Response:
    async with tenant_session(request.app.state.sessions, principal.tenant_id) as session:
        user_id = await chat_repo.ensure_user_id(session, principal)
        document = await _visible(session, document_id, list(principal.roles))
        key = document.s3_key
        await audit.record(
            session,
            tenant_id=principal.tenant_id,
            actor_id=user_id,
            actor=principal.username,
            action="document.deleted",
            target_type="document",
            target_id=document.id,
            details={"title": document.title},
        )
        await session.delete(document)
    await request.app.state.store.delete(key)
    return Response(status_code=204)
