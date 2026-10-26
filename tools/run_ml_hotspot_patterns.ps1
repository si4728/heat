param(
    [string]$PythonPath = "",
    [string]$DatabasePath = "",
    [string]$ArtifactRoot = ""
)

$projectRoot = Split-Path -Parent $PSScriptRoot
$packageRoot = Split-Path -Parent $projectRoot
if (-not $PythonPath) {
    $PythonPath = Join-Path $projectRoot ".venv-ml\Scripts\python.exe"
}
if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw "ML Python executable not found: $PythonPath"
}
if (-not $DatabasePath) {
    $DatabasePath = Join-Path $projectRoot "data\heat_exchanger_db3.db"
}
if (-not $ArtifactRoot) {
    $ArtifactRoot = Join-Path $projectRoot "outputs\ml_implementation"
}

Push-Location $packageRoot
try {
    & $PythonPath -m iris2.ml.cli run-hotspot-patterns `
        --database $DatabasePath `
        --artifacts $ArtifactRoot
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
