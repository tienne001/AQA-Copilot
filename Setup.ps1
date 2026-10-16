[CmdletBinding()]
param(
    [ValidateSet('Check','Build','Models','All')][string]$Mode = 'Check',
    [string]$BuildRoot = '',
    [string]$AppDir = '',
    [ValidateSet('cuda','cpu')][string]$AsrDevice = 'cuda',
    [string]$Model = 'qwen3:8b',
    [ValidateSet('tiny','base','small','medium','large-v3')][string]$AsrModel = 'medium',
    [string]$DataDir = '',
    [switch]$UpdateModelSettings
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if (!$BuildRoot) { $BuildRoot = Join-Path $PSScriptRoot '.build' }
if (!$AppDir) { $AppDir = Join-Path $PSScriptRoot 'release\AQA-Copilot' }
if (![Environment]::Is64BitProcess -or $env:PROCESSOR_ARCHITECTURE -ne 'AMD64') { throw 'Run 64-bit PowerShell on Windows x64.' }
$BuildRoot = [IO.Path]::GetFullPath($BuildRoot)
$AppDir = [IO.Path]::GetFullPath($AppDir)
if (!$DataDir) { $DataDir = Join-Path $AppDir 'data' }
$DataDir = [IO.Path]::GetFullPath($DataDir)
if ($Model -notmatch '^[a-zA-Z0-9][a-zA-Z0-9_.-]*(/[a-zA-Z0-9][a-zA-Z0-9_.-]*)?:[a-zA-Z0-9][a-zA-Z0-9_.-]*$' -or $Model -match 'cloud' -or $Model.Length -gt 160) { throw 'Use a local Ollama model tag, for example qwen3:4b.' }
function Refresh-Path {
    $env:PATH = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User') + ';' + $env:PATH
}
function Install-Package([string]$Id, [string]$Override = '') {
    if (!(Get-Command winget.exe -ErrorAction SilentlyContinue)) { throw 'Install Microsoft App Installer (winget), then run Setup again.' }
    $arguments = @('install','--exact','--id',$Id,'--source','winget','--accept-source-agreements','--accept-package-agreements')
    if ($Override) { $arguments += @('--override',$Override) }
    & winget.exe @arguments
    if ($LASTEXITCODE -ne 0) { throw "winget failed for $Id (exit $LASTEXITCODE). Complete installation/reboot if requested, then rerun." }
    Refresh-Path
}
function Find-Python {
    $candidates = @("$env:LOCALAPPDATA\Programs\Python\Python312\python.exe", 'C:\Python312\python.exe')
    if (Get-Command py.exe -ErrorAction SilentlyContinue) {
        try {
            $found = & py.exe -3.12 -c 'import sys; print(sys.executable)' 2>$null
            if ($LASTEXITCODE -eq 0) { $candidates = @($found) + $candidates }
        } catch { }
    }
    foreach ($candidate in $candidates) { if (Test-Path -LiteralPath $candidate) { return $candidate } }
    return $null
}
function Find-Msvc {
    $vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
    if (Test-Path -LiteralPath $vswhere) { return (& $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath) }
    return $null
}
if ($Mode -eq 'Check') {
    [PSCustomObject]@{
        Python312 = (Find-Python)
        Node = [bool](Get-Command node.exe -ErrorAction SilentlyContinue)
        CppBuildTools = (Find-Msvc)
        Winget = [bool](Get-Command winget.exe -ErrorAction SilentlyContinue)
        AppDir = $AppDir
        PortableOllama = (Test-Path (Join-Path $AppDir 'data\tools\ollama\ollama.exe'))
        Whisper = (Test-Path (Join-Path $AppDir 'data\models\whisper-medium\model.bin'))
    } | Format-List
    Write-Output 'Check only: nothing installed, downloaded or started.'
    return
}
New-Item -ItemType Directory -Path $BuildRoot -Force | Out-Null
$python = Find-Python
if (!$python) { Install-Package 'Python.Python.3.12'; $python = Find-Python }
if (!$python) { throw 'Python 3.12 was not found after installation. Open a new terminal and retry.' }
if ($Mode -in @('Build','All')) {
    $nodeOk = $false
    if (Get-Command node.exe -ErrorAction SilentlyContinue) {
        $nodeVersion = [version]((& node.exe --version).Trim().TrimStart('v'))
        $nodeOk = ($nodeVersion.Major -eq 20 -and $nodeVersion.Minor -ge 19) -or ($nodeVersion.Major -eq 22 -and $nodeVersion.Minor -ge 12) -or ($nodeVersion.Major -ge 24)
    }
    if (!$nodeOk) { Install-Package 'OpenJS.NodeJS.LTS' }
    if (!(Find-Msvc)) { Install-Package 'Microsoft.VisualStudio.2022.BuildTools' '--passive --wait --norestart --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended' }
    if (!(Find-Msvc)) { throw 'C++ build tools are missing. Complete the Visual Studio installation and rerun.' }
    if (!(Test-Path "${env:ProgramFiles(x86)}\Microsoft\EdgeWebView\Application") -and !(Test-Path "$env:LOCALAPPDATA\Microsoft\EdgeWebView\Application")) {
        Install-Package 'Microsoft.EdgeWebView2Runtime'
    }
    $env:RUSTUP_HOME = Join-Path $BuildRoot 'rustup'
    $env:CARGO_HOME = Join-Path $BuildRoot 'cargo'
    $env:PATH = (Join-Path $env:CARGO_HOME 'bin') + ';' + $env:PATH
    if (!(Test-Path (Join-Path $env:CARGO_HOME 'bin\rustup.exe'))) {
        $installer = Join-Path $BuildRoot 'rustup-init.exe'
        Invoke-WebRequest 'https://win.rustup.rs/x86_64' -OutFile $installer -UseBasicParsing
        & $installer -y --no-modify-path --profile minimal --default-toolchain 1.99.0
        if ($LASTEXITCODE) { throw 'Rust installation failed.' }
    } else {
        & rustup.exe toolchain install 1.99.0 --profile minimal
        if ($LASTEXITCODE) { throw 'Rust toolchain installation failed.' }
    }
    $env:RUSTUP_TOOLCHAIN = '1.99.0'
    & (Join-Path $PSScriptRoot 'build\Build.ps1') -BuildRoot $BuildRoot -Python $python -AppDir $AppDir
}
if ($Mode -in @('Models','All')) {
    if (!(Test-Path (Join-Path $AppDir 'aqa-copilot.exe'))) { throw 'Build the application first, or pass -AppDir pointing to an extracted portable build.' }
    $modelEnv = Join-Path $BuildRoot 'model-env'
    $modelPython = Join-Path $modelEnv 'Scripts\python.exe'
    if (!(Test-Path $modelPython)) { & $python -m venv $modelEnv; if ($LASTEXITCODE) { throw 'Model setup venv failed.' } }
    & $modelPython -m pip install --disable-pip-version-check 'huggingface_hub==2.2.0'
    if ($LASTEXITCODE) { throw 'Model downloader installation failed.' }
    $modelArguments = @((Join-Path $PSScriptRoot 'build\setup_models.py'), '--data-dir', $DataDir, '--asr-device', $AsrDevice, '--model', $Model, '--asr-model', $AsrModel)
    if ($UpdateModelSettings) { $modelArguments += '--update-settings' }
    & $modelPython @modelArguments
    if ($LASTEXITCODE) { throw 'Model setup failed. Rerun to resume downloads.' }
}
@{ data_dir = $DataDir } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $AppDir 'installation.json') -Encoding UTF8
Write-Output "Completed: $Mode. Application: $AppDir\aqa-copilot.exe"
Write-Output 'Application was not started. Model data is local and is not included in Git or the distributable ZIP.'
