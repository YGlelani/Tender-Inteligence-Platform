"""
Account deletion, called by Signup-api when a user deletes their account.

    POST /internal/accounts/delete   {"email": "..."}
    X-Internal-Key: <ACCOUNT_DELETION_KEY>   (the same value is set in Signup-api)

Deletes everything this service holds for the user:
  - the AI service's copies of their business profile. This must succeed:
    otherwise nothing else is deleted and the caller gets 502, so the user can
    simply try again;
  - their uploaded files, document records, profile record and insights;
  - Redis entries about them: overview, tender matches, the extraction results
    for their documents and website, cached profile extractions (a cache shared
    by all users, cleared completely) and their AI assistant history;
  - their conversation state held in memory by the AI assistant.
"""
import hashlib
import logging
import secrets

import httpx
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from .config import ai_service_headers, get_settings
from .vault import _user_folder, get_vault

logger = logging.getLogger(__name__)
router = APIRouter(tags=["internal"])


class AccountDeletionRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=320)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


# Looked up when needed, so this module does not load Redis or the AI graph.
def _cache():
    from .cache import get_cache
    return get_cache()


def _memory():
    from .memory import get_memory
    return get_memory()


def _checkpointer():
    from . import graph
    compiled = graph._graph
    return getattr(compiled, "checkpointer", None) if compiled is not None else None


def _forget_onboarding_state(email: str) -> None:
    from . import onboarding
    onboarding._insight_locks.pop(email, None)
    onboarding._dirty.discard(email)


async def delete_ai_service_profiles(email: str) -> int:
    """Delete the AI service's copies of the user's business profile."""
    settings = get_settings()
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            f"{settings.ai_service_url}/api/business-profiles/delete-by-email",
            headers=ai_service_headers(),
            json={"user_email": email},
        )
    response.raise_for_status()
    return int(response.json().get("deleted", 0))


def cache_patterns(email: str, profile: dict | None, documents: list[dict]) -> list[str]:
    """Redis key patterns for cached data about this user (see onboarding.py and doc_ai.py)."""
    patterns = [f"overview:v1:{_sha256(email)}", "profileai:*"]
    if profile and profile.get("ai_profile_id"):
        patterns.append(f"matches:v1:{profile['ai_profile_id']}")
    if profile and profile.get("source_kind") == "website" and profile.get("source_ref"):
        patterns.append(f"site:*:{_sha256(profile['source_ref'])}")
    for doc in documents:
        patterns.append(f"docai:*:{doc['doc_type']}:{doc['sha256']}")
    return patterns


async def _delete_matching(store, patterns: list[str]) -> int:
    if store is None:
        return 0
    deleted = 0
    for pattern in patterns:
        try:
            deleted += await store.delete_matching(pattern)
        except Exception:
            logger.exception("Could not delete cached entries during account deletion")
    return deleted


def forget_conversations(thread_prefix: str) -> int:
    """Drop the AI assistant's in-memory conversation state for these threads."""
    saver = _checkpointer()
    if saver is None:
        return 0
    threads = [t for t in list(getattr(saver, "storage", {})) if str(t).startswith(thread_prefix)]
    for thread in threads:
        if hasattr(saver, "delete_thread"):
            saver.delete_thread(thread)
        else:
            saver.storage.pop(thread, None)
            for attr in ("writes", "blobs"):
                table = getattr(saver, attr, None)
                if isinstance(table, dict):
                    for key in [k for k in table if isinstance(k, tuple) and k and k[0] == thread]:
                        table.pop(key, None)
    return len(threads)


@router.post("/internal/accounts/delete")
async def delete_account(
    body: AccountDeletionRequest, x_internal_key: str = Header(default="")
) -> dict:
    key = get_settings().account_deletion_key
    if not key:
        raise HTTPException(503, "Account deletion is not configured.")
    if not secrets.compare_digest(x_internal_key.encode(), key.encode()):
        raise HTTPException(401, "Invalid or missing service key.")

    email = body.email.strip().lower()
    owner = _user_folder(email)  # the same hash names their chat sessions
    vault = get_vault()
    profile = vault.get_profile(email)
    documents = vault.list_documents(email)

    try:
        ai_profiles = await delete_ai_service_profiles(email)
    except Exception:
        logger.exception("The AI service did not delete the business profiles")
        raise HTTPException(502, "The AI service could not delete the business profile.")

    cache_keys = await _delete_matching(_cache(), cache_patterns(email, profile, documents))
    chat_keys = await _delete_matching(_memory(), [f"chat:history:user:{owner}:*"])
    rows = vault.delete_user(email)
    conversations = forget_conversations(f"user:{owner}:")
    try:
        _forget_onboarding_state(email)
    except Exception:
        logger.exception("Could not clear onboarding state during account deletion")

    result = {
        "deleted": True,
        "ai_profiles": ai_profiles,
        **rows,
        "cache_keys": cache_keys,
        "chat_keys": chat_keys,
        "conversations": conversations,
    }
    # Counts only; the email address is never logged.
    logger.info("Deleted account data: %s", result)
    return result
