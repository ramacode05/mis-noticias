"""Pruebas automáticas de la etapa 1. Correr con: python -m unittest discover tests"""
import os
import tempfile
import unittest

from facturacion import create_app
from facturacion.validaciones import cuit_valido, letra_factura


class ValidacionesTest(unittest.TestCase):
    def test_cuit(self):
        self.assertTrue(cuit_valido("20-12345678-6"))
        self.assertTrue(cuit_valido("30712345671"))
        self.assertFalse(cuit_valido("20-12345678-5"))
        self.assertFalse(cuit_valido("123"))

    def test_letra(self):
        self.assertEqual(letra_factura("RI"), "A")
        for cond in ("MT", "EX", "CF"):
            self.assertEqual(letra_factura(cond), "B")


class ClientesTest(unittest.TestCase):
    def setUp(self):
        fd, self.ruta = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)
        self.app = create_app({"TESTING": True, "DATABASE": self.ruta})
        self.cli = self.app.test_client()

    def tearDown(self):
        os.remove(self.ruta)

    def alta(self, **datos):
        base = {"razon_social": "Ferretería Sur SRL", "condicion_iva": "RI",
                "tipo_doc": "CUIT", "nro_doc": "30-71234567-1", "activo": "1"}
        base.update(datos)
        return self.cli.post("/clientes/nuevo", data=base, follow_redirects=True)

    def test_alta_y_busqueda(self):
        r = self.alta()
        self.assertIn("guardado", r.get_data(as_text=True))
        self.assertIn("Ferretería Sur", self.cli.get("/clientes/?q=ferret").get_data(as_text=True))
        self.assertIn("Ferretería Sur", self.cli.get("/clientes/?q=71234567").get_data(as_text=True))
        self.assertNotIn("Ferretería Sur", self.cli.get("/clientes/?q=zzz").get_data(as_text=True))

    def test_cuit_invalido(self):
        r = self.alta(nro_doc="30-71234567-2")
        self.assertIn("CUIT no es válido", r.get_data(as_text=True))

    def test_ri_requiere_cuit(self):
        r = self.alta(tipo_doc="DNI", nro_doc="12345678")
        self.assertIn("debe tener CUIT", r.get_data(as_text=True))

    def test_consumidor_final_sin_documento(self):
        r = self.alta(razon_social="Juan Pérez", condicion_iva="CF", tipo_doc="SIN", nro_doc="")
        self.assertIn("guardado", r.get_data(as_text=True))

    def test_documento_duplicado(self):
        self.alta()
        r = self.alta(razon_social="Otro")
        self.assertIn("Ya existe un cliente", r.get_data(as_text=True))

    def test_edicion(self):
        self.alta()
        r = self.cli.post("/clientes/1", data={
            "razon_social": "Ferretería Norte SRL", "condicion_iva": "RI",
            "tipo_doc": "CUIT", "nro_doc": "30712345671", "activo": "1"},
            follow_redirects=True)
        texto = r.get_data(as_text=True)
        self.assertIn("actualizado", texto)
        self.assertIn("Ferretería Norte", texto)

    def test_inactivo_oculto(self):
        self.alta(activo="")
        self.assertNotIn("Ferretería Sur", self.cli.get("/clientes/").get_data(as_text=True))
        self.assertIn("Ferretería Sur", self.cli.get("/clientes/?inactivos=1").get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
