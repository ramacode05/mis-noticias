@echo off
REM Instala lo necesario en ESTA computadora (una sola vez por PC). Requiere Python 3.
REM El programa y los datos pueden estar en Google Drive; lo que se instala aca queda en
REM la PC (carpeta AppData), para que Google Drive no tenga que sincronizarlo.
cd /d "%~dp0"
set "VENV=%LOCALAPPDATA%\FacturacionLouletano\venv"

REM --- Busca Python ------------------------------------------------------------------
REM Se pide a cada candidato que diga donde esta instalado (sys.executable). Asi se
REM descarta el "acceso" de Windows que abre la Microsoft Store y no es Python de verdad.
set "PYTHON="
for /f "delims=" %%P in ('python -c "import sys; print(sys.executable)" 2^>nul') do set "PYTHON=%%P"
if not defined PYTHON for /f "delims=" %%P in ('py -3 -c "import sys; print(sys.executable)" 2^>nul') do set "PYTHON=%%P"
REM Si no esta en el PATH, lo busca en las carpetas donde lo instala el instalador oficial.
if not defined PYTHON for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do if exist "%%D\python.exe" set "PYTHON=%%D\python.exe"
if not defined PYTHON for /d %%D in ("%ProgramFiles%\Python3*") do if exist "%%D\python.exe" set "PYTHON=%%D\python.exe"
if not defined PYTHON for /d %%D in ("C:\Python3*") do if exist "%%D\python.exe" set "PYTHON=%%D\python.exe"

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
echo Python encontrado: %PYTHON%

REM Las versiones anteriores instalaban dentro de la carpeta del sistema (.venv).
REM Se borra para que Google Drive no sincronice miles de archivos.
if exist .venv (
    echo Borrando la instalacion vieja de la carpeta del sistema...
    rmdir /s /q .venv
)

if not exist "%VENV%\Scripts\python.exe" (
    echo Creando entorno de Python en esta computadora...
    if exist "%VENV%" rmdir /s /q "%VENV%"
    "%PYTHON%" -m venv "%VENV%"
)
if not exist "%VENV%\Scripts\python.exe" (
    echo.
    echo No se pudo crear el entorno de Python. Mandale una captura de esta ventana a Claude.
    pause
    exit /b 1
)
echo Instalando las herramientas: Flask, ReportLab y cryptography...
"%VENV%\Scripts\python" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
    echo.
    echo Hubo un problema al instalar. Revisa que haya internet y volve a intentar.
    pause
    exit /b 1
)
echo.
echo Listo. Ahora podes abrir el sistema con iniciar.bat
pause
