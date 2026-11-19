"""The /api routes need the shared service key once AI_SERVICE_API_KEY is set."""
import importlib
import os
import sys
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

AI_DIR = Path(__file__).resolve().parents[1]
if str(AI_DIR) not in sys.path:
    sys.path.insert(0, str(AI_DIR))


class FakeStore:
    def list(self):
        return []


class FakeAI:
    async def is_available(self):
        return True


def client_with_key(key):
    """Import main with the given key; skip the lifespan so no database or model is needed."""
    os.environ["AI_SERVICE_API_KEY"] = key
    sys.modules.pop("main", None)
    main = importlib.import_module("main")
    main.app.state.tenders = FakeStore()
    main.app.state.ai = FakeAI()
    return TestClient(main.app)


class ServiceKeyTests(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("AI_SERVICE_API_KEY", None)
        sys.modules.pop("main", None)

    def test_api_rejects_missing_key(self):
        client = client_with_key("test-service-key")
        self.assertEqual(client.get("/api/tenders").status_code, 401)

    def test_api_rejects_wrong_key(self):
        client = client_with_key("test-service-key")
        response = client.get("/api/tenders", headers={"X-Internal-Key": "wrong"})
        self.assertEqual(response.status_code, 401)

    def test_api_accepts_correct_key(self):
        client = client_with_key("test-service-key")
        response = client.get("/api/tenders", headers={"X-Internal-Key": "test-service-key"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_business_profiles_are_protected(self):
        client = client_with_key("test-service-key")
        self.assertEqual(client.get("/api/business-profiles").status_code, 401)

    def test_health_stays_open(self):
        client = client_with_key("test-service-key")
        self.assertEqual(client.get("/health").status_code, 200)

    def test_without_configured_key_api_stays_reachable(self):
        # Lets the service roll out before the shared secret exists; the closed
        # port keeps it off the internet in the meantime.
        client = client_with_key("")
        self.assertEqual(client.get("/api/tenders").status_code, 200)


if __name__ == "__main__":
    unittest.main()
