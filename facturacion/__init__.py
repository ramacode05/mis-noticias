"""Sistema de facturación y cuentas corrientes."""
import os
import threading
from datetime import date

from flask import Flask, redirect, render_template, url_for


def create_app(config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY="cambiar-esta-clave-en-produccion",
        DATABASE=os.path.join(app.instance_path, "facturacion.sqlite"),
    )
    if config:
        app.config.update(config)

    os.makedirs(app.instance_path, exist_ok=True)

    from . import arca_web, db, clientes, cobros, conceptos, copias, cuentas, facturas, mail, resumen
    from .importes import formato_cantidad, formato_pesos
    db.init_app(app)
    app.register_blueprint(clientes.bp)
    app.register_blueprint(conceptos.bp)
    app.register_blueprint(facturas.bp)
    app.register_blueprint(cobros.bp)
    app.register_blueprint(cuentas.bp)
    app.register_blueprint(resumen.bp)
    app.register_blueprint(copias.bp)
    app.register_blueprint(arca_web.bp)
    app.register_blueprint(mail.bp)

    # Formatos para mostrar en las páginas.
    app.add_template_filter(formato_pesos, "pesos")
    app.add_template_filter(formato_cantidad, "cantidad")
    app.add_template_filter(lambda iso: date.fromisoformat(iso).strftime("%d/%m/%Y") if iso else "",
                            "fecha")
    app.add_template_filter(lambda f: f"{f['punto_venta']:05d}-{f['numero']:08d}", "nro_cbte")
    app.add_template_filter(lambda f: facturas.NOMBRE_CBTE.get(f["cbte_tipo"], ""), "nombre_cbte")

    @app.route("/")
    def inicio():
        return redirect(url_for("facturas.lista"))

    @app.route("/cerrar", methods=("POST",))
    def cerrar():
        """Cierra el sistema y avisa (por Google Drive) que la otra PC ya lo puede abrir."""
        uso = app.config.get("CANDADO")
        if uso is not None:
            uso.cerrar()
            # Apaga el programa un instante después, para que llegue a mostrar la página.
            threading.Timer(1.0, lambda: os._exit(0)).start()
        return render_template("cerrado.html")

    return app
