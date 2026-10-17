"""Pruebas de la etapa 7 (cuentas corrientes). Correr con: python -m unittest discover tests"""
from tests.test_facturas import HOY, BaseFacturas


class CuentasTest(BaseFacturas):
    def cobrar(self, facturas, token):
        self.cli.post("/cobros/nuevo", data={"cliente": "1", "factura": [str(f) for f in facturas],
                                             "fecha": HOY, "medio": "Cheque", "referencia": "555",
                                             "token": token})

    def armar(self):
        """3 facturas de 72.600 al cliente 1: una cobrada, una anulada y una pendiente."""
        for _ in range(3):
            self.confirmar()
        self.cobrar([1], "c1")
        self.cli.post("/facturas/2/nota-credito", data={"fecha": HOY, "token": "nc"})

    def test_movimientos_con_saldo(self):
        self.armar()
        from facturacion.cuentas import movimientos
        with self.app.app_context():
            movs = movimientos(1)
        self.assertEqual([(m["tipo"], m["debe"], m["haber"], m["saldo"]) for m in movs], [
            ("factura", 7260000, 0, 7260000),
            ("factura", 7260000, 0, 14520000),
            ("factura", 7260000, 0, 21780000),
            ("nota_credito", 0, 7260000, 14520000),
            ("cobro", 0, 7260000, 7260000),
        ])

    def test_pantalla_de_la_cuenta(self):
        self.armar()
        html = self.cli.get("/cuentas/1").get_data(as_text=True)
        self.assertIn("Cuenta corriente: Transportes Sur SA", html)
        self.assertIn("Saldo al", html)
        self.assertIn("Cobro (Cheque 555)", html)
        self.assertIn("Nota de Crédito A 00002-00000001", html)
        pendientes = html.split("Facturas pendientes de cobro")[1].split("Movimientos")[0]
        self.assertIn("00002-00000003", pendientes)
        self.assertNotIn("00002-00000001", pendientes)  # cobrada
        self.assertNotIn("00002-00000002", pendientes)  # anulada
        self.assertIn("$ 72.600,00", pendientes)

    def test_listado_de_saldos(self):
        self.armar()
        self.confirmar(cliente_id="2")
        html = self.cli.get("/cuentas/").get_data(as_text=True)
        self.assertIn("Transportes Sur SA", html)
        self.assertIn("Juan Pérez", html)
        self.assertIn("$ 217.800,00", html)   # facturado al cliente 1
        tfoot = html.split("<tfoot>")[1]
        self.assertIn("$ 145.200,00", tfoot)  # 72.600 + 72.600 de la factura B

    def test_cliente_que_no_debe_solo_con_todos(self):
        self.confirmar()
        self.cobrar([1], "c1")
        self.assertIn("Ningún cliente tiene saldo pendiente", self.cli.get("/cuentas/").get_data(as_text=True))
        self.assertIn("Transportes Sur SA", self.cli.get("/cuentas/?todos=1").get_data(as_text=True))

    def test_cuenta_sin_movimientos_y_cliente_inexistente(self):
        self.assertIn("Todavía no tiene movimientos", self.cli.get("/cuentas/2").get_data(as_text=True))
        self.assertEqual(self.cli.get("/cuentas/99").status_code, 404)

    def test_enlaces(self):
        self.assertIn("Cuentas corrientes", self.cli.get("/clientes/").get_data(as_text=True))
        self.assertIn("/cuentas/1", self.cli.get("/clientes/").get_data(as_text=True))
