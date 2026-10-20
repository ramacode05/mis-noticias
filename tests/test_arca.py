"""Pruebas de la etapa 10 (conexión con ARCA). Correr con: python -m unittest discover tests

No se conectan a ARCA: usan un ARCA simulado (ArcaFalso) que responde con el formato de los
web services reales (WSAA y WSFEv1). Comprueban que los pedidos se arman bien y que las
respuestas (aprobación, rechazo, corte de comunicación) se manejan como corresponde.
"""
import datetime
import os
import re
import sqlite3
import tempfile
import unittest
from unittest import mock
from xml.sax.saxutils import escape

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization

from facturacion import arca
from tests.test_facturas import HOY, BaseFacturas


def sobre(contenido):
    return ('<?xml version="1.0" encoding="utf-8"?><soap:Envelope '
            'xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"><soap:Body>'
            f"{contenido}</soap:Body></soap:Envelope>").encode()


def campo(xml, nombre):
    m = re.search(rf"<ar:{nombre}>([^<]*)</ar:{nombre}>", xml)
    return m.group(1) if m else None


class ArcaFalso:
    """Imita las respuestas de WSAA y WSFEv1."""

    def __init__(self):
        self.ultimos = {}          # (pto_vta, tipo) -> último número autorizado
        self.autorizados = {}      # (pto_vta, tipo, numero) -> CAE
        self.logins = 0
        self.pedidos = []          # XML de cada FECAESolicitar
        self.rechazar = None       # mensaje de error para el próximo FECAESolicitar
        self.sin_relacion = False  # el certificado no está autorizado a facturar por la empresa
        self.cortar_despues = False  # autoriza pero "se corta internet" antes de responder

    def __call__(self, url, cuerpo, accion):
        if "LoginCms" in url:
            self.logins += 1
            vence = (datetime.datetime.now(arca.ARGENTINA) + datetime.timedelta(hours=12)).isoformat()
            respuesta = (f"<loginTicketResponse><header><expirationTime>{vence}</expirationTime></header>"
                         "<credentials><token>TOKEN</token><sign>SIGN</sign></credentials></loginTicketResponse>")
            return sobre(f"<loginCmsResponse><loginCmsReturn>{escape(respuesta)}</loginCmsReturn></loginCmsResponse>")
        metodo = accion.rsplit("/", 1)[-1]
        if metodo == "FEDummy":
            return sobre("<FEDummyResponse><FEDummyResult><AppServer>OK</AppServer><DbServer>OK</DbServer>"
                         "<AuthServer>OK</AuthServer></FEDummyResult></FEDummyResponse>")
        assert "<ar:Token>TOKEN</ar:Token>" in cuerpo and "<ar:Cuit>30707871918</ar:Cuit>" in cuerpo
        pv, tipo = int(campo(cuerpo, "PtoVta")), int(campo(cuerpo, "CbteTipo"))
        if metodo == "FECompUltimoAutorizado":
            if self.sin_relacion:
                return sobre("<FECompUltimoAutorizadoResponse><FECompUltimoAutorizadoResult><Errors><Err>"
                             "<Code>600</Code><Msg>ValidacionDeToken: No aparecio CUIT en lista de relaciones: "
                             "30707871918</Msg></Err></Errors></FECompUltimoAutorizadoResult>"
                             "</FECompUltimoAutorizadoResponse>")
            return sobre(f"<FECompUltimoAutorizadoResponse><FECompUltimoAutorizadoResult><PtoVta>{pv}</PtoVta>"
                         f"<CbteTipo>{tipo}</CbteTipo><CbteNro>{self.ultimos.get((pv, tipo), 0)}</CbteNro>"
                         "</FECompUltimoAutorizadoResult></FECompUltimoAutorizadoResponse>")
        if metodo == "FECompConsultar":
            numero = int(campo(cuerpo, "CbteNro"))
            cae = self.autorizados.get((pv, tipo, numero))
            if not cae:
                return sobre("<FECompConsultarResponse><FECompConsultarResult><Errors><Err><Code>602</Code>"
                             "<Msg>No existen datos</Msg></Err></Errors></FECompConsultarResult></FECompConsultarResponse>")
            return sobre(f"<FECompConsultarResponse><FECompConsultarResult><ResultGet><CodAutorizacion>{cae}"
                         "</CodAutorizacion><FchVto>20261030</FchVto><CbteFch>20261019</CbteFch>"
                         "</ResultGet></FECompConsultarResult></FECompConsultarResponse>")
        if metodo == "FECAESolicitar":
            self.pedidos.append(cuerpo)
            numero = int(campo(cuerpo, "CbteDesde"))
            if self.rechazar or numero != self.ultimos.get((pv, tipo), 0) + 1:
                motivo = self.rechazar or "10016: El numero de comprobante no es el siguiente"
                self.rechazar = None
                codigo, msg = motivo.split(": ", 1)
                return sobre("<FECAESolicitarResponse><FECAESolicitarResult><FeCabResp><Resultado>R</Resultado>"
                             "</FeCabResp><FeDetResp><FECAEDetResponse><Resultado>R</Resultado><CAE></CAE>"
                             f"</FECAEDetResponse></FeDetResp><Errors><Err><Code>{codigo}</Code><Msg>{msg}</Msg>"
                             "</Err></Errors></FECAESolicitarResult></FECAESolicitarResponse>")
            cae = f"7643{numero:010d}"
            self.ultimos[(pv, tipo)] = numero
            self.autorizados[(pv, tipo, numero)] = cae
            if self.cortar_despues:
                self.cortar_despues = False
                raise arca.SinRespuesta("Se cortó la comunicación con ARCA.")
            return sobre("<FECAESolicitarResponse><FECAESolicitarResult><FeCabResp><Resultado>A</Resultado>"
                         f"</FeCabResp><FeDetResp><FECAEDetResponse><Resultado>A</Resultado><CAE>{cae}</CAE>"
                         "<CAEFchVto>20261030</CAEFchVto><Observaciones><Obs><Code>10217</Code>"
                         "<Msg>Observación de prueba</Msg></Obs></Observaciones></FECAEDetResponse></FeDetResp>"
                         "</FECAESolicitarResult></FECAESolicitarResponse>")
        raise AssertionError(f"Método inesperado: {metodo}")


def certificado_para(pedido_pem, clave_pem):
    """Hace lo que hace ARCA: firma un certificado para la clave del pedido."""
    pedido = x509.load_pem_x509_csr(pedido_pem)
    clave = serialization.load_pem_private_key(clave_pem, password=None)
    ahora = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(pedido.subject).issuer_name(pedido.subject)
            .public_key(pedido.public_key()).serial_number(1).not_valid_before(ahora)
            .not_valid_after(ahora + datetime.timedelta(days=730)).sign(clave, hashes.SHA256()))
    return cert.public_bytes(serialization.Encoding.PEM)


class ConArca(BaseFacturas):
    def setUp(self):
        super().setUp()
        self.carpeta = tempfile.mkdtemp()
        self.app.config["ARCA_CARPETA"] = self.carpeta
        self.falso = ArcaFalso()
        parche = mock.patch.object(arca, "_post", self.falso)
        parche.start()
        self.addCleanup(parche.stop)

    def configurar(self, ambiente="homologacion", punto_venta="4", activar=True):
        self.cli.post(f"/arca/{ambiente}/pedido")
        r = arca.rutas(self.carpeta, ambiente)
        with open(r["pedido"], "rb") as f, open(r["clave"], "rb") as g:
            cert = certificado_para(f.read(), g.read())
        self.cli.post(f"/arca/{ambiente}/certificado", data={"texto": cert.decode()})
        self.cli.post(f"/arca/{ambiente}/punto-venta", data={"punto_venta": punto_venta})
        if activar:
            self.cli.post("/arca/activar", data={"ambiente": ambiente, "confirmo": "1"})


class PantallaArcaTest(ConArca):
    def test_pasos_y_prueba_de_conexion(self):
        html = self.cli.get("/arca/").get_data(as_text=True)
        self.assertIn("SIN CONEXIÓN", html)
        self.cli.post("/arca/homologacion/pedido")
        html = self.cli.get("/arca/").get_data(as_text=True)
        self.assertIn("-----BEGIN CERTIFICATE REQUEST-----", html)
        r = self.cli.get("/arca/homologacion/pedido.csr")
        self.assertIn(b"CERTIFICATE REQUEST", r.data)
        self.configurar(activar=False)
        html = self.cli.post("/arca/homologacion/probar").get_data(as_text=True)
        self.assertIn("ARCA aceptó el certificado", html)
        self.assertIn("Último número de Factura A autorizado en el 00004: 0", html)
        html = self.cli.post("/arca/activar", data={"ambiente": "homologacion"},
                             follow_redirects=True).get_data(as_text=True)
        self.assertIn("CONECTADO A ARCA - HOMOLOGACIÓN", html)

    def test_falta_autorizar_cuit_de_la_empresa(self):
        self.configurar(activar=False)
        self.falso.sin_relacion = True
        html = self.cli.post("/arca/homologacion/probar").get_data(as_text=True)
        self.assertIn("ARCA aceptó el certificado", html)
        self.assertIn("falta autorizarlo a facturar por la empresa", html)
        self.assertIn("CUIT representada 30707871918", html)

    def test_pedido_contiene_cuit_y_alias(self):
        self.cli.post("/arca/homologacion/pedido")
        with open(arca.rutas(self.carpeta, "homologacion")["pedido"], "rb") as f:
            pedido = x509.load_pem_x509_csr(f.read())
        texto = pedido.subject.rfc4514_string()
        self.assertIn("CN=facturacion", texto)
        self.assertIn("CUIT 30707871918", texto)
        self.assertTrue(pedido.is_signature_valid)

    def test_certificado_de_otra_clave_se_rechaza(self):
        self.cli.post("/arca/homologacion/pedido")
        otra = tempfile.mkdtemp()
        arca.generar_clave_y_pedido(otra, "homologacion")
        r = arca.rutas(otra, "homologacion")
        with open(r["pedido"], "rb") as f, open(r["clave"], "rb") as g:
            cert = certificado_para(f.read(), g.read())
        html = self.cli.post("/arca/homologacion/certificado", data={"texto": cert.decode()},
                             follow_redirects=True).get_data(as_text=True)
        self.assertIn("no corresponde a esta clave", html)
        html = self.cli.post("/arca/homologacion/certificado", data={"texto": "basura"},
                             follow_redirects=True).get_data(as_text=True)
        self.assertIn("no es un certificado válido", html)

    def test_no_se_activa_sin_pasos_ni_produccion_sin_confirmar(self):
        html = self.cli.post("/arca/activar", data={"ambiente": "homologacion"},
                             follow_redirects=True).get_data(as_text=True)
        self.assertIn("faltan pasos", html)
        self.configurar("produccion", activar=False)
        html = self.cli.post("/arca/activar", data={"ambiente": "produccion"},
                             follow_redirects=True).get_data(as_text=True)
        self.assertIn("tildá la casilla", html)
        html = self.cli.post("/arca/activar", data={"ambiente": "produccion", "confirmo": "1"},
                             follow_redirects=True).get_data(as_text=True)
        self.assertIn("CONECTADO A ARCA - PRODUCCIÓN", html)

    def test_firma_valida(self):
        self.configurar(activar=False)
        r = arca.rutas(self.carpeta, "homologacion")
        with open(r["clave"], "rb") as f, open(r["certificado"], "rb") as g:
            cms = arca.firmar(arca.pedido_de_acceso(), f.read(), g.read())
        self.assertTrue(len(cms) > 1000)


class EmisionArcaTest(ConArca):
    def test_factura_autorizada_con_numero_de_arca(self):
        self.configurar()
        self.falso.ultimos[(4, 1)] = 7          # en ARCA ya hay 7 facturas A en el 00004
        html = self.cli.get("/facturas/nueva").get_data(as_text=True)
        self.assertIn("00004-Web services ARCA - HOMOLOGACIÓN", html)
        html = self.confirmar(punto_venta="4", remito_numero="6575")
        self.assertIn("Factura A N° 8 autorizada por ARCA en HOMOLOGACIÓN", html)
        self.assertIn("Observación de ARCA: 10217: Observación de prueba", html)
        f = self.facturas()[0]
        self.assertEqual((f["numero"], f["cae"], f["cae_vto"], f["arca"], f["prueba"]),
                         (8, "76430000000008", "2026-10-30", "homologacion", 1))
        pedido = self.falso.pedidos[0]
        for esperado in ("<ar:PtoVta>4</ar:PtoVta>", "<ar:CbteTipo>1</ar:CbteTipo>",
                         "<ar:Concepto>3</ar:Concepto>", "<ar:DocTipo>80</ar:DocTipo>",
                         "<ar:DocNro>30712345671</ar:DocNro>", "<ar:CbteDesde>8</ar:CbteDesde>",
                         f"<ar:CbteFch>{HOY.replace('-', '')}</ar:CbteFch>",
                         "<ar:ImpTotal>72600.00</ar:ImpTotal>", "<ar:ImpNeto>60000.00</ar:ImpNeto>",
                         "<ar:ImpIVA>12600.00</ar:ImpIVA>", "<ar:MonId>PES</ar:MonId>",
                         "<ar:CondicionIVAReceptorId>1</ar:CondicionIVAReceptorId>",
                         "<ar:Id>5</ar:Id><ar:BaseImp>60000.00</ar:BaseImp><ar:Importe>12600.00</ar:Importe>",
                         "<ar:FchServDesde>", "<ar:FchVtoPago>"):
            self.assertIn(esperado, pedido)
        self.assertNotIn("CbtesAsoc", pedido)

    def test_rechazo_no_guarda_nada(self):
        self.configurar()
        self.falso.rechazar = "10015: El CUIT del receptor no es valido"
        html = self.confirmar(punto_venta="4")
        self.assertIn("ARCA no autorizó la factura. No se guardó nada.", html)
        self.assertIn("10015: El CUIT del receptor no es valido", html)
        self.assertEqual(self.facturas(), [])

    def test_corte_de_comunicacion_recupera_el_cae(self):
        self.configurar()
        self.falso.cortar_despues = True
        html = self.confirmar(punto_venta="4")
        self.assertIn("Factura A N° 1 autorizada por ARCA", html)
        self.assertEqual(self.facturas()[0]["cae"], "76430000000001")

    def test_sin_internet_no_guarda(self):
        self.configurar()
        self.assertFalse(os.path.exists(arca.rutas(self.carpeta, "homologacion")["ticket"]))
        with mock.patch.object(arca, "_post", side_effect=arca.SinRespuesta("Sin internet.")):
            html = self.confirmar(punto_venta="4")
        self.assertIn("Sin internet.", html)
        self.assertEqual(self.facturas(), [])

    def test_ticket_se_reusa(self):
        self.configurar()
        self.confirmar(punto_venta="4")
        self.confirmar(punto_venta="4")
        self.assertEqual(self.falso.logins, 1)

    def test_factura_b_consumidor_final(self):
        self.configurar()
        self.confirmar(punto_venta="4", cliente_id="2")
        pedido = self.falso.pedidos[0]
        self.assertIn("<ar:CbteTipo>6</ar:CbteTipo>", pedido)
        self.assertIn("<ar:DocTipo>99</ar:DocTipo><ar:DocNro>0</ar:DocNro>", pedido)
        self.assertIn("<ar:CondicionIVAReceptorId>5</ar:CondicionIVAReceptorId>", pedido)

    def test_nota_de_credito_asociada(self):
        self.configurar()
        self.confirmar(punto_venta="4")
        html = self.cli.post("/facturas/1/nota-credito", data={"fecha": HOY, "token": "nc"},
                             follow_redirects=True).get_data(as_text=True)
        self.assertIn("Nota de Crédito A N° 1 autorizada por ARCA", html)
        pedido = self.falso.pedidos[1]
        self.assertIn("<ar:CbteTipo>3</ar:CbteTipo>", pedido)
        self.assertIn("<ar:CbtesAsoc><ar:CbteAsoc><ar:Tipo>1</ar:Tipo><ar:PtoVta>4</ar:PtoVta>"
                      "<ar:Nro>1</ar:Nro><ar:Cuit>30707871918</ar:Cuit>", pedido)
        nc = self.facturas()[1]
        self.assertEqual((nc["cae"], nc["arca"], nc["asociado_id"]), ("76430000000001", "homologacion", 1))

    def test_nc_de_factura_de_arca_sin_conexion_activa(self):
        self.configurar()
        self.confirmar(punto_venta="4")
        self.cli.post("/arca/activar", data={"ambiente": ""})
        html = self.cli.post("/facturas/1/nota-credito", data={"fecha": HOY, "token": "nc"},
                             follow_redirects=True).get_data(as_text=True)
        self.assertIn("Activalo en la pantalla ARCA", html)

    def test_produccion_es_real_y_no_se_borra(self):
        self.configurar("produccion")
        html = self.confirmar(punto_venta="4")
        self.assertIn("autorizada por ARCA. CAE", html)
        f = self.facturas()[0]
        self.assertEqual((f["prueba"], f["arca"]), (0, "produccion"))
        html = self.cli.post("/facturas/1/eliminar", follow_redirects=True).get_data(as_text=True)
        self.assertIn("no se pueden eliminar", html)
        self.assertEqual(self.cli.get("/facturas/1/pdf").status_code, 200)

    def test_numeracion_separada_de_las_pruebas_del_sistema(self):
        self.confirmar(punto_venta="2")                  # prueba del sistema 00002-1
        self.configurar(punto_venta="2")                 # homologación usando el mismo número de PV
        self.confirmar(punto_venta="2")
        self.assertEqual([(f["arca"], f["numero"]) for f in self.facturas()],
                         [(None, 1), ("homologacion", 1)])

    def test_sin_conexion_sigue_como_antes(self):
        html = self.confirmar()
        self.assertIn("generada (de prueba)", html)
        self.assertEqual(self.falso.pedidos, [])


class QrTest(unittest.TestCase):
    def test_datos_qr_con_cae(self):
        from facturacion.pdf import datos_qr
        f = {"fecha": "2026-10-19", "punto_venta": 4, "cbte_tipo": 1, "numero": 8, "total": 7260000,
             "cliente_tipo_doc": "CUIT", "cliente_nro_doc": "30712345671", "cae": "76430000000008"}
        self.assertTrue(datos_qr(f).startswith("https://www.afip.gob.ar/fe/qr/?p="))


if __name__ == "__main__":
    unittest.main()
