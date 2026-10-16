# Update only program files. Keep installation.json, settings and models byte-for-byte.
function Get-ExistingDataDirectory([string]$AppDirectory) {
    $configuration = Join-Path $AppDirectory 'installation.json'
    if (Test-Path -LiteralPath $configuration) {
        $value = Get-Content -LiteralPath $configuration -Raw -Encoding UTF8 | ConvertFrom-Json
        if (!$value.data_dir -or ![IO.Path]::IsPathRooted($value.data_dir)) { throw 'Invalid existing data directory.' }
        return [IO.Path]::GetFullPath($value.data_dir)
    }
    return Join-Path $AppDirectory 'data'
}

function Publish-AppUpdate([string]$PackageDirectory, [string]$AppDirectory) {
    $root = [IO.Path]::GetFullPath($AppDirectory).TrimEnd('\')
    $package = [IO.Path]::GetFullPath($PackageDirectory).TrimEnd('\')
    foreach ($required in @('aqa-copilot.exe','resources\backend\aqa-backend.exe','application-manifest.json')) {
        if (!(Test-Path -LiteralPath (Join-Path $package $required) -PathType Leaf)) { throw "Incomplete update: $required" }
    }
    $metadata = Get-Content -LiteralPath (Join-Path $package 'application-manifest.json') -Raw | ConvertFrom-Json
    if ($metadata.schema -ne 2 -or !$metadata.multi_model) { throw 'Unsupported update package.' }
    $data = [IO.Path]::GetFullPath((Get-ExistingDataDirectory $root)).TrimEnd('\')
    if ($data -eq $root -or $data.StartsWith($root+'\resources\',[StringComparison]::OrdinalIgnoreCase) -or $data -eq ($root+'\resources')) { throw 'Move data out of program resources before updating.' }
    $files = @('aqa-copilot.exe','application-manifest.json')
    if (Test-Path -LiteralPath (Join-Path $package 'README.md')) { $files += 'README.md' }
    $files += @(Get-ChildItem -LiteralPath (Join-Path $package 'resources') -Recurse -File | ForEach-Object { $_.FullName.Substring($package.Length+1) })
    # Refuse junctions/symlinks in either tree before touching installed files.
    foreach($tree in @($root,$package)) {
        if ((Get-Item -LiteralPath $tree).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Update directory cannot be a link.' }
        $resourcePath=Join-Path $tree 'resources'
        if (Test-Path -LiteralPath $resourcePath) {
            if ((Get-Item -LiteralPath $resourcePath).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Resources cannot be a link.' }
            if (Get-ChildItem -LiteralPath $resourcePath -Recurse -Force | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }) { throw 'Resources contain a link.' }
        }
    }
    $backup = Join-Path $root ('.setup\backups\'+[guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $backup -Force | Out-Null
    $changed = @()
    try {
        foreach ($relative in $files) {
            $target = [IO.Path]::GetFullPath((Join-Path $root $relative))
            if (!$target.StartsWith($root+'\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe update target.' }
            $saved = Join-Path $backup $relative
            $existed = Test-Path -LiteralPath $target -PathType Leaf
            if ($existed) {
                New-Item -ItemType Directory -Path (Split-Path -Parent $saved) -Force | Out-Null
                Copy-Item -LiteralPath $target -Destination $saved -Force
            }
            $changed += @{target=$target; saved=$saved; existed=$existed}
            New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
            Copy-Item -LiteralPath (Join-Path $package $relative) -Destination $target -Force
        }
    } catch {
        foreach ($entry in $changed) {
            if ($entry.existed) { Copy-Item -LiteralPath $entry.saved -Destination $entry.target -Force }
            elseif (Test-Path -LiteralPath $entry.target -PathType Leaf) { Remove-Item -LiteralPath $entry.target -Force }
        }
        throw
    }
    $ownership = Join-Path $root 'installation-files.json'
    if (Test-Path -LiteralPath $ownership) {
        $installed = Get-Content -LiteralPath $ownership -Raw -Encoding UTF8 | ConvertFrom-Json
        $installed.files = @(@($installed.files)+$files | Sort-Object -Unique)
        $installed | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $ownership -Encoding UTF8
    }
    Write-Output "Previous program files saved: $backup"
}
