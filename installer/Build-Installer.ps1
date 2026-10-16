[CmdletBinding()]
param([string]$OutputPath='', [string]$Python='python')
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
if(!$OutputPath){$OutputPath=Join-Path $root 'release\Setup.exe'}
$OutputPath=[IO.Path]::GetFullPath($OutputPath)
$compiler=Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if(!(Test-Path $compiler)){throw '.NET Framework C# compiler is required on the build machine.'}
$staging=Join-Path $root '.build\installer'
New-Item -ItemType Directory -Path $staging,(Split-Path -Parent $OutputPath) -Force | Out-Null
$payload=Join-Path $staging 'source.zip'
& $Python (Join-Path $root 'build\export_sources.py') --output $payload
if($LASTEXITCODE){throw 'Source payload export failed'}
$sources=@(Get-ChildItem -LiteralPath $PSScriptRoot -Filter '*.cs' | ForEach-Object FullName)
$arguments=@('/nologo','/target:winexe','/platform:x64','/optimize+',('/out:'+$OutputPath),('/win32manifest:'+(Join-Path $PSScriptRoot 'app.manifest')),('/win32icon:'+(Join-Path $root 'frontend\src-tauri\icons\icon.ico')),('/resource:'+$payload+',source.zip'),'/r:System.dll','/r:System.Core.dll','/r:System.Drawing.dll','/r:System.Windows.Forms.dll','/r:System.Web.Extensions.dll','/r:System.IO.Compression.dll','/r:System.IO.Compression.FileSystem.dll')+$sources
& $compiler @arguments
if($LASTEXITCODE){throw 'Installer compilation failed'}
$hash=(Get-FileHash -LiteralPath $OutputPath -Algorithm SHA256).Hash.ToLowerInvariant()
[IO.File]::WriteAllText(($OutputPath+'.sha256'),$hash+'  '+[IO.Path]::GetFileName($OutputPath)+"`n",[Text.UTF8Encoding]::new($false))
Write-Output "Installer built: $OutputPath"
Write-Output 'No application, AI runtime or model was installed.'
