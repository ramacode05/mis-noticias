"""Validaciones de datos argentinos."""
import re

CONDICIONES_IVA = {
    "RI": "Responsable Inscripto",
    "MT": "Monotributista",
    "EX": "Exento",
    "CF": "Consumidor Final",
}

TIPOS_DOC = {
    "CUIT": "CUIT",
    "DNI": "DNI",
    "SIN": "Sin documento",
}


def solo_digitos(texto):
    return re.sub(r"\D", "", texto or "")


def cuit_valido(cuit):
    """Verifica que el CUIT tenga 11 dígitos y el dígito verificador correcto."""
    cuit = solo_digitos(cuit)
    if len(cuit) != 11:
        return False
    pesos = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]
    suma = sum(int(d) * p for d, p in zip(cuit[:10], pesos))
    verificador = 11 - suma % 11
    if verificador == 11:
        verificador = 0
    elif verificador == 10:
        return False
    return verificador == int(cuit[10])


def formatear_cuit(cuit):
    cuit = solo_digitos(cuit)
    if len(cuit) != 11:
        return cuit
    return f"{cuit[:2]}-{cuit[2:10]}-{cuit[10]}"


def letra_factura(condicion_iva):
    """Una empresa Responsable Inscripta emite A a otro RI y B al resto."""
    return "A" if condicion_iva == "RI" else "B"


def validar_cliente(datos):
    """Devuelve (datos_limpios, errores). errores es un dict campo -> mensaje."""
    limpio = {
        "razon_social": (datos.get("razon_social") or "").strip(),
        "condicion_iva": datos.get("condicion_iva") or "",
        "tipo_doc": datos.get("tipo_doc") or "",
        "nro_doc": solo_digitos(datos.get("nro_doc")),
        "domicilio": (datos.get("domicilio") or "").strip(),
        "localidad": (datos.get("localidad") or "").strip(),
        "email": (datos.get("email") or "").strip(),
        "telefono": (datos.get("telefono") or "").strip(),
        "observaciones": (datos.get("observaciones") or "").strip(),
        "activo": 1 if datos.get("activo") else 0,
    }
    errores = {}

    if not limpio["razon_social"]:
        errores["razon_social"] = "Ingresá el nombre o razón social."

    cond = limpio["condicion_iva"]
    if cond not in CONDICIONES_IVA:
        errores["condicion_iva"] = "Elegí la condición frente al IVA."

    tipo = limpio["tipo_doc"]
    nro = limpio["nro_doc"]
    if tipo not in TIPOS_DOC:
        errores["tipo_doc"] = "Elegí el tipo de documento."
    elif tipo == "CUIT":
        if not cuit_valido(nro):
            errores["nro_doc"] = "El CUIT no es válido (revisá los 11 números)."
    elif tipo == "DNI":
        if not 7 <= len(nro) <= 8:
            errores["nro_doc"] = "El DNI debe tener 7 u 8 números."
    elif tipo == "SIN":
        limpio["nro_doc"] = ""

    # ARCA exige CUIT para Factura A, Monotributo y Exento.
    if cond in ("RI", "MT", "EX") and tipo != "CUIT" and "tipo_doc" not in errores:
        errores["tipo_doc"] = f"Un cliente {CONDICIONES_IVA[cond]} debe tener CUIT."

    if limpio["email"] and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", limpio["email"]):
        errores["email"] = "El email no parece válido."

    return limpio, errores
