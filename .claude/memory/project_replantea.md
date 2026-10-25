---
name: project-replantea
description: "Estado del proyecto Replantea — servidor, repo, stack Django y estado actual del MVP"
metadata: 
  node_type: memory
  type: project
  originSessionId: 23e0c85b-0f72-4ff5-aaae-14568d7922d9
---

App web para modificar planes de pagos de vivienda. Cliente inicial: VyP (IngeMAX).

## Repositorio
- GitHub público: https://github.com/leosilvaalvarez23/replantea (cuenta leosilvaalvarez23)
- Rama principal: `main`

## Servidor de pruebas
- IP: 2.31.84.237 (Hetzner CX23, Nuremberg, Ubuntu 26.04)
- SSH: `ssh -i ~/.ssh/id_replantea root@2.31.84.237` (llave sin passphrase)
- Stack en `/opt/replantea`: docker compose del repo GitHub
- URL: https://replantea.2-31-84-237.sslip.io

## SSH keys
- `~/.ssh/id_replantea` — sin passphrase, autorizada en el servidor ✓
- `~/.ssh/id_ed25519` — labeled "Comercial2", TIENE passphrase desconocida (no usar)
- `gh` CLI en `C:\Program Files\GitHub CLI\gh.exe` (no está en PATH de Bash, usar desde PowerShell con PATH refreshado)

## Stack desplegado (Django — activo desde 2026-10-20)
- **Django 5 + Django Ninja** + Gunicorn/Uvicorn workers → puerto 8000 interno
- Postgres 16-alpine → volumen `pgdata`
- Caddy 2 → HTTPS automático vía sslip.io
- fail2ban (jail sshd), swap 2GB (swappiness 10)
- Superusuario admin: usuario `admin`. La contraseña NO se guarda aquí (estuvo expuesta en el repo público y debe rotarse); está en el gestor de contraseñas de Leonardo.

## Django apps
- `usuarios` — Usuario(AbstractUser) + rol (administrador/gerente/asesor)
- `proyectos` — ProyectoConfig (tasas, topes, método, activo) — PORTAL de proyectos en /config/ y /admin/
- `solicitudes` — Solicitud (token_comprador, estados, firma electrónica, aprobación)

## API endpoints (Django Ninja en /api/)
- `GET /api/proyectos?todos=true` — lista proyectos (todos=true incluye inactivos, para /config/)
- `PATCH /api/proyectos/{id}` — actualiza config de un proyecto (tasas, topes, método, conceptos)
- `GET /api/negocios?proyecto_id=N` — proxy a IngeMAX
- `GET /api/negocio/{id_venta}?proyecto_id=N` — proxy a IngeMAX
- `POST /api/evaluar` — motor de cálculo server-side
- `GET /api/health`

## IngeMAX API
- Base URL: https://comercial-vyp.gerpro.co/api/
- Token: en `/opt/replantea/.env` (permisos 600), NUNCA en repo
- Token actual EXPUESTO en chat — rotar antes de producción
- Proyecto 1 (IngeMAX) = "Pruebas" → ProyectoConfig id=1, id_imx=1 en DB
- Negocios reales: id_venta 1974 (T1-602), 16 (T1-802), 13 (T1-801) y más
- Campo `inmueble` SÍ viene en respuesta (ej. "T1 - 602")
- `fecha_credito` casi siempre vacía — fallback a última fecha de plan_pagos
- Campos mora por cuota: `int_mora`, `int_aplicado` (1.0 = condonada)

## Motor de cálculo — reglas implementadas (2026-10-21)
- `engine/engine.py` — porta fiel de engine.js (days360 US/NASD, liquidacion, vpn, evaluar)
- `analizar(n)` en JS: calcula `pend`, `base`, `credito`, `fechaCredito`, `vencido`, `mora`, `saldo`
  - `base` incluye crédito en su fecha → motor ve CI + crédito para calcular descuento correcto
  - `mora`: int_aplicado=1 → condonada (0); int_aplicado=0 → suma int_mora; int_aplicado>1 → resta parcial
- `initPropuesta(a)`: inicializa la propuesta según estado del negocio:
  - Sin mora: plan futuro en fechas originales
  - En mora + cuotas futuras: primera cuota futura absorbe todo el saldo vencido (fijo=true), resto intacto
  - Todo vencido: un pago único en CORTE
- `calc(s)`: propMotor = propuesta CI + crédito reducido (`nuevoCred`) → motor ve efecto del excedente
- `rebalancear(s)`: saldo = max(0, a.saldo - totFijos) — nunca cuotas negativas

## Frontend (prototipo) — estado al 2026-10-21
- `prototipo/replantea.html` — SPA HTML+JS, 3 vistas: Asesor / Comprador / Aprobación
- `prototipo/config.html` — panel de configuración de proyectos para gerente (en /config/)
- Tabla unificada: plan vigente izq (read-only) + propuesta der (editable), fila a fila
  - Cuotas vencidas: izq en rojo, der en blanco (no editables)
  - Cuotas futuras: pareadas por índice
  - Fila "Crédito hipotecario" al pie: bloqueada, muestra nuevoCred auto-calculado
- Excedente sobre cuota inicial: alerta ámbar + reduce crédito hipotecario + motor recalcula
- localStorage key: `'replantea.v3'`

## Pendientes inmediatos
- Rotar token IngeMAX antes de producción
- Agregar autenticación JWT a los endpoints del API (proteger /config/ para gerente)
- Endpoint Django `GET /comprador/<token>/` para que compradores accedan a su solicitud
- Firma electrónica: OTP por correo real (Brevo), PDF, log de auditoría
- Probar flujo completo con T1-602 en mora (9 cuotas vencidas nov2025-jul2026)

**Why:** Django reemplazó FastAPI el 2026-10-20. Motor y UI evolucionaron el 2026-10-21.
**How to apply:** Usar `id_replantea` para SSH. Para gh CLI, refrescar PATH en PowerShell primero.
