# Back up or restore access ACLs for the fixed IRIS2 security-review targets.
# Backup is read-only apart from the private report. This script never changes grants
# automatically, never reads file contents, and never visits the sibling iris tree.
[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param(
    [ValidateSet('Backup', 'Restore')][string]$Mode = 'Backup',
    [string]$Snapshot
)
$ErrorActionPreference = 'Stop'
$workspace = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$targets = @('.', 'config', 'data', '.venv', 'web', 'application',
    'hx_configuration.conf', 'web/security.py', 'data/.session_secret',
    'config/database.conf', 'config/database-admin.conf',
    'config/database-readonly.conf', 'config/database-text-to-sql.conf')
$access = [Security.AccessControl.AccessControlSections]::Access
$broad = @('S-1-1-0', 'S-1-5-11', 'S-1-5-32-545')

function Resolve-Target([string]$relative) {
    if ($targets -notcontains $relative) { throw 'Snapshot contains an unexpected ACL target.' }
    $absolute = [IO.Path]::GetFullPath((Join-Path $workspace $relative))
    if ($absolute -ne $workspace -and -not $absolute.StartsWith($workspace + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw 'ACL target is outside IRIS2.'
    }
    $candidate = $absolute
    while ($candidate.Length -ge $workspace.Length) {
        if (Test-Path -LiteralPath $candidate) {
            if (((Get-Item -LiteralPath $candidate -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw 'Reparse points are not permitted in ACL targets.'
            }
        }
        if ($candidate -eq $workspace) { break }
        $candidate = Split-Path -Parent $candidate
    }
    return $absolute
}

if (-not $Snapshot) {
    $Snapshot = Join-Path $workspace ('reports/security-review-20261126/acl-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.json')
}
$snapshotPath = [IO.Path]::GetFullPath($Snapshot)
if (-not $snapshotPath.StartsWith((Join-Path $workspace 'reports') + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Keep the private ACL snapshot under iris2/reports.'
}
if ($Mode -eq 'Backup') {
    if (Test-Path -LiteralPath $snapshotPath) { throw 'Refusing to overwrite an ACL backup.' }
    $entries = foreach ($relative in $targets) {
        $absolute = Resolve-Target $relative
        if (Test-Path -LiteralPath $absolute) {
            $acl = Get-Acl -LiteralPath $absolute
            $wideRules = @($acl.Access | Where-Object {
                $sid = $_.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value
                ($broad -contains $sid) -and ($_.AccessControlType -eq 'Allow')
            } | ForEach-Object {
                [ordered]@{sid=$_.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value;
                    rights=$_.FileSystemRights.ToString(); inherited=$_.IsInherited}
            })
            [ordered]@{path=$relative; protected=$acl.AreAccessRulesProtected;
                sddl=$acl.GetSecurityDescriptorSddlForm($access); broadAllowRules=$wideRules}
        }
    }
    New-Item -ItemType Directory -Path (Split-Path -Parent $snapshotPath) -Force | Out-Null
    [ordered]@{machine=$env:COMPUTERNAME;workspace=$workspace;created=(Get-Date).ToString('o');entries=@($entries)} |
        ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $snapshotPath -Encoding UTF8
    Write-Output ('ACL backup saved: ' + $snapshotPath)
    Write-Output 'No access permissions were changed. Check parent directory write rights before hardening individual files.'
} else {
    $saved = Get-Content -LiteralPath $snapshotPath -Raw | ConvertFrom-Json
    if ($saved.machine -ne $env:COMPUTERNAME -or $saved.workspace -ne $workspace) {
        throw 'Restore requires a backup from this PC and workspace.'
    }
    # Validate the complete manifest before the first ACL write.
    foreach ($entry in $saved.entries) {
        $absolute = Resolve-Target $entry.path
        if (-not (Test-Path -LiteralPath $absolute)) { throw 'ACL target no longer exists.' }
        $validatedAcl = Get-Acl -LiteralPath $absolute
        $validatedAcl.SetSecurityDescriptorSddlForm($entry.sddl, $access)
    }
    foreach ($entry in $saved.entries) {
        $absolute = Resolve-Target $entry.path
        if ($PSCmdlet.ShouldProcess($absolute, 'Restore the saved access ACL')) {
            $acl = Get-Acl -LiteralPath $absolute
            $acl.SetSecurityDescriptorSddlForm($entry.sddl, $access)
            Set-Acl -LiteralPath $absolute -AclObject $acl
        }
    }
}
