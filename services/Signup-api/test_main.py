import hashlib
from datetime import UTC, datetime, timedelta

from main import (
    TOKEN_MINUTES,
    ResendRequest,
    SignupRequest,
    business_email,
    create_verification_token,
    password_error,
    valid_email,
)


def test_valid_email():
    assert valid_email("person@company.co.za") is True


def test_invalid_email():
    assert valid_email("invalid-email") is False


def test_business_email_allowed():
    assert business_email("tenders@company.co.za") is True


def test_gmail_rejected():
    assert business_email("person@gmail.com") is False


def test_yahoo_rejected():
    assert business_email("person@yahoo.com") is False


def test_signup_request_includes_company_name():
    request = SignupRequest(
        company_name="Baloyi Trading",
        email="tenders@company.co.za",
        password="Password123!",
    )
    assert request.company_name == "Baloyi Trading"
    assert request.email == "tenders@company.co.za"


def test_strong_password_is_accepted():
    assert password_error("Password123!") is None


def test_short_password_is_rejected():
    assert password_error("Pa1!") == "Password must be at least 8 characters long."


def test_resend_request():
    assert ResendRequest(email="test@example.com").email == "test@example.com"


def test_verification_token_is_stored_as_sha256_hash():
    raw_token, token_hash, _ = create_verification_token()
    assert token_hash == hashlib.sha256(raw_token.encode()).hexdigest()


def test_verification_token_expires_after_configured_minutes():
    _, _, expires_at = create_verification_token()
    remaining = datetime.fromisoformat(expires_at) - datetime.now(UTC)
    assert timedelta(minutes=TOKEN_MINUTES - 1) < remaining
    assert remaining <= timedelta(minutes=TOKEN_MINUTES)
