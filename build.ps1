# Builds the app into .\dist:
#   dist\PhotoSwipe\PhotoSwipe.exe   folder version (fast start) - always built
#   dist\PhotoSwipe.exe              single file to send to others (slower start) - with -OneFile
# The trimmed VLC in vendor\vlc (made by tools\prepare_vlc.py) is bundled for video playback.
# Usage (from this folder):  powershell -ExecutionPolicy Bypass -File build.ps1 [-OneFile]
param([switch]$OneFile)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Test-Path .venv)) {
    python -m venv .venv
    .\.venv\Scripts\python -m pip install -r requirements.txt pyinstaller
}
if (-not (Test-Path vendor\vlc\libvlc.dll)) {
    throw "vendor\vlc is missing: run tools\prepare_vlc.py <vlc-3.0.24-win64.zip> first"
}
if (-not (Test-Path assets\photoswipe.ico)) {
    .\.venv\Scripts\python tools\make_icon.py
}
$common = @("--noconfirm", "--windowed", "--name", "PhotoSwipe", "--icon", "assets\photoswipe.ico",
            "--exclude-module", "numpy", "--exclude-module", "unittest", "--exclude-module", "pydoc_data",
            "--add-data", "vendor\vlc;vlc", "--add-data", "assets;assets")
.\.venv\Scripts\pyinstaller @common --onedir --distpath dist main.py
# VLC only trusts its plugin index (plugins.dat) if the plugin timestamps are unchanged.
.\.venv\Scripts\python tools\fix_vlc_times.py dist\PhotoSwipe\_internal\vlc
if ($OneFile) {
    .\.venv\Scripts\python tools\make_splash.py build\splash.png
    .\.venv\Scripts\pyinstaller @common --onefile --splash build\splash.png --distpath dist main.py
}
Write-Host "Done."
