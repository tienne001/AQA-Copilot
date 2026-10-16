$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
$testRoot=Join-Path $root ('.build\installer-tests-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $testRoot -Force | Out-Null
Add-Type -AssemblyName System.IO.Compression.FileSystem
Add-Type -AssemblyName System.IO.Compression
$configuration=@{app_dir=(Join-Path $testRoot 'app');data_dir=(Join-Path $testRoot 'data');install_mode='source';archive='';model='qwen3:4b';asr_model='small';device='cpu';prepare_models=$false;shortcut=$false}
function Test-Configuration([bool]$ExpectedSuccess) {
    $file=Join-Path $testRoot 'options.json'
    $configuration|ConvertTo-Json|Set-Content -LiteralPath $file -Encoding UTF8
    $savedPreference=$ErrorActionPreference
    $ErrorActionPreference='Continue'
    try {
        $output=& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'Install.ps1') -ConfigPath $file -ValidateOnly 2>&1 | Out-String
        $success=$LASTEXITCODE -eq 0
    } finally { $ErrorActionPreference=$savedPreference }
    if($success -ne $ExpectedSuccess){throw "Unexpected validation outcome: $output"}
    if(Test-Path $configuration.app_dir){throw 'ValidateOnly created the app directory'}
}
Test-Configuration $true
$configuration.model='qwen3:4b; calc'
Test-Configuration $false
$configuration.model='qwen3:4b'
$configuration.data_dir=Join-Path $configuration.app_dir 'resources\private'
Test-Configuration $false
$configuration.data_dir=Join-Path $testRoot 'data'
$configuration.install_mode='archive'
foreach($unsafe in @($false,$true)) {
    $archive=Join-Path $testRoot ('fixture-'+$unsafe+'.zip')
    $zip=[IO.Compression.ZipFile]::Open($archive,[IO.Compression.ZipArchiveMode]::Create)
    try {
        $entries=@{'AQA-Copilot/application-manifest.json'='{"schema":2,"multi_model":true}';'AQA-Copilot/aqa-copilot.exe'='test only';'AQA-Copilot/resources/backend/aqa-backend.exe'='test only'}
        if($unsafe){$entries['AQA-Copilot/../../escape.txt']='unsafe'}
        foreach($entry in $entries.GetEnumerator()){$writer=[IO.StreamWriter]::new($zip.CreateEntry($entry.Key).Open());try{$writer.Write($entry.Value)}finally{$writer.Dispose()}}
    } finally {$zip.Dispose()}
    $configuration.archive=$archive
    Test-Configuration (!$unsafe)
}
Write-Output 'PASS: source config, invalid model, protected data directory, valid ZIP, ZIP traversal rejection; no installation performed.'

. (Join-Path $PSScriptRoot 'Update.ps1')
$existing = Join-Path $testRoot 'existing'
$package = Join-Path $testRoot 'package'
$data = Join-Path $testRoot 'separate-data'
New-Item -ItemType Directory -Path "$existing\resources\backend","$package\resources\backend",$data -Force | Out-Null
Set-Content -LiteralPath "$existing\aqa-copilot.exe" -Value 'old app'
Set-Content -LiteralPath "$existing\resources\backend\aqa-backend.exe" -Value 'old backend'
Set-Content -LiteralPath "$package\aqa-copilot.exe" -Value 'new app'
Set-Content -LiteralPath "$package\resources\backend\aqa-backend.exe" -Value 'new backend'
Set-Content -LiteralPath "$package\application-manifest.json" -Value '{"schema":2,"multi_model":true}'
@{data_dir=$data} | ConvertTo-Json | Set-Content -LiteralPath "$existing\installation.json" -Encoding UTF8
Set-Content -LiteralPath "$data\settings.json" -Value '{"model":"custom:latest","unrelated":"keep"}'
Set-Content -LiteralPath "$data\copilot.db" -Value 'history fixture'
Set-Content -LiteralPath "$data\model.bin" -Value 'model fixture'
$preserved=@("$existing\installation.json","$data\settings.json","$data\copilot.db","$data\model.bin")
$before=@($preserved | ForEach-Object { (Get-FileHash -LiteralPath $_).Hash })
Publish-AppUpdate $package $existing
if((Get-Content "$existing\aqa-copilot.exe") -ne 'new app'){throw 'Application not updated'}
if((Get-Content "$existing\resources\backend\aqa-backend.exe") -ne 'new backend'){throw 'Backend not updated'}
$after=@($preserved | ForEach-Object { (Get-FileHash -LiteralPath $_).Hash })
if(Compare-Object $before $after){throw 'Update changed user data'}
$backupExe=Get-ChildItem -LiteralPath "$existing\.setup\backups" -Filter aqa-copilot.exe -Recurse -File | Select-Object -First 1
if(!$backupExe -or (Get-Content -LiteralPath $backupExe.FullName) -ne 'old app'){throw 'Previous application not backed up'}
Write-Output 'PASS: update replaces app/backend, backs up old program and preserves external settings/history/models byte-for-byte.'
Set-Content -LiteralPath "$package\aqa-copilot.exe" -Value 'next app'
$locked=[IO.File]::Open("$package\resources\backend\aqa-backend.exe",[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::None)
$rejected=$false
try { try { Publish-AppUpdate $package $existing } catch { $rejected=$true } } finally { $locked.Dispose() }
if(!$rejected -or (Get-Content "$existing\aqa-copilot.exe") -ne 'new app'){throw 'Failed update did not restore previous application'}
if(Compare-Object $before @($preserved | ForEach-Object { (Get-FileHash -LiteralPath $_).Hash })){throw 'Failed update changed user data'}
Write-Output 'PASS: failed file replacement rolls back the application and preserves data.'
