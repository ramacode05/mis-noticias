"""Facturas A y B y notas de crédito.

Si la conexión con ARCA está activa (pantalla ARCA), al confirmar se pide el CAE a ARCA y el
número lo da ARCA. Si no, son facturas de prueba del sistema (numeradas por el sistema).

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

from . import arca, arca_web, mail
from .cobros import cobro_de
from .db import get_db
from .importes import a_centavos, a_centesimos, calcular_totales, subtotal
from .validaciones import CONDICIONES_IVA, formatear_cuit, letra_factura, validar_cliente

bp = Blueprint("facturas", __name__, url_prefix="/facturas")

# Códigos de ARCA.
CBTE_TIPO = {"A": 1, "B": 6}
NC_TIPO = {"A": 3, "B": 8}  # notas de crédito
NOMBRE_CBTE = {1: "Factura A", 6: "Factura B", 3: "Nota de Crédito A", 8: "Nota de Crédito B"}
CONCEPTOS = {1: "Productos", 2: "Servicios", 3: "Productos y Servicios"}
CONDICION_VENTA = "Cuenta Corriente"  # la empresa siempre vende en cuenta corriente
# Puntos de venta de la web de ARCA (se eligen en el paso 1, como en RCEL). Se usan para las
# facturas de prueba del sistema. Con la conexión a ARCA activa se usa el punto de venta de
# web services configurado en la pantalla ARCA (ARCA no deja usar estos por web services).
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


def es_nota_credito(f):
    return f["cbte_tipo"] in NC_TIPO.values()


def nota_credito_de(factura_id):
    """La nota de crédito que anula esta factura (o None)."""
    return get_db().execute("SELECT * FROM facturas WHERE asociado_id = ? ORDER BY id LIMIT 1",
                            (factura_id,)).fetchone()


def puntos_venta():
    """Los puntos de venta que se ofrecen en el paso 1 según el modo (prueba o ARCA)."""
    ambiente = arca_web.ambiente_activo()
    if ambiente:
        etiqueta = "Web services ARCA" + (" - HOMOLOGACIÓN (prueba)" if ambiente == "homologacion" else "")
        return {arca_web.punto_venta(ambiente): etiqueta}
    return PUNTOS_VENTA


def ultima_factura(punto_venta, cbte_tipo, prueba=1, ambiente=None):
    """El último comprobante de ese tipo y punto de venta, en el mismo modo (prueba o ARCA)."""
    return get_db().execute(
        "SELECT numero, fecha FROM facturas WHERE punto_venta = ? AND cbte_tipo = ? AND prueba = ? "
        "AND COALESCE(arca, '') = ? ORDER BY numero DESC LIMIT 1",
        (punto_venta, cbte_tipo, prueba, ambiente or "")
    ).fetchone()


def modo_actual():
    """(prueba, ambiente) para los comprobantes nuevos."""
    ambiente = arca_web.ambiente_activo()
    return (0 if ambiente == "produccion" else 1), ambiente


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
    opciones = puntos_venta()
    ultima = get_db().execute("SELECT punto_venta FROM facturas ORDER BY id DESC LIMIT 1").fetchone()
    punto_venta = ultima["punto_venta"] if ultima and ultima["punto_venta"] in opciones \
        else next(iter(opciones))
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
    if numero_o_none(datos["punto_venta"], 99998) not in puntos_venta():
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
        prueba, ambiente = modo_actual()
        ultima = ultima_factura(punto_venta, CBTE_TIPO[letra], prueba, ambiente) if punto_venta else None
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

CAMPOS_COMPROBANTE = (
    "cbte_tipo", "letra", "punto_venta", "numero", "prueba", "arca", "fecha", "concepto",
    "serv_desde", "serv_hasta", "vto_pago", "condicion_venta", "cliente_id", "cliente_razon_social",
    "cliente_condicion_iva", "cliente_tipo_doc", "cliente_nro_doc", "cliente_domicilio", "neto",
    "iva", "total", "observaciones", "remito_pto_vta", "remito_numero", "token", "asociado_id",
    "cae", "cae_vto")


def insertar_comprobante(db, c, renglones):
    """Guarda el comprobante (dict con CAMPOS_COMPROBANTE) y sus renglones. Devuelve el id."""
    cur = db.execute(f"INSERT INTO facturas ({', '.join(CAMPOS_COMPROBANTE)}) "
                     f"VALUES ({', '.join('?' * len(CAMPOS_COMPROBANTE))})",
                     [c.get(campo) for campo in CAMPOS_COMPROBANTE])
    db.executemany(
        "INSERT INTO factura_renglones (factura_id, orden, descripcion, cantidad, "
        "precio_unitario, subtotal) VALUES (?, ?, ?, ?, ?, ?)",
        [(cur.lastrowid, i, r["descripcion"], r["cantidad"], r["precio_unitario"], r["subtotal"])
         for i, r in enumerate(renglones, start=1)])
    return cur.lastrowid


def numerar_y_autorizar(db, c, asociada=None):
    """Completa número (y CAE si corresponde) en el comprobante c.

    Con ARCA: el número y el CAE los da ARCA (lanza arca.ErrorArca si lo rechaza).
    Sin ARCA: número siguiente del sistema.
    """
    if c["arca"]:
        respuesta = arca_web.emitir(c["arca"], c, asociada)
        c.update(numero=respuesta["numero"], cae=respuesta["cae"], cae_vto=respuesta["cae_vto"])
        return respuesta["observaciones"]
    ultima = ultima_factura(c["punto_venta"], c["cbte_tipo"], c["prueba"], c["arca"])
    c["numero"] = (ultima["numero"] if ultima else 0) + 1
    return []


def guardar_factura(datos, cliente, renglones):
    """Guarda la factura con el número siguiente (pidiendo el CAE a ARCA si está conectado).

    Devuelve (id, observaciones_de_arca). Si ya existe una factura con el mismo token (se tocó
    "Confirmar" dos veces), devuelve esa en lugar de crear otra.
    """
    db = get_db()
    letra = letra_factura(cliente["condicion_iva"])
    totales = calcular_totales([(r["cantidad"], r["precio_unitario"]) for r in renglones])
    concepto = int(datos["concepto"])
    servicio = concepto in (2, 3)
    prueba, ambiente = modo_actual()
    remito = int(datos["remito_numero"]) if datos["remito_numero"] else None
    c = {
        "cbte_tipo": CBTE_TIPO[letra], "letra": letra, "punto_venta": int(datos["punto_venta"]),
        "prueba": prueba, "arca": ambiente, "fecha": datos["fecha"], "concepto": concepto,
        "serv_desde": datos["serv_desde"] if servicio else None,
        "serv_hasta": datos["serv_hasta"] if servicio else None,
        "vto_pago": datos["vto_pago"] if servicio else None,
        "condicion_venta": CONDICION_VENTA, "cliente_id": cliente["id"],
        "cliente_razon_social": cliente["razon_social"], "cliente_condicion_iva": cliente["condicion_iva"],
        "cliente_tipo_doc": cliente["tipo_doc"], "cliente_nro_doc": cliente["nro_doc"],
        "cliente_domicilio": " - ".join(x for x in (cliente["domicilio"], cliente["localidad"]) if x),
        "neto": totales["neto"], "iva": totales["iva"], "total": totales["total"],
        "observaciones": datos["observaciones"],
        "remito_pto_vta": int(datos["remito_pto_vta"]) if remito else None, "remito_numero": remito,
        "token": datos["token"],
    }
    # BEGIN IMMEDIATE bloquea la base mientras se asigna el número, así nunca se repite.
    db.execute("BEGIN IMMEDIATE")
    try:
        repetida = db.execute("SELECT id FROM facturas WHERE token = ?", (datos["token"],)).fetchone()
        if repetida:
            db.rollback()
            return repetida["id"], []
        observaciones = numerar_y_autorizar(db, c)
        factura_id = insertar_comprobante(db, c, renglones)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return factura_id, observaciones


def mensaje_emitida(f):
    if f["arca"] == "produccion":
        return f"autorizada por ARCA. CAE {f['cae']}."
    if f["arca"] == "homologacion":
        return f"autorizada por ARCA en HOMOLOGACIÓN (prueba, sin validez fiscal). CAE {f['cae']}."
    return "generada (de prueba)."


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
    # Facturas anuladas por una nota de crédito (para marcarlas en la lista).
    anuladas = {fila["asociado_id"]: fila for fila in get_db().execute(
        "SELECT asociado_id, punto_venta, numero, letra FROM facturas WHERE asociado_id IS NOT NULL")}
    cobradas = {fila["factura_id"] for fila in get_db().execute("SELECT factura_id FROM cobro_facturas")}
    total = sum(-f["total"] if es_nota_credito(f) else f["total"] for f in facturas)
    return render_template("facturas/lista.html", facturas=facturas, q=q, mes=mes, total=total,
                           anuladas=anuladas, cobradas=cobradas, es_nota_credito=es_nota_credito)


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
                try:
                    factura_id, observaciones = guardar_factura(datos, cliente, renglones)
                except arca.ErrorArca as error:
                    errores = {"arca": str(error)}
                else:
                    f = get_db().execute("SELECT * FROM facturas WHERE id = ?", (factura_id,)).fetchone()
                    flash(f"Factura {f['letra']} N° {f['numero']} " + mensaje_emitida(f), "ok")
                    for obs in observaciones:
                        flash(f"Observación de ARCA: {obs}", "aviso")
                    envio = mail.enviar_si_corresponde(factura_id)
                    if envio:
                        flash(envio[1], "ok" if envio[0] == "ok" else "error")
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
        PUNTOS_VENTA=puntos_venta(), ambiente=arca_web.ambiente_activo(),
    )


@bp.route("/<int:id>")
def ver(id):
    db = get_db()
    factura = db.execute("SELECT * FROM facturas WHERE id = ?", (id,)).fetchone()
    if factura is None:
        abort(404)
    renglones = db.execute("SELECT * FROM factura_renglones WHERE factura_id = ? ORDER BY orden",
                           (id,)).fetchall()
    asociada = (db.execute("SELECT * FROM facturas WHERE id = ?", (factura["asociado_id"],)).fetchone()
                if factura["asociado_id"] else None)
    return render_template("facturas/ver.html", f=factura, renglones=renglones, CONCEPTOS=CONCEPTOS,
                           mail_configurado=mail.configurado(),
                           es_nc=es_nota_credito(factura), asociada=asociada, cobro=cobro_de(id),
                           nota_credito=None if es_nota_credito(factura) else nota_credito_de(id))


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
    asociada = (db.execute("SELECT * FROM facturas WHERE id = ?", (factura["asociado_id"],)).fetchone()
                if factura["asociado_id"] else None)
    return Response(generar_pdf(factura, renglones, copias, asociada), mimetype="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{archivo}"'})


@bp.route("/<int:id>/eliminar", methods=("POST",))
def eliminar(id):
    """Solo se pueden eliminar facturas de prueba. Las reales se anulan con nota de crédito."""
    db = get_db()
    factura = db.execute("SELECT * FROM facturas WHERE id = ?", (id,)).fetchone()
    if factura is None:
        abort(404)
    if not factura["prueba"]:
        flash("Los comprobantes reales no se pueden eliminar: una factura se anula con una nota de "
              "crédito.", "error")
        return redirect(url_for("facturas.ver", id=id))
    if nota_credito_de(id):
        flash("Esta factura tiene una nota de crédito: eliminá primero la nota de crédito.", "error")
        return redirect(url_for("facturas.ver", id=id))
    if cobro_de(id):
        flash("Esta factura tiene un cobro registrado: eliminá primero el cobro.", "error")
        return redirect(url_for("facturas.ver", id=id))
    db.execute("DELETE FROM factura_renglones WHERE factura_id = ?", (id,))
    db.execute("DELETE FROM facturas WHERE id = ?", (id,))
    db.commit()
    flash(f"{NOMBRE_CBTE[factura['cbte_tipo']]} de prueba N° {factura['numero']} eliminada.", "ok")
    return redirect(url_for("facturas.lista"))


# --- Notas de crédito -------------------------------------------------------------------

def validar_nota_credito(factura, fecha_texto):
    """Devuelve un mensaje de error, o None si se puede hacer la nota de crédito."""
    if es_nota_credito(factura):
        return "Una nota de crédito no se puede anular con otra nota de crédito."
    if cobro_de(factura["id"]):
        return ("La factura ya está cobrada. Si hay que anularla, primero eliminá el cobro "
                "(Cobros → Ver → Eliminar cobro).")
    anterior = nota_credito_de(factura["id"])
    if anterior:
        return (f"Esta factura ya tiene la Nota de Crédito {anterior['letra']} "
                f"N° {anterior['punto_venta']:05d}-{anterior['numero']:08d}.")
    fecha = leer_fecha(fecha_texto)
    margen = DIAS_MARGEN.get(factura["concepto"], 5)
    if fecha is None:
        return "Escribí la fecha de la nota de crédito."
    if abs((fecha - date.today()).days) > margen:
        return f"ARCA solo acepta fechas hasta {margen} días antes o después de hoy."
    if fecha_texto < factura["fecha"]:
        return "La nota de crédito no puede tener fecha anterior a la factura."
    if factura["arca"] and factura["arca"] != arca_web.ambiente_activo():
        return ("Esta factura se autorizó en ARCA " + ("HOMOLOGACIÓN" if factura["arca"] == "homologacion"
                else "PRODUCCIÓN") + ", y ahora la conexión con ese ambiente no está activa. "
                "Activalo en la pantalla ARCA para hacer la nota de crédito.")
    ultima = ultima_factura(factura["punto_venta"], NC_TIPO[factura["letra"]], factura["prueba"],
                            factura["arca"])
    if ultima and fecha_texto < ultima["fecha"]:
        return (f"La fecha no puede ser anterior a la última Nota de Crédito {factura['letra']} "
                f"({date.fromisoformat(ultima['fecha']):%d/%m/%Y}).")
    return None


def guardar_nota_credito(factura, fecha, observaciones, token):
    """Nota de crédito por el total de la factura, en el mismo modo que la factura (prueba del
    sistema o ARCA). Devuelve (id, observaciones_de_arca)."""
    db = get_db()
    c = {campo: factura[campo] for campo in CAMPOS_COMPROBANTE if campo in factura.keys()}
    c.update(cbte_tipo=NC_TIPO[factura["letra"]], numero=None, fecha=fecha,
             vto_pago=fecha if factura["vto_pago"] else None, observaciones=observaciones,
             token=token, asociado_id=factura["id"], remito_pto_vta=None, remito_numero=None,
             cae=None, cae_vto=None)
    renglones = db.execute("SELECT * FROM factura_renglones WHERE factura_id = ? ORDER BY orden",
                           (factura["id"],)).fetchall()
    db.execute("BEGIN IMMEDIATE")
    try:
        repetida = db.execute("SELECT id FROM facturas WHERE token = ?", (token,)).fetchone()
        if repetida:
            db.rollback()
            return repetida["id"], []
        observaciones_arca = numerar_y_autorizar(db, c, asociada=factura)
        nota_id = insertar_comprobante(db, c, renglones)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return nota_id, observaciones_arca


@bp.route("/<int:id>/nota-credito", methods=("GET", "POST"))
def nota_credito(id):
    """Nota de crédito por el total de la factura (para anularla)."""
    db = get_db()
    factura = db.execute("SELECT * FROM facturas WHERE id = ?", (id,)).fetchone()
    if factura is None:
        abort(404)
    datos = {"fecha": date.today().isoformat(), "observaciones": "", "token": uuid.uuid4().hex}
    error = None
    if request.method == "POST":
        datos = {"fecha": request.form.get("fecha", ""),
                 "observaciones": (request.form.get("observaciones") or "").strip()[:1000],
                 "token": request.form.get("token") or uuid.uuid4().hex}
        repetida = db.execute("SELECT id FROM facturas WHERE token = ?", (datos["token"],)).fetchone()
        if repetida:  # se tocó "Confirmar" dos veces
            return redirect(url_for("facturas.ver", id=repetida["id"]))
        error = validar_nota_credito(factura, datos["fecha"])
        if not error:
            try:
                nota_id, observaciones = guardar_nota_credito(factura, datos["fecha"],
                                                              datos["observaciones"], datos["token"])
            except arca.ErrorArca as e:
                error = str(e)
            else:
                nota = db.execute("SELECT * FROM facturas WHERE id = ?", (nota_id,)).fetchone()
                flash(f"Nota de Crédito {nota['letra']} N° {nota['numero']} {mensaje_emitida(nota)} "
                      "La factura quedó anulada.", "ok")
                for obs in observaciones:
                    flash(f"Observación de ARCA: {obs}", "aviso")
                return redirect(url_for("facturas.ver", id=nota_id))
    else:
        error = validar_nota_credito(factura, datos["fecha"]) if (
            es_nota_credito(factura) or nota_credito_de(id) or cobro_de(id)) else None
    renglones = db.execute("SELECT * FROM factura_renglones WHERE factura_id = ? ORDER BY orden",
                           (id,)).fetchall()
    return render_template("facturas/nota_credito.html", f=factura, renglones=renglones, datos=datos,
                           error=error, CONCEPTOS=CONCEPTOS)
