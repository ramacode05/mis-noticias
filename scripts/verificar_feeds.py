"""Verifica que cada RSS de config.toml funcione y muestra una tabla.

En GitHub: pestaña Actions -> "Verificar fuentes RSS" -> Run workflow.
No usa la API de Claude (no gasta nada).
"""

import os
import time

from fuentes import cargar_config, leer_todas


def main():
    items, estados, ahora = leer_todas(cargar_config())
    por_medio = {}
    for it in items:
        por_medio.setdefault(it["medio"], []).append(it)

    filas = [
        "## Estado de las fuentes RSS",
        "",
        "| Estado | Medio | Titulares | Más reciente | Feed usado |",
        "|---|---|---|---|---|",
    ]
    for e in estados:
        if not e["ok"]:
            icono = "❌ no funciona"
        elif e["alternativa"]:
            icono = "⚠️ alternativa"
        else:
            icono = "✅ ok"
        recientes = [it["publicado"] for it in por_medio.get(e["medio"], []) if it["publicado"]]
        hace = f"hace {(ahora - max(recientes)) / 3600:.1f} h" if recientes else "-"
        filas.append(f"| {icono} | {e['medio']} | {e['items']} | {hace} | {e['url_usada'] or e['url_configurada']} |")

    malos = [e for e in estados if not e["ok"] or e["alternativa"]]
    if malos:
        filas += ["", "### Detalle de errores", ""]
        for e in malos:
            for err in e["errores"]:
                filas.append(f"- **{e['medio']}**: `{err}`")

    texto = "\n".join(filas)
    print(texto)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(texto + "\n")
    print(f"\nTotal: {len(items)} titulares · {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}")


if __name__ == "__main__":
    main()
