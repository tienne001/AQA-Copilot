[CmdletBinding(SupportsShouldProcess=$true)]
param()
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath($PSScriptRoot).TrimEnd('\')
$manifest=Get-Content -LiteralPath (Join-Path $root 'installation-files.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if (!$WhatIfPreference) {
    Add-Type -AssemblyName System.Windows.Forms
    $answer=[Windows.Forms.MessageBox]::Show('Remove AQA Copilot? Models, history and build cache will be kept. Close the app first.','AQA Copilot',[Windows.Forms.MessageBoxButtons]::YesNo)
    if($answer -ne [Windows.Forms.DialogResult]::Yes){return}
}
# Resolve every target before removing anything. No recursive folder deletion.
$targets=@()
foreach($relative in $manifest.files){
    $file=[IO.Path]::GetFullPath((Join-Path $root $relative))
    if(!$file.StartsWith($root+'\',[StringComparison]::OrdinalIgnoreCase) -or $relative -match '^(data|\.setup)[\\/]'){throw 'Invalid uninstall manifest'}
    $targets+=$file
}
foreach($file in $targets){if((Test-Path -LiteralPath $file -PathType Leaf) -and $PSCmdlet.ShouldProcess($file,'Remove installed file')){Remove-Item -LiteralPath $file -Force}}
if($manifest.shortcut -and (Test-Path -LiteralPath $manifest.shortcut)){
    $shell=New-Object -ComObject WScript.Shell
    if($shell.CreateShortcut($manifest.shortcut).TargetPath -eq (Join-Path $root 'aqa-copilot.exe')){
        if($PSCmdlet.ShouldProcess($manifest.shortcut,'Remove shortcut')){Remove-Item -LiteralPath $manifest.shortcut}
    }
}
if($manifest.registry -match '^HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\AQACopilot-[A-F0-9]{12}$'){
    if((Test-Path $manifest.registry) -and $PSCmdlet.ShouldProcess($manifest.registry,'Remove app registration')){Remove-Item -LiteralPath $manifest.registry}
}
Write-Output "App files removed. Data and build cache preserved in $root and the chosen data directory."
