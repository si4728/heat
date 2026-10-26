param([string]$ListenHost = "127.0.0.1", [int]$Port = 4824, [switch]$NoBrowser, [switch]$HealthCheck)
$ErrorActionPreference = "Stop"
$AppDir = $PSScriptRoot
$Python = Join-Path $AppDir ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) { throw "Run iris2/setup.ps1 first" }
# Run in a child PowerShell because start_mariadb.ps1 exits when ready.
# Health checks must report the current state without starting dependencies.
if (-not $HealthCheck) {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $AppDir "start_mariadb.ps1")
    if ($LASTEXITCODE -ne 0) {
        Write-Error "IRIS2 MariaDB could not start. Check logs/mariadb-error.log; the web server was not started."
        exit 1
    }
}
$Arguments = @((Join-Path $AppDir "server.py"), "--host", $ListenHost, "--port", $Port)
if ($NoBrowser) { $Arguments += "--no-browser" }
if ($HealthCheck) { $Arguments += "--health-check" }
& $Python @Arguments
exit $LASTEXITCODE
