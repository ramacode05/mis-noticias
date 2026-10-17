"""Resumen mensual: ventas por tipo de comprobante (neto, IVA, total), detalle de los
comprobantes (como un libro IVA Ventas) y cobros del mes. Se puede bajar en Excel."""
from datetime import date

from flask import Blueprint, Response, render_template, request

from .db import get_db
from .excel import Negrita, Pesos, libro
from .validaciones import CONDICIONES_IVA, formatear_cuit

bp = Blueprint("resumen", __name__, url_prefix="/resumen")

NOMBRE_CBTE = {1: "Factura A", 3: "Nota de Crédito A", 6: "Factura B", 8: "Nota de Crédito B"}
ORDEN_TIPOS = (1, 3, 6, 8)
MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
         "octubre", "noviembre", "diciembre")


def mes_elegido():
    mes = request.args.get("mes") or date.today().strftime("%Y-%m")
    try:
        date.fromisoformat(mes + "-01")
    except ValueError:
        mes = date.today().strftime("%Y-%m")
    return mes


def nombre_mes(mes):
    anio, numero = mes.split("-")
    return f"{MESES[int(numero) - 1]} {anio}"


def datos_del_mes(mes):
    db = get_db()
    comprobantes = db.execute(
        "SELECT * FROM facturas WHERE substr(fecha, 1, 7) = ? ORDER BY fecha, cbte_tipo, punto_venta, numero",
        (mes,)).fetchall()
    por_tipo = []
    for tipo in ORDEN_TIPOS:
        del_tipo = [c for c in comprobantes if c["cbte_tipo"] == tipo]
        if del_tipo:
            signo = -1 if tipo in (3, 8) else 1
            por_tipo.append({"nombre": NOMBRE_CBTE[tipo], "cantidad": len(del_tipo),
                             "neto": signo * sum(c["neto"] for c in del_tipo),
                             "iva": signo * sum(c["iva"] for c in del_tipo),
                             "total": signo * sum(c["total"] for c in del_tipo)})
    totales = {k: sum(t[k] for t in por_tipo) for k in ("neto", "iva", "total")}
    cobros = db.execute(
        "SELECT c.*, cl.razon_social FROM cobros c JOIN clientes cl ON cl.id = c.cliente_id "
        "WHERE substr(c.fecha, 1, 7) = ? ORDER BY c.fecha, c.id", (mes,)).fetchall()
    return {"comprobantes": comprobantes, "por_tipo": por_tipo, "totales": totales, "cobros": cobros,
            "total_cobrado": sum(c["total"] for c in cobros),
            "hay_prueba": any(c["prueba"] for c in comprobantes)}


def documento(c):
    if c["cliente_tipo_doc"] == "CUIT":
        return formatear_cuit(c["cliente_nro_doc"])
    return c["cliente_nro_doc"] or ""


@bp.route("/")
def ver():
    mes = mes_elegido()
    return render_template("resumen.html", mes=mes, nombre_mes=nombre_mes(mes), d=datos_del_mes(mes),
                           NOMBRE_CBTE=NOMBRE_CBTE, documento=documento)


@bp.route("/excel")
def excel():
    mes = mes_elegido()
    d = datos_del_mes(mes)
    titulo = f"Resumen de {nombre_mes(mes)}"

    resumen = [[Negrita(titulo)], [],
               [Negrita("Ventas"), Negrita("Cantidad"), Negrita("Neto gravado"), Negrita("IVA 21%"),
                Negrita("Total")]]
    for t in d["por_tipo"]:
        resumen.append([t["nombre"], t["cantidad"], Pesos(t["neto"]), Pesos(t["iva"]), Pesos(t["total"])])
    resumen.append([Negrita("Total del mes"), "", Pesos(d["totales"]["neto"]), Pesos(d["totales"]["iva"]),
                    Pesos(d["totales"]["total"])])
    resumen += [[], [Negrita("Cobrado en el mes"), len(d["cobros"]), "", "", Pesos(d["total_cobrado"])]]
    if d["hay_prueba"]:
        resumen += [[], ["Atención: incluye comprobantes de PRUEBA (sin validez fiscal)."]]

    comprobantes = [[Negrita(x) for x in ("Fecha", "Tipo", "Punto de venta", "Número", "Cliente",
                                          "Condición IVA", "CUIT / Documento", "Neto gravado",
                                          "IVA 21%", "Total", "CAE", "Prueba")]]
    for c in d["comprobantes"]:
        signo = -1 if c["cbte_tipo"] in (3, 8) else 1
        comprobantes.append([
            date.fromisoformat(c["fecha"]).strftime("%d/%m/%Y"), NOMBRE_CBTE[c["cbte_tipo"]],
            c["punto_venta"], c["numero"], c["cliente_razon_social"],
            CONDICIONES_IVA.get(c["cliente_condicion_iva"], c["cliente_condicion_iva"]),
            documento(c), Pesos(signo * c["neto"]), Pesos(signo * c["iva"]), Pesos(signo * c["total"]),
            c["cae"] or "", "Sí" if c["prueba"] else ""])

    cobros = [[Negrita(x) for x in ("Fecha", "Cliente", "Medio", "Referencia", "Total")]]
    for c in d["cobros"]:
        cobros.append([date.fromisoformat(c["fecha"]).strftime("%d/%m/%Y"), c["razon_social"],
                       c["medio"], c["referencia"], Pesos(c["total"])])

    datos = libro([("Resumen", resumen), ("Comprobantes", comprobantes), ("Cobros", cobros)])
    return Response(datos, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="resumen_{mes}.xlsx"'})
