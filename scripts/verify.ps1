[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repositoryRoot ".venv\Scripts\python.exe"
$artifactDirectory = Join-Path $repositoryRoot ".verification"

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Missing .venv. Follow BASELINE.md to create the locked environment first."
}

New-Item -ItemType Directory -Force -Path $artifactDirectory | Out-Null

function Invoke-Gate {
    param(
        [Parameter(Mandatory)] [string] $Name,
        [Parameter(Mandatory)] [scriptblock] $Command
    )
    Write-Host "==> $Name"
    $log = Join-Path $artifactDirectory "$Name.log"
    & $Command 2>&1 | Tee-Object -FilePath $log
    if ($LASTEXITCODE -ne 0) {
        throw "$Name failed with exit code $LASTEXITCODE. See $log"
    }
}

Push-Location $repositoryRoot
try {
    Invoke-Gate "python-ruff" { & $python -m ruff check . }
    Invoke-Gate "python-pytest" { & $python -m pytest -q }
    Invoke-Gate "observer-lint" { & npm --prefix dashboard run lint }
    Invoke-Gate "observer-build" { & npm --prefix dashboard run build }
    Invoke-Gate "observer-tests" { & npm --prefix dashboard test }
    Write-Host "All Milestone 13 verification gates passed."
}
finally {
    Pop-Location
}
