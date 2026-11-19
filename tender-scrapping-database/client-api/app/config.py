import os
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


class Settings:

    cors_origins: str = os.getenv("CORS_ORIGINS", "")


@lru_cache
def get_settings() -> Settings:
    return Settings()
