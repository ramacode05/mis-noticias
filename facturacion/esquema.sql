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
