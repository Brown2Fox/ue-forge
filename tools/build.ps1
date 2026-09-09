$ErrorActionPreference = "Stop"

if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw "PowerShell 7 or newer is required."
}

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot

Get-Command python -ErrorAction Stop | Out-Null

& python -m PyInstaller "specs\ue_forge.spec" --noconfirm
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

$artifactPath = Join-Path $projectRoot "dist\UE Forge.exe"
if (-not (Test-Path -LiteralPath $artifactPath -PathType Leaf)) {
    throw "Build finished without producing the expected executable."
}

$artifact = Get-Item -LiteralPath $artifactPath
$sizeMb = [math]::Round($artifact.Length / 1MB, 1)
Write-Host ""
Write-Host "Build completed: $artifactPath ($sizeMb MB)" -ForegroundColor Green
