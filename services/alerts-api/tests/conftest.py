import json
import os
import sqlite3
from datetime import date, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient

os.environ["JWT_SECRET"] = "ci-test-secret"

from app import db, documents, routers, service
from app.main import app

NO_DOCUMENTS = dict(documents.EMPTY)

SCHEMA = """
CREATE TABLE users(id INTEGER PRIMARY KEY, username TEXT, email TEXT, is_active INTEGER DEFAULT 1);
CREATE TABLE categories(id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE organisations(id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE tenders(id INTEGER PRIMARY KEY, tender_number TEXT, title TEXT, description TEXT,
    province TEXT, closing_date TEXT, published_date TEXT, status TEXT,
    category_id INTEGER, organisation_id INTEGER);
CREATE TABLE business_profiles(id INTEGER PRIMARY KEY, user_id INTEGER UNIQUE, business_name TEXT,
    industry TEXT, categories TEXT DEFAULT '[]', provinces TEXT DEFAULT '[]', keywords TEXT DEFAULT '[]',
    min_tender_value NUMERIC, max_tender_value NUMERIC, services_offered TEXT, company_description TEXT,
    province TEXT, cidb_grade TEXT, bbbee_level TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
INSERT INTO users(id, username, email) VALUES (1, 'owner@example.com', 'owner@example.com');
INSERT INTO categories(id, name) VALUES (1, 'Construction');
INSERT INTO organisations(id, name) VALUES (1, 'Public Works');
"""


def build_database(path):
    future = (date.today() + timedelta(days=20)).isoformat()
    past = (date.today() - timedelta(days=5)).isoformat()
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    tenders = [
        (1, "OPEN-1", "Road maintenance and paving", future),
        (2, "OPEN-2", "Paving of municipal roads", future),
        (3, "OLD-1", "Road maintenance and paving", past),
    ]
    for tender_id, number, title, closing in tenders:
        con.execute(
            "INSERT INTO tenders VALUES (?, ?, ?, ?, 'Limpopo', ?, ?, 'open', 1, 1)",
            (tender_id, number, title, title, closing, past),
        )
    con.execute(
        "INSERT INTO business_profiles(id, user_id, business_name, industry, categories, provinces, keywords) VALUES (1, 1, 'Baloyi Civils', 'Construction', ?, ?, ?)",
        (json.dumps(["Construction"]), json.dumps(["Limpopo"]), json.dumps(["road maintenance", "paving"])),
    )
    con.commit()
    con.close()


@pytest.fixture(autouse=True)
def no_ml_service(monkeypatch):
    """Tests never call the real tender-ml service: by default it behaves as unreachable."""
    async def unreachable(profile, tenders):
        return None

    monkeypatch.setattr(service, "shared_categories", unreachable)


@pytest.fixture
def client(tmp_path, monkeypatch):
    path = tmp_path / "tenders.db"
    build_database(path)
    monkeypatch.setattr(db, "DATABASE_PATH", str(path))
    state = {"details": NO_DOCUMENTS}

    async def fake_fetch(user_id, token):
        assert token
        return state["details"]

    monkeypatch.setattr(routers, "fetch_details", fake_fetch)
    token = jwt.encode({"sub": "owner@example.com", "exp": 4102444800}, "ci-test-secret", algorithm="HS256")
    with TestClient(app) as test_client:
        test_client.headers["Authorization"] = f"Bearer {token}"
        test_client.db_path = path
        test_client.documents = state
        yield test_client
