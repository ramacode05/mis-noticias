"""Configuración general del sistema: puntos de venta de facturas y de remitos."""
from flask import Blueprint, flash, redirect, render_template, request, url_for

from .db import get_db

bp = Blueprint("configuracion", __name__, url_prefix="/configuracion")

CAMPOS = ("punto_venta", "remito_punto_venta")


def leer_config(clave):
    fila = get_db().execute("SELECT valor FROM configuracion WHERE clave = ?", (clave,)).fetchone()
    return fila["valor"] if fila else None


@bp.route("/", methods=("GET", "POST"))
def editar():
    errores = {}
    valores = {c: leer_config(c) for c in CAMPOS}
    if request.method == "POST":
        valores = {c: (request.form.get(c) or "").strip() for c in CAMPOS}
        for campo, valor in valores.items():
            if not valor.isdigit() or not 1 <= int(valor) <= 99998:
                errores[campo] = "El punto de venta es un número entre 1 y 99998."
        if not errores:
            db = get_db()
            db.executemany("INSERT OR REPLACE INTO configuracion (clave, valor) VALUES (?, ?)",
                           [(c, str(int(v))) for c, v in valores.items()])
            db.commit()
            flash("Configuración guardada.", "ok")
            return redirect(url_for("configuracion.editar"))
    return render_template("configuracion.html", valores=valores, errores=errores)
