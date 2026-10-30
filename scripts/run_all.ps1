# PowerShell End-to-End Pipeline Reproduction Script
# Reproduces the entire pipeline end-to-end with fixed seeds (seed=42).

$ErrorActionPreference = "Stop"

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " Running Full Pipeline Reproduction (Fixed Seeds)         " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

$ROOT = Split-Path -Parent $PSScriptRoot
Set-Location $ROOT

# 1. Verification of Scenario Dataset
$SCENARIOS_PARQUET = Join-Path $ROOT "data\scenarios.parquet"
if (-not (Test-Path $SCENARIOS_PARQUET)) {
    Write-Host "[1/6] Generating 6.36M scenario transactions (Phase 2)..." -ForegroundColor Yellow
    python fraudengine\data\scenario_generator.py
} else {
    Write-Host "[1/6] Verified scenario dataset: $SCENARIOS_PARQUET" -ForegroundColor Green
}

# 2. Point-in-Time Feature Precomputation (Streaming)
Write-Host "[2/6] Streaming feature precomputation (Phase 3)..." -ForegroundColor Yellow
python scripts\precompute_features.py

# 3. Model Training & Anomaly Pipeline Stacking (Phase 4)
Write-Host "[3/6] Fitting champion XGBoost + Anomaly Pipeline (Phase 4)..." -ForegroundColor Yellow
python fraudengine\models\train_v2.py

# 4. Evaluation Benchmark & Ablation Study (Phase 5)
Write-Host "[4/6] Executing Phase 5 benchmarks, error analysis, and figures..." -ForegroundColor Yellow
python scripts\run_evaluation.py

# 5. Seed Demo Label Store & Case Bundles (Phase 7A)
Write-Host "[5/6] Seeding SQLite database and SHA-256 audit log (Phase 7A)..." -ForegroundColor Yellow
python scripts\seed_demo.py

# 6. Run Test Suite
Write-Host "[6/6] Executing pytest test suite..." -ForegroundColor Yellow
pytest

Write-Host ""
Write-Host "==========================================================" -ForegroundColor Green
Write-Host " PIPELINE COMPLETE! All artifacts generated in:           " -ForegroundColor Green
Write-Host "   Models:  models_v2/v2.0.0/                             " -ForegroundColor White
Write-Host "   Results: results_v2/                                   " -ForegroundColor White
Write-Host "   Tables:  results_v2/tables/                            " -ForegroundColor White
Write-Host "   Figures: results_v2/figures/                           " -ForegroundColor White
Write-Host "==========================================================" -ForegroundColor Green
