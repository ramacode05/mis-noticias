# Sistema de facturación

App web local para facturación y cuentas corrientes. Ver `CLAUDE.md` para el contexto y el plan.

## En Windows

1. Instalar Python 3 desde https://www.python.org/downloads/ (marcar "Add Python to PATH").
2. Poner la carpeta del sistema dentro de Google Drive (para usarla en más de una PC).
3. Doble clic en `instalar.bat` (una vez en cada PC).
4. Doble clic en `iniciar.bat` y abrir http://127.0.0.1:5000
5. Al terminar, botón "Cerrar sistema" (así la otra PC lo puede abrir).

## Pruebas automáticas

    python -m unittest discover tests
