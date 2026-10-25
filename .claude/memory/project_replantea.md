---
name: project-replantea
description: "Estado de Replantea al 2026-10-24: backend Django+Ninja con sesión, API completa, pantallas v2 conectadas, repo público, qué falta"
metadata:
  node_type: memory
  type: project
  originSessionId: 4060887f-1905-45a0-86e9-e48cf7458599
  modified: 2026-10-25T03:39:22.054Z
---

App web para modificar planes de pagos de vivienda (cliente inicial VyP / IngeMAX). Detalle de negocio y API en `CLAUDE.md` del repo (fuente principal; léelo primero).

## Estado (2026-10-24)
- Repo: github.com/leosilvaalvarez23/replantea, rama `main`. **Es PÚBLICO.** Hay ~8 commits locales **sin `push`** (el usuario no lo ha pedido).
- Backend Django 6.1 + Ninja: `engine/` (motor + `analisis.py`, 39 tests), `backend/` (apps usuarios, proyectos, solicitudes; **auth por sesión de Django**, roles asesor/gerente/administrador; 39 tests).
- El servidor recalcula todo (el navegador no es fuente de verdad); las tasas nunca llegan al comprador.
- Frontend en `prototipo/v2/` conectado a la API: login, comprador (`/comprador/<token>`), asesor, proyectos, aprobaciones. Se sirve desde `/app/`.
- Probado de extremo a extremo con `tools/e2e/` (Django en Pyodide, sin Python local). **No probado aún en el servidor ni con IngeMAX real.**

## Cómo verificar en este PC (no hay Python, Node ni Docker)
- `.\tools\e2e\iniciar.ps1` y abrir `http://localhost:8768/e2e.html` (flujo completo) o `unit.html` (tests). Detalle en `tools/e2e/README.md`.
- Los tests en el servidor requieren la llave SSH, que NO está en este PC.

## Servidor de pruebas
- Hetzner `replantea-test`, IP 2.31.84.237, https://replantea.2-31-84-237.sslip.io, `/opt/replantea` (Docker: Caddy + Django/Gunicorn + Postgres).
- La llave `~/.ssh/id_replantea` está en OTRO PC, no en este. Sin ella no se puede desplegar ni rotar la contraseña.
- El compose deja `OTP_MOSTRAR=1` (código en pantalla, solo pruebas). Producción: 0 + SMTP.

## Pendiente urgente / siguiente
1. **Rotar la contraseña de `admin`** (estuvo en el repo público, commit 5b7bdda; el /admin/ es público). Ya se quitó del archivo, pero sigue en el historial. No guardar contraseñas en memoria ni en el repo.
2. Desplegar (git pull + `docker compose up -d --build`) y probar en el servidor; crear usuarios asesor y gerente en /admin/.
3. Con VyP/GERPRO: cómo representa IngeMAX la línea de ajuste (signo y concepto; el cargo usa hoy el mismo concepto que el descuento), si el negocio trae el correo del comprador, días de gracia.
4. Correo real del OTP (Brevo), PDF de la propuesta firmada, log de auditoría, rotar token de IngeMAX.

**Why:** el repo es público y el servidor de pruebas está expuesto, por eso la rotación va primero.
**How to apply:** al retomar, empezar por el punto 1 y 2; antes de cualquier `push` recordar que el repo es público (ver [[feedback-trabajo-con-leonardo]]). Reglas de mora/crédito del motor en [[project-calc-mora]].
