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


def init_db():
    """Crea las tablas que falten. No borra datos existentes."""
    get_db().executescript(ESQUEMA.read_text(encoding="utf-8"))


def init_app(app):
    app.teardown_appcontext(close_db)
    with app.app_context():
        init_db()
