$ErrorActionPreference = "Stop"

# Run with:
# powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1

$root = Split-Path -Parent $MyInvocation.MyCommand.Path | Split-Path -Parent
Set-Location $root

$venv = ".venv-build"
$python = Join-Path $venv "Scripts\\python.exe"
$pyinstaller = Join-Path $venv "Scripts\\pyinstaller.exe"

if (-not (Test-Path $python)) {
  python -m venv $venv
}

& $python -m pip install --upgrade pip
& $python -m pip install -r backend/requirements.txt pyinstaller

if (Test-Path "dist") { Remove-Item "dist" -Recurse -Force }
if (Test-Path "build") { Remove-Item "build" -Recurse -Force }

& $pyinstaller `
  --noconfirm `
  --clean `
  --onedir `
  --name OpenKeeper `
  tools/packaging/launch_win.py `
  --collect-all fastapi `
  --collect-all starlette `
  --collect-all pydantic `
  --collect-all pydantic_core `
  --collect-all anyio `
  --collect-all uvicorn `
  --collect-all websockets `
  --collect-all httpx `
  --collect-all motor `
  --collect-all pymongo `
  --collect-all yaml `
  --collect-all idna `
  --collect-all sniffio `
  --add-data "backend/app;backend/app" `
  --add-data "backend/modules;backend/modules" `
  --add-data "backend/data;backend/data" `
  --add-data "backend/config.yaml;backend/config.yaml" `
  --add-data "backend/static_app.html;backend/static_app.html" `
  --add-data "backend/static_host.html;backend/static_host.html" `
  --add-data "backend/static_placeholder.html;backend/static_placeholder.html"

Write-Host "Build complete: dist\\OpenKeeper\\OpenKeeper.exe"
