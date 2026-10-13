@echo off
REM Abre el sistema de facturacion.
cd /d "%~dp0"
if not exist .venv (
    echo Primero hay que ejecutar instalar.bat
    pause
    exit /b
)
.venv\Scripts\python iniciar.py
pause
