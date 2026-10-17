"""Pruebas de la etapa 8 (resumen mensual y Excel). Correr con: python -m unittest discover tests"""
import io
import unittest
import zipfile
from datetime import date
from xml.etree import ElementTree

from facturacion.excel import Negrita, Pesos, libro, nombre_columna
from tests.test_facturas import HOY, BaseFacturas

MES = date.today().strftime("%Y-%m")
NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def leer_hoja(datos, numero):
    """Devuelve las celdas de una hoja como lista de listas de textos (para las pruebas)."""
    with zipfile.ZipFile(io.BytesIO(datos)) as z:
        raiz = ElementTree.fromstring(z.read(f"xl/worksheets/sheet{numero}.xml"))
    filas = []
    for fila in raiz.iterfind(".//x:row", NS):
        valores = []
        for c in fila.iterfind("x:c", NS):
            t = c.find(".//x:t", NS)
            v = c.find("x:v", NS)
            valores.append(t.text if t is not None else v.text)
        filas.append(valores)
    return filas


class ExcelTest(unittest.TestCase):
    def test_columnas(self):
        self.assertEqual([nombre_columna(n) for n in (0, 25, 26, 27)], ["A", "Z", "AA", "AB"])

    def test_libro_valido(self):
        datos = libro([("Hoja <1>", [[Negrita("Título & más")], ["Texto", 3, Pesos(12345)]]),
                       ("Otra", [])])
        with zipfile.ZipFile(io.BytesIO(datos)) as z:
            self.assertIn("xl/worksheets/sheet2.xml", z.namelist())
            for nombre in z.namelist():  # todos los XML se pueden leer
                ElementTree.fromstring(z.read(nombre))
        self.assertEqual(leer_hoja(datos, 1), [["Título & más"], ["Texto", "3", "123.45"]])


class ResumenTest(BaseFacturas):
    def armar(self):
        self.confirmar()                       # A: neto 60.000
        self.confirmar()
        self.confirmar(cliente_id="2")         # B
        self.cli.post("/facturas/2/nota-credito", data={"fecha": HOY, "token": "nc"})
        self.cli.post("/cobros/nuevo", data={"cliente": "1", "factura": "1", "fecha": HOY,
                                             "medio": "Transferencia", "referencia": "T1", "token": "c"})

    def test_pantalla(self):
        self.armar()
        html = self.cli.get(f"/resumen/?mes={MES}").get_data(as_text=True)
        self.assertIn("Resumen de ", html)
        ventas = html.split("Ventas del mes")[1].split("Cobros del mes")[0]
        self.assertIn("Factura A", ventas)
        self.assertIn("Nota de Crédito A", ventas)
        self.assertIn("Factura B", ventas)
        self.assertIn("$ 120.000,00", ventas)      # neto facturas A
        self.assertIn("$ -60.000,00", ventas)      # neto NC A
        self.assertIn("$ 145.200,00", ventas)      # total: 3 x 72.600 - 72.600
        self.assertIn("$ 72.600,00", html.split("Cobros del mes")[1])
        self.assertIn("PRUEBA", html)

    def test_mes_sin_movimientos_y_mes_invalido(self):
        html = self.cli.get("/resumen/?mes=2000-01").get_data(as_text=True)
        self.assertIn("No hay comprobantes en enero 2000", html)
        self.assertEqual(self.cli.get("/resumen/?mes=basura").status_code, 200)

    def test_excel(self):
        self.armar()
        r = self.cli.get(f"/resumen/excel?mes={MES}")
        self.assertEqual(r.status_code, 200)
        self.assertIn(f"resumen_{MES}.xlsx", r.headers["Content-Disposition"])
        resumen = leer_hoja(r.data, 1)
        self.assertIn(["Total del mes", "120000.00", "25200.00", "145200.00"], resumen)
        comprobantes = leer_hoja(r.data, 2)
        self.assertEqual(len(comprobantes), 5)     # títulos + 3 facturas + 1 NC
        nota = [f for f in comprobantes if f[1] == "Nota de Crédito A"]
        self.assertEqual(len(nota), 1)
        self.assertIn("-72600.00", nota[0])
        self.assertIn("Responsable Inscripto", comprobantes[1])
        self.assertIn("30-71234567-1", comprobantes[1])
        cobros = leer_hoja(r.data, 3)
        self.assertEqual(cobros[1][1:], ["Transportes Sur SA", "Transferencia", "T1", "72600.00"])
