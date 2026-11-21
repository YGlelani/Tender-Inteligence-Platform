"""Settings read from environment variables or a local .env file."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DATABASE_PATH = Path(os.getenv("DATABASE_PATH", "tenders-copy.db"))
MODEL_PATH = Path(os.getenv("MODEL_PATH", "models/category_model.joblib"))
REPORTS_DIR = Path(os.getenv("REPORTS_DIR", "reports"))
