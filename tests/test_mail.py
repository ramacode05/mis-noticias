"""Pruebas del envío de facturas por mail (Gmail simulado: no se manda nada de verdad)."""
import smtplib
import sqlite3
from unittest import mock

from facturacion import mail
from tests.test_arca import ConArca
from tests.test_facturas import BaseFacturas


class GmailFalso:
    """Reemplaza a smtplib.SMTP_SSL y guarda los mails "enviados"."""
    enviados = []
    error = None

    def __init__(self, servidor, puerto, timeout=None):
        assert (servidor, puerto) == ("smtp.gmail.com", 465)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def login(self, usuario, clave):
        if GmailFalso.error:
            raise GmailFalso.error
        assert clave == "abcdefghijklmnop"

    def send_message(self, mensaje):
        GmailFalso.enviados.append(mensaje)


class Base:
    def preparar_mail(self):
        GmailFalso.enviados = []
        GmailFalso.error = None
        parche = mock.patch.object(smtplib, "SMTP_SSL", GmailFalso)
        parche.start()
        self.addCleanup(parche.stop)
        self.cli.post("/mail/", data={"usuario": "Empresa@Gmail.com", "clave": "abcd efgh ijkl mnop",
                                      "automatico": "1"})
        self.cli.post("/clientes/1", data={"razon_social": "Transportes Sur SA", "condicion_iva": "RI",
                                           "tipo_doc": "CUIT", "nro_doc": "30712345671", "activo": "1",
                                           "email": "pagos@transur.com; admin@transur.com"})


class ConfiguracionMailTest(Base, BaseFacturas):
    def test_configurar_y_mail_de_prueba(self):
        self.preparar_mail()
        html = self.cli.get("/mail/").get_data(as_text=True)
        self.assertIn('value="empresa@gmail.com"', html)
        self.assertIn("ya cargada", html)
        self.assertNotIn("abcdefghijklmnop", html)  # la contraseña no se muestra
        html = self.cli.post("/mail/prueba", follow_redirects=True).get_data(as_text=True)
        self.assertIn("Mail de prueba enviado a empresa@gmail.com", html)
        self.assertEqual(GmailFalso.enviados[0]["To"], "empresa@gmail.com")

    def test_validaciones(self):
        html = self.cli.post("/mail/", data={"usuario": "empresa@hotmail.com", "clave": "abcdefghijklmnop"},
                             follow_redirects=True).get_data(as_text=True)
        self.assertIn("termina en @gmail.com", html)
        html = self.cli.post("/mail/", data={"usuario": "empresa@gmail.com", "clave": "123"},
                             follow_redirects=True).get_data(as_text=True)
        self.assertIn("16 letras", html)

    def test_contraseña_incorrecta(self):
        self.preparar_mail()
        GmailFalso.error = smtplib.SMTPAuthenticationError(535, b"bad")
        html = self.cli.post("/mail/prueba", follow_redirects=True).get_data(as_text=True)
        self.assertIn("Gmail rechazó el usuario o la contraseña", html)

    def test_cliente_con_varios_mails(self):
        self.preparar_mail()
        con = sqlite3.connect(self.ruta)
        self.assertEqual(con.execute("SELECT email FROM clientes WHERE id = 1").fetchone(),
                         ("pagos@transur.com, admin@transur.com",))
        con.close()
        html = self.cli.post("/clientes/1", data={"razon_social": "X", "condicion_iva": "CF", "tipo_doc": "SIN",
                                                  "activo": "1", "email": "pagos@, otro"}).get_data(as_text=True)
        self.assertIn("El email no parece válido", html)

    def test_factura_de_prueba_no_se_manda(self):
        self.preparar_mail()
        self.confirmar()
        html = self.cli.post("/mail/factura/1", follow_redirects=True).get_data(as_text=True)
        self.assertIn("Las facturas de prueba no se mandan", html)
        self.assertEqual(GmailFalso.enviados, [])


class EnvioAutomaticoTest(Base, ConArca):
    def test_factura_real_se_manda_sola(self):
        self.preparar_mail()
        self.configurar("produccion")
        html = self.confirmar(punto_venta="4")
        self.assertIn("Factura enviada por mail a pagos@transur.com, admin@transur.com", html)
        m = GmailFalso.enviados[0]
        self.assertEqual(m["Subject"], "Factura A 00004-00000001")
        self.assertEqual(m["To"], "pagos@transur.com, admin@transur.com")
        self.assertIn("empresa@gmail.com", m["From"])
        self.assertEqual(m.get_body().get_content().strip(), "Buenos días, adjunto factura")
        adjunto = next(m.iter_attachments())
        self.assertEqual(adjunto.get_filename(), "30707871918_001_00004_00000001.pdf")
        self.assertTrue(adjunto.get_content().startswith(b"%PDF"))
        html = self.cli.get("/facturas/1").get_data(as_text=True)
        self.assertIn("enviado a pagos@transur.com", html)
        self.assertIn("Reenviar por mail", html)

    def test_homologacion_no_manda(self):
        self.preparar_mail()
        self.configurar("homologacion")
        self.confirmar(punto_venta="4")
        self.assertEqual(GmailFalso.enviados, [])

    def test_automatico_desactivado(self):
        self.preparar_mail()
        self.cli.post("/mail/", data={"usuario": "empresa@gmail.com", "clave": ""})  # sin tildar automático
        self.configurar("produccion")
        self.confirmar(punto_venta="4")
        self.assertEqual(GmailFalso.enviados, [])
        html = self.cli.post("/mail/factura/1", follow_redirects=True).get_data(as_text=True)
        self.assertIn("Factura enviada por mail", html)  # la contraseña guardada sigue sirviendo
        self.assertEqual(len(GmailFalso.enviados), 1)

    def test_cliente_sin_mail_avisa_y_la_factura_queda(self):
        self.preparar_mail()
        self.configurar("produccion")
        html = self.confirmar(punto_venta="4", cliente_id="2")
        self.assertIn("La factura se emitió bien, pero no se pudo mandar por mail", html)
        self.assertIn("no tiene email cargado", html)
        self.assertEqual(len(self.facturas()), 1)
        self.assertIn("no se pudo mandar", self.cli.get("/facturas/1").get_data(as_text=True))

    def test_falla_de_gmail_no_pierde_la_factura(self):
        self.preparar_mail()
        self.configurar("produccion")
        GmailFalso.error = OSError("sin internet")
        html = self.confirmar(punto_venta="4")
        self.assertIn("autorizada por ARCA", html)
        self.assertIn("No se pudo mandar el mail", html)
        self.assertIsNotNone(self.facturas()[0]["cae"])
        GmailFalso.error = None
        html = self.cli.post("/mail/factura/1", follow_redirects=True).get_data(as_text=True)
        self.assertIn("Factura enviada por mail", html)

    def test_nota_de_credito_no_se_manda_sola(self):
        self.preparar_mail()
        self.configurar("produccion")
        self.confirmar(punto_venta="4")
        from tests.test_facturas import HOY
        self.cli.post("/facturas/1/nota-credito", data={"fecha": HOY, "token": "nc"})
        self.assertEqual(len(GmailFalso.enviados), 1)  # solo la factura


class DireccionesTest(BaseFacturas):
    def test_direcciones(self):
        self.assertEqual(mail.direcciones("a@x.com; b@y.com,c@z.com  d@w.com"),
                         ["a@x.com", "b@y.com", "c@z.com", "d@w.com"])
        self.assertEqual(mail.direcciones(""), [])
