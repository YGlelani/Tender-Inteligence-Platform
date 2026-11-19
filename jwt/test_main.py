from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_successful_login():
    response = client.post(
        "/login",
        data={"username": "musiwalo", "password": "password123"}
    )
    assert response.status_code == 200
    
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"

def test_protected_route_without_token():
    response = client.get("/protected-tenders")
    assert response.status_code == 401

def test_protected_route_with_token():
    # Log in first
    login_response = client.post(
        "/login",
        data={"username": "musiwalo", "password": "password123"}
    )
    token = login_response.json()["access_token"]
    
    # Use the token to access the protected route
    headers = {"Authorization": f"Bearer {token}"}
    response = client.get("/protected-tenders", headers=headers)
    
    assert response.status_code == 200

def test_session_timeout_hours_configures_token_lifetime(monkeypatch):
    import main

    monkeypatch.setenv("SESSION_TIMEOUT_HOURS", "3")
    assert main.get_token_expiry_minutes() == 180


def test_session_timeout_hours_rejects_invalid_values(monkeypatch):
    import pytest
    import main

    monkeypatch.setenv("SESSION_TIMEOUT_HOURS", "not-a-number")
    with pytest.raises(RuntimeError, match="SESSION_TIMEOUT_HOURS"):
        main.get_token_expiry_minutes()

    monkeypatch.setenv("SESSION_TIMEOUT_HOURS", "0")
    with pytest.raises(RuntimeError, match="greater than zero"):
        main.get_token_expiry_minutes()


def test_protected_route_rejects_expired_token():
    import os
    from datetime import datetime, timedelta, UTC
    import jwt

    import main

    secret = main.SECRET_KEY
    expired_token = jwt.encode(
        {"sub": "expired-user", "exp": datetime.now(UTC) - timedelta(minutes=1)},
        secret,
        algorithm="HS256",
    )
    response = client.get("/protected-tenders", headers={"Authorization": f"Bearer {expired_token}"})
    assert response.status_code == 401
    assert "expired" in response.json()["detail"].lower()


def test_protected_route_rejects_invalid_token():
    response = client.get("/protected-tenders", headers={"Authorization": "Bearer invalid.token.value"})
    assert response.status_code == 401
