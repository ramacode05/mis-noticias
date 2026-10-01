(function () {
  "use strict";

  var TEMAS = [
    { id: "todas", nombre: "Todas" },
    { id: "impacto", nombre: "Alto impacto" },
    { id: "argentina", nombre: "Argentina" },
    { id: "economia", nombre: "Economía" },
    { id: "mercados", nombre: "Mercados" },
    { id: "cripto", nombre: "Cripto" },
    { id: "tecnologia", nombre: "Tecnología e IA" },
    { id: "geopolitica", nombre: "Geopolítica" }
  ];
  var NOMBRE_TEMA = {};
  TEMAS.forEach(function (t) { NOMBRE_TEMA[t.id] = t.nombre; });

  var RECARGA_MS = 5 * 60 * 1000;

  var estado = {
    historias: [],
    actualizado: null,
    filtro: leer("filtro") || "todas",
    ultimaVisita: Number(leer("ultimaVisita")) || 0
  };

  var $lista = document.getElementById("lista");
  var $filtros = document.getElementById("filtros");
  var $actualizado = document.getElementById("actualizado");
  var $btnRecargar = document.getElementById("btn-recargar");
  var $btnTema = document.getElementById("btn-tema");

  // ---------- localStorage seguro ----------
  function leer(clave) {
    try { return localStorage.getItem(clave); } catch (e) { return null; }
  }
  function guardar(clave, valor) {
    try { localStorage.setItem(clave, valor); } catch (e) { /* sin almacenamiento */ }
  }

  // ---------- utilidades ----------
  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function parrafos(texto) {
    return String(texto || "")
      .split(/\n\s*\n/)
      .map(function (p) { return p.trim(); })
      .filter(Boolean)
      .map(function (p) { return "<p>" + esc(p).replace(/\n/g, "<br>") + "</p>"; })
      .join("");
  }

  function hora(ts) {
    return new Date(ts * 1000).toLocaleTimeString("es-AR", { hour: "2-digit", minute: "2-digit", hour12: false });
  }

  function hace(ts) {
    var s = Math.max(0, Date.now() / 1000 - ts);
    if (s < 60) return "recién";
    if (s < 3600) return "hace " + Math.floor(s / 60) + " min";
    if (s < 86400) return "hace " + Math.floor(s / 3600) + " h";
    var d = Math.floor(s / 86400);
    return "hace " + d + (d === 1 ? " día" : " días");
  }

  function etiquetaDia(ts) {
    var d = new Date(ts * 1000);
    var hoy = new Date();
    var ayer = new Date(); ayer.setDate(hoy.getDate() - 1);
    if (d.toDateString() === hoy.toDateString()) return "Hoy";
    if (d.toDateString() === ayer.toDateString()) return "Ayer";
    var txt = d.toLocaleDateString("es-AR", { weekday: "long", day: "numeric", month: "long" });
    return txt.charAt(0).toUpperCase() + txt.slice(1);
  }

  // ---------- filtros ----------
  function pasaFiltro(h, filtro) {
    if (filtro === "todas") return true;
    if (filtro === "impacto") return !!h.alto_impacto;
    return (h.temas || []).indexOf(filtro) !== -1;
  }

  function pintarFiltros() {
    $filtros.innerHTML = TEMAS.map(function (t) {
      var n = estado.historias.filter(function (h) { return pasaFiltro(h, t.id); }).length;
      var clase = "chip" + (t.id === "impacto" ? " chip-impacto" : "");
      var cuenta = t.id === "todas" ? "" : '<span class="cuenta">' + n + "</span>";
      return '<button type="button" class="' + clase + '" data-filtro="' + t.id + '" aria-pressed="' +
        (estado.filtro === t.id) + '">' + (t.id === "impacto" ? "● " : "") + esc(t.nombre) + cuenta + "</button>";
    }).join("");
  }

  $filtros.addEventListener("click", function (ev) {
    var b = ev.target.closest("[data-filtro]");
    if (!b) return;
    estado.filtro = b.getAttribute("data-filtro");
    guardar("filtro", estado.filtro);
    pintarFiltros();
    pintarLista();
    window.scrollTo({ top: 0 });
  });

  // ---------- tarjetas ----------
  function tarjeta(h) {
    var fuentes = h.fuentes || [];
    var principal = fuentes.filter(function (f) { return !f.muro; })[0] || fuentes[0];
    var medios = [];
    fuentes.forEach(function (f) { if (medios.indexOf(f.medio) === -1) medios.push(f.medio); });

    var esNueva = estado.ultimaVisita && h.creado > estado.ultimaVisita;
    var fueActualizada = h.actualizado && h.creado && h.actualizado - h.creado > 120;

    var html = '<article class="noticia' + (h.alto_impacto ? " impacto" : "") + '">';
    if (h.alto_impacto) {
      html += '<div class="etiqueta-impacto">▲ ALTO IMPACTO</div>';
    }
    html += "<h2>" + esc(h.titular) + "</h2>";
    html += '<div class="meta">' +
      (esNueva ? '<span class="nueva">● Nueva</span>' : "") +
      "<span>" + hora(h.publicado) + " · " + hace(h.publicado) + "</span>" +
      "<span>·</span><span>" + esc(medios.join(", ")) + "</span>" +
      (fueActualizada ? '<span class="actualizada">· actualizada ' + hace(h.actualizado) + "</span>" : "") +
      "</div>";
    if (h.alto_impacto && h.motivo_impacto) {
      html += '<div class="motivo-impacto">' + esc(h.motivo_impacto) + "</div>";
    }
    html += '<div class="cuerpo">' + parrafos(h.que_paso) + "</div>";
    if (h.por_que_importa) {
      html += '<div class="importa"><h3>Por qué importa</h3>' + parrafos(h.por_que_importa) + "</div>";
    }
    if (h.contexto) {
      html += '<details class="contexto"><summary>Contexto</summary>' + parrafos(h.contexto) + "</details>";
    }
    html += '<div class="temas">' + (h.temas || []).map(function (t) {
      return '<span class="tema">' + esc(NOMBRE_TEMA[t] || t) + "</span>";
    }).join("") + "</div>";

    html += '<div class="enlaces">';
    if (principal) {
      html += '<a class="btn-leer" href="' + esc(principal.url) + '" target="_blank" rel="noopener">Leer en ' +
        esc(principal.medio) + (principal.muro ? " 🔒" : "") + "</a>";
    }
    fuentes.forEach(function (f) {
      if (f === principal) return;
      html += '<a class="fuente" href="' + esc(f.url) + '" target="_blank" rel="noopener" title="' +
        esc(f.titulo) + '">' + esc(f.medio) + (f.muro ? " 🔒" : "") + "</a>";
    });
    html += "</div></article>";
    return html;
  }

  function pintarLista() {
    var visibles = estado.historias.filter(function (h) { return pasaFiltro(h, estado.filtro); });
    if (!visibles.length) {
      $lista.innerHTML = '<p class="vacio">' + (estado.historias.length
        ? "No hay noticias con este filtro todavía."
        : "Todavía no hay noticias. El robot se ejecuta cada 15 minutos.") + "</p>";
      return;
    }
    var html = "";
    var diaActual = "";
    visibles.forEach(function (h) {
      var dia = etiquetaDia(h.publicado);
      if (dia !== diaActual) {
        html += '<h2 class="dia">' + esc(dia) + "</h2>";
        diaActual = dia;
      }
      html += tarjeta(h);
    });
    $lista.innerHTML = html;
  }

  function pintarActualizado() {
    $actualizado.textContent = estado.actualizado
      ? "Actualizado " + hace(estado.actualizado) + " (" + hora(estado.actualizado) + ")"
      : "Sin datos todavía";
  }

  // ---------- carga de datos ----------
  function cargar() {
    $btnRecargar.classList.add("girando");
    return fetch("data/noticias.json?t=" + Date.now(), { cache: "no-store" })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (datos) {
        var historias = (datos.historias || []).slice();
        historias.sort(function (a, b) { return b.publicado - a.publicado; });
        estado.historias = historias;
        estado.actualizado = datos.actualizado;
        pintarFiltros();
        pintarLista();
        pintarActualizado();
      })
      .catch(function () {
        $actualizado.textContent = "Sin conexión: mostrando lo último guardado";
      })
      .then(function () { $btnRecargar.classList.remove("girando"); });
  }

  function cargarFuentes() {
    fetch("data/fuentes.json?t=" + Date.now(), { cache: "no-store" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        var cont = document.getElementById("tabla-fuentes");
        if (!d || !d.feeds) { cont.textContent = "Todavía no hay datos."; return; }
        cont.innerHTML = '<table class="tabla-fuentes">' + d.feeds.map(function (f) {
          var icono = !f.ok ? "❌" : (f.alternativa ? "⚠️" : "✅");
          return "<tr><td>" + icono + "</td><td>" + esc(f.medio) + "</td><td>" +
            esc(f.url_usada || f.url_configurada) + "</td></tr>";
        }).join("") + "</table>";
      })
      .catch(function () {});
  }

  // ---------- tema claro/oscuro ----------
  function aplicarTema(t) {
    if (t === "light" || t === "dark") document.documentElement.dataset.theme = t;
    else delete document.documentElement.dataset.theme;
    var nombres = { auto: "automático", light: "claro", dark: "oscuro" };
    $btnTema.title = "Tema: " + nombres[t || "auto"];
    $btnTema.setAttribute("aria-label", "Tema: " + nombres[t || "auto"] + ". Tocar para cambiar.");
  }
  $btnTema.addEventListener("click", function () {
    var orden = ["auto", "dark", "light"];
    var actual = leer("tema") || "auto";
    var sig = orden[(orden.indexOf(actual) + 1) % orden.length];
    guardar("tema", sig);
    aplicarTema(sig);
  });
  aplicarTema(leer("tema") || "auto");

  // ---------- eventos ----------
  $btnRecargar.addEventListener("click", cargar);

  function marcarVisita() { guardar("ultimaVisita", String(Math.floor(Date.now() / 1000))); }

  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible") {
      cargar();
    } else {
      marcarVisita();
    }
  });
  window.addEventListener("pagehide", marcarVisita);

  setInterval(function () {
    if (document.visibilityState === "visible") cargar();
    else pintarActualizado();
  }, RECARGA_MS);
  setInterval(pintarActualizado, 60 * 1000);

  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("sw.js").catch(function () {});
  }

  pintarFiltros();
  cargar();
  cargarFuentes();
})();
