"""Pruebas de la etapa 6 (cobros). Correr con: python -m unittest discover tests"""
import sqlite3
from datetime import date, timedelta

from tests.test_facturas import AYER, HOY, BaseFacturas

MANANA = (date.today() + timedelta(days=1)).isoformat()


class CobrosTest(BaseFacturas):
    def cobrar(self, facturas, cliente="1", **datos):
        datos = {"cliente": cliente, "factura": [str(f) for f in facturas], "fecha": HOY,
                 "medio": "Transferencia", "referencia": "", "observaciones": "",
                 "token": datos.pop("token", "c-" + "-".join(map(str, facturas))), **datos}
        return self.cli.post("/cobros/nuevo", data=datos, follow_redirects=True).get_data(as_text=True)

    def tabla(self, sql):
        con = sqlite3.connect(self.ruta)
        filas = con.execute(sql).fetchall()
        con.close()
        return filas

    def test_cobro_de_varias_facturas(self):
        self.confirmar()
        self.confirmar()
        html = self.cli.get("/cobros/nuevo?cliente=1").get_data(as_text=True)
        self.assertIn("Facturas pendientes de Transportes Sur SA", html)
        self.assertEqual(html.count('name="factura"'), 2)
        html = self.cobrar([1, 2], referencia="Transf 123")
        self.assertIn("Cobro registrado: 2 factura(s)", html)
        self.assertIn("$ 145.200,00", html)
        self.assertEqual(self.tabla("SELECT medio, referencia, total FROM cobros"),
                         [("Transferencia", "Transf 123", 14520000)])

    def test_factura_cobrada_no_vuelve_a_aparecer(self):
        self.confirmar()
        self.confirmar()
        self.cobrar([1])
        html = self.cli.get("/cobros/nuevo?cliente=1").get_data(as_text=True)
        self.assertEqual(html.count('name="factura"'), 1)
        self.cobrar([1], token="otra")  # intentar cobrarla de nuevo
        self.assertEqual(self.tabla("SELECT COUNT(*) FROM cobros"), [(1,)])

    def test_estado_cobrada_en_factura_y_lista(self):
        self.confirmar()
        self.assertIn("Registrar cobro", self.cli.get("/facturas/1").get_data(as_text=True))
        self.cobrar([1], medio="Cheque", referencia="Ch 555")
        html = self.cli.get("/facturas/1").get_data(as_text=True)
        self.assertIn("COBRADA", html)
        self.assertIn("Cheque Ch 555", html)
        self.assertNotIn("Registrar cobro</a>", html)
        self.assertNotIn("Hacer nota de crédito", html)
        self.assertIn("COBRADA", self.cli.get("/facturas/").get_data(as_text=True))

    def test_factura_anulada_no_se_cobra(self):
        self.confirmar()
        self.cli.post("/facturas/1/nota-credito", data={"fecha": HOY, "token": "nc"})
        html = self.cli.get("/cobros/nuevo?cliente=1").get_data(as_text=True)
        self.assertIn("no tiene facturas pendientes", html)

    def test_cobrada_no_se_anula_ni_se_borra(self):
        self.confirmar()
        self.cobrar([1])
        html = self.cli.post("/facturas/1/nota-credito", data={"fecha": HOY, "token": "nc"},
                             follow_redirects=True).get_data(as_text=True)
        self.assertIn("La factura ya está cobrada", html)
        html = self.cli.post("/facturas/1/eliminar", follow_redirects=True).get_data(as_text=True)
        self.assertIn("eliminá primero el cobro", html)

    def test_eliminar_cobro_deja_la_factura_pendiente(self):
        self.confirmar()
        self.cobrar([1])
        html = self.cli.post("/cobros/1/eliminar", follow_redirects=True).get_data(as_text=True)
        self.assertIn("Cobro eliminado", html)
        self.assertEqual(self.tabla("SELECT COUNT(*) FROM cobro_facturas"), [(0,)])
        self.assertIn("Registrar cobro", self.cli.get("/facturas/1").get_data(as_text=True))

    def test_errores(self):
        self.confirmar()
        self.assertIn("Marcá al menos una factura", self.cobrar([]))
        self.assertIn("no puede ser posterior a hoy", self.cobrar([1], fecha=MANANA))
        self.assertIn("anterior a las facturas", self.cobrar([1], fecha=AYER, token="t2"))
        self.assertIn("Elegí el medio", self.cobrar([1], medio="Trueque", token="t3"))
        self.assertIn("Elegí el cliente", self.cobrar([1], cliente="", token="t4"))
        self.assertEqual(self.tabla("SELECT COUNT(*) FROM cobros"), [(0,)])

    def test_doble_confirmacion(self):
        self.confirmar()
        self.cobrar([1], token="mismo")
        self.cobrar([1], token="mismo")
        self.assertEqual(self.tabla("SELECT COUNT(*) FROM cobros"), [(1,)])

    def test_lista_de_cobros(self):
        self.confirmar()
        self.cobrar([1])
        html = self.cli.get("/cobros/").get_data(as_text=True)
        self.assertIn("Transportes Sur SA", html)
        self.assertIn("$ 72.600,00", html)
        self.assertNotIn("Transportes Sur SA", self.cli.get("/cobros/?mes=2000-01").get_data(as_text=True))

    def test_desde_la_factura_viene_marcada(self):
        self.confirmar()
        self.confirmar()
        html = self.cli.get("/cobros/nuevo?cliente=1&factura=2").get_data(as_text=True)
        self.assertIn('value="2" data-total="7260000" checked', html)
        self.assertIn('value="1" data-total="7260000" >', html)
