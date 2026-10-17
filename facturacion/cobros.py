"""Cobros: siempre por el total de cada factura. Un cobro puede pagar varias facturas del
mismo cliente (por ejemplo, una sola transferencia por tres facturas)."""
import uuid
from datetime import date

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from .db import get_db

bp = Blueprint("cobros", __name__, url_prefix="/cobros")

MEDIOS = ["Transferencia", "Efectivo", "Cheque", "E-cheq", "Depósito", "Otro"]


def facturas_pendientes(cliente_id):
    """Facturas del cliente que no están cobradas ni anuladas por una nota de crédito."""
    return get_db().execute(
        """SELECT f.* FROM facturas f
           WHERE f.cliente_id = ? AND f.cbte_tipo IN (1, 6)
             AND NOT EXISTS (SELECT 1 FROM cobro_facturas cf WHERE cf.factura_id = f.id)
             AND NOT EXISTS (SELECT 1 FROM facturas nc WHERE nc.asociado_id = f.id)
           ORDER BY f.fecha, f.id""", (cliente_id,)).fetchall()


def cobro_de(factura_id):
    """El cobro que pagó esta factura (o None)."""
    return get_db().execute(
        "SELECT c.* FROM cobros c JOIN cobro_facturas cf ON cf.cobro_id = c.id WHERE cf.factura_id = ?",
        (factura_id,)).fetchone()


def clientes_con_pendientes():
    return get_db().execute(
        """SELECT c.id, c.razon_social, COUNT(f.id) AS cantidad, SUM(f.total) AS total
           FROM clientes c JOIN facturas f ON f.cliente_id = c.id
           WHERE f.cbte_tipo IN (1, 6)
             AND NOT EXISTS (SELECT 1 FROM cobro_facturas cf WHERE cf.factura_id = f.id)
             AND NOT EXISTS (SELECT 1 FROM facturas nc WHERE nc.asociado_id = f.id)
           GROUP BY c.id ORDER BY c.razon_social COLLATE NOCASE""").fetchall()


@bp.route("/")
def lista():
    mes = request.args.get("mes") or ""
    sql = """SELECT c.*, cl.razon_social,
                    (SELECT COUNT(*) FROM cobro_facturas cf WHERE cf.cobro_id = c.id) AS cantidad
             FROM cobros c JOIN clientes cl ON cl.id = c.cliente_id"""
    params = []
    if mes:
        sql += " WHERE substr(c.fecha, 1, 7) = ?"
        params.append(mes)
    sql += " ORDER BY c.fecha DESC, c.id DESC"
    cobros = get_db().execute(sql, params).fetchall()
    return render_template("cobros/lista.html", cobros=cobros, mes=mes,
                           total=sum(c["total"] for c in cobros))


@bp.route("/nuevo", methods=("GET", "POST"))
def nuevo():
    db = get_db()
    form = request.form if request.method == "POST" else request.args
    cliente_id = form.get("cliente", type=int)
    elegidas = {int(x) for x in form.getlist("factura") if x.isdigit()}
    datos = {"fecha": form.get("fecha") or date.today().isoformat(),
             "medio": form.get("medio") or MEDIOS[0],
             "referencia": (form.get("referencia") or "").strip()[:100],
             "observaciones": (form.get("observaciones") or "").strip()[:1000],
             "token": form.get("token") or uuid.uuid4().hex}
    cliente = db.execute("SELECT * FROM clientes WHERE id = ?", (cliente_id,)).fetchone() \
        if cliente_id else None
    pendientes = facturas_pendientes(cliente_id) if cliente else []
    errores = []

    if request.method == "POST":
        repetido = db.execute("SELECT id FROM cobros WHERE token = ?", (datos["token"],)).fetchone()
        if repetido:  # se tocó "Registrar" dos veces
            return redirect(url_for("cobros.ver", id=repetido["id"]))
        a_cobrar = [f for f in pendientes if f["id"] in elegidas]
        if cliente is None:
            errores.append("Elegí el cliente.")
        elif not a_cobrar:
            errores.append("Marcá al menos una factura.")
        try:
            fecha = date.fromisoformat(datos["fecha"])
        except ValueError:
            fecha = None
            errores.append("Escribí la fecha del cobro.")
        if fecha and fecha > date.today():
            errores.append("La fecha del cobro no puede ser posterior a hoy.")
        if fecha and a_cobrar and datos["fecha"] < min(f["fecha"] for f in a_cobrar):
            errores.append("La fecha del cobro no puede ser anterior a las facturas que paga.")
        if datos["medio"] not in MEDIOS:
            errores.append("Elegí el medio de pago.")
        if not errores:
            total = sum(f["total"] for f in a_cobrar)
            cur = db.execute(
                "INSERT INTO cobros (cliente_id, fecha, medio, referencia, total, observaciones, token) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (cliente["id"], datos["fecha"], datos["medio"], datos["referencia"], total,
                 datos["observaciones"], datos["token"]))
            db.executemany("INSERT INTO cobro_facturas (cobro_id, factura_id, importe) VALUES (?, ?, ?)",
                           [(cur.lastrowid, f["id"], f["total"]) for f in a_cobrar])
            db.commit()
            flash(f"Cobro registrado: {len(a_cobrar)} factura(s) de {cliente['razon_social']}.", "ok")
            return redirect(url_for("cobros.ver", id=cur.lastrowid))

    return render_template("cobros/nuevo.html", cliente=cliente, pendientes=pendientes,
                           elegidas=elegidas, datos=datos, errores=errores, MEDIOS=MEDIOS,
                           clientes=clientes_con_pendientes())


@bp.route("/<int:id>")
def ver(id):
    db = get_db()
    cobro = db.execute("SELECT c.*, cl.razon_social FROM cobros c JOIN clientes cl ON cl.id = c.cliente_id "
                       "WHERE c.id = ?", (id,)).fetchone()
    if cobro is None:
        abort(404)
    facturas = db.execute("SELECT f.* FROM facturas f JOIN cobro_facturas cf ON cf.factura_id = f.id "
                          "WHERE cf.cobro_id = ? ORDER BY f.fecha, f.id", (id,)).fetchall()
    return render_template("cobros/ver.html", c=cobro, facturas=facturas)


@bp.route("/<int:id>/eliminar", methods=("POST",))
def eliminar(id):
    """Borra un cobro cargado por error: sus facturas vuelven a quedar pendientes."""
    db = get_db()
    cobro = db.execute("SELECT * FROM cobros WHERE id = ?", (id,)).fetchone()
    if cobro is None:
        abort(404)
    db.execute("DELETE FROM cobro_facturas WHERE cobro_id = ?", (id,))
    db.execute("DELETE FROM cobros WHERE id = ?", (id,))
    db.commit()
    flash("Cobro eliminado. Sus facturas volvieron a quedar pendientes.", "ok")
    return redirect(url_for("cobros.lista"))
