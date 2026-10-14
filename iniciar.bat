@echo off
REM Abre el sistema de facturacion.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
    echo.
    echo Falta la instalacion. Primero hace doble clic en instalar.bat
    echo.
    pause
    exit /b
)
.venv\Scripts\python iniciar.py
pause
