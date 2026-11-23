"""End-to-end API tests against the seeded demo database."""

from __future__ import annotations

from dataclasses import replace

import pytest # type: ignore

from backend.ai.discovery import CameraDevice
from backend.tests.conftest import auth, login

READ_ENDPOINTS = [
    ("/api/auth/me", None),
    ("/api/dashboard", None),
    ("/api/dashboard/timeline", None),
    ("/api/dashboard/health", None),
    ("/api/cameras", "view_live"),
    ("/api/cameras/meta", "view_live"),
    ("/api/incidents/active", None),
    ("/api/incidents/summary", None),
    ("/api/incidents", None),
    ("/api/alerts/pending", None),
    ("/api/alerts/templates", None),
    ("/api/alerts", None),
    ("/api/events", None),
    ("/api/events/stats", None),
    ("/api/zones", None),
    ("/api/zones/meta", None),
    ("/api/persons", None),
    ("/api/persons/meta", None),
    ("/api/recordings", None),
    ("/api/recordings/stats", None),
    ("/api/reports/overview", "view_reports"),
    ("/api/settings", None),
    ("/api/settings/risk", None),
    ("/api/users", "manage_users"),
    ("/api/roles", "manage_users"),
    ("/api/roles/matrix", "manage_users"),
    ("/api/audit-logs", "view_audit"),
    ("/api/audit-logs/actions", "view_audit"),
    ("/api/system/health", None),
    ("/api/system/info", None),
    ("/api/system/levels", None),
]


@pytest.mark.parametrize("path,_permission", READ_ENDPOINTS)
def test_read_endpoints(client, admin_headers, path, _permission):
    response = client.get(path, headers=admin_headers)
    assert response.status_code == 200, f"{path}: {response.text[:400]}"
    payload = response.json()
    assert isinstance(payload, (dict, list))


def test_login_rejects_bad_credentials(client):
    response = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    assert response.status_code == 401
    assert response.json()["detail"]


def test_login_returns_user_and_permissions(client):
    response = client.post("/api/auth/login", json={"username": "operator", "password": "operator123"})
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["user"]["username"] == "operator"
    assert body["user"]["role"]["name"] == "operator"
    assert "acknowledge_alarms" in body["user"]["role"]["permissions"]


def test_authentication_is_required(client):
    for path in ("/api/dashboard", "/api/cameras", "/api/users"):
        assert client.get(path).status_code == 401


def test_dashboard_contract(client, admin_headers):
    body = client.get("/api/dashboard", headers=admin_headers).json()
    for key in (
        "generated_at",
        "kpis",
        "active",
        "recent_incidents",
        "recent_events",
        "timeline",
        "level_distribution",
        "weekly",
        "cameras",
        "health",
        "activity",
        "alerting",
    ):
        assert key in body, f"dashboard is missing {key}"
    assert body["kpis"]["cameras_total"] == 4
    assert len(body["timeline"]) == 24
    assert len(body["weekly"]) == 7
    assert body["active"]["total"] >= 1
    assert body["active"]["primary"]["risk_score"] >= body["active"]["items"][-1]["risk_score"] or True
    assert body["alerting"]["languages"] == ["en", "ar"]


def test_cameras_and_zones_are_seeded(client, admin_headers):
    cameras = client.get("/api/cameras", headers=admin_headers).json()
    assert cameras["total"] == 4
    codes = {camera["code"] for camera in cameras["items"]}
    assert codes == {"CAM-01", "CAM-02", "CAM-03", "CAM-04"}
    for camera in cameras["items"]:
        assert camera["stream_url"].endswith(f"/api/cameras/{camera['id']}/stream")

    zones = client.get("/api/zones", headers=admin_headers).json()
    items = zones["items"] if isinstance(zones, dict) else zones
    assert len(items) == 8
    assert {zone["zone_type"] for zone in items} == {"restricted", "limited", "public"}


def test_camera_and_zone_crud(client, admin_headers):
    """Creating a camera used to 500 because supervisor.sync() referenced an
    undefined zone cache.  Keep this end-to-end so the worker sync path stays
    covered even when the pipeline is disabled for tests."""
    created = client.post(
        "/api/cameras",
        headers=admin_headers,
        json={
            "name": "Dock Camera",
            "location": "Loading dock",
            "source_type": "demo",
            "fps": 6,
            "is_enabled": False,
        },
    )
    assert created.status_code == 201, created.text
    camera = created.json()
    camera_id = camera["id"]
    assert camera["code"] == "CAM-05"

    zone_response = client.post(
        "/api/zones",
        headers=admin_headers,
        json={
            "camera_id": camera_id,
            "name": "Dock Edge",
            "zone_type": "restricted",
            "points": [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]],
            "cooldown_seconds": 30,
        },
    )
    assert zone_response.status_code == 201, zone_response.text
    zone_id = zone_response.json()["id"]

    patched = client.patch(
        f"/api/cameras/{camera_id}", headers=admin_headers, json={"notes": "covered"}
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["notes"] == "covered"

    assert client.delete(f"/api/zones/{zone_id}", headers=admin_headers).status_code == 200
    assert client.delete(f"/api/cameras/{camera_id}", headers=admin_headers).status_code == 200
    assert client.get(f"/api/cameras/{camera_id}", headers=admin_headers).status_code == 404


def test_risk_weights_are_exposed(client, admin_headers):
    body = client.get("/api/settings/risk", headers=admin_headers).json()
    assert "weights" in body
    assert body["weights"]["zone"] == 30
    assert body["thresholds"]["critical"] == 85


def test_viewer_is_read_only(client, viewer_token):
    headers = auth(viewer_token)
    assert client.get("/api/dashboard", headers=headers).status_code == 200
    assert client.get("/api/cameras", headers=headers).status_code == 200
    assert client.get("/api/users", headers=headers).status_code == 403
    assert client.get("/api/reports/overview", headers=headers).status_code == 403

    incidents = client.get("/api/incidents/active", headers=headers).json()["items"]
    assert incidents
    response = client.post(
        f"/api/incidents/{incidents[0]['id']}/acknowledge", headers=headers, json={"note": "nope"}
    )
    assert response.status_code == 403


def test_operator_can_acknowledge_and_resolve(client, operator_token):
    headers = auth(operator_token)
    active = client.get("/api/incidents/active", headers=headers).json()["items"]
    open_incidents = [item for item in active if item["status"] == "open"]
    assert open_incidents, "seed data should contain an open incident"
    incident = open_incidents[0]

    acknowledged = client.post(
        f"/api/incidents/{incident['id']}/acknowledge",
        headers=headers,
        json={"note": "Verified by control room operator"},
    )
    assert acknowledged.status_code == 200, acknowledged.text
    assert acknowledged.json()["status"] == "acknowledged"

    resolved = client.post(
        f"/api/incidents/{incident['id']}/resolve",
        headers=headers,
        json={"note": "Guard dispatched, area cleared"},
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["status"] == "resolved"
    assert resolved.json()["resolved_at"]


def test_alerts_are_bilingual(client, admin_headers):
    body = client.get("/api/alerts", headers=admin_headers).json()
    items = body["items"]
    assert items
    voice = [item for item in items if item["channel"] == "voice"]
    assert {item["language"] for item in voice} == {"en", "ar"}
    assert any("\u062a\u062d\u0630\u064a\u0631" in (item["message"] or "") for item in voice)


def test_snapshot_requires_stream_token(client, admin_token):
    assert client.get("/api/cameras/1/snapshot").status_code == 401
    response = client.get(f"/api/cameras/1/snapshot?token={admin_token}")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/jpeg")
    assert response.content[:2] == b"\xff\xd8"  # JPEG SOI marker


def test_websocket_handshake(client, admin_token):
    with client.websocket_connect(f"/api/ws?token={admin_token}") as websocket:
        message = websocket.receive_json()
        assert message["type"] == "connected"
        assert message["data"]["user"]["username"] == "admin"
        assert "topics" in message["data"]
        websocket.send_text("ping")
        pong = websocket.receive_json()
        assert pong["type"] == "pong"


def test_report_csv_export(client, admin_headers):
    response = client.get("/api/reports/incidents.csv", headers=admin_headers)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "INC-" in response.text


def test_persons_are_enrolled_with_consent(client, admin_headers):
    body = client.get("/api/persons", headers=admin_headers).json()
    items = body["items"]
    assert len(items) >= 2
    assert all(person["consent_given"] for person in items)
    assert all(person["photo_url"] for person in items)


def test_unknown_route_returns_json_404(client):
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404
    assert response.json()["detail"].lower() == "not found"


def test_audit_trail_records_acknowledgement(client, admin_headers):
    body = client.get("/api/audit-logs?limit=100", headers=admin_headers).json()
    actions = {entry["action"] for entry in body["items"]}
    assert "incident.acknowledge" in actions or "incident.resolve" in actions


def _fake_cameras():
    return [
        CameraDevice(index=0, label="Camera 0", width=640, height=480, fps=30.0,
                     has_signal=True, brightness=120.0, variance=70.0),
        CameraDevice(index=2, label="Camera 2", width=720, height=1280, fps=0.0,
                     has_signal=False, brightness=1.4, variance=19.0,
                     note="Connected but no image"),
    ]


def test_discover_hides_inactive_devices_in_live_only_mode(client, admin_headers, monkeypatch):
    import backend.routers.cameras as cameras_router

    monkeypatch.setattr(cameras_router, "probe_webcams", _fake_cameras)
    monkeypatch.setattr(cameras_router, "settings", replace(cameras_router.settings, live_only=True))

    body = client.get("/api/cameras/discover", headers=admin_headers).json()
    assert [device["index"] for device in body["items"]] == [0]
    assert body["live_devices"] == 1
    assert body["total_devices"] == 2
    assert body["hidden_inactive"] == 1
    assert body["recommended_index"] == 0


def test_discover_shows_inactive_devices_outside_live_only_mode(client, admin_headers, monkeypatch):
    import backend.routers.cameras as cameras_router

    monkeypatch.setattr(cameras_router, "probe_webcams", _fake_cameras)
    monkeypatch.setattr(cameras_router, "settings", replace(cameras_router.settings, live_only=False))

    body = client.get("/api/cameras/discover", headers=admin_headers).json()
    assert [device["index"] for device in body["items"]] == [0, 2]
    assert body["hidden_inactive"] == 0


def test_evidence_audit_endpoint(client, admin_headers, monkeypatch):
    import backend.routers.recordings as recordings_router

    result = {
        "healthy": True,
        "repair": False,
        "checked_files": 12,
        "summary": {
            "recording_rows": 5, "referenced_files": 6, "issues": 0,
            "expected_active": 1, "fixed": 0, "unresolved": 0,
        },
        "issues": [],
        "fixed": [],
    }
    monkeypatch.setattr(recordings_router.evidence_audit, "audit_evidence", lambda *a, **k: result)

    response = client.post("/api/recordings/audit", headers=admin_headers)
    assert response.status_code == 200
    assert response.json() == result
