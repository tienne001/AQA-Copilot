$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$env:RUSTUP_HOME = Join-Path $projectRoot '.build\rustup'
$env:CARGO_HOME = Join-Path $projectRoot '.build\cargo'
if (!(Test-Path (Join-Path $env:CARGO_HOME 'bin\cargo.exe'))) {
    # Compatibility with an existing isolated toolchain from earlier builds.
    $env:RUSTUP_HOME = Join-Path $projectRoot '.rustup'
    $env:CARGO_HOME = Join-Path $projectRoot '.cargo-cache'
}
if (!(Test-Path (Join-Path $env:CARGO_HOME 'bin\cargo.exe'))) { throw 'Run Setup.ps1 -Mode Build to prepare the build toolchain.' }
$env:PATH = (Join-Path $env:CARGO_HOME 'bin') + ';' + $env:PATH
Push-Location (Join-Path $projectRoot 'frontend')
try {
    & npm.cmd run tauri -- build --no-bundle --config src-tauri/tauri.portable.json
    if ($LASTEXITCODE) { throw 'Window build failed' }
    Write-Output (Join-Path $projectRoot 'frontend/src-tauri/target/release/aqa-copilot.exe')
    # Place this executable beside the existing resources directory to run it.
} finally { Pop-Location }
