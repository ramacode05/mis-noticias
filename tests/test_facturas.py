"""Pruebas de facturas (carga en pasos como ARCA). Correr con: python -m unittest discover tests"""
import os
import re
import sqlite3
import tempfile
import unittest
from datetime import date, timedelta

from facturacion import create_app
from facturacion.db import ESQUEMA
from facturacion.importes import (a_centavos, a_centesimos, calcular_totales, formato_cantidad,
                                  formato_pesos)

HOY = date.today().isoformat()
AYER = (date.today() - timedelta(days=1)).isoformat()


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


class BaseFacturas(unittest.TestCase):
    def setUp(self):
        fd, self.ruta = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)
        self.app = create_app({"TESTING": True, "DATABASE": self.ruta})
        self.cli = self.app.test_client()
        alta = lambda **d: self.cli.post("/clientes/nuevo", data=dict(activo="1", **d))
        alta(razon_social="Transportes Sur SA", condicion_iva="RI", tipo_doc="CUIT",
             nro_doc="30712345671", domicilio="Ruta 9 km 300", localidad="Rosario")
        alta(razon_social="Juan Pérez", condicion_iva="CF", tipo_doc="SIN", nro_doc="")

    def tearDown(self):
        os.remove(self.ruta)

    def datos(self, renglones=(("Int. AB123CD", "", "0"), ("Desarme y Reparación", "2", "30.000")),
              **extra):
        d = {"token": extra.pop("token", "t-" + os.urandom(4).hex()),
             "fecha": HOY, "concepto": "3", "serv_desde": HOY, "serv_hasta": HOY, "vto_pago": HOY,
             "cliente_id": "1", "remito_numero": "", "remito_confirmado": "", "observaciones": "",
             "descripcion": [r[0] for r in renglones],
             "cantidad": [r[1] for r in renglones],
             "precio": [r[2] for r in renglones]}
        d.update(extra)
        return d

    def paso(self, paso, accion, **datos):
        datos = self.datos(**datos)
        datos.update(paso=str(paso), accion=accion)
        r = self.cli.post("/facturas/nueva", data=datos, follow_redirects=True)
        return r.get_data(as_text=True)

    def confirmar(self, **datos):
        return self.paso(4, "confirmar", **datos)

    def facturas(self):
        con = sqlite3.connect(self.ruta)
        con.row_factory = sqlite3.Row
        filas = con.execute("SELECT * FROM facturas ORDER BY id").fetchall()
        con.close()
        return filas

    def paso_mostrado(self, html):
        return int(re.search(r'name="paso" value="(\d)"', html).group(1))


class PasosTest(BaseFacturas):
    def test_recorrido_completo(self):
        html = self.cli.get("/facturas/nueva").get_data(as_text=True)
        self.assertIn("DATOS DE EMISIÓN (PASO 1 DE 4)", html)
        html = self.paso(1, "continuar")
        self.assertIn("DATOS DEL RECEPTOR (PASO 2 DE 4)", html)
        html = self.paso(2, "continuar")
        self.assertIn("DATOS DE LA OPERACIÓN (PASO 3 DE 4)", html)
        html = self.paso(3, "continuar")
        self.assertIn("RESUMEN (PASO 4 DE 4)", html)
        self.assertIn("$ 72.600,00", html)            # 60.000 + IVA 12.600
        self.assertIn("Cuenta Corriente", html)
        html = self.confirmar()
        self.assertIn("Factura A N° 1 generada", html)
        f = self.facturas()[0]
        self.assertEqual((f["letra"], f["numero"], f["neto"], f["iva"], f["total"]),
                         ("A", 1, 6000000, 1260000, 7260000))
        self.assertEqual(f["condicion_venta"], "Cuenta Corriente")

    def test_volver_conserva_los_datos(self):
        html = self.paso(3, "volver", remito_numero="6535")
        self.assertEqual(self.paso_mostrado(html), 2)
        self.assertIn('value="6535"', html)
        self.assertIn('value="Desarme y Reparación"', html)  # renglones viajan ocultos

    def test_modificar_desde_resumen(self):
        html = self.paso(4, "ir_1")
        self.assertEqual(self.paso_mostrado(html), 1)
        html = self.paso(2, "ir_3")  # no deja saltar hacia adelante
        self.assertEqual(self.paso_mostrado(html), 2)

    def test_errores_paso_1(self):
        casos = [
            ({"fecha": (date.today() - timedelta(days=11)).isoformat()}, "hasta 10 días"),
            ({"concepto": "1", "fecha": (date.today() - timedelta(days=6)).isoformat()}, "hasta 5 días"),
            ({"serv_hasta": AYER}, "no puede ser posterior"),
            ({"vto_pago": AYER}, "vencimiento no puede"),
            ({"fecha": ""}, "Escribí la fecha"),
        ]
        for cambios, mensaje in casos:
            with self.subTest(mensaje):
                html = self.paso(1, "continuar", **cambios)
                self.assertIn(mensaje, html)
                self.assertEqual(self.paso_mostrado(html), 1)

    def test_errores_paso_2_y_3(self):
        html = self.paso(2, "continuar", cliente_id="")
        self.assertIn("Elegí el cliente", html)
        casos = [
            ([("", "", "")], "al menos una línea"),
            ([("Algo", "1", "")], "el precio unitario no es válido"),
            ([("", "1", "100")], "falta el producto"),
            ([("Algo", "0", "100")], "la cantidad no es válida"),
            ([("Algo", "1", "0")], "mayor a cero"),
        ]
        for renglones, mensaje in casos:
            with self.subTest(mensaje):
                html = self.paso(3, "continuar", renglones=renglones)
                self.assertIn(mensaje, html)
                self.assertEqual(self.paso_mostrado(html), 3)

    def test_confirmar_revalida_todo(self):
        html = self.confirmar(renglones=[("", "", "")])
        self.assertEqual(self.paso_mostrado(html), 3)
        self.assertEqual(self.facturas(), [])

    def test_doble_confirmacion_genera_una_sola_factura(self):
        self.confirmar(token="mismo")
        html = self.confirmar(token="mismo")
        self.assertIn("Factura A N° 1", html)
        self.assertEqual(len(self.facturas()), 1)

    def test_factura_b_y_numeracion_separada(self):
        self.confirmar()
        self.confirmar()
        html = self.confirmar(cliente_id="2")
        self.assertIn("Factura B N° 1 generada", html)
        self.assertEqual([(f["letra"], f["numero"]) for f in self.facturas()],
                         [("A", 1), ("A", 2), ("B", 1)])

    def test_fecha_no_anterior_a_la_ultima(self):
        self.confirmar()
        html = self.paso(2, "continuar", fecha=AYER)
        self.assertIn("no puede ser anterior a la última Factura A", html)

    def test_productos_no_guarda_periodo(self):
        self.confirmar(concepto="1", serv_desde="", serv_hasta="", vto_pago="")
        self.assertIsNone(self.facturas()[0]["serv_desde"])

    def test_datos_del_cliente_quedan_fijos(self):
        self.confirmar()
        self.cli.post("/clientes/1", data={"razon_social": "Nombre Nuevo", "condicion_iva": "RI",
                                           "tipo_doc": "CUIT", "nro_doc": "30712345671", "activo": "1"})
        self.assertEqual(self.facturas()[0]["cliente_razon_social"], "Transportes Sur SA")

    def test_cliente_preelegido_desde_lista_de_clientes(self):
        html = self.cli.get("/facturas/nueva?cliente=2").get_data(as_text=True)
        self.assertIn('name="cliente_id" value="2"', html)
        self.assertIn("FACTURA B", html)


class RemitoTest(BaseFacturas):
    def test_remito_se_guarda_y_se_busca(self):
        self.confirmar(remito_numero="00006535")
        f = self.facturas()[0]
        self.assertEqual((f["remito_pto_vta"], f["remito_numero"]), (1, 6535))
        lista = self.cli.get("/facturas/?q=6535").get_data(as_text=True)
        self.assertIn("Transportes Sur SA", lista)
        self.assertNotIn("Transportes Sur SA", self.cli.get("/facturas/?q=9999").get_data(as_text=True))
        self.assertIn("R 00001-00006535", self.cli.get("/facturas/1").get_data(as_text=True))

    def test_remito_opcional(self):
        self.confirmar()
        self.assertIsNone(self.facturas()[0]["remito_numero"])

    def test_remito_invalido(self):
        html = self.paso(2, "continuar", remito_numero="0001-6535")
        self.assertIn("Escribí solo el número del remito", html)

    def test_remito_repetido_avisa_y_se_puede_confirmar(self):
        self.confirmar(remito_numero="6535")
        html = self.paso(2, "continuar", remito_numero="6535")
        self.assertIn("Este remito ya está en la Factura A N° 1", html)
        self.assertIn("Usar este remito igual", html)
        self.assertEqual(self.paso_mostrado(html), 2)
        html = self.paso(2, "continuar", remito_numero="6535", remito_confirmado="1")
        self.assertEqual(self.paso_mostrado(html), 3)
        self.confirmar(remito_numero="6535", remito_confirmado="1")
        self.assertEqual(len(self.facturas()), 2)

    def test_punto_de_venta_del_remito_configurable(self):
        self.cli.post("/configuracion/", data={"punto_venta": "2", "remito_punto_venta": "4"})
        self.confirmar(remito_numero="10")
        f = self.facturas()[0]
        self.assertEqual((f["punto_venta"], f["remito_pto_vta"]), (2, 4))


class ClienteNuevoTest(BaseFacturas):
    def test_alta_de_cliente_desde_el_paso_2(self):
        datos = self.datos(cliente_id="")
        datos.update(paso="2", accion="crear_cliente", nc_razon_social="Logística Norte SRL",
                     nc_condicion_iva="RI", nc_tipo_doc="CUIT", nc_nro_doc="20-12345678-6",
                     nc_domicilio="Calle 1", nc_localidad="Quilmes", nc_email="")
        html = self.cli.post("/facturas/nueva", data=datos).get_data(as_text=True)
        self.assertIn('name="cliente_id" id="cliente_id" value="3"', html)
        self.assertIn("Logística Norte SRL", html)
        self.assertEqual(self.paso_mostrado(html), 2)

    def test_alta_con_error_no_pierde_la_factura(self):
        datos = self.datos(cliente_id="")
        datos.update(paso="2", accion="crear_cliente", nc_razon_social="Otro", nc_condicion_iva="RI",
                     nc_tipo_doc="CUIT", nc_nro_doc="30712345671")
        html = self.cli.post("/facturas/nueva", data=datos).get_data(as_text=True)
        self.assertIn("Ya existe un cliente con ese documento", html)
        self.assertIn('value="Desarme y Reparación"', html)

    def test_buscador_tiene_los_clientes(self):
        html = self.paso(1, "continuar")
        self.assertIn('"razon_social": "Transportes Sur SA"', html)
        self.assertIn('"documento": "CUIT 30-71234567-1"', html)


class ListaYEliminarTest(BaseFacturas):
    def test_lista_ver_y_eliminar_prueba(self):
        self.confirmar()
        lista = self.cli.get("/facturas/").get_data(as_text=True)
        self.assertIn("00001-00000001", lista)
        self.assertIn("PRUEBA", lista)
        self.assertIn("Transportes Sur SA", self.cli.get("/facturas/?q=transportes").get_data(as_text=True))
        self.assertNotIn("Transportes Sur SA", self.cli.get("/facturas/?mes=2000-01").get_data(as_text=True))
        r = self.cli.post("/facturas/1/eliminar", follow_redirects=True)
        self.assertIn("eliminada", r.get_data(as_text=True))
        self.assertEqual(self.facturas(), [])

    def test_factura_real_no_se_elimina(self):
        self.confirmar()
        con = sqlite3.connect(self.ruta)
        con.execute("UPDATE facturas SET prueba = 0")
        con.commit()
        con.close()
        r = self.cli.post("/facturas/1/eliminar", follow_redirects=True)
        self.assertIn("no se pueden eliminar", r.get_data(as_text=True))
        self.assertEqual(len(self.facturas()), 1)

    def test_configuracion_invalida(self):
        html = self.cli.post("/configuracion/", data={"punto_venta": "abc", "remito_punto_venta": "1"}
                             ).get_data(as_text=True)
        self.assertIn("número entre 1 y 99998", html)


class ActualizacionBaseTest(unittest.TestCase):
    def test_base_etapa_3_recibe_columnas_nuevas(self):
        """Una base con facturas de la versión anterior (sin remito) se actualiza sola."""
        fd, ruta = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)
        try:
            con = sqlite3.connect(ruta)
            esquema = ESQUEMA.read_text(encoding="utf-8").replace(
                "INSERT OR IGNORE INTO configuracion (clave, valor) VALUES ('remito_punto_venta', '1');", "")
            con.executescript(esquema)
            con.execute("INSERT INTO clientes (razon_social, condicion_iva, tipo_doc) VALUES ('Viejo', 'CF', 'SIN')")
            con.execute("""INSERT INTO facturas (cbte_tipo, letra, punto_venta, numero, fecha, condicion_venta,
                cliente_id, cliente_razon_social, cliente_condicion_iva, cliente_tipo_doc, cliente_nro_doc,
                cliente_domicilio, neto, iva, total) VALUES (6, 'B', 1, 1, ?, 'Cuenta Corriente', 1,
                'Viejo', 'CF', 'SIN', '', '', 100, 21, 121)""", (HOY,))
            con.commit()
            con.close()

            app = create_app({"TESTING": True, "DATABASE": ruta})
            con = sqlite3.connect(ruta)
            columnas = {c[1] for c in con.execute("PRAGMA table_info(facturas)")}
            self.assertTrue({"remito_pto_vta", "remito_numero", "token"} <= columnas)
            self.assertEqual(con.execute("SELECT count(*) FROM facturas").fetchone(), (1,))
            self.assertEqual(con.execute("SELECT valor FROM configuracion WHERE clave = 'remito_punto_venta'"
                                         ).fetchone(), ("1",))
            con.close()
            self.assertIn("Viejo", app.test_client().get("/facturas/").get_data(as_text=True))
        finally:
            os.remove(ruta)


if __name__ == "__main__":
    unittest.main()
