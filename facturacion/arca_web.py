"""Pantalla "ARCA" (certificado, punto de venta, prueba de conexión) y emisión con CAE.

Configuración guardada en la tabla `configuracion`:
  arca_ambiente           "" (sin ARCA: facturas de prueba del sistema), "homologacion" o "produccion"
  arca_pv_homologacion    punto de venta para web services en homologación
  arca_pv_produccion      punto de venta "RECE para aplicativo y web services" (producción)
"""
import os

from flask import (Blueprint, Response, current_app, flash, redirect, render_template, request,
                   url_for)

from . import arca
from .db import get_db

bp = Blueprint("arca", __name__, url_prefix="/arca")


# --- Configuración ------------------------------------------------------------------------

def leer(clave, defecto=""):
    fila = get_db().execute("SELECT valor FROM configuracion WHERE clave = ?", (clave,)).fetchone()
    return fila["valor"] if fila else defecto


def guardar(clave, valor):
    db = get_db()
    db.execute("INSERT OR REPLACE INTO configuracion (clave, valor) VALUES (?, ?)", (clave, str(valor)))
    db.commit()


def instancia():
    """Carpeta donde viven los archivos de ARCA (instance/arca/...)."""
    return current_app.config.get("ARCA_CARPETA") or current_app.instance_path


def punto_venta(ambiente):
    valor = leer(f"arca_pv_{ambiente}")
    return int(valor) if valor.isdigit() else None


def listo(ambiente):
    """¿Está todo lo necesario para facturar en este ambiente?"""
    return bool(ambiente in arca.AMBIENTES and punto_venta(ambiente)
                and arca.estado(instancia(), ambiente)["certificado"])


def ambiente_activo():
    """El ambiente de ARCA en uso, o None si se factura en modo prueba del sistema."""
    ambiente = leer("arca_ambiente")
    return ambiente if listo(ambiente) else None


# --- Emisión -----------------------------------------------------------------------------

def emitir(ambiente, comprobante, asociada=None):
    """Pide a ARCA el número siguiente y el CAE para el comprobante (dict con los datos).

    Devuelve {"numero", "cae", "cae_vto", "observaciones"}. Si se corta la comunicación justo
    después de mandar el pedido, consulta a ARCA si lo autorizó igual, para no perder un CAE
    ni duplicar un número.
    """
    carpeta = instancia()
    pv, tipo = comprobante["punto_venta"], comprobante["cbte_tipo"]
    numero = arca.ultimo_autorizado(carpeta, ambiente, pv, tipo) + 1
    try:
        respuesta = arca.solicitar_cae(carpeta, ambiente, comprobante, numero, asociada)
    except arca.SinRespuesta:
        # ¿Llegó a autorizarlo? Si el último autorizado ahora es este número, buscamos su CAE.
        if arca.ultimo_autorizado(carpeta, ambiente, pv, tipo) == numero:
            datos = arca.consultar(carpeta, ambiente, pv, tipo, numero)
            if datos:
                return {"numero": numero, "cae": datos["cae"], "cae_vto": datos["cae_vto"],
                        "observaciones": []}
        raise
    respuesta["numero"] = numero
    return respuesta


# --- Pantalla ----------------------------------------------------------------------------

def datos_pantalla():
    carpeta = instancia()
    ambientes = {}
    for clave, nombre in arca.AMBIENTES.items():
        estado = arca.estado(carpeta, clave)
        pedido = ""
        if estado["pedido"]:
            with open(arca.rutas(carpeta, clave)["pedido"], encoding="ascii") as f:
                pedido = f.read()
        ambientes[clave] = {"nombre": nombre, "estado": estado, "pedido": pedido,
                            "punto_venta": punto_venta(clave), "listo": listo(clave)}
    return {"ambientes": ambientes, "activo": leer("arca_ambiente"), "alias": arca.ALIAS}


@bp.route("/")
def ver():
    return render_template("arca.html", **datos_pantalla(), prueba=None)


@bp.route("/<ambiente>/pedido", methods=("POST",))
def generar_pedido(ambiente):
    if ambiente not in arca.AMBIENTES:
        return redirect(url_for("arca.ver"))
    arca.generar_clave_y_pedido(instancia(), ambiente)
    flash("Pedido de certificado generado. Seguí con el paso 2.", "ok")
    return redirect(url_for("arca.ver", _anchor=ambiente))


@bp.route("/<ambiente>/pedido.csr")
def bajar_pedido(ambiente):
    ruta = arca.rutas(instancia(), ambiente)["pedido"] if ambiente in arca.AMBIENTES else ""
    if not ruta or not os.path.exists(ruta):
        return redirect(url_for("arca.ver"))
    with open(ruta, "rb") as f:
        return Response(f.read(), mimetype="application/pkcs10", headers={
            "Content-Disposition": f'attachment; filename="pedido_{ambiente}.csr"'})


@bp.route("/<ambiente>/certificado", methods=("POST",))
def subir_certificado(ambiente):
    if ambiente not in arca.AMBIENTES:
        return redirect(url_for("arca.ver"))
    archivo = request.files.get("archivo")
    contenido = archivo.read() if archivo and archivo.filename else \
        (request.form.get("texto") or "").strip().encode()
    if not contenido:
        flash("Elegí el archivo del certificado o pegá su contenido.", "error")
        return redirect(url_for("arca.ver", _anchor=ambiente))
    try:
        certificado = arca.guardar_certificado(instancia(), ambiente, contenido)
    except arca.ErrorArca as error:
        flash(str(error), "error")
    else:
        vence = certificado.not_valid_after_utc.astimezone(arca.ARGENTINA)
        flash(f"Certificado guardado. Vence el {vence:%d/%m/%Y}.", "ok")
    return redirect(url_for("arca.ver", _anchor=ambiente))


@bp.route("/<ambiente>/punto-venta", methods=("POST",))
def guardar_punto_venta(ambiente):
    valor = (request.form.get("punto_venta") or "").strip().lstrip("0")
    if ambiente not in arca.AMBIENTES or not valor.isdigit() or not 1 <= int(valor) <= 99998:
        flash("El punto de venta es un número entre 1 y 99998.", "error")
    else:
        guardar(f"arca_pv_{ambiente}", int(valor))
        flash(f"Punto de venta {int(valor):05d} guardado.", "ok")
    return redirect(url_for("arca.ver", _anchor=ambiente))


@bp.route("/<ambiente>/probar", methods=("POST",))
def probar(ambiente):
    """Prueba la conexión paso a paso y muestra qué anduvo y qué no."""
    if ambiente not in arca.AMBIENTES:
        return redirect(url_for("arca.ver"))
    pasos = []
    try:
        servidores = arca.estado_servidores(ambiente)
        pasos.append(("Servidores de ARCA", all(v == "OK" for v in servidores.values()),
                      ", ".join(f"{k}: {v}" for k, v in servidores.items())))
        arca.ticket(instancia(), ambiente)
        pasos.append(("Identificación con el certificado", True, "ARCA aceptó el certificado."))
        pv = punto_venta(ambiente)
        if pv:
            ultimo = arca.ultimo_autorizado(instancia(), ambiente, pv, 1)
            pasos.append(("Punto de venta", True,
                          f"Último número de Factura A autorizado en el {pv:05d}: {ultimo}."))
        else:
            pasos.append(("Punto de venta", False, "Falta cargar el punto de venta (paso 4)."))
    except arca.ErrorArca as error:
        pasos.append(("Error", False, str(error)))
    return render_template("arca.html", **datos_pantalla(),
                           prueba={"ambiente": ambiente, "pasos": pasos,
                                   "ok": all(ok for _, ok, _ in pasos)})


@bp.route("/activar", methods=("POST",))
def activar():
    ambiente = request.form.get("ambiente", "")
    if ambiente == "":
        guardar("arca_ambiente", "")
        flash("Conexión con ARCA desactivada: las facturas nuevas vuelven a ser de prueba del sistema.", "ok")
    elif not listo(ambiente):
        flash("Para activar ese ambiente faltan pasos (certificado y punto de venta).", "error")
    elif ambiente == "produccion" and request.form.get("confirmo") != "1":
        flash("Para activar producción tildá la casilla de confirmación.", "error")
    else:
        guardar("arca_ambiente", ambiente)
        flash(f"Conexión activada: {arca.AMBIENTES[ambiente]}.", "ok")
    return redirect(url_for("arca.ver"))
