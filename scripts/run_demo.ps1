# PowerShell Demo Launcher Script
# Starts both the FastAPI backend and React frontend for the Fraud Detection Engine Demo.

$ErrorActionPreference = "Stop"

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " Starting Financial Fraud Detection Engine (v2.0) Demo    " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

$ROOT = Split-Path -Parent $PSScriptRoot
Set-Location $ROOT

# 1. Seed demo data if database does not exist
$DB_PATH = Join-Path $ROOT "data\label_store.db"
if (-not (Test-Path $DB_PATH)) {
    Write-Host "[1/3] Seeding demo SQLite database and alert queues..." -ForegroundColor Yellow
    python scripts\seed_demo.py
} else {
    Write-Host "[1/3] Demo database found at $DB_PATH" -ForegroundColor Green
}

# 2. Launch FastAPI Backend on port 8000
Write-Host "[2/3] Launching FastAPI Backend on http://localhost:8000 ..." -ForegroundColor Yellow
$BackendJob = Start-Process -FilePath "uvicorn" -ArgumentList "fraudengine.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--reload" -PassThru

# 3. Launch React Frontend on port 5173
Write-Host "[3/3] Launching React Frontend on http://localhost:5173 ..." -ForegroundColor Yellow
$FrontendDir = Join-Path $ROOT "frontend"
$FrontendJob = Start-Process -FilePath "npm" -ArgumentList "run", "dev" -WorkingDirectory $FrontendDir -PassThru

Write-Host ""
Write-Host "==========================================================" -ForegroundColor Green
Write-Host " SYSTEM READY! Access the Workbench in your browser:       " -ForegroundColor Green
Write-Host " Frontend: http://localhost:5173                           " -ForegroundColor White
Write-Host " API Docs: http://localhost:8000/docs                      " -ForegroundColor White
Write-Host "                                                          " -ForegroundColor Green
Write-Host " Demo Credentials:                                        " -ForegroundColor Yellow
Write-Host "   Analyst: analyst / analyst123                          " -ForegroundColor Yellow
Write-Host "   Admin:   admin / admin123                              " -ForegroundColor Yellow
Write-Host "==========================================================" -ForegroundColor Green
Write-Host "Press Ctrl+C or Enter to stop both services."

Read-Host

Write-Host "Stopping demo processes..." -ForegroundColor Yellow
Stop-Process -Id $BackendJob.Id -Force -ErrorAction SilentlyContinue
Stop-Process -Id $FrontendJob.Id -Force -ErrorAction SilentlyContinue
Write-Host "Demo stopped cleanly." -ForegroundColor Green
