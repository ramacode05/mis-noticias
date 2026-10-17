@echo off
REM Instala lo necesario (una sola vez). Requiere Python 3 instalado.
cd /d "%~dp0"

REM Busca Python: primero "python", despues el lanzador "py" de Windows.
set PYTHON=
python --version >nul 2>&1 && set PYTHON=python
if not defined PYTHON py -3 --version >nul 2>&1 && set PYTHON=py -3
if not defined PYTHON (
    echo.
    echo ======================================================================
    echo  No se encontro Python en esta computadora.
    echo.
    echo  1. Entra a https://www.python.org/downloads/ y baja Python.
    echo  2. Al instalarlo, TILDA la opcion "Add python.exe to PATH"
    echo     que esta abajo de todo en la primera pantalla.
    echo  3. Despues volve a ejecutar instalar.bat
    echo ======================================================================
    echo.
    pause
    exit /b 1
)

if not exist .venv\Scripts\python.exe (
    echo Creando entorno de Python...
    if exist .venv rmdir /s /q .venv
    %PYTHON% -m venv .venv
)
echo Instalando las herramientas: Flask y ReportLab...
.venv\Scripts\python -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo Hubo un problema al instalar. Revisa que haya internet y volve a intentar.
    pause
    exit /b 1
)
echo.
echo Listo. Ahora podes abrir el sistema con iniciar.bat
pause
