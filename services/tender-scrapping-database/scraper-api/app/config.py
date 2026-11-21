import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(ENV_PATH)


class Settings:
    base_url: str = os.getenv("ETENDERS_BASE_URL", "https://www.etenders.gov.za")

    status_ids: dict[str, int] = {
        "current": 1,
        "awarded": 2,
        "cancelled": 3,
        "closed": 4,
    }
    # The status a tender is saved with, by the eTenders list it was found on.
    status_names: dict[str, str] = {
        "current": "Open",
        "awarded": "Awarded",
        "cancelled": "Cancelled",
        "closed": "Closed",
    }

    table_wait_timeout_ms: int = int(os.getenv("ETENDERS_TABLE_TIMEOUT_MS", "20000"))
    max_pages_default: int = int(os.getenv("ETENDERS_MAX_PAGES_DEFAULT", "1000"))
    max_pages_hard_cap: int = int(os.getenv("ETENDERS_MAX_PAGES_HARD_CAP", "1000"))
    cache_ttl_seconds: int = int(os.getenv("ETENDERS_CACHE_TTL_SECONDS", "300"))

    user_agent: str = os.getenv(
        "ETENDERS_USER_AGENT",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    )


    api_key: str = os.getenv("API_KEY", "")

    # Background scraper loop
    scraper_loop_enabled: bool = os.getenv("SCRAPER_LOOP_ENABLED", "true").lower() == "true"
    scraper_loop_interval_seconds: int = int(os.getenv("SCRAPER_LOOP_INTERVAL_SECONDS", "1800"))
    scraper_loop_start_delay_seconds: int = int(os.getenv("SCRAPER_LOOP_START_DELAY_SECONDS", "5"))


@lru_cache
def get_settings() -> Settings:
    return Settings()
