from app.main import app


def test_application_routes_exist():
    # Read the routes from the API schema: newer FastAPI keeps included routers
    # as one entry in app.routes.
    paths = set(app.openapi()["paths"])

    assert "/health" in paths
    assert "/profile" in paths
    assert "/matches" in paths
    assert "/notifications" in paths
    assert "/alerts" not in paths
