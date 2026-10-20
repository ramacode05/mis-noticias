"""Conexión con ARCA por web services: WSAA (identificación) y WSFEv1 (factura electrónica).

Cómo funciona:
  1. Con la clave privada y el certificado de la empresa se firma un pedido de acceso (TRA) y
     se lo manda al WSAA. ARCA devuelve un "ticket de acceso" (token + sign) que vale 12 horas.
     El ticket se guarda en instance/arca/<ambiente>/ticket.json para reusarlo: ARCA no da otro
     mientras el anterior siga vigente.
  2. Con el ticket se llama al WSFEv1: último número autorizado, pedir CAE, consultar un
     comprobante.

Ambientes: "homologacion" (prueba de ARCA, sin validez fiscal) y "produccion" (real).
Los archivos (clave, pedido de certificado, certificado, ticket) viven en instance/arca/, que
no se sube a Git y se comparte entre las dos PCs por Google Drive.
"""
import base64
import json
import os
import ssl
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs7
from cryptography.x509.oid import NameOID

from .emisor import EMISOR

AMBIENTES = {"homologacion": "Homologación (prueba de ARCA, sin validez fiscal)",
             "produccion": "Producción (facturas reales)"}
URLS = {
    "homologacion": {"wsaa": "https://wsaahomo.afip.gov.ar/ws/services/LoginCms",
                     "wsfe": "https://wswhomo.afip.gov.ar/wsfev1/service.asmx"},
    "produccion": {"wsaa": "https://wsaa.afip.gov.ar/ws/services/LoginCms",
                   "wsfe": "https://servicios1.afip.gov.ar/wsfev1/service.asmx"},
}
SERVICIO = "wsfe"
ALIAS = "facturacion"   # nombre del "computador fiscal" en ARCA
ESPERA = 60             # segundos máximos esperando respuesta de ARCA
ARGENTINA = timezone(timedelta(hours=-3))

# Códigos de ARCA
DOC_TIPO = {"CUIT": 80, "DNI": 96, "SIN": 99}
CONDICION_IVA_RECEPTOR = {"RI": 1, "EX": 4, "CF": 5, "MT": 6}  # RG 5616
IVA_21 = 5
NS_FE = "http://ar.gov.afip.dif.FEV1/"


class ErrorArca(Exception):
    """Error al hablar con ARCA, con un mensaje en castellano para mostrar en pantalla."""


class SinRespuesta(ErrorArca):
    """No se sabe si ARCA recibió el pedido (se cortó internet, tardó demasiado)."""


# --- Archivos de cada ambiente -----------------------------------------------------------

def carpeta(instance, ambiente):
    ruta = os.path.join(instance, "arca", ambiente)
    os.makedirs(ruta, exist_ok=True)
    return ruta


def rutas(instance, ambiente):
    base = carpeta(instance, ambiente)
    return {"clave": os.path.join(base, "clave.key"), "pedido": os.path.join(base, "pedido.csr"),
            "certificado": os.path.join(base, "certificado.crt"),
            "ticket": os.path.join(base, "ticket.json")}


def generar_clave_y_pedido(instance, ambiente):
    """Crea la clave privada y el pedido de certificado (CSR) para subir a ARCA.

    Si ya existe una clave, la reusa (para no invalidar un certificado ya tramitado).
    """
    r = rutas(instance, ambiente)
    if os.path.exists(r["clave"]):
        with open(r["clave"], "rb") as f:
            clave = serialization.load_pem_private_key(f.read(), password=None)
    else:
        clave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        with open(r["clave"], "wb") as f:
            f.write(clave.private_bytes(serialization.Encoding.PEM,
                                        serialization.PrivateFormat.TraditionalOpenSSL,
                                        serialization.NoEncryption()))
    nombre = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "AR"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, EMISOR["nombre_fantasia"][:64]),
        x509.NameAttribute(NameOID.COMMON_NAME, ALIAS),
        x509.NameAttribute(NameOID.SERIAL_NUMBER, f"CUIT {EMISOR['cuit']}"),
    ])
    pedido = x509.CertificateSigningRequestBuilder().subject_name(nombre).sign(clave, hashes.SHA256())
    with open(r["pedido"], "wb") as f:
        f.write(pedido.public_bytes(serialization.Encoding.PEM))
    return r["pedido"]


def guardar_certificado(instance, ambiente, contenido):
    """Valida el certificado que dio ARCA (que corresponda a nuestra clave) y lo guarda."""
    r = rutas(instance, ambiente)
    if not os.path.exists(r["clave"]):
        raise ErrorArca("Primero hay que generar el pedido de certificado (paso 1).")
    try:
        certificado = x509.load_pem_x509_certificate(contenido)
    except ValueError:
        try:
            certificado = x509.load_der_x509_certificate(contenido)
        except ValueError:
            raise ErrorArca("El archivo no es un certificado válido. Tiene que ser el .crt que da ARCA.")
    with open(r["clave"], "rb") as f:
        clave = serialization.load_pem_private_key(f.read(), password=None)
    if certificado.public_key().public_numbers() != clave.public_key().public_numbers():
        raise ErrorArca("Ese certificado no corresponde a esta clave. Usá el certificado que ARCA "
                        "generó con el pedido que bajaste de este sistema.")
    with open(r["certificado"], "wb") as f:
        f.write(certificado.public_bytes(serialization.Encoding.PEM))
    if os.path.exists(r["ticket"]):
        os.remove(r["ticket"])  # el ticket viejo era de otro certificado
    return certificado


def estado(instance, ambiente):
    """Qué pasos están hechos en este ambiente."""
    r = rutas(instance, ambiente)
    datos = {"clave": os.path.exists(r["clave"]), "pedido": os.path.exists(r["pedido"]),
             "certificado": os.path.exists(r["certificado"]), "vence": None}
    if datos["certificado"]:
        with open(r["certificado"], "rb") as f:
            cert = x509.load_pem_x509_certificate(f.read())
        datos["vence"] = cert.not_valid_after_utc.astimezone(ARGENTINA)
    return datos


# --- Comunicación SOAP -------------------------------------------------------------------

def _post(url, cuerpo, accion):
    pedido = urllib.request.Request(url, data=cuerpo.encode("utf-8"), headers={
        "Content-Type": "text/xml; charset=utf-8", "SOAPAction": f'"{accion}"'})
    # Los servidores de ARCA usan claves Diffie-Hellman chicas que Python rechaza por defecto.
    contexto = ssl.create_default_context()
    contexto.set_ciphers("DEFAULT@SECLEVEL=1")
    try:
        with urllib.request.urlopen(pedido, timeout=ESPERA, context=contexto) as respuesta:
            return respuesta.read()
    except urllib.error.HTTPError as error:
        return error.read()  # los errores SOAP vienen con código 500 y explicación en el cuerpo
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise SinRespuesta(f"No se pudo comunicar con ARCA ({error}). Revisá la conexión a internet.")


def _xml(datos):
    try:
        return ElementTree.fromstring(datos)
    except ElementTree.ParseError:
        raise ErrorArca("ARCA respondió algo que no se pudo leer. Probá de nuevo en unos minutos.")


def _buscar(raiz, nombre):
    """Busca un elemento por nombre sin importar el espacio de nombres."""
    for elemento in raiz.iter():
        if elemento.tag.rsplit("}", 1)[-1] == nombre:
            return elemento
    return None


def _texto(raiz, nombre):
    elemento = _buscar(raiz, nombre)
    return elemento.text.strip() if elemento is not None and elemento.text else ""


def _falla_soap(raiz):
    falla = _buscar(raiz, "Fault")
    return _texto(falla, "faultstring") if falla is not None else ""


# --- WSAA: ticket de acceso --------------------------------------------------------------

def pedido_de_acceso(ahora=None):
    """El TRA (ticket request) que se firma y se manda al WSAA."""
    ahora = ahora or datetime.now(ARGENTINA)
    return (f'<?xml version="1.0" encoding="UTF-8"?><loginTicketRequest version="1.0"><header>'
            f"<uniqueId>{int(ahora.timestamp())}</uniqueId>"
            f"<generationTime>{(ahora - timedelta(minutes=10)).isoformat(timespec='seconds')}</generationTime>"
            f"<expirationTime>{(ahora + timedelta(minutes=10)).isoformat(timespec='seconds')}</expirationTime>"
            f"</header><service>{SERVICIO}</service></loginTicketRequest>")


def firmar(tra, clave_pem, certificado_pem):
    """Firma el TRA en formato CMS (PKCS#7) como pide ARCA. Devuelve el texto en base64."""
    clave = serialization.load_pem_private_key(clave_pem, password=None)
    certificado = x509.load_pem_x509_certificate(certificado_pem)
    cms = (pkcs7.PKCS7SignatureBuilder().set_data(tra.encode("utf-8"))
           .add_signer(certificado, clave, hashes.SHA256())
           .sign(serialization.Encoding.DER, []))
    return base64.b64encode(cms).decode()


def ticket(instance, ambiente, ahora=None):
    """Devuelve (token, sign). Reusa el ticket guardado mientras siga vigente."""
    ahora = ahora or datetime.now(ARGENTINA)
    r = rutas(instance, ambiente)
    if os.path.exists(r["ticket"]):
        with open(r["ticket"], encoding="utf-8") as f:
            guardado = json.load(f)
        if datetime.fromisoformat(guardado["vence"]) > ahora + timedelta(minutes=5):
            return guardado["token"], guardado["sign"]
    if not os.path.exists(r["certificado"]):
        raise ErrorArca("Falta el certificado de ARCA. Completá los pasos de la pantalla ARCA.")
    with open(r["clave"], "rb") as f:
        clave = f.read()
    with open(r["certificado"], "rb") as f:
        certificado = f.read()
    cms = firmar(pedido_de_acceso(ahora), clave, certificado)
    cuerpo = ('<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
              'xmlns:wsaa="http://wsaa.view.sua.dvadac.desein.afip.gov"><soapenv:Header/><soapenv:Body>'
              f"<wsaa:loginCms><wsaa:in0>{cms}</wsaa:in0></wsaa:loginCms></soapenv:Body></soapenv:Envelope>")
    raiz = _xml(_post(URLS[ambiente]["wsaa"], cuerpo, ""))
    falla = _falla_soap(raiz)
    if falla:
        if "ya posee un TA valido" in falla:
            raise ErrorArca("ARCA dice que ya entregó un permiso vigente que este sistema no tiene "
                            "guardado (pasa si se borró el archivo del ticket). Esperá unos minutos "
                            "(hasta 12 horas en el peor caso) y probá de nuevo.")
        if "Computador no autorizado" in falla or "no autorizado" in falla.lower():
            raise ErrorArca("ARCA no autoriza este certificado para facturar. Falta el paso de "
                            "autorizar el servicio de factura electrónica (wsfe). " + falla)
        raise ErrorArca(f"ARCA rechazó la identificación: {falla}")
    respuesta = _xml(_texto(raiz, "loginCmsReturn").encode("utf-8"))
    token, sign = _texto(respuesta, "token"), _texto(respuesta, "sign")
    if not token or not sign:
        raise ErrorArca("ARCA no devolvió el permiso de acceso. Probá de nuevo en unos minutos.")
    with open(r["ticket"], "w", encoding="utf-8") as f:
        json.dump({"token": token, "sign": sign, "vence": _texto(respuesta, "expirationTime")}, f)
    return token, sign


# --- WSFEv1 ------------------------------------------------------------------------------

def _wsfe(instance, ambiente, metodo, contenido, con_auth=True):
    auth = ""
    if con_auth:
        token, sign = ticket(instance, ambiente)
        auth = (f"<ar:Auth><ar:Token>{token}</ar:Token><ar:Sign>{sign}</ar:Sign>"
                f"<ar:Cuit>{EMISOR['cuit']}</ar:Cuit></ar:Auth>")
    cuerpo = ('<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
              f'xmlns:ar="{NS_FE}"><soapenv:Header/><soapenv:Body>'
              f"<ar:{metodo}>{auth}{contenido}</ar:{metodo}></soapenv:Body></soapenv:Envelope>")
    raiz = _xml(_post(URLS[ambiente]["wsfe"], cuerpo, NS_FE + metodo))
    falla = _falla_soap(raiz)
    if falla:
        raise ErrorArca(f"ARCA respondió con un error: {falla}")
    return raiz


def _errores(raiz, grupo="Errors", item="Err"):
    elemento = _buscar(raiz, grupo)
    if elemento is None:
        return []
    return [f"{_texto(e, 'Code')}: {_texto(e, 'Msg')}" for e in elemento
            if e.tag.rsplit("}", 1)[-1] == item]


def estado_servidores(ambiente):
    """FEDummy: ¿están funcionando los servidores de ARCA? (no necesita certificado)"""
    raiz = _wsfe(None, ambiente, "FEDummy", "", con_auth=False)
    return {k: _texto(raiz, k) for k in ("AppServer", "DbServer", "AuthServer")}


def ultimo_autorizado(instance, ambiente, punto_venta, cbte_tipo):
    raiz = _wsfe(instance, ambiente, "FECompUltimoAutorizado",
                 f"<ar:PtoVta>{punto_venta}</ar:PtoVta><ar:CbteTipo>{cbte_tipo}</ar:CbteTipo>")
    errores = _errores(raiz)
    if any("lista de relaciones" in e for e in errores):
        raise ErrorArca(
            f"El certificado funciona, pero en ARCA falta autorizarlo a facturar por la empresa "
            f"(CUIT {EMISOR['cuit']}). En \"WSASS\" (homologación) o en el \"Administrador de "
            f"Relaciones\" (producción) creá la autorización al servicio \"wsfe\" con CUIT "
            f"representada {EMISOR['cuit']}. ARCA tarda en tomar el cambio: si sigue igual, probá de "
            f"nuevo después de 12 horas. (" + "; ".join(errores) + ")")
    if errores:
        raise ErrorArca("ARCA no informó el último número: " + "; ".join(errores))
    return int(_texto(raiz, "CbteNro") or 0)


def consultar(instance, ambiente, punto_venta, cbte_tipo, numero):
    """Datos de un comprobante ya autorizado (o None si ARCA no lo tiene)."""
    raiz = _wsfe(instance, ambiente, "FECompConsultar",
                 f"<ar:FeCompConsReq><ar:CbteTipo>{cbte_tipo}</ar:CbteTipo><ar:CbteNro>{numero}"
                 f"</ar:CbteNro><ar:PtoVta>{punto_venta}</ar:PtoVta></ar:FeCompConsReq>")
    if _errores(raiz) or not _texto(raiz, "CodAutorizacion"):
        return None
    return {"cae": _texto(raiz, "CodAutorizacion"), "cae_vto": _fecha_iso(_texto(raiz, "FchVto")),
            "total": _texto(raiz, "ImpTotal"), "fecha": _fecha_iso(_texto(raiz, "CbteFch")),
            "doc_nro": _texto(raiz, "DocNro")}


def _importe(centavos):
    return f"{centavos / 100:.2f}"


def _fecha_arca(iso):
    return iso.replace("-", "") if iso else ""


def _fecha_iso(arca):
    return f"{arca[:4]}-{arca[4:6]}-{arca[6:8]}" if arca and len(arca) == 8 else ""


def detalle_comprobante(c, numero, asociada=None):
    """El XML de FECAEDetRequest para el comprobante c (factura o nota de crédito)."""
    doc_tipo = DOC_TIPO.get(c["cliente_tipo_doc"], 99)
    partes = [
        f"<ar:Concepto>{c['concepto']}</ar:Concepto>",
        f"<ar:DocTipo>{doc_tipo}</ar:DocTipo>",
        f"<ar:DocNro>{c['cliente_nro_doc'] if doc_tipo != 99 else 0}</ar:DocNro>",
        f"<ar:CbteDesde>{numero}</ar:CbteDesde><ar:CbteHasta>{numero}</ar:CbteHasta>",
        f"<ar:CbteFch>{_fecha_arca(c['fecha'])}</ar:CbteFch>",
        f"<ar:ImpTotal>{_importe(c['total'])}</ar:ImpTotal>",
        "<ar:ImpTotConc>0.00</ar:ImpTotConc>",
        f"<ar:ImpNeto>{_importe(c['neto'])}</ar:ImpNeto>",
        "<ar:ImpOpEx>0.00</ar:ImpOpEx><ar:ImpTrib>0.00</ar:ImpTrib>",
        f"<ar:ImpIVA>{_importe(c['iva'])}</ar:ImpIVA>",
    ]
    if c["concepto"] in (2, 3):
        partes.append(f"<ar:FchServDesde>{_fecha_arca(c['serv_desde'])}</ar:FchServDesde>"
                      f"<ar:FchServHasta>{_fecha_arca(c['serv_hasta'])}</ar:FchServHasta>"
                      f"<ar:FchVtoPago>{_fecha_arca(c['vto_pago'])}</ar:FchVtoPago>")
    partes.append("<ar:MonId>PES</ar:MonId><ar:MonCotiz>1</ar:MonCotiz>")
    partes.append(f"<ar:CondicionIVAReceptorId>{CONDICION_IVA_RECEPTOR[c['cliente_condicion_iva']]}"
                  "</ar:CondicionIVAReceptorId>")
    if asociada is not None:  # nota de crédito: la factura que anula
        partes.append(f"<ar:CbtesAsoc><ar:CbteAsoc><ar:Tipo>{asociada['cbte_tipo']}</ar:Tipo>"
                      f"<ar:PtoVta>{asociada['punto_venta']}</ar:PtoVta><ar:Nro>{asociada['numero']}</ar:Nro>"
                      f"<ar:Cuit>{EMISOR['cuit']}</ar:Cuit><ar:CbteFch>{_fecha_arca(asociada['fecha'])}"
                      "</ar:CbteFch></ar:CbteAsoc></ar:CbtesAsoc>")
    partes.append(f"<ar:Iva><ar:AlicIva><ar:Id>{IVA_21}</ar:Id><ar:BaseImp>{_importe(c['neto'])}</ar:BaseImp>"
                  f"<ar:Importe>{_importe(c['iva'])}</ar:Importe></ar:AlicIva></ar:Iva>")
    return "<ar:FECAEDetRequest>" + "".join(partes) + "</ar:FECAEDetRequest>"


def solicitar_cae(instance, ambiente, c, numero, asociada=None):
    """Pide el CAE. Devuelve {"cae", "cae_vto", "observaciones"} o lanza ErrorArca con el motivo."""
    contenido = (f"<ar:FeCAEReq><ar:FeCabReq><ar:CantReg>1</ar:CantReg><ar:PtoVta>{c['punto_venta']}"
                 f"</ar:PtoVta><ar:CbteTipo>{c['cbte_tipo']}</ar:CbteTipo></ar:FeCabReq><ar:FeDetReq>"
                 + detalle_comprobante(c, numero, asociada) + "</ar:FeDetReq></ar:FeCAEReq>")
    raiz = _wsfe(instance, ambiente, "FECAESolicitar", contenido)
    errores = _errores(raiz)
    observaciones = _errores(raiz, "Observaciones", "Obs")
    detalle = _buscar(raiz, "FECAEDetResponse")
    resultado = _texto(detalle, "Resultado") if detalle is not None else ""
    if resultado != "A":
        motivos = (errores + observaciones) or ["ARCA no aceptó el comprobante y no dijo por qué."]
        raise ErrorArca("ARCA rechazó el comprobante: " + "; ".join(motivos))
    return {"cae": _texto(detalle, "CAE"), "cae_vto": _fecha_iso(_texto(detalle, "CAEFchVto")),
            "observaciones": observaciones}
