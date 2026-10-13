"""Pruebas de la etapa 2 (conceptos fijos). Correr con: python -m unittest discover tests"""
import os
import sqlite3
import tempfile
import unittest

from facturacion import create_app
from facturacion.db import ESQUEMA

DELANTERO_DER = "Desarme y Reparación en Elásticos Delanteros Derecho"
TRASERO_IZQ = "Desarme y Reparación en Elásticos Traseros Izquierdo"


class ConceptosTest(unittest.TestCase):
    def setUp(self):
        fd, self.ruta = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)
        self.app = create_app({"TESTING": True, "DATABASE": self.ruta})
        self.cli = self.app.test_client()

    def tearDown(self):
        os.remove(self.ruta)

    def alta(self, descripcion, **extra):
        datos = {"descripcion": descripcion, "activo": "1"}
        datos.update(extra)
        return self.cli.post("/conceptos/nuevo", data=datos, follow_redirects=True)

    def test_alta_y_lista(self):
        r = self.alta(DELANTERO_DER)
        texto = r.get_data(as_text=True)
        self.assertIn("Concepto guardado", texto)
        self.assertIn(DELANTERO_DER, texto)

    def test_busqueda_por_palabras_en_cualquier_orden(self):
        self.alta(DELANTERO_DER)
        self.alta(TRASERO_IZQ)
        texto = self.cli.get("/conceptos/?q=izquierdo traseros").get_data(as_text=True)
        self.assertIn(TRASERO_IZQ, texto)
        self.assertNotIn(DELANTERO_DER, texto)

    def test_vacio(self):
        r = self.alta("   ")
        self.assertIn("Escribí el texto", r.get_data(as_text=True))

    def test_duplicado_sin_importar_mayusculas_ni_espacios(self):
        self.alta(DELANTERO_DER)
        r = self.alta("  " + DELANTERO_DER.upper().replace(" ", "  "))
        self.assertIn("Ya existe un concepto", r.get_data(as_text=True))

    def test_guardar_y_cargar_otro(self):
        r = self.alta(DELANTERO_DER, otro="1")
        self.assertIn("Nuevo concepto", r.get_data(as_text=True))

    def test_edicion_e_inactivo(self):
        self.alta(DELANTERO_DER)
        r = self.cli.post("/conceptos/1", data={"descripcion": TRASERO_IZQ}, follow_redirects=True)
        self.assertIn("Concepto actualizado", r.get_data(as_text=True))
        self.assertNotIn(TRASERO_IZQ, self.cli.get("/conceptos/").get_data(as_text=True))
        self.assertIn(TRASERO_IZQ, self.cli.get("/conceptos/?inactivos=1").get_data(as_text=True))


class ActualizacionBaseTest(unittest.TestCase):
    """Una base creada con la etapa 1 recibe la tabla nueva sin perder los clientes."""

    def test_base_vieja_conserva_clientes(self):
        fd, ruta = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)
        try:
            # Esquema tal como quedó en la etapa 1 (solo la tabla de clientes).
            esquema = ESQUEMA.read_text(encoding="utf-8").split("-- Conceptos fijos")[0]
            con = sqlite3.connect(ruta)
            con.executescript(esquema)
            con.execute("INSERT INTO clientes (razon_social, condicion_iva, tipo_doc) "
                        "VALUES ('Cliente viejo', 'CF', 'SIN')")
            con.commit()
            con.close()

            create_app({"TESTING": True, "DATABASE": ruta})

            con = sqlite3.connect(ruta)
            self.assertEqual(con.execute("SELECT razon_social FROM clientes").fetchall(),
                             [("Cliente viejo",)])
            self.assertEqual(con.execute("SELECT count(*) FROM conceptos").fetchone(), (0,))
            con.close()
        finally:
            os.remove(ruta)


if __name__ == "__main__":
    unittest.main()
