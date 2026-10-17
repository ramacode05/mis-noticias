"""Pruebas del uso compartido con Google Drive: aviso de "en uso", copias y botón Cerrar."""
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest import mock

from facturacion import candado, copias, create_app


class CandadoTest(unittest.TestCase):
    def setUp(self):
        self.carpeta = tempfile.mkdtemp()
        self.ruta = os.path.join(self.carpeta, candado.ARCHIVO)

    def test_sin_archivo_esta_libre(self):
        self.assertEqual(candado.revisar(self.ruta, pc="CASA")[0], "libre")

    def test_abierto_en_la_otra_pc_con_latido_reciente(self):
        candado.escribir(self.ruta, "abierto", pc="DEPTO")
        self.assertEqual(candado.revisar(self.ruta, pc="CASA")[0], "en_uso")

    def test_abierto_en_esta_misma_pc_se_puede_abrir(self):
        candado.escribir(self.ruta, "abierto", pc="CASA")  # por ejemplo, se cortó la luz
        self.assertEqual(candado.revisar(self.ruta, pc="CASA")[0], "libre")

    def test_cerrado_en_la_otra_pc_esta_libre(self):
        candado.escribir(self.ruta, "cerrado", pc="DEPTO")
        self.assertEqual(candado.revisar(self.ruta, pc="CASA")[0], "libre")

    def test_otra_pc_sin_latido_es_dudoso(self):
        candado.escribir(self.ruta, "abierto", pc="DEPTO")
        mas_tarde = datetime.now() + timedelta(minutes=10)
        estado, datos = candado.revisar(self.ruta, pc="CASA", ahora=mas_tarde)
        self.assertEqual(estado, "dudoso")
        self.assertEqual(datos["pc"], "DEPTO")

    def test_archivo_roto_se_toma_como_libre(self):
        with open(self.ruta, "w") as f:
            f.write("{basura")
        self.assertEqual(candado.revisar(self.ruta, pc="CASA")[0], "libre")

    def test_candado_abrir_y_cerrar(self):
        uso = candado.Candado(self.ruta)
        with mock.patch.object(candado, "nombre_pc", return_value="DEPTO"):
            uso.abrir()
            self.assertEqual(candado.revisar(self.ruta, pc="CASA")[0], "en_uso")
            uso.cerrar()
            uso.cerrar()  # cerrar dos veces no falla
        self.assertEqual(candado.leer(self.ruta)["estado"], "cerrado")
        self.assertEqual(candado.revisar(self.ruta, pc="CASA")[0], "libre")


class CopiasTest(unittest.TestCase):
    def test_copia_y_conserva_las_ultimas(self):
        carpeta = tempfile.mkdtemp()
        base = os.path.join(carpeta, "facturacion.sqlite")
        con = sqlite3.connect(base)
        con.execute("CREATE TABLE t (x)")
        con.execute("INSERT INTO t VALUES (42)")
        con.commit()
        con.close()
        destino = os.path.join(carpeta, "copias")
        for i in range(5):
            # Nombres distintos aunque se hagan en el mismo segundo.
            with mock.patch.object(copias, "datetime") as dt:
                dt.now.return_value = datetime(2026, 10, 17, 10, 0, i)
                ruta = copias.hacer_copia(base, destino, conservar=3)
        self.assertEqual(len(os.listdir(destino)), 3)
        self.assertEqual(sqlite3.connect(ruta).execute("SELECT x FROM t").fetchone(), (42,))

    def test_sin_base_no_copia(self):
        self.assertIsNone(copias.hacer_copia("/no/existe.sqlite", tempfile.mkdtemp()))


class CerrarSistemaTest(unittest.TestCase):
    def setUp(self):
        fd, self.ruta = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)

    def tearDown(self):
        os.remove(self.ruta)

    def test_boton_en_el_menu(self):
        app = create_app({"TESTING": True, "DATABASE": self.ruta})
        html = app.test_client().get("/clientes/").get_data(as_text=True)
        self.assertIn("Cerrar sistema", html)

    def test_cerrar_marca_cerrado_y_apaga(self):
        uso = mock.Mock()
        app = create_app({"TESTING": True, "DATABASE": self.ruta, "CANDADO": uso})
        with mock.patch("facturacion.threading.Timer") as timer:
            html = app.test_client().post("/cerrar").get_data(as_text=True)
        self.assertIn("El sistema se cerró", html)
        uso.cerrar.assert_called_once()
        timer.return_value.start.assert_called_once()

    def test_cerrar_sin_candado_no_apaga(self):
        app = create_app({"TESTING": True, "DATABASE": self.ruta})
        with mock.patch("facturacion.threading.Timer") as timer:
            app.test_client().post("/cerrar")
        timer.assert_not_called()


if __name__ == "__main__":
    unittest.main()
