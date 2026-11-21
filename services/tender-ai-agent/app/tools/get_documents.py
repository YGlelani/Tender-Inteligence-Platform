"""
Tool: get_tender_documents

Fetches the document list for a specific tender from client-api.
"""
import json
import logging

from langchain_core.tools import tool

from ..config import get_settings
from ..upstream import get_tender

logger = logging.getLogger(__name__)
settings = get_settings()


@tool
async def get_tender_documents(tender_number: str) -> str:
    """
    Get the list of documents attached to a specific tender.

    Use this when the user asks for the documents, files, PDFs,
    or attachments for a given tender number.

    Args:
        tender_number: The tender number (e.g., "CTICC 012/2027").

    Returns:
        A plain-text list of documents with name, type, and download URL.
        If the tender has no documents, say so.
    """
    logger.info("get_tender_documents: %s", tender_number)

    try:
        data = await get_tender(tender_number)  # Redis read-through cache
        if data is None:
            return (
                f"TOOL_ERROR: Tender '{tender_number}' was not found. "
                "Tell the user it wasn't found. Do NOT invent documents."
            )
    except Exception as e:
        logger.error("get_tender_documents failed: %s", e)
        return (
            "TOOL_ERROR: Could not fetch documents. "
            "Tell the user to try again."
        )

    docs = data.get("documents") or []

    if not docs:
        return f"Tender '{tender_number}' has no documents attached."

    lines = [f"Found {len(docs)} documents for tender '{tender_number}':", ""]
    for i, d in enumerate(docs, 1):
        name = d.get("name") or d.get("document_name") or "Untitled"
        dtype = d.get("type") or d.get("document_type") or "file"
        url_ = d.get("url") or d.get("document_url") or ""
        uploaded = d.get("date_uploaded") or ""
        lines.append(f"{i}. {name} ({dtype})")
        if url_:
            lines.append(f"   Download: {url_}")
        if uploaded:
            lines.append(f"   Uploaded: {uploaded}")
        lines.append("")

    lines.append("Present these to the user as a numbered list with the download links.")
    return "\n".join(lines)