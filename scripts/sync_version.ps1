$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$VersionFile = Join-Path $Root "version.json"

if (-not (Test-Path $VersionFile)) {
    throw "Version config not found: $VersionFile"
}

$AppVersion = (Get-Content -Raw -Encoding UTF8 -Path $VersionFile | ConvertFrom-Json).version
if (-not $AppVersion -or $AppVersion -notmatch '^\d+\.\d+\.\d+([-.][0-9A-Za-z.-]+)?$') {
    throw "Invalid version in version.json: $AppVersion"
}

function Write-Utf8NoBom {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Content
    )

    $Encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Content, $Encoding)
}

function Has-Utf8Bom {
    param([Parameter(Mandatory = $true)][string]$Path)

    $Stream = [System.IO.File]::OpenRead($Path)
    try {
        if ($Stream.Length -lt 3) {
            return $false
        }
        $Bytes = New-Object byte[] 3
        [void]$Stream.Read($Bytes, 0, 3)
        return $Bytes[0] -eq 0xEF -and $Bytes[1] -eq 0xBB -and $Bytes[2] -eq 0xBF
    }
    finally {
        $Stream.Dispose()
    }
}

function Update-TextFile {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Pattern,
        [Parameter(Mandatory = $true)][string]$Replacement
    )

    $FullPath = Join-Path $Root $Path
    if (-not (Test-Path $FullPath)) {
        throw "File not found: $FullPath"
    }

    $Content = Get-Content -Raw -Encoding UTF8 -Path $FullPath
    $Updated = [regex]::Replace($Content, $Pattern, $Replacement)
    if ($Updated -ne $Content -or (Has-Utf8Bom -Path $FullPath)) {
        Write-Utf8NoBom -Path $FullPath -Content $Updated
    }
}

function Update-PackageJson {
    param([Parameter(Mandatory = $true)][string]$Path)

    $FullPath = Join-Path $Root $Path
    if (-not (Test-Path $FullPath)) {
        throw "File not found: $FullPath"
    }

    $Content = Get-Content -Raw -Encoding UTF8 -Path $FullPath
    $VersionRegex = [regex]'("version"\s*:\s*")[^"]+(")'
    $Updated = $VersionRegex.Replace($Content, '${1}' + $AppVersion + '${2}', 1)
    if ($Updated -ne $Content -or (Has-Utf8Bom -Path $FullPath)) {
        Write-Utf8NoBom -Path $FullPath -Content $Updated
    }
}

function Update-PackageLock {
    param([Parameter(Mandatory = $true)][string]$Path)

    $FullPath = Join-Path $Root $Path
    if (-not (Test-Path $FullPath)) {
        throw "File not found: $FullPath"
    }

    $Content = Get-Content -Raw -Encoding UTF8 -Path $FullPath
    $VersionRegex = [regex]'("version"\s*:\s*")[^"]+(")'
    $Updated = $VersionRegex.Replace($Content, '${1}' + $AppVersion + '${2}', 2)
    if ($Updated -ne $Content -or (Has-Utf8Bom -Path $FullPath)) {
        Write-Utf8NoBom -Path $FullPath -Content $Updated
    }
}

function Update-TauriConfig {
    $Path = Join-Path $Root "desktop\src-tauri\tauri.conf.json"
    $Content = Get-Content -Raw -Encoding UTF8 -Path $Path
    $VersionRegex = [regex]'("version"\s*:\s*")[^"]+(")'
    $Updated = $VersionRegex.Replace($Content, '${1}' + $AppVersion + '${2}', 1)
    if ($Updated -ne $Content -or (Has-Utf8Bom -Path $Path)) {
        Write-Utf8NoBom -Path $Path -Content $Updated
    }
}

Update-TextFile "pyproject.toml" '(?m)^(version\s*=\s*)".*"' "`${1}`"$AppVersion`""
Update-TextFile "open_agent\__init__.py" '(?m)^(__version__\s*=\s*)".*"' "`${1}`"$AppVersion`""
Update-TextFile "open_agent\cli.py" 'version="open-agent [^"]+"' "version=`"open-agent $AppVersion`""
Update-TextFile "open_agent\acp\__init__.py" 'version="[^"]+"\)' "version=`"$AppVersion`")"
Update-TextFile "open_agent\app\_app.py" 'version="[^"]+"' "version=`"$AppVersion`""
Update-TextFile "desktop\src-tauri\Cargo.toml" '(?m)^(version\s*=\s*)".*"' "`${1}`"$AppVersion`""

Update-PackageJson "desktop\package.json"
Update-PackageJson "open_agent\app\web\package.json"
Update-PackageLock "desktop\package-lock.json"
Update-PackageLock "open_agent\app\web\package-lock.json"
Update-TauriConfig

Write-Host "Synced OpenAgentSeal version: $AppVersion"
