"""Lectura de los RSS configurados en config.toml."""

import calendar
import hashlib
import html
import re
import time
import tomllib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote_plus, urlsplit, urlunsplit, parse_qsl, urlencode

import feedparser
import requests

RAIZ = Path(__file__).resolve().parent.parent
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36 MisNoticias/1.0"
)
TIMEOUT = 20


def cargar_config():
    with open(RAIZ / "config.toml", "rb") as f:
        return tomllib.load(f)


def url_google_news(dominio, idioma):
    q = quote_plus(f"site:{dominio} when:1d")
    if idioma == "es":
        return f"https://news.google.com/rss/search?q={q}&hl=es-419&gl=AR&ceid=AR:es-419"
    return f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"


def limpiar_texto(texto, largo=400):
    texto = re.sub(r"<[^>]+>", " ", texto or "")
    texto = html.unescape(texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto[:largo]


def normalizar_url(url):
    """Quita parámetros de seguimiento (utm_*, etc.) para detectar duplicados."""
    try:
        p = urlsplit(url)
        qs = [(k, v) for k, v in parse_qsl(p.query) if not k.lower().startswith(("utm_", "fbclid", "gclid", "cmpid", "ref"))]
        return urlunsplit((p.scheme, p.netloc.lower(), p.path.rstrip("/"), urlencode(qs), ""))
    except ValueError:
        return url


def id_item(url, titulo):
    base = normalizar_url(url) or titulo
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]


def _descargar(url):
    r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
    r.raise_for_status()
    feed = feedparser.parse(r.content)
    if not feed.entries:
        raise ValueError("el RSS no tiene entradas")
    return feed


def _leer_fuente(fuente):
    """Prueba las URLs en orden; si todas fallan, usa Google News."""
    intentos = list(fuente["urls"])
    if fuente.get("dominio"):
        intentos.append(url_google_news(fuente["dominio"], fuente.get("idioma", "en")))

    errores = []
    for i, url in enumerate(intentos):
        try:
            feed = _descargar(url)
        except Exception as e:  # noqa: BLE001 - cualquier falla pasa a la alternativa
            errores.append(f"{url} -> {type(e).__name__}: {str(e)[:120]}")
            continue
        es_google = "news.google.com" in url
        items = []
        for e in feed.entries:
            titulo = limpiar_texto(e.get("title", ""), 300)
            link = e.get("link", "")
            if not titulo or not link:
                continue
            t = e.get("published_parsed") or e.get("updated_parsed")
            publicado = calendar.timegm(t) if t else None
            if es_google:
                # Google News agrega " - Medio" al final del título.
                titulo = re.sub(r"\s+-\s+[^-]{2,40}$", "", titulo)
            items.append({
                "id": id_item(link, titulo),
                "medio": fuente["medio"],
                "titulo": titulo,
                "resumen": "" if es_google else limpiar_texto(e.get("summary", "")),
                "url": link,
                "publicado": publicado,
                "muro": bool(fuente.get("muro", False)),
                "idioma": fuente.get("idioma", "en"),
                "via_google": es_google,
            })
        estado = {
            "medio": fuente["medio"],
            "url_configurada": fuente["urls"][0],
            "url_usada": url,
            "ok": True,
            "alternativa": i > 0,
            "items": len(items),
            "errores": errores,
        }
        return items, estado

    return [], {
        "medio": fuente["medio"],
        "url_configurada": fuente["urls"][0],
        "url_usada": None,
        "ok": False,
        "alternativa": False,
        "items": 0,
        "errores": errores,
    }


def leer_todas(config):
    fuentes = config["fuente"]
    with ThreadPoolExecutor(max_workers=12) as ex:
        resultados = list(ex.map(_leer_fuente, fuentes))
    items, estados = [], []
    vistos = set()
    for its, est in resultados:
        estados.append(est)
        for it in its:
            if it["id"] not in vistos:
                vistos.add(it["id"])
                items.append(it)
    return items, estados, int(time.time())


def texto_de_nota(url, max_chars):
    """Descarga la nota original y extrae el texto (si no hay muro de pago)."""
    try:
        import trafilatura

        r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
        r.raise_for_status()
        texto = trafilatura.extract(r.text, include_comments=False, include_tables=False) or ""
        return texto[:max_chars]
    except Exception:  # noqa: BLE001 - si falla, seguimos solo con el resumen del RSS
        return ""
