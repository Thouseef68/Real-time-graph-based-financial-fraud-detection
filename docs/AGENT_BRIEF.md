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
8. If a phase fails its acceptance criteria twice, log the blocker, skip to
<truncated 18988 bytes>
 seed script, starts
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