"""Pruebas del cierre de mes (ingresos contra gastos, Humberto y beneficio)."""
import sqlite3
from datetime import date, timedelta

from facturacion import cierre
from tests.test_facturas import HOY, BaseFacturas
from tests.test_resumen import leer_hoja

MES = date.today().strftime("%Y-%m")
ANIO = date.today().year


class CierreTest(BaseFacturas):
    def categoria(self, nombre):
        con = sqlite3.connect(self.ruta)
        fila = con.execute("SELECT id FROM categorias_gasto WHERE nombre = ?", (nombre,)).fetchone()
        con.close()
        return fila[0]

    def totales(self):
        with self.app.app_context():
            return cierre.totales_mes(MES)

    def test_mes_vacio(self):
        html = self.cli.get("/cierre/").get_data(as_text=True)
        self.assertIn("Cierre de", html)
        t = self.totales()
        self.assertEqual((t["ingresos"], t["gastos"], t["resultado"], t["humberto"]), (0, 0, 0, 0))

    def test_cuentas_completas(self):
        self.confirmar()                                    # Factura A: 72.600 con IVA
        self.confirmar()
        self.cli.post("/facturas/2/nota-credito", data={"fecha": HOY, "token": "nc"})  # resta 72.600
        self.cli.post("/cierre/efectivo", data={"mes": MES, "fecha": HOY, "detalle": "Arreglo",
                                                "importe": "10.000,50"})
        self.cli.post("/cierre/compras", data={"mes": MES, "fecha": HOY, "proveedor": "Aceros  SA",
                                               "numero": "A-1", "total": "20.000"})
        luz, varios = self.categoria("Luz"), self.categoria("Varios")
        self.cli.post("/cierre/gastos", data={"mes": MES, f"cat_{luz}": "5.000", f"cat_{varios}": "1000,25"})
        t = self.totales()
        self.assertEqual(t["ventas"], 7260000)
        self.assertEqual(t["ingresos"], 7260000 + 1000050)
        self.assertEqual(t["gastos"], 2000000 + 500000 + 100025)
        self.assertEqual(t["resultado"], 8260050 - 2600025)
        self.assertEqual(t["humberto"], 1188605)            # 21% de 56.600,25 = 11.886,0525
        self.assertEqual(t["beneficio"], t["resultado"] - t["humberto"])
        html = self.cli.get(f"/cierre/?mes={MES}").get_data(as_text=True)
        self.assertIn("Aceros SA", html)
        self.assertIn("Arreglo", html)
        # Un campo vacío borra el gasto
        self.cli.post("/cierre/gastos", data={"mes": MES, f"cat_{luz}": "", f"cat_{varios}": "1000,25"})
        self.assertEqual(self.totales()["gastos_categorias"], 100025)

    def test_importe_invalido(self):
        luz = self.categoria("Luz")
        html = self.cli.post("/cierre/gastos", data={"mes": MES, f"cat_{luz}": "abc"},
                             follow_redirects=True).get_data(as_text=True)
        self.assertIn("Luz: el importe no es válido", html)
        html = self.cli.post("/cierre/compras", data={"mes": MES, "fecha": HOY, "proveedor": "", "total": "1"},
                             follow_redirects=True).get_data(as_text=True)
        self.assertIn("hacen falta la fecha, el proveedor y el total", html)

    def test_cada_mes_empieza_vacio(self):
        luz = self.categoria("Luz")
        self.cli.post("/cierre/gastos", data={"mes": MES, f"cat_{luz}": "5000"})
        with self.app.app_context():
            self.assertEqual(cierre.totales_mes(cierre.mes_vecino(MES, 1))["gastos"], 0)

    def test_vencimiento_y_pagada(self):
        vence = (date.today() + timedelta(days=3)).isoformat()
        self.cli.post("/cierre/compras", data={"mes": MES, "fecha": HOY, "proveedor": "Gomas SRL",
                                               "total": "1000", "vencimiento": vence})
        html = self.cli.get("/cierre/").get_data(as_text=True)
        self.assertIn("Gomas SRL", html.split("Facturas de proveedores")[0])  # aviso arriba
        self.cli.post(f"/cierre/compras/1/pagada?mes={MES}")
        con = sqlite3.connect(self.ruta)
        self.assertIsNotNone(con.execute("SELECT pagada FROM compras").fetchone()[0])
        self.cli.post(f"/cierre/compras/1/pagada?mes={MES}")
        self.assertIsNone(con.execute("SELECT pagada FROM compras").fetchone()[0])
        self.cli.post(f"/cierre/compras/1/eliminar?mes={MES}")
        self.assertEqual(con.execute("SELECT COUNT(*) FROM compras").fetchone()[0], 0)
        con.close()

    def test_categorias(self):
        luz = self.categoria("Luz")
        self.cli.post("/cierre/categorias", data={"nueva": "Seguros", f"nombre_{luz}": "Luz Edesur",
                                                  f"orden_{luz}": "2"})
        html = self.cli.get("/cierre/").get_data(as_text=True)
        self.assertIn("Seguros", html)
        self.assertNotIn("Luz Edesur", html)  # no se tildó "activa": queda oculta
        self.assertIn("Luz Edesur", self.cli.get("/cierre/categorias").get_data(as_text=True))

    def test_anual_y_excel(self):
        self.confirmar()
        self.cli.post("/cierre/compras", data={"mes": MES, "fecha": HOY, "proveedor": "X", "total": "100"})
        html = self.cli.get(f"/cierre/anual?anio={ANIO}").get_data(as_text=True)
        self.assertIn("Anual", html)
        respuesta = self.cli.get(f"/cierre/anual/excel?anio={ANIO}")
        self.assertIn(f"cierre_{ANIO}.xlsx", respuesta.headers["Content-Disposition"])
        filas = leer_hoja(respuesta.data, 1)
        titulos = filas[2]
        anual = filas[-1]
        self.assertEqual(anual[0], "Anual")
        self.assertEqual(anual[titulos.index("Facturado")], "72600.00")
        self.assertEqual(anual[titulos.index("Proveedores")], "100.00")
        self.assertEqual(anual[titulos.index("Resultado")], "72500.00")
        self.assertEqual(anual[titulos.index("Humberto (21%)")], "15225.00")
