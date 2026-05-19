$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$WebDir = Join-Path $Root "open_agent\app\web"
$DesktopDir = Join-Path $Root "desktop"
$TauriDir = Join-Path $DesktopDir "src-tauri"
$BackendEntry = Join-Path $DesktopDir "backend\open_agent_backend.py"
$BinariesDir = Join-Path $TauriDir "binaries"
$PyinstallerWorkDir = Join-Path $Root "build\pyinstaller"
$SidecarName = "open-agent-backend-x86_64-pc-windows-msvc"
$SidecarExe = Join-Path $BinariesDir "$SidecarName.exe"

New-Item -ItemType Directory -Force -Path $BinariesDir | Out-Null
New-Item -ItemType Directory -Force -Path $PyinstallerWorkDir | Out-Null

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    $Python = "python"
}

Write-Host "[1/4] Building Vue Web UI..."
npm --prefix $WebDir run build

Write-Host "[2/4] Building Python backend sidecar..."
& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --name $SidecarName `
    --distpath $BinariesDir `
    --workpath $PyinstallerWorkDir `
    --specpath $PyinstallerWorkDir `
    --add-data "$Root\open_agent\app\static;open_agent\app\static" `
    --add-data "$Root\open_agent\config;open_agent\config" `
    --add-data "$Root\open_agent\skills;open_agent\skills" `
    --hidden-import "uvicorn.logging" `
    --hidden-import "uvicorn.loops" `
    --hidden-import "uvicorn.loops.auto" `
    --hidden-import "uvicorn.protocols" `
    --hidden-import "uvicorn.protocols.http" `
    --hidden-import "uvicorn.protocols.http.auto" `
    --hidden-import "uvicorn.protocols.websockets" `
    --hidden-import "uvicorn.protocols.websockets.auto" `
    --hidden-import "uvicorn.lifespan" `
    --hidden-import "uvicorn.lifespan.on" `
    $BackendEntry

if (-not (Test-Path $SidecarExe)) {
    throw "Sidecar build failed: $SidecarExe was not created"
}

Write-Host "[3/4] Building Tauri desktop app..."
npm --prefix $DesktopDir run tauri:build

Write-Host "[4/4] Done."
Write-Host "Sidecar: $SidecarExe"
Write-Host "App exe: $TauriDir\target\release\open-agent-seal-desktop.exe"
Write-Host "NSIS: $TauriDir\target\release\bundle\nsis\OpenAgentSeal_0.1.0_x64-setup.exe"
Write-Host "MSI: $TauriDir\target\release\bundle\msi\OpenAgentSeal_0.1.0_x64_en-US.msi"
