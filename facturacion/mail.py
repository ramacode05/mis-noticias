"""Envío de facturas por mail desde una cuenta de Gmail (con "contraseña de aplicación").

Cuando ARCA autoriza una factura real (producción), se manda sola al email del cliente:
  Asunto:  Factura A 00004-00000012
  Texto:   Buenos días, adjunto factura
  Adjunto: el PDF (solo el ORIGINAL)

Configuración (pantalla "Mail", guardada en la tabla `configuracion`):
  mail_usuario     la cuenta de Gmail
  mail_clave       la contraseña de aplicación de 16 letras que da Google
  mail_automatico  "1" para mandar solo cada factura autorizada, "" para no hacerlo
"""
import re
import smtplib
import socket
from email.message import EmailMessage
from email.utils import formataddr

from flask import Blueprint, flash, redirect, render_template, request, url_for

from .db import get_db
from .emisor import EMISOR

SERVIDOR, PUERTO = "smtp.gmail.com", 465
ESPERA = 30
TEXTO = "Buenos días, adjunto factura"
NOMBRE_CBTE = {1: "Factura A", 6: "Factura B", 3: "Nota de Crédito A", 8: "Nota de Crédito B"}


class ErrorMail(Exception):
    """Error al mandar un mail, con un mensaje en castellano para mostrar en pantalla."""


def leer(clave, defecto=""):
    fila = get_db().execute("SELECT valor FROM configuracion WHERE clave = ?", (clave,)).fetchone()
    return fila["valor"] if fila else defecto


def guardar(clave, valor):
    db = get_db()
    db.execute("INSERT OR REPLACE INTO configuracion (clave, valor) VALUES (?, ?)", (clave, valor))
    db.commit()


def configurado():
    return bool(leer("mail_usuario") and leer("mail_clave"))


def direcciones(texto):
    """'a@x.com; b@y.com' -> ['a@x.com', 'b@y.com'] (un cliente puede tener varios mails)."""
    return [d for d in re.split(r"[,;\s]+", texto or "") if d]


def mail_valido(direccion):
    return bool(re.fullmatch(r"[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+", direccion))


def enviar(para, asunto, texto, adjunto=None, nombre_adjunto=None):
    """Manda un mail por Gmail. Lanza ErrorMail con el motivo si no se puede."""
    usuario, clave = leer("mail_usuario"), leer("mail_clave")
    if not usuario or not clave:
        raise ErrorMail("Falta configurar el mail (menú Mail).")
    mensaje = EmailMessage()
    mensaje["From"] = formataddr((EMISOR["nombre_fantasia"], usuario))
    mensaje["To"] = ", ".join(para)
    mensaje["Subject"] = asunto
    mensaje.set_content(texto)
    if adjunto:
        mensaje.add_attachment(adjunto, maintype="application", subtype="pdf", filename=nombre_adjunto)
    try:
        with smtplib.SMTP_SSL(SERVIDOR, PUERTO, timeout=ESPERA) as servidor:
            servidor.login(usuario, clave)
            servidor.send_message(mensaje)
    except smtplib.SMTPAuthenticationError:
        raise ErrorMail("Gmail rechazó el usuario o la contraseña de aplicación. Revisalos en el menú Mail.")
    except smtplib.SMTPRecipientsRefused:
        raise ErrorMail(f"Gmail no aceptó la dirección del cliente ({', '.join(para)}). Revisala en Clientes.")
    except (smtplib.SMTPException, socket.gaierror, socket.timeout, OSError) as error:
        raise ErrorMail(f"No se pudo mandar el mail ({error}). Revisá la conexión a internet.")


def enviar_factura(factura_id):
    """Manda el PDF (original) de la factura al email del cliente y anota el resultado.

    Devuelve un mensaje para mostrar. Lanza ErrorMail si no se pudo mandar.
    """
    from .pdf import generar_pdf, nombre_archivo

    db = get_db()
    f = db.execute("SELECT * FROM facturas WHERE id = ?", (factura_id,)).fetchone()
    cliente = db.execute("SELECT email FROM clientes WHERE id = ?", (f["cliente_id"],)).fetchone()
    para = [d for d in direcciones(cliente["email"] if cliente else "") if mail_valido(d)]
    try:
        if not para:
            raise ErrorMail(f"El cliente {f['cliente_razon_social']} no tiene email cargado. "
                            "Cargalo en Clientes y tocá \"Enviar por mail\" en la factura.")
        renglones = db.execute("SELECT * FROM factura_renglones WHERE factura_id = ? ORDER BY orden",
                               (factura_id,)).fetchall()
        asociada = (db.execute("SELECT * FROM facturas WHERE id = ?", (f["asociado_id"],)).fetchone()
                    if f["asociado_id"] else None)
        pdf = generar_pdf(f, renglones, ("ORIGINAL",), asociada)
        asunto = f"{NOMBRE_CBTE[f['cbte_tipo']]} {f['punto_venta']:05d}-{f['numero']:08d}"
        enviar(para, asunto, TEXTO, pdf, nombre_archivo(f))
    except ErrorMail as error:
        db.execute("UPDATE facturas SET mail_error = ? WHERE id = ?", (str(error), factura_id))
        db.commit()
        raise
    db.execute("UPDATE facturas SET mail_enviado = datetime('now', 'localtime'), mail_para = ?, "
               "mail_error = NULL WHERE id = ?", (", ".join(para), factura_id))
    db.commit()
    return f"Factura enviada por mail a {', '.join(para)}."


def enviar_si_corresponde(factura_id):
    """Después de autorizar: manda sola la factura si es real (producción) y está activado."""
    f = get_db().execute("SELECT arca, cbte_tipo FROM facturas WHERE id = ?", (factura_id,)).fetchone()
    if f["arca"] != "produccion" or f["cbte_tipo"] not in (1, 6):
        return None
    if not leer("mail_automatico", "1") or not configurado():
        return None
    try:
        return "ok", enviar_factura(factura_id)
    except ErrorMail as error:
        return "error", f"La factura se emitió bien, pero no se pudo mandar por mail: {error}"


# --- Pantalla "Mail" ---------------------------------------------------------------------

bp = Blueprint("mail", __name__, url_prefix="/mail")


@bp.route("/", methods=("GET", "POST"))
def configurar():
    if request.method == "POST":
        usuario = (request.form.get("usuario") or "").strip().lower()
        clave = re.sub(r"\s", "", request.form.get("clave") or "")
        if not mail_valido(usuario) or not usuario.endswith(("@gmail.com", "@googlemail.com")):
            flash("Escribí una dirección de Gmail (termina en @gmail.com).", "error")
            return redirect(url_for("mail.configurar"))
        if clave and not re.fullmatch(r"[a-zA-Z]{16}", clave):
            flash("La contraseña de aplicación son 16 letras (Google las muestra en 4 grupos de 4).", "error")
            return redirect(url_for("mail.configurar"))
        guardar("mail_usuario", usuario)
        if clave:
            guardar("mail_clave", clave)
        guardar("mail_automatico", "1" if request.form.get("automatico") else "")
        flash("Configuración del mail guardada. Probala con \"Mandarme un mail de prueba\".", "ok")
        return redirect(url_for("mail.configurar"))
    return render_template("mail.html", usuario=leer("mail_usuario"), tiene_clave=bool(leer("mail_clave")),
                           automatico=bool(leer("mail_automatico", "1")), texto=TEXTO)


@bp.route("/prueba", methods=("POST",))
def prueba():
    usuario = leer("mail_usuario")
    try:
        enviar([usuario], "Prueba del sistema de facturación",
               "Si te llegó este mail, el sistema ya puede mandar las facturas por mail.")
    except ErrorMail as error:
        flash(str(error), "error")
    else:
        flash(f"Mail de prueba enviado a {usuario}. Fijate en tu bandeja de entrada.", "ok")
    return redirect(url_for("mail.configurar"))


@bp.route("/factura/<int:factura_id>", methods=("POST",))
def reenviar(factura_id):
    f = get_db().execute("SELECT id, prueba FROM facturas WHERE id = ?", (factura_id,)).fetchone()
    if f is None:
        return redirect(url_for("facturas.lista"))
    if f["prueba"]:
        flash("Las facturas de prueba no se mandan a los clientes.", "error")
        return redirect(url_for("facturas.ver", id=factura_id))
    try:
        flash(enviar_factura(factura_id), "ok")
    except ErrorMail as error:
        flash(str(error), "error")
    return redirect(url_for("facturas.ver", id=factura_id))
