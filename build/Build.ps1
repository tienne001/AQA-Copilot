[CmdletBinding()]
param(
    [string]$BuildRoot = '',
    [string]$Python = 'python',
    [string]$AppDir = ''
)
$ErrorActionPreference = 'Stop'
$sourceRoot = Split-Path -Parent $PSScriptRoot
if (!$BuildRoot) { $BuildRoot = Join-Path $sourceRoot '.build' }
if (!$AppDir) { $AppDir = Join-Path $sourceRoot 'release\AQA-Copilot' }
$BuildRoot = [IO.Path]::GetFullPath($BuildRoot)
$AppDir = [IO.Path]::GetFullPath($AppDir)
& $Python -c 'import sys; sys.exit(0 if sys.version_info[:2] == (3,12) else 1)'
if ($LASTEXITCODE) { throw 'Python 3.12 is required. Use Setup.ps1 -Mode Build.' }
New-Item -ItemType Directory -Path $BuildRoot -Force | Out-Null
$venv = Join-Path $BuildRoot 'python-env'
$buildPython = Join-Path $venv 'Scripts\python.exe'
if (!(Test-Path $buildPython)) { & $Python -m venv $venv; if ($LASTEXITCODE) { throw 'venv failed' } }
& $buildPython -m pip install --disable-pip-version-check -r (Join-Path $sourceRoot 'backend\requirements-lock.txt')
if ($LASTEXITCODE) { throw 'Python dependencies failed' }
$env:CARGO_TARGET_DIR = Join-Path $BuildRoot 'cargo-target'
$env:PYTHONPATH = Join-Path $sourceRoot 'backend'
$env:AQA_RUN_ASR_ACCURACY = '0'
& $buildPython -m pytest (Join-Path $sourceRoot 'backend\tests') -q
if ($LASTEXITCODE) { throw 'Backend tests failed' }
& $buildPython -m unittest discover -s (Join-Path $sourceRoot 'build\tests') -v
if ($LASTEXITCODE) { throw 'Setup tests failed' }
& $buildPython -m PyInstaller (Join-Path $PSScriptRoot 'backend.spec') --distpath (Join-Path $BuildRoot 'backend-dist') --workpath (Join-Path $BuildRoot 'pyinstaller-work') --noconfirm
if ($LASTEXITCODE) { throw 'Backend packaging failed' }
Push-Location (Join-Path $sourceRoot 'frontend')
try {
    & npm.cmd ci --no-audit --no-fund
    if ($LASTEXITCODE) { throw 'npm ci failed' }
    & npm.cmd test
    if ($LASTEXITCODE) { throw 'Frontend tests failed' }
    & npm.cmd run tauri -- build --no-bundle --config src-tauri/tauri.portable.json
    if ($LASTEXITCODE) { throw 'Tauri build failed' }
} finally { Pop-Location }
$backend = Join-Path $BuildRoot 'backend-dist\aqa-backend'
$exe = Join-Path $BuildRoot 'cargo-target\release\aqa-copilot.exe'
$resources = Join-Path $AppDir 'resources\backend'
New-Item -ItemType Directory -Path $resources -Force | Out-Null
Copy-Item -LiteralPath $exe -Destination (Join-Path $AppDir 'aqa-copilot.exe') -Force
Get-ChildItem -LiteralPath $backend | Copy-Item -Destination $resources -Recurse -Force
Copy-Item -LiteralPath (Join-Path $sourceRoot 'README.md') -Destination $AppDir -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'app-manifest.json') -Destination (Join-Path $AppDir 'application-manifest.json') -Force
$archive = Join-Path $sourceRoot 'release\AQA-Copilot-1.0.0-Windows-x64.zip'
& $buildPython (Join-Path $PSScriptRoot 'package_portable.py') --exe $exe --backend $backend --source $sourceRoot --output $archive
if ($LASTEXITCODE) { throw 'Portable archive validation failed' }
Write-Output "Built: $AppDir`nArchive (without models): $archive"
