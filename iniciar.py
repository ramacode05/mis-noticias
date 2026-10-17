"""Arranca el sistema. Abrir en el navegador: http://127.0.0.1:5000

Antes de abrir revisa que el sistema no esté abierto en la otra PC (la carpeta se comparte
con Google Drive) y guarda una copia de seguridad de los datos en esta PC.
"""
import atexit
import os
import socket
import sys
import threading
import time
import webbrowser

from facturacion import candado, copias

DIRECCION = "http://127.0.0.1:5000"
CARPETA = os.path.dirname(os.path.abspath(__file__))
BASE_DATOS = os.path.join(CARPETA, "instance", "facturacion.sqlite")
EN_USO = os.path.join(CARPETA, "instance", candado.ARCHIVO)


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


def aviso(*lineas):
    print("=" * 72)
    for linea in lineas:
        print(linea)
    print("=" * 72)


def revisar_otra_pc():
    """Devuelve True si se puede abrir. Si está abierto en la otra PC, no deja."""
    estado, datos = candado.revisar(EN_USO)
    if estado == "libre":
        return True
    hora = datos["latido"].strftime("%d/%m/%Y %H:%M")
    if estado == "en_uso":
        aviso("NO SE PUEDE ABRIR: el sistema está abierto en la computadora " + datos["pc"] + ".",
              "",
              "Cerralo en esa computadora con el botón \"Cerrar sistema\" (arriba a la",
              "derecha), esperá un minuto a que Google Drive sincronice y volvé a abrirlo acá.")
        return False
    aviso("ATENCIÓN: la última vez el sistema no se cerró bien en " + datos["pc"],
          f"(última señal: {hora}).",
          "",
          "Puede ser que se haya cortado la luz, o que esa computadora se apagó antes de",
          "que Google Drive terminara de subir los últimos cambios.",
          "",
          "Si esa computadora está apagada: prendela, abrí Google Drive, esperá a que",
          "termine de sincronizar y recién ahí abrí el sistema acá.",
          "",
          "Si estás seguro de que los datos están al día, podés abrirlo igual.")
    respuesta = input("¿Abrir igual? Escribí SI y apretá Enter (cualquier otra cosa cancela): ")
    return respuesta.strip().upper() in ("SI", "SÍ")


def cerrar_al_cerrar_la_ventana(cerrar):
    """En Windows, marca el sistema como cerrado aunque se cierre la ventana negra con la X."""
    if os.name != "nt":
        return
    import ctypes

    tipo = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_uint)

    def manejador(_evento):
        cerrar()
        return False  # deja que Windows siga cerrando la ventana

    cerrar_al_cerrar_la_ventana.manejador = tipo(manejador)  # que no lo borre la memoria
    ctypes.windll.kernel32.SetConsoleCtrlHandler(cerrar_al_cerrar_la_ventana.manejador, True)


if __name__ == "__main__":
    if puerto_ocupado():
        aviso("ATENCIÓN: el sistema ya está abierto en otra ventana negra de esta computadora.",
              "Si acabás de actualizar, cerrá TODAS las ventanas negras del sistema",
              "y volvé a abrir iniciar.bat.")
        webbrowser.open(DIRECCION)
        sys.exit(1)

    os.makedirs(os.path.dirname(BASE_DATOS), exist_ok=True)
    if not revisar_otra_pc():
        sys.exit(1)

    try:
        copia = copias.hacer_copia(BASE_DATOS)
        if copia:
            print("Copia de seguridad guardada en esta PC:", copia)
    except Exception as error:  # una copia que falla no debe impedir trabajar
        print("No se pudo guardar la copia de seguridad:", error)

    uso = candado.Candado(EN_USO)
    uso.abrir()
    atexit.register(uso.cerrar)
    cerrar_al_cerrar_la_ventana(uso.cerrar)

    print("Arrancando el sistema de facturación, esperá unos segundos...")
    from facturacion import create_app
    app = create_app({"CANDADO": uso})

    print(f"Sistema funcionando en {DIRECCION}")
    print("Para cerrarlo, usá el botón \"Cerrar sistema\" en la página (o cerrá esta ventana).")
    threading.Thread(target=abrir_navegador_cuando_este_listo, daemon=True).start()
    app.run(host="127.0.0.1", port=5000, debug=False)
