"""Account deletion: the AI agent asks this service to delete a user's business profiles."""
import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

AI_DIR = Path(__file__).resolve().parents[1]
if str(AI_DIR) not in sys.path:
    sys.path.insert(0, str(AI_DIR))

from store import TenderStore  # noqa: E402

PROFILE = {
    "business_name": "Co",
    "registration_number": "2020/000001/07",
    "description": "Builders",
    "industries": ["construction"],
    "services": ["roads"],
    "service_areas": ["Gauteng"],
    "certifications": [],
    "contact_email": "info@company.co.za",
    "website": None,
}


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = TenderStore(str(Path(self.tmp.name) / "ai.db"))
        self.store.initialize()
        self.store.create_business_profile(PROFILE, user_email="tenders@company.co.za")
        self.store.create_business_profile(PROFILE, user_email="Tenders@Company.co.za ")
        self.store.create_business_profile(PROFILE, user_email="other@company.co.za")

    def tearDown(self):
        self.tmp.cleanup()

    def test_deletes_all_of_the_users_profiles(self):
        deleted = self.store.delete_business_profiles_by_email("tenders@company.co.za")

        self.assertEqual(deleted, 2)
        owners = [p["user_email"] for p in self.store.list_business_profiles()]
        self.assertEqual(owners, ["other@company.co.za"])

    def test_unknown_email_deletes_nothing(self):
        self.assertEqual(self.store.delete_business_profiles_by_email("nobody@company.co.za"), 0)
        self.assertEqual(len(self.store.list_business_profiles()), 3)


class FakeStore:
    def __init__(self):
        self.deleted = []

    def delete_business_profiles_by_email(self, email):
        self.deleted.append(email)
        return 1


class RouteTests(unittest.TestCase):
    def setUp(self):
        os.environ["AI_SERVICE_API_KEY"] = "test-service-key"
        sys.modules.pop("main", None)
        self.main = importlib.import_module("main")
        self.store = FakeStore()
        self.main.app.state.tenders = self.store
        self.client = TestClient(self.main.app)

    def tearDown(self):
        os.environ.pop("AI_SERVICE_API_KEY", None)
        sys.modules.pop("main", None)

    def post(self, headers):
        return self.client.post(
            "/api/business-profiles/delete-by-email",
            json={"user_email": "tenders@company.co.za"},
            headers=headers,
        )

    def test_needs_the_service_key(self):
        self.assertEqual(self.post({}).status_code, 401)
        self.assertEqual(self.store.deleted, [])

    def test_deletes_with_the_service_key(self):
        response = self.post({"X-Internal-Key": "test-service-key"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"deleted": 1})
        self.assertEqual(self.store.deleted, ["tenders@company.co.za"])


if __name__ == "__main__":
    unittest.main()
