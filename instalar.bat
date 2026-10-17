@echo off
REM Instala lo necesario en ESTA computadora (una sola vez por PC). Requiere Python 3.
REM El programa y los datos pueden estar en Google Drive; lo que se instala aca queda en
REM la PC (carpeta AppData), para que Google Drive no tenga que sincronizarlo.
cd /d "%~dp0"
set VENV=%LOCALAPPDATA%\FacturacionLouletano\venv

REM Busca Python: primero "python", despues el lanzador "py" de Windows.
set PYTHON=
python --version >/dev/null 2>&1 && set PYTHON=python
if not defined PYTHON py -3 --version >/dev/null 2>&1 && set PYTHON=py -3
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

REM Las versiones anteriores instalaban dentro de la carpeta del sistema (.venv).
REM Se borra para que Google Drive no sincronice miles de archivos.
if exist .venv (
    echo Borrando la instalacion vieja de la carpeta del sistema...
    rmdir /s /q .venv
)

if not exist "%VENV%\Scripts\python.exe" (
    echo Creando entorno de Python en esta computadora...
    if exist "%VENV%" rmdir /s /q "%VENV%"
    %PYTHON% -m venv "%VENV%"
)
echo Instalando las herramientas: Flask y ReportLab...
"%VENV%\Scripts\python" -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo Hubo un problema al instalar. Revisa que haya internet y volve a intentar.
    pause
    exit /b 1
)
echo.
echo Listo. Ahora podes abrir el sistema con iniciar.bat
pause
