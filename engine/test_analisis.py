"""Tests del análisis de negocios y validación de propuestas.

El negocio de prueba reproduce el de demostración del prototipo (T1-602, #1974)
con la fecha de corte fija en 2026-10-24. Las cifras esperadas (saldo, vencido,
mora) se verifican a mano:

  * 15 cuotas de 9.750.000, de ene-2026 a mar-2027 (día 28): plan = 146.250.000
  * recaudo: 5 x 10.000.000 + 10.400.000 = 60.400.000
  * FIFO: cubre 6 cuotas (58.500.000) y 1.900.000 de la séptima
  * vencido: jul (7.850.000) + ago + sep (9.750.000 c/u) = 27.350.000
  * saldo: 146.250.000 - 60.400.000 = 85.850.000
"""
import copy

import pytest

from engine.analisis import (
    analizar,
    calcular,
    fecha_larga,
    fmt_cop,
    init_propuesta,
    _redondear,
)
from engine.engine import ConfigProyecto

CORTE = "2026-10-24"
CFG = ConfigProyecto(
    metodo="liquidacion", tasa_cia=0.006, tasa_cliente=0.01,
    tope_pct=0.03, umbral_pct=0.015, cuota_min=1_000_000,
)


def _mes(i: int) -> str:
    """i = 0 -> 2026-01-28 ... i = 14 -> 2027-03-28"""
    y, m = divmod(i, 12)
    return f"{2026 + y}-{m + 1:02d}-28"


def negocio_1974() -> dict:
    plan = []
    for i in range(15):
        plan.append({
            "fecha_pp": _mes(i), "concepto": "Recursos Propios", "valor": 9_750_000,
            "int_mora": 180_000 if i < 9 else 0,
            # i<5: condonada (1); i=5: pendiente (0); i=6: cobrada en parte (60.000); resto 0
            "int_aplicado": 1 if i < 5 else (60_000 if i == 6 else 0),
        })
    recaudo = [{"fecha": _mes(i), "concepto": "Recursos Propios", "valor": 10_000_000} for i in range(5)]
    recaudo.append({"fecha": _mes(5), "concepto": "Recursos Propios", "valor": 10_400_000})
    return {
        "id_venta": 1974, "valor_venta": 487_500_000, "valor_credito": 341_250_000,
        "fecha_escrituracion_programada": "1900-01-01",   # sin definir
        "plan_pagos": plan, "recaudo": recaudo,
    }


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def test_formato_pesos():
    assert fmt_cop(1_234_567) == "$ 1.234.567"
    assert fmt_cop(-5) == "−$ 5"
    assert fmt_cop(0) == "$ 0"


def test_redondeo_como_javascript():
    assert _redondear(2.5) == 3      # Python redondearía a 2
    assert _redondear(-2.5) == -2    # igual que Math.round
    assert _redondear(2.4) == 2


def test_fecha_larga():
    assert fecha_larga("2027-03-28") == "28 de marzo de 2027"
    assert fecha_larga("2026-10-01") == "1 de octubre de 2026"


# ---------------------------------------------------------------------------
# analizar
# ---------------------------------------------------------------------------

def test_analizar_negocio_1974():
    a = analizar(negocio_1974(), CORTE)
    assert a.tot_rec == 60_400_000
    assert a.saldo == 85_850_000
    assert a.vencido == 27_350_000
    assert len(a.pend) == 9
    assert [p["vencida"] for p in a.pend] == [True] * 3 + [False] * 6
    # la séptima cuota quedó cubierta en 1.900.000
    assert a.pend[0]["valor"] == 7_850_000


def test_mora_segun_int_aplicado():
    # i=5 pendiente (180.000) + i=6 parcial (180.000-60.000) + i=7 y i=8 sin cobrar (2 x 180.000)
    assert analizar(negocio_1974(), CORTE).mora == 180_000 + 120_000 + 360_000


def test_mora_condonada_no_suma():
    n = {"plan_pagos": [{"fecha_pp": "2026-01-28", "valor": 1, "int_mora": 500_000, "int_aplicado": 1}],
         "recaudo": [], "valor_venta": 10}
    assert analizar(n, CORTE).mora == 0


def test_mora_sin_campos_es_cero():
    n = {"plan_pagos": [{"fecha_pp": "2026-01-28", "valor": 100}], "recaudo": [], "valor_venta": 10}
    assert analizar(n, CORTE).mora == 0


def test_fecha_limite_sin_definir_usa_ultima_cuota():
    a = analizar(negocio_1974(), CORTE)
    assert a.fecha_limite == "2027-03-28"
    assert a.fecha_credito == "2027-03-28"


def test_fecha_limite_definida():
    n = negocio_1974()
    n["fecha_escrituracion_programada"] = "2027-06-30"
    assert analizar(n, CORTE).fecha_limite == "2027-06-30"


def test_base_lleva_vencidas_al_corte_e_incluye_el_credito():
    a = analizar(negocio_1974(), CORTE)
    assert [b["fecha"] for b in a.base[:3]] == [CORTE] * 3
    assert a.base[-1] == {"fecha": "2027-03-28", "valor": 341_250_000}
    assert sum(b["valor"] for b in a.base) == 85_850_000 + 341_250_000


def test_fifo_cubre_cuotas_mas_antiguas():
    n = {"valor_venta": 1, "plan_pagos": [
            {"fecha_pp": "2026-12-01", "valor": 100}, {"fecha_pp": "2026-11-01", "valor": 100}],
         "recaudo": [{"fecha": "2026-10-01", "valor": 150}]}
    a = analizar(n, CORTE)
    # el recaudo cubre primero noviembre (100) y 50 de diciembre
    assert [(p["fecha"], p["valor"]) for p in a.pend] == [("2026-12-01", 50)]


# ---------------------------------------------------------------------------
# init_propuesta
# ---------------------------------------------------------------------------

def test_propuesta_inicial_con_mora_absorbe_vencido_en_la_primera_futura():
    a = analizar(negocio_1974(), CORTE)
    p = init_propuesta(a, CORTE)
    assert len(p) == 6
    assert p[0]["valor"] == 9_750_000 + 27_350_000
    assert p[0]["fijo"] is True and all(not x["fijo"] for x in p[1:])
    assert [x["valor"] for x in p[1:]] == [9_750_000] * 5
    assert sum(x["valor"] for x in p) == a.saldo


def test_propuesta_inicial_al_dia_copia_el_plan():
    n = negocio_1974()
    n["plan_pagos"] = [{"fecha_pp": f, "concepto": "X", "valor": 9_750_000}
                       for f in ["2026-11-28", "2026-12-28", "2027-01-28"]]
    n["recaudo"] = []
    a = analizar(n, CORTE)
    p = init_propuesta(a, CORTE)
    assert [x["fecha"] for x in p] == ["2026-11-28", "2026-12-28", "2027-01-28"]
    assert not any(x["fijo"] for x in p)


def test_propuesta_inicial_todo_vencido_paga_en_el_corte():
    n = {"valor_venta": 1, "recaudo": [],
         "plan_pagos": [{"fecha_pp": "2026-08-28", "concepto": "X", "valor": 5_000_000},
                        {"fecha_pp": "2026-09-28", "concepto": "X", "valor": 5_000_000}]}
    a = analizar(n, CORTE)
    p = init_propuesta(a, CORTE)
    assert len(p) == 1
    assert p[0]["fecha"] == CORTE and p[0]["valor"] == 10_000_000 and p[0]["fijo"] is True


# ---------------------------------------------------------------------------
# calcular
# ---------------------------------------------------------------------------

def _ctx():
    n = negocio_1974()
    a = analizar(n, CORTE)
    return n, a, init_propuesta(a, CORTE)


def test_propuesta_inicial_es_valida_y_cubre_el_saldo():
    n, a, p = _ctx()
    r = calcular(p, a, n, CFG, CORTE)
    assert r.valido and r.dif == 0 and r.excedente == 0
    assert r.nuevo_cred == 341_250_000


def test_resultado_del_motor_coincide_con_el_prototipo():
    """Valor que mostró el prototipo en pantalla para este caso: cargo de $ 38.302."""
    n, a, p = _ctx()
    r = calcular(p, a, n, CFG, CORTE)
    assert abs(r.ev.ajuste - 38_302) <= 1


def test_excedente_se_descuenta_del_credito():
    n, a, p = _ctx()
    p[-1]["valor"] += 1_000_000
    r = calcular(p, a, n, CFG, CORTE)
    assert r.excedente == 1_000_000
    assert r.nuevo_cred == 340_250_000
    assert r.valido


def test_excedente_nunca_deja_el_credito_negativo():
    n, a, p = _ctx()
    p[-1]["valor"] += 999_000_000
    assert calcular(p, a, n, CFG, CORTE).nuevo_cred == 0


def test_faltante_es_error():
    n, a, p = _ctx()
    p[1]["valor"] -= 2_000_000
    r = calcular(p, a, n, CFG, CORTE)
    assert not r.valido
    assert any("Faltan $ 2.000.000" in e for e in r.errores)


def test_fecha_pasada_es_error():
    n, a, p = _ctx()
    p[1]["fecha"] = "2026-10-01"
    assert any("anterior a hoy" in e for e in calcular(p, a, n, CFG, CORTE).errores)


def test_fecha_despues_del_limite_es_error():
    n, a, p = _ctx()
    p[-1]["fecha"] = "2027-04-28"
    assert any("28 de marzo de 2027" in e for e in calcular(p, a, n, CFG, CORTE).errores)


def test_cuota_minima_se_exige_salvo_abonos():
    n, a, p = _ctx()
    p[1]["valor"] = 500_000
    p[2]["valor"] += 9_250_000          # mantiene el total para aislar el error
    assert any("al menos" in e for e in calcular(p, a, n, CFG, CORTE).errores)
    p[1]["abono"] = True
    assert not any("al menos" in e for e in calcular(p, a, n, CFG, CORTE).errores)


def test_cuota_en_cero_es_error():
    n, a, p = _ctx()
    p[2]["valor"] = 0
    p[3]["valor"] += 9_750_000
    assert any("en cero" in e for e in calcular(p, a, n, CFG, CORTE).errores)


def test_no_modifica_el_negocio_ni_la_propuesta():
    n, a, p = _ctx()
    n0, p0 = copy.deepcopy(n), copy.deepcopy(p)
    calcular(p, a, n, CFG, CORTE)
    assert n == n0 and p == p0


def test_adelantar_pagos_da_descuento_y_aplazar_da_cargo():
    n = {"valor_venta": 300_000_000, "valor_credito": 0, "fecha_escrituracion_programada": "2027-12-28",
         "plan_pagos": [{"fecha_pp": _mes(i), "concepto": "X", "valor": 10_000_000} for i in range(10, 15)],
         "recaudo": []}
    a = analizar(n, CORTE)
    base = init_propuesta(a, CORTE)
    adelanto = copy.deepcopy(base)
    adelanto[0]["valor"] += adelanto[-1]["valor"]
    adelanto.pop()
    assert calcular(adelanto, a, n, CFG, CORTE).ev.ajuste < 0     # descuento
    aplaza = copy.deepcopy(base)
    aplaza[0]["valor"] -= 5_000_000
    aplaza[-1]["valor"] += 5_000_000
    assert calcular(aplaza, a, n, CFG, CORTE).ev.ajuste > 0       # cargo
