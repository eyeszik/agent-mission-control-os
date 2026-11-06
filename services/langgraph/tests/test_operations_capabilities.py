from fastapi.testclient import TestClient

from services.langgraph.app.main import app

client = TestClient(app)


def test_capabilities_reports_the_skill_registry():
    response = client.get("/operations/capabilities")
    assert response.status_code == 200
    body = response.json()
    assert "skills" in body
    assert body["skills"]["skills"], "expected at least one registered skill"
    zo_entry = next(item for item in body["skills"]["skills"] if item["skill_id"] == "zo_ask")
    assert zo_entry["capability"] == "research_synthesis"
