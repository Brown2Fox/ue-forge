param(
    [Parameter(Mandatory = $true)]
    [string]$SpecName,

    [Parameter(Mandatory = $true)]
    [string]$ArtifactName
)

$ErrorActionPreference = "Stop"

if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw "PowerShell 7 or newer is required."
}

$projectRoot = Split-Path -Parent $PSScriptRoot
$specPath = Join-Path $projectRoot "specs\$SpecName.spec"
$artifactPath = Join-Path $projectRoot "dist\$ArtifactName"

if (-not (Test-Path -LiteralPath $specPath -PathType Leaf)) {
    throw "Build spec was not found: $specPath"
}

if (Test-Path -LiteralPath $artifactPath -PathType Leaf) {
    try {
        $artifactStream = [System.IO.File]::Open(
            $artifactPath,
            [System.IO.FileMode]::Open,
            [System.IO.FileAccess]::ReadWrite,
            [System.IO.FileShare]::None
        )
        $artifactStream.Dispose()
    }
    catch {
        throw "Cannot replace the existing executable. Close '$ArtifactName' and try again."
    }
}

Set-Location -LiteralPath $projectRoot
Get-Command python -ErrorAction Stop | Out-Null

& python -m PyInstaller $specPath --noconfirm
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE."
}

if (-not (Test-Path -LiteralPath $artifactPath -PathType Leaf)) {
    throw "Build finished without producing the expected executable."
}

$artifact = Get-Item -LiteralPath $artifactPath
$sizeMb = [math]::Round($artifact.Length / 1MB, 1)
Write-Host ""
Write-Host "Build completed: $artifactPath ($sizeMb MB)" -ForegroundColor Green
