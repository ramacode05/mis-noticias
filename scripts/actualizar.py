"""Proceso principal: lee los RSS, filtra/agrupa con Claude, redacta y guarda el JSON.

Lo ejecuta GitHub Actions cada 15 minutos (.github/workflows/actualizar-noticias.yml).
Para probarlo en tu compu:  ANTHROPIC_API_KEY=... python scripts/actualizar.py
"""

import hashlib
import json
import os
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import anthropic

from fuentes import RAIZ, cargar_config, leer_todas, texto_de_nota
from ia import ClienteIA, SinPresupuesto

ARCHIVO_NOTICIAS = RAIZ / "docs" / "data" / "noticias.json"
ARCHIVO_FUENTES = RAIZ / "docs" / "data" / "fuentes.json"
ARCHIVO_ESTADO = RAIZ / "data" / "estado.json"
TZ_AR = ZoneInfo("America/Argentina/Buenos_Aires")

TAMANO_LOTE_CLASIFICAR = 50
MAX_ITEMS_POR_EJECUCION = 200
MAX_REESCRITURAS_POR_EJECUCION = 8
MAX_FUENTES_POR_HISTORIA = 4
MAX_CARACTERES_NOTA = 3500


def leer_json(ruta, por_defecto):
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return por_defecto


def guardar_json(ruta, datos):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_suffix(".tmp")
    tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(ruta)


def hora_ar(ts):
    if not ts:
        return "hora desconocida"
    return datetime.fromtimestamp(ts, TZ_AR).strftime("%d/%m/%Y %H:%M (hora Argentina)")


def log(msg):
    print(msg, flush=True)


def resumen_actions(lineas):
    ruta = os.environ.get("GITHUB_STEP_SUMMARY")
    if ruta:
        with open(ruta, "a", encoding="utf-8") as f:
            f.write("\n".join(lineas) + "\n")


def fuente_para_web(it):
    return {
        "id": it["id"],
        "medio": it["medio"],
        "titulo": it["titulo"],
        "url": it["url"],
        "publicado": it["publicado"],
        "muro": it["muro"],
    }


def ordenar_fuentes(fuentes):
    # Primero las sin muro de pago; dentro de cada grupo, la más antigua primero.
    return sorted(fuentes, key=lambda f: (f["muro"], f["publicado"] or 0))


def preparar_fuentes_para_redactar(items, leer_nota):
    # Preferimos notas sin muro y que no vengan por Google News (se pueden leer).
    candidatos = sorted(items, key=lambda it: (it["via_google"] or it["muro"], -(it["publicado"] or 0)))
    elegidos = candidatos[:MAX_FUENTES_POR_HISTORIA]
    salida = []
    leidas = 0
    for it in elegidos:
        texto = ""
        if leer_nota and leidas < 2 and not it["via_google"] and not it["muro"]:
            texto = texto_de_nota(it["url"], MAX_CARACTERES_NOTA)
            if texto:
                leidas += 1
        salida.append({
            "medio": it["medio"],
            "titulo": it["titulo"],
            "resumen": it["resumen"],
            "texto": texto,
            "publicado_txt": hora_ar(it["publicado"]),
        })
    return salida


def main():
    config = cargar_config()
    g = config["general"]
    ahora = int(time.time())
    fecha_txt = hora_ar(ahora)
    hoy_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    noticias = leer_json(ARCHIVO_NOTICIAS, {"actualizado": None, "historias": []})
    estado = leer_json(ARCHIVO_ESTADO, {"vistos": {}, "gasto": {"fecha": hoy_utc, "usd": 0.0}})
    if estado["gasto"].get("fecha") != hoy_utc:
        estado["gasto"] = {"fecha": hoy_utc, "usd": 0.0}
    vistos = estado["vistos"]
    primera_vez = not vistos and not noticias["historias"]

    # ---------- 1. Leer RSS ----------
    items, estados_fuentes, _ = leer_todas(config)
    log(f"RSS leídos: {len(items)} titulares de {len(estados_fuentes)} feeds")
    for e in estados_fuentes:
        if not e["ok"]:
            log(f"  ✗ {e['medio']}: NO FUNCIONA -> {e['errores']}")
        elif e["alternativa"]:
            log(f"  ~ {e['medio']}: usando alternativa {e['url_usada']}")

    anterior_fuentes = leer_json(ARCHIVO_FUENTES, {"feeds": []})
    firma = lambda lst: [(e["medio"], e["url_configurada"], e["ok"], e["url_usada"]) for e in lst]  # noqa: E731
    if firma(anterior_fuentes.get("feeds", [])) != firma(estados_fuentes):
        guardar_json(ARCHIVO_FUENTES, {"revisado": ahora, "feeds": estados_fuentes})

    # ---------- 2. Elegir titulares nuevos ----------
    horas = g["horas_primera_vez"] if primera_vez else g["antiguedad_maxima_horas"]
    limite = ahora - horas * 3600
    ya_publicados = {f["id"] for h in noticias["historias"] for f in h["fuentes"]}
    nuevos = []
    for it in items:
        if it["id"] in vistos or it["id"] in ya_publicados:
            continue
        if it["publicado"] is None:
            it["publicado"] = ahora
        if it["publicado"] < limite:
            continue
        nuevos.append(it)
    nuevos.sort(key=lambda it: -it["publicado"])
    nuevos = nuevos[:MAX_ITEMS_POR_EJECUCION]
    log(f"Titulares nuevos a analizar: {len(nuevos)}")

    if not nuevos:
        log("Nada nuevo. Fin.")
        return

    restante = g["presupuesto_diario_usd"] - estado["gasto"]["usd"]
    if restante <= 0:
        log(f"Se alcanzó el presupuesto diario (USD {g['presupuesto_diario_usd']}). Se reanuda mañana (UTC).")
        return
    ia = ClienteIA(g["modelo"], restante)

    # ---------- 3. Clasificar y agrupar ----------
    historias = noticias["historias"]
    recientes = sorted(
        [h for h in historias if h["publicado"] >= ahora - 36 * 3600],
        key=lambda h: -h["publicado"],
    )[:150]
    alias_a_historia = {f"H{i + 1}": h for i, h in enumerate(recientes)}
    lista_recientes = [{"alias": a, "titular": h["titular"]} for a, h in alias_a_historia.items()]

    grupos_nuevos = defaultdict(list)  # (lote, "N1") -> [items]
    para_reescribir = {}  # id historia -> historia
    sumados = 0
    descartados = 0

    try:
        for n_lote in range(0, len(nuevos), TAMANO_LOTE_CLASIFICAR):
            lote = nuevos[n_lote:n_lote + TAMANO_LOTE_CLASIFICAR]
            alias_item = {f"t{i + 1}": it for i, it in enumerate(lote)}
            entrada = [{"id": a, "medio": it["medio"], "titulo": it["titulo"], "resumen": it["resumen"]}
                       for a, it in alias_item.items()]
            try:
                resultado = ia.clasificar(entrada, lista_recientes, fecha_txt)
            except (anthropic.APIStatusError, anthropic.APIConnectionError, ValueError) as e:
                log(f"Error clasificando un lote ({type(e).__name__}: {e}). Se reintenta en la próxima ejecución.")
                continue
            for r in resultado:
                it = alias_item.get(r["id"])
                if not it:
                    continue
                relevancia = max(0, min(5, int(r["relevancia"])))
                it["relevancia"] = relevancia
                grupo = (r["grupo"] or "").strip().upper()
                if relevancia < g["relevancia_minima"] or grupo == "X":
                    vistos[it["id"]] = ahora
                    descartados += 1
                elif grupo in alias_a_historia:
                    h = alias_a_historia[grupo]
                    h["fuentes"] = ordenar_fuentes(h["fuentes"] + [fuente_para_web(it)])
                    h["relevancia"] = max(h.get("relevancia", 0), relevancia)
                    vistos[it["id"]] = ahora
                    sumados += 1
                    if r["aporta_novedad"]:
                        h.setdefault("_items_nuevos", []).append(it)
                        para_reescribir[h["id"]] = h
                elif grupo.startswith("N"):
                    grupos_nuevos[(n_lote, grupo)].append(it)
                else:
                    grupos_nuevos[(n_lote, "solo-" + it["id"])].append(it)
    except SinPresupuesto:
        log("Presupuesto diario agotado durante la clasificación.")

    log(f"Descartados: {descartados} · sumados a historias existentes: {sumados} · grupos nuevos: {len(grupos_nuevos)}")

    # ---------- 4. Redactar ----------
    grupos = sorted(
        grupos_nuevos.values(),
        key=lambda its: (-max(it["relevancia"] for it in its), -max(it["publicado"] for it in its)),
    )[: g["max_historias_por_ejecucion"]]
    reescrituras = sorted(para_reescribir.values(), key=lambda h: -h.get("relevancia", 0))[:MAX_REESCRITURAS_POR_EJECUCION]
    leer_nota = g.get("leer_nota_completa", True)

    def redactar_nueva(its):
        fuentes = preparar_fuentes_para_redactar(its, leer_nota)
        return its, ia.redactar(fuentes, fecha_txt)

    def redactar_actualizacion(h):
        fuentes = preparar_fuentes_para_redactar(h["_items_nuevos"], leer_nota)
        previa = {k: h[k] for k in ("titular", "que_paso", "contexto", "por_que_importa")}
        return h, ia.redactar(fuentes, fecha_txt, version_anterior=previa)

    creadas = 0
    actualizadas = 0
    with ThreadPoolExecutor(max_workers=4) as ex:
        futuros_nuevas = [ex.submit(redactar_nueva, its) for its in grupos]
        futuros_act = [ex.submit(redactar_actualizacion, h) for h in reescrituras]

        for fut in futuros_nuevas:
            try:
                its, texto = fut.result()
            except SinPresupuesto:
                continue
            except (anthropic.APIStatusError, anthropic.APIConnectionError, ValueError, KeyError) as e:
                log(f"Error redactando ({type(e).__name__}: {e}). Se reintenta luego.")
                continue
            fuentes = ordenar_fuentes([fuente_para_web(it) for it in its])
            historia = {
                "id": hashlib.sha1("".join(sorted(it["id"] for it in its)).encode()).hexdigest()[:12],
                **texto,
                "relevancia": max(it["relevancia"] for it in its),
                "publicado": min(it["publicado"] for it in its),
                "creado": ahora,
                "actualizado": ahora,
                "fuentes": fuentes,
            }
            historias.append(historia)
            for it in its:
                vistos[it["id"]] = ahora
            creadas += 1

        for fut in futuros_act:
            try:
                h, texto = fut.result()
            except (SinPresupuesto, anthropic.APIStatusError, anthropic.APIConnectionError, ValueError, KeyError) as e:
                log(f"No se pudo actualizar una historia ({type(e).__name__}).")
                continue
            # Mantener "alto impacto" si ya lo era.
            texto["alto_impacto"] = texto["alto_impacto"] or h.get("alto_impacto", False)
            if not texto["motivo_impacto"]:
                texto["motivo_impacto"] = h.get("motivo_impacto", "")
            h.update(texto)
            h["actualizado"] = ahora
            actualizadas += 1

    for h in historias:
        h.pop("_items_nuevos", None)

    # ---------- 5. Guardar ----------
    corte = ahora - g["horas_a_mostrar"] * 3600
    historias = [h for h in historias if h["publicado"] >= corte]
    historias.sort(key=lambda h: -h["publicado"])
    if creadas or actualizadas or sumados:
        guardar_json(ARCHIVO_NOTICIAS, {"actualizado": ahora, "historias": historias})

    estado["vistos"] = {k: v for k, v in vistos.items() if v >= ahora - 4 * 86400}
    estado["gasto"]["usd"] = round(estado["gasto"]["usd"] + ia.gastado, 4)
    guardar_json(ARCHIVO_ESTADO, estado)

    resumen = [
        f"### Ejecución {fecha_txt}",
        f"- Titulares nuevos analizados: {len(nuevos)}",
        f"- Descartados por tema/relevancia: {descartados}",
        f"- Historias nuevas: {creadas} · actualizadas: {actualizadas} · fuentes sumadas: {sumados}",
        f"- Gasto de esta ejecución: USD {ia.gastado:.4f} · gasto de hoy: USD {estado['gasto']['usd']:.3f} "
        f"de {g['presupuesto_diario_usd']}",
    ]
    log("\n".join(resumen))
    resumen_actions(resumen)


if __name__ == "__main__":
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("Falta la variable ANTHROPIC_API_KEY (en GitHub va como secreto del repositorio).")
    main()
