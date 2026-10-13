"""Importes y cantidades: lectura en formato argentino, cálculos y formato para mostrar.

Los importes se guardan como enteros en centavos y las cantidades como enteros en
centésimos (1,5 unidades = 150), para que las cuentas no tengan errores de redondeo.
"""
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

ALICUOTA_IVA = Decimal("21")


def leer_decimal(texto):
    """Convierte "30.000,50", "30000,5", "30000.50" o "30000" en Decimal. None si no es válido."""
    texto = (texto or "").strip().replace("$", "").replace(" ", "")
    if not texto:
        return None
    if "," in texto:
        # Formato argentino: el punto separa miles y la coma los decimales.
        texto = texto.replace(".", "").replace(",", ".")
    elif texto.count(".") > 1 or re.fullmatch(r"\d{1,3}(\.\d{3})+", texto):
        # "30.000" o "1.250.000": puntos de miles.
        texto = texto.replace(".", "")
    try:
        valor = Decimal(texto)
    except InvalidOperation:
        return None
    return valor if valor.is_finite() else None


def a_centavos(texto):
    """Lee un importe en pesos y lo devuelve en centavos (int). None si no es válido."""
    valor = leer_decimal(texto)
    # Rechaza más de 2 decimales y números absurdamente grandes (más de mil millones).
    if valor is None or abs(valor) >= Decimal("1e9") or valor != valor.quantize(Decimal("0.01")):
        return None
    return int(valor * 100)


def a_centesimos(texto):
    """Lee una cantidad y la devuelve en centésimos (int). None si no es válida."""
    return a_centavos(texto)


def redondear(valor):
    return int(Decimal(valor).to_integral_value(ROUND_HALF_UP))


def subtotal(cantidad_centesimos, precio_centavos):
    """Cantidad × precio unitario, en centavos."""
    return redondear(Decimal(cantidad_centesimos) * precio_centavos / 100)


def calcular_totales(renglones):
    """renglones: lista de (cantidad_centesimos, precio_centavos). Devuelve neto, iva, total."""
    neto = sum(subtotal(c, p) for c, p in renglones)
    iva = redondear(Decimal(neto) * ALICUOTA_IVA / 100)
    return {"neto": neto, "iva": iva, "total": neto + iva}


def _con_miles(entero):
    return f"{entero:,}".replace(",", ".")


def formato_pesos(centavos, signo=True):
    """12345678 -> "$ 123.456,78"."""
    if centavos is None:
        return ""
    negativo = centavos < 0
    centavos = abs(centavos)
    texto = f"{_con_miles(centavos // 100)},{centavos % 100:02d}"
    if negativo:
        texto = "-" + texto
    return f"$ {texto}" if signo else texto


def formato_cantidad(centesimos):
    """150 -> "1,5"; 200 -> "2"."""
    if centesimos is None:
        return ""
    entero, resto = divmod(centesimos, 100)
    if resto == 0:
        return _con_miles(entero)
    return f"{_con_miles(entero)},{resto:02d}".rstrip("0")
