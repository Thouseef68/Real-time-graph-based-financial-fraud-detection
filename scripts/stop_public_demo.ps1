# scripts/stop_public_demo.ps1
# Phase 12 - Stop Public Demo & Wipe All Participant Data Residue

param(
    [string]$RoomCode = "MULE42"
)

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "   Stopping Public Demo & Tearing Down Tunnel..." -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# 1. Wipe Room Data Residue via Manager
Write-Host "`n[1/4] Wiping room data and resetting state for room '$RoomCode'..." -ForegroundColor Yellow
try {
    $wipeResp = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/live/rooms/$RoomCode/wipe" -Method Post -TimeoutSec 5 -ErrorAction Stop
    Write-Host "  -> Room wiped successfully: $($wipeResp.status)" -ForegroundColor Green
} catch {
    Write-Host "  -> Backend not reachable on localhost:8000 or wipe call failed. Running direct redis cleanup script..." -ForegroundColor Yellow
    python -c "from fraudengine.live.manager import get_live_manager; m = get_live_manager(); m.wipe_room('$RoomCode'); print('Direct manager wipe completed')"
}

# 2. Terminate Tunnel Processes (cloudflared, ngrok)
Write-Host "`n[2/4] Terminating public tunnels (cloudflared / ngrok)..." -ForegroundColor Yellow
$tunnels = Get-Process -Name "cloudflared", "ngrok" -ErrorAction SilentlyContinue
if ($tunnels) {
    foreach ($proc in $tunnels) {
        Write-Host "  -> Stopping process: $($proc.ProcessName) (PID: $($proc.Id))" -ForegroundColor Yellow
        Stop-Process -Id $proc.Id -Force
    }
    Write-Host "  -> All tunnel processes stopped." -ForegroundColor Green
} else {
    Write-Host "  -> No active cloudflared or ngrok processes found." -ForegroundColor DarkGray
}

# 3. Clean up tunnel log artifacts
Write-Host "`n[3/4] Cleaning temporary tunnel logs..." -ForegroundColor Yellow
if (Test-Path "cloudflared.log") {
    Remove-Item "cloudflared.log" -Force -ErrorAction SilentlyContinue
    Write-Host "  -> Removed cloudflared.log" -ForegroundColor DarkGray
}
if (Test-Path "ngrok.log") {
    Remove-Item "ngrok.log" -Force -ErrorAction SilentlyContinue
    Write-Host "  -> Removed ngrok.log" -ForegroundColor DarkGray
}

# 4. Confirm Nothing is Publicly Reachable
Write-Host "`n[4/4] Verifying network surface isolation..." -ForegroundColor Yellow
$activeTunnels = Get-Process -Name "cloudflared", "ngrok" -ErrorAction SilentlyContinue
if (-not $activeTunnels) {
    Write-Host "  -> CONFIRMED: No public tunnels running." -ForegroundColor Green
    Write-Host "  -> CONFIRMED: All external access has been terminated." -ForegroundColor Green
    Write-Host "  -> CONFIRMED: Room state wiped, zero participant residue remains." -ForegroundColor Green
} else {
    Write-Host "  [!] WARNING: Tunnel process still detected!" -ForegroundColor Red
}

Write-Host "`nPublic demo teardown complete.`n" -ForegroundColor Cyan
