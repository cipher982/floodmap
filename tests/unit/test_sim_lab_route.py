from fastapi.testclient import TestClient


def test_sim_lab_is_served_in_development(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("ALLOW_MISSING_DATA", "true")

    import importlib

    import main

    importlib.reload(main)
    client = TestClient(main.app)
    response = client.get("/sim-lab")

    assert response.status_code == 200
    assert "Flood Sandbox Lab" in response.text
    assert "flood-sim-core.js" in response.text
