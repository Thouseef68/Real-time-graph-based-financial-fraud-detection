"""Integration tests for FastAPI backend endpoints."""

import pytest
from fastapi.testclient import TestClient

from fraudengine.api.app import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def analyst_token(client):
    res = client.post(
        "/api/v1/auth/login",
        json={"username": "analyst", "password": "analyst123"},
    )
    assert res.status_code == 200
    data = res.json()
    assert "access_token" in data
    return data["access_token"]


@pytest.fixture(scope="module")
def admin_token(client):
    res = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "admin123"},
    )
    assert res.status_code == 200
    data = res.json()
    assert "access_token" in data
    return data["access_token"]


def test_health_check(client):
    res = client.get("/api/v1/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert "version" in data


def test_auth_failure(client):
    res = client.post(
        "/api/v1/auth/login",
        json={"username": "invalid_user", "password": "wrong_password"},
    )
    assert res.status_code == 401


def test_metrics_summary(client, analyst_token):
    res = client.get(
        "/api/v1/metrics/summary",
        headers={"Authorization": f"Bearer {analyst_token}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert "total_alerts" in data
    assert "alert_rate" in data
    assert "avg_risk_score" in data


def test_alerts_list(client, analyst_token):
    res = client.get(
        "/api/v1/alerts",
        headers={"Authorization": f"Bearer {analyst_token}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert "items" in data
    assert "total" in data
    assert isinstance(data["items"], list)


def test_alert_detail(client, analyst_token):
    res_list = client.get(
        "/api/v1/alerts",
        headers={"Authorization": f"Bearer {analyst_token}"},
    )
    alerts = res_list.json()["items"]
    if len(alerts) > 0:
        case_id = alerts[0]["case_id"]
        res = client.get(
            f"/api/v1/alerts/{case_id}",
            headers={"Authorization": f"Bearer {analyst_token}"},
        )
        assert res.status_code == 200
        detail = res.json()
        assert detail["case_id"] == case_id
        assert "reasons" in detail


def test_analyst_action_and_label(client, analyst_token):
    res_list = client.get(
        "/api/v1/alerts",
        headers={"Authorization": f"Bearer {analyst_token}"},
    )
    alerts = res_list.json()["items"]
    if len(alerts) > 0:
        case_id = alerts[0]["case_id"]
        res_action = client.post(
            f"/api/v1/alerts/{case_id}/action",
            headers={"Authorization": f"Bearer {analyst_token}"},
            json={
                "action": "block",
                "note": "Verified fraudulent burst activity",
            },
        )
        assert res_action.status_code == 200
        data = res_action.json()
        assert data["status"] == "block"


def test_graph_subgraph(client, analyst_token):
    res = client.get(
        "/api/v1/graph/C1000000000",
        headers={"Authorization": f"Bearer {analyst_token}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert "nodes" in data
    assert "edges" in data


def test_models_list(client, analyst_token):
    res = client.get(
        "/api/v1/models",
        headers={"Authorization": f"Bearer {analyst_token}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert "models" in data


def test_audit_log_and_verification(client, analyst_token):
    res = client.get(
        "/api/v1/audit?limit=10",
        headers={"Authorization": f"Bearer {analyst_token}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert "items" in data

    res_verify = client.post(
        "/api/v1/audit/verify",
        headers={"Authorization": f"Bearer {analyst_token}"},
    )
    assert res_verify.status_code == 200
    verify_data = res_verify.json()
    assert "valid" in verify_data


def test_settings_admin_only(client, analyst_token, admin_token):
    # Analyst should get 403 Forbidden on PUT settings
    res_forbidden = client.put(
        "/api/v1/settings",
        headers={"Authorization": f"Bearer {analyst_token}"},
        json={"threshold_review_max": 0.65},
    )
    assert res_forbidden.status_code == 403

    # Admin should succeed
    res_admin = client.put(
        "/api/v1/settings",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"threshold_review_max": 0.65},
    )
    assert res_admin.status_code == 200
    settings_data = res_admin.json()
    assert settings_data["threshold_review_max"] == 0.65


def test_single_transaction_score(client, analyst_token):
    res = client.post(
        "/api/v1/score",
        headers={"Authorization": f"Bearer {analyst_token}"},
        json={
            "txn_id": "TXN_LIVE_9999",
            "step": 50,
            "account_id": "C1234567890",
            "payee_id": "C9876543210",
            "amount": 95000.0,
            "txn_type": "TRANSFER",
            "old_balance_orig": 100000.0,
            "new_balance_orig": 5000.0,
            "device_id": "DEV_NEW_99",
            "ip_prefix": "198.51.100",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert "txn_id" in data
    assert "tier" in data
    assert "score" in data
    assert "reasons" in data
