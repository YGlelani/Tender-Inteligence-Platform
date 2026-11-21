import os

from dotenv import load_dotenv

load_dotenv()

DATABASE_PATH = os.getenv("DATABASE_PATH", "/data/tenders.db")
SCAN_INTERVAL_SECONDS = max(60, int(os.getenv("ALERT_SCAN_INTERVAL_SECONDS", "300")))
AGENT_URL = os.getenv("AGENT_URL", "http://tender-agent-api:9000").rstrip("/")
# The ML category model. When it is unreachable, matching works exactly as before.
TENDER_ML_URL = os.getenv("TENDER_ML_URL", "http://tender-ml:9004").rstrip("/")
TENDER_ML_TIMEOUT = float(os.getenv("TENDER_ML_TIMEOUT", "10"))
