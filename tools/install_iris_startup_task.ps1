param(
    [string]$TaskName = "IRIS Heat Exchanger Server"
)

$ErrorActionPreference = "Stop"
$Launcher = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) "start_iris_background.ps1"
$PowerShell = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$CurrentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

if (-not (Test-Path -LiteralPath $Launcher -PathType Leaf)) {
    throw "IRIS background launcher not found: $Launcher"
}

$Action = New-ScheduledTaskAction `
    -Execute $PowerShell `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Launcher`""
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $CurrentUser
$Principal = New-ScheduledTaskPrincipal -UserId $CurrentUser -LogonType Interactive -RunLevel Limited
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -StartWhenAvailable

$Task = New-ScheduledTask -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings `
    -Description "Starts the local IRIS server and its scheduled-backup worker at user logon."
Register-ScheduledTask -TaskName $TaskName -InputObject $Task -Force | Out-Null
Get-ScheduledTask -TaskName $TaskName
