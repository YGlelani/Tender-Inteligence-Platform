"""
Answers "which tenders match my business profile?" in the chat and on the dashboard.

Matches come from Smart Alerts (alerts-api), so the dashboard, the chat and the
Smart Alerts page always show the same tenders. When Smart Alerts has no answer
for the user, the AI service's matcher is used instead.
"""
import logging
from contextvars import ContextVar

import httpx
from langchain_core.messages import SystemMessage

from .config import ai_service_headers, get_settings
from .intent import requested_count
from .onboarding import fetch_matches

logger = logging.getLogger(__name__)
settings = get_settings()

NO_PROFILE = ("You haven't uploaded your business documents yet. Upload them on Tender Scrapper, under "
              "Business Documents, then ask again and I'll show the tenders that suit your business.")
ALERTS_TIMEOUT_SECONDS = 20

# The signed-in user's token for the current chat message. It is not put in the graph's
# state or config, because LangGraph's checkpointer saves both.
current_token: ContextVar[str | None] = ContextVar("current_token", default=None)


def _same_email(first, second) -> bool:
    # Emails are compared without case, as the AI service does when deleting a user's profiles.
    return (first or "").strip().lower() == (second or "").strip().lower()


async def find_user_profile(email: str) -> dict | None:
    """The user's most recent business profile in the AI service, or None if they have none."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{settings.ai_service_url}/api/business-profiles", headers=ai_service_headers())
        resp.raise_for_status()
    for profile in reversed(resp.json()):
        if _same_email(profile.get("user_email"), email):
            return profile
    return None


async def smart_alerts_matches(token: str) -> list[dict] | None:
    """The user's matches from Smart Alerts, asked with their own sign-in.

    None when Smart Alerts has nothing for them (no profile or documents) or cannot be reached.
    """
    try:
        async with httpx.AsyncClient(timeout=ALERTS_TIMEOUT_SECONDS) as client:
            resp = await client.get(f"{settings.alerts_api_url}/matches",
                                    headers={"Authorization": f"Bearer {token}"})
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        found = resp.json()
    except (httpx.HTTPError, ValueError) as error:
        logger.warning("Smart Alerts matches unavailable, using the AI service matcher: %s", error)
        return None
    return found if isinstance(found, list) else None


async def user_matches(email: str, token: str | None) -> tuple[dict | None, list[dict], str]:
    """(the user's uploaded profile, their best-matching open tenders, where the matches came from)."""
    profile = await find_user_profile(email)
    if profile is None:
        return None, [], "none"
    found = await smart_alerts_matches(token) if token else None
    if found is not None:
        return profile, found, "smart_alerts"
    result = await fetch_matches(profile["id"])
    return profile, result.get("top_matches") or [], "ai_service"


def format_matches(profile: dict, matches: list[dict], count: int) -> str:
    business = profile.get("business_name") or "your business"
    shown = matches[:count]
    if not shown:
        return (f"No open tenders match {business}'s profile right now. New tenders arrive every day, "
                "so check again soon, or add more services to your profile.")
    lines = [f"Here are the {len(shown)} open tenders that best match {business}'s profile:", ""]
    for tender in shown:
        lines.append(
            f"- [{tender.get('tender_number') or 'N/A'}] {(tender.get('title') or '')[:100]} — "
            f"{tender.get('organisation') or ''} ({tender.get('province') or 'N/A'}), "
            f"closes: {tender.get('closing_date') or 'not specified'} — match {tender.get('score', 0)}/100"
        )
        if tender.get("reasons"):
            lines.append(f"  Why: {'; '.join(tender['reasons'][:3])}")
    lines += ["", "These come from your business profile. Update it to change your matches."]
    return "\n".join(lines)


async def run_matches(state: dict) -> dict:
    email = state.get("user_email")
    if not email:
        state["final_response"] = "Please sign in to see the tenders that match your business profile."
        return state
    try:
        profile, found, _ = await user_matches(email, current_token.get())
    except (httpx.HTTPError, ValueError, KeyError) as error:
        logger.error("run_matches failed: %s", error)
        state["error"] = "matches_failed"
        return state
    if profile is None:
        state["final_response"] = NO_PROFILE
        return state
    count = requested_count(state["user_input"])
    state["final_response"] = format_matches(profile, found, count)
    return state


async def user_context(email: str | None) -> list[SystemMessage]:
    """Who the user is, for questions about themselves ("what is my company called?").

    Only used for personal questions, whose answers are never cached for other users.
    """
    if not email:
        return []
    try:
        profile = await find_user_profile(email)
    except (httpx.HTTPError, ValueError) as error:
        logger.warning("Could not load the user's profile for chat context: %s", error)
        profile = None
    facts = [f"The signed-in user's email address is {email}. Their personal name is not known."]
    if profile:
        facts.append(
            f"Their company is {profile.get('business_name') or 'not named'}. "
            f"Industries: {', '.join(profile.get('industries') or []) or 'not given'}. "
            f"Services: {', '.join(profile.get('services') or []) or 'not given'}. "
            f"Provinces: {', '.join(profile.get('service_areas') or []) or 'not given'}."
        )
    else:
        facts.append("They have not uploaded a business profile yet.")
    return [SystemMessage(content=" ".join(facts))]
