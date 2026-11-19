"""
Configuration for the AI Agent service.

All values come from environment variables with sensible defaults.
The defaults assume we're running inside the shared Docker network
(`tender-scrapping-net`), where containers reach each other by name.
"""
import os
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


class Settings:
   
    # ---- Azure AI (Mistral LLM) ----
    azure_ai_endpoint: str = os.getenv("AZURE_AI_ENDPOINT", "")
    azure_ai_deployment: str = os.getenv(
        "AZURE_AI_DEPLOYMENT",
        "mistral-small-2503",
    )
    azure_ai_api_key: str = os.getenv("AZURE_AI_API_KEY", "")

    # Temperature 0 = deterministic; useful for structured extraction.
    azure_ai_temperature: float = float(
        os.getenv("AZURE_AI_TEMPERATURE", "0")
    )


    # ---- Upstream services (the tools) ----
    client_api_url: str = os.getenv("CLIENT_API_URL", "http://client-api:8001")
    ai_service_url: str = os.getenv("AI_SERVICE_URL", "http://ai:8002")
    # Smart Alerts (alerts-api): the dashboard and chat show its matches, so all three agree.
    alerts_api_url: str = os.getenv("ALERTS_API_URL", "http://alerts-api:9005").rstrip("/")
    # Shared with the AI service, which rejects /api calls without it once it is set.
    ai_service_api_key: str = os.getenv("AI_SERVICE_API_KEY", "").strip()
    # Shared with Signup-api, which calls /internal/accounts/delete with it.
    # Unset: account deletion answers 503.
    account_deletion_key: str = os.getenv("ACCOUNT_DELETION_KEY", "").strip()
    # tender-ml predicts a tender category from text. When it is down, search works as before.
    tender_ml_url: str = os.getenv("TENDER_ML_URL", "http://tender-ml:9004").rstrip("/")
    # Kept short: a slow prediction must never hold up a search reply.
    tender_ml_timeout: float = float(os.getenv("TENDER_ML_TIMEOUT", "2"))

    # ---- Redis (conversation memory) ----
    redis_url: str = os.getenv("REDIS_URL", "redis://redis:6379/0")

    # ---- Embeddings + vector search (Redis Query Engine, Redis 8+) ----
    # Azure deployment name of the embedding model.
    embed_model: str = os.getenv("EMBED_MODEL", "text-embedding-3-small")
    embed_batch_size: int = int(os.getenv("EMBED_BATCH_SIZE", "64"))
    # Embeddings are deterministic per (model, text), so they can live a long time.
    embed_cache_ttl: int = int(os.getenv("EMBED_CACHE_TTL", str(60 * 60 * 24 * 30)))
    # One embedding request may take this long before it is abandoned (seconds).
    embed_timeout: float = float(os.getenv("EMBED_TIMEOUT", "8"))
    # After an embedding failure, skip embeddings for this long instead of
    # making every request wait for the same failure again.
    embed_breaker_seconds: int = int(os.getenv("EMBED_BREAKER_SECONDS", "60"))
    # Only needed when the embedding deployment lives on a different Azure resource.
    azure_embed_endpoint: str = os.getenv("AZURE_EMBED_ENDPOINT", "")
    azure_embed_api_key: str = os.getenv("AZURE_EMBED_API_KEY", "")

    # ---- Semantic cache for LLM answers ----
    semantic_cache_enabled: bool = os.getenv("SEMANTIC_CACHE_ENABLED", "true").lower() in ("1", "true", "yes")
    # Cosine similarity (0..1) a new question needs to reuse a cached answer.
    # High on purpose: "B-BBEE level 1" vs "level 2" are ~0.93 similar.
    semantic_cache_threshold: float = float(os.getenv("SEMANTIC_CACHE_THRESHOLD", "0.95"))
    semantic_cache_ttl: int = int(os.getenv("SEMANTIC_CACHE_TTL", "86400"))
    # Max seconds the "same meaning" cache lookup may add before the LLM runs.
    semantic_cache_lookup_budget: float = float(os.getenv("SEMANTIC_CACHE_LOOKUP_BUDGET", "1.5"))

    # ---- Read-through cache for client-api calls ----
    upstream_ttl_detail: int = int(os.getenv("UPSTREAM_CACHE_TTL_DETAIL", "600"))
    upstream_ttl_list: int = int(os.getenv("UPSTREAM_CACHE_TTL_LIST", "120"))
    upstream_ttl_not_found: int = int(os.getenv("UPSTREAM_CACHE_TTL_404", "60"))

    # ---- Semantic tender index ----
    # How often open tenders are re-synced into the vector index (seconds; 0 = off).
    tender_sync_interval: int = int(os.getenv("TENDER_SYNC_INTERVAL", "21600"))
    tender_sync_max: int = int(os.getenv("TENDER_SYNC_MAX", "3000"))

    # ---- Onboarding document vault ----
    # Uploaded compliance documents + the SQLite index live here (mount a volume).
    data_dir: str = os.getenv("AGENT_DATA_DIR", "/data")
    # Deployment used for scanned PDFs / photos. Mistral Small 3.1 reads images,
    # so by default it is the same deployment as the text model.
    azure_ai_vision_deployment: str = (
        os.getenv("AZURE_AI_VISION_DEPLOYMENT")
        or os.getenv("AZURE_AI_DEPLOYMENT", "mistral-small-2503")
    )

    # ---- Agent behaviour ----
    agent_max_iterations: int = int(os.getenv("AGENT_MAX_ITERATIONS", "4"))
    agent_timeout_seconds: int = int(os.getenv("AGENT_TIMEOUT_SECONDS", "45"))
    # One LLM request may take this long before it is abandoned (seconds).
    llm_timeout: float = float(os.getenv("LLM_TIMEOUT", "30"))

    # ---- CORS ----
    cors_origins: str = os.getenv("CORS_ORIGINS", "*")

    # ---- Optional API key protection ----
    agent_api_key: str = os.getenv("AGENT_API_KEY", "")


@lru_cache
def get_settings() -> Settings:
    return Settings()


def ai_service_headers() -> dict[str, str]:
    """Headers for every call to the AI service: the shared key, when one is configured."""
    key = get_settings().ai_service_api_key
    return {"X-Internal-Key": key} if key else {}