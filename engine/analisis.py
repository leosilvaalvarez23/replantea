"""Análisis de un negocio y validación de propuestas — Replantea.

Port a Python de `analizar`, `initPropuesta` y `calc` de prototipo/v2/motor.js.
El servidor recalcula con esto lo que el comprador ve y firma: el resultado
del navegador nunca se toma como verdad.

Fechas 'YYYY-MM-DD' (comparables como texto). Montos en COP.
`corte` es la fecha de hoy y se recibe como parámetro para poder probar.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from .engine import ConfigProyecto, ResultadoEvaluar, evaluar


def _redondear(x: float) -> int:
    """Math.round de JavaScript (la mitad sube), no el redondeo bancario de Python."""
    return math.floor(x + 0.5)


def fmt_cop(v: float) -> str:
    """$ 1.234.567 (con − delante si es negativo), como en la interfaz."""
    texto = f"{_redondear(abs(v)):,}".replace(",", ".")
    return f"{'−' if v < 0 else ''}$ {texto}"


_MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
           "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def fecha_larga(f: str) -> str:
    """2027-03-28 -> 28 de marzo de 2027."""
    y, m, d = f.split("-")
    return f"{int(d)} de {_MESES[int(m) - 1]} de {y}"


def _fecha_valida(f: Optional[str]) -> Optional[str]:
    return f if f and f > "1900-01-01" else None


@dataclass
class AnalisisNegocio:
    pend: list            # cuotas pendientes (FIFO contra el recaudo): fecha, valor, concepto, vencida
    base: list            # base para el motor: pendiente (vencidas llevadas al corte) + crédito
    credito: float
    fecha_credito: Optional[str]
    tot_rec: float
    saldo: float          # cuota inicial pendiente (plan pactado menos recaudo)
    vencido: float
    mora: int             # mora pendiente de cobrar, según IngeMAX
    fecha_limite: Optional[str]
    recaudo: list = field(default_factory=list)


def analizar(negocio: dict, corte: str) -> AnalisisNegocio:
    """Calcula lo pendiente de un negocio de IngeMAX (`plan_pagos` + `recaudo`)."""
    pactado = [
        {"fecha": p["fecha_pp"], "valor": p["valor"], "concepto": p.get("concepto", "")}
        for p in negocio.get("plan_pagos", [])
    ]
    recaudo = [
        {"fecha": r["fecha"], "valor": r["valor"], "concepto": r.get("concepto", "")}
        for r in negocio.get("recaudo", [])
    ]

    # El recaudo cubre las cuotas más antiguas primero (FIFO)
    disponible = sum(r["valor"] for r in recaudo)
    pend = []
    for p in sorted(pactado, key=lambda x: x["fecha"]):
        usado = min(disponible, p["valor"])
        disponible -= usado
        resto = p["valor"] - usado
        if resto > 0.5:
            pend.append({**p, "valor": resto, "vencida": p["fecha"] < corte})

    tot_pact = sum(p["valor"] for p in pactado)
    tot_rec = sum(r["valor"] for r in recaudo)
    vencido = sum(p["valor"] for p in pend if p["vencida"])

    fecha_limite = _fecha_valida(negocio.get("fecha_escrituracion_programada"))
    if not fecha_limite and pactado:
        fecha_limite = max(p["fecha"] for p in pactado)

    credito = negocio.get("valor_credito") or 0
    fecha_credito = _fecha_valida(negocio.get("fecha_credito")) or fecha_limite

    # Las vencidas se llevan a la fecha de corte; el crédito va en su fecha
    base = [
        {"fecha": corte if p["vencida"] else p["fecha"], "valor": p["valor"]} for p in pend
    ]
    if credito > 0:
        base.append({"fecha": fecha_credito, "valor": credito})

    # Mora según IngeMAX, por cuota:
    #   int_aplicado == 1 -> condonada por la constructora (no suma)
    #   int_aplicado == 0 -> pendiente: suma int_mora
    #   int_aplicado  > 1 -> cobrada en parte: suma int_mora - int_aplicado
    mora = 0.0
    for p in negocio.get("plan_pagos", []):
        m = p.get("int_mora") or 0
        a = p.get("int_aplicado") or 0
        if a == 1:
            continue
        mora += max(0, m - a)

    return AnalisisNegocio(
        pend=pend,
        base=base,
        credito=credito,
        fecha_credito=fecha_credito,
        tot_rec=tot_rec,
        saldo=tot_pact - tot_rec,
        vencido=vencido,
        mora=_redondear(mora),
        fecha_limite=fecha_limite,
        recaudo=recaudo,
    )


def init_propuesta(a: AnalisisNegocio, corte: str) -> list[dict]:
    """Propuesta inicial: el plan pendiente, con lo vencido absorbido por la primera cuota futura."""
    vencidas = [p for p in a.pend if p["vencida"]]
    futuras = [p for p in a.pend if not p["vencida"]]
    total_vencido = sum(p["valor"] for p in vencidas)

    def fila(p, valor, fijo):
        return {
            "fecha": p["fecha"], "concepto": p["concepto"], "valor": valor,
            "orig": p["valor"], "orig_fecha": p["fecha"], "fijo": fijo,
        }

    if total_vencido == 0:
        return [fila(p, p["valor"], False) for p in futuras]
    if not futuras:
        # Todo vencido y nada futuro: un único pago en la fecha de corte
        p = {**vencidas[0], "fecha": corte, "valor": total_vencido}
        return [fila(p, total_vencido, True)]
    return [
        fila(p, p["valor"] + total_vencido if i == 0 else p["valor"], i == 0)
        for i, p in enumerate(futuras)
    ]


@dataclass
class ResultadoCalculo:
    ev: ResultadoEvaluar
    tot_prop: float
    dif: int              # >0: falta por asignar; <0: sobra
    excedente: int        # lo que la propuesta paga por encima de la cuota inicial pendiente
    nuevo_cred: float     # el excedente se descuenta del crédito
    errores: list

    @property
    def valido(self) -> bool:
        return not self.errores


def calcular(
    propuesta: list[dict],
    a: AnalisisNegocio,
    negocio: dict,
    cfg: ConfigProyecto,
    corte: str,
) -> ResultadoCalculo:
    """Evalúa una propuesta (lista de {fecha, valor, abono?}) y la valida."""
    tot_prop = sum(p["valor"] for p in propuesta)
    dif = _redondear(a.saldo - tot_prop)
    excedente = max(0, -dif)
    valor_credito = negocio.get("valor_credito") or 0
    nuevo_cred = max(0, valor_credito - excedente)

    # El motor ve la cuota inicial propuesta + el crédito ya reducido por el excedente
    prop_motor = [{"fecha": p["fecha"], "valor": p["valor"]} for p in propuesta]
    if a.credito > 0:
        prop_motor.append({"fecha": a.fecha_credito, "valor": nuevo_cred})
    ev = evaluar(a.base, [], prop_motor, cfg, negocio["valor_venta"])

    errores = []
    if dif > 1:
        errores.append(f"Faltan {fmt_cop(dif)} por asignar a las cuotas.")
    if any(p["fecha"] < corte for p in propuesta):
        errores.append("Hay cuotas con fecha anterior a hoy.")
    if a.fecha_limite and any(p["fecha"] > a.fecha_limite for p in propuesta):
        errores.append(f"Todas las cuotas deben quedar antes del {fecha_larga(a.fecha_limite)}.")
    if any(not p.get("abono") and 0 < p["valor"] < cfg.cuota_min for p in propuesta):
        errores.append(f"Cada cuota debe ser de al menos {fmt_cop(cfg.cuota_min)}, salvo los abonos.")
    if any(not p["valor"] > 0 for p in propuesta):
        errores.append("Hay cuotas en cero. Elimínalas o asígnales un valor.")

    return ResultadoCalculo(
        ev=ev, tot_prop=tot_prop, dif=dif, excedente=excedente,
        nuevo_cred=nuevo_cred, errores=errores,
    )
