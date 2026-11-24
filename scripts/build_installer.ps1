# Build XHS Studio portable app + Windows installer.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\build_installer.ps1
#
# Optional env vars:
#   PYTHON_EXE   Python executable with project deps + PyInstaller (default: python)
#   NODE_EXE     node.exe to bundle for PyExecJS (default: node from PATH)
#
# Outputs:
#   dist\XHSStudio\              portable app folder
#   dist\XHS-Studio-Setup.exe    per-user Windows installer

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Python = if ($env:PYTHON_EXE) { $env:PYTHON_EXE } else { "python" }
$NodeExe = if ($env:NODE_EXE) { $env:NODE_EXE } else { (Get-Command node -ErrorAction Stop).Source }

function Step($Text) {
    Write-Host ""
    Write-Host "==> $Text" -ForegroundColor Cyan
}

Step "Checking toolchain"
& $Python -c "import PyInstaller; print('PyInstaller', PyInstaller.__version__)"

if (-not (Test-Path "packaging\app.ico")) {
    Step "Generating app icon"
    & $Python -c @"
from PIL import Image
img = Image.open(r'frontend\public\logo.jpg').convert('RGBA').resize((256, 256))
img.save(r'packaging\app.ico', sizes=[(256,256),(128,128),(64,64),(48,48),(32,32),(16,16)])
"@
}

Step "Building frontend"
Push-Location frontend
try {
    if (-not (Test-Path "node_modules")) {
        npm ci --no-audit --no-fund
    }
    npm run build
} finally {
    Pop-Location
}

Step "Bundling Node.js runtime"
New-Item -ItemType Directory -Force -Path "packaging\node" | Out-Null
Copy-Item $NodeExe "packaging\node\node.exe" -Force

Step "Building application (PyInstaller onedir)"
& $Python -m PyInstaller --noconfirm "packaging\app.spec"

Step "Packing application payload"
& $Python -c @"
import os, zipfile
src = os.path.abspath(r'dist\XHSStudio')
dst = os.path.abspath(r'packaging\payload.zip')
with zipfile.ZipFile(dst, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
    for root, dirs, files in os.walk(src):
        for name in files:
            path = os.path.join(root, name)
            z.write(path, os.path.relpath(path, src))
print('payload MB:', round(os.path.getsize(dst) / 1048576, 1))
"@

Step "Building installer (single exe)"
& $Python -m PyInstaller --noconfirm --onefile --windowed `
    --name "XHS-Studio-Setup" `
    --icon "packaging\app.ico" `
    --add-data "packaging\payload.zip;." `
    "packaging\installer.py"

Step "Done"
$setup = Get-Item "dist\XHS-Studio-Setup.exe"
Write-Host ("Installer: {0} ({1:N1} MB)" -f $setup.FullName, ($setup.Length / 1MB)) -ForegroundColor Green
Write-Host ("Portable:  {0}" -f (Resolve-Path "dist\XHSStudio")) -ForegroundColor Green
