<#
.SYNOPSIS
    Monta o instalador .msi do Revelador com o WiX Toolset v5.

.DESCRIPTION
    Grava o revelador-install.json {"kind": "msi"} na pasta do PyInstaller, gera a licença em RTF
    e chama o `wix build` com packaging\windows\Revelador.wxs. Instala as extensões do WiX
    (UI e Util) no cache global do usuário se ainda não estiverem lá.

    Requisitos: .NET SDK 6+ e o WiX como ferramenta do dotnet:
        dotnet tool install --global wix --version 5.0.2

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File packaging\windows\build_msi.ps1 `
        -SourceDir dist\Revelador -Output dist\Revelador-0.1.0-windows-x64.msi
#>
param(
    [Parameter(Mandatory = $true)][string]$SourceDir,
    [Parameter(Mandatory = $true)][string]$Output,
    [string]$Version = "",
    [string]$Python = "python",
    [string]$WixVersion = "5.0.2"
)

$ErrorActionPreference = "Stop"
$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Src = (Resolve-Path $SourceDir).Path
if (-not [System.IO.Path]::IsPathRooted($Output)) { $Output = Join-Path (Get-Location).Path $Output }

if (-not (Test-Path (Join-Path $Src "Revelador.exe"))) {
    throw "Não achei Revelador.exe em $Src. Rode o PyInstaller antes."
}
if (-not $Version) {
    $Version = (& $Python (Join-Path $Repo "packaging\install_marker.py") --print-version | Out-String).Trim()
}
if ($Version -notmatch '^\d+\.\d+\.\d+$') {
    throw "Versão inválida para o MSI: '$Version' (o MSI só aceita números: x.y.z)."
}
if (-not (Get-Command wix -ErrorAction SilentlyContinue)) {
    throw "WiX não encontrado. Instale com: dotnet tool install --global wix --version $WixVersion"
}

# Extensões do WiX na mesma versão da ferramenta.
$cache = (& wix extension list -g | Out-String)
foreach ($ext in @("WixToolset.UI.wixext", "WixToolset.Util.wixext")) {
    if ($cache -notmatch [regex]::Escape("$ext $WixVersion")) {
        & wix extension add -g "$ext/$WixVersion" | Out-Host
        if ($LASTEXITCODE -ne 0) { throw "Falha ao instalar a extensão $ext/$WixVersion do WiX." }
    }
}

$Work = Join-Path $Repo "build\msi"
New-Item -ItemType Directory -Force -Path $Work | Out-Null
$Rtf = Join-Path $Work "License.rtf"
# As saídas vão para a tela (Out-Host), não para o pipeline: quem chama este script não recebe lixo.
& $Python (Join-Path $Repo "packaging\windows\license_rtf.py") (Join-Path $Repo "LICENSE") $Rtf | Out-Host
if ($LASTEXITCODE -ne 0) { throw "Falha ao gerar a licença em RTF." }
& $Python (Join-Path $Repo "packaging\install_marker.py") $Src msi --version $Version | Out-Host
if ($LASTEXITCODE -ne 0) { throw "Falha ao gravar o revelador-install.json." }

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Output) | Out-Null
Write-Host "Montando $Output (versão $Version)..."
& wix build (Join-Path $PSScriptRoot "Revelador.wxs") `
    -arch x64 -culture pt-BR `
    -ext "WixToolset.UI.wixext/$WixVersion" -ext "WixToolset.Util.wixext/$WixVersion" `
    -d "Version=$Version" -d "SourceDir=$Src" -d "RepoDir=$Repo" -d "LicenseRtf=$Rtf" `
    -pdbtype none -o $Output | Out-Host
if ($LASTEXITCODE -ne 0) { throw "O wix build falhou (código $LASTEXITCODE)." }

$size = [math]::Round((Get-Item $Output).Length / 1MB, 1)
Write-Host "Instalador gerado: $Output ($size MB)"
