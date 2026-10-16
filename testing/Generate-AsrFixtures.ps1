[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$OutputDir,
      [string]$CasesPath = (Join-Path $PSScriptRoot 'asr_cases.json'))
$ErrorActionPreference = 'Stop'
$OutputDir = [IO.Path]::GetFullPath($OutputDir)
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
$cases = Get-Content -LiteralPath $CasesPath -Raw -Encoding UTF8 | ConvertFrom-Json
$voice = New-Object -ComObject SAPI.SpVoice
$voices = $voice.GetVoices()
$russian = $null
for ($i=0; $i -lt $voices.Count; $i++) {
    if ($voices.Item($i).GetDescription() -match 'Irina.*Russian') { $russian = $voices.Item($i); break }
}
if ($null -eq $russian) { throw 'Microsoft Irina Russian voice is required for this synthetic benchmark.' }
$voice.Voice = $russian
$voice.Rate = 0
foreach ($case in $cases) {
    $stream = New-Object -ComObject SAPI.SpFileStream
    try {
        $stream.Format.Type = 22 # SAFT22kHz16BitMono
        $stream.Open((Join-Path $OutputDir ($case.id + '.wav')), 3, $false)
        $voice.AudioOutputStream = $stream
        $null = $voice.Speak($case.text, 0)
    } finally { $stream.Close() }
}
Copy-Item -LiteralPath $CasesPath -Destination (Join-Path $OutputDir 'asr_cases.json')
Write-Output ('Generated ' + $cases.Count + ' synthetic Russian speech clips in ' + $OutputDir)
