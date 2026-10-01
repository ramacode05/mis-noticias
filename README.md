# Mis Noticias 📰

Web personal de noticias (instalable en el celular) que cada 15 minutos lee
los RSS de medios confiables, descarta lo que no te interesa, agrupa la misma
noticia publicada por varios medios y la explica en español con
**qué pasó**, **contexto** y **por qué importa**. Las noticias que pueden mover
los mercados se marcan como **ALTO IMPACTO**.

- Web: `https://ramacode05.github.io/mis-noticias/` (funciona después del Paso 5)
- Robot: GitHub Actions + API de Claude (modelo Haiku 4.5, el más económico)
- Costo de GitHub: gratis. Costo de Claude: ver [¿Cuánto cuesta?](#cuánto-cuesta)

---

## Cómo funciona (en criollo)

```
 Cada 15 min (GitHub Actions)
 ┌───────────────┐   ┌───────────────────────┐   ┌──────────────────────┐
 │ Lee 32 RSS    │──▶│ Claude: ¿es de mis    │──▶│ Claude: titular +    │
 │ de 17 medios  │   │ temas? ¿qué titulares │   │ qué pasó / contexto /│
 └───────────────┘   │ son la misma noticia? │   │ por qué importa +    │
                     └───────────────────────┘   │ ¿alto impacto?       │
                                                 └──────────┬───────────┘
                                                            ▼
                        docs/data/noticias.json  ──▶  GitHub Pages (tu web)
```

| Archivo | Para qué sirve |
|---|---|
| `config.toml` | **Lo que vas a querer tocar**: fuentes RSS, presupuesto diario, relevancia mínima, etc. |
| `scripts/actualizar.py` | El proceso principal (leer → filtrar → agrupar → redactar → guardar). |
| `scripts/ia.py` | Las instrucciones (prompts) que recibe Claude. |
| `scripts/fuentes.py` | Lectura de RSS, con alternativas automáticas si un feed falla. |
| `scripts/verificar_feeds.py` | Revisa que cada RSS funcione (no gasta nada). |
| `docs/` | La web (HTML, CSS, JS, PWA). |
| `.github/workflows/` | Los "robots" de GitHub Actions. |

---

## Puesta en marcha paso a paso

Vas a necesitar unos 20–30 minutos. Todo se hace desde el navegador,
no hace falta instalar nada en tu compu.

### Paso 1 · Crear la cuenta de Anthropic y la clave de API

1. Entrá a **https://console.anthropic.com** y creá una cuenta
   (podés usar tu mail de Google).
2. Cargá crédito: menú **Settings → Billing** → **Buy credits**.
   Con **USD 5** alcanza para probar varios días. Te pide una tarjeta.
3. **Poné un límite de gasto** (muy recomendado): **Settings → Limits** →
   *Spend limit*. Por ejemplo USD 30 por mes. Así nunca te llevás una sorpresa.
4. Creá la clave: **Settings → API Keys** → **Create Key**.
   Ponele de nombre `mis-noticias` y tocá *Add*.
5. **Copiá la clave** (empieza con `sk-ant-...`). Se muestra **una sola vez**;
   guardala un minuto en un lugar seguro (por ejemplo, un borrador de notas)
   porque la vas a pegar en el Paso 3.

> ⚠️ La clave es como una contraseña: quien la tenga puede gastar tu crédito.
> Nunca la pegues en ningún archivo del repositorio. Solo va como "secreto" de
> GitHub (Paso 3). Si alguna vez la expusiste, borrala en la consola y creá otra.

### Paso 2 · Pasar el código a la rama principal (`main`)

El código está en la rama `claude/news-pwa-personal-qe2hqr`. GitHub solo
ejecuta los robots programados desde la rama principal, así que hay que
"mergearlo":

1. Entrá a **https://github.com/ramacode05/mis-noticias**.
2. Si aparece un cartel amarillo que dice *"claude/news-pwa-personal-qe2hqr had
   recent pushes"*, tocá **Compare & pull request**.
   Si no aparece: pestaña **Pull requests** → **New pull request** →
   en *compare* elegí `claude/news-pwa-personal-qe2hqr` → **Create pull request**.
3. Tocá **Create pull request** y después **Merge pull request** →
   **Confirm merge**.

(Si preferís, pedímelo y abro yo el pull request; vos solo tenés que tocar *Merge*.)

### Paso 3 · Guardar la clave como secreto de GitHub

1. En el repositorio: **Settings** (pestaña con el engranaje, arriba a la derecha).
2. Menú izquierdo: **Secrets and variables → Actions**.
3. Botón verde **New repository secret**.
4. *Name*: `ANTHROPIC_API_KEY` (exactamente así, en mayúsculas).
5. *Secret*: pegá la clave `sk-ant-...`.
6. **Add secret**. Listo: ya podés borrar la clave de tu borrador de notas.

### Paso 4 · Darle permiso al robot para guardar las noticias

1. **Settings → Actions → General**.
2. Bajá hasta **Workflow permissions** → elegí
   **Read and write permissions** → **Save**.
3. Andá a la pestaña **Actions**. Si aparece un botón tipo
   *"I understand my workflows, go ahead and enable them"*, tocalo.

### Paso 5 · Activar GitHub Pages (la web)

1. **Settings → Pages**.
2. En **Build and deployment → Source** elegí **Deploy from a branch**.
3. En **Branch** elegí `main` y al lado la carpeta **`/docs`** → **Save**.
4. Esperá 1–2 minutos y recargá: arriba va a decir
   *"Your site is live at https://ramacode05.github.io/mis-noticias/"*.

> GitHub Pages gratis requiere que el repositorio sea **público**. Las noticias
> generadas quedan visibles para quien tenga el link; la clave de API **no**,
> porque es un secreto.

### Paso 6 · Verificar las fuentes RSS (gratis)

1. Pestaña **Actions** → en la izquierda **Verificar fuentes RSS** →
   botón **Run workflow** → **Run workflow**.
2. Esperá ~1 minuto, entrá a la ejecución (el renglón con ✅) y vas a ver una
   tabla con el estado de cada medio:
   - ✅ **ok**: el RSS original funciona.
   - ⚠️ **alternativa**: el original falló y se está usando la alternativa
     (otra URL del mismo medio o Google News filtrado por ese medio).
   - ❌ **no funciona**: ni el original ni las alternativas. Avisame y lo cambiamos.

### Paso 7 · Primera ejecución

1. **Actions** → **Actualizar noticias** → **Run workflow**.
2. Tarda 2–5 minutos. Al terminar, en la ejecución vas a ver un resumen:
   cuántos titulares analizó, cuántos descartó, cuántas historias escribió y
   cuánto gastó.
3. Abrí tu web. A partir de ahora se actualiza sola cada ~15 minutos.

### Paso 8 · Instalar la app en el celular

- **Android (Chrome)**: abrí la web → menú **⋮** → **Instalar app**
  (o *Agregar a la pantalla principal*).
- **iPhone (Safari)**: abrí la web → botón **Compartir** (cuadrado con flecha) →
  **Agregar a inicio**.

Queda como una app más, con ícono propio y pantalla completa.

---

## La web

- Noticias de **más nueva a más vieja**, separadas por día.
- **Filtros** arriba: Todas · Alto impacto · Argentina · Economía · Mercados ·
  Cripto · Tecnología e IA · Geopolítica (con la cantidad de cada uno).
- Las de **ALTO IMPACTO** tienen borde rojo, etiqueta y una línea que dice
  qué mercados podrían moverse.
- Cada noticia: titular, hora, medios, **qué pasó**, **por qué importa** y
  **contexto** (desplegable).
- Botón **"Leer en …"**: lleva a la nota original priorizando un medio
  **sin muro de pago**. Los medios con muro se marcan con 🔒.
- Marca **● Nueva** en lo que apareció desde tu última visita.
- **Modo oscuro**: automático según tu celular; con el botón 🌙 alternás
  automático → oscuro → claro.
- Se actualiza sola cada 5 minutos mientras la tenés abierta, y al volver a la app.
- Abajo de todo: **Estado de las fuentes** (qué RSS funcionan).

---

## Fuentes RSS

| Medio | Feed | Nota |
|---|---|---|
| Reuters | Google News filtrado por reuters.com | Reuters cerró sus RSS públicos en 2020. Es la alternativa más fiel: los links abren la nota de Reuters. |
| AP | Google News filtrado por apnews.com | AP no publica RSS oficiales. Misma solución. |
| Bloomberg | feeds.bloomberg.com (markets, economics, technology, politics) | 🔒 muro de pago |
| Financial Times | ft.com (markets, global-economy, world) | 🔒 muro de pago |
| CNBC | search.cnbc.com (top news, finanzas, economía) | |
| BBC | feeds.bbci.co.uk (business, world, technology) | |
| The Guardian | theguardian.com (business, world, technology) | |
| Al Jazeera | aljazeera.com/xml/rss/all.xml | |
| DW | rss.dw.com (business, world) | |
| Ars Technica | feeds.arstechnica.com | |
| The Verge | theverge.com/rss | |
| TechCrunch | techcrunch.com/feed | |
| MIT Technology Review | technologyreview.com/feed | 🔒 muro parcial |
| Ámbito | ambito.com (economía, finanzas) | |
| El Cronista | cronista.com (economía-política, finanzas-mercados) | |
| Infobae | infobae.com (economía) | |
| La Nación | lanacion.com.ar (economía) | 🔒 muro parcial |

**Red de seguridad automática:** cada fuente tiene alternativas. Si el RSS
original deja de andar, el robot prueba la siguiente URL de la lista y, como
último recurso, Google News filtrado por el dominio del medio. Así una fuente
caída no deja un hueco.

Para **agregar o quitar** un medio: editá `config.toml` desde GitHub (abrí el
archivo → lápiz ✏️ → copiá un bloque `[[fuente]]` → *Commit changes*).

---

## ¿Cuánto cuesta?

- **GitHub Actions y GitHub Pages**: gratis para repositorios públicos.
- **API de Claude (Haiku 4.5)**: USD 1 por millón de tokens de entrada y
  USD 5 por millón de salida. Estimación para este uso: **entre USD 0,50 y
  USD 1,50 por día** según cuántas noticias haya (más en días agitados),
  o sea aprox. **USD 15–45 por mes**.

Cómo controlarlo (en `config.toml`):

| Opción | Efecto |
|---|---|
| `presupuesto_diario_usd = 1.50` | Tope duro: si se alcanza, el robot pausa hasta el día siguiente (00:00 UTC = 21:00 Argentina). |
| `relevancia_minima = 3` | Subilo a **4** para quedarte solo con lo importante: menos noticias y menos gasto. |
| `leer_nota_completa = true` | Ponelo en `false` para gastar ~40% menos (explicaciones algo más pobres). |
| `max_historias_por_ejecucion = 30` | Máximo de noticias nuevas cada 15 min. |

En cada ejecución (Actions → la ejecución → *Summary*) ves el gasto del día.
Y el límite mensual que pusiste en la consola de Anthropic es la última barrera.

---

## Problemas frecuentes

| Síntoma | Solución |
|---|---|
| La ejecución falla con *"Falta la variable ANTHROPIC_API_KEY"* | Revisá el Paso 3: el nombre del secreto tiene que ser exactamente `ANTHROPIC_API_KEY`. |
| Falla con `AuthenticationError` o `401` | La clave está mal copiada o fue borrada. Creá otra y reemplazá el secreto. |
| Falla con `credit balance is too low` | Cargá crédito en console.anthropic.com → Billing. |
| Falla en "Guardar resultados" con `403` | Revisá el Paso 4 (permisos de lectura y escritura). |
| La web dice 404 | Revisá el Paso 5 (rama `main`, carpeta `/docs`) y esperá unos minutos. |
| No corre cada 15 minutos exactos | Normal: GitHub demora a veces las tareas programadas 5–15 min en horas pico. |
| El robot dejó de correr solo | GitHub pausa los robots programados tras 60 días sin actividad en el repo; como el robot guarda noticias, eso no debería pasar. Si pasa: Actions → *Enable workflow*. |
| No veo la versión nueva de la web en el celular | Cerrá la app del todo y abrila de nuevo. |

---

## Segunda etapa: notificaciones push (propuesta)

**La opción más simple y gratuita: [ntfy](https://ntfy.sh).**

- Instalás la app **ntfy** (Android o iPhone), gratis, **sin crear cuenta**.
- Te suscribís a un "tema" con un nombre secreto difícil de adivinar
  (por ejemplo `noticias-ramiro-x7k29q`).
- Cuando el robot detecta una noticia de ALTO IMPACTO, le manda un aviso a ese
  tema con una línea de código; te llega al celular con el titular y, al
  tocarla, abre la noticia.
- Del lado del proyecto solo hay que guardar el nombre del tema como otro
  secreto de GitHub.

Alternativas: **Telegram** (crear un bot con @BotFather; también gratis, un
poco más de pasos) o **Web Push nativo de la PWA** (sin apps extra, pero
bastante más complejo y en iPhone solo funciona con la app instalada en la
pantalla de inicio). Recomiendo ntfy para empezar.
