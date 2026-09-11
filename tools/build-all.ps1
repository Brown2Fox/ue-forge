$ErrorActionPreference = "Stop"

$buildScripts = @(
    "build-forge.ps1",
    "build-plugin-builder.ps1",
    "build-uproject-launcher.ps1",
    "build-renamer.ps1",
    "build-include-optimizer.ps1",
    "build-commandlet-runner.ps1"
)

foreach ($buildScript in $buildScripts) {
    Write-Host ""
    Write-Host "Building with $buildScript..." -ForegroundColor Cyan
    & (Join-Path $PSScriptRoot $buildScript)
}

Write-Host ""
Write-Host "All builds completed." -ForegroundColor Green
