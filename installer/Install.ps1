[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$ConfigPath, [switch]$ValidateOnly, [string]$StartGate='')
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($StartGate) { while (!(Test-Path -LiteralPath $StartGate)) { Start-Sleep -Milliseconds 100 } }
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUNBUFFERED = '1'
$config = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
$sourceRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'Update.ps1')
function Local-Folder([string]$value) {
    if (!$value -or ![IO.Path]::IsPathRooted($value) -or $value.StartsWith('\\') -or $value.Contains('"')) { throw 'Choose an absolute local directory.' }
    $full = [IO.Path]::GetFullPath($value).TrimEnd('\')
    if ($full.Length -le 3 -or $full -eq $env:USERPROFILE -or $full -eq $env:WINDIR) { throw 'Choose a dedicated application directory, not a drive or system root.' }
    return $full
}
$appDir = Local-Folder $config.app_dir
if ($config.install_mode -eq 'update') {
    if (!(Test-Path -LiteralPath (Join-Path $appDir 'aqa-copilot.exe') -PathType Leaf)) { throw 'Select the existing application directory.' }
    $existingData = Get-ExistingDataDirectory $appDir
    if ($ValidateOnly) { Write-Output "Update valid. Data preserved at: $existingData"; return }
    Get-Process -Name aqa-copilot -ErrorAction SilentlyContinue | ForEach-Object {
        if ($_.Path -eq (Join-Path $appDir 'aqa-copilot.exe')) { throw 'Exit AQA Copilot from its tray menu before updating.' }
    }
    $stagedApp = Join-Path $appDir ('.setup\updates\'+[guid]::NewGuid().ToString('N'))
    Write-Output 'STAGE: Building update; installed application and models are preserved'
    & (Join-Path $sourceRoot 'Setup.ps1') -Mode Build -AppDir $stagedApp -BuildRoot (Join-Path $appDir '.setup\build')
    Write-Output 'STAGE: Applying update with backup of previous program files'
    Publish-AppUpdate $stagedApp $appDir
    Write-Output 'STAGE: Update complete. Settings, models and history preserved.'
    return
}
$dataDir = Local-Folder $config.data_dir
foreach($reserved in @($appDir,(Join-Path $appDir 'resources'),(Join-Path $appDir '.setup'))) {
    if($dataDir -eq $reserved -or ($reserved -ne $appDir -and $dataDir.StartsWith($reserved+'\',[StringComparison]::OrdinalIgnoreCase))) { throw 'Data must use a separate folder, not the application root, resources or .setup.' }
}
$buildRoot = Join-Path $appDir '.setup\build'
if ($config.install_mode -notin @('source','archive','models')) { throw 'Unknown installation mode.' }
if ($config.model -notmatch '^[a-zA-Z0-9][a-zA-Z0-9_.-]*(/[a-zA-Z0-9][a-zA-Z0-9_.-]*)?:[a-zA-Z0-9][a-zA-Z0-9_.-]*$' -or $config.model -match 'cloud' -or $config.model.Length -gt 160) { throw 'Invalid local model tag.' }
if ($config.asr_model -notin @('tiny','base','small','medium','large-v3') -or $config.device -notin @('cpu','cuda')) { throw 'Invalid speech configuration.' }
if ($config.install_mode -eq 'archive' -and !(Test-Path -LiteralPath $config.archive -PathType Leaf)) { throw 'Portable ZIP not found.' }
if ($config.install_mode -eq 'models' -and !(Test-Path -LiteralPath (Join-Path $appDir 'aqa-copilot.exe'))) { throw 'Select a folder with an installed AQA Copilot.' }
function Confirm-Archive($zip, [string]$appDir) {
        $manifest = $zip.GetEntry('AQA-Copilot/application-manifest.json')
        if (!$manifest) { throw 'This ZIP is too old: application-manifest.json is missing. Build a new release.' }
        $reader = [IO.StreamReader]::new($manifest.Open())
        try { $metadata = $reader.ReadToEnd() | ConvertFrom-Json } finally { $reader.Dispose() }
        if ($metadata.schema -ne 2 -or !$metadata.multi_model) { throw 'This build does not support model selection.' }
        if (!$zip.GetEntry('AQA-Copilot/aqa-copilot.exe') -or !$zip.GetEntry('AQA-Copilot/resources/backend/aqa-backend.exe')) { throw 'Incomplete application ZIP.' }
        # Validate all paths before writing any files. Never import someone else's data.
        foreach ($entry in $zip.Entries) {
            if ($entry.FullName -eq 'AQA-Copilot/' -and !$entry.Name) { continue }
            if (!$entry.FullName.StartsWith('AQA-Copilot/')) { throw 'Unexpected ZIP layout.' }
            $relative = $entry.FullName.Substring(12).Replace('/', '\')
            $target = [IO.Path]::GetFullPath((Join-Path $appDir $relative))
            if (!$target.StartsWith($appDir + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe ZIP entry.' }
            if ($relative -match '^(data|\.setup)\\' -or $relative -in @('installation.json','settings.json')) { throw 'ZIP contains private installation data.' }
        }
}
if ($config.install_mode -eq 'archive') {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $inspection = [IO.Compression.ZipFile]::OpenRead($config.archive)
    try { Confirm-Archive $inspection $appDir } finally { $inspection.Dispose() }
}
if ($ValidateOnly) { Write-Output 'Configuration valid. No installation actions performed.'; return }

Write-Output 'STAGE: Preparing installation'
Get-Process -Name aqa-copilot -ErrorAction SilentlyContinue | ForEach-Object {
    if ($_.Path -eq (Join-Path $appDir 'aqa-copilot.exe')) { throw 'Close AQA Copilot before continuing.' }
}
New-Item -ItemType Directory -Path $appDir,$dataDir -Force | Out-Null
$setupArguments = @{ BuildRoot=$buildRoot; AppDir=$appDir; DataDir=$dataDir; Model=$config.model; AsrModel=$config.asr_model; AsrDevice=$config.device; UpdateModelSettings=$true }
if ($config.install_mode -eq 'source') {
    Write-Output 'STAGE: Building application (first run downloads build tools)'
    & (Join-Path $sourceRoot 'Setup.ps1') -Mode Build @setupArguments
} elseif ($config.install_mode -eq 'archive') {
    Write-Output 'STAGE: Extracting portable build'
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [IO.Compression.ZipFile]::OpenRead($config.archive)
    try {
        Confirm-Archive $zip $appDir
        foreach ($entry in $zip.Entries) {
            if (!$entry.Name) { continue }
            $target = Join-Path $appDir $entry.FullName.Substring(12).Replace('/', '\')
            New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
            [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $target, $true)
        }
    } finally { $zip.Dispose() }
}
$manifestPath = Join-Path $appDir 'application-manifest.json'
if (!(Test-Path -LiteralPath $manifestPath)) { throw 'Installed app does not declare multi-model support. Reinstall from source or a new ZIP.' }
$appManifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
if ($appManifest.schema -ne 2 -or !$appManifest.multi_model) { throw 'Unsupported application version.' }

# Record installed application files before downloads; model/data files are excluded.
$installed = @('aqa-copilot.exe','application-manifest.json','README.md')
if (Test-Path (Join-Path $appDir 'resources')) {
    $installed += @(Get-ChildItem -LiteralPath (Join-Path $appDir 'resources') -Recurse -File | ForEach-Object { $_.FullName.Substring($appDir.Length + 1) })
}
$previous = Join-Path $appDir 'installation-files.json'
if (Test-Path $previous) { $installed += @((Get-Content $previous -Raw | ConvertFrom-Json).files) }
$settingsPath = Join-Path $dataDir 'settings.json'
$settings = @{}
if (Test-Path $settingsPath) {
    Copy-Item -LiteralPath $settingsPath -Destination ($settingsPath + '.backup-' + [guid]::NewGuid().ToString('N'))
    (Get-Content $settingsPath -Raw -Encoding UTF8 | ConvertFrom-Json).psobject.Properties | ForEach-Object { $settings[$_.Name]=$_.Value }
}
$settings.model=$config.model
$settings.asr_model_path=Join-Path $dataDir ('models\whisper-' + $config.asr_model)
$settings.asr_device=$config.device
$settings.asr_compute_type=if($config.device -eq 'cuda'){'int8_float16'}else{'int8'}
[IO.File]::WriteAllText($settingsPath, ($settings | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
[IO.File]::WriteAllText((Join-Path $appDir 'installation.json'), (@{data_dir=$dataDir}|ConvertTo-Json), [Text.UTF8Encoding]::new($false))

Write-Output 'STAGE: Registering application'
$linkPath = ''
if ($config.shortcut) {
    $linkPath = Join-Path ([Environment]::GetFolderPath('Desktop')) 'AQA Copilot.lnk'
    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut($linkPath)
    $link.TargetPath=Join-Path $appDir 'aqa-copilot.exe'
    $link.WorkingDirectory=$appDir
    $link.Save()
}
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'Uninstall.ps1') -Destination $appDir -Force
$hash = [BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::UTF8.GetBytes($appDir.ToLowerInvariant()))).Replace('-','').Substring(0,12)
$registry = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\AQACopilot-' + $hash
@{ files=@($installed | Sort-Object -Unique); shortcut=$linkPath; registry=$registry } | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $previous -Encoding UTF8
New-Item -Path $registry -Force | Out-Null
New-ItemProperty -Path $registry -Name DisplayName -Value 'AQA Copilot' -Force | Out-Null
New-ItemProperty -Path $registry -Name DisplayVersion -Value '1.1.0' -Force | Out-Null
New-ItemProperty -Path $registry -Name InstallLocation -Value $appDir -Force | Out-Null
New-ItemProperty -Path $registry -Name DisplayIcon -Value (Join-Path $appDir 'aqa-copilot.exe') -Force | Out-Null
New-ItemProperty -Path $registry -Name UninstallString -Value ('powershell.exe -NoProfile -ExecutionPolicy Bypass -File "' + (Join-Path $appDir 'Uninstall.ps1') + '"') -Force | Out-Null
if ($config.prepare_models) {
    Write-Output 'STAGE: Downloading and checking selected models'
    & (Join-Path $sourceRoot 'Setup.ps1') -Mode Models @setupArguments
}
Write-Output 'STAGE: Complete'
Write-Output "Installed: $appDir\aqa-copilot.exe"
Write-Output 'Application was not launched. Model inference has not been tested.'
