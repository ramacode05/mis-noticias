"""Aviso de "sistema en uso" para compartir la carpeta entre dos PCs con Google Drive.

La base de datos (SQLite) vive en una carpeta de Google Drive. Si el sistema se abriera
en las dos PCs a la vez, cada una modificaría su copia y Google Drive no sabría cuál
quedarse. Para evitarlo, junto a la base se guarda el archivo en_uso.json:

    {"pc": "CASA", "estado": "abierto", "latido": "2026-10-17T10:30:00"}

Mientras el sistema está abierto, el "latido" se actualiza cada minuto (y Drive lo
sincroniza). Al cerrar, el estado pasa a "cerrado".
"""
import json
import os
import socket
import threading
from datetime import datetime, timedelta

ARCHIVO = "en_uso.json"
CADA = 60                         # segundos entre latidos
VENCIDO = timedelta(minutes=3)    # sin latido hace más de esto: la otra PC ya no lo usa


def nombre_pc():
    return os.environ.get("COMPUTERNAME") or socket.gethostname()


def leer(ruta):
    try:
        with open(ruta, encoding="utf-8") as f:
            datos = json.load(f)
        datos["latido"] = datetime.fromisoformat(datos["latido"])
        return datos
    except (OSError, ValueError, KeyError, TypeError):
        return None


def escribir(ruta, estado, pc=None):
    datos = {"pc": pc or nombre_pc(), "estado": estado,
             "latido": datetime.now().isoformat(timespec="seconds")}
    temporal = ruta + ".tmp"
    with open(temporal, "w", encoding="utf-8") as f:
        json.dump(datos, f)
    os.replace(temporal, ruta)


def revisar(ruta, pc=None, ahora=None):
    """Devuelve ("libre" | "en_uso" | "dudoso", datos_del_archivo).

    libre:   nadie lo usa, o lo dejó abierto esta misma PC (por ejemplo, un corte de luz).
    en_uso:  está abierto en la otra PC (latido reciente). No hay que abrirlo.
    dudoso:  la otra PC lo dejó "abierto" pero dejó de dar latidos: se cerró mal, o
             Google Drive todavía no terminó de sincronizar lo último que hizo esa PC.
    """
    pc = pc or nombre_pc()
    ahora = ahora or datetime.now()
    datos = leer(ruta)
    if not datos or datos.get("estado") != "abierto" or datos.get("pc") == pc:
        return "libre", datos
    if ahora - datos["latido"] < VENCIDO:
        return "en_uso", datos
    return "dudoso", datos


class Candado:
    """Marca el sistema como abierto en esta PC y mantiene el latido hasta cerrar."""

    def __init__(self, ruta):
        self.ruta = ruta
        self._parar = threading.Event()
        self._cerrado = False

    def abrir(self):
        escribir(self.ruta, "abierto")
        threading.Thread(target=self._latir, daemon=True).start()

    def _latir(self):
        while not self._parar.wait(CADA):
            try:
                escribir(self.ruta, "abierto")
            except OSError:
                pass  # Drive puede tener el archivo tomado un instante; reintenta al minuto

    def cerrar(self):
        if self._cerrado:
            return
        self._cerrado = True
        self._parar.set()
        try:
            escribir(self.ruta, "cerrado")
        except OSError:
            pass
