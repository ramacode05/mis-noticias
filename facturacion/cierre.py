"""Cierre de mes: lo que entró contra lo que se gastó, y el beneficio de la empresa.

Igual que la planilla que usaba el usuario:
  Ingresos (verde)  = facturas del mes (con IVA, menos notas de crédito) + efectivo no facturado
  Gastos (rojo)     = facturas de proveedores del mes + gastos por categoría
  Resultado         = Ingresos - Gastos
  Humberto          = 21% del Resultado
  Beneficio         = Resultado - Humberto
"""
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from flask import Blueprint, Response, abort, flash, redirect, render_template, request, url_for

from .db import get_db
from .excel import Negrita, Pesos, libro
from .importes import a_centavos

bp = Blueprint("cierre", __name__, url_prefix="/cierre")

PORCENTAJE_HUMBERTO = Decimal("21")
MESES = ("Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre",
         "Octubre", "Noviembre", "Diciembre")
AVISO_VENCIMIENTO = 7  # días antes del vencimiento en que se avisa


def mes_de_pedido():
    mes = request.values.get("mes") or date.today().strftime("%Y-%m")
    try:
        date.fromisoformat(mes + "-01")
    except ValueError:
        mes = date.today().strftime("%Y-%m")
    return mes


def nombre_mes(mes):
    anio, numero = mes.split("-")
    return f"{MESES[int(numero) - 1]} {anio}"


def mes_vecino(mes, delta):
    anio, numero = map(int, mes.split("-"))
    numero += delta
    anio, numero = anio + (numero - 1) // 12, (numero - 1) % 12 + 1
    return f"{anio:04d}-{numero:02d}"


def leer_fecha(texto):
    try:
        return date.fromisoformat(texto or "")
    except ValueError:
        return None


def categorias(solo_activas=True):
    sql = "SELECT * FROM categorias_gasto"
    if solo_activas:
        sql += " WHERE activa = 1"
    return get_db().execute(sql + " ORDER BY orden, id").fetchall()


# --- Cálculos ----------------------------------------------------------------------------

def totales_mes(mes):
    """Todos los números del cierre de un mes."""
    db = get_db()
    ventas = db.execute(
        """SELECT COALESCE(SUM(CASE WHEN cbte_tipo IN (3, 8) THEN -total ELSE total END), 0) AS total,
                  COUNT(CASE WHEN cbte_tipo IN (1, 6) THEN 1 END) AS facturas,
                  COUNT(CASE WHEN cbte_tipo IN (3, 8) THEN 1 END) AS notas_credito,
                  COALESCE(SUM(prueba), 0) AS de_prueba
           FROM facturas WHERE substr(fecha, 1, 7) = ?""", (mes,)).fetchone()
    efectivo = db.execute("SELECT COALESCE(SUM(importe), 0) FROM ingresos_efectivo WHERE substr(fecha, 1, 7) = ?",
                          (mes,)).fetchone()[0]
    proveedores = db.execute("SELECT COALESCE(SUM(total), 0) FROM compras WHERE substr(fecha, 1, 7) = ?",
                             (mes,)).fetchone()[0]
    por_categoria = {fila["categoria_id"]: fila["importe"] for fila in db.execute(
        "SELECT categoria_id, importe FROM gastos_mes WHERE mes = ?", (mes,))}
    gastos_categorias = sum(por_categoria.values())

    ingresos = ventas["total"] + efectivo
    gastos = proveedores + gastos_categorias
    resultado = ingresos - gastos
    humberto = int((Decimal(resultado) * PORCENTAJE_HUMBERTO / 100).to_integral_value(ROUND_HALF_UP))
    return {
        "mes": mes, "ventas": ventas["total"], "facturas": ventas["facturas"],
        "notas_credito": ventas["notas_credito"], "hay_prueba": ventas["de_prueba"] > 0,
        "efectivo": efectivo, "ingresos": ingresos, "proveedores": proveedores,
        "por_categoria": por_categoria, "gastos_categorias": gastos_categorias, "gastos": gastos,
        "resultado": resultado, "humberto": humberto, "beneficio": resultado - humberto,
    }


def totales_anio(anio):
    meses = [totales_mes(f"{anio:04d}-{n:02d}") for n in range(1, 13)]
    suma = {k: sum(m[k] for m in meses) for k in ("ventas", "efectivo", "ingresos", "proveedores",
                                                    "gastos_categorias", "gastos", "resultado",
                                                    "humberto", "beneficio")}
    suma["por_categoria"] = {}
    for m in meses:
        for cat, importe in m["por_categoria"].items():
            suma["por_categoria"][cat] = suma["por_categoria"].get(cat, 0) + importe
    return meses, suma


# --- Pantallas ---------------------------------------------------------------------------

@bp.route("/")
def ver():
    mes = mes_de_pedido()
    db = get_db()
    hoy = date.today()
    compras = db.execute("SELECT * FROM compras WHERE substr(fecha, 1, 7) = ? ORDER BY fecha, id",
                         (mes,)).fetchall()
    # Facturas de proveedores sin pagar que vencen pronto (de cualquier mes).
    por_vencer = db.execute(
        "SELECT * FROM compras WHERE pagada IS NULL AND vencimiento IS NOT NULL AND vencimiento <= ? "
        "ORDER BY vencimiento", ((hoy + timedelta(days=AVISO_VENCIMIENTO)).isoformat(),)).fetchall()
    proveedores = [f["proveedor"] for f in db.execute(
        "SELECT proveedor FROM compras GROUP BY proveedor COLLATE NOCASE ORDER BY MAX(fecha) DESC LIMIT 200")]
    return render_template(
        "cierre/mes.html", mes=mes, nombre_mes=nombre_mes(mes), t=totales_mes(mes),
        anterior=mes_vecino(mes, -1), siguiente=mes_vecino(mes, 1), categorias=categorias(),
        efectivo=db.execute("SELECT * FROM ingresos_efectivo WHERE substr(fecha, 1, 7) = ? ORDER BY fecha, id",
                            (mes,)).fetchall(),
        compras=compras, por_vencer=por_vencer, proveedores=proveedores, hoy=hoy.isoformat(),
        fecha_sugerida=hoy.isoformat() if hoy.strftime("%Y-%m") == mes else f"{mes}-01")


def volver(mes, ancla=""):
    return redirect(url_for("cierre.ver", mes=mes, _anchor=ancla))


@bp.route("/gastos", methods=("POST",))
def guardar_gastos():
    """Guarda los importes de todas las categorías del mes (vacío = sin gasto)."""
    mes = mes_de_pedido()
    db = get_db()
    errores = []
    for cat in categorias():
        texto = (request.form.get(f"cat_{cat['id']}") or "").strip()
        if not texto:
            db.execute("DELETE FROM gastos_mes WHERE mes = ? AND categoria_id = ?", (mes, cat["id"]))
            continue
        importe = a_centavos(texto)
        if importe is None or importe < 0:
            errores.append(f"{cat['nombre']}: el importe no es válido.")
            continue
        db.execute("INSERT OR REPLACE INTO gastos_mes (mes, categoria_id, importe) VALUES (?, ?, ?)",
                   (mes, cat["id"], importe))
    db.commit()
    if errores:
        flash("Se guardó todo menos: " + " ".join(errores), "error")
    else:
        flash(f"Gastos de {nombre_mes(mes)} guardados.", "ok")
    return volver(mes, "gastos")


@bp.route("/efectivo", methods=("POST",))
def agregar_efectivo():
    mes = mes_de_pedido()
    fecha = leer_fecha(request.form.get("fecha"))
    importe = a_centavos(request.form.get("importe"))
    if fecha is None or importe is None or importe <= 0:
        flash("Para el efectivo hace falta la fecha y un importe mayor a cero.", "error")
        return volver(mes, "efectivo")
    db = get_db()
    db.execute("INSERT INTO ingresos_efectivo (fecha, detalle, importe) VALUES (?, ?, ?)",
               (fecha.isoformat(), (request.form.get("detalle") or "").strip()[:200], importe))
    db.commit()
    flash("Ingreso en efectivo agregado.", "ok")
    return volver(fecha.strftime("%Y-%m"), "efectivo")


@bp.route("/efectivo/<int:id>/eliminar", methods=("POST",))
def eliminar_efectivo(id):
    db = get_db()
    db.execute("DELETE FROM ingresos_efectivo WHERE id = ?", (id,))
    db.commit()
    flash("Ingreso en efectivo eliminado.", "ok")
    return volver(mes_de_pedido(), "efectivo")


@bp.route("/compras", methods=("POST",))
def agregar_compra():
    mes = mes_de_pedido()
    fecha = leer_fecha(request.form.get("fecha"))
    total = a_centavos(request.form.get("total"))
    proveedor = " ".join((request.form.get("proveedor") or "").split())[:200]
    vencimiento = leer_fecha(request.form.get("vencimiento"))
    if fecha is None or not proveedor or total is None or total <= 0:
        flash("Para la factura del proveedor hacen falta la fecha, el proveedor y el total.", "error")
        return volver(mes, "proveedores")
    db = get_db()
    db.execute("INSERT INTO compras (fecha, proveedor, numero, total, vencimiento, observaciones) "
               "VALUES (?, ?, ?, ?, ?, ?)",
               (fecha.isoformat(), proveedor, (request.form.get("numero") or "").strip()[:50], total,
                vencimiento.isoformat() if vencimiento else None,
                (request.form.get("observaciones") or "").strip()[:500]))
    db.commit()
    flash(f"Factura de {proveedor} agregada.", "ok")
    return volver(fecha.strftime("%Y-%m"), "proveedores")


@bp.route("/compras/<int:id>/pagada", methods=("POST",))
def marcar_pagada(id):
    db = get_db()
    compra = db.execute("SELECT * FROM compras WHERE id = ?", (id,)).fetchone()
    if compra is None:
        abort(404)
    nueva = None if compra["pagada"] else date.today().isoformat()
    db.execute("UPDATE compras SET pagada = ? WHERE id = ?", (nueva, id))
    db.commit()
    return volver(mes_de_pedido(), "proveedores")


@bp.route("/compras/<int:id>/eliminar", methods=("POST",))
def eliminar_compra(id):
    db = get_db()
    db.execute("DELETE FROM compras WHERE id = ?", (id,))
    db.commit()
    flash("Factura de proveedor eliminada.", "ok")
    return volver(mes_de_pedido(), "proveedores")


@bp.route("/categorias", methods=("GET", "POST"))
def editar_categorias():
    db = get_db()
    if request.method == "POST":
        for cat in categorias(solo_activas=False):
            nombre = " ".join((request.form.get(f"nombre_{cat['id']}") or "").split())[:60]
            orden = request.form.get(f"orden_{cat['id']}", type=int) or cat["orden"]
            activa = 1 if request.form.get(f"activa_{cat['id']}") else 0
            if nombre:
                db.execute("UPDATE categorias_gasto SET nombre = ?, orden = ?, activa = ? WHERE id = ?",
                           (nombre, orden, activa, cat["id"]))
        nueva = " ".join((request.form.get("nueva") or "").split())[:60]
        if nueva:
            maximo = db.execute("SELECT COALESCE(MAX(orden), 0) FROM categorias_gasto").fetchone()[0]
            db.execute("INSERT OR IGNORE INTO categorias_gasto (nombre, orden) VALUES (?, ?)", (nueva, maximo + 1))
        db.commit()
        flash("Categorías guardadas.", "ok")
        return redirect(url_for("cierre.editar_categorias", mes=request.values.get("mes", "")))
    return render_template("cierre/categorias.html", categorias=categorias(solo_activas=False),
                           mes=request.values.get("mes", ""))


@bp.route("/anual")
def anual():
    anio = request.args.get("anio", type=int) or date.today().year
    meses, suma = totales_anio(anio)
    return render_template("cierre/anual.html", anio=anio, meses=meses, suma=suma, MESES=MESES,
                           categorias=categorias(solo_activas=False))


@bp.route("/anual/excel")
def anual_excel():
    anio = request.args.get("anio", type=int) or date.today().year
    meses, suma = totales_anio(anio)
    cats = [c for c in categorias(solo_activas=False)
            if c["activa"] or suma["por_categoria"].get(c["id"])]
    titulos = ["Mes"] + [c["nombre"] for c in cats] + [
        "Proveedores", "Total gastos", "Facturado", "Efectivo", "Total ingresos", "Resultado",
        "Humberto (21%)", "Beneficio"]
    filas = [[Negrita(f"Cierre {anio}")], [], [Negrita(t) for t in titulos]]
    for nombre, m in zip(MESES, meses):
        filas.append([nombre] + [Pesos(m["por_categoria"].get(c["id"], 0)) for c in cats] + [
            Pesos(m[k]) for k in ("proveedores", "gastos", "ventas", "efectivo", "ingresos", "resultado",
                                  "humberto", "beneficio")])
    filas.append([Negrita("Anual")] + [Pesos(suma["por_categoria"].get(c["id"], 0)) for c in cats] + [
        Pesos(suma[k]) for k in ("proveedores", "gastos", "ventas", "efectivo", "ingresos", "resultado",
                                 "humberto", "beneficio")])
    return Response(libro([(f"Cierre {anio}", filas)]),
                    mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="cierre_{anio}.xlsx"'})
