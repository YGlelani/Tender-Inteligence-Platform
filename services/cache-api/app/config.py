import os
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


class Settings:
    # Redis connection
    redis_url: str = os.getenv("REDIS_URL", "redis://redis:6379/0")

    # Upstream API
    client_api_url: str = os.getenv("CLIENT_API_URL", "http://client-api:8001")
    upstream_timeout: float = float(os.getenv("UPSTREAM_TIMEOUT", "30"))

    # Cache TTLs (seconds)
    cache_ttl_list: int = int(os.getenv("CACHE_TTL_LIST", "120"))
    cache_ttl_search: int = int(os.getenv("CACHE_TTL_SEARCH", "60"))
    cache_ttl_detail: int = int(os.getenv("CACHE_TTL_DETAIL", "600"))
    cache_ttl_stats: int = int(os.getenv("CACHE_TTL_STATS", "300"))

    # Namespacing
    cache_key_prefix: str = os.getenv("CACHE_KEY_PREFIX", "lelani")

    # CORS
    cors_origins: str = os.getenv("CORS_ORIGINS", "*")


@lru_cache
def get_settings() -> Settings:
    return Settings()