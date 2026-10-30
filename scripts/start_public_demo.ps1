# ==============================================================================
# start_public_demo.ps1 - Start Live Demo with Temporary Public Tunnel
# ==============================================================================

param(
    [string]$TunnelType = "auto",  # "cloudflared", "ngrok", or "auto"
    [string]$RoomCode = "MULE42",
    [int]$FrontendPort = 5173,
    [int]$BackendPort = 8000
)

$ErrorActionPreference = "Continue"

Write-Host "==================================================================" -ForegroundColor Cyan
Write-Host "     STARTING FRAUDENGINE LIVE DEMO & PUBLIC GATEWAY             " -ForegroundColor Cyan
Write-Host "==================================================================" -ForegroundColor Cyan

# 1. Preflight Checks (Item 15)
Write-Host "`n[1/5] Running Preflight Service Checks..." -ForegroundColor Yellow

function Test-PortBoundLocal($port) {
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $iar = $client.BeginConnect("127.0.0.1", $port, $null, $null)
        $success = $iar.AsyncWaitHandle.WaitOne(300, $false)
        if ($success) {
            $client.EndConnect($iar)
            $client.Close()
            return $true
        }
        $client.Close()
        return $false
    } catch {
        return $false
    }
}

$backendRunning = Test-PortBoundLocal -port $BackendPort
$frontendRunning = Test-PortBoundLocal -port $FrontendPort
$redisRunning = Test-PortBoundLocal -port 6379
$kafkaRunning = Test-PortBoundLocal -port 9092

$backendStatus = if ($backendRunning) { "[ONLINE]" } else { "[STARTING]" }
$backendColor  = if ($backendRunning) { "Green" } else { "Yellow" }
Write-Host "      Backend (:8000):   $backendStatus" -ForegroundColor $backendColor

$frontendStatus = if ($frontendRunning) { "[ONLINE]" } else { "[STARTING]" }
$frontendColor  = if ($frontendRunning) { "Green" } else { "Yellow" }
Write-Host "      Frontend (:5173):  $frontendStatus" -ForegroundColor $frontendColor

$redisStatus = if ($redisRunning) { "[ONLINE]" } else { "[OFFLINE / IN-MEMORY]" }
$redisColor  = if ($redisRunning) { "Green" } else { "DarkYellow" }
Write-Host "      Redis (:6379):     $redisStatus" -ForegroundColor $redisColor

$kafkaStatus = if ($kafkaRunning) { "[ONLINE]" } else { "[OFFLINE / SIMULATED]" }
$kafkaColor  = if ($kafkaRunning) { "Green" } else { "DarkYellow" }
Write-Host "      Redpanda (:9092):  $kafkaStatus" -ForegroundColor $kafkaColor

# 2. Start Backend & Frontend if not already running
if (-not $backendRunning) {
    Write-Host "`n[2/5] Starting Backend Server on 127.0.0.1:$BackendPort..." -ForegroundColor Yellow
    Start-Process -FilePath "python" -ArgumentList "-m uvicorn fraudengine.api.app:app --host 127.0.0.1 --port $BackendPort" -WindowStyle Minimized
    Start-Sleep -Seconds 2
}

if (-not $frontendRunning) {
    Write-Host "`n[3/5] Starting Frontend Dev Server on 127.0.0.1:$FrontendPort..." -ForegroundColor Yellow
    Start-Process -FilePath "npm" -ArgumentList "run dev -- --host 127.0.0.1 --port $FrontendPort" -WorkingDirectory "frontend" -WindowStyle Minimized
    Start-Sleep -Seconds 2
}

# 3. Tunnel Detection & Launch (Item 10 & 15)
Write-Host "`n[4/5] Launching Temporary Public Tunnel for Participant Gateway..." -ForegroundColor Yellow

$toolsCloudflared = Join-Path (Split-Path $PSScriptRoot -Parent) "tools\cloudflared.exe"
$cloudflaredBin = if (Test-Path $toolsCloudflared) { $toolsCloudflared } elseif (Get-Command cloudflared -ErrorAction SilentlyContinue) { "cloudflared" } else { $null }
$hasCloudflared = $cloudflaredBin -ne $null
$hasNgrok = (Get-Command ngrok -ErrorAction SilentlyContinue) -ne $null
$publicUrl = ""

$tunnelLog = "$PSScriptRoot\tunnel.log"
if (Test-Path $tunnelLog) { Remove-Item $tunnelLog -Force }

if ($hasCloudflared -and ($TunnelType -eq "auto" -or $TunnelType -eq "cloudflared")) {
    Write-Host "      Using Cloudflare Quick Tunnel ($cloudflaredBin)..." -ForegroundColor Green
    Start-Process -FilePath $cloudflaredBin -ArgumentList "tunnel --url http://127.0.0.1:$FrontendPort" -RedirectStandardError $tunnelLog -WindowStyle Minimized
    
    # Poll log for trycloudflare.com URL
    for ($i = 0; $i -lt 15; $i++) {
        Start-Sleep -Seconds 1
        if (Test-Path $tunnelLog) {
            $content = Get-Content $tunnelLog -Raw
            if ($content -match "https://[a-zA-Z0-9-]+\.trycloudflare\.com") {
                $publicUrl = $matches[0]
                break
            }
        }
    }
} elseif ($hasNgrok -and ($TunnelType -eq "auto" -or $TunnelType -eq "ngrok")) {
    Write-Host "      Using ngrok tunnel..." -ForegroundColor Green
    Start-Process -FilePath "ngrok" -ArgumentList "http $FrontendPort" -WindowStyle Minimized
    Start-Sleep -Seconds 3
    try {
        $ngrokApi = Invoke-RestMethod -Uri "http://127.0.0.1:4040/api/tunnels"
        $publicUrl = $ngrokApi.tunnels[0].public_url
    } catch {}
} else {
    Write-Host "      [!] Neither 'cloudflared' nor 'ngrok' found on PATH." -ForegroundColor Yellow
    Write-Host "          Install Cloudflare Tunnel: 'winget install Cloudflare.cloudflared' or download from cloudflare.com" -ForegroundColor Gray
    Write-Host "          Falling back to Local Wi-Fi LAN Mode." -ForegroundColor Cyan
}

# 4. Configure Public URL & Join Link
Write-Host "`n[5/5] Generating Live Session..." -ForegroundColor Yellow
if ($publicUrl) {
    [System.Environment]::SetEnvironmentVariable("PUBLIC_BASE_URL", $publicUrl, "Process")
    $joinUrl = "$publicUrl/app?room=$RoomCode"
    Write-Host "      ===========================================================" -ForegroundColor Green
    Write-Host "      PUBLIC PARTICIPANT GATEWAY ACTIVE:" -ForegroundColor Green
    Write-Host "      $joinUrl" -ForegroundColor Cyan
    Write-Host "      ===========================================================" -ForegroundColor Green
    Write-Host "      - Audience scans QR code or navigates to the public URL above." -ForegroundColor Gray
    Write-Host "      - Console & Admin routes are strictly BLOCKED on the public tunnel (HTTP 403)." -ForegroundColor Gray
} else {
    $joinUrl = "http://localhost:$FrontendPort/app?room=$RoomCode"
    Write-Host "      Local Mode URL: $joinUrl" -ForegroundColor Gray
}

# Open Analyst Console Locally
$consoleUrl = "http://localhost:$FrontendPort/demo"
Write-Host "`nOpening Analyst Console locally: $consoleUrl" -ForegroundColor Cyan
Start-Process $consoleUrl

Write-Host "`nDemo is running. Use scripts/stop_public_demo.ps1 when your presentation concludes." -ForegroundColor Green
