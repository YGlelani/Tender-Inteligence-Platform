import sqlite3

import pandas as pd
import pytest

from tender_ml.classifier import build_pipeline

SCHEMA = """
CREATE TABLE categories (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
CREATE TABLE organisations (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
CREATE TABLE tenders (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT,
    organisation_id INTEGER REFERENCES organisations(id),
    category_id INTEGER REFERENCES categories(id)
);
"""

TOPICS = {
    "Security": "security guarding services for {place}",
    "Cleaning": "cleaning and hygiene services for {place}",
    "Catering": "catering and meals for {place}",
    "Stationery": "stationery and printing paper for {place}",
}
PLACES = ["head office", "regional office", "clinic", "school", "depot", "library", "hospital", "airport"]


@pytest.fixture
def database_path(tmp_path):
    path = tmp_path / "tenders.db"
    with sqlite3.connect(path) as connection:
        connection.executescript(SCHEMA)
        connection.executemany(
            "INSERT INTO categories (id, name) VALUES (?, ?)",
            [(1, "Security"), (2, "Uncategorised")],
        )
        connection.execute("INSERT INTO organisations (id, name) VALUES (1, 'Department of Health')")
        connection.executemany(
            "INSERT INTO tenders (id, title, description, organisation_id, category_id) VALUES (?, ?, ?, ?, ?)",
            [
                (1, "Guarding services", "Guarding services", 1, 1),
                (2, "Office cleaning", None, None, 2),
                (3, "Catering", "Meals for staff", 1, None),
            ],
        )
    connection.close()
    return path


@pytest.fixture(scope="session")
def training_data():
    rows = [
        {"text": template.format(place=place), "category": category}
        for category, template in TOPICS.items()
        for place in PLACES
    ]
    return pd.DataFrame(rows)


@pytest.fixture(scope="session")
def trained_pipeline(training_data):
    return build_pipeline().fit(training_data["text"], training_data["category"])
