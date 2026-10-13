"""Pantallas de clientes: listado con búsqueda, alta y edición."""
import sqlite3

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from .db import get_db
from .validaciones import (CONDICIONES_IVA, TIPOS_DOC, formatear_cuit,
                           letra_factura, solo_digitos, validar_cliente)

bp = Blueprint("clientes", __name__, url_prefix="/clientes")

CAMPOS = ("razon_social", "condicion_iva", "tipo_doc", "nro_doc", "domicilio",
          "localidad", "email", "telefono", "observaciones", "activo")


@bp.app_context_processor
def ayudas_plantillas():
    """Funciones y listas disponibles en todas las páginas."""
    return {
        "CONDICIONES_IVA": CONDICIONES_IVA,
        "TIPOS_DOC": TIPOS_DOC,
        "letra_factura": letra_factura,
        "formatear_doc": lambda c: formatear_cuit(c["nro_doc"]) if c["tipo_doc"] == "CUIT" else c["nro_doc"],
    }


@bp.route("/")
def lista():
    q = (request.args.get("q") or "").strip()
    ver_inactivos = request.args.get("inactivos") == "1"

    sql = "SELECT * FROM clientes WHERE 1=1"
    params = []
    if not ver_inactivos:
        sql += " AND activo = 1"
    if q:
        sql += " AND (razon_social LIKE ? OR email LIKE ? OR localidad LIKE ?"
        texto = f"%{q}%"
        params += [texto, texto, texto]
        digitos = solo_digitos(q)
        if digitos:
            sql += " OR nro_doc LIKE ?"
            params.append(f"%{digitos}%")
        sql += ")"
    sql += " ORDER BY razon_social COLLATE NOCASE"

    clientes = get_db().execute(sql, params).fetchall()
    return render_template("clientes/lista.html", clientes=clientes, q=q,
                           ver_inactivos=ver_inactivos)


@bp.route("/nuevo", methods=("GET", "POST"))
def nuevo():
    if request.method == "POST":
        datos, errores = validar_cliente(request.form)
        if not errores:
            try:
                db = get_db()
                db.execute(
                    f"INSERT INTO clientes ({', '.join(CAMPOS)}) "
                    f"VALUES ({', '.join('?' * len(CAMPOS))})",
                    [datos[c] for c in CAMPOS],
                )
                db.commit()
            except sqlite3.IntegrityError:
                errores["nro_doc"] = "Ya existe un cliente con ese documento."
            else:
                flash(f"Cliente «{datos['razon_social']}» guardado.", "ok")
                return redirect(url_for("clientes.lista"))
        return render_template("clientes/form.html", cliente=datos, errores=errores, nuevo=True)

    vacio = {c: "" for c in CAMPOS}
    vacio.update(condicion_iva="CF", tipo_doc="SIN", activo=1)
    return render_template("clientes/form.html", cliente=vacio, errores={}, nuevo=True)


@bp.route("/<int:id>", methods=("GET", "POST"))
def editar(id):
    db = get_db()
    cliente = db.execute("SELECT * FROM clientes WHERE id = ?", (id,)).fetchone()
    if cliente is None:
        abort(404)

    if request.method == "POST":
        datos, errores = validar_cliente(request.form)
        if not errores:
            try:
                db.execute(
                    f"UPDATE clientes SET {', '.join(c + ' = ?' for c in CAMPOS)}, "
                    "modificado = datetime('now', 'localtime') WHERE id = ?",
                    [datos[c] for c in CAMPOS] + [id],
                )
                db.commit()
            except sqlite3.IntegrityError:
                errores["nro_doc"] = "Ya existe otro cliente con ese documento."
            else:
                flash(f"Cliente «{datos['razon_social']}» actualizado.", "ok")
                return redirect(url_for("clientes.lista"))
        datos["id"] = id
        return render_template("clientes/form.html", cliente=datos, errores=errores, nuevo=False)

    return render_template("clientes/form.html", cliente=dict(cliente), errores={}, nuevo=False)
