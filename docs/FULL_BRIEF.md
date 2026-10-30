<USER_REQUEST>
# AGENT BRIEF: Real-Time Graph & Anomaly-Based Financial Fraud Detection Engine

## ROLE
You are a senior ML/data engineer finishing a solo final-year project. Work autonomously
and complete as much as possible, in the priority order below. Correctness and honesty
matter more than speed. Do not ask me questions; record assumptions in STATUS.md.

## NON-NEGOTIABLE RULES
1. Git: work on branch agent/full-pipeline. If git is not initialised, init and commit the
   current state first. Commit after every completed phase with a clear message.
2. Do NOT modify or delete these verified files: features.py, train.py, scorer.py,
   replay_producer.py, seed_redis.py, eval_live.py, baselines.py, model/, data/,
   results/baselines.json. All new work goes in a new package fraudengine/, plus configs/,
   scripts/, tests/, docs/, models_v2/, results_v2/.
3. NEVER fabricate results. Every number in any document must come from a result file
   produced by a script you actually ran, and the document must cite that file path. If
   something failed or was not run, say so plainly.
4. No leakage. Tune only on the validation split. Use the test split (step > 600) once per
   final model family. Features for a transaction at event time t may use only information
   from strictly before t (event time, never wall-clock). Labels may be used as features
   only after a simulated confirmation delay (default 24 sim-hours).
5. Isolation: use run-scoped Kafka topic names (suffix run_id) and a per-run Redis key
   prefix. Never run FLUSHALL. Do not delete topics or keys you did not create.
6. Windows + PowerShell compatible: pathlib, no bash-only scripts. Pin dependencies in
   requirements.txt and log every install in STATUS.md.
7. Persistent memory: maintain STATUS.md at repo root. Re-read this brief and STATUS.md at
   the start of every phase. Log: done items, commands run, key results, blockers,
   deviations, assumptions.
8. If a phase fails its acceptance criteria twice, log the blocker, skip to the next
   independent phase, and continue. Do not loop.
9. Fixed seed 42. For learned models, report mean +/- std over 3 seeds where feasible.
10. OUT OF SCOPE: HTTP API/backend, frontend/dashboard, auth, cloud or live deployment,
    Grafana/Prometheus servers. Instead expose clean Python interfaces and JSON outputs
    so these can be added later.

## CURRENT STATE (verified by the user)
- Stack: Windows, PowerShell, VS Code, Docker Desktop. Redpanda and Redis containers exist.
- PaySim CSV at data/PS_20174392719_1491204439457_log.csv (6.3M rows, step = 1 hour).
- Split by step: train <= 500, val 501-600, test > 600 (test fraud rate ~1.5%).
- v1 XGBoost + Redis velocity scorer works; live replay matches offline (PR-AUC 0.9875
  vs 0.9877).
- Baseline results on test: XGB all features PR-AUC 0.9877; without drain features
  (orig_drained, amount_to_balance) 0.3601; without velocity 0.9898; logistic regression
  0.2816. Conclusion: PaySim fraud is single-shot account draining, so v1 is strong only on
  that pattern and velocity adds nothing there.
- GOAL: show a system that also catches burst fraud, mule rings, shared-device rings and
  other patterns PaySim lacks, using graph, behavioural and anomaly signals, evaluated
  honestly.

## PRIORITY TIERS
Tier 1 (must finish): Phases 1-5. Tier 2: Phases 6-7. Tier 3: Phase 8 and final report.
If you run low on budget, protect Tier 1 and always write the final status report.

## PHASE 1: Package skeleton and infrastructure
- Create package fraudengine/ with subpackages: config, data, features, graph, models,
  rules, scoring, feedback, monitoring, eval. YAML configs in configs/.
- Core API: Scorer.score(txn: dict) -> Decision, with no Kafka dependency. The Kafka
  consumer is a thin wrapper around it.
- docker-compose.yml with pinned images: redpanda, redis, neo4j, each with healthchecks.
- pytest skeleton, requirements.txt, ruff config.
Acceptance: pytest runs, compose services start, existing v1 scripts still run unchanged.

## PHASE 2: Realistic scenario generator (synthetic injection)
Build scripts/generate_scenarios.py producing a single chronologically ordered table
(parquet if pyarrow is available) merging PaySim with injected scenarios. Columns: txn_id,
step, ts, account_id, payee_id, amount, txn_type, old_balance_orig, new_balance_orig,
device_id, ip_prefix, label, scenario, group_id, split.
- Synthesise device_id and ip_prefix for all accounts deterministically (mostly 1 device
  per account, ~5% with a second device, households of 2-4 accounts sharing a device).
- Keep PaySim native fraud with scenario="paysim_native".
- Injected FRAUD scenarios (counts configurable in configs/scenarios.yaml):
  A burst_takeover: compromised account, new device, 8-25 small or medium transfers to 1-3
    mule payees within 1-3 hours. Account is NOT drained to zero.
  B mule_fanin_fanout: 10-40 victims pay one mule within 24h; mule forwards >=80% to 1-3
    collector accounts within 6h.
  C shared_device_ring: 5-15 accounts on one device/ip_prefix doing circular transfers
    and layering through common payees.
  D structuring: repeated just-below-threshold amounts over several days to varied payees.
  E dormant_reactivation: long-inactive account suddenly sends a large amount to a new
    payee from a new device.
- Injected HARD NEGATIVES (label 0): payroll (one employer to many employees), merchant-like
  customer accounts with high fan-in, household shared devices, large legitimate transfers
  that drain a balance, legitimate month-start bill-payment bursts.
- Injected transactions must have internally consistent balances, and amounts and balances
  drawn from distributions comparable to legitimate traffic.
- Every scenario instance is assigned to one split by its start step and must not span
  split boundaries. group_id identifies the instance for group-aware evaluation.
Sanity checks (log all in STATUS.md): (a) train an XGBoost using ONLY drain features and
report its PR-AUC on injected-scenario rows (should be low, otherwise the injection is
trivially separable and must be redesigned); (b) KS statistics comparing amount/balance
distributions of injected fraud vs legitimate; (c) table of counts and fraud rate by split
and scenario.

## PHASE 3: Point-in-time feature layer (incl. graph)
Implement features so the SAME feature functions run offline and online. Provide a
FeatureStore interface with an in-memory backend (offline replay, deterministic) and a Redis
backend (streaming). Hot-path features come from these stores. Neo4j is written
asynchronously in batches (UNWIND, constraints/indexes on account_id and device_id) and used
for multi-hop queries, periodic snapshot features and case subgraphs, not on the hot path.
Feature groups:
 1. base: amount, type, balance ratios, drain flags (as in v1).
 2. velocity: counts, sums, distinct payees at 1h/6h/24h.
 3. behavioural profile per account: running mean/std of amount (Welford), amount z-score,
    new-payee flag, payee first-seen, hour-of-day deviation, time since last txn, dormancy.
 4. device/network: is_new_device, accounts_per_device (as-of), devices_per_account,
    ip_prefix sharing.
 5. graph: payee distinct payers at 1h/24h (fan-in), payee outflow/inflow ratio within 24h
    (pass-through), payee first-seen age, is_merchant flag (PaySim "M" accounts are normal
    high fan-in; handle them separately from customer accounts), delayed-label fraud
    exposure within 2 hops (using only labels past the confirmation delay), degree and
    PageRank snapshots recomputed every 6 sim-hours (document the staleness).
Tests (must pass): (a) point-in-time test: a transaction's features are unchanged when all
later events are removed from the stream; (b) parity test: in-memory vs Redis backend give
identical features on a 20k-event sample (exact features match to 1e-9); (c) microbenchmark
of per-feature-group latency.
Cache heavy computations in data/cache/. Chunk or subsample where memory is tight.

## PHASE 4: Models
- Anomaly: IsolationForest and an autoencoder (PyTorch if installed, else sklearn
  MLPRegressor) trained on legitimate-only training rows over behavioural + velocity
  features. Convert scores to percentile ranks calibrated on validation.
- Supervised: XGBoost over all feature groups plus anomaly scores. Anomaly scores fed to
  XGBoost must be out-of-fold on the training set (group-aware time-based folds) to avoid
  optimistic stacking bias.
- Tuning: Optuna, at most 40 trials, on validation only, optimising PR-AUC at a fixed 1%
  alert budget. Subsample training data for tuning speed.
- Calibration: isotonic regression fit on validation.
- Save to models_v2/<version>/: model files, feature list, thresholds, data hash, metrics
  JSON, git commit hash.
- Stretch (only if time remains): Node2Vec or GraphSAGE embeddings as an ablation.

## PHASE 5: Evaluation core
Build an experiment runner producing results_v2/*.json, results_v2/tables/*.md and
results_v2/figures/*.png.
- Models: rule baselines, logistic regression, v1 XGBoost, and v2 variants.
- Ablations: remove each feature group one at a time, and add groups cumulatively.
- Metrics, overall AND per scenario: PR-AUC, recall at 1% and 0.5% alert budgets,
  precision at recall 0.8 and 0.9, cost-weighted loss (configurable review cost, fraud loss
  = amount, false-block cost). 95% bootstrap confidence intervals resampling by group_id /
  account. Time-slice stability (test split cut into 3 windows). False-positive rate on
  hard negatives specifically.
- Error analysis: top 50 false positives and false negatives with their features.
- Figures: PR curves, per-scenario recall bars, ablation chart, score distributions,
  calibration curve.
- Streaming parity run: replay the test split through Redpanda using the Scorer with fresh
  run-scoped topics, group and Redis prefix. Join to offline predictions by txn_id and
  report max score difference and decision agreement.
- Report honestly if graph or behavioural features show no lift on any scenario.

## PHASE 6 (Tier 2): Decision engine
- YAML-configurable rules engine (velocity caps, new-device + large-amount, blocklist),
  recording rule hits.
- Fusion of calibrated model probability and rules into tiers ALLOW / STEP_UP / REVIEW /
  BLOCK, with cost-based thresholds computed on validation from configured costs. Store the
  threshold sweeps.
- Reason codes: SHAP TreeExplainer top-k contributions mapped through templates to
  analyst-readable text (for example "payee received funds from 23 distinct senders in 24h")
  plus rule reasons. Compute SHAP only for non-ALLOW decisions to protect latency.
- Append-only audit log: JSONL with a hash chain (prev_hash). Each record has txn_id,
  model_version, config hash, feature snapshot, scores, decision, reasons, latency. Provide
  verify_chain() and a test that detects tampering.
- Latency: per-stage timings and a benchmark of 50k events reporting p50/p95/p99 and
  throughput for the in-memory and Redis backends separately. Target p95 < 100 ms; if
  missed, profile and report the bottleneck rather than hiding it.
- Kafka wrapper producing to a run-scoped decisions topic, extending the v1 format.

## PHASE 7 (Tier 2): Feedback loop and monitoring
- Simulated analyst: reviews REVIEW/BLOCK decisions up to a configurable daily capacity,
  confirms with configurable accuracy after a 24-72 sim-hour delay, and writes to a SQLite
  label store.
- Retraining job on a rolling window producing a challenger model. Champion/challenger
  promotion rule: non-inferior PR-AUC (using CIs) and cost on a held-out recent window,
  plus a passing calibration check. Model registry with versions, promote and rollback.
  Simulate 3 retraining cycles across the test period and report the effect.
- Drift monitor: PSI per feature and for the score distribution over rolling windows,
  alert-rate monitor, flag PSI > 0.2. Inject a synthetic drift to demonstrate detection.
  Output monitoring/*.json and a drift figure.

## PHASE 8 (Tier 3): Case bundles, docs, polish
- Case bundle exporter: for each REVIEW/BLOCK, a JSON with decision, reasons, features and
  a 2-hop subgraph (nodes/edges, capped at 100 nodes). Document the contract in
  docs/api_contracts.md for the future backend and frontend.
- Docs: README (Mermaid architecture diagram, setup, PowerShell reproduction commands),
  docs/design.md, docs/model_card.md, docs/data_card.md (state clearly that scenarios are
  synthetic and what that implies), docs/limitations.md, docs/threat_model.md (adversarial
  adaptation, evasion, label delay, privacy), docs/REPORT_DRAFT.md with results tables
  generated from the result files.
- scripts/run_all.ps1 reproducing the pipeline end to end with fixed seeds.
- pytest all green, ruff clean.

## EDIT 1: REPLACE RULE 10 WITH
10. OUT OF SCOPE: live or cloud deployment only (no hosting config, no cloud accounts, no
    public URLs, nothing pushed to a remote host). Local Dockerfiles and docker-compose for
    local development ARE in scope. The backend (FastAPI) and frontend (React) ARE in scope.
    Secrets go in .env with a committed .env.example. The only hard-coded credentials allowed
    are documented local demo users.

## EDIT 2: REPLACE "PRIORITY TIERS" WITH
Tier 1 (must finish): Phases 1-5.
Tier 2: Phase 6 (decision engine), Phase 7A (label store + analyst actions),
        Phase 8A (case bundles), Phase 9 (backend), Phase 10 (frontend).
Tier 3: Phase 7B (retraining + champion/challenger + drift), Phase 8B (docs, run_all, polish).
Split of existing phases: Phase 7A = simulated analyst + SQLite label store.
Phase 7B = retraining job, registry, drift monitor. Phase 8A = case bundle exporter.
Phase 8B = docs and scripts. The live OpenAPI schema replaces docs/api_contracts.md.
GRACEFUL DEGRADATION: the backend and frontend must work with whatever stage the engine has
reached. If SHAP reasons or graph features are unavailable, fall back to rule-based reasons
and an empty-state graph. Never let an unfinished earlier phase block Phases 9-10.
Phase 6 reason codes MUST include per-reason fields: title, explanation (plain English),
severity, evidence values; and a one-sentence plain-English summary per decision.

## PHASE 9 (Tier 2): Backend (FastAPI)
Stack: FastAPI, Pydantic v2, SQLAlchemy + SQLite (tables: users, cases, case_events,
labels, settings), JWT auth with roles analyst/admin, seeded local demo users, CORS for
http://localhost:5173, structured logging with request IDs, consistent error model.
ENGINE_MODE=inproc (default; Scorer runs in-process, no Kafka needed) or kafka (consume the
decisions topic). Demo mode must work with no Kafka.
Endpoints under /api/v1:
- POST auth/login, GET auth/me, GET health
- GET metrics/summary (KPIs over a time window: transactions scored, alert rate, amount
  held/blocked, p50/p95 latency, open cases)
- POST transactions/score (score one transaction, return decision, summary, reasons)
- GET alerts (filters: tier, status, scenario type, min score, date range; sort; pagination)
- GET alerts/{id} (full case: decision, summary, reasons, features, account timeline,
  2-hop subgraph, audit trail)
- POST alerts/{id}/action (approve | block | escalate + note; writes the label store and
  the audit log)
- GET stream (Server-Sent Events: new alerts and KPI ticks)
- GET graph/account/{id}?hops=2 and GET accounts/{id} (profile and history)
- Simulator: POST simulator/start|stop, GET simulator/status, POST simulator/speed,
  POST simulator/inject (scenario type) - replays the test split including injected
  scenarios through the Scorer at adjustable speed
- GET models (versions, champion, metrics, per-scenario results read from results_v2/)
- GET monitoring/drift (from Phase 7B outputs if present, else a clean empty state)
- GET audit and POST audit/verify (hash-chain verification)
- GET/PUT settings (thresholds and costs; PUT is admin-only and validated)
Ground-truth label and scenario fields are hidden from the analyst role. Admin only, behind
an explicit "demo reveal" flag.
Seed script: scripts/seed_demo.py runs the engine over a test-split slice with injected
scenarios to pre-populate at least 300 alerts spanning every scenario, so the UI is never
empty on first open.
Tests: pytest + httpx covering every endpoint (auth, permissions, filters, action flow, SSE
connects, audit verify). Report the latency of POST transactions/score.
Acceptance: all backend tests pass, /docs shows the OpenAPI schema, the demo works
end-to-end with ENGINE_MODE=inproc.

## PHASE 10 (Tier 2): Frontend (modern, easy to understand)
Stack: Vite + React + TypeScript, Tailwind CSS, shadcn/ui (Radix), TanStack Query, React
Router, Recharts, Cytoscape.js for graphs, lucide-react icons, Inter via fontsource (no
CDN). Typed API client generated from the backend OpenAPI schema (openapi-typescript).
Check "node -v" first. If Node is missing, log the blocker, still write the code, and mark
the frontend unbuilt in STATUS.md.
Also support a mock mode (JSON fixtures) so the UI runs when the backend is down.

DESIGN DIRECTION (follow it; avoid the default component-library look):
- Calm, modern fintech aesthetic. Light and dark themes (follow system, with a toggle).
- Neutral slate surfaces, ONE indigo accent. Green/amber/red are reserved strictly for risk
  meaning (Low / Medium / High / Critical) and used sparingly.
- 8px spacing grid, rounded-xl cards with soft borders and subtle shadows, generous white
  space, large readable KPI numbers, tabular figures for amounts, consistent icons.
- Layout: left navigation rail, top bar with global search (account / device / transaction)
  and a live-status pill (Live / Paused / Offline), breadcrumbs on detail pages.
- Motion: subtle only (alert slide-in, number count-up, skeleton shimmer).

UNDERSTANDABILITY RULES (the user must understand every screen without ML knowledge):
- Plain English everywhere. Every alert leads with a one-sentence summary, e.g. "Likely mule
  account: received money from 23 different senders in 24 hours and forwarded most of it
  onward."
- A risk gauge with a text label (Low / Medium / High / Critical), never a bare number.
- "Why was this flagged?": the top 3 reasons as cards (icon, title, explanation, evidence
  value). "What should I do?": a recommended action with a short rationale.
- Info tooltips with a glossary for terms such as fan-in, velocity, PSI, precision, recall.
- A first-run guided tour (4-5 steps). Designed empty, loading and error states on every
  page. Raw JSON only inside an "Advanced" expandable section.
- Amounts use a configurable currency symbol (default rupee sign).

PAGES:
1. Login.
2. Overview: KPI cards, alerts-over-time chart, alerts by scenario/type, latency card, top
   risky accounts, recent critical alerts.
3. Live Alerts: real-time queue via SSE (slide-in animation), filters synced to the URL,
   sortable paginated table, severity chips, quick-action buttons.
4. Case Detail: summary, risk gauge, reason cards, account activity timeline chart, entity
   graph (suspicious nodes highlighted, legend, click to expand neighbours), related alerts,
   action bar (Approve / Block / Escalate with a confirm dialog and note), audit trail.
5. Network Explorer: search an account or device, expand neighbours, filter by hop depth,
   legend explaining node and edge colours.
6. Model Performance: KPI cards, PR curve, per-scenario recall bars, ablation chart,
   hard-negative false-positive rate; each chart has a "What this means" caption in plain
   English. Data from /models.
7. Monitoring: drift (PSI) table/heatmap, alert-rate trend, model versions with champion /
   challenger status. Clean empty state if Phase 7B did not run.
8. Simulator (Demo Control): start/stop, speed slider, one-click "Inject scenario" buttons
   (burst takeover, mule ring, shared-device ring, structuring, dormant reactivation).
9. Audit Log: table plus a "Verify integrity" button showing the chain result clearly.
10. Settings: thresholds and costs (admin only), with validation and an explanation of
    each setting.

QUALITY GATES:
- Responsive (desktop first, usable on tablet), keyboard accessible, WCAG AA contrast,
  skeleton loaders, toasts, optimistic updates for case actions, URL-synced filters.
- "npm run build" and lint pass with zero TypeScript errors.
- Playwright smoke test visits every page in demo mode, asserts no console errors, and saves
  screenshots at 1440px in light and dark themes to docs/screenshots/. If browser download
  fails, log it and skip rather than looping.
- No lorem ipsum or placeholder text anywhere.
- scripts/run_demo.ps1 starts the backend (ENGINE_MODE=inproc), runs the seed script, starts
  the frontend dev server, and prints the URLs plus the demo credentials.

## EDIT 3: ADD TO THE FINAL STEP
8. How to launch the demo with one command and a 5-minute walkthrough script (which pages
   to show, in what order, what to say about each).
9. List of API endpoints and the screenshots folder path.
10. Anything in Phases 9-10 that is mocked, stubbed or degraded.

## FINAL STEP (always do this, even if budget runs out)
Write the final section of STATUS.md:
1. Phase checklist (done / partial / skipped) with commit hashes.
2. Key results table (pulled from result files, with file paths).
3. Sanity-check outcomes from Phase 2 and the leakage/parity test results.
4. Deviations from this brief and assumptions made.
5. Blockers and known issues.
6. Exact commands to reproduce each result.
7. What remains (backend, frontend, deployment, anything unfinished).
Then stop. Do not begin out-of-scope work. finish this in loop all pahse one by one
</USER_REQUEST>
<ADDITIONAL_METADATA>
The current local time is: 2026-10-29T18:59:53+05:30.

The user's current state is as follows:
Active Document: c:\Users\thous\OneDrive\Desktop\DSU_PROJECT\fraudengine\features\store.py (LANGUAGE_PYTHON)
Cursor is on line: 1
Other open documents:
- c:\Users\thous\OneDrive\Desktop\DSU_PROJECT\scripts\sanity_checks.py (LANGUAGE_PYTHON)
- c:\Users\thous\OneDrive\Desktop\DSU_PROJECT\scripts\precompute_features.py (LANGUAGE_PYTHON)
- c:\Users\thous\OneDrive\Desktop\DSU_PROJECT\fraudengine\models\train_v2.py (LANGUAGE_PYTHON)
- c:\Users\thous\OneDrive\Desktop\DSU_PROJECT\.gitignore (LANGUAGE_UNSPECIFIED)
- c:\Users\thous\OneDrive\Desktop\DSU_PROJECT\fraudengine\graph\__init__.py (LANGUAGE_PYTHON)
</ADDITIONAL_METADATA>
<USER_SETTINGS_CHANGE>
The user changed setting `Model Selection` from None to Claude Opus 4.6 (Thinking). No need to comment on this change if the user doesn't ask about it. If reporting what model you are, please use a human readable name instead of the exact string.
</USER_SETTINGS_CHANGE>