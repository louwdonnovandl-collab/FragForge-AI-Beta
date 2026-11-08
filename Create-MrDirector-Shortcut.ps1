$ErrorActionPreference = 'Stop'
$exe = Join-Path $PSScriptRoot 'FragForge.exe'
if (!(Test-Path $exe)) { throw 'Place this script beside FragForge.exe in the extracted Windows build.' }
$shortcut = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Mr Director.lnk'
$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut($shortcut)
$link.TargetPath = $exe
$link.WorkingDirectory = $PSScriptRoot
$icon = Join-Path $PSScriptRoot 'mr_director.ico'
if (Test-Path $icon) { $link.IconLocation = $icon }
$link.Description = 'Launch FragForge AI - Mr Director'
$link.Save()
Write-Host "Created $shortcut"
