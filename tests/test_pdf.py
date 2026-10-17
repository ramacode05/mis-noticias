"""Pruebas del PDF de la factura (etapa 4). Correr con: python -m unittest discover tests"""
import base64
import json
import re
import sqlite3

from facturacion.pdf import datos_qr, generar_pdf, importe, nombre_archivo
from tests.test_facturas import BaseFacturas


def paginas(pdf):
    return len(re.findall(rb"/Type /Page\b(?!s)", pdf))


class PdfTest(BaseFacturas):
    def factura(self):
        con = sqlite3.connect(self.ruta)
        con.row_factory = sqlite3.Row
        f = dict(con.execute("SELECT * FROM facturas WHERE id = 1").fetchone())
        r = [dict(x) for x in con.execute("SELECT * FROM factura_renglones WHERE factura_id = 1")]
        con.close()
        return f, r

    def test_pdf_tres_copias_y_solo_original(self):
        self.confirmar(remito_numero="6575")
        r = self.cli.get("/facturas/1/pdf")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.mimetype, "application/pdf")
        self.assertTrue(r.data.startswith(b"%PDF"))
        self.assertEqual(paginas(r.data), 3)
        self.assertIn("30707871918_001_00002_00000001_PRUEBA.pdf", r.headers["Content-Disposition"])
        self.assertEqual(paginas(self.cli.get("/facturas/1/pdf?copias=1").data), 1)

    def test_importes_como_arca(self):
        self.assertEqual(importe(33577500), "335775,00")
        self.assertEqual(importe(5), "0,05")
        self.assertEqual(importe(150000000), "1500000,00")

    def test_factura_inexistente(self):
        self.assertEqual(self.cli.get("/facturas/99/pdf").status_code, 404)

    def test_muchos_renglones_ocupan_varias_hojas(self):
        self.confirmar()
        f, r = self.factura()
        muchos = [dict(r[1], descripcion=f"Renglón {i} " + "texto largo " * 8) for i in range(40)]
        self.assertGreater(paginas(generar_pdf(f, muchos, ("ORIGINAL",))), 1)

    def test_factura_b_consumidor_final_sin_documento(self):
        self.confirmar(cliente_id="2")
        r = self.cli.get("/facturas/1/pdf")
        self.assertEqual(paginas(r.data), 3)

    def test_qr_con_cae(self):
        self.confirmar()
        f, r = self.factura()
        f.update(prueba=0, cae="86427925012230", cae_vto="2026-10-25")
        url = datos_qr(f)
        self.assertTrue(url.startswith("https://www.afip.gob.ar/fe/qr/?p="))
        datos = json.loads(base64.b64decode(url.split("p=")[1]))
        self.assertEqual(datos["cuit"], 30707871918)
        self.assertEqual((datos["ptoVta"], datos["tipoCmp"], datos["nroCmp"]), (2, 1, 1))
        self.assertEqual(datos["importe"], 72600.0)
        self.assertEqual((datos["tipoDocRec"], datos["nroDocRec"]), (80, 30712345671))
        self.assertEqual(datos["codAut"], 86427925012230)
        self.assertEqual(nombre_archivo(f), "30707871918_001_00002_00000001.pdf")
        self.assertTrue(generar_pdf(f, r).startswith(b"%PDF"))
