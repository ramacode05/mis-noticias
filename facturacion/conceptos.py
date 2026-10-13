"""Pantallas de conceptos fijos (plantillas para el detalle de las facturas)."""
import sqlite3

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from .db import get_db

bp = Blueprint("conceptos", __name__, url_prefix="/conceptos")


def validar_concepto(datos):
    """Devuelve (datos_limpios, errores)."""
    limpio = {
        # Junta espacios repetidos para que "Desarme  y" y "Desarme y" sean el mismo texto.
        "descripcion": " ".join((datos.get("descripcion") or "").split()),
        "activo": 1 if datos.get("activo") else 0,
    }
    errores = {}
    if not limpio["descripcion"]:
        errores["descripcion"] = "Escribí el texto del concepto."
    elif len(limpio["descripcion"]) > 500:
        errores["descripcion"] = "El texto es demasiado largo (máximo 500 letras)."
    return limpio, errores


def existe_descripcion(descripcion, excepto_id=None):
    """Compara sin mayúsculas en Python, porque SQLite no iguala "Ó" con "ó"."""
    buscada = descripcion.casefold()
    filas = get_db().execute("SELECT id, descripcion FROM conceptos").fetchall()
    return any(f["descripcion"].casefold() == buscada and f["id"] != excepto_id for f in filas)


@bp.route("/")
def lista():
    q = (request.args.get("q") or "").strip()
    ver_inactivos = request.args.get("inactivos") == "1"

    sql = "SELECT * FROM conceptos WHERE 1=1"
    params = []
    if not ver_inactivos:
        sql += " AND activo = 1"
    # Cada palabra buscada tiene que aparecer, en cualquier orden: "traseros izq" encuentra
    # "Desarme y Reparación en Elásticos Traseros Izquierdo".
    for palabra in q.split():
        sql += " AND descripcion LIKE ?"
        params.append(f"%{palabra}%")
    sql += " ORDER BY descripcion COLLATE NOCASE"

    conceptos = get_db().execute(sql, params).fetchall()
    return render_template("conceptos/lista.html", conceptos=conceptos, q=q,
                           ver_inactivos=ver_inactivos)


@bp.route("/nuevo", methods=("GET", "POST"))
def nuevo():
    if request.method == "POST":
        datos, errores = validar_concepto(request.form)
        if not errores and existe_descripcion(datos["descripcion"]):
            errores["descripcion"] = "Ya existe un concepto con ese texto."
        if not errores:
            try:
                db = get_db()
                db.execute("INSERT INTO conceptos (descripcion, activo) VALUES (?, ?)",
                           (datos["descripcion"], datos["activo"]))
                db.commit()
            except sqlite3.IntegrityError:
                errores["descripcion"] = "Ya existe un concepto con ese texto."
            else:
                flash("Concepto guardado.", "ok")
                if request.form.get("otro"):
                    return redirect(url_for("conceptos.nuevo"))
                return redirect(url_for("conceptos.lista"))
        return render_template("conceptos/form.html", concepto=datos, errores=errores, nuevo=True)

    return render_template("conceptos/form.html", concepto={"descripcion": "", "activo": 1},
                           errores={}, nuevo=True)


@bp.route("/<int:id>", methods=("GET", "POST"))
def editar(id):
    db = get_db()
    concepto = db.execute("SELECT * FROM conceptos WHERE id = ?", (id,)).fetchone()
    if concepto is None:
        abort(404)

    if request.method == "POST":
        datos, errores = validar_concepto(request.form)
        if not errores and existe_descripcion(datos["descripcion"], excepto_id=id):
            errores["descripcion"] = "Ya existe otro concepto con ese texto."
        if not errores:
            try:
                db.execute("UPDATE conceptos SET descripcion = ?, activo = ?, "
                           "modificado = datetime('now', 'localtime') WHERE id = ?",
                           (datos["descripcion"], datos["activo"], id))
                db.commit()
            except sqlite3.IntegrityError:
                errores["descripcion"] = "Ya existe otro concepto con ese texto."
            else:
                flash("Concepto actualizado.", "ok")
                return redirect(url_for("conceptos.lista"))
        datos["id"] = id
        return render_template("conceptos/form.html", concepto=datos, errores=errores, nuevo=False)

    return render_template("conceptos/form.html", concepto=dict(concepto), errores={}, nuevo=False)
