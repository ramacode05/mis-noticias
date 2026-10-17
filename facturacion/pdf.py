"""PDF de la factura con el mismo diseño que el de ARCA (Comprobantes en Línea).

Una hoja A4 por copia (ORIGINAL, DUPLICADO, TRIPLICADO). Si los renglones no entran en
una hoja, la copia sigue en otra ("Pág. 1/2"), y los totales van en la última.
Las facturas de prueba llevan la marca "PRUEBA - SIN VALIDEZ FISCAL" y no tienen QR.
"""
import base64
import io
import json
from datetime import date

from reportlab.graphics import renderPDF
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib.colors import Color, black
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen.canvas import Canvas

from .emisor import EMISOR
from .validaciones import CONDICIONES_IVA

ANCHO, ALTO = A4
IZQ, DER = 15, ANCHO - 15
GRIS = Color(0.82, 0.82, 0.82)
COPIAS = ("ORIGINAL", "DUPLICADO", "TRIPLICADO")
TIPO_DOC_ARCA = {"CUIT": 80, "DNI": 96, "SIN": 99}
# Dirección que ARCA indica para el código QR (RG 4892/2020).
URL_QR = "https://www.afip.gob.ar/fe/qr/"

# Columnas del detalle: (título, x izquierda, x derecha, alineación)
COLUMNAS = [
    ("Código", IZQ, 55, "izq"),
    ("Producto / Servicio", 55, 228, "izq"),
    ("Cantidad", 228, 280, "der"),
    ("U. medida", 280, 322, "izq"),
    ("Precio Unit.", 322, 385, "der"),
    ("% Bonif", 385, 415, "der"),
    ("Subtotal", 415, 474, "der"),
    ("Alicuota\nIVA", 474, 512, "centro"),
    ("Subtotal c/IVA", 512, DER, "der"),
]
DETALLE_ARRIBA = 540     # donde empiezan los renglones
DETALLE_ABAJO = 342      # donde empieza el cuadro de totales
INTERLINEA = 9


def nombre_condicion(codigo):
    nombre = CONDICIONES_IVA.get(codigo, codigo)
    return "IVA Responsable Inscripto" if codigo == "RI" else nombre


def fecha(iso):
    return date.fromisoformat(iso).strftime("%d/%m/%Y") if iso else ""


def importe(centavos):
    """Como ARCA: sin puntos de miles y con coma decimal (150000,00)."""
    signo = "-" if centavos < 0 else ""
    centavos = abs(centavos)
    return f"{signo}{centavos // 100},{centavos % 100:02d}"


def cantidad(centesimos):
    return importe(centesimos)  # mismo formato: 1,00 / 2,50


def nombre_archivo(f):
    """Igual que ARCA: CUIT_TIPO_PTOVTA_NUMERO.pdf"""
    nombre = f"{EMISOR['cuit']}_{f['cbte_tipo']:03d}_{f['punto_venta']:05d}_{f['numero']:08d}"
    return nombre + ("_PRUEBA" if f["prueba"] else "") + ".pdf"


def datos_qr(f):
    """Texto del código QR según la especificación de ARCA (solo con CAE)."""
    datos = {
        "ver": 1, "fecha": f["fecha"], "cuit": int(EMISOR["cuit"]),
        "ptoVta": f["punto_venta"], "tipoCmp": f["cbte_tipo"], "nroCmp": f["numero"],
        "importe": round(f["total"] / 100, 2), "moneda": "PES", "ctz": 1,
        "tipoDocRec": TIPO_DOC_ARCA.get(f["cliente_tipo_doc"], 99),
        "nroDocRec": int(f["cliente_nro_doc"] or 0),
        "tipoCodAut": "E", "codAut": int(f["cae"]),
    }
    codigo = base64.b64encode(json.dumps(datos, separators=(",", ":")).encode()).decode()
    return f"{URL_QR}?p={codigo}"


# --- Dibujo ------------------------------------------------------------------------------

def texto(c, x, y, cadena, tam=8, negrita=False, alinear="izq", cursiva=False):
    fuente = "Helvetica" + ("-BoldOblique" if negrita and cursiva else "-Bold" if negrita
                            else "-Oblique" if cursiva else "")
    c.setFont(fuente, tam)
    if alinear == "der":
        c.drawRightString(x, y, cadena)
    elif alinear == "centro":
        c.drawCentredString(x, y, cadena)
    else:
        c.drawString(x, y, cadena)


def etiqueta_valor(c, x, y, etiqueta, valor, tam=8, ancho_valor=None, tam_valor=None):
    """Dibuja "Etiqueta: valor" con la etiqueta en negrita. Devuelve la y de la última línea."""
    texto(c, x, y, etiqueta, tam, negrita=True)
    x_valor = x + c.stringWidth(etiqueta, "Helvetica-Bold", tam) + 4
    tam_valor = tam_valor or tam
    lineas = simpleSplit(valor, "Helvetica", tam_valor, ancho_valor) if ancho_valor else [valor]
    for i, linea in enumerate(lineas):
        texto(c, x_valor, y - i * (tam_valor + 2), linea, tam_valor)
    return y - (len(lineas) - 1) * (tam_valor + 2)


def marca_de_agua(c):
    c.saveState()
    c.setFillColor(Color(0.85, 0.15, 0.15, alpha=0.13))
    c.translate(ANCHO / 2, ALTO / 2)
    c.rotate(40)
    c.setFont("Helvetica-Bold", 54)
    c.drawCentredString(0, 20, "PRUEBA")
    c.setFont("Helvetica-Bold", 30)
    c.drawCentredString(0, -25, "SIN VALIDEZ FISCAL")
    c.restoreState()


def encabezado(c, f, copia):
    """Recuadros de arriba: copia, emisor, letra, datos del comprobante, período y receptor."""
    c.setLineWidth(0.8)
    # Copia
    c.rect(IZQ, 797, DER - IZQ, 27)
    texto(c, ANCHO / 2, 805, copia, 13, negrita=True, alinear="centro")

    # Emisor y comprobante
    c.rect(IZQ, 680, DER - IZQ, 117)
    medio = ANCHO / 2
    c.rect(medio - 23, 755, 46, 42)
    texto(c, medio, 772, f["letra"], 24, negrita=True, alinear="centro")
    texto(c, medio, 759, f"COD. {f['cbte_tipo']:02d}", 7, negrita=True, alinear="centro")
    c.line(medio, 680, medio, 755)

    texto(c, (IZQ + medio - 23) / 2, 772, EMISOR["nombre_fantasia"], 10, negrita=True, alinear="centro")
    etiqueta_valor(c, IZQ + 8, 742, "Razón Social:", EMISOR["razon_social"], 8, ancho_valor=200)
    etiqueta_valor(c, IZQ + 8, 715, "Domicilio Comercial:", EMISOR["domicilio"], 8, ancho_valor=180)
    texto(c, IZQ + 8, 688, "Condición frente al IVA:", 8, negrita=True)
    texto(c, IZQ + 112, 688, EMISOR["condicion_iva"], 8, negrita=True)

    x = medio + 36
    texto(c, x, 772, "FACTURA", 18, negrita=True)
    texto(c, x, 750, "Punto de Venta:", 8, negrita=True)
    texto(c, x + 68, 750, f"{f['punto_venta']:05d}", 9, negrita=True)
    texto(c, x + 128, 750, "Comp. Nro:", 8, negrita=True)
    texto(c, x + 176, 750, f"{f['numero']:08d}", 9, negrita=True)
    texto(c, x, 735, "Fecha de Emisión:", 8, negrita=True)
    texto(c, x + 78, 735, fecha(f["fecha"]), 9, negrita=True)
    etiqueta_valor(c, x, 714, "CUIT:", EMISOR["cuit"], 8)
    etiqueta_valor(c, x, 702, "Ingresos Brutos:", EMISOR["ingresos_brutos"], 8)
    etiqueta_valor(c, x, 690, "Fecha de Inicio de Actividades:", fecha(EMISOR["inicio_actividades"]), 8)

    # Período facturado (solo si hay servicios)
    c.rect(IZQ, 657, DER - IZQ, 23)
    if f["serv_desde"]:
        texto(c, IZQ + 8, 665, "Período Facturado Desde:", 9, negrita=True)
        texto(c, IZQ + 140, 665, fecha(f["serv_desde"]), 9)
        texto(c, IZQ + 210, 665, "Hasta:", 9, negrita=True)
        texto(c, IZQ + 242, 665, fecha(f["serv_hasta"]), 9)
        texto(c, IZQ + 330, 665, "Fecha de Vto. para el pago:", 9, negrita=True)
        texto(c, IZQ + 472, 665, fecha(f["vto_pago"]), 9)

    # Receptor
    c.rect(IZQ, 597, DER - IZQ, 58)
    if f["cliente_tipo_doc"] != "SIN":
        etiqueta_valor(c, IZQ + 8, 643, f"{f['cliente_tipo_doc']}:", f["cliente_nro_doc"], 7.5)
    etiqueta_valor(c, 230, 643, "Apellido y Nombre / Razón Social:", f["cliente_razon_social"], 7.5,
                   ancho_valor=210)
    texto(c, IZQ + 8, 625, "Condición frente al IVA:", 7.5, negrita=True)
    texto(c, IZQ + 112, 625, nombre_condicion(f["cliente_condicion_iva"]), 7.5)
    etiqueta_valor(c, 255, 625, "Domicilio Comercial:", f["cliente_domicilio"], 7.5, ancho_valor=245)
    texto(c, IZQ + 8, 607, "Condición de venta:", 7.5, negrita=True)
    texto(c, IZQ + 112, 607, f["condicion_venta"], 7.5)
    if f["remito_numero"]:
        etiqueta_valor(c, 275, 607, "Remito:", f"{f['remito_pto_vta']:05d}-{f['remito_numero']:08d}", 7.5)

    # Títulos del detalle
    c.setFillColor(GRIS)
    c.rect(IZQ, 549, DER - IZQ, 17, fill=1, stroke=1)
    c.setFillColor(black)
    for titulo, x1, x2, alinear in COLUMNAS:
        if x1 > IZQ:
            c.line(x1, 549, x1, 566)
        lineas = titulo.split("\n")
        y = 555 if len(lineas) == 1 else 559
        for i, linea in enumerate(lineas):
            if titulo.startswith("Producto") or titulo == "Código":
                texto(c, x1 + 4, y, linea, 7.5, negrita=True)
            else:
                tam = 7 if len(lineas) > 1 or c.stringWidth(linea, "Helvetica-Bold", 7.5) > x2 - x1 - 4 else 7.5
                texto(c, (x1 + x2) / 2, y - i * 8, linea, tam, negrita=True, alinear="centro")


def armar_filas(renglones):
    """Prepara cada renglón con su descripción partida en líneas y su alto."""
    _, x1, x2, _ = COLUMNAS[1]
    filas = []
    for r in renglones:
        lineas = simpleSplit(r["descripcion"], "Helvetica", 7.5, x2 - x1 - 6) or [""]
        iva = round(r["subtotal"] * 21 / 100)
        filas.append({
            "lineas": lineas, "alto": len(lineas) * INTERLINEA + 6,
            "valores": ["", None, cantidad(r["cantidad"]), "unidades", importe(r["precio_unitario"]),
                        "0,00", importe(r["subtotal"]), "21%", importe(r["subtotal"] + iva)],
        })
    return filas


def paginar(filas):
    disponible = DETALLE_ARRIBA - DETALLE_ABAJO - 4
    paginas, actual, usado = [], [], 0
    for fila in filas:
        if actual and usado + fila["alto"] > disponible:
            paginas.append(actual)
            actual, usado = [], 0
        actual.append(fila)
        usado += fila["alto"]
    paginas.append(actual)
    return paginas


def detalle(c, filas):
    y = DETALLE_ARRIBA
    for fila in filas:
        for (titulo, x1, x2, alinear), valor in zip(COLUMNAS, fila["valores"]):
            if valor is None:  # descripción
                for i, linea in enumerate(fila["lineas"]):
                    texto(c, x1 + 4, y - i * INTERLINEA, linea, 7.5)
            elif alinear == "der":
                texto(c, x2 - 4, y, valor, 7.5, alinear="der")
            elif alinear == "centro":
                texto(c, (x1 + x2) / 2, y, valor, 7.5, alinear="centro")
            else:
                texto(c, x1 + 4, y, valor, 7)
        y -= fila["alto"]


def totales(c, f):
    c.rect(IZQ, 170, DER - IZQ, DETALLE_ABAJO - 170)
    texto(c, 300, 312, "Importe Otros Tributos: $", 8, alinear="der")
    texto(c, 330, 312, "0,00", 8)
    filas = [("Importe Neto Gravado: $", f["neto"]), ("IVA 27%: $", 0), ("IVA 21%: $", f["iva"]),
             ("IVA 10.5%: $", 0), ("IVA 5%: $", 0), ("IVA 2.5%: $", 0), ("IVA 0%: $", 0),
             ("Importe Otros Tributos: $", 0)]
    y = 290
    for etiqueta, valor in filas:
        texto(c, 500, y, etiqueta, 8.5, negrita=True, alinear="der")
        texto(c, DER - 6, y, importe(valor), 8.5, negrita=True, alinear="der")
        y -= 13.5
    texto(c, 500, y - 2, "Importe Total: $", 10, negrita=True, alinear="der")
    texto(c, DER - 6, y - 2, importe(f["total"]), 10, negrita=True, alinear="der")


def pie(c, f, pagina, total_paginas, ultima):
    texto(c, ANCHO / 2 - 18, 150, f"Pág. {pagina}/{total_paginas}", 8.5, negrita=True, alinear="centro")
    if not ultima:
        texto(c, ANCHO / 2, DETALLE_ABAJO + 6, "Continúa en la página siguiente", 7.5, cursiva=True,
              alinear="centro")
    if f["cae"]:
        qr = QrCodeWidget(datos_qr(f), barLevel="M")
        x1, y1, x2, y2 = qr.getBounds()
        tam = 75
        dibujo = Drawing(tam, tam, transform=[tam / (x2 - x1), 0, 0, tam / (y2 - y1), 0, 0])
        dibujo.add(qr)
        renderPDF.draw(dibujo, c, IZQ + 8, 85)
        texto(c, 115, 112, "Comprobante Autorizado", 8, negrita=True, cursiva=True)
        etiqueta_valor(c, 410, 148, "CAE N°:", f["cae"], 9)
        etiqueta_valor(c, 372, 133, "Fecha de Vto. de CAE:", fecha(f["cae_vto"]), 9)
    else:
        c.setDash(2, 2)
        c.rect(IZQ + 8, 85, 75, 75)
        c.setDash()
        texto(c, IZQ + 45.5, 126, "Código QR", 7, alinear="centro")
        texto(c, IZQ + 45.5, 116, "(se genera con", 7, alinear="centro")
        texto(c, IZQ + 45.5, 107, "el CAE de ARCA)", 7, alinear="centro")
        etiqueta_valor(c, 372, 148, "CAE N°:", "sin CAE", 9)
        texto(c, 372, 133, "Comprobante de prueba, sin validez fiscal", 8, cursiva=True)


def generar_pdf(f, renglones, copias=COPIAS):
    """Devuelve el PDF (bytes) de la factura f con sus renglones."""
    salida = io.BytesIO()
    c = Canvas(salida, pagesize=A4)
    c.setTitle(f"Factura {f['letra']} {f['punto_venta']:05d}-{f['numero']:08d}")
    c.setAuthor(EMISOR["nombre_fantasia"])
    paginas = paginar(armar_filas(renglones))
    for copia in copias:
        for n, filas in enumerate(paginas, start=1):
            if f["prueba"]:
                marca_de_agua(c)
            encabezado(c, f, copia)
            detalle(c, filas)
            ultima = n == len(paginas)
            if ultima:
                totales(c, f)
            else:
                c.rect(IZQ, 170, DER - IZQ, DETALLE_ABAJO - 170)
            pie(c, f, n, len(paginas), ultima)
            c.showPage()
    c.save()
    return salida.getvalue()
