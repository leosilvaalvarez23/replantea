---
name: project-calc-mora
description: "Reglas implementadas de mora en el motor de cálculo — resuelto 2026-10-21"
metadata: 
  node_type: memory
  type: project
  originSessionId: 23e0c85b-0f72-4ff5-aaae-14568d7922d9
---

## Reglas de mora — implementadas (2026-10-21)

### Cálculo de mora pendiente desde IngeMAX
Por cuota de `plan_pagos`:
- `int_aplicado = 0` → mora calculada y pendiente de cobrar → suma `int_mora`
- `int_aplicado = 1.0` → cuota condonada por la constructora → suma 0
- `int_aplicado > 1` → mora parcialmente cobrada → suma `int_mora - int_aplicado`

Confirmado con T1-602: cuotas nov2025–jul2026 condonadas (int_aplicado=1), ago y sep con mora parcial.

### Propuesta inicial cuando hay mora — `initPropuesta(a)`
Si el negocio tiene cuotas vencidas (`a.vencido > 0`):
- Las cuotas vencidas NO aparecen como filas editables en la propuesta
- La **primera cuota futura** absorbe todo el saldo vencido (`totalVencido`) sumado a su valor original
- Esa primera cuota queda `fijo=true` (mínimo para regularizar la mora)
- El resto del plan mantiene sus fechas y valores originales — sin cuotas nuevas

Si no hay cuotas futuras (todo vencido): un único pago en CORTE por el saldo total.

### Por qué esto es correcto para el motor
- `a.base` tiene las vencidas en CORTE (fecha de referencia)
- La propuesta paga esas mismas cantidades en la fecha futura (ej. 31-oct)
- El motor calcula el sobrecosto financiero por ese diferimiento → **castiga la mora correctamente**
- Comportamiento anterior (vencidas → CORTE en propuesta también) daba ajuste ≈ 0 (no castigaba)

### Excedente sobre cuota inicial → descuenta del crédito
- `excedente = max(0, totProp - a.saldo)` donde `a.saldo` es solo cuota inicial
- `nuevoCred = max(0, valor_credito - excedente)`
- `a.base` incluye el crédito en `fechaCredito` → motor ve efecto completo
- `propMotor` incluye `nuevoCred` → descuento refleja pago anticipado del crédito
- `rebalancear()`: saldo = max(0, ...) para evitar cuotas negativas

**Why:** T1-602 tiene 9 cuotas vencidas ago/sep/nov2025–jul2026. Sin estas reglas el motor no castigaba la mora y no calculaba correctamente el beneficio de pagar el excedente al crédito.
**How to apply:** `initPropuesta(a)` en `encontrarOCrear()` y `btnReset`. Motor recibe `propMotor` con crédito.
