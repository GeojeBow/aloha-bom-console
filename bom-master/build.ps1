# Builds BOM_Master.exe and publishes it to .\release (the auto-update source).
# Usage:  powershell -ExecutionPolicy Bypass -File build.ps1 [-Notes "what changed"]
param([string]$Notes = "")

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$src = Join-Path $root "src"
$work = Join-Path $env:LOCALAPPDATA "BOMMaster\build"     # keep build junk out of OneDrive
$release = Join-Path $root "release"
New-Item -ItemType Directory -Force $work, $release | Out-Null

$version = (Select-String -Path (Join-Path $src "bom_master\__init__.py") -Pattern 'VERSION = "(.+)"').Matches[0].Groups[1].Value
Write-Host "Building BOM Master v$version"

python (Join-Path $src "make_icon.py") (Join-Path $work "app.ico")

Push-Location $src
try {
    python -m PyInstaller --noconfirm --clean --onefile --windowed --name BOM_Master `
        --icon (Join-Path $work "app.ico") `
        --distpath (Join-Path $work "dist") --workpath (Join-Path $work "tmp") --specpath $work `
        --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtWebEngineWidgets `
        --exclude-module PySide6.QtQml --exclude-module PySide6.QtQuick --exclude-module PySide6.Qt3DCore `
        --exclude-module PySide6.QtMultimedia --exclude-module PySide6.QtPdf --exclude-module PySide6.QtCharts `
        --exclude-module tkinter --exclude-module customtkinter --exclude-module pandas --exclude-module numpy `
        main.py
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
} finally { Pop-Location }

Copy-Item (Join-Path $work "dist\BOM_Master.exe") (Join-Path $release "BOM_Master.exe") -Force
@{ version = $version; file = "BOM_Master.exe"; notes = $Notes; built = (Get-Date -Format "yyyy-MM-dd HH:mm") } |
    ConvertTo-Json | Set-Content -Encoding utf8 (Join-Path $release "version.json")
Write-Host "Published v$version to $release"
