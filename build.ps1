# Alt Clip Ctrl: build with Microsoft's existing .NET Framework compiler.
$ErrorActionPreference = 'Stop'
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path -LiteralPath $compiler)) { $compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319\csc.exe' }
if (-not (Test-Path -LiteralPath $compiler)) { throw '.NET Framework 4.x compiler not found.' }
$binPath = Join-Path $PSScriptRoot 'bin'
New-Item -ItemType Directory -Path $binPath -Force | Out-Null
$sourceFiles = Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot 'src') -Filter '*.cs' | Sort-Object Name | ForEach-Object { $_.FullName }
$iconPath = Join-Path $PSScriptRoot 'assets\AltClipCtrl.ico'
$appPath = Join-Path $binPath 'AltClipCtrl.exe'
& $compiler /nologo /target:winexe /platform:anycpu /optimize+ /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /reference:System.Xml.dll "/win32icon:$iconPath" "/out:$appPath" $sourceFiles
if ($LASTEXITCODE -ne 0) { throw 'Build failed.' }
Write-Output "Built $appPath"
