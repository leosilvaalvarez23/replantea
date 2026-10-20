"""Motor de cálculo — Replantea.
Fechas como 'YYYY-MM-DD'. Montos en COP.
Traducción fiel de engine.js.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from typing import Sequence


# ---------------------------------------------------------------------------
# Tipos
# ---------------------------------------------------------------------------

@dataclass
class Pago:
    fecha: str
    valor: float
    concepto: str = ""


@dataclass
class FilaTimeline:
    fecha: str
    D: float = 0.0  # demanda (plan pactado)
    F: float = 0.0  # flujo (pagos reales)
    H: float = 0.0  # interés generado en el período
    I: float = 0.0  # saldo de interés acumulado
    J: float = 0.0  # saldo de capital


@dataclass
class ResultadoLiquidacion:
    ajuste: float
    filas: list[FilaTimeline]


@dataclass
class ResultadoVpn:
    ajuste: float
    pv_pactado: float
    pv_pagos: float
    fecha_liquidacion: str


@dataclass
class ConfigProyecto:
    metodo: str = "liquidacion"       # 'liquidacion' | 'vpn'
    tasa_cia: float = 0.006           # tasa mensual adelantos (saldo < 0)
    tasa_cliente: float = 0.024       # tasa mensual atrasos  (saldo >= 0)
    tasa_vpn: float = 0.01            # tasa mensual VPN
    tope_pct: float = 0.03            # tope descuento como fracción del valor de venta
    umbral_pct: float = 0.015         # umbral aprobación gerencia
    cuota_min: float = 1_000_000
    concepto: str = "Descuento financiero plan de pagos"
    concepto_abono: str = "Recursos Propios"


@dataclass
class ResultadoEvaluar:
    ajuste_calculado: int
    ajuste: int
    topado: bool
    tope: int
    requiere_aprobacion: bool


# ---------------------------------------------------------------------------
# Fecha helpers
# ---------------------------------------------------------------------------

def _parse(s: str) -> tuple[int, int, int]:
    y, m, d = s.split("-")
    return int(y), int(m), int(d)


def _is_last_feb(y: int, m: int, d: int) -> bool:
    return m == 2 and d == calendar.monthrange(y, 2)[1]


def days360(a: str, b: str) -> int:
    """DAYS360 método US (NASD) — equivalente a DAYS360(a,b) de Excel."""
    ay, am, ad = _parse(a)
    by_, bm, bd = _parse(b)
    d1, d2 = ad, bd
    if _is_last_feb(ay, am, ad) and _is_last_feb(by_, bm, bd):
        d2 = 30
    if _is_last_feb(ay, am, ad):
        d1 = 30
    if d2 == 31 and d1 >= 30:
        d2 = 30
    if d1 == 31:
        d1 = 30
    return (by_ - ay) * 360 + (bm - am) * 30 + (d2 - d1)


def _days_actual(a: str, b: str) -> float:
    from datetime import date
    da = date.fromisoformat(a)
    db = date.fromisoformat(b)
    return (db - da).days


# ---------------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------------

def timeline(
    pactado: Sequence[Pago | dict],
    pagos: Sequence[Pago | dict],
) -> list[FilaTimeline]:
    """Combina plan pactado y pagos en una línea de tiempo ordenada."""
    def _val(p: Pago | dict, k: str):
        return getattr(p, k) if isinstance(p, Pago) else p[k]

    rows: dict[str, FilaTimeline] = {}
    for p in pactado:
        f = _val(p, "fecha")
        r = rows.setdefault(f, FilaTimeline(fecha=f))
        r.D += _val(p, "valor")
    for p in pagos:
        f = _val(p, "fecha")
        r = rows.setdefault(f, FilaTimeline(fecha=f))
        r.F += _val(p, "valor")
    return sorted(rows.values(), key=lambda r: r.fecha)


# ---------------------------------------------------------------------------
# Método: Liquidación de saldo (réplica Excel)
# ---------------------------------------------------------------------------

def liquidacion(
    pactado: Sequence,
    pagos: Sequence,
    tasa_cia: float,
    tasa_cliente: float,
) -> ResultadoLiquidacion:
    """Réplica exacta de la plantilla Excel (columnas H, I, J).

    tasa_cia:     interés mensual reconocido cuando saldo < 0 (comprador adelantado)
    tasa_cliente: interés mensual cobrado cuando saldo >= 0  (comprador atrasado)
    """
    rows = timeline(pactado, pagos)
    I_acc = 0.0  # saldo interés
    J_acc = 0.0  # saldo capital
    total_H = 0.0

    for k, r in enumerate(rows):
        H = 0.0
        if k == 0:
            I_acc = 0.0 if r.F > 0 else -r.F
            if I_acc < 0:
                I_acc = 0.0
            J_acc = r.D - r.F
        else:
            prev = rows[k - 1]
            rate = tasa_cliente if J_acc >= 0 else tasa_cia
            H = rate * (12 * days360(prev.fecha, r.fecha) / 360) * J_acc
            IH = I_acc + H
            if IH < 0:
                if IH + r.D >= 0:
                    nI = 0.0
                    nJ = J_acc + (IH + r.D) - r.F
                else:
                    nI = IH + r.D
                    nJ = J_acc - r.F
            else:
                if IH < r.F:
                    nI = 0.0
                    nJ = J_acc + r.D - (r.F - IH)
                else:
                    nI = IH - r.F
                    nJ = J_acc + r.D
            I_acc, J_acc = nI, nJ
        total_H += H
        r.H, r.I, r.J = H, I_acc, J_acc

    return ResultadoLiquidacion(ajuste=total_H, filas=rows)


# ---------------------------------------------------------------------------
# Método: VPN
# ---------------------------------------------------------------------------

def vpn(
    pactado: Sequence,
    pagos: Sequence,
    tasa: float,
) -> ResultadoVpn:
    """Descuenta ambos flujos a t0 con tasa mensual compuesta (días reales / 30.4167)
    y expresa la diferencia a la fecha del último pago.
    """
    def _fecha(p):
        return p["fecha"] if isinstance(p, dict) else p.fecha

    def _valor(p):
        return p["valor"] if isinstance(p, dict) else p.valor

    all_fechas = sorted(set(_fecha(p) for p in list(pactado) + list(pagos)))
    t0 = all_fechas[0]
    t_n = all_fechas[-1]

    def _months(f: str) -> float:
        return _days_actual(t0, f) / (365 / 12)

    def _pv(flujo) -> float:
        return sum(_valor(p) / (1 + tasa) ** _months(_fecha(p)) for p in flujo)

    pv_pact = _pv(pactado)
    pv_pag = _pv(pagos)
    diff = pv_pact - pv_pag  # >0: comprador entrega menos VP → sobrecargo
    mn = _months(t_n)
    ajuste = diff * (1 + tasa) ** mn

    return ResultadoVpn(
        ajuste=ajuste,
        pv_pactado=pv_pact,
        pv_pagos=pv_pag,
        fecha_liquidacion=t_n,
    )


# ---------------------------------------------------------------------------
# Evaluar — con tope y umbral de aprobación
# ---------------------------------------------------------------------------

def evaluar(
    pactado: Sequence,
    recaudo: Sequence,
    propuesta: Sequence,
    cfg: ConfigProyecto,
    valor_venta: float,
) -> ResultadoEvaluar:
    pagos = list(recaudo) + list(propuesta)
    if cfg.metodo == "liquidacion":
        ajuste_raw = liquidacion(pactado, pagos, cfg.tasa_cia, cfg.tasa_cliente).ajuste
    else:
        ajuste_raw = vpn(pactado, pagos, cfg.tasa_vpn).ajuste
    ajuste_calc = round(ajuste_raw)
    tope = round(valor_venta * cfg.tope_pct)
    topado = ajuste_calc < 0 and -ajuste_calc > tope
    aplicado = -tope if topado else ajuste_calc
    requiere = aplicado < 0 and -aplicado > valor_venta * cfg.umbral_pct
    return ResultadoEvaluar(
        ajuste_calculado=ajuste_calc,
        ajuste=aplicado,
        topado=topado,
        tope=tope,
        requiere_aprobacion=requiere,
    )
