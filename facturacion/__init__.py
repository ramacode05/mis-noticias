"""Sistema de facturación y cuentas corrientes."""
import os

from flask import Flask, redirect, url_for


def create_app(config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY="cambiar-esta-clave-en-produccion",
        DATABASE=os.path.join(app.instance_path, "facturacion.sqlite"),
    )
    if config:
        app.config.update(config)

    os.makedirs(app.instance_path, exist_ok=True)

    from . import db, clientes, conceptos
    db.init_app(app)
    app.register_blueprint(clientes.bp)
    app.register_blueprint(conceptos.bp)

    @app.route("/")
    def inicio():
        return redirect(url_for("clientes.lista"))

    return app
