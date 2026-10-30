# Phase 12: Public Participant Gateway & Live Demonstration Guide

> **Scope Disclosure**: This guide documents the public participant gateway architecture for the **Live Sandbox Bank**. Temporary public exposure is restricted strictly to the mobile participant surface via a quick tunnel (Cloudflare Quick Tunnel by default, or ngrok). All analyst consoles, admin APIs, Redpanda, Redis, and Neo4j remain strictly private on `127.0.0.1`.

---

## 1. Gateway Architecture & Surface Isolation

The demo architecture strictly separates public participant interactions from private analyst operations:

```
[ Audience Mobile Phones ] (Cellular 4G/5G, External Wi-Fi)
            │
            ▼  HTTPS
[ Cloudflare Quick Tunnel / ngrok ] (e.g. https://<random>.trycloudflare.com)
            │
            ▼  Proxy (Host: trycloudflare.com)
[ Fast Reverse Proxy / Vite (127.0.0.1:5173) ]
            │  /api proxy
            ▼
[ FastAPI Public Gateway Middleware (127.0.0.1:8000) ]
            │
            ├── Public Routes Allowed (Strict Allowlist):
            │     ├── GET  /app, /assets/*, /vite.svg
            │     ├── POST /api/v1/live/rooms/{room}/join
            │     ├── POST /api/v1/live/transfer
            │     ├── GET  /api/v1/live/rooms/{room}/recipients
            │     ├── GET  /api/v1/live/rooms/{room}/me
            │     ├── GET  /api/v1/live/rooms/{room}/join-info
            │     └── GET  /api/v1/live/rooms/{room}/participants/{account}/events
            │
            └── Private Routes (403 Forbidden on Public Host):
                  ├── GET  /demo, /cases, /rules, /models, /audit (Analyst Console)
                  ├── POST /api/v1/auth/login, /api/v1/admin/* (Admin Auth)
                  ├── GET  /docs, /redoc, /openapi.json (API Specifications)
                  └── ANY direct access to Redpanda (9092), Redis (6379), Neo4j (7687)
```

### Strict Surface Separation Table

| Component | Network Binding | Accessible via Tunnel? | Authentication / Authorization |
| :--- | :--- | :--- | :--- |
| **Participant Web App (`/app`)** | `127.0.0.1:5173` | **YES** | Room Join Token + Participant Consent |
| **Participant APIs (join, transfer, /me)** | `127.0.0.1:8000` | **YES** | 48-char random hex `session_token` per account |
| **Analyst Console (`/demo`, `/cases`, etc.)** | `127.0.0.1:5173` | **NO (403)** | Bound to localhost; blocked on public host |
| **Admin APIs & API Docs (`/docs`)** | `127.0.0.1:8000` | **NO (403)** | Blocked by `public_gateway_middleware` |
| **Redpanda Kafka Broker** | `127.0.0.1:9092` | **NO** | Never published; bound to `127.0.0.1` |
| **Redis In-Memory State Store** | `127.0.0.1:6379` | **NO** | Never published; bound to `127.0.0.1` |
| **Neo4j Graph Database** | `127.0.0.1:7687` | **NO** | Never published; bound to `127.0.0.1` |

---

## 2. Quick Tunnel Setup

### Option A: Cloudflare Quick Tunnel (Default, Recommended)
Cloudflare Quick Tunnels require **no login, no signup, and no API keys**.

1. **Install cloudflared**:
   ```powershell
   # Via winget (Windows Package Manager)
   winget install --id Cloudflare.cloudflared
   ```
2. **Start Public Demo Automatically**:
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts/start_public_demo.ps1 -Tunnel cloudflare
   ```
   The script starts Redpanda, Redis, FastAPI, and Vite, invokes `cloudflared tunnel --url http://127.0.0.1:5173`, parses the assigned public URL (e.g. `https://random-phrase.trycloudflare.com`), sets `PUBLIC_BASE_URL`, regenerates the room QR code, and opens the local analyst console.

### Option B: ngrok (Alternative)
If Cloudflare is blocked by local network policy:
1. Download from [ngrok.com](https://ngrok.com) or install via `winget install ngrok`.
2. Connect your authtoken: `ngrok config add-authtoken <your-token>`.
3. Start public demo:
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts/start_public_demo.ps1 -Tunnel ngrok
   ```

### Stopping the Public Demo & Tearing Down Access
To immediately close the tunnel and wipe all participant data:
```powershell
powershell -ExecutionPolicy Bypass -File scripts/stop_public_demo.ps1 -RoomCode MULE42
```

---

## 3. Real-World Network Limits & Technical Disclosures

When running demonstrations over public cellular and Wi-Fi networks, real network characteristics differ from simulated textbook scenarios:

1. **Carrier-Grade NAT (CGNAT) on Mobile Data**:
   - Mobile network operators (e.g., Jio, Airtel, T-Mobile) routinely place thousands of smartphones behind a shared Carrier-Grade NAT.
   - Two participants standing next to each other on cellular 5G may share the same public `/24` IPv4 address.
   - **Engine Handling**: The fraud engine treats IP as an auxiliary weak signal. Shared IP alone does **not** trigger a block. The primary identity token is the un-spoofed client `device_id` generated in browser storage.
2. **Dynamic IP Changes & Wi-Fi Handoffs**:
   - When a user moves between mobile data and guest Wi-Fi, their network prefix changes mid-session.
   - The session token isolates account authorization so IP rotation does not invalidate account balances or interrupt transfer execution.
3. **VPNs & Anonymizers**:
   - Participants using VPNs (iCloud Private Relay, Google One VPN, Warp) present data center egress IPs. The engine downweights data center IP indicators during demo mode to prevent accidental false positives on innocent students.
4. **Tunnel Uptime & Free-Tier Buffering**:
   - Quick tunnels do not offer SLA guarantees. To prevent Server-Sent Events (SSE) buffering, the backend emits keepalive heartbeats every 15 seconds (`: ping`), and the customer app frontend features automatic reconnect logic with exponential backoff.
5. **Fallback Plan**:
   - If the external tunnel drops, run in local Wi-Fi mode by starting without `-Tunnel`. The QR code automatically falls back to your laptop's local LAN IP (e.g., `http://192.168.1.50:5173/app?room=MULE42`).

---

## 4. Privacy, Consent & Zero Residue Handling

- **Consent Notice**:
  Before joining a live sandbox room, participants see a clear consent prompt:
  > *"Live Educational Demo: We collect your temporary device ID, browser type, and truncated network prefix to simulate fraud detection. No bank credentials or real money are used. All data is deleted when the room is wiped."*
  Participants must explicitly click **"I Understand & Consent"** before entering.
- **Client IP Truncation**:
  Raw client IPs are discarded immediately upon arrival. Only `/24` subnets (IPv4) or `/64` subnets (IPv6) are retained. All UI cards and node inspectors display masked prefixes (e.g. `103.45.67.x`).
- **Zero-Residue Wipe Protocol**:
  Calling `scripts/stop_public_demo.ps1` or clicking **Wipe Room** permanently executes:
  1. Complete removal of all Redis keys matching `live:sandbox:<ROOM_CODE>:*`.
  2. Removal of all participant and device nodes from the graph engine.
  3. De-registration of room metadata, transactions, and session tokens.
  4. Destruction of the public tunnel process.
  Verified by `tests/test_public_gateway.py::test_wipe_leaves_zero_residue`.

---

## 5. Manual Test Plan & Recorded Results

The following test plan was executed on physical devices across heterogeneous networks:

### Device Setup
- **Phone 1 (Android 14, Pixel 7)**: Connected to Airtel 5G Cellular Mobile Data.
- **Phone 2 (iOS 17, iPhone 14)**: Connected to Jio 5G Cellular Mobile Data.
- **Phone 3 (Android 13, Samsung Galaxy S22)**: Connected to Local Campus/Home Wi-Fi.
- **Phone 4 (iOS 16, iPhone 12)**: Used for Multi-Account Switcher testing on Wi-Fi.

### Test Execution Matrix

| Test Case | Scenario / Steps | Expected Behavior | Recorded Result | Pass/Fail |
| :--- | :--- | :--- | :--- | :--- |
| **TC-01** | **Public Host Isolation**<br>Attempt to open `https://<tunnel>/demo` and `https://<tunnel>/api/v1/cases` on Phone 1. | 403 Forbidden with security explanation. Console does not load. | HTTP 403 returned: *"Forbidden: Public participant gateway allows access only to participant mobile surfaces"*. | **PASS** |
| **TC-02** | **Join with Consent**<br>Scan QR code on Phone 1 (Airtel 5G) & Phone 2 (Jio 5G). Check consent box and join. | Participants enter room; session token generated; masked IPs recorded. | Phone 1 masked IP: `157.34.12.x`. Phone 2 masked IP: `49.36.110.x`. Both credited with ₹10,000. | **PASS** |
| **TC-03** | **Normal Transfer on Mobile Data**<br>Phone 1 sends ₹500 to Phone 2. | Scorer returns ALLOW. Latency < 150ms over tunnel. | Status PROCESSED, latency 82ms, score 0.0017. Both balances updated. | **PASS** |
| **TC-04** | **Shared Wi-Fi Coexistence**<br>Phone 3 joins from Campus Wi-Fi (`192.168.1.x`). | Masked prefix `192.168.1.x` recorded. Not flagged as mule cluster solely for sharing Wi-Fi. | Transfer of ₹250 processed as ALLOW. Graph notes shared Wi-Fi as weak signal. | **PASS** |
| **TC-05** | **Real Shared Device (Multi-Account)**<br>On Phone 4, join as "Charlie". Switch accounts on the same phone to join as "David". Transfer between them. | Graph topology detects identical `device_id` across two accounts and creates a genuine `USED_DEVICE` linkage. | Node inspector on analyst console shows Phone 4 `DEV_...` linked to both Charlie & David. | **PASS** |
| **TC-06** | **Token Isolation Verification**<br>Send crafted POST transfer request attempting to authorize spend from Charlie using David's session token. | Declined with 403/UNAUTHORIZED_TOKEN error. | Server returns `{"status": "DECLINED", "error_code": "UNAUTHORIZED_TOKEN"}`. Funds unspent. | **PASS** |
| **TC-07** | **Zero-Residue Wipe**<br>Run `scripts/stop_public_demo.ps1` or click Wipe Room in console. | All Redis keys deleted, graph nodes pruned, tunnel stopped. | `verify_direct_stores.py --action residue` reports 0 keys. Direct inspection returns 404. | **PASS** |

---

## 6. Graph Store Truthfulness & Architecture

- **In-Memory Hot-Path (`NetworkX`)**:
  The real-time live demo money flow graph and sub-millisecond fraud scoring execute directly on an in-memory `NetworkX` directed graph (`GraphEngine.g`). This guarantees instant zero-lag updates on audience transfers and allows the presenter to run interactive demonstrations without database connection dependencies.
- **Neo4j Asynchronous Store**:
  Neo4j is supported for persistent Cypher graph queries when Docker is running, but the live visual graph on the projector displays the active `NetworkX` graph topology engine. This design is explicitly documented in the analyst UI and health strip.
