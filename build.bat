@echo off
rem Gera o Revelador com o PyInstaller (pasta dist\Revelador, com Revelador.exe), confere as
rem dependências nativas, monta o .zip portátil e, se o WiX Toolset estiver instalado, o instalador
rem .msi. Com WINDOWS_CERT_PFX_BASE64 + WINDOWS_CERT_PASSWORD ou WINDOWS_CERT_SHA1 definidas, também
rem assina o executável e o .msi.
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title Revelador - build

if not exist ".venv\Scripts\python.exe" (
    echo.
    echo  O ambiente .venv não existe. Rode primeiro o instalar.bat.
    echo.
    pause
    exit /b 1
)

echo  Instalando o PyInstaller no ambiente .venv...
".venv\Scripts\python.exe" -m pip install --upgrade "pyinstaller>=6.10"
if errorlevel 1 goto fail

echo.
echo  Gerando o executável...
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean Revelador.spec
if errorlevel 1 goto fail

set "PS=powershell -NoProfile -ExecutionPolicy Bypass -File"
echo.
echo  Conferindo as dependências dentro do executável...
%PS% packaging\windows\diagnosticar.ps1 -Exe dist\Revelador\Revelador.exe
if errorlevel 1 goto fail

for /f "delims=" %%v in ('.venv\Scripts\python.exe packaging\install_marker.py --print-version') do set VER=%%v
set "BASE=dist\Revelador-%VER%-windows-x64"
set "MSI="
set "ASSINAR="
if defined WINDOWS_CERT_PFX_BASE64 set "ASSINAR=1"
if defined WINDOWS_CERT_SHA1 set "ASSINAR=1"

if defined ASSINAR (
    echo.
    echo  Assinando o executável...
    %PS% packaging\windows\assinar.ps1 dist\Revelador\Revelador.exe
    if errorlevel 1 goto fail
)

where wix >nul 2>nul
if errorlevel 1 (
    echo.
    echo  WiX Toolset não encontrado: o instalador .msi não será gerado.
    echo  Para gerar, instale o .NET SDK e rode: dotnet tool install --global wix --version 5.0.2
    goto zip
)
echo.
echo  Gerando o instalador .msi...
%PS% packaging\windows\build_msi.ps1 -SourceDir dist\Revelador -Output "%BASE%.msi" -Version %VER% -Python ".venv\Scripts\python.exe"
if errorlevel 1 goto fail
if defined ASSINAR (
    %PS% packaging\windows\assinar.ps1 "%BASE%.msi"
    if errorlevel 1 goto fail
)
set "MSI=%BASE%.msi"

:zip
echo.
echo  Gerando o .zip portátil...
".venv\Scripts\python.exe" packaging\install_marker.py dist\Revelador zip
if errorlevel 1 goto fail
if exist "%BASE%.zip" del /q "%BASE%.zip"
powershell -NoProfile -Command "Compress-Archive -Path 'dist\Revelador' -DestinationPath '%BASE%.zip'"
if errorlevel 1 goto fail

echo.
echo  Pronto!
echo    Executável:  dist\Revelador\Revelador.exe
if defined MSI echo    Instalador:  %MSI%
echo    Portátil:    %BASE%.zip
echo.
pause
exit /b 0

:fail
echo.
echo  O build falhou. Veja as mensagens acima.
echo.
pause
exit /b 1
