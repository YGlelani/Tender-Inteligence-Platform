"""
Onboarding + overview endpoints.

The frontend uploads a business profile (PDF or website) and compliance
documents here; the agent processes them in the background and the overview
page reads the result from GET /agent/overview. No chat involved.
"""
import hashlib
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from ..auth import user_email, verify_token
from ..doc_ai import normalise_url, sniff_kind
from ..doc_catalog import get_type, public_catalogue
from ..onboarding import get_overview, invalidate, process_document, process_profile, refresh_insights, spawn
from ..vault import get_vault

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agent", tags=["onboarding"])

MAX_UPLOAD_BYTES = 15 * 1024 * 1024
EXTENSIONS = {b"%PDF": ".pdf", b"\x89PNG": ".png", b"\xff\xd8\xff": ".jpg", b"RIFF": ".webp"}
CONTENT_TYPES = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp"}


async def _read_upload(file: UploadFile) -> tuple[bytes, str]:
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    await file.close()
    if not data:
        raise HTTPException(400, "The file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Files must be 15 MB or smaller.")
    if not sniff_kind(data):
        raise HTTPException(400, "Upload a PDF, JPG or PNG file.")
    ext = next(e for magic, e in EXTENSIONS.items() if data.startswith(magic))
    return data, ext


@router.get("/onboarding/catalogue")
async def catalogue(user: dict = Depends(verify_token)) -> dict:
    return {"documents": public_catalogue()}


@router.post("/onboarding/profile", status_code=202)
async def upload_profile(
    file: Annotated[UploadFile | None, File(description="Business profile PDF")] = None,
    website: Annotated[str | None, Form(max_length=500)] = None,
    user: dict = Depends(verify_token),
) -> dict:
    email = user_email(user)
    vault = get_vault()
    website = (website or "").strip() or None

    if file is not None and file.filename:
        data, ext = await _read_upload(file)
        if ext != ".pdf":
            raise HTTPException(400, "The business profile must be a PDF.")
        path = vault.save_file(email, data, ext)
        vault.upsert_profile_source(email, "pdf", file.filename, path)
        spawn(process_profile(email, "pdf", data=data))
    elif website:
        url = normalise_url(website)
        vault.upsert_profile_source(email, "website", url, None)
        spawn(process_profile(email, "website", url=url))
    else:
        raise HTTPException(400, "Upload a business profile PDF or enter your website.")

    await invalidate(email)
    return {"status": "processing"}


@router.post("/onboarding/documents", status_code=202)
async def upload_document(
    doc_type: Annotated[str, Form()],
    file: Annotated[UploadFile, File(description="Compliance document (PDF, JPG or PNG)")],
    user: dict = Depends(verify_token),
) -> dict:
    email = user_email(user)
    t = get_type(doc_type)
    if t is None:
        raise HTTPException(400, "Unknown document type.")
    data, ext = await _read_upload(file)
    vault = get_vault()

    if not t["multiple"]:
        for old in vault.list_documents(email):
            if old["doc_type"] == doc_type:
                vault.delete_document(email, old["id"])

    path = vault.save_file(email, data, ext)
    doc = vault.add_document(
        email, doc_type, file.filename or f"{doc_type}{ext}", CONTENT_TYPES[ext], len(data),
        hashlib.sha256(data).hexdigest(), path,
    )
    spawn(process_document(email, doc["id"]))
    await invalidate(email)
    return {"id": doc["id"], "status": "processing"}


@router.delete("/onboarding/documents/{doc_id}")
async def delete_document(doc_id: str, user: dict = Depends(verify_token)) -> dict:
    email = user_email(user)
    if not get_vault().delete_document(email, doc_id):
        raise HTTPException(404, "Document not found.")
    await invalidate(email)
    spawn(refresh_insights(email))
    return {"deleted": doc_id}


@router.post("/onboarding/documents/{doc_id}/reprocess", status_code=202)
async def reprocess_document(doc_id: str, user: dict = Depends(verify_token)) -> dict:
    email = user_email(user)
    vault = get_vault()
    if not vault.get_document(email, doc_id):
        raise HTTPException(404, "Document not found.")
    vault.mark_processing(doc_id)
    spawn(process_document(email, doc_id))
    await invalidate(email)
    return {"id": doc_id, "status": "processing"}


@router.get("/onboarding/documents/{doc_id}/file")
async def download_document(doc_id: str, user: dict = Depends(verify_token)):
    doc = get_vault().get_document(user_email(user), doc_id)
    if not doc:
        raise HTTPException(404, "Document not found.")
    return FileResponse(doc["path"], media_type=doc["content_type"], filename=doc["filename"])


@router.get("/overview")
async def overview(user: dict = Depends(verify_token)) -> dict:
    return await get_overview(user_email(user))


@router.post("/overview/refresh", status_code=202)
async def refresh_overview(user: dict = Depends(verify_token)) -> dict:
    email = user_email(user)
    await invalidate(email)
    spawn(refresh_insights(email))
    return {"status": "refreshing"}
