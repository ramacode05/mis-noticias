"""Arranca el sistema. Abrir en el navegador: http://127.0.0.1:5000"""
import socket
import sys
import threading
import time
import webbrowser

DIRECCION = "http://127.0.0.1:5000"


def puerto_ocupado():
    with socket.socket() as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", 5000)) == 0


def abrir_navegador_cuando_este_listo():
    """Espera a que el sistema responda (hasta 60 segundos) y recién ahí abre el navegador."""
    for _ in range(120):
        if puerto_ocupado():
            webbrowser.open(DIRECCION)
            return
        time.sleep(0.5)
    print("El sistema tarda en arrancar. Probá abrir a mano:", DIRECCION)


if __name__ == "__main__":
    if puerto_ocupado():
        print("=" * 70)
        print("ATENCIÓN: el sistema ya está abierto en otra ventana negra.")
        print("Si acabás de actualizar, cerrá TODAS las ventanas negras del sistema")
        print("y volvé a abrir iniciar.bat.")
        print("=" * 70)
        webbrowser.open(DIRECCION)
        sys.exit(1)

    print("Arrancando el sistema de facturación, esperá unos segundos...")
    from facturacion import create_app
    app = create_app()

    print(f"Sistema funcionando en {DIRECCION}")
    print("Para cerrarlo, cerrá esta ventana (o Ctrl+C).")
    threading.Thread(target=abrir_navegador_cuando_este_listo, daemon=True).start()
    app.run(host="127.0.0.1", port=5000, debug=False)
