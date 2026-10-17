"""PDF de la factura con el mismo diseño que el de ARCA (Comprobantes en Línea).

Las posiciones y tamaños están medidos sobre un PDF real de RCEL (factura A 00002-00003731).
Una hoja A4 por copia (ORIGINAL, DUPLICADO, TRIPLICADO). Si los renglones no entran en
una hoja, la copia sigue en otra ("Pág. 1/2"), y los totales van en la última.

Factura A: precios sin IVA, columnas de alícuota y subtotal con IVA, IVA discriminado.
Factura B: precios con IVA incluido, sin columnas de IVA, y el recuadro del "Régimen de
Transparencia Fiscal al Consumidor (Ley 27.743)" con el IVA contenido.

No lleva el logo de ARCA ni su leyenda: eso lo agrega ARCA solo a los PDF de su web.
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

ANCHO, ALTO = A4
IZQ, DER = 15, ANCHO - 15
MEDIO = ANCHO / 2
GRIS = Color(0.82, 0.82, 0.82)
COPIAS = ("ORIGINAL", "DUPLICADO", "TRIPLICADO")
TIPO_DOC_ARCA = {"CUIT": 80, "DNI": 96, "SIN": 99}
# Cómo escribe ARCA cada condición frente al IVA.
CONDICION_ARCA = {"RI": "IVA Responsable Inscripto", "MT": "Responsable Monotributo",
                  "EX": "IVA Sujeto Exento", "CF": "Consumidor Final"}
# Dirección que ARCA indica para el código QR (RG 4892/2020).
URL_QR = "https://www.afip.gob.ar/fe/qr/"

# Columnas del detalle: (título, x izquierda, x derecha, alineación del valor)
COLUMNAS_A = [
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
COLUMNAS_B = [
    ("Código", IZQ, 55, "izq"),
    ("Producto / Servicio", 55, 260, "izq"),
    ("Cantidad", 260, 315, "der"),
    ("U. medida", 315, 360, "izq"),
    ("Precio Unit.", 360, 430, "der"),
    ("% Bonif", 430, 465, "der"),
    ("Imp. Bonif.", 465, 515, "der"),
    ("Subtotal", 515, DER, "der"),
]
DETALLE_ARRIBA = 534.5     # línea base del primer renglón
TOTALES_ARRIBA = 333     # borde de arriba del cuadro de totales
TOTALES_ABAJO = 170
INTERLINEA = 7.9         # entre líneas de una misma descripción
MARGEN_RENGLON = 8.5     # espacio extra de cada renglón


def fecha(iso):
    return date.fromisoformat(iso).strftime("%d/%m/%Y") if iso else ""


def importe(centavos):
    """Como ARCA: sin puntos de miles y con coma decimal (150000,00)."""
    signo = "-" if centavos < 0 else ""
    centavos = abs(centavos)
    return f"{signo}{centavos // 100},{centavos % 100:02d}"


def cantidad(centesimos):
    return importe(centesimos)  # mismo formato: 1,00 / 2,50


def con_iva(centavos):
    return centavos + round(centavos * 21 / 100)


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

def fuente(negrita=False, cursiva=False):
    return "Helvetica" + ("-BoldOblique" if negrita and cursiva else "-Bold" if negrita
                          else "-Oblique" if cursiva else "")


def texto(c, x, y, cadena, tam=8, negrita=False, alinear="izq", cursiva=False):
    c.setFont(fuente(negrita, cursiva), tam)
    if alinear == "der":
        c.drawRightString(x, y, cadena)
    elif alinear == "centro":
        c.drawCentredString(x, y, cadena)
    else:
        c.drawString(x, y, cadena)


def etiqueta_valor(c, x, y, etiqueta, valor, tam=8, tam_valor=None, negrita_valor=False,
                   ancho_valor=None, separacion=4):
    """Dibuja "Etiqueta: valor" con la etiqueta en negrita (el valor puede ocupar varias líneas)."""
    texto(c, x, y, etiqueta, tam, negrita=True)
    x_valor = x + c.stringWidth(etiqueta, fuente(True), tam) + separacion
    tam_valor = tam_valor or tam
    lineas = (simpleSplit(valor, fuente(negrita_valor), tam_valor, ancho_valor)
              if ancho_valor else [valor])
    for i, linea in enumerate(lineas):
        texto(c, x_valor, y - i * (tam_valor + 1.5), linea, tam_valor, negrita=negrita_valor)


def marca_de_agua(c):
    c.saveState()
    c.setFillColor(Color(0.85, 0.15, 0.15, alpha=0.13))
    c.translate(MEDIO, ALTO / 2)
    c.rotate(40)
    c.setFont("Helvetica-Bold", 54)
    c.drawCentredString(0, 20, "PRUEBA")
    c.setFont("Helvetica-Bold", 30)
    c.drawCentredString(0, -25, "SIN VALIDEZ FISCAL")
    c.restoreState()


def encabezado(c, f, copia, columnas):
    """Recuadros de arriba: copia, emisor, letra, datos del comprobante, período y receptor."""
    c.setLineWidth(0.8)
    # Copia
    c.rect(IZQ, 797, DER - IZQ, 27)
    texto(c, MEDIO, 805, copia, 13, negrita=True, alinear="centro")

    # Emisor y comprobante
    c.rect(IZQ, 679, DER - IZQ, 118)
    c.rect(MEDIO - 23, 756, 46, 41)
    texto(c, MEDIO, 773, f["letra"], 24, negrita=True, alinear="centro")
    texto(c, MEDIO, 761, f"COD. {f['cbte_tipo']:02d}", 7, negrita=True, alinear="centro")
    c.line(MEDIO, 679, MEDIO, 756)

    texto(c, (IZQ + MEDIO - 23) / 2, 772, EMISOR["nombre_fantasia"], 10, negrita=True,
          alinear="centro")
    etiqueta_valor(c, IZQ + 7, 733, "Razón Social:", EMISOR["razon_social"], 9, ancho_valor=195)
    etiqueta_valor(c, IZQ + 7, 708, "Domicilio Comercial:", EMISOR["domicilio"], 9, ancho_valor=180)
    etiqueta_valor(c, IZQ + 7, 684, "Condición frente al IVA:", EMISOR["condicion_iva"], 9,
                   negrita_valor=True, separacion=7)

    x = MEDIO + 44
    texto(c, x - 2, 768, "FACTURA", 19, negrita=True)
    texto(c, x, 749, "Punto de Venta:", 9, negrita=True)
    texto(c, 417, 749, f"{f['punto_venta']:05d}", 10.5, negrita=True)
    texto(c, 461, 749, "Comp. Nro:", 9, negrita=True)
    texto(c, 517, 749, f"{f['numero']:08d}", 10.5, negrita=True)
    texto(c, x, 733, "Fecha de Emisión:", 9, negrita=True)
    texto(c, 428, 733, fecha(f["fecha"]), 10.5, negrita=True)
    etiqueta_valor(c, x, 711, "CUIT:", EMISOR["cuit"], 9, separacion=7)
    etiqueta_valor(c, x, 699, "Ingresos Brutos:", EMISOR["ingresos_brutos"], 9)
    etiqueta_valor(c, x, 687, "Fecha de Inicio de Actividades:", fecha(EMISOR["inicio_actividades"]), 9,
                   separacion=7)

    # Período facturado (solo si hay servicios)
    c.rect(IZQ, 655.5, DER - IZQ, 23.5)
    if f["serv_desde"]:
        texto(c, IZQ + 7, 664, "Período Facturado Desde:", 10, negrita=True)
        texto(c, 159, 664, fecha(f["serv_desde"]), 10)
        texto(c, 232, 664, "Hasta:", 10, negrita=True)
        texto(c, 262, 664, fecha(f["serv_hasta"]), 10)
        texto(c, 362.5, 664, "Fecha de Vto. para el pago:", 10, negrita=True)
        texto(c, 495, 664, fecha(f["vto_pago"]), 10)

    # Receptor
    c.rect(IZQ, 592, DER - IZQ, 61.5)
    if f["cliente_tipo_doc"] != "SIN":
        texto(c, IZQ + 7, 644, f"{f['cliente_tipo_doc']}:", 7.5, negrita=True)
        texto(c, 52, 644, f["cliente_nro_doc"], 8)
    etiqueta_valor(c, 222.5, 644, "Apellido y Nombre / Razón Social:", f["cliente_razon_social"], 7.5,
                   tam_valor=8, ancho_valor=225)
    texto(c, IZQ + 7, 627, "Condición frente al IVA:", 7.5, negrita=True)
    texto(c, 131, 627, CONDICION_ARCA.get(f["cliente_condicion_iva"], ""), 8)
    etiqueta_valor(c, 271.5, 627, "Domicilio Comercial:", f["cliente_domicilio"], 7.5, tam_valor=8,
                   ancho_valor=225)
    texto(c, IZQ + 7, 610, "Condición de venta:", 7.5, negrita=True)
    texto(c, 113, 610, f["condicion_venta"], 8)
    if f["remito_numero"]:
        etiqueta_valor(c, 284.5, 608.5, "Remito:", f"{f['remito_pto_vta']:05d}-{f['remito_numero']:08d}",
                       7.5, tam_valor=8, separacion=2)

    # Títulos del detalle
    c.setFillColor(GRIS)
    c.rect(IZQ, 547.5, DER - IZQ, 16.5, fill=1, stroke=1)
    c.setFillColor(black)
    for titulo, x1, x2, _ in columnas:
        if x1 > IZQ:
            c.line(x1, 547.5, x1, 564)
        lineas = titulo.split("\n")
        if titulo in ("Código", "Producto / Servicio"):
            texto(c, x1 + 4, 553, titulo, 7.5, negrita=True)
            continue
        for i, linea in enumerate(lineas):
            tam = 6.5 if len(lineas) > 1 or c.stringWidth(linea, fuente(True), 7.5) > x2 - x1 - 4 else 7.5
            y = 553 if len(lineas) == 1 else 557.5 - i * 7
            texto(c, (x1 + x2) / 2, y, linea, tam, negrita=True, alinear="centro")


def armar_filas(f, renglones, columnas):
    """Prepara cada renglón con su descripción partida en líneas, su alto y sus valores."""
    _, x1, x2, _ = columnas[1]
    filas = []
    for r in renglones:
        lineas = simpleSplit(r["descripcion"], "Helvetica", 7.5, x2 - x1 - 6) or [""]
        if f["letra"] == "A":
            valores = ["", None, cantidad(r["cantidad"]), "unidades", importe(r["precio_unitario"]),
                       "0,00", importe(r["subtotal"]), "21%", importe(con_iva(r["subtotal"]))]
        else:  # En la B los precios van con IVA incluido.
            valores = ["", None, cantidad(r["cantidad"]), "unidades",
                       importe(con_iva(r["precio_unitario"])), "0,00", "0,00",
                       importe(con_iva(r["subtotal"]))]
        filas.append({"lineas": lineas, "alto": (len(lineas) - 1) * INTERLINEA + 8 + MARGEN_RENGLON,
                      "valores": valores})
    return filas


def paginar(filas):
    disponible = DETALLE_ARRIBA - TOTALES_ARRIBA - 4
    paginas, actual, usado = [], [], 0
    for fila in filas:
        if actual and usado + fila["alto"] > disponible:
            paginas.append(actual)
            actual, usado = [], 0
        actual.append(fila)
        usado += fila["alto"]
    paginas.append(actual)
    return paginas


def detalle(c, filas, columnas):
    y = DETALLE_ARRIBA
    for fila in filas:
        for (_, x1, x2, alinear), valor in zip(columnas, fila["valores"]):
            if valor is None:  # descripción
                for i, linea in enumerate(fila["lineas"]):
                    texto(c, x1 + 4, y - i * INTERLINEA, linea, 7.5)
            elif alinear == "der":
                texto(c, x2 - 3, y, valor, 7.5, alinear="der")
            elif alinear == "centro":
                texto(c, (x1 + x2) / 2, y, valor, 7.5, alinear="centro")
            else:
                texto(c, x1 + 4, y, valor, 6.8)
        y -= fila["alto"]


def totales(c, f):
    c.rect(IZQ, TOTALES_ABAJO, DER - IZQ, TOTALES_ARRIBA - TOTALES_ABAJO)
    texto(c, 286.5, 303, "Importe Otros Tributos: $", 9, alinear="der")
    texto(c, 329, 303, "0,00", 9)
    if f["letra"] == "A":
        filas = [("Importe Neto Gravado: $", f["neto"]), ("IVA 27%: $", 0), ("IVA 21%: $", f["iva"]),
                 ("IVA 10.5%: $", 0), ("IVA 5%: $", 0), ("IVA 2.5%: $", 0), ("IVA 0%: $", 0),
                 ("Importe Otros Tributos: $", 0)]
        y = 282
        for etiqueta, valor in filas:
            texto(c, 502.5, y, etiqueta, 9, negrita=True, alinear="der")
            texto(c, 574, y, importe(valor), 9, negrita=True, alinear="der")
            y -= 13.09
    else:
        for y, etiqueta, valor in ((204, "Subtotal: $", f["total"]),
                                   (191, "Importe Otros Tributos: $", 0)):
            texto(c, 502.5, y, etiqueta, 9, negrita=True, alinear="der")
            texto(c, 574, y, importe(valor), 9, negrita=True, alinear="der")
        # Ley 27.743: el IVA que contiene el precio tiene que figurar en la factura B.
        c.rect(IZQ + 8, 226, 300, 40)
        texto(c, IZQ + 14, 255, "Régimen de Transparencia Fiscal al Consumidor (Ley 27.743)", 8, negrita=True,
              cursiva=True)
        etiqueta_valor(c, IZQ + 14, 242, "IVA Contenido: $", importe(f["iva"]), 8)
        etiqueta_valor(c, IZQ + 14, 231, "Otros Impuestos Nacionales Indirectos: $", "0,00", 8)
    texto(c, 502.5, 176.5, "Importe Total: $", 11, negrita=True, alinear="der")
    texto(c, 574, 176.5, importe(f["total"]), 11, negrita=True, alinear="der")


def pie(c, f, pagina, total_paginas, ultima):
    texto(c, 297, 147, f"Pág. {pagina}/{total_paginas}", 9, negrita=True, alinear="centro")
    if not ultima:
        texto(c, MEDIO, TOTALES_ARRIBA + 6, "Continúa en la página siguiente", 7.5, cursiva=True,
              alinear="centro")
    if f["cae"]:
        qr = QrCodeWidget(datos_qr(f), barLevel="M")
        x1, y1, x2, y2 = qr.getBounds()
        tam = 70
        dibujo = Drawing(tam, tam, transform=[tam / (x2 - x1), 0, 0, tam / (y2 - y1), 0, 0])
        dibujo.add(qr)
        renderPDF.draw(dibujo, c, 25, 87)
        texto(c, 114.5, 114, "Comprobante Autorizado", 8.5, negrita=True, cursiva=True)
        texto(c, 482, 143, "CAE N°:", 10, negrita=True, alinear="der")
        texto(c, 486, 143, f["cae"], 10)
        texto(c, 482, 129, "Fecha de Vto. de CAE:", 10, negrita=True, alinear="der")
        texto(c, 486, 129, fecha(f["cae_vto"]), 10)
    else:
        c.setDash(2, 2)
        c.rect(25, 87, 70, 70)
        c.setDash()
        for y, linea in ((126, "Código QR"), (117, "(se genera con"), (108, "el CAE de ARCA)")):
            texto(c, 60, y, linea, 6.5, alinear="centro")
        texto(c, 482, 143, "CAE N°:", 10, negrita=True, alinear="der")
        texto(c, 486, 143, "sin CAE", 10)
        texto(c, 482, 129, "Comprobante de prueba, sin validez fiscal", 8.5, cursiva=True, alinear="der")


def generar_pdf(f, renglones, copias=COPIAS):
    """Devuelve el PDF (bytes) de la factura f con sus renglones."""
    salida = io.BytesIO()
    c = Canvas(salida, pagesize=A4)
    c.setTitle(f"Factura {f['letra']} {f['punto_venta']:05d}-{f['numero']:08d}")
    c.setAuthor(EMISOR["nombre_fantasia"])
    columnas = COLUMNAS_A if f["letra"] == "A" else COLUMNAS_B
    paginas = paginar(armar_filas(f, renglones, columnas))
    for copia in copias:
        for n, filas in enumerate(paginas, start=1):
            if f["prueba"]:
                marca_de_agua(c)
            encabezado(c, f, copia, columnas)
            detalle(c, filas, columnas)
            ultima = n == len(paginas)
            if ultima:
                totales(c, f)
            else:
                c.rect(IZQ, TOTALES_ABAJO, DER - IZQ, TOTALES_ARRIBA - TOTALES_ABAJO)
            pie(c, f, n, len(paginas), ultima)
            c.showPage()
    c.save()
    return salida.getvalue()
