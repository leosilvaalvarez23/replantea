"""Tests del motor de cálculo — valores esperados verificados contra engine.js con Node.js."""
import pytest
from engine.engine import (
    ConfigProyecto,
    Pago,
    days360,
    evaluar,
    liquidacion,
    vpn,
)


# ---------------------------------------------------------------------------
# days360 (US/NASD — equivalente a DAYS360 de Excel)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("a,b,expected", [
    ("2020-01-01", "2020-02-01", 30),
    ("2020-01-31", "2020-02-28", 28),   # Feb normal: d2 queda en 28
    ("2020-01-31", "2020-03-31", 60),
    ("2020-02-28", "2020-03-31", 33),   # Feb28 no es el último (2020 bisiesto)
    ("2020-02-29", "2020-03-31", 30),   # Feb29 es el último de Feb en año bisiesto
])
def test_days360(a, b, expected):
    assert days360(a, b) == expected


# ---------------------------------------------------------------------------
# liquidacion: ajuste = 0 cuando propuesta = pactado
# ---------------------------------------------------------------------------

def test_zero_adjustment_simple():
    """Si propuesta = plan pactado y no hay recaudo, el ajuste es exactamente 0."""
    pactado = [
        {"fecha": "2024-01-15", "valor": 5_000_000},
        {"fecha": "2024-02-15", "valor": 5_000_000},
        {"fecha": "2024-03-15", "valor": 5_000_000},
    ]
    result = liquidacion(pactado, pactado, tasa_cia=0.006, tasa_cliente=0.024)
    assert result.ajuste == 0.0


def test_zero_adjustment_negocio_1974():
    """Negocio 1974 (datos reales IngeMAX VyP): propuesta = base pendiente → ajuste 0."""
    plan_pagos = [
        {"fecha": "2025-11-28", "valor": 1_500_000},
        {"fecha": "2025-12-28", "valor": 7_238_000},
        {"fecha": "2026-01-31", "valor": 7_238_000},
        {"fecha": "2026-02-28", "valor": 7_238_000},
        {"fecha": "2026-03-31", "valor": 7_238_000},
        {"fecha": "2026-04-30", "valor": 7_238_000},
        {"fecha": "2026-05-31", "valor": 7_238_000},
        {"fecha": "2026-06-30", "valor": 7_238_000},
        {"fecha": "2026-07-31", "valor": 7_238_000},
        {"fecha": "2026-08-31", "valor": 7_238_000},
        {"fecha": "2026-09-30", "valor": 7_238_000},
        {"fecha": "2026-10-31", "valor": 7_238_000},
        {"fecha": "2026-11-30", "valor": 7_238_000},
        {"fecha": "2026-12-31", "valor": 7_238_000},
        {"fecha": "2027-01-31", "valor": 7_238_000},
        {"fecha": "2027-02-28", "valor": 7_238_000},
        {"fecha": "2027-03-31", "valor": 7_238_000},
        {"fecha": "2027-04-30", "valor": 7_238_000},
        {"fecha": "2027-05-31", "valor": 7_238_000},
        {"fecha": "2027-06-30", "valor": 7_238_000},
        {"fecha": "2027-07-31", "valor": 7_228_000},
    ]
    recaudo = [
        {"fecha": "2026-07-24", "valor": 40_000_000},
        {"fecha": "2026-08-19", "valor": 20_404_000},
    ]
    corte = "2026-10-20"
    disp = sum(r["valor"] for r in recaudo)
    pend = []
    for p in sorted(plan_pagos, key=lambda x: x["fecha"]):
        if disp >= p["valor"]:
            disp -= p["valor"]
            continue
        resto = p["valor"] - disp
        disp = 0
        pend.append({"fecha": corte if p["fecha"] <= corte else p["fecha"], "valor": resto})
    result = liquidacion(pend, pend, tasa_cia=0.006, tasa_cliente=0.024)
    assert result.ajuste == 0.0


# ---------------------------------------------------------------------------
# liquidacion: pago adelantado (descuento negativo)
# ---------------------------------------------------------------------------

def test_early_lump_sum():
    """Pagar 3 cuotas de 5 M juntas en la primera fecha → descuento = -90 360.
    Valor calculado con engine.js (Node.js).
    """
    pactado = [
        {"fecha": "2024-01-15", "valor": 5_000_000},
        {"fecha": "2024-02-15", "valor": 5_000_000},
        {"fecha": "2024-03-15", "valor": 5_000_000},
    ]
    propuesta = [{"fecha": "2024-01-15", "valor": 15_000_000}]
    result = liquidacion(pactado, propuesta, tasa_cia=0.006, tasa_cliente=0.024)
    assert abs(result.ajuste - (-90_360.00)) < 0.01


# ---------------------------------------------------------------------------
# liquidacion: pago retrasado (cargo positivo)
# ---------------------------------------------------------------------------

def test_late_single_payment():
    """Una cuota de 5 M pagada 2 meses tarde → cargo = +240 000.
    Valor calculado con engine.js.
    """
    pactado = [{"fecha": "2024-01-15", "valor": 5_000_000}]
    propuesta = [{"fecha": "2024-03-15", "valor": 5_000_000}]
    result = liquidacion(pactado, propuesta, tasa_cia=0.006, tasa_cliente=0.024)
    assert abs(result.ajuste - 240_000.00) < 0.01


# ---------------------------------------------------------------------------
# evaluar: topes y umbrales
# ---------------------------------------------------------------------------

CFG_BASE = ConfigProyecto(
    metodo="liquidacion",
    tasa_cia=0.006,
    tasa_cliente=0.024,
    tope_pct=0.03,
    umbral_pct=0.015,
)


def test_evaluar_sin_tope():
    """Descuento de 3.6 M no supera el tope del 3 % (4.5 M) pero sí el umbral."""
    pactado = [{"fecha": "2024-07-15", "valor": 100_000_000}]
    propuesta = [{"fecha": "2024-01-15", "valor": 100_000_000}]
    res = evaluar(pactado, [], propuesta, CFG_BASE, valor_venta=150_000_000)
    assert res.ajuste_calculado == -3_600_000
    assert res.ajuste == -3_600_000
    assert res.topado is False
    assert res.tope == 4_500_000
    assert res.requiere_aprobacion is True


def test_evaluar_con_tope():
    """Descuento de 14.4 M supera el tope → se aplica el tope = 4.5 M."""
    pactado = [{"fecha": "2026-01-15", "valor": 100_000_000}]
    propuesta = [{"fecha": "2024-01-15", "valor": 100_000_000}]
    res = evaluar(pactado, [], propuesta, CFG_BASE, valor_venta=150_000_000)
    assert res.ajuste_calculado == -14_400_000
    assert res.ajuste == -4_500_000
    assert res.topado is True
    assert res.requiere_aprobacion is True


def test_evaluar_cargo_sin_tope():
    """Cargo por atraso: positivo, no se topa (solo se topa el descuento)."""
    pactado = [{"fecha": "2024-01-15", "valor": 100_000_000}]
    propuesta = [{"fecha": "2024-07-15", "valor": 100_000_000}]
    res = evaluar(pactado, [], propuesta, CFG_BASE, valor_venta=150_000_000)
    assert res.ajuste_calculado == 14_400_000
    assert res.ajuste == 14_400_000
    assert res.topado is False
    assert res.requiere_aprobacion is False


# ---------------------------------------------------------------------------
# vpn: pago anticipado genera descuento
# ---------------------------------------------------------------------------

def test_vpn_early_payment():
    """Pagar 10 M hoy en vez de 5 M + 5 M a 6 meses → descuento ≈ -306 732.68.
    Valor calculado con engine.js.
    """
    pactado = [
        {"fecha": "2024-01-15", "valor": 5_000_000},
        {"fecha": "2024-07-15", "valor": 5_000_000},
    ]
    propuesta = [{"fecha": "2024-01-15", "valor": 10_000_000}]
    result = vpn(pactado, propuesta, tasa=0.01)
    assert abs(result.ajuste - (-306_732.6752)) < 0.1


# ---------------------------------------------------------------------------
# Caso Excel: -6.925.145,36
# ---------------------------------------------------------------------------
# TODO: completar con los datos de Plantilla_Liquidacion_Interes_Clientes.xlsx.
# Pedir a Leonardo: plan_pagos y pagos del caso que produce exactamente -6.925.145,36.
# El test debe llamar liquidacion(pactado, pagos, tasa_cia, tasa_cliente) y verificar
# que result.ajuste == pytest.approx(-6_925_145.36, abs=0.01).
@pytest.mark.skip(reason="Pendiente: datos del Excel (Plantilla_Liquidacion_Interes_Clientes.xlsx)")
def test_caso_excel():
    pactado = []   # reemplazar con datos reales
    pagos = []     # reemplazar con datos reales
    result = liquidacion(pactado, pagos, tasa_cia=0.006, tasa_cliente=0.024)
    assert result.ajuste == pytest.approx(-6_925_145.36, abs=0.01)
