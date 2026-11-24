"""Documents: streaming upload, status, download, retry, delete (contract UPL-*, FILE-05, OWN-03, ISO-03).

The upload route reads the raw request stream itself (no FastAPI ``File`` parameters), so nothing is buffered before
the ownership check and the per-file limit apply (UPL-01, UPL-02).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Path, Query, Request, Response, status
from fastapi.responses import FileResponse
from pydantic import BaseModel

from backend.app.api.deps import CurrentUser, DbSession
from backend.app.core.errors import ApiError
from backend.app.db.models import Document
from backend.app.services.documents import DocumentService, reason_for
from backend.app.services.jobs import JobRunner
from backend.app.services.uploads import receive_files

router = APIRouter(tags=["documents"])

#: Exact upload route, exempt from the generic JSON body limit (it enforces its own per-file limit).
UPLOAD_ROUTE = ("POST", r"/api/v1/courses/[^/]+/documents")

MEDIA_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}

Id = Annotated[str, Path()]


def get_documents(request: Request) -> DocumentService:
    service: DocumentService = request.app.state.documents
    return service


def get_jobs(request: Request) -> JobRunner:
    runner: JobRunner = request.app.state.jobs
    return runner


Documents = Annotated[DocumentService, Depends(get_documents)]


class DocumentOut(BaseModel):
    id: str
    course_id: str
    file_name: str
    file_type: str
    size_bytes: int
    status: str
    progress: int
    error_code: str | None
    error_message: str | None
    page_count: int | None
    chunk_count: int | None
    created_at: datetime
    updated_at: datetime
    ready_at: datetime | None


class UploadedDocument(DocumentOut):
    duplicate: bool


class UploadResponse(BaseModel):
    documents: list[UploadedDocument]


class DocumentList(BaseModel):
    items: list[DocumentOut]
    limit: int
    offset: int


def _out(document: Document) -> dict[str, object]:
    return {
        "id": document.id, "course_id": document.course_id, "file_name": document.file_name,
        "file_type": document.file_type, "size_bytes": document.size_bytes, "status": document.status,
        "progress": document.progress, "error_code": document.error_code,
        "error_message": reason_for(document.error_code), "page_count": document.page_count,
        "chunk_count": document.chunk_count, "created_at": document.created_at, "updated_at": document.updated_at,
        "ready_at": document.ready_at,
    }


@router.post("/courses/{course_id}/documents", status_code=status.HTTP_202_ACCEPTED, response_model=UploadResponse)
async def upload_documents(course_id: Id, request: Request, user: CurrentUser, session: DbSession,
                           documents: Documents) -> UploadResponse:
    settings = request.app.state.settings
    course = documents.precheck_upload(session, user, course_id)  # before any byte is stored (UPL-01)
    declared = request.headers.get("content-length")
    ceiling = settings.max_files_per_request * settings.max_upload_bytes + 1024 * 1024
    if declared is not None and declared.isdigit() and int(declared) > ceiling:
        raise ApiError(413, "The upload is larger than the limit.", code="file_too_large")
    files = await receive_files(request.headers.get("content-type"), request.stream(), request.app.state.storage,
                                max_file_bytes=settings.max_upload_bytes, max_files=settings.max_files_per_request)
    accepted = documents.accept(session, user, course, files)
    get_jobs(request).notify()
    return UploadResponse(documents=[UploadedDocument(**_out(a.document), duplicate=a.duplicate) for a in accepted])


@router.get("/courses/{course_id}/documents", response_model=DocumentList)
def list_documents(course_id: Id, user: CurrentUser, session: DbSession, documents: Documents,
                   limit: Annotated[int, Query(ge=1, le=100)] = 50,
                   offset: Annotated[int, Query(ge=0, le=100_000)] = 0) -> DocumentList:
    items = documents.list_for_course(session, user, course_id, limit=limit, offset=offset)
    return DocumentList(items=[DocumentOut(**_out(d)) for d in items], limit=limit, offset=offset)


@router.get("/documents/{document_id}", response_model=DocumentOut)
def get_document(document_id: Id, user: CurrentUser, session: DbSession, documents: Documents) -> DocumentOut:
    return DocumentOut(**_out(documents.get(session, user, document_id)))


@router.get("/documents/{document_id}/file")
def download_document(document_id: Id, user: CurrentUser, session: DbSession, documents: Documents) -> FileResponse:
    """The stored original (FILE-05): verified media type, attachment disposition, never inline."""
    document = documents.get(session, user, document_id)
    encoded = quote(document.file_name, safe="")
    return FileResponse(
        documents.file_path_for(document),
        media_type=MEDIA_TYPES[document.file_type],
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"},
    )


@router.post("/documents/{document_id}/retry", status_code=status.HTTP_202_ACCEPTED, response_model=DocumentOut)
def retry_document(document_id: Id, request: Request, user: CurrentUser, session: DbSession,
                   documents: Documents) -> DocumentOut:
    document = documents.retry(session, user, document_id)
    get_jobs(request).notify()
    return DocumentOut(**_out(document))


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(document_id: Id, user: CurrentUser, session: DbSession, documents: Documents) -> Response:
    documents.delete(session, user, document_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
