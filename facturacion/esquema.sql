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

-- Facturas. Los datos del cliente se copian en la factura: si después se edita el
-- cliente, la factura ya emitida no cambia. Importes en centavos.
CREATE TABLE IF NOT EXISTS facturas (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    cbte_tipo           INTEGER NOT NULL,           -- código ARCA: 1 = Factura A, 6 = Factura B
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
    -- remito_pto_vta, remito_numero y token se agregan desde db.py (COLUMNAS_NUEVAS).
    creado              TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- No puede haber dos comprobantes con el mismo número (las de prueba van aparte).
CREATE UNIQUE INDEX IF NOT EXISTS facturas_numero_unico
    ON facturas (punto_venta, cbte_tipo, prueba, numero);
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
