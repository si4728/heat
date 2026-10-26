param(
    [Parameter(Mandatory = $true)]
    [string]$SourceRoot,
    [Parameter(Mandatory = $true)]
    [string]$OutputPath
)

$ErrorActionPreference = 'Stop'

function Convert-DbValue {
    param([object]$Value)
    if ($null -eq $Value -or $Value -is [DBNull]) {
        return $null
    }
    if ($Value -is [DateTime]) {
        return $Value.ToString('o')
    }
    return $Value
}

function Read-MdbTable {
    param(
        [System.Data.OleDb.OleDbConnection]$Connection,
        [string]$TableName
    )
    $command = $Connection.CreateCommand()
    $command.CommandText = "SELECT * FROM [$TableName]"
    $adapter = New-Object System.Data.OleDb.OleDbDataAdapter($command)
    $table = New-Object System.Data.DataTable
    [void]$adapter.Fill($table)
    $items = @()
    foreach ($row in $table.Rows) {
        $item = [ordered]@{}
        foreach ($column in $table.Columns) {
            $item[$column.ColumnName] = Convert-DbValue $row[$column.ColumnName]
        }
        $items += [pscustomobject]$item
    }
    return ,$items
}

$source = [IO.Path]::GetFullPath($SourceRoot)
$target = [IO.Path]::GetFullPath($OutputPath)
$targetDirectory = [IO.Path]::GetDirectoryName($target)
[IO.Directory]::CreateDirectory($targetDirectory) | Out-Null

$documents = @()
$errors = @()
$wantedTables = @(
    'inspection',
    'section',
    'tube',
    'result',
    'tubeFeature',
    'featureCode'
)

$files = Get-ChildItem -LiteralPath (Join-Path $source 'VCM1'), (Join-Path $source 'VCM2') -Recurse -File -Filter '*.mdb' |
    Where-Object { $_.Name -ne 'Report.mdb' } |
    Sort-Object FullName

foreach ($file in $files) {
    $connection = New-Object System.Data.OleDb.OleDbConnection(
        "Provider=Microsoft.ACE.OLEDB.12.0;Data Source=$($file.FullName);Persist Security Info=False;"
    )
    try {
        $connection.Open()
        $available = @(
            $connection.GetSchema('Tables') |
                Where-Object { $_.TABLE_TYPE -eq 'TABLE' } |
                ForEach-Object { [string]$_.TABLE_NAME }
        )
        $tables = [ordered]@{}
        foreach ($tableName in $wantedTables) {
            if ($available -contains $tableName) {
                $tables[$tableName] = @(Read-MdbTable -Connection $connection -TableName $tableName)
            }
        }
        $relativePath = $file.FullName.Substring($source.TrimEnd('\').Length).TrimStart('\')
        $documents += [pscustomobject][ordered]@{
            path = $relativePath
            size = $file.Length
            modified_at = $file.LastWriteTime.ToString('o')
            tables = [pscustomobject]$tables
        }
    }
    catch {
        $errors += [pscustomobject][ordered]@{
            path = $file.FullName.Substring($source.TrimEnd('\').Length).TrimStart('\')
            error = $_.Exception.Message
        }
    }
    finally {
        $connection.Dispose()
    }
}

$payload = [pscustomobject][ordered]@{
    source_root = $source
    generated_at = (Get-Date).ToString('o')
    document_count = $documents.Count
    error_count = $errors.Count
    documents = $documents
    errors = $errors
}

$json = $payload | ConvertTo-Json -Depth 12 -Compress
[IO.File]::WriteAllText($target, $json, (New-Object Text.UTF8Encoding($false)))
Write-Output "OUTPUT=$target"
Write-Output "DOCUMENTS=$($documents.Count)"
Write-Output "ERRORS=$($errors.Count)"
