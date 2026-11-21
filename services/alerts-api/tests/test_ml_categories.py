import asyncio
import json
import sqlite3

import httpx
import pytest

from app import ml_categories, service


class FakeClient:
    """Records each request to tender-ml and answers with a match for every tender id it gets."""

    def __init__(self, posts, fail=False):
        self.posts = posts
        self.fail = fail

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json):
        if self.fail:
            raise httpx.ConnectError("tender-ml is down")
        self.posts.append(json)
        matches = {tender["id"]: "Construction" for tender in json["tenders"]}
        return httpx.Response(200, json={"company_categories": ["Construction"], "matches": matches},
                              request=httpx.Request("POST", url))


@pytest.fixture
def posts(monkeypatch):
    sent = []
    monkeypatch.setattr(ml_categories.httpx, "AsyncClient", lambda timeout: FakeClient(sent))
    return sent


def _tenders(count):
    return [{"id": number, "title": f"Tender {number}", "category": "Construction"} for number in range(count)]


def test_company_uses_what_the_business_does():
    profile = {"industry": "Construction", "document_industries": ["Civil works"], "services_offered": "roads",
               "keywords": ["paving", ""], "company_description": "We build roads."}

    assert ml_categories.company(profile) == {
        "industries": ["Construction", "Civil works"], "services": ["roads"],
        "keywords": ["paving"], "description": "We build roads.",
    }


def test_tenders_are_sent_in_batches_below_the_service_limit(posts):
    result = asyncio.run(ml_categories.shared_categories({"industry": "Construction"}, _tenders(4500)))

    assert [len(post["tenders"]) for post in posts] == [2000, 2000, 500]
    assert len(result) == 4500
    assert result["4499"] == "Construction"


def test_no_tenders_needs_no_request(posts):
    assert asyncio.run(ml_categories.shared_categories({}, [])) == {}
    assert posts == []


def test_unreachable_service_returns_none(monkeypatch):
    monkeypatch.setattr(ml_categories.httpx, "AsyncClient", lambda timeout: FakeClient([], fail=True))

    assert asyncio.run(ml_categories.shared_categories({}, _tenders(3))) is None


def test_matches_show_the_ml_category_reason(client, monkeypatch):
    con = sqlite3.connect(client.db_path)
    con.execute("UPDATE business_profiles SET categories = ?", (json.dumps(["Electrical"]),))
    con.commit()
    con.close()

    async def ml_says_construction(profile, tenders):
        return {str(tender["id"]): "Construction" for tender in tenders}

    monkeypatch.setattr(service, "shared_categories", ml_says_construction)

    matches = {item["tender_number"]: item for item in client.get("/matches").json()}
    assert "Category matches your business (ML: Construction)" in matches["OPEN-1"]["reasons"]
