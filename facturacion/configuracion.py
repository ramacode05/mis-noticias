"""Configuración general del sistema (por ahora, el punto de venta)."""
from flask import Blueprint, flash, redirect, render_template, request, url_for

from .db import get_db

bp = Blueprint("configuracion", __name__, url_prefix="/configuracion")


def leer_config(clave):
    fila = get_db().execute("SELECT valor FROM configuracion WHERE clave = ?", (clave,)).fetchone()
    return fila["valor"] if fila else None


@bp.route("/", methods=("GET", "POST"))
def editar():
    errores = {}
    punto_venta = leer_config("punto_venta")
    if request.method == "POST":
        punto_venta = (request.form.get("punto_venta") or "").strip()
        if not punto_venta.isdigit() or not 1 <= int(punto_venta) <= 99998:
            errores["punto_venta"] = "El punto de venta es un número entre 1 y 99998."
        else:
            db = get_db()
            db.execute("UPDATE configuracion SET valor = ? WHERE clave = 'punto_venta'",
                       (str(int(punto_venta)),))
            db.commit()
            flash("Configuración guardada.", "ok")
            return redirect(url_for("configuracion.editar"))
    return render_template("configuracion.html", punto_venta=punto_venta, errores=errores)
