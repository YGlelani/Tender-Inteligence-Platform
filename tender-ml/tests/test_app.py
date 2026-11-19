import pytest
from fastapi.testclient import TestClient

from app import app, get_matcher, get_metadata, get_pipeline
from tender_ml.matching import CategoryMatcher
from tender_ml import config

METADATA = {"version": "20261117-120000", "sklearn_version": "test", "metrics": {"accuracy": 1.0}}


@pytest.fixture
def client(trained_pipeline):
    # Without a "with" block the startup step does not run, so no model file is needed.
    app.dependency_overrides[get_pipeline] = lambda: trained_pipeline
    app.dependency_overrides[get_matcher] = lambda: CategoryMatcher(trained_pipeline)
    app.dependency_overrides[get_metadata] = lambda: METADATA
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_home_page_is_served(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert 'id="tender-form"' in response.text


def test_health_and_model_report_the_model_version(client):
    assert client.get("/health").json() == {"status": "ok", "model_version": "20261117-120000"}
    assert client.get("/model").json() == METADATA


def test_service_starts_degraded_until_a_model_is_trained(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "MODEL_PATH", tmp_path / "missing-model.joblib")

    with TestClient(app) as untrained_client:
        assert untrained_client.get("/health").json() == {
            "status": "degraded", "reason": "model_not_trained",
        }
        assert untrained_client.post("/predict", json={"title": "Office cleaning"}).status_code == 503


def test_predict_returns_the_category_suggestions_and_explanation(client):
    response = client.post("/predict", json={"title": "Security guarding services for the warehouse"})

    body = response.json()
    assert response.status_code == 200
    assert body["category"] == "Security"
    assert len(body["suggestions"]) == 3
    probabilities = [suggestion["probability"] for suggestion in body["suggestions"]]
    assert probabilities == sorted(probabilities, reverse=True)
    assert "security" in body["explanation"]


def test_predict_returns_no_category_for_unknown_words(client):
    response = client.post("/predict", json={"title": "zebra umbrella"})

    assert response.status_code == 200
    assert response.json()["category"] is None


def test_predict_rejects_a_blank_title(client):
    assert client.post("/predict", json={"title": "   "}).status_code == 422


def test_categorise_company(client):
    response = client.post("/categorise-company", json={"services": ["catering and meals"]})

    body = response.json()
    assert body["categories"] == ["Catering"]
    assert body["suggestions"][0]["category"] == "Catering"
    assert "catering" in body["explanation"]


def test_categorise_company_without_enough_information(client):
    assert client.post("/categorise-company", json={}).json() == {
        "categories": [], "suggestions": [], "explanation": [],
    }


def test_match_categories_returns_only_matching_tenders(client):
    tenders = [
        {"id": "1", "title": "Catering and meals for the depot"},
        {"id": "2", "title": "Stationery and printing paper for the school"},
        {"id": "3", "title": "Anything", "category": "Catering"},
    ]
    response = client.post(
        "/match-categories", json={"company": {"services": ["catering and meals"]}, "tenders": tenders}
    )

    assert response.json() == {"company_categories": ["Catering"], "matches": {"1": "Catering", "3": "Catering"}}


def test_match_categories_rejects_too_many_tenders(client):
    tenders = [{"id": str(number), "title": "x"} for number in range(5001)]

    assert client.post("/match-categories", json={"company": {}, "tenders": tenders}).status_code == 422
