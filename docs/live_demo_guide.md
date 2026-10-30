# Phase 12: Live Sandbox Bank — Presenter & Demonstration Guide

> **Important**: This live audience demonstration operates exclusively in a **local sandbox environment with virtual balances**. No real money, payment rails, or personal credentials are ever handled. All screens display `"Simulation: Virtual Money Only"`.

---

## 1. System Overview & Architecture

The **Live Sandbox Bank** turns the demonstration from a passive recorded playback into a live interactive experience where your professor and peers participate directly using their own mobile phones.

| What is Real | What is NOT Real |
| :--- | :--- |
| **Real people** on their own smartphone browsers tapping buttons | **The money**: Virtual balances in an in-memory & Redis sandbox ledger |
| **Real pipeline**: Real Redpanda with native Kafka partitioner (`key = account_id`), real Redis counters & deltas, real in-memory **NetworkX** directed graph topology engine (`GraphEngine.g`), real XGBoost v2 Scorer + TreeSHAP explanations | **Any bank or UPI connection**: Zero connection to banking rails, payment gateways, or real accounts |
| **Real device IDs & IP addresses**: Extracted client-side via browser `localStorage` + coarse hashing; IPs truncated to `/24` or `/64` and masked | **Personal data**: Users enter display names only; no real bank account numbers, credentials, or PII |

> **Graph Store Truth Disclosure**: The real-time interactive money flow graph and sub-millisecond fraud scoring execute directly on the **in-memory NetworkX graph topology engine** (`GraphEngine.g`). This guarantees sub-millisecond updates without database round-trip latency. Neo4j is available for persistent Cypher graph queries when Docker is running, but the live visual demonstration is honestly labeled and powered by NetworkX.

---

## 2. Pre-Demo Setup (Before the Audience Enters)

### Step 1: Start Infrastructure & Services
Ensure Docker infrastructure is running, then start the platform:

```powershell
# 1. Start core services bound strictly to 127.0.0.1 (Redpanda, Redis, Neo4j)
docker compose up -d

# 2. Start the Backend (bound strictly to 127.0.0.1 for local isolation)
python -m uvicorn fraudengine.api.app:app --host 127.0.0.1 --port 8000

# 3. Start the Frontend (Vite)
cd frontend
npm run dev -- --host 127.0.0.1 --port 5173
```

### Step 2: Windows Firewall Configuration
If audience phones cannot reach your laptop's Wi-Fi IP, allow inbound connections on ports `8000` and `5173` via PowerShell (Run as Administrator):

```powershell
New-NetFirewallRule -DisplayName "FraudEngine Backend (8000)" -Direction Inbound -LocalPort 8000 -Protocol TCP -Action Allow
New-NetFirewallRule -DisplayName "FraudEngine Frontend (5173)" -Direction Inbound -LocalPort 5173 -Protocol TCP -Action Allow
```

### Step 3: Projector & Laptop Display Setup
- Open your laptop browser to `http://localhost:5173/demo`.
- Switch the top toggle to **Live Sandbox Mode**.
- Click **"Create Room & QR"** (or use the pre-seeded demo room `MULE42`).
- A large QR code appears containing your laptop's LAN IP (e.g., `http://172.20.10.2:5173/app?room=MULE42`). Project this on the presentation screen.

---

## 3. Audience Onboarding & Role Cards

When participants scan the QR code with their phones, they arrive at the mobile customer banking interface (`/app`).
Each participant enters their name (e.g., "Sarah", "Rahul") and is credited with a starting virtual balance of **₹10,000**.

### Pre-Assigned Role Cards
Distribute these cards to 4–5 volunteers:

| Participant | Role Card | Prompt on Phone Screen | Action & System Impact |
| :--- | :--- | :--- | :--- |
| **Volunteer 1** *(Innocent Customer)* | **Normal Shopper** | *"Select 'Campus Mart' and pay ₹250 for snacks."* | **ALLOW**: Ordinary velocity and baseline spending. Never blocked or held. |
| **Volunteer 2** *(Victim A)* | **Payer 1** | *"Select 'Mule A' and deposit ₹2,000 for invoice deposit."* | **PROCESSED**: Payee fan-in count in Redis increments to 1. |
| **Volunteer 3** *(Victim B)* | **Payer 2** | *"Select 'Mule A' and send ₹2,000 as urgent refund."* | **PROCESSED**: Payee fan-in count in Redis increments to 2. Graph draws convergence. |
| **Volunteer 4** *(Victim C)* | **Payer 3** | *"Select 'Mule A' and send ₹2,000 for shared rent."* | **HELD (Review Escrow)**: Distinct sender count reaches $\ge 3$ within 5 min. Demo sensitivity triggers **REVIEW**; analyst sees live case. |
| **Volunteer 5** *(Mule A)* | **Layering Mule** | *"Once funds arrive, immediately send ₹5,500 to Mule B / Crypto."* | **DECLINED (Instant Block)**: Forwarding $\ge 70\%$ of fresh inflow triggers **BLOCK** (pass-through layering). Real-time containment isolates linked accounts. |

---

## 4. Live Demonstration Script (Step-by-Step)

```
[Time 0:00] -- Introduce the Architecture
"What you see on the projector is the analyst investigation console. Every counter,
 graph edge, and decision is computed live by our engine. On your phones, you are
 holding our sandbox customer app."

[Time 1:00] -- Normal Customer Payment
- Volunteer 1 pays ₹250 to Campus Mart.
- Projector:
  * Transaction event flashes on Redpanda bus.
  * Scorer outputs score 0.04 (ALLOW).
  * Latency: ~15ms. Customer app shows "Payment Processed".

[Time 2:30] -- The Mule Fan-In Infiltration
- Volunteers 2, 3, and 4 follow role cards and deposit funds into Volunteer 5 (Mule A).
- Projector:
  * Redis `fanin:24h:CUST_MULEA` live counter steps: 1 -> 2 -> 3.
  * Graph topology draws converging directed edges into Mule A.
  * Transaction 3 crosses the demo sensitivity threshold ($\ge 3$ distinct senders in 5 min).
  * Engine marks tier as REVIEW. Money is held in review escrow. Analyst case queue lights up.

[Time 4:00] -- The Pass-Through Layering Attempt
- Volunteer 5 attempts to forward ₹5,500 onward to an external account or peer.
- Projector:
  * Fast pass-through ratio computed: 5,500 / 6,000 = 91.7% (exceeds 70% threshold).
  * Decision Engine triggers BLOCK tier with TreeSHAP explanation:
    "Rapid Pass-Through Layering (91.7% forwarded) + High Payee Fan-In".
  * Auto-containment adds Mule A to Redis blocklist and holds linked accounts.
- Mule Phone Screen:
  * Customer-safe message: "Payment declined by bank security systems."
  * Note: Fraud scoring logic and SHAP reasons are NEVER disclosed to the customer.

[Time 5:30] -- Enforcement & Sub-Millisecond Pre-Score Filter
- Volunteer 5 attempts to send another ₹100.
- Projector:
  * Blocklist filter intercepts the request in 0.08ms (<0.1ms SLA) before the ML model runs.
  * Ledger displays: "Money Saved: ₹5,500 | Money Held: ₹2,000".
```

---

## 5. Contingency Planning: What If Detection Does Not Trigger?

Do **NOT** fabricate or hardcode results. If detection does not trigger live:

1. **Check Redis Fan-In & Inflow Status**:
   In your browser developer tools or backend console:
   ```bash
   # Inspect fan-in set for the recipient
   redis-cli scard "demo:fanin:24h:<recipient_id>"
   redis-cli get "demo:inflow:<recipient_id>"
   ```
2. **Adjust Demo Profile Thresholds Live**:
   If only 2 people participated instead of 3, modify `configs/live_profile.yaml`:
   ```yaml
   demo_sensitivity:
     fan_in_distinct_senders: 2   # Lowered from 3 for 2-participant rehearsal
     pass_through_ratio: 0.60     # Lowered from 0.70
   ```
   Save the file. The backend automatically reloads the profile on the next transfer.
3. **Fallback to Phase 11 Scripted Story**:
   If Wi-Fi drops or participants disconnect, simply toggle the switch in the top-right corner from **"Live Sandbox Mode"** to **"Story Mode"**. You can immediately step through Acts 1–5 of the scripted mule ring with zero delay.

---

## 6. Examiner Q&A Defense Sheet

### Q1: "Why is the model detecting a mule ring with only 3 participants when the training data had 10–40 victim rings?"
> *"In production, high-volume models require 10 to 40 victims over multiple days to trigger structural fraud alerts. For a 5-minute live classroom demonstration, waiting 48 hours for 40 transactions is impossible.
> We explicitly designed a **Demo Sensitivity Profile** (`configs/live_profile.yaml`) with a 60x time-compression clock (1 real minute = 1 simulated hour) and lower volume thresholds (3 distinct senders, $\ge 70\%$ pass-through).
> As you can see on the projector banner, 'Demo Sensitivity Profile Active' is explicitly disclosed. Every transaction logs which profile was evaluated, preserving complete mathematical honesty."*

### Q2: "How does the system handle everyone sharing the college Wi-Fi network?"
> *"If we used raw IP addresses alone, everyone on this room's Wi-Fi would share the same `/24` subnet, causing false IP-clustering rings.
> In our design, the raw IP is down-weighted as a weak auxiliary signal. The primary entity identifier is a browser-generated cryptographically unique `device_id` stored client-side. Furthermore, the analyst console provides a dynamic 'Network Label' manager, allowing us to assign distinct virtual carrier labels (e.g., Cellular-Jio, Campus-WiFi, Home-Broadband) to simulate multi-network topologies."*

### Q3: "Could this sandbox ever affect real banking systems or leak student data?"
> *"No. The sandbox ledger is entirely self-contained within Redis and backend memory. There are no API keys, webhooks, or connections to UPI or NPCI rails. Furthermore, participants only provide ephemeral display names—no phone numbers, bank accounts, or real names are collected or persisted."*
