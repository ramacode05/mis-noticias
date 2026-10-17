"""Cuentas corrientes: saldo de cada cliente y sus movimientos (facturas, notas de crédito y
cobros) con el saldo acumulado, como un resumen de cuenta."""
from datetime import date

from flask import Blueprint, abort, render_template, request

from .cobros import facturas_pendientes
from .db import get_db

bp = Blueprint("cuentas", __name__, url_prefix="/cuentas")

NOMBRE_CBTE = {1: "Factura A", 6: "Factura B", 3: "Nota de Crédito A", 8: "Nota de Crédito B"}


def saldos(incluir_en_cero=False):
    """Una fila por cliente: facturado, notas de crédito, cobrado, saldo y deuda más vieja."""
    filas = get_db().execute(
        """SELECT c.id, c.razon_social,
             COALESCE((SELECT SUM(total) FROM facturas WHERE cliente_id = c.id AND cbte_tipo IN (1, 6)), 0)
               AS facturado,
             COALESCE((SELECT SUM(total) FROM facturas WHERE cliente_id = c.id AND cbte_tipo IN (3, 8)), 0)
               AS notas_credito,
             COALESCE((SELECT SUM(total) FROM cobros WHERE cliente_id = c.id), 0) AS cobrado,
             (SELECT MIN(f.fecha) FROM facturas f
                WHERE f.cliente_id = c.id AND f.cbte_tipo IN (1, 6)
                  AND NOT EXISTS (SELECT 1 FROM cobro_facturas cf WHERE cf.factura_id = f.id)
                  AND NOT EXISTS (SELECT 1 FROM facturas nc WHERE nc.asociado_id = f.id)) AS pendiente_desde,
             (SELECT COUNT(*) FROM facturas f
                WHERE f.cliente_id = c.id AND f.cbte_tipo IN (1, 6)
                  AND NOT EXISTS (SELECT 1 FROM cobro_facturas cf WHERE cf.factura_id = f.id)
                  AND NOT EXISTS (SELECT 1 FROM facturas nc WHERE nc.asociado_id = f.id)) AS pendientes
           FROM clientes c
           WHERE EXISTS (SELECT 1 FROM facturas WHERE cliente_id = c.id)
           ORDER BY c.razon_social COLLATE NOCASE""").fetchall()
    resultado = []
    for f in filas:
        fila = dict(f)
        fila["saldo"] = fila["facturado"] - fila["notas_credito"] - fila["cobrado"]
        fila["dias"] = (date.today() - date.fromisoformat(fila["pendiente_desde"])).days \
            if fila["pendiente_desde"] else None
        if fila["saldo"] or incluir_en_cero:
            resultado.append(fila)
    return resultado


def movimientos(cliente_id):
    """Facturas (suman), notas de crédito y cobros (restan), en orden, con saldo acumulado."""
    db = get_db()
    lista = []
    for f in db.execute("SELECT * FROM facturas WHERE cliente_id = ?", (cliente_id,)):
        es_nc = f["cbte_tipo"] in (3, 8)
        lista.append({
            "fecha": f["fecha"], "orden": (1 if es_nc else 0, f["id"]),
            "tipo": "nota_credito" if es_nc else "factura", "id": f["id"],
            "detalle": f"{NOMBRE_CBTE[f['cbte_tipo']]} {f['punto_venta']:05d}-{f['numero']:08d}",
            "remito": f["remito_numero"], "prueba": f["prueba"],
            "debe": 0 if es_nc else f["total"], "haber": f["total"] if es_nc else 0,
        })
    for c in db.execute("SELECT * FROM cobros WHERE cliente_id = ?", (cliente_id,)):
        detalle = f"Cobro ({c['medio']}{' ' + c['referencia'] if c['referencia'] else ''})"
        lista.append({"fecha": c["fecha"], "orden": (2, c["id"]), "tipo": "cobro", "id": c["id"],
                      "detalle": detalle, "remito": None, "prueba": 0, "debe": 0, "haber": c["total"]})
    lista.sort(key=lambda m: (m["fecha"], m["orden"]))
    saldo = 0
    for m in lista:
        saldo += m["debe"] - m["haber"]
        m["saldo"] = saldo
    return lista


@bp.route("/")
def lista():
    todos = request.args.get("todos") == "1"
    filas = saldos(incluir_en_cero=todos)
    return render_template("cuentas/lista.html", filas=filas, todos=todos,
                           total=sum(f["saldo"] for f in filas))


@bp.route("/<int:cliente_id>")
def cuenta(cliente_id):
    cliente = get_db().execute("SELECT * FROM clientes WHERE id = ?", (cliente_id,)).fetchone()
    if cliente is None:
        abort(404)
    movs = movimientos(cliente_id)
    pendientes = [dict(f, dias=(date.today() - date.fromisoformat(f["fecha"])).days)
                  for f in facturas_pendientes(cliente_id)]
    return render_template("cuentas/cuenta.html", cliente=cliente, movimientos=movs,
                           pendientes=pendientes, saldo=movs[-1]["saldo"] if movs else 0,
                           hoy=date.today().isoformat())
