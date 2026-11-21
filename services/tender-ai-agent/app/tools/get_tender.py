"""
Tool: get_tender_details
"""
import json
import logging

from langchain_core.tools import tool

from ..config import get_settings
from ..upstream import get_tender

logger = logging.getLogger(__name__)
settings = get_settings()


@tool
async def get_tender_details(tender_number: str) -> str:
    """
    Get full details of a single tender by tender number.

    Args:
        tender_number: The tender number (e.g., "CTICC 012/2027").

    Returns:
        Plain-text details: dates, organisation, contacts, briefing and document names.
    """
    logger.info("get_tender_details: %s", tender_number)

    try:
        data = await get_tender(tender_number)  # Redis read-through cache
        if data is None:
            return (
                f"TOOL_ERROR: Tender '{tender_number}' was not found. "
                "Tell the user it wasn't found. Do NOT invent details."
            )
    except Exception as e:
        logger.error("get_tender_details failed: %s", e)
        return (
            "TOOL_ERROR: Could not fetch tender details. "
            "Tell the user to try again."
        )

    return summarize_tender(data)


def summarize_tender(t: dict) -> str:
    """Compact plain text for the LLM. The full JSON dump made prompts large and slow."""
    def line(label, *keys):
        for k in keys:
            v = t.get(k)
            if v not in (None, "", [], {}):
                return f"{label}: {v}"
        return None

    briefing = None
    if t.get("has_briefing"):
        parts = ["compulsory" if t.get("is_compulsory") else "optional",
                 str(t.get("briefing_date_time") or ""), str(t.get("briefing_venue") or "")]
        briefing = "Briefing session: " + ", ".join(p for p in parts if p)

    docs = t.get("documents") or []
    doc_lines = [f"  - {d.get('name') or d.get('document_name') or 'Untitled'}" for d in docs[:15]]

    lines = [
        line("Tender number", "tender_number"),
        line("Title", "title"),
        line("Organisation", "organisation_name", "organisation"),
        line("Category", "category_name", "category"),
        line("Province", "province"),
        line("Status", "status"),
        line("Published", "published_date"),
        line("Closing date", "closing_date"),
        briefing,
        line("Contact person", "contact_person"),
        line("Contact email", "contact_email"),
        line("Contact phone", "contact_telephone"),
        line("Description", "description"),
    ]
    out = [l for l in lines if l]
    if out and len(out[-1]) > 1500:
        out[-1] = out[-1][:1500] + "..."
    if doc_lines:
        out.append(f"Documents ({len(docs)}):")
        out.extend(doc_lines)
    return "\n".join(out) or json.dumps(t, default=str)[:3000]