// Pantalla "Nueva factura": calcula subtotales y totales mientras se escribe.
// El cálculo definitivo lo hace el servidor al guardar; esto es solo para ver los números.
(function () {
  var tbody = document.getElementById('renglones');
  var selCliente = document.getElementById('cliente');
  var selConcepto = document.getElementById('concepto');

  // Lee "30.000,50", "30000,5", "30000.50" o "30.000" (igual que importes.py).
  function leerNumero(texto) {
    texto = (texto || '').replace(/[\s$]/g, '');
    if (!texto) return null;
    if (texto.indexOf(',') >= 0) {
      texto = texto.replace(/\./g, '').replace(',', '.');
    } else if ((texto.match(/\./g) || []).length > 1 || /^\d{1,3}(\.\d{3})+$/.test(texto)) {
      texto = texto.replace(/\./g, '');
    }
    var n = Number(texto);
    return isFinite(n) ? n : null;
  }

  // Trabaja en centavos enteros para que coincida con el servidor.
  function centavos(n) { return Math.round(n * 100); }

  function pesos(cent) {
    var negativo = cent < 0;
    cent = Math.abs(cent);
    var entero = Math.floor(cent / 100).toString().replace(/\B(?=(\d{3})+(?!\d))/g, '.');
    var dec = String(cent % 100).padStart(2, '0');
    return '$ ' + (negativo ? '-' : '') + entero + ',' + dec;
  }

  function recalcular() {
    var neto = 0;
    tbody.querySelectorAll('tr').forEach(function (tr) {
      var cant = leerNumero(tr.querySelector('[name=cantidad]').value);
      var precio = leerNumero(tr.querySelector('[name=precio]').value);
      if (tr.querySelector('[name=cantidad]').value.trim() === '') cant = 1;
      var celda = tr.querySelector('.subtotal');
      if (cant === null || precio === null) { celda.textContent = ''; return; }
      var sub = Math.round(centavos(cant) * centavos(precio) / 100);
      neto += sub;
      celda.textContent = pesos(sub);
    });
    var iva = Math.round(neto * 21 / 100);
    document.getElementById('total-neto').textContent = pesos(neto);
    document.getElementById('total-iva').textContent = pesos(iva);
    document.getElementById('total-total').textContent = pesos(neto + iva);
  }

  function nuevoRenglon(descripcion) {
    var modelo = tbody.querySelector('tr');
    var tr = modelo.cloneNode(true);
    tr.querySelectorAll('input').forEach(function (i) { i.value = ''; i.placeholder = i.name === 'cantidad' ? '1' : i.name === 'precio' ? '0,00' : ''; });
    tr.querySelector('.subtotal').textContent = '';
    if (descripcion) tr.querySelector('[name=descripcion]').value = descripcion;
    tbody.appendChild(tr);
    return tr;
  }

  // Usa el primer renglón vacío; si no hay, agrega uno.
  function renglonLibre() {
    var filas = tbody.querySelectorAll('tr');
    for (var i = 0; i < filas.length; i++) {
      if (!filas[i].querySelector('[name=descripcion]').value.trim()) return filas[i];
    }
    return nuevoRenglon();
  }

  tbody.addEventListener('input', recalcular);
  tbody.addEventListener('click', function (e) {
    if (!e.target.classList.contains('quitar')) return;
    var tr = e.target.closest('tr');
    if (tbody.querySelectorAll('tr').length > 1) tr.remove();
    else tr.querySelectorAll('input').forEach(function (i) { i.value = ''; });
    recalcular();
  });

  document.getElementById('agregar-renglon').addEventListener('click', function () {
    nuevoRenglon().querySelector('[name=descripcion]').focus();
  });

  document.getElementById('agregar-concepto').addEventListener('change', function () {
    if (!this.value) return;
    var tr = renglonLibre();
    tr.querySelector('[name=descripcion]').value = this.value;
    this.value = '';
    tr.querySelector('[name=precio]').focus();
  });

  function mostrarLetra() {
    var opcion = selCliente.options[selCliente.selectedIndex];
    var letra = opcion && opcion.dataset.letra;
    document.getElementById('titulo-letra').textContent = letra ? letra : '';
    document.getElementById('aviso-letra').textContent = letra
      ? 'A este cliente le corresponde Factura ' + letra + '.'
      : 'Elegí un cliente para ver qué factura le corresponde.';
  }
  selCliente.addEventListener('change', mostrarLetra);

  // Las fechas del servicio solo se piden si se facturan servicios.
  function mostrarFechasServicio() {
    document.getElementById('fechas-servicio').style.display = selConcepto.value === '1' ? 'none' : '';
  }
  selConcepto.addEventListener('change', mostrarFechasServicio);

  // Si cambia la fecha de la factura, acompaña las fechas del servicio que estaban iguales.
  var fecha = document.getElementById('fecha');
  var fechaAnterior = fecha.value;
  fecha.addEventListener('change', function () {
    ['serv_desde', 'serv_hasta', 'vto_pago'].forEach(function (n) {
      var campo = document.querySelector('[name=' + n + ']');
      if (campo.value === fechaAnterior) campo.value = fecha.value;
    });
    fechaAnterior = fecha.value;
  });

  // Enter en un renglón no envía el formulario por accidente.
  tbody.addEventListener('keydown', function (e) {
    if (e.key === 'Enter') e.preventDefault();
  });

  mostrarLetra();
  mostrarFechasServicio();
  recalcular();
})();
