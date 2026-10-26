$ErrorActionPreference = "Stop"

$AppDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$ProjectRoot = Split-Path -Parent $AppDir
$Python = Join-Path $AppDir ".venv\Scripts\python.exe"
$Server = Join-Path $AppDir "server.py"
$LogDir = Join-Path $AppDir "backups\logs"
$Log = Join-Path $LogDir "server.log"

if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "Python virtual environment not found: $Python"
}
if (-not (Test-Path -LiteralPath $Server -PathType Leaf)) {
    throw "IRIS server entry point not found: $Server"
}

New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
Set-Location -LiteralPath $ProjectRoot
& $Python $Server --no-browser *>> $Log
exit $LASTEXITCODE
