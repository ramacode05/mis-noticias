"""Arranca el sistema. Abrir en el navegador: http://127.0.0.1:5000"""
import threading
import webbrowser

from facturacion import create_app

app = create_app()

if __name__ == "__main__":
    print("Sistema de facturación funcionando en http://127.0.0.1:5000")
    print("Para cerrarlo, cerrá esta ventana (o Ctrl+C).")
    threading.Timer(1.5, lambda: webbrowser.open("http://127.0.0.1:5000")).start()
    app.run(host="127.0.0.1", port=5000, debug=False)
