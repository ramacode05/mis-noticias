"""Pruebas de la etapa 3 (facturas de prueba). Correr con: python -m unittest discover tests"""
import os
import sqlite3
import tempfile
import unittest
from datetime import date, timedelta

from facturacion import create_app
from facturacion.db import ESQUEMA
from facturacion.importes import (a_centavos, a_centesimos, calcular_totales, formato_cantidad,
                                  formato_pesos)

HOY = date.today().isoformat()


class ImportesTest(unittest.TestCase):
    def test_lectura_formato_argentino(self):
        self.assertEqual(a_centavos("30.000,50"), 3000050)
        self.assertEqual(a_centavos("30000,5"), 3000050)
        self.assertEqual(a_centavos("30000.50"), 3000050)
        self.assertEqual(a_centavos("30.000"), 3000000)
        self.assertEqual(a_centavos("1.250.000"), 125000000)
        self.assertEqual(a_centavos("$ 1.500"), 150000)
        self.assertEqual(a_centavos("0"), 0)
        self.assertIsNone(a_centavos("abc"))
        self.assertIsNone(a_centavos("10,555"))   # más de 2 decimales
        self.assertIsNone(a_centavos("NaN"))
        self.assertEqual(a_centesimos("1,5"), 150)

    def test_formato(self):
        self.assertEqual(formato_pesos(12345678), "$ 123.456,78")
        self.assertEqual(formato_pesos(5), "$ 0,05")
        self.assertEqual(formato_cantidad(150), "1,5")
        self.assertEqual(formato_cantidad(200), "2")
        self.assertEqual(formato_cantidad(125), "1,25")

    def test_totales(self):
        # 2 x 30.000 + 1 x 15.000,50 = 75.000,50 ; IVA 15.750,105 -> 15.750,11
        t = calcular_totales([(200, 3000000), (100, 1500050)])
        self.assertEqual(t, {"neto": 7500050, "iva": 1575011, "total": 9075061})


class FacturasTest(unittest.TestCase):
    def setUp(self):
        fd, self.ruta = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)
        self.app = create_app({"TESTING": True, "DATABASE": self.ruta})
        self.cli = self.app.test_client()
        alta = lambda **d: self.cli.post("/clientes/nuevo", data=dict(activo="1", **d))
        alta(razon_social="Transportes Sur SA", condicion_iva="RI", tipo_doc="CUIT", nro_doc="30712345671")
        alta(razon_social="Juan Pérez", condicion_iva="CF", tipo_doc="SIN", nro_doc="")

    def tearDown(self):
        os.remove(self.ruta)

    def facturar(self, cliente_id=1, renglones=(("Int. AB123CD - Desarme y Reparación", "1", "30.000"),),
                 **extra):
        datos = {"cliente_id": str(cliente_id), "fecha": HOY, "concepto": "3",
                 "serv_desde": HOY, "serv_hasta": HOY, "vto_pago": HOY,
                 "condicion_venta": "Cuenta Corriente",
                 "descripcion": [r[0] for r in renglones],
                 "cantidad": [r[1] for r in renglones],
                 "precio": [r[2] for r in renglones]}
        datos.update(extra)
        return self.cli.post("/facturas/nueva", data=datos, follow_redirects=True)

    def facturas(self):
        con = sqlite3.connect(self.ruta)
        con.row_factory = sqlite3.Row
        filas = con.execute("SELECT * FROM facturas ORDER BY id").fetchall()
        con.close()
        return filas

    def test_factura_a_con_totales(self):
        r = self.facturar(renglones=[("Desarme", "2", "30.000"), ("Repuesto", "1", "15.000,50"), ("", "", "")])
        texto = r.get_data(as_text=True)
        self.assertIn("Factura A N° 1 guardada", texto)
        self.assertIn("$ 90.750,61", texto)
        f = self.facturas()[0]
        self.assertEqual((f["letra"], f["cbte_tipo"], f["numero"], f["prueba"]), ("A", 1, 1, 1))
        self.assertEqual((f["neto"], f["iva"], f["total"]), (7500050, 1575011, 9075061))

    def test_factura_b_y_numeracion_separada(self):
        self.facturar(1)
        self.facturar(1)
        r = self.facturar(2)
        self.assertIn("Factura B N° 1 guardada", r.get_data(as_text=True))
        self.assertEqual([(f["letra"], f["numero"]) for f in self.facturas()],
                         [("A", 1), ("A", 2), ("B", 1)])

    def test_cantidad_vacia_es_uno(self):
        self.facturar(renglones=[("Mano de obra", "", "10.000")])
        self.assertEqual(self.facturas()[0]["neto"], 1000000)

    def test_datos_del_cliente_quedan_fijos(self):
        self.facturar()
        self.cli.post("/clientes/1", data={"razon_social": "Nombre Nuevo", "condicion_iva": "RI",
                                           "tipo_doc": "CUIT", "nro_doc": "30712345671", "activo": "1"})
        self.assertEqual(self.facturas()[0]["cliente_razon_social"], "Transportes Sur SA")

    def test_errores(self):
        casos = [
            ({"cliente_id": ""}, "Elegí el cliente"),
            ({"renglones": [("", "", "")]}, "al menos un renglón"),
            ({"renglones": [("Algo", "1", "")]}, "el precio no es válido"),
            ({"renglones": [("", "1", "100")]}, "falta la descripción"),
            ({"renglones": [("Algo", "0", "100")]}, "la cantidad no es válida"),
            ({"renglones": [("Algo", "1", "0")]}, "mayor a cero"),
            ({"fecha": (date.today() - timedelta(days=11)).isoformat()}, "hasta 10 días"),
            ({"serv_desde": HOY, "serv_hasta": (date.today() - timedelta(days=1)).isoformat()},
             "no puede ser posterior"),
            ({"vto_pago": (date.today() - timedelta(days=1)).isoformat()}, "vencimiento no puede"),
        ]
        for cambios, mensaje in casos:
            with self.subTest(mensaje):
                renglones = cambios.pop("renglones", None)
                kwargs = {"renglones": renglones} if renglones else {}
                if "cliente_id" in cambios:
                    kwargs["cliente_id"] = cambios.pop("cliente_id")
                r = self.facturar(**kwargs, **cambios)
                self.assertIn(mensaje, r.get_data(as_text=True))
        self.assertEqual(self.facturas(), [])

    def test_productos_no_pide_fechas_de_servicio(self):
        self.facturar(concepto="1", serv_desde="", serv_hasta="", vto_pago="")
        f = self.facturas()[0]
        self.assertEqual(f["concepto"], 1)
        self.assertIsNone(f["serv_desde"])

    def test_fecha_no_anterior_a_la_ultima(self):
        self.facturar()
        r = self.facturar(fecha=(date.today() - timedelta(days=1)).isoformat())
        self.assertIn("no puede ser anterior a la última Factura A", r.get_data(as_text=True))

    def test_lista_ver_y_eliminar_prueba(self):
        self.facturar()
        lista = self.cli.get("/facturas/").get_data(as_text=True)
        self.assertIn("00001-00000001", lista)
        self.assertIn("PRUEBA", lista)
        self.assertIn("Transportes Sur SA", self.cli.get("/facturas/?q=transportes").get_data(as_text=True))
        self.assertNotIn("Transportes Sur SA", self.cli.get("/facturas/?mes=2000-01").get_data(as_text=True))
        r = self.cli.post("/facturas/1/eliminar", follow_redirects=True)
        self.assertIn("eliminada", r.get_data(as_text=True))
        self.assertEqual(self.facturas(), [])

    def test_factura_real_no_se_elimina(self):
        self.facturar()
        con = sqlite3.connect(self.ruta)
        con.execute("UPDATE facturas SET prueba = 0")
        con.commit()
        con.close()
        r = self.cli.post("/facturas/1/eliminar", follow_redirects=True)
        self.assertIn("no se pueden eliminar", r.get_data(as_text=True))
        self.assertEqual(len(self.facturas()), 1)

    def test_punto_de_venta(self):
        self.cli.post("/configuracion/", data={"punto_venta": "3"})
        self.facturar()
        self.assertEqual(self.facturas()[0]["punto_venta"], 3)
        r = self.cli.post("/configuracion/", data={"punto_venta": "abc"})
        self.assertIn("número entre 1 y 99998", r.get_data(as_text=True))

    def test_pantalla_nueva_con_cliente_elegido(self):
        texto = self.cli.get("/facturas/nueva?cliente=2").get_data(as_text=True)
        self.assertIn('value="2" data-letra="B"\n            selected', texto)


class ActualizacionBaseTest(unittest.TestCase):
    def test_base_etapa_2_conserva_datos(self):
        fd, ruta = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)
        try:
            esquema = ESQUEMA.read_text(encoding="utf-8").split("-- Configuración general")[0]
            con = sqlite3.connect(ruta)
            con.executescript(esquema)
            con.execute("INSERT INTO clientes (razon_social, condicion_iva, tipo_doc) VALUES ('Viejo', 'CF', 'SIN')")
            con.execute("INSERT INTO conceptos (descripcion) VALUES ('Concepto viejo')")
            con.commit()
            con.close()
            create_app({"TESTING": True, "DATABASE": ruta})
            con = sqlite3.connect(ruta)
            self.assertEqual(con.execute("SELECT count(*) FROM clientes").fetchone(), (1,))
            self.assertEqual(con.execute("SELECT count(*) FROM conceptos").fetchone(), (1,))
            self.assertEqual(con.execute("SELECT valor FROM configuracion").fetchone(), ("1",))
            con.close()
        finally:
            os.remove(ruta)


if __name__ == "__main__":
    unittest.main()
