$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$WebDir = Join-Path $Root "open_agent\app\web"
$DesktopDir = Join-Path $Root "desktop"
$TauriDir = Join-Path $DesktopDir "src-tauri"
$BackendEntry = Join-Path $DesktopDir "backend\open_agent_backend.py"
$BinariesDir = Join-Path $TauriDir "binaries"
$PyinstallerWorkDir = Join-Path $Root "build\pyinstaller"
$ReleaseDir = Join-Path $Root "dist\OpenAgentSeal-win-x64"
$InstallersDir = Join-Path $ReleaseDir "installers"
$PortableDir = Join-Path $ReleaseDir "portable"
$PortableZip = Join-Path $ReleaseDir "OpenAgentSeal-portable-win-x64.zip"
$SidecarName = "open-agent-backend-x86_64-pc-windows-msvc"
$SidecarExe = Join-Path $BinariesDir "$SidecarName.exe"
$AppExe = Join-Path $TauriDir "target\release\open-agent-seal-desktop.exe"
$NsisInstaller = Join-Path $TauriDir "target\release\bundle\nsis\OpenAgentSeal_0.1.0_x64-setup.exe"
$MsiInstaller = Join-Path $TauriDir "target\release\bundle\msi\OpenAgentSeal_0.1.0_x64_en-US.msi"

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
    --noconsole `
    --name $SidecarName `
    --paths $Root `
    --distpath $BinariesDir `
    --workpath $PyinstallerWorkDir `
    --specpath $PyinstallerWorkDir `
    --add-data "$Root\open_agent\app\static;open_agent\app\static" `
    --add-data "$Root\open_agent\config;open_agent\config" `
    --add-data "$Root\open_agent\skills;open_agent\skills" `
    --hidden-import "open_agent.cli" `
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

foreach ($Artifact in @($AppExe, $NsisInstaller, $MsiInstaller)) {
    if (-not (Test-Path $Artifact)) {
        throw "Desktop build failed: $Artifact was not created"
    }
}

Write-Host "[4/4] Collecting release artifacts..."
if (Test-Path $ReleaseDir) {
    Remove-Item -LiteralPath $ReleaseDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $InstallersDir | Out-Null
New-Item -ItemType Directory -Force -Path $PortableDir | Out-Null

Copy-Item -LiteralPath $NsisInstaller -Destination $InstallersDir -Force
Copy-Item -LiteralPath $MsiInstaller -Destination $InstallersDir -Force
Copy-Item -LiteralPath $AppExe -Destination (Join-Path $PortableDir "OpenAgentSeal.exe") -Force
Copy-Item -LiteralPath $SidecarExe -Destination (Join-Path $PortableDir "$SidecarName.exe") -Force
Compress-Archive -Path (Join-Path $PortableDir "*") -DestinationPath $PortableZip -Force

Write-Host "Done."
Write-Host "Sidecar: $SidecarExe"
Write-Host "Release dir: $ReleaseDir"
Write-Host "Portable app: $PortableDir\OpenAgentSeal.exe"
Write-Host "Portable zip: $PortableZip"
Write-Host "NSIS: $InstallersDir\OpenAgentSeal_0.1.0_x64-setup.exe"
Write-Host "MSI: $InstallersDir\OpenAgentSeal_0.1.0_x64_en-US.msi"
