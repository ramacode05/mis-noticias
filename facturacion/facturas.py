"""Facturas A y B (por ahora de prueba, sin CAE de ARCA)."""
from datetime import date

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from .configuracion import leer_config
from .db import get_db
from .importes import a_centavos, a_centesimos, calcular_totales, subtotal
from .validaciones import letra_factura

bp = Blueprint("facturas", __name__, url_prefix="/facturas")

# Códigos de ARCA.
CBTE_TIPO = {"A": 1, "B": 6}
CONCEPTOS = {1: "Productos", 2: "Servicios", 3: "Productos y Servicios"}
CONDICIONES_VENTA = [
    "Cuenta Corriente", "Contado", "Transferencia Bancaria", "Cheque",
    "Tarjeta de Débito", "Tarjeta de Crédito", "Otra",
]
# ARCA acepta la fecha de emisión hasta 5 días antes o después de hoy para productos
# y hasta 10 días para servicios.
DIAS_MARGEN = {1: 5, 2: 10, 3: 10}


def leer_fecha(texto):
    try:
        return date.fromisoformat(texto or "")
    except ValueError:
        return None


def clientes_activos():
    return get_db().execute(
        "SELECT * FROM clientes WHERE activo = 1 ORDER BY razon_social COLLATE NOCASE"
    ).fetchall()


def conceptos_activos():
    return get_db().execute(
        "SELECT descripcion FROM conceptos WHERE activo = 1 ORDER BY descripcion COLLATE NOCASE"
    ).fetchall()


def ultima_factura(punto_venta, cbte_tipo, prueba=1):
    return get_db().execute(
        "SELECT numero, fecha FROM facturas WHERE punto_venta = ? AND cbte_tipo = ? AND prueba = ? "
        "ORDER BY numero DESC LIMIT 1", (punto_venta, cbte_tipo, prueba)
    ).fetchone()


def leer_renglones(form):
    """Lee los renglones del formulario. Devuelve (renglones_tal_cual, renglones_validos, errores)."""
    descripciones = form.getlist("descripcion")
    cantidades = form.getlist("cantidad")
    precios = form.getlist("precio")
    crudos, validos, errores = [], [], []
    for n, (desc, cant, precio) in enumerate(zip(descripciones, cantidades, precios), start=1):
        desc = " ".join(desc.split())
        if not (desc or cant.strip() or precio.strip()):
            continue  # renglón vacío: se ignora
        crudos.append({"descripcion": desc, "cantidad": cant.strip(), "precio": precio.strip()})
        c = a_centesimos(cant) if cant.strip() else 100
        p = a_centavos(precio)
        if not desc:
            errores.append(f"Renglón {n}: falta la descripción.")
        elif len(desc) > 1000:
            errores.append(f"Renglón {n}: la descripción es demasiado larga.")
        if c is None or c <= 0:
            errores.append(f"Renglón {n}: la cantidad no es válida.")
        if p is None or p < 0:
            errores.append(f"Renglón {n}: el precio no es válido (escribilo sin IVA, por ejemplo 30.000,50).")
        if desc and c and c > 0 and p is not None and p >= 0:
            validos.append({"descripcion": desc, "cantidad": c, "precio_unitario": p,
                            "subtotal": subtotal(c, p)})
    if not crudos:
        errores.append("Agregá al menos un renglón al detalle.")
    return crudos, validos, errores


def validar_factura(form):
    """Devuelve (datos, renglones, crudos, errores). errores: dict campo -> mensaje."""
    errores = {}
    datos = {
        "cliente_id": form.get("cliente_id", type=int),
        "fecha": form.get("fecha", ""),
        "concepto": form.get("concepto", type=int) or 3,
        "serv_desde": form.get("serv_desde", ""),
        "serv_hasta": form.get("serv_hasta", ""),
        "vto_pago": form.get("vto_pago", ""),
        "condicion_venta": form.get("condicion_venta", ""),
        "observaciones": (form.get("observaciones") or "").strip(),
    }

    cliente = None
    if datos["cliente_id"]:
        cliente = get_db().execute("SELECT * FROM clientes WHERE id = ? AND activo = 1",
                                   (datos["cliente_id"],)).fetchone()
    if cliente is None:
        errores["cliente_id"] = "Elegí el cliente."

    if datos["concepto"] not in CONCEPTOS:
        errores["concepto"] = "Elegí qué se factura."
    if datos["condicion_venta"] not in CONDICIONES_VENTA:
        errores["condicion_venta"] = "Elegí la condición de venta."

    fecha = leer_fecha(datos["fecha"])
    hoy = date.today()
    margen = DIAS_MARGEN.get(datos["concepto"], 5)
    if fecha is None:
        errores["fecha"] = "Escribí la fecha de la factura."
    elif abs((fecha - hoy).days) > margen:
        errores["fecha"] = f"ARCA solo acepta fechas hasta {margen} días antes o después de hoy."
    elif cliente is not None:
        letra = letra_factura(cliente["condicion_iva"])
        ultima = ultima_factura(int(leer_config("punto_venta")), CBTE_TIPO[letra])
        if ultima and datos["fecha"] < ultima["fecha"]:
            errores["fecha"] = (f"La fecha no puede ser anterior a la última Factura {letra} "
                                f"({date.fromisoformat(ultima['fecha']):%d/%m/%Y}).")

    if datos["concepto"] in (2, 3):
        desde, hasta, vto = (leer_fecha(datos[c]) for c in ("serv_desde", "serv_hasta", "vto_pago"))
        if desde is None or hasta is None:
            errores["serv_desde"] = "Completá el período del servicio (desde y hasta)."
        elif desde > hasta:
            errores["serv_desde"] = "La fecha «desde» no puede ser posterior a «hasta»."
        if vto is None:
            errores["vto_pago"] = "Completá el vencimiento del pago."
        elif fecha and vto < fecha:
            errores["vto_pago"] = "El vencimiento no puede ser anterior a la fecha de la factura."
    else:
        datos.update(serv_desde="", serv_hasta="", vto_pago="")

    crudos, renglones, errores_renglones = leer_renglones(form)
    if errores_renglones:
        errores["renglones"] = errores_renglones
    elif calcular_totales([(r["cantidad"], r["precio_unitario"]) for r in renglones])["total"] <= 0:
        errores["renglones"] = ["El total de la factura tiene que ser mayor a cero."]

    return datos, cliente, renglones, crudos, errores


def guardar_factura(datos, cliente, renglones):
    """Guarda la factura con el número siguiente. Devuelve el id."""
    db = get_db()
    letra = letra_factura(cliente["condicion_iva"])
    cbte_tipo = CBTE_TIPO[letra]
    totales = calcular_totales([(r["cantidad"], r["precio_unitario"]) for r in renglones])
    domicilio = ", ".join(x for x in (cliente["domicilio"], cliente["localidad"]) if x)

    # BEGIN IMMEDIATE bloquea la base mientras se asigna el número, así dos personas
    # facturando al mismo tiempo nunca obtienen el mismo número.
    db.execute("BEGIN IMMEDIATE")
    try:
        punto_venta = int(leer_config("punto_venta"))
        ultima = ultima_factura(punto_venta, cbte_tipo)
        numero = (ultima["numero"] if ultima else 0) + 1
        cur = db.execute(
            """INSERT INTO facturas (cbte_tipo, letra, punto_venta, numero, prueba, fecha, concepto,
                   serv_desde, serv_hasta, vto_pago, condicion_venta, cliente_id,
                   cliente_razon_social, cliente_condicion_iva, cliente_tipo_doc, cliente_nro_doc,
                   cliente_domicilio, neto, iva, total, observaciones)
               VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (cbte_tipo, letra, punto_venta, numero, datos["fecha"], datos["concepto"],
             datos["serv_desde"] or None, datos["serv_hasta"] or None, datos["vto_pago"] or None,
             datos["condicion_venta"], cliente["id"], cliente["razon_social"],
             cliente["condicion_iva"], cliente["tipo_doc"], cliente["nro_doc"], domicilio,
             totales["neto"], totales["iva"], totales["total"], datos["observaciones"]),
        )
        factura_id = cur.lastrowid
        db.executemany(
            "INSERT INTO factura_renglones (factura_id, orden, descripcion, cantidad, "
            "precio_unitario, subtotal) VALUES (?, ?, ?, ?, ?, ?)",
            [(factura_id, i, r["descripcion"], r["cantidad"], r["precio_unitario"], r["subtotal"])
             for i, r in enumerate(renglones, start=1)],
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return factura_id, letra, numero


@bp.route("/")
def lista():
    q = (request.args.get("q") or "").strip()
    mes = request.args.get("mes") or ""

    sql = "SELECT * FROM facturas WHERE 1=1"
    params = []
    for palabra in q.split():
        sql += " AND cliente_razon_social LIKE ?"
        params.append(f"%{palabra}%")
    if mes:
        sql += " AND substr(fecha, 1, 7) = ?"
        params.append(mes)
    sql += " ORDER BY fecha DESC, id DESC"

    facturas = get_db().execute(sql, params).fetchall()
    return render_template("facturas/lista.html", facturas=facturas, q=q, mes=mes,
                           total=sum(f["total"] for f in facturas))


@bp.route("/nueva", methods=("GET", "POST"))
def nueva():
    if request.method == "POST":
        datos, cliente, renglones, crudos, errores = validar_factura(request.form)
        if not errores:
            factura_id, letra, numero = guardar_factura(datos, cliente, renglones)
            flash(f"Factura {letra} N° {numero} guardada (de prueba).", "ok")
            return redirect(url_for("facturas.ver", id=factura_id))
    else:
        hoy = date.today().isoformat()
        datos = {"cliente_id": request.args.get("cliente", type=int), "fecha": hoy,
                 "concepto": 3, "serv_desde": hoy, "serv_hasta": hoy, "vto_pago": hoy,
                 "condicion_venta": "Cuenta Corriente", "observaciones": ""}
        crudos, errores = [], {}

    while len(crudos) < 3:
        crudos.append({"descripcion": "", "cantidad": "", "precio": ""})

    return render_template("facturas/nueva.html", datos=datos, renglones=crudos, errores=errores,
                           clientes=clientes_activos(), conceptos=conceptos_activos(),
                           CONCEPTOS=CONCEPTOS, CONDICIONES_VENTA=CONDICIONES_VENTA,
                           punto_venta=int(leer_config("punto_venta")))


@bp.route("/<int:id>")
def ver(id):
    db = get_db()
    factura = db.execute("SELECT * FROM facturas WHERE id = ?", (id,)).fetchone()
    if factura is None:
        abort(404)
    renglones = db.execute("SELECT * FROM factura_renglones WHERE factura_id = ? ORDER BY orden",
                           (id,)).fetchall()
    return render_template("facturas/ver.html", f=factura, renglones=renglones, CONCEPTOS=CONCEPTOS)


@bp.route("/<int:id>/eliminar", methods=("POST",))
def eliminar(id):
    """Solo se pueden eliminar facturas de prueba. Las reales se anulan con nota de crédito."""
    db = get_db()
    factura = db.execute("SELECT * FROM facturas WHERE id = ?", (id,)).fetchone()
    if factura is None:
        abort(404)
    if not factura["prueba"]:
        flash("Las facturas reales no se pueden eliminar: se anulan con una nota de crédito.", "error")
        return redirect(url_for("facturas.ver", id=id))
    db.execute("DELETE FROM factura_renglones WHERE factura_id = ?", (id,))
    db.execute("DELETE FROM facturas WHERE id = ?", (id,))
    db.commit()
    flash(f"Factura de prueba {factura['letra']} N° {factura['numero']} eliminada.", "ok")
    return redirect(url_for("facturas.lista"))
