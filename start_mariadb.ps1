$ErrorActionPreference = "Stop"
$Config = Join-Path $PSScriptRoot "data\mariadb\my.ini"
$Executable = Join-Path $PSScriptRoot "runtime\mariadb-11.4.12-winx64\bin\mariadbd.exe"
$Existing = Get-NetTCPConnection -LocalPort 3307 -State Listen -ErrorAction SilentlyContinue
if ($Existing) {
    $Owner = Get-Process -Id ($Existing | Select-Object -First 1).OwningProcess
    if ($Owner.Path -ne $Executable) { throw "Port 3307 is occupied by a different instance" }
    $OwnerDetails = Get-CimInstance Win32_Process -Filter "ProcessId = $($Owner.Id)"
    if ($OwnerDetails.CommandLine -notlike "*--defaults-file=$Config*") { throw "The listening instance uses another configuration" }
    Write-Output "IRIS2 MariaDB is already running on 127.0.0.1:3307"
    exit 0
}
if (-not (Test-Path -LiteralPath $Config)) { throw "MariaDB initialization is required" }
Start-Process -FilePath $Executable -ArgumentList "--defaults-file=$Config" -WorkingDirectory $PSScriptRoot -WindowStyle Hidden | Out-Null
$Deadline = [DateTime]::UtcNow.AddSeconds(30)
do {
    $Connection = New-Object System.Net.Sockets.TcpClient
    try {
        $PendingConnection = $Connection.ConnectAsync('127.0.0.1', 3307)
        if ($PendingConnection.Wait(500) -and $Connection.Connected) {
            Write-Output "IRIS2 MariaDB is ready on 127.0.0.1:3307"
            exit 0
        }
    } catch { } finally { $Connection.Dispose() }
    Start-Sleep -Milliseconds 250
} while ([DateTime]::UtcNow -lt $Deadline)
throw "MariaDB did not become ready within 30 seconds; check logs/mariadb-error.log"
