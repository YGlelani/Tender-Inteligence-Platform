"""
Tool: get_bid_strategy

Fetches a rule-based bid strategy from the AI service.
No LLM involved — the AI service produces the strategy deterministically.
"""
import logging

import httpx
from langchain_core.tools import tool

from ..config import ai_service_headers, get_settings
from ..upstream import get_tender

logger = logging.getLogger(__name__)
settings = get_settings()


@tool
async def get_bid_strategy(
    tender_number: str | None = None,
    profile_id: str | int | None = None
) -> str:
    """
    Generate a bid strategy for a specific tender and business profile.

    ONLY use this tool if you know BOTH a real tender_number AND a real profile_id.
    If either is missing, return TOOL_ERROR and do NOT call this tool.

    Args:
        tender_number: The tender number (e.g. "01/2026-27").
        profile_id: The profile id (an integer from upload_business_profile).

    Returns:
        A detailed, readable bid strategy with requirements, documents,
        tactics, and next steps.
    """
    # 1. Guard clauses before we try to parse
    if not tender_number or not str(tender_number).strip():
        return "TOOL_ERROR: No tender_number provided. Ask the user which tender they want a strategy for."
    
    if profile_id is None or str(profile_id).strip().lower() in ("", "none", "null", "undefined"):
        return "TOOL_ERROR: No profile_id provided. Ask the user to upload their business profile first."

    try:
        profile_id = int(profile_id)
    except (ValueError, TypeError):
        return f"TOOL_ERROR: Invalid profile_id '{profile_id}'. It must be a number."

    try:
        # 2. Find the tender in client-api (Redis read-through cache)
        tender = await get_tender(str(tender_number))
        if tender is None:
            return (
                f"TOOL_ERROR: Tender '{tender_number}' was not found. "
                "Tell the user it wasn't found. Do NOT invent details."
            )
        async with httpx.AsyncClient(timeout=60) as client:

            # 3. Create the tender in AI service (idempotent enough for our scale)
            create_resp = await client.post(
                f"{settings.ai_service_url}/api/tenders",
                headers=ai_service_headers(),
                json={
                    "title": tender.get("title", "Untitled"),
                    "organisation": tender.get("organisation_name") or tender.get("organisation"),
                    "description": tender.get("description") or tender.get("title", ""),
                    "source_url": tender.get("tender_url") or tender.get("source_url"),
                    "closing_date": str(tender.get("closing_date")) if tender.get("closing_date") else None,
                },
            )
            create_resp.raise_for_status()
            tender_id = create_resp.json()["id"]

            # 4. Generate the bid strategy (rule-based)
            strategy_resp = await client.post(
                f"{settings.ai_service_url}/api/tenders/{tender_id}/bid-strategy/{profile_id}",
                headers=ai_service_headers(),
            )
            strategy_resp.raise_for_status()
            data = strategy_resp.json()

    except httpx.HTTPStatusError as e:
        logger.error("get_bid_strategy HTTP error: %s", e)
        return (
            "TOOL_ERROR: The AI service returned an error. "
            "Tell the user to try again in a moment."
        )
    except Exception as e:
        logger.error("get_bid_strategy failed: %s", e)
        return (
            "TOOL_ERROR: Could not generate the strategy right now. "
            "Tell the user to try again."
        )

    # ---------------- Format ----------------
    lines: list[str] = []

    lines.append(f"# Bid Strategy for {tender_number}")
    lines.append("")
    if data.get("industry_detected"):
        lines.append(f"**Industry detected:** {data['industry_detected']}")
    lines.append(f"**Suitability score:** {data.get('suitability_score', 0)}/100")
    if data.get("deadlines", {}).get("days_remaining"):
        lines.append(f"**Days until closing:** {data['deadlines']['days_remaining']}")
    lines.append("")

    lines.append("## Executive Summary")
    lines.append(data.get("summary", ""))
    lines.append("")

    lines.append("## Why This Tender Fits Your Business")
    for item in data.get("why_this_fits", []):
        lines.append(f"- {item}")
    lines.append("")

    lines.append("## Key Requirements")
    for item in data.get("key_requirements", []):
        lines.append(f"- {item}")
    lines.append("")

    lines.append("## Documents to Prepare")
    for i, item in enumerate(data.get("documents_to_prepare", []), 1):
        lines.append(f"{i}. {item}")
    lines.append("")

    lines.append("## Winning Strategy")
    for item in data.get("winning_strategy", []):
        lines.append(f"- {item}")
    lines.append("")

    lines.append("## Differentiators to Highlight")
    for item in data.get("differentiators_to_highlight", []):
        lines.append(f"- {item}")
    lines.append("")

    lines.append("## Gaps and Risks to Address")
    for item in data.get("gaps_to_address", []):
        lines.append(f"- {item}")
    lines.append("")

    lines.append("## Next Steps")
    for i, item in enumerate(data.get("next_steps", []), 1):
        lines.append(f"{i}. {item}")
    lines.append("")

    evidence = data.get("evidence") or {}
    if evidence:
        lines.append("## Evidence (quoted from the tender)")
        for label, quote in evidence.items():
            lines.append(f"- **{label}**: \"{quote}\"")
        lines.append("")

    lines.append(
        "Now write your final answer to the user. Present this strategy in a "
        "clear, professional, and well-formatted way. Do NOT call any more tools."
    )

    return "\n".join(lines)