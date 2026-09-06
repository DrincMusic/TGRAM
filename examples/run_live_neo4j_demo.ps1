param(
    [switch]$Reset
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$composeFile = Join-Path $PSScriptRoot "neo4j-compose.yml"
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"

function Test-DockerEngine {
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    docker info 2>&1 | Out-Null
    $available = $LASTEXITCODE -eq 0
    $ErrorActionPreference = $previousPreference
    return $available
}

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
$demoArguments = @((Join-Path $PSScriptRoot "live_neo4j_demo.py"))
if ($Reset) {
    $demoArguments += "--reset"
}
& $python @demoArguments
if ($LASTEXITCODE -ne 0) {
    throw "RLMGraph live Neo4j demo failed."
}
