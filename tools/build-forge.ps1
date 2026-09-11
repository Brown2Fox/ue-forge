$ErrorActionPreference = "Stop"

& (Join-Path $PSScriptRoot "build-tool.ps1") `
    -SpecName "ue_forge" `
    -ArtifactName "UE Forge.exe"
