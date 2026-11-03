<#
.SYNOPSIS
    Assina arquivos do Windows (.exe, .msi) com o signtool, SE houver certificado.

.DESCRIPTION
    Duas formas, escolhidas pelas variáveis de ambiente:
      - WINDOWS_CERT_PFX_BASE64 + WINDOWS_CERT_PASSWORD: certificado .pfx em base64 e a senha
        (segredos do repositório no GitHub; é o que o CI usa).
      - WINDOWS_CERT_SHA1: impressão digital de um certificado já instalado no repositório do
        usuário (cartão inteligente, token USB, SimplySign...); para builds locais.
    Sem nenhuma delas, avisa e sai sem erro: o build continua com arquivos não assinados.
    Carimbo de tempo RFC 3161 em http://timestamp.digicert.com (a assinatura continua válida
    depois que o certificado vencer). Veja docs/ASSINATURA.md.

.EXAMPLE
    pwsh -NoProfile -File packaging\windows\assinar.ps1 dist\Revelador\Revelador.exe
#>
param(
    [Parameter(Mandatory = $true, ValueFromRemainingArguments = $true)][string[]]$Files
)

$ErrorActionPreference = "Stop"
$pfxB64 = $env:WINDOWS_CERT_PFX_BASE64
$senha = $env:WINDOWS_CERT_PASSWORD
$sha1 = ($env:WINDOWS_CERT_SHA1 -replace '\s', '')
$usarPfx = -not [string]::IsNullOrWhiteSpace($pfxB64) -and -not [string]::IsNullOrEmpty($senha)
if (-not $usarPfx -and -not $sha1) {
    Write-Host "Sem certificado (WINDOWS_CERT_PFX_BASE64/WINDOWS_CERT_PASSWORD ou WINDOWS_CERT_SHA1): nada foi assinado."
    exit 0
}

# signtool: no PATH ou no Windows SDK mais novo instalado.
$signtool = (Get-Command signtool.exe -ErrorAction SilentlyContinue).Source
if (-not $signtool) {
    $kits = Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10\bin"
    $signtool = Get-ChildItem -Path $kits -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match '^\d+(\.\d+){3}$' } |
        Sort-Object { [version]$_.Name } -Descending |
        ForEach-Object { Join-Path $_.FullName "x64\signtool.exe" } |
        Where-Object { Test-Path $_ } |
        Select-Object -First 1
}
if (-not $signtool) { throw "signtool.exe não encontrado (instale o Windows SDK)." }

$pfx = $null
if ($usarPfx) {
    $tmp = if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { [System.IO.Path]::GetTempPath() }
    $pfx = Join-Path $tmp ("cert-" + [guid]::NewGuid().ToString("N") + ".pfx")
    [System.IO.File]::WriteAllBytes($pfx, [Convert]::FromBase64String($pfxB64.Trim()))
    $certArgs = @("/f", $pfx, "/p", $senha)
} else {
    $certArgs = @("/sha1", $sha1)
}

try {
    foreach ($f in $Files) {
        if (-not (Test-Path $f)) { throw "Arquivo para assinar não existe: $f" }
        $ok = $false
        for ($i = 1; $i -le 3 -and -not $ok; $i++) {
            # O servidor de carimbo de tempo às vezes falha; tenta de novo.
            & $signtool sign /fd SHA256 /tr "http://timestamp.digicert.com" /td SHA256 `
                /d "Revelador" /du "https://github.com/edvitor13/revelador" `
                @certArgs $f
            if ($LASTEXITCODE -eq 0) { $ok = $true } else { Start-Sleep -Seconds (5 * $i) }
        }
        if (-not $ok) { throw "O signtool não conseguiu assinar $f." }
        & $signtool verify /pa $f
        if ($LASTEXITCODE -ne 0) {
            # Acontece com certificado de teste (autoassinado): a assinatura existe, mas a raiz não é confiável.
            Write-Warning "A assinatura de $f não foi aceita pela política padrão do Windows (certificado de teste?)."
        }
        Write-Host "Assinado: $f"
    }
} finally {
    if ($pfx) { Remove-Item -Force -ErrorAction SilentlyContinue $pfx }
}
# Tudo assinado: não deixa o código do último "signtool verify" (que falha com certificado de
# teste) vazar como $LASTEXITCODE para quem chamou (o GitHub Actions encerra o passo com ele).
exit 0
