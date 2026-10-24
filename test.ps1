param([switch]$Smoke)
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'build.ps1')
$resultsPath = Join-Path $PSScriptRoot 'test-results'
New-Item -ItemType Directory -Path $resultsPath -Force | Out-Null
$appPath = Join-Path $PSScriptRoot 'bin\AltClipCtrl.exe'
$modes = @('--self-test')
if ($Smoke) { $modes += '--smoke-test' }
foreach ($mode in $modes) {
    $reportPath = Join-Path $resultsPath ($mode.TrimStart('-') + '.txt')
    $quotedReport = '"{0}"' -f $reportPath
    $process = Start-Process -FilePath $appPath -ArgumentList @($mode,$quotedReport) -WindowStyle Hidden -Wait -PassThru
    if (Test-Path -LiteralPath $reportPath) { Get-Content -LiteralPath $reportPath }
    if ($process.ExitCode -ne 0) { throw "Diagnostic failed: $mode" }
}
