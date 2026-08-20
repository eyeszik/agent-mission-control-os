from fastapi.testclient import TestClient
from services.langgraph.app.main import app

client = TestClient(app)


def test_cors_allows_configured_frontend_origin():
    # A browser sends this preflight before any real cross-origin POST/GET.
    # Without CORSMiddleware configured, no frontend can call this API at all.
    response = client.options(
        "/agency/runs",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
