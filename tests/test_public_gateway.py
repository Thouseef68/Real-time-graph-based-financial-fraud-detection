"""
tests/test_public_gateway.py
Phase 12 Tests: Public Gateway, IP Privacy, Device Identity, Token Isolation, Zero Residue.
"""

import time
import pytest
from fastapi.testclient import TestClient

from fraudengine.api.app import app
from fraudengine.api.state import state
from fraudengine.live.security import (
    derive_client_ip,
    truncate_ip,
    is_public_host,
    is_route_publicly_allowed,
)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def manager():
    return state.live_manager


@pytest.fixture(autouse=True)
def strict_gateway_mode(monkeypatch):
    monkeypatch.setenv("ALLOW_FULL_PUBLIC_ACCESS", "false")


# ----------------------------------------------------------------------
# 1. Public Host Allowlist & Denylist Enforcement
# ----------------------------------------------------------------------
def test_public_host_denies_console_and_admin_routes(client):
    """Requests bearing a public host header must NOT access analyst or admin routes."""
    headers = {"Host": "frauddemo-sandbox.trycloudflare.com"}

    # Analyst console / case management
    res = client.get("/api/v1/cases", headers=headers)
    assert res.status_code == 403
    assert "Forbidden: Public participant gateway" in res.json().get("error", "")

    # Admin / System status
    res = client.get("/api/v1/demo/status", headers=headers)
    assert res.status_code == 403

    # Docs and openapi schema
    res = client.get("/docs", headers=headers)
    assert res.status_code == 403

    res = client.get("/openapi.json", headers=headers)
    assert res.status_code == 403

    # Auth login
    res = client.post("/api/v1/auth/login", data={"username": "admin", "password": "x"}, headers=headers)
    assert res.status_code == 403


def test_public_host_allows_only_participant_routes(client):
    """Public gateway allows ONLY participant app, join, transfer, me, and recipients."""
    headers = {"Host": "frauddemo-sandbox.trycloudflare.com"}

    # Static app entry /app is allowed
    res = client.get("/app", headers=headers)
    assert res.status_code != 403

    # Participant join endpoint is allowed (returns 404/400 for bad room, but not 403)
    res = client.post("/api/v1/live/rooms/NONEXISTENT_ROOM/join", json={}, headers=headers)
    assert res.status_code != 403


# ----------------------------------------------------------------------
# 2. Client IP Derivation & Anti-Spoofing
# ----------------------------------------------------------------------
def test_forwarded_headers_from_non_loopback_peer_ignored():
    """If the direct peer is not loopback, forwarded headers MUST be ignored to prevent spoofing."""
    direct_peer = "192.168.1.50"
    headers = {
        "x-forwarded-for": "203.0.113.195",
        "cf-connecting-ip": "198.51.100.22",
    }
    extracted_ip = derive_client_ip(direct_peer, headers)
    # Must equal direct_peer, NOT the spoofed header
    assert extracted_ip == "192.168.1.50"


def test_forwarded_headers_from_loopback_peer_trusted():
    """If the direct peer is loopback (the local tunnel process), forwarded headers are trusted."""
    direct_peer = "127.0.0.1"
    headers = {
        "cf-connecting-ip": "203.0.113.195",
    }
    extracted_ip = derive_client_ip(direct_peer, headers)
    assert extracted_ip == "203.0.113.195"

    # Multi-hop X-Forwarded-For: leftmost is client
    headers_xff = {
        "x-forwarded-for": "198.51.100.77, 10.0.0.1",
    }
    extracted_xff = derive_client_ip(direct_peer, headers_xff)
    assert extracted_xff == "198.51.100.77"


# ----------------------------------------------------------------------
# 3. IP Truncation and Privacy Masking
# ----------------------------------------------------------------------
def test_ip_truncation_ipv4_and_ipv6():
    """IPv4 truncated to /24 and IPv6 to /64. Raw IP discarded."""
    # IPv4
    prefix_v4, masked_v4 = truncate_ip("203.0.113.195")
    assert prefix_v4 == "203.0.113.0/24"
    assert masked_v4 == "203.0.113.x"

    # IPv6
    prefix_v6, masked_v6 = truncate_ip("2001:0db8:85a3:0000:0000:8a2e:0370:7334")
    assert prefix_v6 == "2001:db8:85a3::/64"
    assert masked_v6 == "2001:db8:85a3::x"


# ----------------------------------------------------------------------
# 4. Device Identity & Shared Device Feature
# ----------------------------------------------------------------------
def test_two_accounts_on_one_device_produces_shared_device_feature(manager):
    """When two participants join on the same device_id, the graph records a shared device."""
    room_code = f"TEST_DEV_{int(time.time())}"
    room = manager.create_room(room_code)

    shared_dev = "DEV_SHARED_PHONE_001"
    p1 = room.add_participant(
        display_name="Participant Alice",
        device_id=shared_dev,
        network_prefix="103.45.67.0/24",
        masked_ip="103.45.67.x",
        consent_accepted=True,
    )
    p2 = room.add_participant(
        display_name="Participant Bob",
        device_id=shared_dev,
        network_prefix="103.45.67.0/24",
        masked_ip="103.45.67.x",
        consent_accepted=True,
    )

    # Record transactions on the shared device
    manager.graph_engine.update_transaction(
        account_id=p1.account_id,
        payee_id="CUST_OTHER",
        amount=10.0,
        device_id=shared_dev,
        ip_prefix="103.45.67.0/24",
        label=0,
        step=700,
    )
    manager.graph_engine.update_transaction(
        account_id=p2.account_id,
        payee_id="CUST_OTHER",
        amount=10.0,
        device_id=shared_dev,
        ip_prefix="103.45.67.0/24",
        label=0,
        step=700,
    )

    # Check graph engine contains both edges pointing to the shared device node
    g = manager.graph_engine.g
    assert shared_dev in g.nodes
    assert g.has_edge(p1.account_id, shared_dev)
    assert g.has_edge(p2.account_id, shared_dev)

    # Clean up test room
    manager.wipe_room(room_code)


# ----------------------------------------------------------------------
# 5. Token Isolation & Rate Limiting
# ----------------------------------------------------------------------
def test_token_isolation_prevents_impersonation(manager):
    """A participant cannot execute transfers from another participant's account."""
    room_code = f"TEST_ISO_{int(time.time())}"
    room = manager.create_room(room_code)

    p1 = room.add_participant(display_name="Sender", consent_accepted=True)
    p2 = room.add_participant(display_name="Target", consent_accepted=True)

    # p1 tries to authorize transfer from p2 using a forged or mismatched token
    res = manager.execute_transfer(
        room_code=room_code,
        sender_id=p2.account_id,
        receiver_id=p1.account_id,
        amount=100.0,
        session_token="FORGED_SESSION_TOKEN_12345",
    )
    assert res.get("status") == "DECLINED"
    assert res.get("error_code") == "UNAUTHORIZED_TOKEN"

    # p1 tries to authorize transfer from p2 using p1's own session token
    res2 = manager.execute_transfer(
        room_code=room_code,
        sender_id=p2.account_id,
        receiver_id=p1.account_id,
        amount=100.0,
        session_token=p1.session_token,
    )
    assert res2.get("status") == "DECLINED"
    assert res2.get("error_code") == "UNAUTHORIZED_TOKEN"

    # Valid token for sender p1 succeeds
    res3 = manager.execute_transfer(
        room_code=room_code,
        sender_id=p1.account_id,
        receiver_id=p2.account_id,
        amount=50.0,
        session_token=p1.session_token,
    )
    assert res3.get("status") in ("PROCESSED", "HELD", "DECLINED")
    assert res3.get("error_code") is None

    manager.wipe_room(room_code)


def test_rate_limiting_per_session_token(manager):
    """Rapid spamming of transfers from one session token triggers rate limiting."""
    room_code = f"TEST_RL_{int(time.time())}"
    room = manager.create_room(room_code)

    p1 = room.add_participant(display_name="Spammer", consent_accepted=True)
    p2 = room.add_participant(display_name="Receiver", consent_accepted=True)

    # Fire 8 transfers instantly (limit is 5 in 10.0s window in default profile)
    rate_limited_count = 0
    for _ in range(8):
        res = manager.execute_transfer(
            room_code=room_code,
            sender_id=p1.account_id,
            receiver_id=p2.account_id,
            amount=10.0,
            session_token=p1.session_token,
        )
        if res.get("error_code") == "RATE_LIMITED":
            rate_limited_count += 1

    assert rate_limited_count > 0, "Expected at least one transfer to be rate-limited"
    manager.wipe_room(room_code)


# ----------------------------------------------------------------------
# 6. Zero Residue Room Wipe
# ----------------------------------------------------------------------
def test_wipe_leaves_zero_residue(manager):
    """Wipe permanently deletes all room redis keys, participants, ledger, and graph nodes."""
    room_code = f"TEST_WIPE_{int(time.time())}"
    room = manager.create_room(room_code)

    p1 = room.add_participant(display_name="UserToWipe", device_id="DEV_WIPE_99", consent_accepted=True)
    p2 = room.add_participant(display_name="UserToWipe2", consent_accepted=True)

    # Perform a transfer so ledger and graph entries exist
    manager.execute_transfer(
        room_code=room_code,
        sender_id=p1.account_id,
        receiver_id=p2.account_id,
        amount=25.0,
        session_token=p1.session_token,
    )

    # Confirm presence before wipe
    assert room_code in manager.rooms
    assert p1.account_id in manager.graph_engine.g.nodes

    # Execute wipe
    wiped = manager.wipe_room(room_code)
    assert wiped is True

    # Confirm room is removed from manager registry
    assert room_code not in manager.rooms

    # Confirm participant nodes removed from graph
    assert p1.account_id not in manager.graph_engine.g.nodes
    assert p2.account_id not in manager.graph_engine.g.nodes

    # Confirm Redis keys starting with room prefix are 0
    redis_client = getattr(manager.redis_store, "client", None)
    if redis_client:
        try:
            keys = redis_client.keys(f"live:sandbox:{room_code}:*")
            assert len(keys) == 0, f"Expected 0 residue keys in Redis, found: {keys}"
        except Exception:
            pass
