$ErrorActionPreference = "Stop"
$Server = Join-Path $PSScriptRoot "server.py"
$AllowedScripts = @($Server, (Join-Path $PSScriptRoot "app.py"), (Join-Path $PSScriptRoot "server_v3.py"))
$Listeners = @(Get-NetTCPConnection -LocalPort 4824 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique)
$VerifiedIds = @()
foreach ($ListenerId in $Listeners) {
    $ProcessInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $ListenerId"
    $Recognized = @($AllowedScripts | Where-Object { $ProcessInfo.CommandLine -like "*$_*" }).Count -gt 0
    if (-not $Recognized) { throw "Unexpected listener on port 4824; restart cancelled" }
    $VerifiedIds += $ProcessInfo.ProcessId
    $ParentInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $($ProcessInfo.ParentProcessId)"
    $RecognizedParent = @($AllowedScripts | Where-Object { $ParentInfo.CommandLine -like "*$_*" }).Count -gt 0
    if ($ParentInfo.Name -eq "python.exe" -and $RecognizedParent) { $VerifiedIds += $ParentInfo.ProcessId }
}
if ($VerifiedIds.Count -gt 0) { Stop-Process -Id ($VerifiedIds | Select-Object -Unique) -Force -ErrorAction SilentlyContinue }
$Python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
Start-Process -FilePath $Python -ArgumentList @($Server,"--host","127.0.0.1","--port","4824","--no-browser") -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $PSScriptRoot "logs\server.stdout.log") -RedirectStandardError (Join-Path $PSScriptRoot "logs\server.stderr.log")
Write-Output "IRIS2 restart requested; check /api/health"
