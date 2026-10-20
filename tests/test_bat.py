"""Revisa los archivos .bat de Windows (no se pueden ejecutar acá, pero sí detectar errores comunes)."""
import re
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
BATS = sorted(RAIZ.glob("*.bat"))


class BatTest(unittest.TestCase):
    def test_hay_bats(self):
        self.assertEqual({b.name for b in BATS}, {"iniciar.bat", "instalar.bat"})

    def test_finales_de_linea_de_windows(self):
        for bat in BATS:
            with self.subTest(bat.name):
                datos = bat.read_bytes()
                self.assertEqual(datos.count(b"\n"), datos.count(b"\r\n"), "todas las líneas con CRLF")

    def test_sin_redirecciones_de_linux(self):
        for bat in BATS:
            with self.subTest(bat.name):
                texto = bat.read_text(encoding="ascii")
                self.assertNotIn("/dev/null", texto, "en Windows es >nul")
                self.assertIsNone(re.search(r"^\s*(export|source|rm |ls |cp )", texto, re.M))

    def test_usan_el_entorno_de_cada_pc(self):
        for bat in BATS:
            with self.subTest(bat.name):
                self.assertIn(r"%LOCALAPPDATA%\FacturacionLouletano\venv", bat.read_text(encoding="ascii"))

    def test_parentesis_balanceados(self):
        for bat in BATS:
            with self.subTest(bat.name):
                abiertos = 0
                for linea in bat.read_text(encoding="ascii").splitlines():
                    if linea.strip().upper().startswith(("REM", "ECHO")):
                        continue
                    sin_comillas = re.sub(r'"[^"]*"', "", linea)
                    sin_comillas = re.sub(r"'[^']*'", "", sin_comillas)
                    abiertos += sin_comillas.count("(") - sin_comillas.count(")")
                    self.assertGreaterEqual(abiertos, 0, linea)
                self.assertEqual(abiertos, 0)
