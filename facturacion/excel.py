"""Archivos de Excel (.xlsx) armados solo con Python, sin instalar nada.

Un .xlsx es un ZIP con algunos archivos XML adentro. Acá se arma lo mínimo: varias hojas
con textos, números e importes en pesos (formato 1.234,56 según la configuración de la PC),
títulos en negrita y ancho de columnas.

Uso:
    datos = libro([("Resumen", [["Concepto", "Total"], ["Ventas", Pesos(12345)]])])
"""
import io
import zipfile
from xml.sax.saxutils import escape


class Pesos(int):
    """Importe en centavos que se muestra en Excel como pesos con 2 decimales."""


class Negrita(str):
    """Texto en negrita (para títulos)."""


ESTILOS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<numFmts count="1"><numFmt numFmtId="164" formatCode="#,##0.00"/></numFmts>
<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts>
<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>
<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="3">
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>
<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
</cellXfs>
<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>"""


def nombre_columna(n):
    """0 -> A, 25 -> Z, 26 -> AA"""
    letras = ""
    n += 1
    while n:
        n, resto = divmod(n - 1, 26)
        letras = chr(65 + resto) + letras
    return letras


def celda(ref, valor):
    if valor is None or valor == "":
        return ""
    if isinstance(valor, Pesos):
        return f'<c r="{ref}" s="2"><v>{int(valor) / 100:.2f}</v></c>'
    if isinstance(valor, bool):
        valor = "Sí" if valor else "No"
    if isinstance(valor, (int, float)):
        return f'<c r="{ref}"><v>{valor}</v></c>'
    estilo = ' s="1"' if isinstance(valor, Negrita) else ""
    return f'<c r="{ref}" t="inlineStr"{estilo}><is><t xml:space="preserve">{escape(str(valor))}</t></is></c>'


def hoja(filas):
    anchos = {}
    for fila in filas:
        if sum(1 for v in fila if v not in (None, "")) <= 1:
            continue  # títulos y notas de una sola celda no definen el ancho de la columna
        for i, valor in enumerate(fila):
            largo = len(f"{int(valor) / 100:,.2f}") if isinstance(valor, Pesos) else len(str(valor or ""))
            anchos[i] = min(max(anchos.get(i, 8), largo + 2), 60)
    columnas = "".join(f'<col min="{i + 1}" max="{i + 1}" width="{w}" customWidth="1"/>'
                       for i, w in sorted(anchos.items()))
    renglones = []
    for r, fila in enumerate(filas, start=1):
        celdas = "".join(celda(f"{nombre_columna(c)}{r}", v) for c, v in enumerate(fila))
        renglones.append(f'<row r="{r}">{celdas}</row>')
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            + (f"<cols>{columnas}</cols>" if columnas else "")
            + f'<sheetData>{"".join(renglones)}</sheetData></worksheet>')


def libro(hojas):
    """hojas: lista de (nombre, filas). Devuelve los bytes del archivo .xlsx."""
    salida = io.BytesIO()
    with zipfile.ZipFile(salida, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                   '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                   + "".join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                             for i in range(1, len(hojas) + 1))
                   + "</Types>")
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                   "</Relationships>")
        z.writestr("xl/workbook.xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                   + "".join(f'<sheet name="{escape(nombre[:31])}" sheetId="{i}" r:id="rId{i}"/>'
                             for i, (nombre, _) in enumerate(hojas, start=1))
                   + "</sheets></workbook>")
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + "".join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
                             for i in range(1, len(hojas) + 1))
                   + f'<Relationship Id="rId{len(hojas) + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
                   "</Relationships>")
        z.writestr("xl/styles.xml", ESTILOS)
        for i, (_, filas) in enumerate(hojas, start=1):
            z.writestr(f"xl/worksheets/sheet{i}.xml", hoja(filas))
    return salida.getvalue()
