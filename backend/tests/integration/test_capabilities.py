"""The capability advertisement the browser uses to hide absent controls."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_capabilities_are_public_and_name_the_optional_features(client: TestClient) -> None:
    response = client.get("/api/v1/capabilities")
    assert response.status_code == 200
    body = response.json()
    assert body["scheme_criteria_authoring"] is True
    assert body["messaging_stream_payloads"] is True
    # A capability payload must never carry workspace detail.
    assert set(body) == {"scheme_criteria_authoring", "messaging_stream_payloads"}
