# Sistema de facturación y cuentas corrientes

## Contexto del negocio

- Empresa argentina **Responsable Inscripta**.
- Emite **Factura A** a clientes Responsables Inscriptos y **Factura B** a Consumidor Final, Monotributo y Exento.
  La letra se decide automáticamente por la **condición frente al IVA** del cliente.
- **IVA 21% siempre.** Solo **pesos** (sin moneda extranjera).
- Volumen: 25 a 40 facturas por mes.
- El detalle de cada factura es **texto libre**, más algunos **conceptos fijos** guardados como plantillas.
- Los cobros son **siempre por el total** de la factura (no hay pagos parciales).
- Lo usan **2 personas en una PC con Windows**, desde el navegador (app web local).

## Usuario

- **No sabe programar.** Explicar todo en castellano simple.
- **Pedir confirmación antes de instalar cualquier cosa.**
- Al terminar cada parte, explicar **cómo probarla** paso a paso.
- Todo el texto visible en la app y los mensajes van en castellano (Argentina).

## Tecnología

- Python 3 + Flask + SQLite (módulo `sqlite3` de Python, sin ORM).
- App web local: corre en la PC y se abre en `http://127.0.0.1:5000`.
- Git para versionar.
- Dependencias mínimas: agregar una librería solo si hace falta y con el OK del usuario.

## Estructura del proyecto

```
facturacion/            Código de la aplicación
  __init__.py           Crea la app Flask
  db.py                 Conexión y creación de la base de datos
  esquema.sql           Tablas de la base
  validaciones.py       Validaciones (CUIT, DNI, etc.)
  clientes.py           Pantallas de clientes
  conceptos.py          Pantallas de conceptos fijos (plantillas de detalle)
  facturas.py           Facturas A/B: alta, lista, ver, eliminar (solo de prueba)
  configuracion.py      Configuración general (punto de venta)
  importes.py           Lectura de números en formato argentino, cálculos y formato $
  templates/            Páginas HTML
  static/               Estilos (CSS) y factura.js (cálculo en vivo en la pantalla)
instance/               Base de datos real (NO se sube a Git)
tests/                  Pruebas automáticas
iniciar.py              Arranca el sistema
instalar.bat            Instalación en Windows (una sola vez)
iniciar.bat             Abre el sistema en Windows
```

## Cómo factura la empresa (para ARCA)

- Concepto habitual: **Productos y Servicios** (código 3): pide período del servicio y vencimiento del pago.
- Renglones con **cantidad y precio unitario sin IVA**.
- Condición de venta habitual: **Cuenta Corriente** (se puede cambiar en cada factura).
- La patente va como texto en el primer renglón: "Int. AB123CD" (renglón con precio 0 permitido).
- Códigos ARCA: Factura A = 1, Factura B = 6 (NC A = 3, NC B = 8).
- Fecha de emisión: ±5 días (productos) o ±10 días (servicios) de hoy, y no anterior a la última del mismo tipo.
- La factura copia los datos del cliente al emitirse (editar el cliente no cambia facturas viejas).

## Convenciones

- Montos: guardar como **enteros en centavos** para evitar errores de redondeo.
- Los precios se cargan **sin IVA** (como en la web de ARCA); el sistema calcula IVA 21% y total.
- Cambios en la base: solo agregar tablas/columnas que se creen solas al arrancar, sin borrar
  datos existentes (la base del usuario en `instance/` ya tiene información real).
- Fechas: guardar como texto ISO `AAAA-MM-DD`.
- CUIT: guardar solo dígitos (11), mostrar como `XX-XXXXXXXX-X`. Validar dígito verificador.
- Facturas emitidas no se borran: se anulan con nota de crédito.
- Pruebas con `unittest` (viene con Python): `python -m unittest discover tests`.

## Plan por etapas

1. **Base y clientes** ✅
   Proyecto, base de datos, pantalla de clientes: alta, edición, búsqueda.
   Condición frente al IVA y CUIT/DNI validados. Muestra qué letra de factura le corresponde.
2. **Plantillas de conceptos** ✅
   ABM de conceptos fijos: solo el texto (el precio cambia en cada factura).
   Ej.: "Desarme y Reparación en Elásticos Delanteros Derecho". Búsqueda por palabras.
3. **Facturas (de prueba, sin ARCA)** ✅
   Alta de factura A/B: cliente, fecha, renglones (cantidad × precio unitario sin IVA) de texto
   libre o desde concepto fijo, neto + IVA 21% + total. Numeración por punto de venta y tipo.
   Marcadas como "PRUEBA" (`prueba = 1`); solo esas se pueden eliminar.
4. **PDF de la factura**
   PDF con el formato fiscal (datos del emisor, receptor, detalle, totales) y QR de ARCA
   (con datos ficticios hasta tener CAE real).
5. **Notas de crédito**
   NC A/B asociadas a una factura (total, que es lo habitual cuando se anula).
6. **Cobros**
   Registrar cobro de una factura por su total: fecha, medio de pago, observaciones.
7. **Cuenta corriente por cliente**
   Movimientos (facturas, NC, cobros) con saldo; listado de saldos de todos los clientes.
8. **Resumen mensual y Excel**
   Ventas del mes (neto, IVA, total por tipo), cobros del mes, exportable a Excel.
9. **Backup automático**
   Copia diaria de la base de datos a una carpeta (con rotación), y botón de backup manual.
10. **Conexión con ARCA (homologación y luego producción)**
    Certificado digital, WSAA (autenticación) y WSFEv1 (obtener CAE).
    Primero en el ambiente de prueba de ARCA; después en producción.
    QR con datos reales del CAE.
