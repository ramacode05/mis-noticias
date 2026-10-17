@echo off
REM Abre el sistema de facturacion.
cd /d "%~dp0"
set VENV=%LOCALAPPDATA%\FacturacionLouletano\venv
REM No guardar archivos .pyc en la carpeta compartida (Drive los sincronizaria sin sentido).
set PYTHONDONTWRITEBYTECODE=1
if not exist "%VENV%\Scripts\python.exe" (
    echo.
    echo Falta la instalacion en esta computadora.
    echo Primero hace doble clic en instalar.bat
    echo.
    pause
    exit /b
)
REM Si una version nueva necesita alguna herramienta mas, la instala (si ya esta, no hace nada).
"%VENV%\Scripts\python" -m pip install -q --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
    echo.
    echo No se pudieron instalar las herramientas nuevas. Revisa que haya internet.
    echo El sistema arranca igual, pero algunas funciones pueden no andar.
    echo.
)
"%VENV%\Scripts\python" iniciar.py
pause
