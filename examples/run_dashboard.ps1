param([switch]$NoBrowser)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$composeFile = Join-Path $PSScriptRoot "neo4j-compose.yml"
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$dashboardRoot = Join-Path $projectRoot "dashboard"

function Test-DockerEngine {
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    docker info 2>&1 | Out-Null
    $available = $LASTEXITCODE -eq 0
    $ErrorActionPreference = $previousPreference
    return $available
}

if ($env:RLMGRAPH_BACKEND -eq "neo4j") {
if (-not (Test-DockerEngine)) {
    $dockerDesktop = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    if (-not (Test-Path -LiteralPath $dockerDesktop)) {
        throw "Docker engine is unavailable and Docker Desktop was not found."
    }
    Start-Process -FilePath $dockerDesktop -WindowStyle Hidden
    $ready = $false
    foreach ($attempt in 1..60) {
        Start-Sleep -Seconds 2
        if (Test-DockerEngine) {
            $ready = $true
            break
        }
    }
    if (-not $ready) {
        throw "Docker Desktop did not become ready within 120 seconds."
    }
}

docker compose -f $composeFile up -d --wait
if ($LASTEXITCODE -ne 0) {
    throw "Neo4j Docker Compose startup failed."
}
}

if (-not (Get-NetTCPConnection -LocalPort 8787 -State Listen -ErrorAction SilentlyContinue)) {
    Start-Process -FilePath $python -ArgumentList "-m", "rlmgraph.dashboard" `
        -WorkingDirectory $projectRoot -WindowStyle Hidden
}

if (-not (Get-NetTCPConnection -LocalPort 3000 -State Listen -ErrorAction SilentlyContinue)) {
    Start-Process -FilePath "npm.cmd" -ArgumentList "run", "dev" `
        -WorkingDirectory $dashboardRoot -WindowStyle Hidden
}

$apiReady = $false
foreach ($attempt in 1..30) {
    try {
        $response = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:8787/api/profiles" -TimeoutSec 2
        if ($response.StatusCode -eq 200) { $apiReady = $true; break }
    } catch { Start-Sleep -Seconds 1 }
}
if (-not $apiReady) {
    throw "TGRAM conversation service did not become ready. The dashboard requires the local API on port 8787."
}

$dashboardReady = $false
foreach ($attempt in 1..30) {
    Start-Sleep -Seconds 1
    try {
        $response = Invoke-WebRequest -UseBasicParsing "http://localhost:3000/"
        if ($response.StatusCode -eq 200) {
            $dashboardReady = $true
            break
        }
    } catch {
        continue
    }
}
if (-not $dashboardReady) {
    throw "RLMGraph Observer did not become ready within 30 seconds."
}

if (-not $NoBrowser) { Start-Process "http://localhost:3000/" }
Write-Output "RLMGraph Observer is running at http://localhost:3000/"
