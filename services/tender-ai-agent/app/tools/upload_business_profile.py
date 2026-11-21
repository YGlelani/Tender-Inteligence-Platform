"""
Tool: upload_business_profile

Uploads a business profile PDF to the AI service and gets back
the parsed profile plus matching tenders. Rule-based, no LLM.
"""
import logging
from pathlib import Path

import httpx
from langchain_core.tools import tool

from ..config import ai_service_headers, get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


@tool
async def upload_business_profile(pdf_path: str) -> str:
    """
    Upload a business profile PDF. The AI service extracts the profile,
    finds matching open tenders, and returns the top matches.

    Use this tool when the user provides a path to a business profile PDF.

    Args:
        pdf_path: Full path to the business profile PDF (e.g. "/tmp/profile.pdf").

    Returns:
        A short summary of the profile and the top matching tenders.
    """
    path = Path(pdf_path)
    if not path.exists():
        return (
            f"TOOL_ERROR: File not found at '{pdf_path}'. "
            "Tell the user the file could not be found."
        )

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            with path.open("rb") as f:
                resp = await client.post(
                    f"{settings.ai_service_url}/api/ai/business-profile/from-pdf",
                    headers=ai_service_headers(),
                    files={"file": (path.name, f, "application/pdf")},
                )
            resp.raise_for_status()
            result = resp.json()

    except httpx.HTTPStatusError as e:
        logger.error("upload_business_profile HTTP error: %s", e)
        return (
            "TOOL_ERROR: The AI service returned an error. "
            "Tell the user to try again in a moment."
        )
    except Exception as e:
        logger.error("upload_business_profile failed: %s", e)
        return (
            "TOOL_ERROR: Could not process the business profile. "
            "Tell the user to try again in a moment."
        )

    profile = result.get("profile", {})
    matches = result.get("top_matches", [])
    profile_id = result.get("profile_id")

    lines = [
        f"SUCCESS: profile_id={profile_id}",
        f"Business: {profile.get('business_name', 'Unknown')}",
        f"Industries: {', '.join(profile.get('industries', []))}",
        f"Services: {', '.join(profile.get('services', []))}",
        f"Service areas: {', '.join(profile.get('service_areas', [])) or 'Not specified'}",
        "",
        f"Found {len(matches)} matching tenders (out of {result.get('tenders_scanned', 0)} scanned):",
        "",
    ]

    for i, m in enumerate(matches[:5], 1):
        lines.append(f"{i}. [{m['tender_number']}] {m['title']}")
        lines.append(
            f"   {m['organisation']} — {m['province']} — score {m['score']}/100"
        )
        if m.get("reasons"):
            for r in m["reasons"][:3]:
                lines.append(f"     • {r}")
        lines.append("")

    lines.append(
        "Now write your final answer to the user with these matches. "
        "Do NOT call any more tools."
    )

    return "\n".join(lines)