@echo off
REM Instala lo necesario (una sola vez). Requiere Python 3 instalado.
cd /d "%~dp0"
if not exist .venv (
    echo Creando entorno de Python...
    python -m venv .venv
)
echo Instalando Flask...
.venv\Scripts\python -m pip install -r requirements.txt
echo.
echo Listo. Ahora podes abrir el sistema con iniciar.bat
pause
