@echo off
rem Abre o Revelador sem janela de console. Fotos passadas como argumento (ou arrastadas sobre
rem este .bat) são abertas direto no app.
chcp 65001 >nul
set "RV_DIR=%~dp0"

if not exist "%RV_DIR%.venv\Scripts\pythonw.exe" (
    echo.
    echo  O ambiente do Revelador ainda não foi criado.
    echo  Rode primeiro o instalar.bat.
    echo.
    pause
    exit /b 1
)

start "" "%RV_DIR%.venv\Scripts\pythonw.exe" "%RV_DIR%Revelador.pyw" %*
