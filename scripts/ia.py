"""Llamadas a la API de Claude: clasificar/agrupar y redactar noticias."""

import json

import anthropic

# Precios de Claude Haiku 4.5 (USD por millón de tokens).
PRECIO_ENTRADA = 1.00
PRECIO_SALIDA = 5.00

TEMAS = ["argentina", "economia", "mercados", "cripto", "tecnologia", "geopolitica"]

SISTEMA_CLASIFICAR = """Sos el editor de un servicio personal de noticias para un inversor argentino.
Tu tarea: decidir qué titulares de RSS son relevantes y agrupar los que cuentan la MISMA noticia.

TEMAS DE INTERÉS
- Economía argentina: inflación, dólar (oficial, MEP, CCL, blue), BCRA, tasas, reservas, deuda, FMI, riesgo país, bonos, acciones argentinas, política económica, medidas del gobierno con impacto económico, elecciones y política solo si afectan a la economía o los mercados.
- Economía internacional: crecimiento, inflación, empleo, comercio, aranceles, bancos centrales (Fed, BCE, BoJ, PBoC, etc.).
- Mercados financieros: acciones, bonos, tasas, monedas, commodities (petróleo, gas, oro, soja, trigo, cobre, litio), cripto, resultados de empresas grandes, fusiones, quiebras, bancos.
- Cualquier hecho que pueda mover el valor de las inversiones.
- Tecnología e inteligencia artificial: empresas tecnológicas, IA, chips/semiconductores, regulación tecnológica, ciberseguridad relevante.
- Conflictos internacionales y geopolítica: guerras, sanciones, tensiones entre potencias, elecciones de países importantes, energía.

EXCLUIR (relevancia 0): policiales y crímenes comunes, farándula, espectáculos, deportes, estilo de vida, salud/clima/curiosidades sin impacto económico o geopolítico, horóscopos, recetas, reseñas de productos, ofertas y guías de compra, notas de opinión sin hechos nuevos, contenido patrocinado.

ESCALA DE RELEVANCIA
0 = fuera de tema. 1 = marginal. 2 = menor o muy local. 3 = interesante. 4 = importante. 5 = muy importante, de primera plana.

AGRUPAMIENTO
- Si un titular cuenta el mismo hecho que una "historia existente", poné en "grupo" el código de esa historia (ej. "H3").
- Si no, creá grupos nuevos "N1", "N2", ...; titulares nuevos que cuenten el mismo hecho comparten el mismo grupo N.
- Mismo hecho = mismo acontecimiento concreto (ej. "la Fed bajó la tasa 0,25 hoy"), no solo el mismo tema general.
- "aporta_novedad": true solo si el titular se suma a una historia existente y trae información nueva sustancial (una cifra, una reacción del mercado, un giro). Si no, false.
- Para titulares con relevancia 0 poné grupo "X".

Respondé un elemento por cada titular recibido, con su mismo "id"."""

SISTEMA_REDACTAR = """Sos un periodista económico y de política internacional que escribe para un lector argentino que invierte y quiere entender rápido y bien lo que pasa en el mundo.

Recibís una o más versiones de UNA misma noticia, publicadas por distintos medios (a veces en inglés). Escribí en español rioplatense neutro y claro (sin voseo exagerado, sin jerga innecesaria):

- "titular": claro, informativo y preciso, sin sensacionalismo ni clickbait. Máximo ~110 caracteres.
- "que_paso": el hecho concreto con los datos clave (quién, qué, cuánto, cuándo, dónde). Combiná la información de todas las fuentes.
- "contexto": los antecedentes necesarios para entenderlo. Explicá brevemente términos técnicos (por ejemplo qué es el CCL, el riesgo país o una curva de rendimientos) cuando aparezcan.
- "por_que_importa": consecuencias posibles y por qué le importa a un inversor; qué activos, sectores, monedas o países podrían verse afectados, y qué conviene seguir de cerca.
- La extensión depende de la noticia: un hecho simple puede resolverse en pocas oraciones; algo complejo merece varios párrafos. Priorizá calidad y claridad antes que brevedad. Separá párrafos con una línea en blanco.
- "temas": uno o más de: argentina, economia, mercados, cripto, tecnologia, geopolitica.
- "alto_impacto": true SOLO si la noticia puede generar volatilidad significativa en los mercados financieros (ej.: decisiones o sorpresas de bancos centrales, datos de inflación/empleo muy distintos a lo esperado, escalada bélica que afecte energía o rutas comerciales, nuevos aranceles o sanciones importantes, crisis bancarias, default o reestructuración de deuda soberana, resultados que sorprenden en empresas gigantes, en Argentina: cambios en el régimen cambiario o el cepo, acuerdos o tensiones con el FMI, saltos fuertes del dólar o del riesgo país, decisiones del BCRA). Sé exigente: la mayoría de las noticias NO son de alto impacto.
- "motivo_impacto": si es de alto impacto, una frase sobre qué mercados o activos podrían moverse y por qué. Si no, cadena vacía.

REGLAS DE EXACTITUD (muy importante)
- No inventes datos. Cifras, nombres, fechas y citas deben salir de las fuentes recibidas.
- Tu conocimiento general puede estar desactualizado: usalo solo para antecedentes de fondo y estables. No afirmes como actuales cargos, precios, tasas o cotizaciones que no estén en las fuentes.
- Si las fuentes se contradicen, decilo.
- Si la información es escasa (solo un titular), escribí algo breve y no rellenes con especulación."""

ESQUEMA_CLASIFICAR = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "relevancia": {"type": "integer"},
                    "grupo": {"type": "string"},
                    "aporta_novedad": {"type": "boolean"},
                },
                "required": ["id", "relevancia", "grupo", "aporta_novedad"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}

ESQUEMA_REDACTAR = {
    "type": "object",
    "properties": {
        "titular": {"type": "string"},
        "que_paso": {"type": "string"},
        "contexto": {"type": "string"},
        "por_que_importa": {"type": "string"},
        "temas": {"type": "array", "items": {"type": "string", "enum": TEMAS}},
        "alto_impacto": {"type": "boolean"},
        "motivo_impacto": {"type": "string"},
    },
    "required": ["titular", "que_paso", "contexto", "por_que_importa", "temas", "alto_impacto", "motivo_impacto"],
    "additionalProperties": False,
}


class SinPresupuesto(Exception):
    pass


class ClienteIA:
    def __init__(self, modelo, presupuesto_restante_usd):
        self.cliente = anthropic.Anthropic(max_retries=3, timeout=120.0)
        self.modelo = modelo
        self.restante = presupuesto_restante_usd
        self.gastado = 0.0

    def _llamar(self, sistema, texto, esquema, max_tokens):
        if self.restante - self.gastado <= 0:
            raise SinPresupuesto()
        r = self.cliente.messages.create(
            model=self.modelo,
            max_tokens=max_tokens,
            system=sistema,
            messages=[{"role": "user", "content": texto}],
            output_config={"format": {"type": "json_schema", "schema": esquema}},
        )
        self.gastado += (
            r.usage.input_tokens * PRECIO_ENTRADA + r.usage.output_tokens * PRECIO_SALIDA
        ) / 1_000_000
        if r.stop_reason != "end_turn":
            raise ValueError(f"respuesta incompleta (stop_reason={r.stop_reason})")
        texto_resp = next(b.text for b in r.content if b.type == "text")
        return json.loads(texto_resp)

    def clasificar(self, items, historias_recientes, fecha):
        """items: [{"id","medio","titulo","resumen"}]; historias: [{"alias","titular"}]."""
        lineas = ["Fecha y hora actual: " + fecha, "", "HISTORIAS EXISTENTES (últimas horas):"]
        if historias_recientes:
            lineas += [f'{h["alias"]}: {h["titular"]}' for h in historias_recientes]
        else:
            lineas.append("(ninguna)")
        lineas += ["", "TITULARES NUEVOS:"]
        for it in items:
            linea = f'[{it["id"]}] ({it["medio"]}) {it["titulo"]}'
            if it.get("resumen"):
                linea += f' — {it["resumen"][:220]}'
            lineas.append(linea)
        datos = self._llamar(SISTEMA_CLASIFICAR, "\n".join(lineas), ESQUEMA_CLASIFICAR, 8000)
        return datos["items"]

    def redactar(self, fuentes, fecha, version_anterior=None):
        """fuentes: [{"medio","titulo","resumen","texto","publicado_txt"}]."""
        partes = [f"Fecha y hora actual: {fecha}", ""]
        if version_anterior:
            partes += [
                "Ya habías publicado esta versión de la noticia. Actualizala integrando la información nueva:",
                json.dumps(version_anterior, ensure_ascii=False),
                "",
            ]
        for i, f in enumerate(fuentes, 1):
            partes.append(f"--- FUENTE {i}: {f['medio']} ({f['publicado_txt']}) ---")
            partes.append(f"Título: {f['titulo']}")
            if f.get("resumen"):
                partes.append(f"Resumen: {f['resumen']}")
            if f.get("texto"):
                partes.append(f"Texto de la nota:\n{f['texto']}")
            partes.append("")
        datos = self._llamar(SISTEMA_REDACTAR, "\n".join(partes), ESQUEMA_REDACTAR, 3000)
        datos["temas"] = [t for t in dict.fromkeys(datos["temas"]) if t in TEMAS] or ["economia"]
        if not datos["alto_impacto"]:
            datos["motivo_impacto"] = ""
        return datos
