<#
.SYNOPSIS
    Roda o diagnóstico de um Revelador.exe (dependências nativas) e confere o resultado.

.DESCRIPTION
    O Revelador.exe não tem console: o resultado vai para um arquivo JSON
    (Revelador.exe --diagnostico ARQUIVO; veja revelador/diagnostico.py). Sai com código 1 se o
    executável não terminar, não gravar o arquivo ou algum item falhar. Usado pelo CI no executável
    recém-gerado e no instalado pelo .msi (verificar_msi.ps1).

.EXAMPLE
    pwsh -NoProfile -File packaging\windows\diagnosticar.ps1 -Exe dist\Revelador\Revelador.exe
#>
param(
    [Parameter(Mandatory = $true)][string]$Exe,
    [int]$TimeoutSeconds = 120
)

$ErrorActionPreference = "Stop"
$Exe = (Resolve-Path $Exe).Path
$tmp = if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { [IO.Path]::GetTempPath() }
$saida = Join-Path $tmp ("diagnostico-" + [guid]::NewGuid().ToString("N") + ".json")

Write-Host "Diagnóstico de $Exe"
$p = Start-Process -FilePath $Exe -ArgumentList @("--diagnostico", "`"$saida`"") -PassThru
$null = $p.Handle  # guarda o handle: sem isso o ExitCode pode vir vazio
if (-not $p.WaitForExit($TimeoutSeconds * 1000)) {
    $p.Kill()
    throw "O Revelador.exe não terminou o diagnóstico em $TimeoutSeconds s."
}
if (-not (Test-Path $saida)) { throw "O Revelador.exe saiu com o código $($p.ExitCode) sem gravar $saida." }

$r = Get-Content $saida -Raw -Encoding utf8 | ConvertFrom-Json
Remove-Item $saida -ErrorAction SilentlyContinue
Write-Host ("  {0} {1} | Python {2} | empacotado: {3}" -f $r.app, $r.versao, $r.python, $r.empacotado)
foreach ($nome in $r.itens.PSObject.Properties.Name) {
    $i = $r.itens.$nome
    if ($i.ok) {
        Write-Host ("  ok      {0} {1}" -f $nome, $i.versao)
    } else {
        Write-Host ("  FALHOU  {0}: {1}" -f $nome, $i.erro)
        if ($i.detalhes) { Write-Host $i.detalhes }
    }
}
if (-not $r.ok -or $p.ExitCode -ne 0) {
    Write-Host "O diagnóstico falhou (código $($p.ExitCode))."
    exit 1
}
Write-Host "Todas as dependências nativas funcionam."
exit 0
