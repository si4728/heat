$ErrorActionPreference = "Stop"
$Venv = Join-Path $PSScriptRoot ".venv"
python -m venv $Venv
if ($LASTEXITCODE -ne 0) { throw "venv creation failed" }
& (Join-Path $Venv "Scripts\python.exe") -m pip install -r (Join-Path $PSScriptRoot "requirements-lock.txt")
if ($LASTEXITCODE -ne 0) { throw "dependency installation failed" }
