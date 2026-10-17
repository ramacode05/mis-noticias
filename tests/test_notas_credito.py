"""Pruebas de la etapa 5 (notas de crédito). Correr con: python -m unittest discover tests"""
import re
import sqlite3
from datetime import date, timedelta

from tests.test_facturas import AYER, HOY, BaseFacturas

MANANA = (date.today() + timedelta(days=1)).isoformat()


class NotasCreditoTest(BaseFacturas):
    def hacer_nc(self, factura_id=1, **datos):
        datos.setdefault("fecha", HOY)
        datos.setdefault("token", "nc-" + str(factura_id) + datos["fecha"])
        r = self.cli.post(f"/facturas/{factura_id}/nota-credito", data=datos, follow_redirects=True)
        return r.get_data(as_text=True)

    def test_nc_por_el_total_asociada_a_la_factura(self):
        self.confirmar(remito_numero="6575")
        html = self.cli.get("/facturas/1").get_data(as_text=True)
        self.assertIn("Hacer nota de crédito", html)
        html = self.hacer_nc(observaciones="Error en el precio")
        self.assertIn("Nota de Crédito A N° 1 generada (de prueba)", html)
        self.assertIn("anula la", html)
        f, nc = self.facturas()
        self.assertEqual((nc["cbte_tipo"], nc["letra"], nc["numero"], nc["asociado_id"]), (3, "A", 1, 1))
        self.assertEqual((nc["neto"], nc["iva"], nc["total"]), (f["neto"], f["iva"], f["total"]))
        self.assertEqual(nc["cliente_razon_social"], f["cliente_razon_social"])
        self.assertIsNone(nc["remito_numero"])  # el remito es de la factura
        self.assertEqual(nc["observaciones"], "Error en el precio")
        con = sqlite3.connect(self.ruta)
        renglones = con.execute("SELECT factura_id, descripcion, subtotal FROM factura_renglones "
                                "ORDER BY factura_id, orden").fetchall()
        con.close()
        self.assertEqual([r[1:] for r in renglones if r[0] == 1], [r[1:] for r in renglones if r[0] == 2])

    def test_factura_queda_anulada_y_no_admite_otra_nc(self):
        self.confirmar()
        self.hacer_nc()
        html = self.cli.get("/facturas/1").get_data(as_text=True)
        self.assertIn("ANULADA", html)
        self.assertIn("está anulada por la", html)
        self.assertNotIn("Hacer nota de crédito", html)
        html = self.hacer_nc(token="otra")
        self.assertIn("ya tiene la Nota de Crédito A", html)
        self.assertEqual(len(self.facturas()), 2)

    def test_nc_de_una_nc_no(self):
        self.confirmar()
        self.hacer_nc()
        self.assertIn("no se puede anular con otra nota de crédito", self.hacer_nc(2, token="x"))

    def test_numeracion_propia_de_las_nc(self):
        self.confirmar()
        self.confirmar()
        self.confirmar(cliente_id="2")       # Factura B
        self.hacer_nc(1)
        self.hacer_nc(2)
        self.hacer_nc(3)
        nc = [(f["cbte_tipo"], f["numero"]) for f in self.facturas() if f["asociado_id"]]
        self.assertEqual(nc, [(3, 1), (3, 2), (8, 1)])

    def test_fechas(self):
        self.confirmar()
        self.assertIn("no puede tener fecha anterior a la factura", self.hacer_nc(fecha=AYER))
        lejos = (date.today() + timedelta(days=20)).isoformat()
        self.assertIn("hasta 10 días", self.hacer_nc(fecha=lejos))
        self.assertIn("Escribí la fecha", self.hacer_nc(fecha=""))
        self.assertEqual(len(self.facturas()), 1)

    def test_vencimiento_de_la_nc_es_su_fecha(self):
        self.confirmar()
        self.hacer_nc(fecha=MANANA)
        nc = self.facturas()[1]
        self.assertEqual((nc["fecha"], nc["vto_pago"]), (MANANA, MANANA))

    def test_doble_confirmacion_genera_una_sola(self):
        self.confirmar()
        self.hacer_nc(token="mismo")
        self.hacer_nc(token="mismo")
        self.assertEqual(len(self.facturas()), 2)

    def test_lista_resta_las_nc(self):
        self.confirmar()                     # 72.600
        self.confirmar()                     # 72.600
        self.hacer_nc(1)
        html = self.cli.get("/facturas/").get_data(as_text=True)
        self.assertIn("$ -72.600,00", html)
        self.assertIn("3 comprobante(s)", html)
        tfoot = html.split("<tfoot>")[1]
        self.assertIn("$ 72.600,00", tfoot)
        self.assertIn("ANULADA", html)
        self.assertIn(">NC<", html)

    def test_eliminar_prueba(self):
        self.confirmar()
        self.hacer_nc()
        html = self.cli.post("/facturas/1/eliminar", follow_redirects=True).get_data(as_text=True)
        self.assertIn("eliminá primero la nota de crédito", html)
        html = self.cli.post("/facturas/2/eliminar", follow_redirects=True).get_data(as_text=True)
        self.assertIn("Nota de Crédito A de prueba N° 1 eliminada", html)
        html = self.cli.post("/facturas/1/eliminar", follow_redirects=True).get_data(as_text=True)
        self.assertIn("Factura A de prueba N° 1 eliminada", html)
        self.assertEqual(self.facturas(), [])

    def test_pdf_de_la_nc(self):
        self.confirmar()
        self.hacer_nc()
        r = self.cli.get("/facturas/2/pdf")
        self.assertEqual(r.status_code, 200)
        self.assertIn("30707871918_003_00002_00000001_PRUEBA.pdf", r.headers["Content-Disposition"])
        self.assertEqual(len(re.findall(rb"/Type /Page\b(?!s)", r.data)), 3)
