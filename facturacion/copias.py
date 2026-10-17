"""Copias de seguridad de la base de datos en cada PC (fuera de Google Drive).

Cada vez que se abre el sistema se guarda una copia en la carpeta local de la PC, así hay
un respaldo aunque algo salga mal con la sincronización. Se conservan las últimas 30.
"""
import os
import sqlite3
from datetime import datetime
from pathlib import Path

CONSERVAR = 30


def carpeta_local():
    """En Windows: C:\\Users\\<usuario>\\AppData\\Local\\FacturacionLouletano\\copias"""
    base = os.environ.get("LOCALAPPDATA") or os.path.join(Path.home(), ".facturacion")
    return os.path.join(base, "FacturacionLouletano", "copias")


def hacer_copia(base_datos, carpeta=None, conservar=CONSERVAR):
    """Copia la base (de forma segura, aunque esté en uso). Devuelve la ruta de la copia o None."""
    if not os.path.exists(base_datos):
        return None
    carpeta = carpeta or carpeta_local()
    os.makedirs(carpeta, exist_ok=True)
    destino = os.path.join(carpeta, f"facturacion_{datetime.now():%Y-%m-%d_%H-%M-%S}.sqlite")
    origen = sqlite3.connect(base_datos)
    copia = sqlite3.connect(destino)
    try:
        origen.backup(copia)
    finally:
        copia.close()
        origen.close()
    viejas = sorted(p for p in os.listdir(carpeta) if p.startswith("facturacion_") and p.endswith(".sqlite"))
    for nombre in viejas[:-conservar]:
        os.remove(os.path.join(carpeta, nombre))
    return destino
