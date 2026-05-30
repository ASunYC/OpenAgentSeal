param(
    [string]$Configuration = "Release",
    [string]$Runtime = "win-x64",
    [switch]$FrameworkDependent
)

$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Project = Join-Path $Root "tools\uninstaller\OpenAgentSeal.Uninstaller.csproj"
$OutputDir = Join-Path $Root "dist\uninstaller"
$FinalDir = Join-Path $Root "dist"
$FinalExe = Join-Path $FinalDir "OpenAgentSealUninstaller.exe"

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
New-Item -ItemType Directory -Force -Path $FinalDir | Out-Null

$publishArgs = @(
    "publish",
    $Project,
    "-c", $Configuration,
    "-r", $Runtime,
    "-o", $OutputDir,
    "/p:DebugType=None",
    "/p:DebugSymbols=false"
)

if ($FrameworkDependent) {
    $publishArgs += "--self-contained"
    $publishArgs += "false"
} else {
    $publishArgs += "--self-contained"
    $publishArgs += "true"
    $publishArgs += "/p:PublishSingleFile=true"
    $publishArgs += "/p:IncludeNativeLibrariesForSelfExtract=true"
    $publishArgs += "/p:EnableCompressionInSingleFile=true"
}

dotnet @publishArgs

$BuiltExe = Join-Path $OutputDir "OpenAgentSealUninstaller.exe"
if (-not (Test-Path $BuiltExe)) {
    throw "Build succeeded but $BuiltExe was not created."
}

Copy-Item -LiteralPath $BuiltExe -Destination $FinalExe -Force
Remove-Item -LiteralPath $OutputDir -Recurse -Force
Get-Item -LiteralPath $FinalExe
