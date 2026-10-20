-- Tablas de la base de datos. "IF NOT EXISTS" permite correrlo varias veces sin borrar nada.

CREATE TABLE IF NOT EXISTS clientes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    razon_social    TEXT NOT NULL,
    condicion_iva   TEXT NOT NULL CHECK (condicion_iva IN ('RI', 'MT', 'EX', 'CF')),
    tipo_doc        TEXT NOT NULL CHECK (tipo_doc IN ('CUIT', 'DNI', 'SIN')),
    nro_doc         TEXT NOT NULL DEFAULT '',
    domicilio       TEXT NOT NULL DEFAULT '',
    localidad       TEXT NOT NULL DEFAULT '',
    email           TEXT NOT NULL DEFAULT '',
    telefono        TEXT NOT NULL DEFAULT '',
    observaciones   TEXT NOT NULL DEFAULT '',
    activo          INTEGER NOT NULL DEFAULT 1,
    creado          TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    modificado      TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- No puede haber dos clientes con el mismo CUIT o DNI.
CREATE UNIQUE INDEX IF NOT EXISTS clientes_doc_unico
    ON clientes (tipo_doc, nro_doc) WHERE tipo_doc <> 'SIN';

-- Conceptos fijos que se repiten en las facturas. Solo el texto: el precio se pone en cada factura.
CREATE TABLE IF NOT EXISTS conceptos (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    descripcion     TEXT NOT NULL,
    activo          INTEGER NOT NULL DEFAULT 1,
    creado          TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    modificado      TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- No puede haber dos conceptos con el mismo texto (sin importar mayúsculas).
CREATE UNIQUE INDEX IF NOT EXISTS conceptos_descripcion_unica
    ON conceptos (descripcion COLLATE NOCASE);

-- Configuración general (clave = valor). Hoy sin uso: los puntos de venta se eligen en
-- cada factura. Se deja para guardar datos de la empresa más adelante (PDF, ARCA).
CREATE TABLE IF NOT EXISTS configuracion (
    clave           TEXT PRIMARY KEY,
    valor           TEXT NOT NULL
);

-- Facturas y notas de crédito (comprobantes). Los datos del cliente se copian en la factura: si después se edita el
-- cliente, la factura ya emitida no cambia. Importes en centavos.
CREATE TABLE IF NOT EXISTS facturas (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    cbte_tipo           INTEGER NOT NULL,           -- código ARCA: 1/6 = Factura A/B, 3/8 = Nota de Crédito A/B
    letra               TEXT NOT NULL CHECK (letra IN ('A', 'B')),
    punto_venta         INTEGER NOT NULL,
    numero              INTEGER NOT NULL,
    prueba              INTEGER NOT NULL DEFAULT 1, -- 1 = factura de prueba (sin CAE de ARCA)
    fecha               TEXT NOT NULL,              -- AAAA-MM-DD
    concepto            INTEGER NOT NULL DEFAULT 3, -- ARCA: 1 Productos, 2 Servicios, 3 Productos y Servicios
    serv_desde          TEXT,
    serv_hasta          TEXT,
    vto_pago            TEXT,
    condicion_venta     TEXT NOT NULL,
    cliente_id          INTEGER NOT NULL REFERENCES clientes (id),
    cliente_razon_social TEXT NOT NULL,
    cliente_condicion_iva TEXT NOT NULL,
    cliente_tipo_doc    TEXT NOT NULL,
    cliente_nro_doc     TEXT NOT NULL,
    cliente_domicilio   TEXT NOT NULL,
    neto                INTEGER NOT NULL,
    iva                 INTEGER NOT NULL,
    total               INTEGER NOT NULL,
    observaciones       TEXT NOT NULL DEFAULT '',
    cae                 TEXT,
    cae_vto             TEXT,
    -- remito_pto_vta, remito_numero, token, asociado_id y arca se agregan desde db.py (COLUMNAS_NUEVAS).
    creado              TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- La regla de "no repetir números" se crea en db.py (INDICES_NUEVOS), porque depende de la
-- columna `arca`, que se agrega después.
CREATE INDEX IF NOT EXISTS facturas_cliente ON facturas (cliente_id);
CREATE INDEX IF NOT EXISTS facturas_fecha ON facturas (fecha);

-- Renglones del detalle de cada factura.
CREATE TABLE IF NOT EXISTS factura_renglones (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    factura_id          INTEGER NOT NULL REFERENCES facturas (id) ON DELETE CASCADE,
    orden               INTEGER NOT NULL,
    descripcion         TEXT NOT NULL,
    cantidad            INTEGER NOT NULL,           -- en centésimos: 1,5 = 150
    precio_unitario     INTEGER NOT NULL,           -- en centavos, sin IVA
    subtotal            INTEGER NOT NULL            -- en centavos, sin IVA
);
CREATE INDEX IF NOT EXISTS factura_renglones_factura ON factura_renglones (factura_id);

-- Cobros. Siempre por el total de cada factura; un cobro puede pagar varias facturas del
-- mismo cliente (por ejemplo, una transferencia por tres facturas). Importes en centavos.
CREATE TABLE IF NOT EXISTS cobros (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    cliente_id      INTEGER NOT NULL REFERENCES clientes (id),
    fecha           TEXT NOT NULL,              -- AAAA-MM-DD
    medio           TEXT NOT NULL,
    referencia      TEXT NOT NULL DEFAULT '',   -- número de cheque, de transferencia, etc.
    total           INTEGER NOT NULL,
    observaciones   TEXT NOT NULL DEFAULT '',
    token           TEXT UNIQUE,                -- evita duplicar si se confirma dos veces
    creado          TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS cobros_cliente ON cobros (cliente_id);

-- Qué facturas paga cada cobro. Una factura se cobra una sola vez.
CREATE TABLE IF NOT EXISTS cobro_facturas (
    cobro_id        INTEGER NOT NULL REFERENCES cobros (id) ON DELETE CASCADE,
    factura_id      INTEGER NOT NULL UNIQUE REFERENCES facturas (id),
    importe         INTEGER NOT NULL,
    PRIMARY KEY (cobro_id, factura_id)
);

-- ===== Cierre de mes: ingresos en efectivo, facturas de proveedores y gastos por categoría =====
-- Importes en centavos. El mes de cada registro sale de su fecha (AAAA-MM).

-- Plata en efectivo que entra y no está facturada.
CREATE TABLE IF NOT EXISTS ingresos_efectivo (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha           TEXT NOT NULL,
    detalle         TEXT NOT NULL DEFAULT '',
    importe         INTEGER NOT NULL,
    creado          TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS ingresos_efectivo_fecha ON ingresos_efectivo (fecha);

-- Facturas que le hacen los proveedores a la empresa (solo el total).
CREATE TABLE IF NOT EXISTS compras (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha           TEXT NOT NULL,
    proveedor       TEXT NOT NULL,
    numero          TEXT NOT NULL DEFAULT '',
    total           INTEGER NOT NULL,
    vencimiento     TEXT,
    pagada          TEXT,                       -- fecha de pago (NULL: pendiente)
    observaciones   TEXT NOT NULL DEFAULT '',
    creado          TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS compras_fecha ON compras (fecha);

-- Categorías de gastos (las columnas de la planilla anual). Se pueden agregar u ocultar.
CREATE TABLE IF NOT EXISTS categorias_gasto (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre          TEXT NOT NULL,
    orden           INTEGER NOT NULL DEFAULT 0,
    activa          INTEGER NOT NULL DEFAULT 1
);
CREATE UNIQUE INDEX IF NOT EXISTS categorias_gasto_nombre ON categorias_gasto (nombre COLLATE NOCASE);
INSERT OR IGNORE INTO categorias_gasto (nombre, orden) VALUES
    ('Jubilaciones', 1), ('Luz', 2), ('Teléfono', 3), ('Seguridad e higiene', 4),
    ('Cartel y publicidad', 5), ('Inmobiliario', 6), ('Tasa municipal', 7), ('Agua', 8),
    ('ARBA Ingresos brutos', 9), ('Contador', 10), ('Sueldos', 11), ('Aportes jubilatorios', 12),
    ('Gas', 13), ('Atilio', 14), ('IVA', 15), ('Varios', 16);

-- Importe de cada categoría en cada mes.
CREATE TABLE IF NOT EXISTS gastos_mes (
    mes             TEXT NOT NULL,              -- AAAA-MM
    categoria_id    INTEGER NOT NULL REFERENCES categorias_gasto (id),
    importe         INTEGER NOT NULL,
    PRIMARY KEY (mes, categoria_id)
);
