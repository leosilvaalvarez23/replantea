# Replantea — contexto del proyecto

App web para que los compradores de proyectos de vivienda **modifiquen su plan de pagos**, vean el **descuento** (si adelantan) o el **cargo financiero** (si aplazan), **firmen electrónicamente** y la constructora apruebe y cargue el nuevo plan en **IngeMAX**.

- Cliente inicial: **Viviendas y Proyectos (VyP)**, que usa IngeMAX Gestión Comercial (GERPRO).
- Dueño del proyecto: Leonardo Silva (consultoría). Comunicación en español, directa y estructurada.
- Reemplaza un Excel manual del cliente (`Plantilla_Liquidacion_Interes_Clientes.xlsx`).
- Prototipo funcional publicado como artifact de claude.ai ("Replantea Plan de Pagos"); el HTML está en `prototipo/replantea.html`.

## 1. API de IngeMAX (verificada en vivo)

- Base URL VyP: `https://comercial-vyp.gerpro.co/api/`
- Autenticación: header `IMX-TOKEN: <token>`. Sin token → `403 "Token error"`. **No hay restricción por IP** (probado desde el servidor de Hetzner → HTTP 200).
- El token **nunca** va en el repositorio ni en el navegador: solo en `.env` del servidor (permisos 600). El token usado en pruebas quedó expuesto en un chat: **hay que rotarlo** antes de producción.

| Endpoint | Método | Notas |
|---|---|---|
| `obtener-proyectos-ext/` | GET | 20 proyectos. ID 1 = "Pruebas" |
| `obtener-inmuebles-ext/?proyecto=ID` | GET | |
| `obtener-cliente-ext/?documento=X` | GET | |
| `obtener-negocios-ext/?proyecto=ID` | GET | Clave: `plan_pagos`, `recaudo`, `valor_venta`, `valor_credito` |
| `crear-cliente-ext/` | POST | Solo leads |
| `crear-negocio-ext/` | POST | Crea negocio nuevo. **No sirve para modificar** |

**No existe endpoint para modificar un negocio ni su plan de pagos.** El asesor carga el plan aprobado manualmente en IngeMAX; la app luego verifica contra el API que coincida. Pendiente preguntar a GERPRO si hay endpoint de actualización y si pueden exponer la tasa del proyecto.

### Hallazgos no documentados del API
- Cada cuota de `plan_pagos` trae: `fecha_pp`, `concepto`, `valor`, **`int_mora`** (mora causada), **`int_desc`** (descuento pronto pago), **`int_aplicado`** (mora ya cobrada).
- Mora pendiente de un negocio = Σ(`int_mora` − `int_aplicado`).
- `plan_pagos` = **solo cuota inicial**. El crédito va aparte en `valor_credito` (`fecha_credito` casi siempre vacía). Verificado: Σ plan_pagos + valor_credito = valor_venta.
- `fecha_escrituracion_programada` / `fecha_entrega_programada` vienen como `1900-01-01` = sin definir. Fallback: fecha de la última cuota.
- Conceptos reales: "Recursos Propios", "Cesantias", "Reformas". Al cargar en IngeMAX los conceptos deben coincidir exactamente.
- `recaudo` trae solo `fecha`, `valor`, `concepto` (no separa interés de capital).
- Negocio de referencia: **#1974** (proyecto 1, T1-602): venta 487,5 M, crédito 341,25 M, recaudo 60,4 M, mora pendiente ≈ 5,29 M. Rareza: `fecha_venta` 2026-07-24 pero plan arranca 2025-11-28 (probablemente datos de prueba; Leonardo lo está validando).

### Reglas de IngeMAX confirmadas por Leonardo
1. La tasa (mora/descuento) se define **por proyecto**, es fija y se cambia manualmente en IngeMAX.
2. La mora la calcula el sistema desde la fecha de pago pactada + un **gap (días de gracia)** configurado manualmente.
3. Los pagos se aplican **primero a intereses y luego a capital**.
4. Tasa de mora inferida en "Pruebas": ≈ 2,4 % mensual simple (inferencia, no confirmada).

## 2. Reglas de negocio de la app

- **Métodos de cálculo, seleccionables por proyecto:**
  - *Liquidación de saldo* (réplica exacta del Excel del cliente): interés simple sobre saldo de capital, DAYS360 (US/NASD), tasa A para adelantos (saldo < 0), tasa B para atrasos (saldo ≥ 0). Validado al peso contra el Excel: −6.925.145,36.
  - *VPN*: tasa fija mensual compuesta por proyecto; diferencia expresada a la fecha del último pago. (Preferencia inicial de Leonardo.)
- **El ajuste es general al plan** (premia adelantos, castiga retrasos); va como línea aparte con concepto configurable ("Descuento financiero plan de pagos").
- **Los descuentos se calculan sobre lo pendiente por pagar.** Base de comparación = cuotas pendientes (FIFO contra recaudo), con las vencidas llevadas a la fecha de corte. La mora ya causada la liquida IngeMAX y se muestra aparte (no se cobra dos veces).
- **Si la propuesta paga más que la cuota inicial pendiente, el excedente se descuenta del crédito.** Mostrar crédito original vs nuevo y advertir que debe informarse al banco. Pendiente verificar cuál es el crédito exacto en cada negocio.
- Se debe **exponer lo pagado y lo pendiente por pagar**.
- Tope de descuento (% del valor de venta) por proyecto; umbral sobre el cual aprueba gerencia.
- Validaciones de la propuesta: suma = saldo pendiente; ninguna fecha < hoy; ninguna > fecha límite; cuota mínima por proyecto (salvo abonos); crédito no editable.
- **Portal de proyectos** obligatorio: como el API no expone la tasa, la política de cada proyecto (método, tasas, días de gracia, tope, umbral, conceptos, cuota mínima) se administra en la app.
- Firma electrónica **propia**: OTP por correo + PDF + hash SHA-256 + IP/fecha + log de auditoría (Ley 527/1999, Decreto 2364/2012). Autorización de datos (Ley 1581).
- Flujo: asesor genera link (un solo uso, vence en 7 días) → comprador modela y firma → si supera umbral, aprueba gerencia → asesor carga en IngeMAX → app verifica contra API.

## 3. Arquitectura decidida

- Backend **Django + Django Ninja** (requirements pide `>=5.1`; hoy corre 6.1) (endpoints JSON) + **PostgreSQL** propio + frontend a partir del prototipo.
- **Por qué Django Ninja y no FastAPI o DRF:**
  - Django Admin integrado = portal de proyectos (tasas, topes) y gestión de usuarios/roles sin construir UI adicional.
  - Django ya lo usa Ágora → mismo stack, misma experiencia operativa.
  - Django Ninja da la misma ergonomía de FastAPI (Pydantic, type hints, OpenAPI) dentro del ecosistema Django.
- Docker Compose en `/opt/replantea` del servidor existente.
- Correo: Brevo (producción). En pruebas el OTP se muestra en pantalla.
- Motor de cálculo: módulo Python independiente (`engine/`) con sus 14 pruebas. No depende de Django.
- **Estructura del backend (`backend/`):**
  - `replantea/` — configuración Django (settings, urls, wsgi)
  - `usuarios/` — app: modelo Usuario (AbstractUser + rol fijo), admin configurado
  - `proyectos/` — app: ProyectoConfig (tasas, topes, método, activo), admin = portal de proyectos
  - `solicitudes/` — app: Solicitud + link de comprador + firma electrónica
  - `imx_client.py` — proxy al API de IngeMAX (token solo en servidor)
  - `api.py` — endpoints Django Ninja: `/api/imx/`, `/api/evaluar/`, `/api/comprador/<token>/`
- **Roles fijos** (sin UI de gestión; se ajustan por Django Admin si se requiere):
  - `administrador` — acceso total
  - `gerente` — aprueba solicitudes que superan el umbral
  - `asesor` — crea solicitudes, genera links para compradores
- **Link del comprador:** reutilizable (no de un solo uso), se cierra cuando el plan queda firmado o vence el plazo.

## 4a. Servidor de PRUEBAS de Replantea (dedicado)

- Hetzner **CX23** `replantea-test`, Nuremberg, Ubuntu 26.04, 2 vCPU, 4 GB RAM, 40 GB. IP **2.31.84.237**.
- Firewall Hetzner `replantea-fw`: entrada TCP 22/80/443 + ICMP; salida libre. (También aplicado al servidor de Ágora.)
- Llaves SSH: `mi-pc` y `Comercial2`. Llave operativa desde este PC: `~/.ssh/id_replantea` (sin passphrase).
- Stack: **Caddy** (HTTPS automático) + Django/Gunicorn + PostgreSQL en Docker Compose, todo en `/opt/replantea`.
- URL de pruebas: **https://replantea.2-31-84-237.sslip.io**
- Decisión: validar aquí; al final decidir si producción queda en servidor propio para VyP o integrada al de Ágora.

## 4b. Servidor de Ágora (Hetzner) — referencia si Replantea se integra ahí

- Hetzner CPX22, `ubuntu-4gb-nbg1-1`, IP **195.201.148.235**, Ubuntu 26.04, 2 vCPU, 3,7 GB RAM, 75 GB disco.
- Ya corre **Ágora** (stack `comercial_*`): Django `comercial_web`, `comercial_celery`, `comercial_celery_reportes`, `comercial_redis`, `comercial_db` (MySQL 5.7), `comercial_nginx` (dueño de 80/443), `comercial_certbot`.
- Nginx de Ágora: configs en host `/app/nginx/conf.d/` (montado en `/etc/nginx/conf.d`). Solo carga `*.conf`. Archivo de Ágora: `comercial.conf`. **No tocarlo.**
- Certbot: `/app/certbot/conf` → `/etc/letsencrypt`, webroot `/app/certbot/www` → `/var/www/certbot`.
- Redes Docker del Nginx: `app_frontend` (Nginx + web) y `app_backend` (MySQL/Redis/Celery).
- **Integración de Replantea:**
  - `replantea_api` se une a `app_frontend` (externa). **Nunca** a `app_backend`.
  - `replantea_db` (Postgres) en red privada propia `replantea_db`.
  - `mem_limit`: api 512m, db 256m. Contenedores sin root, sin socket de Docker.
  - Publicar agregando `/app/nginx/conf.d/replantea.conf` + `nginx -s reload` dentro de `comercial_nginx`.
  - Certificado con el certbot existente (webroot).
- (Si se integra aquí, dominio provisional sería `replantea.195-201-148-235.sslip.io`.)
- Mantenimiento hecho el 2026-10-20:
  - `docker builder prune -f` liberó 34,9 GB (disco 72 % → 27 %).
  - Swap de 2 GB creado (`/swapfile`, swappiness 10, persistente).
  - SSH endurecido: `/etc/ssh/sshd_config.d/00-seguridad.conf` (sin contraseña, root solo con llave). Verificar que el acceso con llave funciona antes de cerrar sesiones.
- Pendientes de seguridad: instalar **fail2ban**; revisar **Firewall de Hetzner** (solo 22/80/443); activar **Backups de Hetzner**; autenticación básica en Nginx para el ambiente de pruebas.

## 5. Hecho / Pendientes

### Completado
- [x] Repositorio GitHub `replantea` → `github.com/leosilvaalvarez23/replantea`. **Es PÚBLICO** (el CLAUDE.md anterior decía privado). No versionar secretos; la contraseña de `admin` estuvo publicada en el historial y debe rotarse.
- [x] Motor `engine/engine.py` (14 tests) + análisis y validación `engine/analisis.py` (25 tests): FIFO, mora, vencido, crédito, excedente al crédito, validaciones. El servidor recalcula todo; el navegador nunca es la fuente de verdad.
- [x] Backend Django + Ninja: apps `usuarios`, `proyectos`, `solicitudes`; **autenticación por sesión de Django** (cookie + CSRF, mismo dominio) con roles fijos; API de solicitudes, comprador por token, aprobaciones y proyectos. 35 tests de API.
- [x] Diseño del frontend (prototipos con datos de demostración) en `prototipo/v2/`: simulador del comprador, bandeja y detalle del asesor, portal de proyectos y aprobaciones de gerencia.
- [x] Servidor pruebas: Docker, swap 2 GB, fail2ban, SSH solo llave.

### Cómo se prueba
- Motor: `pytest engine/` (desde la raíz, con `PYTHONPATH=.`).
- API: `cd backend && python manage.py test` (sqlite; IngeMAX y el correo se simulan).
- En un PC sin Python se verificó ejecutando Python en el navegador con Pyodide (solo pruebas).

### API (`/api/`)
- Sesión: `GET auth/csrf`, `POST auth/login`, `POST auth/logout`, `GET auth/yo`. Las peticiones que modifican datos envían `X-CSRFToken`.
- Asesor/gerente: `solicitudes` (listar, crear, `/{id}`, `enviar`, `reabrir`, `cargada`, `verificar`), `solicitudes/negocios/buscar`.
- Gerente: `solicitudes/{id}/aprobar`, `solicitudes/{id}/devolver`, `PATCH proyectos/{id}`.
- Comprador (sin sesión, por token): `comprador/{token}`, `/evaluar`, `/codigo`, `/firmar`. Las tasas nunca salen del servidor.
- Estados: `borrador → pendiente_firma → (pendiente_aprobacion) → firmada/aprobada → cargada → verificada`; `rechazada` = devuelta por gerencia. Vencida = `pendiente_firma` con link vencido (7 días).

### Próximos pasos
- [ ] **Rotar la contraseña de `admin`** en el servidor (estuvo en el repo público) y el token de IngeMAX antes de producción
- [ ] Conectar las pantallas de `prototipo/v2/` a la API (hoy usan datos de demostración): página de login, comprador, asesor, proyectos, aprobaciones
- [ ] Desplegar y probar el flujo completo en el servidor de pruebas (las pantallas viejas `prototipo/replantea.html` y `config.html` ya no se sirven)
- [ ] Correo real del OTP (Brevo/SMTP): en pruebas se muestra en pantalla (`OTP_MOSTRAR=1`); en producción `OTP_MOSTRAR=0`
- [ ] PDF de la propuesta firmada; log de auditoría
- [ ] Con VyP: tasas por proyecto, días de gracia (los define IngeMAX), conceptos exactos (¿el cargo usa el mismo concepto del descuento?), usuarios, textos legales
- [ ] Con GERPRO: ¿endpoint para modificar pagos pactados? ¿exponer la tasa del proyecto? ¿el negocio trae el correo del cliente?
- [ ] Verificar cómo representa IngeMAX la línea de ajuste (signo y concepto) para afinar `verificar`

## 6. Comercial (propuesta preliminar)
- Implementación: COP 18–25 M. Suscripción: COP 1,2–1,8 M/mes por empresa (hasta 5 proyectos) o COP 350–500 mil por proyecto activo/mes.
