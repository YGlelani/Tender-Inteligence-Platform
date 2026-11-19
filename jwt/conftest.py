import os

import pytest

# main refuses to start without a signing secret, and reads its CORS list at
# import time; give local test runs a value (CI sets JWT_SECRET itself).
os.environ.setdefault("JWT_SECRET", "local-test-secret")
os.environ.setdefault("CORS_ORIGINS", "http://allowed.example")


@pytest.fixture(autouse=True)
def reset_login_limits():
    """Failed sign-ins from one test must not lock accounts in the next."""
    import main

    main._login_failures.clear()
    yield
    main._login_failures.clear()
