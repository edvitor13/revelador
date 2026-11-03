<#
.SYNOPSIS
    Testa o .msi do Revelador de verdade: instala, confere, atualiza e desinstala.

.DESCRIPTION
    Feito para o CI (runner do GitHub, usuário descartável). NÃO rode no seu computador: o
    script instala e desinstala o Revelador do usuário atual.

    1. Instala o .msi (com ABRIR_APOS_INSTALAR=1) e confere pasta, marcador, atalhos, entrada em
       "Adicionar ou remover programas", se o app abriu e o diagnóstico do executável instalado.
    2. Atualiza para um .msi mínimo de versão maior (mesmo UpgradeCode) e confere que a versão
       antiga saiu e que só há uma entrada instalada (é o que o atualizador do app usa).
    3. Desinstala e confere que não sobrou nada.
    4. Instala numa pasta escolhida, atualiza sem informar a pasta e confere que a pasta foi
       lembrada; desinstala.
#>
param(
    [Parameter(Mandatory = $true)][string]$Msi,
    [Parameter(Mandatory = $true)][string]$Version,
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$Msi = (Resolve-Path $Msi).Path
$Tmp = Join-Path $(if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { [IO.Path]::GetTempPath() }) "verificar-msi"
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $Tmp
New-Item -ItemType Directory -Force -Path $Tmp | Out-Null

$Padrao = Join-Path $env:LOCALAPPDATA "Programs\Revelador"
$AtalhoMenu = Join-Path ([Environment]::GetFolderPath("Programs")) "Revelador.lnk"
$AtalhoDesktop = Join-Path ([Environment]::GetFolderPath("Desktop")) "Revelador.lnk"
$script:falhas = New-Object System.Collections.Generic.List[string]
$script:n = 0

function Confere([bool]$cond, [string]$msg) {
    if ($cond) { Write-Host "  ok      $msg" } else { Write-Host "  FALHOU  $msg"; $script:falhas.Add($msg) }
}

function Msiexec([string]$argumentos, [string]$nome) {
    $script:n++
    $log = Join-Path $Tmp ("{0:D2}-{1}.log" -f $script:n, $nome)
    Write-Host ""
    Write-Host "msiexec $argumentos"
    # Sem -Wait (que espera também os processos filhos) e com limite de tempo: uma linha de comando
    # errada faz o msiexec abrir uma janela de ajuda que nunca fecha sozinha.
    $p = Start-Process -FilePath msiexec.exe -ArgumentList "$argumentos /qn /norestart /l*v `"$log`"" -PassThru
    $null = $p.Handle
    if (-not $p.WaitForExit(15 * 60 * 1000)) {
        $p.Kill()
        throw "msiexec ($nome) não terminou em 15 minutos."
    }
    if ($p.ExitCode -ne 0 -and $p.ExitCode -ne 3010) {
        Get-Content $log -Tail 80 -ErrorAction SilentlyContinue
        throw "msiexec ($nome) saiu com o código $($p.ExitCode). Log: $log"
    }
}

# Produtos instalados com o UpgradeCode do Revelador (API do Windows Installer: é o que
# "Adicionar ou remover programas" e o MajorUpgrade enxergam).
$UpgradeCode = "{" + ([regex]::Match((Get-Content (Join-Path $PSScriptRoot "Revelador.wxs") -Raw),
    'UpgradeCode="([0-9A-Fa-f-]{36})"').Groups[1].Value) + "}"
$Installer = New-Object -ComObject WindowsInstaller.Installer

function Produtos-Instalados {
    # O PowerShell desenrola a coleção COM; @() garante uma lista (vazia ou não).
    $lista = @($Installer.RelatedProducts($UpgradeCode) | Where-Object { $_ })
    , $lista
}

function Info-Produto([string]$codigo, [string]$prop) {
    try { [string]$Installer.ProductInfo($codigo, $prop) } catch { "" }
}

function Marcador([string]$pasta) {
    $f = Join-Path $pasta "revelador-install.json"
    if (Test-Path $f) { Get-Content $f -Raw | ConvertFrom-Json } else { $null }
}

function Pare-App {
    Get-Process -Name Revelador -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
}

function Confere-Removido([string]$pasta) {
    Confere (-not (Test-Path $pasta)) "pasta removida ($pasta)"
    Confere ((Produtos-Instalados).Count -eq 0) "nenhum Revelador instalado (Windows Installer)"
    Confere (-not (Test-Path $AtalhoMenu)) "atalho do Menu Iniciar removido"
    Confere (-not (Test-Path $AtalhoDesktop)) "atalho da Área de Trabalho removido"
    # Só os valores do instalador somem. As preferências do app (subchave Revelador, gravada pelo
    # próprio app ao abrir) ficam de propósito: numa atualização o MSI também desinstala a versão
    # antiga, e apagá-las ali faria a pessoa perder as pastas recentes e as opções.
    $chave = "HKCU:\Software\Revelador"
    $valores = if (Test-Path $chave) { @((Get-Item $chave).Property) } else { @() }
    $doMsi = @("InstallDir", "AtalhoMenuIniciar", "AtalhoAreaDeTrabalho")
    $sobra = @($valores | Where-Object { $doMsi -contains $_ })
    Confere ($sobra.Count -eq 0) "valores do instalador removidos de HKCU\Software\Revelador ($($sobra -join ', '))"
}

# Um .msi mínimo (só o executável principal) com a mesma receita, para testar as atualizações.
function Msi-Minimo([string]$versao) {
    $pasta = Join-Path $Tmp "mini-$versao"
    New-Item -ItemType Directory -Force -Path $pasta | Out-Null
    Copy-Item $script:exeCopia $pasta
    $saida = Join-Path $Tmp "Revelador-$versao-mini.msi"
    & (Join-Path $PSScriptRoot "build_msi.ps1") -SourceDir $pasta -Output $saida -Version $versao -Python $Python | Out-Host
    $saida
}

Pare-App

# ---------------------------------------------------------------------------- 1. instalação
Write-Host "== 1. Instalação ($Msi)"
Msiexec "/i `"$Msi`" ABRIR_APOS_INSTALAR=1" "instalar"
$abriu = $false
for ($i = 0; $i -lt 30 -and -not $abriu; $i++) {
    if (Get-Process -Name Revelador -ErrorAction SilentlyContinue) { $abriu = $true } else { Start-Sleep -Seconds 1 }
}
Confere $abriu "ABRIR_APOS_INSTALAR=1 abriu o Revelador"
Pare-App

$exe = Join-Path $Padrao "Revelador.exe"
Confere (Test-Path $exe) "Revelador.exe em $Padrao"
Confere (Test-Path (Join-Path $Padrao "_internal")) "pasta _internal instalada"
$m = Marcador $Padrao
Confere ($m -and $m.kind -eq "msi" -and $m.version -eq $Version) "revelador-install.json = {kind: msi, version: $Version}"
$script:exeCopia = Join-Path $Tmp "Revelador.exe"
Copy-Item $exe $script:exeCopia

Confere (Test-Path $AtalhoMenu) "atalho no Menu Iniciar"
Confere (Test-Path $AtalhoDesktop) "atalho na Área de Trabalho"
$assoc = (Get-ItemProperty "HKCU:\Software\Classes\.revelador" -ErrorAction SilentlyContinue).'(default)'
$abrirCmd = (Get-ItemProperty "HKCU:\Software\Classes\Revelador.Trabalho\shell\open\command" -ErrorAction SilentlyContinue).'(default)'
Confere ($assoc -eq "Revelador.Trabalho") "extensão .revelador associada (ProgId Revelador.Trabalho)"
Confere ($abrirCmd -like '*Revelador.exe" "%1"') "comando de abertura do .revelador usa ""%1"""
$prods = Produtos-Instalados
Confere ($prods.Count -eq 1) "um Revelador instalado (Windows Installer, UpgradeCode $UpgradeCode)"
if ($prods.Count -ge 1) {
    $pc = $prods[0]
    Write-Host "        produto: $pc  $(Info-Produto $pc 'ProductName') $(Info-Produto $pc 'VersionString')"
    Confere ((Info-Produto $pc "VersionString") -eq $Version) "versão registrada = $Version"
    Confere ((Info-Produto $pc "URLInfoAbout") -like "https://github.com/edvitor13/revelador*") "link do repositório em Adicionar ou remover programas"
    Confere ([bool](Info-Produto $pc "ProductIcon")) "ícone em Adicionar ou remover programas"
    Confere ((Info-Produto $pc "AssignmentType") -eq "0") "instalação por usuário (AssignmentType 0)"
}

# O executável instalado carrega todas as dependências nativas (Pillow, pillow-heif, OpenCV...).
try {
    & (Join-Path $PSScriptRoot "diagnosticar.ps1") -Exe $exe | Out-Host
    $codigoDiag = $LASTEXITCODE
} catch {
    Write-Host "  erro no diagnóstico: $_"
    $codigoDiag = -1
}
Confere ($codigoDiag -eq 0) "diagnóstico do Revelador.exe instalado (código $codigoDiag)"

# ---------------------------------------------------------------------------- 2. atualização
Write-Host ""
Write-Host "== 2. Atualização para uma versão maior"
$mini1 = Msi-Minimo "99.0.0"
Msiexec "/i `"$mini1`"" "atualizar"
$prods = Produtos-Instalados
Confere ($prods.Count -eq 1) "continua um produto só (a versão antiga foi removida)"
if ($prods.Count -ge 1) { Confere ((Info-Produto $prods[0] "VersionString") -eq "99.0.0") "versão nova registrada (99.0.0)" }
Confere (-not (Test-Path (Join-Path $Padrao "_internal"))) "arquivos da versão antiga removidos"
$m = Marcador $Padrao
Confere ($m -and $m.version -eq "99.0.0") "marcador atualizado para 99.0.0"

# ---------------------------------------------------------------------------- 3. desinstalação
Write-Host ""
Write-Host "== 3. Desinstalação"
Msiexec "/x `"$mini1`"" "desinstalar"
Confere-Removido $Padrao

# ---------------------------------------------------------------------------- 4. pasta lembrada
Write-Host ""
Write-Host "== 4. Pasta escolhida é mantida nas atualizações"
$pasta = Join-Path $Tmp "Pasta Escolhida\Revelador"
Msiexec "/i `"$mini1`" INSTALLFOLDER=`"$pasta\`"" "instalar-pasta"
Confere (Test-Path (Join-Path $pasta "Revelador.exe")) "instalado em $pasta"
$mini2 = Msi-Minimo "99.0.1"
Msiexec "/i `"$mini2`"" "atualizar-pasta"
Confere (Test-Path (Join-Path $pasta "Revelador.exe")) "atualização ficou em $pasta"
Confere (-not (Test-Path (Join-Path $Padrao "Revelador.exe"))) "nada instalado na pasta padrão"
$m = Marcador $pasta
Confere ($m -and $m.version -eq "99.0.1") "marcador da pasta escolhida = 99.0.1"
Msiexec "/x `"$mini2`"" "desinstalar-pasta"
Confere-Removido $pasta

Write-Host ""
if ($script:falhas.Count -gt 0) {
    Write-Host "O .msi falhou em $($script:falhas.Count) conferência(s):"
    $script:falhas | ForEach-Object { Write-Host "  - $_" }
    exit 1
}
Write-Host "O .msi passou em todas as conferências."
