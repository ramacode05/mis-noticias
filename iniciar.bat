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
REM Si una version nueva necesita alguna herramienta mas, la instala (si ya esta, no hace nada).
.venv\Scripts\python -m pip install -q --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
    echo.
    echo No se pudieron instalar las herramientas nuevas. Revisa que haya internet.
    echo El sistema arranca igual, pero algunas funciones pueden no andar.
    echo.
)
.venv\Scripts\python iniciar.py
pause
