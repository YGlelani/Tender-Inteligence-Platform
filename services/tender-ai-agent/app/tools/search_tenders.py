"""
Tool: search_tenders
"""
import logging

from langchain_core.tools import tool

from ..config import get_settings
from ..upstream import list_tenders

logger = logging.getLogger(__name__)
settings = get_settings()


@tool
async def search_tenders(
    keyword: str = "",
    province: str = "",
    category: str = "",
    status: str = "Open",
    limit: int = 5,
) -> str:
    """
    Search for tenders by keyword, province, or category.

    Args:
        keyword: Text to find.
        province: Province name.
        category: Tender category.
        status: "Open" (default), "Closed", "Awarded".
        limit: Max results (default 5, max 20).

    Returns:
        A plain-text list of tenders.
    """
    params = {"limit": min(limit, 20), "status": status}
    if keyword:
        params["keyword"] = keyword
    if province:
        params["province"] = province
    if category:
        params["category"] = category

    logger.info("search_tenders: params=%s", params)

    try:
        data = await list_tenders(**params)  # Redis read-through cache (short TTL)
    except Exception as e:
        logger.error("search_tenders failed: %s", e)
        return (
            "TOOL_ERROR: Could not search tenders right now. "
            "Tell the user to try again. Do NOT invent tender data."
        )

    tenders = data.get("tenders", [])
    if not tenders:
        return "No tenders found matching those criteria."

    total = data.get("total", len(tenders))
    max_returned = min(limit, 5)

    lines = [f"Found {total} tenders total. Showing the first {max_returned}:"]
    for t in tenders[:max_returned]:
        title = (t.get("title") or "")[:100]
        org = (t.get("organisation_name") or t.get("organisation") or "")[:50]
        prov = t.get("province") or "N/A"
        date = t.get("closing_date") or "not specified"
        number = t.get("tender_number") or "N/A"
        lines.append(f"- [{number}] {title} — {org} ({prov}), closes: {date}")

    return "\n".join(lines)
