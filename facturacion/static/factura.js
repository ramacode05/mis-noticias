// Pantalla "Nueva factura" (pasos como en ARCA).
// Paso 1: oculta el período facturado si se factura solo "Productos".
// Paso 2: buscador de clientes por nombre o CUIT.
// Paso 3: calcula subtotales, IVA y total mientras se escribe.
// El cálculo definitivo lo hace el servidor; esto es solo para ver los números.
(function () {
  var form = document.getElementById('form-factura');
  if (!form) return;

  // Evita generar dos facturas si se hace doble clic en "Confirmar Datos".
  form.addEventListener('submit', function (e) {
    var boton = e.submitter;
    if (!boton || boton.value !== 'confirmar') return;
    if (form.dataset.enviado) { e.preventDefault(); return; }
    form.dataset.enviado = '1';
    setTimeout(function () { boton.disabled = true; boton.textContent = 'Generando…'; }, 0);
  });

  // Enter en un campo de texto pasa al paso siguiente (como "Continuar"),
  // salvo en el buscador de clientes y en los renglones.
  form.addEventListener('keydown', function (e) {
    if (e.key !== 'Enter' || (e.target.tagName === 'TEXTAREA' && !e.target.closest('#renglones'))) return;
    if (e.target.closest('#renglones') || e.target.id === 'buscar-cliente' ||
        e.target.closest('.nuevo-cliente')) {
      e.preventDefault();
    }
  });

  // Minúsculas y sin tildes, para buscar "elastico" y encontrar "Elástico".
  var normalizar = function (t) {
    return (t || '').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
  };

  // ------------------------------------------------------------------ Paso 1
  var concepto = document.getElementById('concepto');
  if (concepto) {
    var mostrarPeriodo = function () {
      document.getElementById('fechas-servicio').style.display = concepto.value === '1' ? 'none' : '';
    };
    concepto.addEventListener('change', mostrarPeriodo);
    mostrarPeriodo();

    // Si cambia la fecha del comprobante, acompaña las fechas del período que estaban iguales.
    var fecha = document.getElementById('fecha');
    var fechaAnterior = fecha.value;
    fecha.addEventListener('change', function () {
      ['serv_desde', 'serv_hasta', 'vto_pago'].forEach(function (id) {
        var campo = document.getElementById(id);
        if (campo.value === fechaAnterior) campo.value = fecha.value;
      });
      fechaAnterior = fecha.value;
    });
  }

  // ------------------------------------------------------------------ Paso 2
  var buscador = document.getElementById('buscar-cliente');
  if (buscador) {
    var clientes = JSON.parse(document.getElementById('datos-clientes').textContent);
    var lista = document.getElementById('resultados-cliente');
    var seleccionado = -1;


    var elegir = function (c) {
      document.getElementById('cliente_id').value = c.id;
      document.getElementById('c-condicion').value = c.condicion;
      document.getElementById('c-documento').value = c.documento;
      document.getElementById('c-razon').value = c.razon_social;
      document.getElementById('c-domicilio').value = c.domicilio;
      document.getElementById('c-email').value = c.email;
      document.getElementById('c-letra').textContent = 'Factura ' + c.letra;
      document.getElementById('titulo-comprobante').textContent = 'FACTURA ' + c.letra;
      buscador.value = '';
      lista.hidden = true;
      document.getElementById('remito_numero').focus();
    };

    var marcar = function () {
      lista.querySelectorAll('li').forEach(function (li, i) {
        li.classList.toggle('activo', i === seleccionado);
      });
    };

    buscador.addEventListener('input', function () {
      var texto = normalizar(buscador.value.trim());
      var digitos = buscador.value.replace(/\D/g, '');
      lista.innerHTML = '';
      seleccionado = -1;
      if (!texto) { lista.hidden = true; return; }
      var palabras = texto.split(/\s+/);
      var encontrados = clientes.filter(function (c) {
        var nombre = normalizar(c.razon_social);
        var porNombre = palabras.every(function (p) { return nombre.indexOf(p) >= 0; });
        var porDoc = digitos.length >= 3 && c.nro_doc.indexOf(digitos) >= 0;
        return porNombre || porDoc;
      }).slice(0, 15);

      if (!encontrados.length) {
        var vacio = document.createElement('li');
        vacio.className = 'vacio';
        vacio.textContent = 'No se encontró. Podés cargarlo abajo en "Cargar cliente nuevo".';
        lista.appendChild(vacio);
      }
      encontrados.forEach(function (c) {
        var li = document.createElement('li');
        var nombre = document.createElement('strong');
        nombre.textContent = c.razon_social;
        li.appendChild(nombre);
        li.appendChild(document.createTextNode(
          ' — ' + (c.documento || 'sin documento') + ' — ' + c.condicion + ' (Factura ' + c.letra + ')'));
        li.addEventListener('mousedown', function (e) { e.preventDefault(); elegir(c); });
        li.cliente = c;
        lista.appendChild(li);
      });
      lista.hidden = false;
      if (encontrados.length === 1) { seleccionado = 0; marcar(); }
    });

    // Flechas arriba/abajo y Enter para elegir con el teclado.
    buscador.addEventListener('keydown', function (e) {
      var items = lista.querySelectorAll('li:not(.vacio)');
      if (e.key === 'ArrowDown' && items.length) {
        seleccionado = Math.min(seleccionado + 1, items.length - 1); marcar(); e.preventDefault();
      } else if (e.key === 'ArrowUp' && items.length) {
        seleccionado = Math.max(seleccionado - 1, 0); marcar(); e.preventDefault();
      } else if (e.key === 'Enter' && seleccionado >= 0 && items[seleccionado]) {
        elegir(items[seleccionado].cliente);
      } else if (e.key === 'Escape') {
        lista.hidden = true;
      }
    });
    buscador.addEventListener('blur', function () { setTimeout(function () { lista.hidden = true; }, 150); });
  }

  // ------------------------------------------------------------------ Paso 3
  var tbody = document.getElementById('renglones');
  if (tbody) {
    // Lee "30.000,50", "30000,5", "30000.50" o "30.000" (igual que importes.py).
    var leerNumero = function (texto) {
      texto = (texto || '').replace(/[\s$]/g, '');
      if (!texto) return null;
      if (texto.indexOf(',') >= 0) {
        texto = texto.replace(/\./g, '').replace(',', '.');
      } else if ((texto.match(/\./g) || []).length > 1 || /^\d{1,3}(\.\d{3})+$/.test(texto)) {
        texto = texto.replace(/\./g, '');
      }
      var n = Number(texto);
      return isFinite(n) ? n : null;
    };

    // Formato "123.456,78" (los importes se calculan en centavos enteros, como el servidor).
    var pesos = function (cent) {
      var negativo = cent < 0;
      cent = Math.abs(cent);
      var entero = Math.floor(cent / 100).toString().replace(/\B(?=(\d{3})+(?!\d))/g, '.');
      return (negativo ? '-' : '') + entero + ',' + String(cent % 100).padStart(2, '0');
    };

    var recalcular = function () {
      var neto = 0;
      tbody.querySelectorAll('tr').forEach(function (tr) {
        var campoCant = tr.querySelector('[name=cantidad]');
        var cant = campoCant.value.trim() === '' ? 1 : leerNumero(campoCant.value);
        var precio = leerNumero(tr.querySelector('[name=precio]').value);
        var celdas = [tr.querySelector('.subtotal'), tr.querySelector('.importe-iva'), tr.querySelector('.subtotal-iva')];
        if (cant === null || precio === null) {
          celdas.forEach(function (c) { c.textContent = ''; });
          return;
        }
        var sub = Math.round(Math.round(cant * 100) * Math.round(precio * 100) / 100);
        var iva = Math.round(sub * 21 / 100);
        neto += sub;
        celdas[0].textContent = pesos(sub);
        celdas[1].textContent = pesos(iva);
        celdas[2].textContent = pesos(sub + iva);
      });
      var ivaTotal = Math.round(neto * 21 / 100);
      document.getElementById('total-neto').textContent = pesos(neto);
      document.getElementById('total-iva').textContent = pesos(ivaTotal);
      document.getElementById('total-total').textContent = pesos(neto + ivaTotal);
    };

    var nuevoRenglon = function () {
      var tr = tbody.querySelector('tr').cloneNode(true);
      tr.querySelectorAll('input, textarea').forEach(function (i) { i.value = ''; });
      tr.querySelectorAll('.subtotal, .importe-iva, .subtotal-iva').forEach(function (c) { c.textContent = ''; });
      tbody.appendChild(tr);
      return tr;
    };

    // Usa la primera línea sin descripción; si no hay, agrega una.
    var renglonLibre = function () {
      var filas = tbody.querySelectorAll('tr');
      for (var i = 0; i < filas.length; i++) {
        if (!filas[i].querySelector('[name=descripcion]').value.trim()) return filas[i];
      }
      return nuevoRenglon();
    };

    tbody.addEventListener('input', recalcular);
    tbody.addEventListener('click', function (e) {
      if (!e.target.classList.contains('quitar')) return;
      var tr = e.target.closest('tr');
      if (tbody.querySelectorAll('tr').length > 1) tr.remove();
      else tr.querySelectorAll('input, textarea').forEach(function (i) { i.value = ''; });
      recalcular();
    });

    document.getElementById('agregar-renglon').addEventListener('click', function () {
      nuevoRenglon().querySelector('[name=descripcion]').focus();
    });

    var selConcepto = document.getElementById('agregar-concepto');
    if (selConcepto) {
      selConcepto.addEventListener('change', function () {
        if (!this.value) return;
        var tr = renglonLibre();
        tr.querySelector('[name=descripcion]').value = this.value;
        this.value = '';
        tr.querySelector('[name=precio]').focus();
      });
    }

    // --- Autocompletar conceptos fijos mientras se escribe en la descripción ---
    // Escribiendo "tras izq" sugiere "Desarme y Reparación en Elásticos Traseros Izquierdo".
    var conceptos = JSON.parse((document.getElementById('datos-conceptos') || {}).textContent || '[]');
    var sugerencias = document.createElement('ul');
    sugerencias.className = 'resultados sugerencias';
    sugerencias.hidden = true;
    var campoActivo = null;
    var elegida = -1;

    var cerrarSugerencias = function () { sugerencias.hidden = true; elegida = -1; };

    var marcarSugerencia = function () {
      sugerencias.querySelectorAll('li').forEach(function (li, i) {
        li.classList.toggle('activo', i === elegida);
      });
    };

    var usarSugerencia = function (texto) {
      campoActivo.value = texto;
      cerrarSugerencias();
      campoActivo.closest('tr').querySelector('[name=cantidad]').focus();
      recalcular();
    };

    var mostrarSugerencias = function (campo) {
      var escrito = normalizar(campo.value).trim();
      var palabras = escrito.split(/\s+/).filter(Boolean);
      sugerencias.innerHTML = '';
      elegida = -1;
      if (!conceptos.length || escrito.length < 2) { cerrarSugerencias(); return; }
      var encontrados = conceptos.filter(function (c) {
        var texto = normalizar(c);
        return texto !== escrito && palabras.every(function (p) { return texto.indexOf(p) >= 0; });
      }).slice(0, 10);
      if (!encontrados.length) { cerrarSugerencias(); return; }
      encontrados.forEach(function (c) {
        var li = document.createElement('li');
        li.textContent = c;
        li.addEventListener('mousedown', function (e) { e.preventDefault(); usarSugerencia(c); });
        sugerencias.appendChild(li);
      });
      campo.closest('td').appendChild(sugerencias);
      campoActivo = campo;
      sugerencias.hidden = false;
      if (encontrados.length === 1) { elegida = 0; marcarSugerencia(); }
    };

    tbody.addEventListener('input', function (e) {
      if (e.target.name === 'descripcion') mostrarSugerencias(e.target);
    });
    tbody.addEventListener('keydown', function (e) {
      if (e.target.name !== 'descripcion' || sugerencias.hidden) return;
      var items = sugerencias.querySelectorAll('li');
      if (e.key === 'ArrowDown') {
        elegida = Math.min(elegida + 1, items.length - 1); marcarSugerencia(); e.preventDefault();
      } else if (e.key === 'ArrowUp') {
        elegida = Math.max(elegida - 1, 0); marcarSugerencia(); e.preventDefault();
      } else if ((e.key === 'Enter' || e.key === 'Tab') && elegida >= 0) {
        e.preventDefault(); usarSugerencia(items[elegida].textContent);
      } else if (e.key === 'Escape') {
        cerrarSugerencias();
      }
    });
    tbody.addEventListener('focusout', function (e) {
      if (e.target.name === 'descripcion') setTimeout(cerrarSugerencias, 150);
    });

    recalcular();
    var primera = tbody.querySelector('[name=descripcion]');
    if (primera && !primera.value) primera.focus();
  }
})();
