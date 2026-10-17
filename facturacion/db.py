"""Conexión a la base de datos SQLite."""
import sqlite3
from pathlib import Path

from flask import current_app, g

ESQUEMA = Path(__file__).with_name("esquema.sql")


def get_db():
    """Devuelve la conexión de la petición actual (la abre si hace falta)."""
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


# Columnas agregadas después de que la tabla ya existía en la PC del usuario.
# (tabla, columna, definición). Se agregan solas al arrancar si faltan.
COLUMNAS_NUEVAS = [
    ("facturas", "remito_pto_vta", "INTEGER"),
    ("facturas", "remito_numero", "INTEGER"),
    ("facturas", "token", "TEXT"),
    ("facturas", "asociado_id", "INTEGER"),  # en una nota de crédito: la factura que anula
]

# Índices sobre columnas nuevas: se crean después de agregar las columnas.
INDICES_NUEVOS = [
    "CREATE INDEX IF NOT EXISTS facturas_remito ON facturas (remito_pto_vta, remito_numero)",
    # Evita guardar dos veces la misma factura si se toca "Confirmar" dos veces.
    "CREATE UNIQUE INDEX IF NOT EXISTS facturas_token ON facturas (token) WHERE token IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS facturas_asociado ON facturas (asociado_id)",
]


def init_db():
    """Crea las tablas y columnas que falten. No borra datos existentes."""
    db = get_db()
    db.executescript(ESQUEMA.read_text(encoding="utf-8"))
    for tabla, columna, definicion in COLUMNAS_NUEVAS:
        existentes = {fila["name"] for fila in db.execute(f"PRAGMA table_info({tabla})")}
        if columna not in existentes:
            db.execute(f"ALTER TABLE {tabla} ADD COLUMN {columna} {definicion}")
    for sql in INDICES_NUEVOS:
        db.execute(sql)
    db.commit()


def init_app(app):
    app.teardown_appcontext(close_db)
    with app.app_context():
        init_db()
