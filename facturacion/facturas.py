"""Facturas A y B (por ahora de prueba, sin CAE de ARCA).

La carga de una factura nueva sigue los mismos pasos que la web de ARCA (RCEL):
  1. Datos de emisión    (fecha, concepto, período facturado, vencimiento)
  2. Datos del receptor  (cliente y remito asociado)
  3. Datos de la operación (renglones)
  4. Resumen y confirmación
Los datos de todos los pasos viajan en el formulario (campos ocultos) hasta que se
confirma; recién ahí se guarda la factura.
"""
import sqlite3
import uuid
from datetime import date

from flask import (Blueprint, Response, abort, flash, redirect, render_template, request,
                   url_for)

from .db import get_db
from .importes import a_centavos, a_centesimos, calcular_totales, subtotal
from .validaciones import CONDICIONES_IVA, formatear_cuit, letra_factura, validar_cliente

bp = Blueprint("facturas", __name__, url_prefix="/facturas")

# Códigos de ARCA.
CBTE_TIPO = {"A": 1, "B": 6}
CONCEPTOS = {1: "Productos", 2: "Servicios", 3: "Productos y Servicios"}
CONDICION_VENTA = "Cuenta Corriente"  # la empresa siempre vende en cuenta corriente
# Puntos de venta habilitados en ARCA (se eligen en el paso 1, como en RCEL).
PUNTOS_VENTA = {2: "Av Los Quilmes 1856 - Bernal, Buenos Aires",
                3: "Av Los Quilmes 1856 - Bernal, Buenos Aires"}
REMITO_PTO_VTA = 1  # punto de venta habitual de los remitos (se puede cambiar en el paso 2)
# ARCA acepta la fecha de emisión hasta 5 días antes o después de hoy para productos
# y hasta 10 días para servicios.
DIAS_MARGEN = {1: 5, 2: 10, 3: 10}

PASOS = {1: "Datos de emisión", 2: "Datos del receptor", 3: "Datos de la operación",
         4: "Resumen"}
CAMPOS_PASO = {
    1: ("punto_venta", "fecha", "concepto", "serv_desde", "serv_hasta", "vto_pago"),
    2: ("cliente_id", "remito_pto_vta", "remito_numero", "remito_confirmado"),
    3: ("observaciones",),
}


def leer_fecha(texto):
    try:
        return date.fromisoformat(texto or "")
    except ValueError:
        return None


def ultima_factura(punto_venta, cbte_tipo, prueba=1):
    return get_db().execute(
        "SELECT numero, fecha FROM facturas WHERE punto_venta = ? AND cbte_tipo = ? AND prueba = ? "
        "ORDER BY numero DESC LIMIT 1", (punto_venta, cbte_tipo, prueba)
    ).fetchone()


def leer_formulario(form):
    """Junta los datos de todos los pasos que vienen en el formulario."""
    datos = {campo: (form.get(campo) or "").strip()
             for campos in CAMPOS_PASO.values() for campo in campos}
    datos["token"] = form.get("token") or uuid.uuid4().hex
    datos["renglones"] = [
        {"descripcion": " ".join(d.split()), "cantidad": c.strip(), "precio": p.strip()}
        for d, c, p in zip(form.getlist("descripcion"), form.getlist("cantidad"),
                           form.getlist("precio"))
    ]
    return datos


def datos_iniciales(cliente_id=None):
    hoy = date.today().isoformat()
    # Propone el punto de venta de la última factura (o el primero de la lista).
    ultima = get_db().execute("SELECT punto_venta FROM facturas ORDER BY id DESC LIMIT 1").fetchone()
    punto_venta = ultima["punto_venta"] if ultima and ultima["punto_venta"] in PUNTOS_VENTA \
        else next(iter(PUNTOS_VENTA))
    return {"token": uuid.uuid4().hex, "punto_venta": str(punto_venta), "fecha": hoy,
            "concepto": "3", "serv_desde": hoy, "serv_hasta": hoy, "vto_pago": hoy,
            "cliente_id": str(cliente_id or ""), "remito_pto_vta": str(REMITO_PTO_VTA),
            "remito_numero": "", "remito_confirmado": "", "observaciones": "",
            "renglones": []}


def numero_o_none(texto, maximo):
    """Convierte "00002" en 2. None si no es un número entre 1 y maximo."""
    texto = (texto or "").replace(" ", "")
    if not texto.isdigit() or not 1 <= int(texto) <= maximo:
        return None
    return int(texto)


# --- Validaciones de cada paso ----------------------------------------------------------

def validar_emision(datos):
    errores = {}
    if numero_o_none(datos["punto_venta"], 99998) not in PUNTOS_VENTA:
        errores["punto_venta"] = "Elegí el punto de venta."
    concepto = int(datos["concepto"]) if datos["concepto"].isdigit() else 0
    if concepto not in CONCEPTOS:
        errores["concepto"] = "Elegí qué se factura."
    fecha = leer_fecha(datos["fecha"])
    margen = DIAS_MARGEN.get(concepto, 5)
    if fecha is None:
        errores["fecha"] = "Escribí la fecha del comprobante."
    elif abs((fecha - date.today()).days) > margen:
        errores["fecha"] = f"ARCA solo acepta fechas hasta {margen} días antes o después de hoy."
    if concepto in (2, 3):
        desde, hasta, vto = (leer_fecha(datos[c]) for c in ("serv_desde", "serv_hasta", "vto_pago"))
        if desde is None or hasta is None:
            errores["serv_desde"] = "Completá el período facturado (desde y hasta)."
        elif desde > hasta:
            errores["serv_desde"] = "La fecha «Desde» no puede ser posterior a «Hasta»."
        if vto is None:
            errores["vto_pago"] = "Completá el vencimiento para el pago."
        elif fecha and vto < fecha:
            errores["vto_pago"] = "El vencimiento no puede ser anterior a la fecha del comprobante."
    return errores


def buscar_cliente(datos):
    if not datos["cliente_id"].isdigit():
        return None
    return get_db().execute("SELECT * FROM clientes WHERE id = ? AND activo = 1",
                            (int(datos["cliente_id"]),)).fetchone()


def factura_con_remito(pto_vta, numero):
    return get_db().execute(
        "SELECT * FROM facturas WHERE remito_pto_vta = ? AND remito_numero = ? ORDER BY id LIMIT 1",
        (pto_vta, numero)).fetchone()


def validar_receptor(datos):
    errores = {}
    cliente = buscar_cliente(datos)
    if cliente is None:
        errores["cliente_id"] = "Elegí el cliente."
    else:
        letra = letra_factura(cliente["condicion_iva"])
        punto_venta = numero_o_none(datos["punto_venta"], 99998)
        ultima = ultima_factura(punto_venta, CBTE_TIPO[letra]) if punto_venta else None
        if ultima and datos["fecha"] and datos["fecha"] < ultima["fecha"]:
            errores["cliente_id"] = (
                f"La fecha del comprobante (paso 1) no puede ser anterior a la última Factura {letra} "
                f"({date.fromisoformat(ultima['fecha']):%d/%m/%Y}). Volvé al paso 1 y cambiala.")

    if datos["remito_numero"]:
        pto_vta = numero_o_none(datos["remito_pto_vta"], 99998)
        numero = numero_o_none(datos["remito_numero"], 99999999)
        if pto_vta is None:
            errores["remito_numero"] = "El punto de venta del remito tiene que ser un número (por ejemplo 00001)."
        elif numero is None:
            errores["remito_numero"] = "Escribí solo el número del remito (hasta 8 números, sin guiones)."
        else:
            datos["remito_pto_vta"], datos["remito_numero"] = str(pto_vta), str(numero)
            anterior = factura_con_remito(pto_vta, numero)
            if anterior and not datos["remito_confirmado"]:
                errores["remito_numero"] = (
                    f"Este remito ya está en la Factura {anterior['letra']} N° {anterior['numero']} "
                    f"del {date.fromisoformat(anterior['fecha']):%d/%m/%Y} "
                    f"({anterior['cliente_razon_social']}).")
                errores["remito_repetido"] = True
    return cliente, errores


def validar_operacion(datos):
    """Devuelve (renglones_validos, errores)."""
    validos, mensajes = [], []
    cargados = [r for r in datos["renglones"] if r["descripcion"] or r["cantidad"] or r["precio"]]
    for n, r in enumerate(cargados, start=1):
        c = a_centesimos(r["cantidad"]) if r["cantidad"] else 100
        p = a_centavos(r["precio"])
        if not r["descripcion"]:
            mensajes.append(f"Línea {n}: falta el producto o servicio.")
        elif len(r["descripcion"]) > 1000:
            mensajes.append(f"Línea {n}: la descripción es demasiado larga.")
        if c is None or c <= 0:
            mensajes.append(f"Línea {n}: la cantidad no es válida.")
        if p is None or p < 0:
            mensajes.append(f"Línea {n}: el precio unitario no es válido "
                            "(escribilo sin IVA, por ejemplo 30.000,50).")
        if r["descripcion"] and c and c > 0 and p is not None and p >= 0:
            validos.append({"descripcion": r["descripcion"], "cantidad": c, "precio_unitario": p,
                            "subtotal": subtotal(c, p)})
    if not cargados:
        mensajes.append("Agregá al menos una línea con el producto o servicio.")
    elif not mensajes and calcular_totales(
            [(r["cantidad"], r["precio_unitario"]) for r in validos])["total"] <= 0:
        mensajes.append("El importe total tiene que ser mayor a cero.")
    if len(datos["observaciones"]) > 1000:
        mensajes.append("Las observaciones son demasiado largas.")
    return validos, ({"renglones": mensajes} if mensajes else {})


VALIDAR_PASO = {
    1: validar_emision,
    2: lambda d: validar_receptor(d)[1],
    3: lambda d: validar_operacion(d)[1],
}


# --- Guardado ---------------------------------------------------------------------------

def guardar_factura(datos, cliente, renglones):
    """Guarda la factura con el número siguiente. Devuelve el id.

    Si ya existe una factura con el mismo token (se tocó "Confirmar" dos veces),
    devuelve esa en lugar de crear otra.
    """
    db = get_db()
    letra = letra_factura(cliente["condicion_iva"])
    cbte_tipo = CBTE_TIPO[letra]
    totales = calcular_totales([(r["cantidad"], r["precio_unitario"]) for r in renglones])
    domicilio = " - ".join(x for x in (cliente["domicilio"], cliente["localidad"]) if x)
    concepto = int(datos["concepto"])
    servicio = concepto in (2, 3)

    # BEGIN IMMEDIATE bloquea la base mientras se asigna el número, así dos personas
    # facturando al mismo tiempo nunca obtienen el mismo número.
    db.execute("BEGIN IMMEDIATE")
    try:
        repetida = db.execute("SELECT id FROM facturas WHERE token = ?", (datos["token"],)).fetchone()
        if repetida:
            db.rollback()
            return repetida["id"]
        punto_venta = int(datos["punto_venta"])
        ultima = ultima_factura(punto_venta, cbte_tipo)
        numero = (ultima["numero"] if ultima else 0) + 1
        remito = int(datos["remito_numero"]) if datos["remito_numero"] else None
        cur = db.execute(
            """INSERT INTO facturas (cbte_tipo, letra, punto_venta, numero, prueba, fecha, concepto,
                   serv_desde, serv_hasta, vto_pago, condicion_venta, cliente_id,
                   cliente_razon_social, cliente_condicion_iva, cliente_tipo_doc, cliente_nro_doc,
                   cliente_domicilio, neto, iva, total, observaciones,
                   remito_pto_vta, remito_numero, token)
               VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (cbte_tipo, letra, punto_venta, numero, datos["fecha"], concepto,
             datos["serv_desde"] if servicio else None, datos["serv_hasta"] if servicio else None,
             datos["vto_pago"] if servicio else None, CONDICION_VENTA, cliente["id"],
             cliente["razon_social"], cliente["condicion_iva"], cliente["tipo_doc"],
             cliente["nro_doc"], domicilio, totales["neto"], totales["iva"], totales["total"],
             datos["observaciones"],
             int(datos["remito_pto_vta"]) if remito else None, remito, datos["token"]),
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
    return factura_id


def crear_cliente_rapido(form):
    """Alta de cliente desde el paso 2. Devuelve (cliente_id, datos_cliente, errores)."""
    datos, errores = validar_cliente({
        "razon_social": form.get("nc_razon_social"), "condicion_iva": form.get("nc_condicion_iva"),
        "tipo_doc": form.get("nc_tipo_doc"), "nro_doc": form.get("nc_nro_doc"),
        "domicilio": form.get("nc_domicilio"), "localidad": form.get("nc_localidad"),
        "email": form.get("nc_email"), "activo": "1",
    })
    if errores:
        return None, datos, errores
    campos = list(datos)
    try:
        db = get_db()
        cur = db.execute(f"INSERT INTO clientes ({', '.join(campos)}) "
                         f"VALUES ({', '.join('?' * len(campos))})", [datos[c] for c in campos])
        db.commit()
    except sqlite3.IntegrityError:
        return None, datos, {"nro_doc": "Ya existe un cliente con ese documento: buscalo en la lista."}
    return cur.lastrowid, datos, {}


# --- Pantallas --------------------------------------------------------------------------

@bp.route("/")
def lista():
    q = (request.args.get("q") or "").strip()
    mes = request.args.get("mes") or ""

    sql = "SELECT * FROM facturas WHERE 1=1"
    params = []
    if q.isdigit():
        # Un número busca por número de remito o de factura.
        sql += " AND (remito_numero = ? OR numero = ?)"
        params += [int(q), int(q)]
    else:
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
    errores, nuevo_cliente = {}, {}
    if request.method == "GET":
        datos, paso = datos_iniciales(request.args.get("cliente", type=int)), 1
    else:
        datos = leer_formulario(request.form)
        paso = request.form.get("paso", type=int) or 1
        accion = request.form.get("accion", "")

        if accion == "volver":
            paso = max(1, paso - 1)
        elif accion.startswith("ir_"):
            paso = min(paso, int(accion[3:]))  # solo permite volver a pasos anteriores
        elif accion == "crear_cliente":
            cliente_id, nuevo_cliente, errores_nc = crear_cliente_rapido(request.form)
            if cliente_id:
                datos["cliente_id"] = str(cliente_id)
                nuevo_cliente = {}
                flash(f"Cliente «{request.form.get('nc_razon_social', '').strip()}» cargado y elegido.", "ok")
            else:
                errores = {"nuevo_cliente": errores_nc}
        elif accion == "continuar" and paso in VALIDAR_PASO:
            errores = VALIDAR_PASO[paso](datos)
            if not errores:
                paso += 1
        elif accion == "confirmar":
            # Revisa todo de nuevo: puede haber cambiado algo desde que se cargó cada paso.
            for p in (1, 2, 3):
                errores = VALIDAR_PASO[p](datos)
                if errores:
                    paso = p
                    break
            else:
                cliente, _ = validar_receptor(datos)
                renglones, _ = validar_operacion(datos)
                factura_id = guardar_factura(datos, cliente, renglones)
                f = get_db().execute("SELECT * FROM facturas WHERE id = ?", (factura_id,)).fetchone()
                flash(f"Factura {f['letra']} N° {f['numero']} generada (de prueba).", "ok")
                return redirect(url_for("facturas.ver", id=factura_id))

    cliente = buscar_cliente(datos)
    renglones, _ = validar_operacion(datos) if paso == 4 else ([], {})
    if paso == 3:
        while len(datos["renglones"]) < 3:
            datos["renglones"].append({"descripcion": "", "cantidad": "", "precio": ""})

    clientes = get_db().execute(
        "SELECT * FROM clientes WHERE activo = 1 ORDER BY razon_social COLLATE NOCASE").fetchall()
    # Datos de los clientes para el buscador del paso 2 (lo usa factura.js).
    clientes_json = [{
        "id": c["id"], "razon_social": c["razon_social"], "nro_doc": c["nro_doc"],
        "condicion": CONDICIONES_IVA[c["condicion_iva"]], "letra": letra_factura(c["condicion_iva"]),
        "documento": (f"{c['tipo_doc']} {formatear_cuit(c['nro_doc']) if c['tipo_doc'] == 'CUIT' else c['nro_doc']}"
                      if c["tipo_doc"] != "SIN" else ""),
        "domicilio": " - ".join(x for x in (c["domicilio"], c["localidad"]) if x), "email": c["email"],
    } for c in clientes] if paso == 2 else []
    conceptos = get_db().execute(
        "SELECT descripcion FROM conceptos WHERE activo = 1 ORDER BY descripcion COLLATE NOCASE"
    ).fetchall()
    return render_template(
        "facturas/nueva.html", paso=paso, PASOS=PASOS, datos=datos, errores=errores,
        cliente=cliente, letra=letra_factura(cliente["condicion_iva"]) if cliente else "",
        clientes_json=clientes_json, conceptos=conceptos, renglones=renglones,
        totales=calcular_totales([(r["cantidad"], r["precio_unitario"]) for r in renglones]),
        nuevo_cliente=nuevo_cliente, CONCEPTOS=CONCEPTOS, CONDICION_VENTA=CONDICION_VENTA,
        PUNTOS_VENTA=PUNTOS_VENTA,
    )


@bp.route("/<int:id>")
def ver(id):
    db = get_db()
    factura = db.execute("SELECT * FROM facturas WHERE id = ?", (id,)).fetchone()
    if factura is None:
        abort(404)
    renglones = db.execute("SELECT * FROM factura_renglones WHERE factura_id = ? ORDER BY orden",
                           (id,)).fetchall()
    return render_template("facturas/ver.html", f=factura, renglones=renglones, CONCEPTOS=CONCEPTOS)


@bp.route("/<int:id>/pdf")
def pdf(id):
    """PDF como el de ARCA. ?copias=1 da solo el ORIGINAL (para mandar por mail)."""
    from .pdf import COPIAS, generar_pdf, nombre_archivo  # se carga solo al pedir un PDF

    db = get_db()
    factura = db.execute("SELECT * FROM facturas WHERE id = ?", (id,)).fetchone()
    if factura is None:
        abort(404)
    renglones = db.execute("SELECT * FROM factura_renglones WHERE factura_id = ? ORDER BY orden",
                           (id,)).fetchall()
    copias = COPIAS[:1] if request.args.get("copias") == "1" else COPIAS
    archivo = nombre_archivo(factura)
    return Response(generar_pdf(factura, renglones, copias), mimetype="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{archivo}"'})


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
