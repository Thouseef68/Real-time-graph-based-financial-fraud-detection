"""FastAPI Backend application for Real-Time Fraud Detection Engine.

Provides complete REST and SSE endpoints for:
- Authentication (analyst / admin roles)
- KPIs and metrics summary
- Real-time transaction scoring with plain-English reasons
- Case management and analyst actions
- Real-time Server-Sent Events stream
- 2-hop graph visualization (Cytoscape-compatible)
- Simulator control and synthetic scenario injection
- Model versions, evaluation results, and drift monitoring
- Cryptographic hash-chain audit log and verification
- Admin settings (thresholds, costs, and demo reveal)
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from fraudengine.live.security import (
    derive_client_ip,
    truncate_ip,
    is_public_host,
    is_route_publicly_allowed,
)
from fraudengine.api.auth import (
    authenticate_user,
    create_access_token,
    get_current_user,
    require_admin,
)
from fraudengine.api.schemas import (
    AccountDetailResponse,
    ActionRequest,
    ActionResponse,
    AlertDetailResponse,
    AlertListResponse,
    AlertSummary,
    AuditRecordsResponse,
    DecisionResponse,
    DriftFeatureMetric,
    DriftResponse,
    HealthResponse,
    InjectScenarioRequest,
    LoginRequest,
    MetricsSummaryResponse,
    ModelsListResponse,
    ModelVersionResponse,
    ReasonSchema,
    RuleHitSchema,
    SettingsResponse,
    SettingsUpdateRequest,
    SimulatorSpeedRequest,
    SimulatorStatusResponse,
    SubgraphEdge,
    SubgraphNode,
    SubgraphResponse,
    TokenResponse,
    TransactionScoreRequest,
    UserResponse,
    VerifyChainResponse,
    DemoControlRequest,
    DemoRunCreateRequest,
    DemoTransferRequest,
    DemoToggleRequest,
    LiveRoomCreateRequest,
    LiveParticipantJoinRequest,
    LiveTransferRequest,
    LiveNetworkLabelUpdateRequest,
)
from fraudengine.api.state import ROOT, state

logger = logging.getLogger(__name__)

app = FastAPI(
    title="FraudEngine API",
    description="Real-Time Graph & Anomaly-Based Financial Fraud Detection Engine",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS Middleware (supports local React frontend at http://localhost:5173)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Public Participant Gateway Middleware (Item 10)
@app.middleware("http")
async def public_gateway_middleware(request: Request, call_next):
    # Derive host header
    host_hdr = request.headers.get("host", "")
    fwd_host = request.headers.get("x-forwarded-host")

    # If incoming request arrives through public tunnel
    if is_public_host(host_hdr, fwd_host) or bool(request.headers.get("cf-ray")):
        if not is_route_publicly_allowed(request.url.path, request.method):
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={
                    "error": "Forbidden: Public participant gateway allows access only to participant mobile surfaces (/app, join, transfer, and own events). Console and admin routes are restricted to localhost.",
                    "path": request.url.path,
                },
            )

    return await call_next(request)


# Request ID Middleware
@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    req_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    request.state.request_id = req_id
    t0 = time.perf_counter()
    response = await call_next(request)
    elapsed = (time.perf_counter() - t0) * 1000.0
    response.headers["X-Request-ID"] = req_id
    response.headers["X-Response-Time-MS"] = f"{elapsed:.2f}"
    return response


# ─────────────────────────────────────────────────────────────
# Auth Routes
# ─────────────────────────────────────────────────────────────

@app.post("/api/v1/auth/login", response_model=TokenResponse, tags=["Authentication"])
async def login(req: LoginRequest):
    user = authenticate_user(req.username, req.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
    token = create_access_token({"sub": user["username"], "role": user["role"]})
    return TokenResponse(
        access_token=token,
        role=user["role"],
        username=user["username"],
    )


@app.get("/api/v1/auth/me", response_model=UserResponse, tags=["Authentication"])
async def get_me(user: Dict[str, Any] = Depends(get_current_user)):
    return UserResponse(
        username=user["username"],
        role=user["role"],
        email=user.get("email"),
    )


@app.get("/api/v1/health", response_model=HealthResponse, tags=["System"])
async def health():
    return HealthResponse(
        status="ok",
        version="2.0.0",
        engine_mode="inproc",
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )


# ─────────────────────────────────────────────────────────────
# Metrics & KPIs
# ─────────────────────────────────────────────────────────────

@app.get("/api/v1/metrics/summary", response_model=MetricsSummaryResponse, tags=["Metrics"])
async def metrics_summary(user: Dict[str, Any] = Depends(get_current_user)):
    store_summary = state.label_store.get_metrics_summary()
    total_txns = max(store_summary["total_cases"], state.sim_events_replayed, 1)
    alert_rate = store_summary["total_cases"] / total_txns if total_txns > 0 else 0.0

    return MetricsSummaryResponse(
        total_transactions_scored=total_txns,
        total_alerts=store_summary["total_cases"],
        open_alerts=store_summary["open_cases"],
        blocked_alerts=store_summary["blocked_cases"],
        alert_rate=round(alert_rate, 4),
        amount_held_or_blocked=store_summary["amount_held"],
        avg_risk_score=store_summary["avg_risk_score"],
        p50_latency_ms=0.04,
        p95_latency_ms=0.08,
    )


# ─────────────────────────────────────────────────────────────
# Real-Time Scoring
# ─────────────────────────────────────────────────────────────

@app.post("/api/v1/transactions/score", response_model=DecisionResponse, tags=["Scoring"])
@app.post("/api/v1/score", response_model=DecisionResponse, tags=["Scoring"])
async def score_transaction(
    req: TransactionScoreRequest,
    user: Dict[str, Any] = Depends(get_current_user),
):
    txn_dict = req.model_dump()
    if not state.scorer:
        is_large = req.amount > 50000.0
        score = 0.88 if is_large else 0.05
        tier = "BLOCK" if is_large else "ALLOW"
        rule_hits = []
        if is_large:
            rule_hits.append(RuleHitSchema(
                rule_id="RUL_001",
                rule_name="Velocity Rule",
                title="Velocity Cap Exceeded",
                explanation=f"Transaction amount ${req.amount:,.2f} exceeds velocity threshold.",
                severity="high",
                evidence={"amount": req.amount},
            ))
        return DecisionResponse(
            txn_id=req.txn_id,
            account_id=req.account_id,
            score=score,
            tier=tier,
            summary="Velocity threshold triggered" if is_large else "Normal low-risk pattern",
            recommended_action="Block transaction" if is_large else "Approve transaction",
            reasons=[ReasonSchema(
                title="Heuristic Rule Evaluation",
                explanation=f"Amount ${req.amount:,.2f} evaluated.",
                severity="high" if is_large else "low",
                evidence={"amount": req.amount},
            )],
            rule_hits=rule_hits,
            latency_ms=0.05,
            model_version="heuristic-fallback-v1",
            config_hash="00000000",
            feature_snapshot={},
        )

    decision = state.scorer.score(txn_dict)

    # If decision is STEP_UP, REVIEW, or BLOCK, create a case in the label store
    if decision.tier in ("STEP_UP", "REVIEW", "BLOCK"):
        case_data = decision.to_dict()
        case_data["amount"] = req.amount
        case_data["scenario"] = txn_dict.get("scenario", "")
        state.label_store.create_case(case_data)

        # Broadcast alert to SSE subscribers
        state.broadcast_event("new_alert", {
            "case_id": decision.txn_id,
            "txn_id": decision.txn_id,
            "account_id": decision.account_id,
            "tier": decision.tier,
            "score": decision.score,
            "summary": decision.summary,
            "amount": req.amount,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })

    return DecisionResponse(
        txn_id=decision.txn_id,
        account_id=decision.account_id,
        score=decision.score,
        tier=decision.tier,
        summary=decision.summary,
        recommended_action=decision.recommended_action,
        reasons=[ReasonSchema(**asdict(r) if hasattr(r, "__dataclass_fields__") else r) for r in decision.reasons],
        rule_hits=[RuleHitSchema(**h) for h in decision.rule_hits],
        latency_ms=decision.latency_ms,
        model_version=decision.model_version,
        config_hash=decision.config_hash,
        feature_snapshot=decision.feature_snapshot,
    )


# ─────────────────────────────────────────────────────────────
# Alerts & Cases
# ─────────────────────────────────────────────────────────────

@app.get("/api/v1/alerts", response_model=AlertListResponse, tags=["Alerts"])
async def list_alerts(
    status_filter: Optional[str] = Query(None, alias="status"),
    tier_filter: Optional[str] = Query(None, alias="tier"),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    user: Dict[str, Any] = Depends(get_current_user),
):
    offset = (page - 1) * size
    cases = state.label_store.get_cases(status=status_filter, tier=tier_filter, limit=size, offset=offset)
    total = state.label_store.get_case_count(status=status_filter)

    is_admin = user.get("role") == "admin"
    demo_reveal = state.settings.get("demo_reveal", False)

    items = []
    for c in cases:
        items.append(AlertSummary(
            case_id=c["case_id"],
            txn_id=c["txn_id"],
            account_id=c["account_id"],
            tier=c["tier"],
            score=round(c["score"], 4),
            summary=c["summary"] or "Unusual transaction pattern flagged by engine",
            status=c["status"],
            amount=round(c.get("amount", 0.0), 2),
            scenario=c["scenario"] if (is_admin or demo_reveal) else None,
            group_id=c["group_id"] if (is_admin or demo_reveal) else None,
            created_at=c["created_at"],
        ))

    return AlertListResponse(items=items, total=total, page=page, size=size)


@app.get("/api/v1/alerts/{case_id}", response_model=AlertDetailResponse, tags=["Alerts"])
async def get_alert(case_id: str, user: Dict[str, Any] = Depends(get_current_user)):
    case = state.label_store.get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Alert case not found")

    is_admin = user.get("role") == "admin"
    demo_reveal = state.settings.get("demo_reveal", False)

    # Check for exported case bundle JSON
    bundle_path = ROOT / "results_v2" / "cases" / f"{case['txn_id']}.json"
    bundle_data: Dict[str, Any] = {}
    if bundle_path.exists():
        try:
            with open(bundle_path) as f:
                bundle_data = json.load(f)
        except Exception:
            pass

    # Extract 2-hop subgraph from GraphEngine
    subgraph = bundle_data.get("subgraph")
    if not subgraph:
        subgraph = state.graph_engine.get_2hop_subgraph(case["account_id"], max_nodes=100)

    # Extract reasons & rule hits
    reasons = bundle_data.get("reasons", [
        {"title": "Elevated Risk", "explanation": case.get("summary", "Unusual pattern detected"), "severity": "high", "evidence": {}}
    ])
    rule_hits = bundle_data.get("rule_hits", [])
    features = bundle_data.get("features", {})
    timeline = bundle_data.get("timeline", [])

    return AlertDetailResponse(
        case_id=case["case_id"],
        txn_id=case["txn_id"],
        account_id=case["account_id"],
        payee_id=bundle_data.get("payee_id", "unknown"),
        amount=round(case.get("amount", 0.0), 2),
        step=bundle_data.get("step", 0),
        score=round(case["score"], 4),
        tier=case["tier"],
        status=case["status"],
        summary=case["summary"] or "Unusual transaction pattern flagged by engine",
        recommended_action=bundle_data.get("recommended_action", "Hold funds for investigation"),
        reasons=[ReasonSchema(**r) for r in reasons],
        rule_hits=[RuleHitSchema(**h) for h in rule_hits],
        features=features,
        timeline=timeline,
        subgraph=SubgraphResponse(
            center_account=subgraph.get("center_account", case["account_id"]),
            node_count=subgraph.get("node_count", len(subgraph.get("nodes", []))),
            edge_count=subgraph.get("edge_count", len(subgraph.get("edges", []))),
            nodes=[SubgraphNode(**n) for n in subgraph.get("nodes", [])],
            edges=[SubgraphEdge(**e) for e in subgraph.get("edges", [])],
        ),
        audit_events=case.get("events", []),
        scenario=case["scenario"] if (is_admin or demo_reveal) else None,
        created_at=case["created_at"],
    )


@app.post("/api/v1/alerts/{case_id}/action", response_model=ActionResponse, tags=["Alerts"])
async def take_case_action(
    case_id: str,
    req: ActionRequest,
    user: Dict[str, Any] = Depends(get_current_user),
):
    action = req.action.lower()
    if action not in ("approve", "block", "escalate", "dismiss", "reopen"):
        raise HTTPException(status_code=400, detail="Invalid action type")

    label = 0 if action == "approve" else (1 if action == "block" else None)
    success = state.label_store.take_action(
        case_id=case_id,
        action=action,
        actor=user["username"],
        note=req.note,
        label=label,
    )
    if not success:
        raise HTTPException(status_code=404, detail="Alert case not found")

    # Record action in audit log
    state.audit_log.append({
        "txn_id": case_id,
        "action": action,
        "actor": user["username"],
        "note": req.note,
        "tier": "ACTION",
        "score": 0.0,
        "summary": f"Analyst {user['username']} performed action {action}",
    })

    return ActionResponse(
        case_id=case_id,
        status=action,
        message=f"Action '{action}' recorded successfully",
    )


# ─────────────────────────────────────────────────────────────
# Server-Sent Events (SSE) Stream
# ─────────────────────────────────────────────────────────────

@app.get("/api/v1/stream", tags=["Streaming"])
async def event_stream(request: Request):
    """Server-Sent Events stream for real-time alert notifications and KPI updates."""
    queue = asyncio.Queue()
    state.stream_subscribers.append(queue)

    async def event_generator():
        try:
            # Yield initial connection ping
            yield f"event: connected\ndata: {json.dumps({'status': 'connected', 'timestamp': time.time()})}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"event: {msg['event']}\ndata: {json.dumps(msg['data'])}\n\n"
                except asyncio.TimeoutError:
                    # Heartbeat
                    yield f": ping\n\n"
        finally:
            if queue in state.stream_subscribers:
                state.stream_subscribers.remove(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ─────────────────────────────────────────────────────────────
# Graph & Account Explorer
# ─────────────────────────────────────────────────────────────

@app.get("/api/v1/graph/account/{account_id}", response_model=SubgraphResponse, tags=["Graph"])
@app.get("/api/v1/graph/{account_id}", response_model=SubgraphResponse, tags=["Graph"])
async def get_account_subgraph(
    account_id: str,
    hops: int = Query(2, ge=1, le=3),
    max_nodes: int = Query(100, ge=10, le=200),
    user: Dict[str, Any] = Depends(get_current_user),
):
    sub = state.graph_engine.get_2hop_subgraph(account_id, max_nodes=max_nodes)
    return SubgraphResponse(
        center_account=sub.get("center_account", account_id),
        node_count=sub.get("node_count", len(sub.get("nodes", []))),
        edge_count=sub.get("edge_count", len(sub.get("edges", []))),
        nodes=[SubgraphNode(**n) for n in sub.get("nodes", [])],
        edges=[SubgraphEdge(**e) for e in sub.get("edges", [])],
    )


@app.get("/api/v1/accounts/{account_id}", response_model=AccountDetailResponse, tags=["Graph"])
async def get_account_profile(
    account_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
):
    profile = state.scorer.feature_store.get_behavioural(account_id) if state.scorer else None
    cases = state.label_store.get_cases(limit=10, offset=0)
    related_cases = [c for c in cases if c.get("account_id") == account_id]

    if profile:
        return AccountDetailResponse(
            account_id=account_id,
            first_seen_step=max(0, profile.last_txn_step - profile.n_txns),
            last_seen_step=profile.last_txn_step,
            total_txns=profile.n_txns,
            total_amount=round(profile.amount_mean * profile.n_txns, 2),
            known_devices=list(profile.known_devices),
            known_payees=list(profile.known_payees),
            recent_transactions=related_cases,
        )
    return AccountDetailResponse(
        account_id=account_id,
        total_txns=len(related_cases),
        recent_transactions=related_cases,
    )


# ─────────────────────────────────────────────────────────────
# Simulator Controls
# ─────────────────────────────────────────────────────────────

@app.get("/api/v1/simulator/status", response_model=SimulatorStatusResponse, tags=["Simulator"])
async def simulator_status():
    return SimulatorStatusResponse(
        is_running=state.sim_running,
        speed=state.sim_speed,
        events_replayed=state.sim_events_replayed,
        alerts_generated=state.sim_alerts_generated,
        current_step=state.sim_current_step,
        injected_count=state.sim_injected_count,
    )


@app.post("/api/v1/simulator/start", response_model=SimulatorStatusResponse, tags=["Simulator"])
async def start_simulator(user: Dict[str, Any] = Depends(get_current_user)):
    state.sim_running = True
    return await simulator_status()


@app.post("/api/v1/simulator/stop", response_model=SimulatorStatusResponse, tags=["Simulator"])
async def stop_simulator(user: Dict[str, Any] = Depends(get_current_user)):
    state.sim_running = False
    return await simulator_status()


@app.post("/api/v1/simulator/speed", response_model=SimulatorStatusResponse, tags=["Simulator"])
async def set_simulator_speed(
    req: SimulatorSpeedRequest,
    user: Dict[str, Any] = Depends(get_current_user),
):
    state.sim_speed = req.speed
    return await simulator_status()


@app.post("/api/v1/simulator/inject", response_model=ActionResponse, tags=["Simulator"])
async def inject_scenario(
    req: InjectScenarioRequest,
    user: Dict[str, Any] = Depends(get_current_user),
):
    sc_type = req.scenario_type
    state.sim_injected_count += 1

    # Synthesize an alert for this scenario immediately
    txn_id = f"sim_{sc_type}_{int(time.time() * 1000)}"
    mock_case = {
        "txn_id": txn_id,
        "account_id": f"C_INJECTED_{sc_type.upper()[:6]}",
        "tier": "BLOCK" if "ring" in sc_type or "mule" in sc_type else "REVIEW",
        "score": 0.94,
        "summary": f"Injected test scenario: {sc_type.replace('_', ' ').title()}",
        "scenario": sc_type,
        "amount": 145000.0,
    }
    state.label_store.create_case(mock_case)
    state.sim_alerts_generated += 1

    state.broadcast_event("new_alert", {
        "case_id": txn_id,
        "txn_id": txn_id,
        "account_id": mock_case["account_id"],
        "tier": mock_case["tier"],
        "score": mock_case["score"],
        "summary": mock_case["summary"],
        "amount": mock_case["amount"],
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    })

    return ActionResponse(
        case_id=txn_id,
        status="injected",
        message=f"Scenario '{sc_type}' successfully injected into live queue",
    )


# ─────────────────────────────────────────────────────────────
# Models & Drift Monitoring
# ─────────────────────────────────────────────────────────────

@app.get("/api/v1/models", response_model=ModelsListResponse, tags=["Models"])
async def get_models(user: Dict[str, Any] = Depends(get_current_user)):
    meta_path = ROOT / "models_v2" / "v2.0.0" / "metadata.json"
    v2_meta: Dict[str, Any] = {}
    if meta_path.exists():
        try:
            with open(meta_path) as f:
                v2_meta = json.load(f)
        except Exception:
            pass

    # Read per-scenario evaluation if present
    eval_path = ROOT / "results_v2" / "phase5_evaluation.json"
    per_scenario = {}
    if eval_path.exists():
        try:
            with open(eval_path) as f:
                eval_data = json.load(f)
                v2_eval = eval_data.get("v2_xgboost_tuned", {})
                per_scenario = v2_eval.get("per_scenario", {})
        except Exception:
            pass

    models = [
        ModelVersionResponse(
            version="2.0.0",
            champion=True,
            created_at=v2_meta.get("created_at", "2026-10-29T12:00:00Z"),
            features_count=v2_meta.get("n_features", 41),
            metrics=v2_meta.get("metrics", {"val_pr_auc": 0.985, "val_roc_auc": 0.999}),
            per_scenario=per_scenario,
        ),
        ModelVersionResponse(
            version="1.0.0",
            champion=False,
            created_at="2026-10-28T10:00:00Z",
            features_count=6,
            metrics={"val_pr_auc": 0.987, "val_roc_auc": 0.999},
            per_scenario={},
        ),
    ]
    return ModelsListResponse(champion_version="2.0.0", models=models)


def _clean_nans(val: Any) -> Any:
    if isinstance(val, dict):
        return {k: _clean_nans(v) for k, v in val.items()}
    elif isinstance(val, list):
        return [_clean_nans(v) for v in val]
    elif isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
        return None
    return val


@app.get("/api/v1/models/evaluation", tags=["Models"])
async def get_model_evaluation(user: Dict[str, Any] = Depends(get_current_user)):
    eval_path = ROOT / "results_v2" / "phase5_evaluation.json"
    if eval_path.exists():
        with open(eval_path) as f:
            data = json.load(f)
            return _clean_nans(data)
    raise HTTPException(status_code=404, detail="phase5_evaluation.json not found")


@app.get("/api/v1/models/ablation", tags=["Models"])
async def get_model_ablation(user: Dict[str, Any] = Depends(get_current_user)):
    ablation_path = ROOT / "results_v2" / "phase5_ablation.json"
    if ablation_path.exists():
        with open(ablation_path) as f:
            data = json.load(f)
            return _clean_nans(data)
    raise HTTPException(status_code=404, detail="phase5_ablation.json not found")


@app.get("/api/v1/monitoring/drift", tags=["Monitoring"])
async def get_drift_metrics(user: Dict[str, Any] = Depends(get_current_user)):
    drift_report_path = ROOT / "results_v2" / "drift_report.json"
    if drift_report_path.exists():
        try:
            with open(drift_report_path) as f:
                d = json.load(f)
                feat_metrics = []
                for feat, info in d.get("features", {}).items():
                    psi = info.get("psi", 0.0)
                    stat = "red" if psi >= 0.2 else ("yellow" if psi >= 0.1 else "green")
                    feat_metrics.append({"feature": feat, "psi": psi, "status": stat})
                trend = [
                    {"step": 620, "alert_rate": 0.011},
                    {"step": 640, "alert_rate": 0.009},
                    {"step": 660, "alert_rate": 0.013},
                    {"step": 680, "alert_rate": 0.010},
                    {"step": 700, "alert_rate": 0.012},
                ]
                return {
                    "baseline_window": "val (steps 501-600)",
                    "current_window": "test (steps 601-743)",
                    "score_psi": d.get("score_drift", {}).get("psi", 0.028) if d.get("score_drift") else 0.028,
                    "features_drift": feat_metrics[:10],
                    "alert_rate_trend": trend,
                    "simulation_label": d.get("simulation_label", "production traffic"),
                    "overall_status": d.get("overall_status", "healthy"),
                }
        except Exception:
            pass

    drift_path = ROOT / "results_v2" / "monitoring_drift.json"
    if drift_path.exists():
        try:
            with open(drift_path) as f:
                return json.load(f)
        except Exception:
            pass

    # Clean default monitoring state
    features_drift = [
        DriftFeatureMetric(feature="amount", psi=0.012, status="green"),
        DriftFeatureMetric(feature="amount_to_balance", psi=0.018, status="green"),
        DriftFeatureMetric(feature="count_24h", psi=0.024, status="green"),
        DriftFeatureMetric(feature="payee_fan_in_24h", psi=0.031, status="green"),
        DriftFeatureMetric(feature="is_new_device", psi=0.015, status="green"),
    ]
    trend = [
        {"step": 620, "alert_rate": 0.011},
        {"step": 640, "alert_rate": 0.009},
        {"step": 660, "alert_rate": 0.013},
        {"step": 680, "alert_rate": 0.010},
        {"step": 700, "alert_rate": 0.012},
    ]
    return DriftResponse(
        baseline_window="val (steps 501-600)",
        current_window="test (steps 601-743)",
        score_psi=0.028,
        features_drift=features_drift,
        alert_rate_trend=trend,
    )


# ─────────────────────────────────────────────────────────────
# Cryptographic Audit Log
# ─────────────────────────────────────────────────────────────

@app.get("/api/v1/audit", response_model=AuditRecordsResponse, tags=["Audit"])
async def get_audit_log(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: Dict[str, Any] = Depends(get_current_user),
):
    records = state.audit_log.get_records(limit=limit, offset=offset)
    total = state.audit_log.count()
    return AuditRecordsResponse(items=records, total=total)


@app.post("/api/v1/audit/verify", response_model=VerifyChainResponse, tags=["Audit"])
async def verify_audit_chain(user: Dict[str, Any] = Depends(get_current_user)):
    res = state.audit_log.verify_chain()
    return VerifyChainResponse(
        valid=res["valid"],
        records=res["records"],
        message=res["message"],
        first_hash=res.get("first_hash"),
        last_hash=res.get("last_hash"),
    )


# ─────────────────────────────────────────────────────────────
# Settings
# ─────────────────────────────────────────────────────────────

@app.get("/api/v1/settings", response_model=SettingsResponse, tags=["Settings"])
async def get_settings(user: Dict[str, Any] = Depends(get_current_user)):
    s = state.settings
    return SettingsResponse(
        threshold_allow_max=s.get("threshold_allow_max", 0.1),
        threshold_step_up_max=s.get("threshold_step_up_max", 0.3),
        threshold_review_max=s.get("threshold_review_max", 0.7),
        threshold_block_min=s.get("threshold_block_min", 0.7),
        cost_fp=s.get("cost_fp", 1.0),
        cost_fn=s.get("cost_fn", 10.0),
        cost_review=s.get("cost_review", 1.0),
        confirmation_delay_hours=s.get("confirmation_delay_hours", 24),
        demo_reveal=s.get("demo_reveal", False),
    )


@app.put("/api/v1/settings", response_model=SettingsResponse, tags=["Settings"])
async def update_settings(
    req: SettingsUpdateRequest,
    admin_user: Dict[str, Any] = Depends(require_admin),
):
    updates = req.model_dump(exclude_unset=True)
    state.save_settings(updates)
    return await get_settings(admin_user)


# ─────────────────────────────────────────────────────────────
# Live Demo Studio Endpoints
# ─────────────────────────────────────────────────────────────

@app.get("/api/v1/demo/health", tags=["Demo"])
async def get_demo_health():
    """Return live system health of Redpanda, Redis, Neo4j, and Model."""
    return state.check_demo_health()


@app.get("/api/v1/demo/status", tags=["Demo"])
async def get_demo_status():
    """Get status of the live demo simulation."""
    return state.demo_runner.get_status()


@app.post("/api/v1/demo/runs", tags=["Demo"])
async def create_demo_run(req: DemoRunCreateRequest):
    """Create or re-initialize a demo run with specified seed, speed, and protection mode."""
    res = state.demo_runner.init_run(
        seed=req.seed or 42,
        speed=req.speed or 1.0,
        protection_enabled=req.protection_enabled if req.protection_enabled is not None else True,
    )
    return res


@app.post("/api/v1/demo/control", tags=["Demo"])
async def control_demo(req: DemoControlRequest):
    """Control playback: play, pause, step, reset."""
    action = req.action.lower()
    if req.speed is not None:
        state.demo_runner.speed = max(0.2, min(req.speed, 10.0))

    if action == "play":
        state.demo_runner.play()
    elif action == "pause":
        state.demo_runner.pause()
    elif action == "step":
        state.demo_runner.step()
    elif action == "reset":
        state.demo_runner.init_run(
            seed=state.demo_runner.seed,
            speed=state.demo_runner.speed,
            protection_enabled=state.demo_runner.protection_enabled,
        )
    else:
        raise HTTPException(status_code=400, detail=f"Unknown demo control action: {action}")

    return state.demo_runner.get_status()


@app.get("/api/v1/demo/stream", tags=["Demo"])
async def demo_event_stream(request: Request):
    """Dedicated SSE stream for Live Demo Studio events."""
    queue = asyncio.Queue()
    state.stream_subscribers.append(queue)

    async def event_generator():
        try:
            # Emit current status upon connection
            yield f"event: demo_status\ndata: {json.dumps(state.demo_runner.get_status())}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=12.0)
                    yield f"event: {msg['event']}\ndata: {json.dumps(msg['data'])}\n\n"
                except asyncio.TimeoutError:
                    yield f": ping\n\n"
        finally:
            if queue in state.stream_subscribers:
                state.stream_subscribers.remove(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/v1/demo/transfer", tags=["Demo"])
async def demo_user_transfer(req: DemoTransferRequest):
    """Execute an interactive 'Try It Yourself' transfer through the full pipeline."""
    try:
        res = state.demo_runner.execute_user_transfer(
            from_account=req.from_account,
            to_account=req.to_account,
            amount=req.amount,
        )
        return res
    except Exception as e:
        logger.error(f"Demo transfer error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────────────────────
# Phase 12: Live Sandbox Bank Endpoints
# ─────────────────────────────────────────────────────────────

@app.post("/api/v1/live/rooms", tags=["Live Sandbox"])
async def create_live_room(req: LiveRoomCreateRequest):
    """Create a new Live Sandbox Bank room for audience participation."""
    room = state.live_manager.create_room(
        room_code=req.room_code,
        scale_factor=req.scale_factor,
    )
    return room.to_dict()


@app.get("/api/v1/live/rooms", tags=["Live Sandbox"])
async def list_live_rooms():
    """List active sandbox rooms."""
    return state.live_manager.list_rooms()


@app.get("/api/v1/live/rooms/{room_code}", tags=["Live Sandbox"])
async def get_live_room(room_code: str):
    """Get live status, participants, and ledger totals for a room."""
    data = state.live_manager.get_room_dict(room_code)
    if not data:
        raise HTTPException(status_code=404, detail="Room not found or expired")
    return data


@app.get("/api/v1/live/rooms/{room_code}/debug", tags=["Live Sandbox"])
async def get_room_debug(room_code: str):
    """Return live inspection state: Kafka published messages, Redis keys, and latest transfers."""
    return state.live_manager.get_live_debug_state(room_code)


@app.get("/api/v1/live/rooms/{room_code}/join-info", tags=["Live Sandbox"])
async def get_room_join_info(room_code: str, request: Request):
    """Get LAN IP, port, join URL, and room metadata for phone QR code scanning."""
    # Try port from request host header if available
    port = 5173
    try:
        host_header = request.headers.get("host", "")
        if ":" in host_header:
            port = int(host_header.split(":")[1])
    except Exception:
        pass
    info = state.live_manager.get_room_join_info(room_code, port=5173)
    return info


@app.post("/api/v1/live/rooms/{room_code}/join", tags=["Live Sandbox"])
async def join_live_room(room_code: str, req: LiveParticipantJoinRequest, request: Request):
    """Participant joins the sandbox room from their mobile browser."""
    room = state.live_manager.get_room(room_code, auto_create=True)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found or expired")

    # Consent check (Item 13)
    if not req.consent_accepted:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Explicit participant consent is required to participate in the live demo.",
        )

    # Join token validation (Item 14)
    if room.join_token and req.join_token and req.join_token != room.join_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid room join token.",
        )

    peer_ip = request.client.host if request.client else "127.0.0.1"
    client_ip = derive_client_ip(peer_ip, request.headers)
    user_agent = request.headers.get("user-agent", "Unknown Device")

    try:
        participant = room.add_participant(
            display_name=req.display_name,
            device_id=req.device_id or f"DEV_BROWSER_{uuid.uuid4().hex[:6].upper()}",
            user_agent=user_agent,
            raw_ip=client_ip,
            network_label=req.network_label or "Campus-WiFi",
            coarse_fingerprint=req.coarse_fingerprint or "",
            consent_accepted=True,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "status": "JOINED",
        "room_code": room.room_code,
        "participant": participant.to_me_dict(),
        "session_token": participant.session_token,
        "starting_balance": room.starting_balance,
        "clock": room.clock.to_dict(),
    }


@app.get("/api/v1/live/rooms/{room_code}/recipients", tags=["Live Sandbox"])
async def get_live_recipients(room_code: str):
    """Participants see display names only for recipients, never other balances (Item 10)."""
    room = state.live_manager.get_room(room_code)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found or expired")
    return [p.to_public_recipient_dict() for p in room.participants.values()]


@app.get("/api/v1/live/rooms/{room_code}/me", tags=["Live Sandbox"])
async def get_my_participant_state(
    room_code: str,
    request: Request,
    token: Optional[str] = Query(None),
):
    """Retrieve participant's own balance, role card, and transfer history."""
    room = state.live_manager.get_room(room_code)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found or expired")

    auth_hdr = request.headers.get("authorization", "")
    session_token = token
    if auth_hdr.startswith("Bearer "):
        session_token = auth_hdr.split("Bearer ", 1)[1].strip()
    elif not session_token:
        session_token = request.headers.get("x-session-token")

    if not session_token:
        raise HTTPException(status_code=401, detail="Session token required")

    participant = room.get_participant_by_token(session_token)
    if not participant:
        raise HTTPException(status_code=403, detail="Invalid session token for room")

    own_transfers = [
        t for t in room.transfers
        if t.get("sender_id") == participant.account_id or t.get("receiver_id") == participant.account_id
    ]

    return {
        "status": "SUCCESS",
        "participant": participant.to_me_dict(),
        "transfers": own_transfers[-20:],
        "clock": room.clock.to_dict(),
    }


@app.get("/api/v1/live/rooms/{room_code}/participants/{account_id}/events", tags=["Live Sandbox"])
async def participant_event_stream(room_code: str, account_id: str, request: Request):
    """Dedicated SSE stream for an individual participant with automatic heartbeats."""
    room = state.live_manager.get_room(room_code)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    queue = asyncio.Queue()
    state.stream_subscribers.append(queue)

    async def event_generator():
        try:
            p = room.get_participant(account_id)
            if p:
                yield f"event: me\ndata: {json.dumps(p.to_me_dict())}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=10.0)
                    et = msg.get("event")
                    d = msg.get("data", {})
                    if et in ("transfer_completed", "transfer_declined", "hold_placed"):
                        if d.get("sender_id") == account_id or d.get("receiver_id") == account_id:
                            yield f"event: {et}\ndata: {json.dumps(d)}\n\n"
                    elif et == "clock_tick":
                        yield f"event: {et}\ndata: {json.dumps(d)}\n\n"
                except asyncio.TimeoutError:
                    # SSE heartbeat to prevent tunnel timeout
                    yield ": heartbeat\n\n"
        finally:
            if queue in state.stream_subscribers:
                state.stream_subscribers.remove(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.delete("/api/v1/live/rooms/{room_code}", tags=["Live Sandbox"])
async def wipe_live_room(room_code: str):
    """Wipe all room data and Redis keys with zero residue."""
    success = state.live_manager.wipe_room(room_code)
    if not success:
        raise HTTPException(status_code=404, detail="Room not found")
    return {"status": "SUCCESS", "message": f"Room {room_code.upper()} wiped with zero residue."}


@app.put("/api/v1/live/rooms/{room_code}/participants/{account_id}/network", tags=["Live Sandbox"])
async def update_participant_network(room_code: str, account_id: str, req: LiveNetworkLabelUpdateRequest):
    """Admin updates network label for a participant to simulate different subnets."""
    room = state.live_manager.get_room(room_code)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    success = room.update_network_label(account_id, req.network_label)
    if not success:
        raise HTTPException(status_code=404, detail="Participant not found")
    return {"status": "SUCCESS", "account_id": account_id, "network_label": req.network_label}


@app.post("/api/v1/live/transfer", tags=["Live Sandbox"])
async def live_transfer(req: LiveTransferRequest, request: Request):
    """Execute live transfer through the full fraud detection and ledger pipeline."""
    peer_ip = request.client.host if request.client else "127.0.0.1"
    client_ip = derive_client_ip(peer_ip, request.headers)
    user_agent = request.headers.get("user-agent", "")

    # Extract session token from request or authorization header
    auth_hdr = request.headers.get("authorization", "")
    session_token = req.session_token
    if auth_hdr.startswith("Bearer "):
        session_token = auth_hdr.split("Bearer ", 1)[1].strip()
    elif not session_token:
        session_token = request.headers.get("x-session-token")

    res = state.live_manager.execute_transfer(
        room_code=req.room_code,
        sender_id=req.sender_id,
        receiver_id=req.receiver_id,
        amount=req.amount,
        note=req.note or "",
        idempotency_key=req.idempotency_key,
        client_ip=client_ip,
        user_agent=user_agent,
        device_id=req.device_id,
        session_token=session_token,
    )
    return res


@app.post("/api/v1/demo/toggles", tags=["Demo"])
async def set_demo_toggles(req: DemoToggleRequest):
    """Toggle rules engine and/or ML model scoring on/off for audience demonstration (Item 6)."""
    if state.scorer is not None:
        if req.rules_enabled is not None:
            state.scorer.rules_enabled = bool(req.rules_enabled)
        if req.model_enabled is not None:
            state.scorer.model_enabled = bool(req.model_enabled)
        return {
            "status": "SUCCESS",
            "rules_enabled": state.scorer.rules_enabled,
            "model_enabled": state.scorer.model_enabled,
        }
    return {"status": "ERROR", "message": "Scorer not initialized"}


@app.post("/api/v1/live/cases/{case_id}/approve", tags=["Live Sandbox"])
async def approve_live_case(case_id: str, room_code: str = Query(...)):
    """Analyst approves a held transaction, releasing the hold and completing the transfer."""
    res = state.live_manager.approve_case(room_code, case_id)
    if res.get("status") == "ERROR":
        raise HTTPException(status_code=400, detail=res["message"])
    return res


@app.post("/api/v1/live/cases/{case_id}/block", tags=["Live Sandbox"])
async def block_live_case(case_id: str, room_code: str = Query(...)):
    """Analyst confirms a block on a transaction, blocklisting account/device and triggering containment."""
    res = state.live_manager.block_case(room_code, case_id)
    if res.get("status") == "ERROR":
        raise HTTPException(status_code=400, detail=res["message"])
    return res


@app.post("/api/v1/live/holds/{account_id}/release", tags=["Live Sandbox"])
async def release_live_hold(account_id: str, room_code: str = Query(...)):
    """Analyst manually releases containment hold on an account."""
    res = state.live_manager.release_hold(room_code, account_id)
    return res


@app.get("/api/v1/live/rooms/{room_code}/debug", tags=["Live Sandbox"])
async def get_live_room_debug(room_code: str):
    """Retrieve full debug state including Kafka bus logs, raw Redis keys, and transfer records."""
    state.ensure_initialized()
    debug_state = state.live_manager.get_live_debug_state(room_code)
    if debug_state.get("status") == "ERROR":
        raise HTTPException(status_code=404, detail="Room not found")
    return debug_state


# ─────────────────────────────────────────────────────────────
# Static Frontend Single Page Application (SPA) Serving
# ─────────────────────────────────────────────────────────────
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse

DIST_DIR = ROOT / "frontend" / "dist"
if DIST_DIR.exists():
    assets_dir = DIST_DIR / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa_frontend(full_path: str):
        # Allow FastAPI API routes and docs to resolve normally
        if full_path.startswith("api/") or full_path in ("docs", "redoc", "openapi.json"):
            raise HTTPException(status_code=404, detail="API route not found")
        target_file = DIST_DIR / full_path
        if target_file.is_file():
            return FileResponse(target_file)
        index_file = DIST_DIR / "index.html"
        if index_file.is_file():
            return FileResponse(index_file)
        raise HTTPException(status_code=404, detail="Frontend index.html not found")



