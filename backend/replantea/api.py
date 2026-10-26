from typing import List, Optional

from django.contrib.auth import authenticate, login, logout
from django.core.cache import cache
from django.middleware.csrf import get_token
from ninja import NinjaAPI, Schema
from ninja.errors import HttpError

from replantea.auth import asesor_o_gerente, cualquier_usuario, solo_gerente
from solicitudes.api import comprador as comprador_router
from solicitudes.api import router as solicitudes_router
from solicitudes.servicios import ErrorNegocio

api = NinjaAPI(title="Replantea API", version="0.3.0", docs_url="/docs")


@api.exception_handler(ErrorNegocio)
def _error_negocio(request, exc: ErrorNegocio):
    cuerpo = {"detail": exc.mensaje}
    if exc.detalle:
        cuerpo["errores"] = exc.detalle
    return api.create_response(request, cuerpo, status=exc.status)


api.add_router("/solicitudes", solicitudes_router)
api.add_router("/comprador", comprador_router)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class PagoSchema(Schema):
    fecha: str
    valor: float


class EvaluarRequest(Schema):
    pactado: List[PagoSchema]
    recaudo: List[PagoSchema] = []
    propuesta: List[PagoSchema]
    proyecto_id: int
    valor_venta: float


class LoginIn(Schema):
    username: str
    password: str


# ---------------------------------------------------------------------------
# Sesión
# ---------------------------------------------------------------------------

LOGIN_MAX_FALLOS = 5
LOGIN_BLOQUEO_SEGUNDOS = 15 * 60


def _usuario(u) -> dict:
    return {"id": u.id, "username": u.username, "nombre": u.get_full_name() or u.username, "rol": u.rol}


@api.get("/health")
def health(request):
    return {"status": "ok", "version": "0.3.0"}


@api.get("/auth/csrf", tags=["auth"])
def csrf(request):
    """Entrega el token CSRF (y fija su cookie). El navegador lo envía en X-CSRFToken al modificar datos."""
    return {"csrf": get_token(request)}


@api.post("/auth/login", tags=["auth"])
def login_view(request, datos: LoginIn):
    ip = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip() or request.META.get("REMOTE_ADDR", "")
    clave = f"login:{ip}:{datos.username.strip().lower()}"
    if cache.get(clave, 0) >= LOGIN_MAX_FALLOS:
        raise HttpError(429, "Demasiados intentos. Espera unos minutos e inténtalo de nuevo.")
    user = authenticate(request, username=datos.username.strip(), password=datos.password)
    if user is None or not user.is_active:
        cache.add(clave, 0, timeout=LOGIN_BLOQUEO_SEGUNDOS)
        try:
            cache.incr(clave)
        except ValueError:
            cache.set(clave, 1, timeout=LOGIN_BLOQUEO_SEGUNDOS)
        raise HttpError(401, "Usuario o contraseña incorrectos.")
    cache.delete(clave)
    login(request, user)
    return _usuario(user)


@api.post("/auth/logout", auth=cualquier_usuario, tags=["auth"])
def logout_view(request):
    logout(request)
    return {"ok": True}


@api.get("/auth/yo", auth=cualquier_usuario, tags=["auth"])
def yo(request):
    return _usuario(request.auth)


# ---------------------------------------------------------------------------
# Proyectos
# ---------------------------------------------------------------------------

CAMPOS_PROYECTO = (
    "id", "id_imx", "nombre", "metodo", "tasa_cia", "tasa_cliente", "tasa_vpn",
    "tope_pct", "umbral_pct", "cuota_min", "concepto", "concepto_abono", "activo",
)


@api.get("/proyectos", auth=cualquier_usuario, tags=["proyectos"])
def get_proyectos(request, todos: bool = False):
    from proyectos.models import ProyectoConfig
    # Solo gerencia ve los inactivos; las tasas las ven asesores y gerentes (no el comprador)
    if todos and request.auth.rol not in ("gerente", "administrador"):
        raise HttpError(403, "Solo gerencia puede ver los proyectos inactivos.")
    qs = ProyectoConfig.objects.all() if todos else ProyectoConfig.objects.filter(activo=True)
    return list(qs.values(*CAMPOS_PROYECTO))


class ProyectoUpdateSchema(Schema):
    metodo: Optional[str] = None
    tasa_cia: Optional[float] = None
    tasa_cliente: Optional[float] = None
    tasa_vpn: Optional[float] = None
    tope_pct: Optional[float] = None
    umbral_pct: Optional[float] = None
    cuota_min: Optional[int] = None
    concepto: Optional[str] = None
    concepto_abono: Optional[str] = None
    activo: Optional[bool] = None


@api.post("/proyectos/sincronizar", auth=solo_gerente, tags=["proyectos"])
def sincronizar_proyectos(request):
    from proyectos.models import ProyectoConfig
    from imx_client import fetch_proyectos
    proyectos_imx = _imx(fetch_proyectos)
    nuevos = []
    for p in proyectos_imx:
        _, creado = ProyectoConfig.objects.get_or_create(
            id_imx=p["id"],
            defaults={"nombre": p["nombre_proyecto"], "activo": False},
        )
        if creado:
            nuevos.append(p["nombre_proyecto"])
    return {"sincronizados": len(proyectos_imx), "nuevos": len(nuevos), "nombres_nuevos": nuevos}


@api.patch("/proyectos/{proyecto_id}", auth=solo_gerente, tags=["proyectos"])
def update_proyecto(request, proyecto_id: int, data: ProyectoUpdateSchema):
    from proyectos.models import ProyectoConfig
    try:
        p = ProyectoConfig.objects.get(id=proyecto_id)
    except ProyectoConfig.DoesNotExist:
        raise HttpError(404, "Proyecto no encontrado")
    campos = data.dict(exclude_unset=True)

    if "metodo" in campos and campos["metodo"] not in ("liquidacion", "vpn"):
        raise HttpError(422, "Método inválido: use 'liquidacion' o 'vpn'.")
    for k in ("tasa_cia", "tasa_cliente", "tasa_vpn"):
        if k in campos and not (0 <= campos[k] <= 0.1):
            raise HttpError(422, f"{k}: debe estar entre 0 y 10 % mensual.")
    for k in ("tope_pct", "umbral_pct"):
        if k in campos and not (0 <= campos[k] <= 0.2):
            raise HttpError(422, f"{k}: debe estar entre 0 y 20 % del valor de venta.")
    if "cuota_min" in campos and campos["cuota_min"] < 0:
        raise HttpError(422, "cuota_min: no puede ser negativa.")
    for k in ("concepto", "concepto_abono"):
        if k in campos:
            campos[k] = (campos[k] or "").strip()
            if not campos[k]:
                raise HttpError(422, f"{k}: no puede quedar vacío.")
    umbral = campos.get("umbral_pct", p.umbral_pct)
    tope = campos.get("tope_pct", p.tope_pct)
    if umbral > tope:
        raise HttpError(422, "El umbral de aprobación no puede superar el tope de descuento.")

    for k, v in campos.items():
        setattr(p, k, v)
    p.save()
    return {"ok": True}


# ---------------------------------------------------------------------------
# IngeMAX (proxy; el token nunca sale del servidor)
# ---------------------------------------------------------------------------

def _imx(llamada):
    try:
        return llamada()
    except ValueError as e:
        raise HttpError(503, str(e))
    except Exception as e:
        raise HttpError(502, f"Error IngeMAX: {e}")


@api.get("/negocios", auth=asesor_o_gerente, tags=["ingemax"])
def get_negocios(request, proyecto_id: int = 1):
    from imx_client import fetch_negocios
    return _imx(lambda: fetch_negocios(proyecto_id))


@api.get("/negocio/{id_venta}", auth=asesor_o_gerente, tags=["ingemax"])
def get_negocio(request, id_venta: int, proyecto_id: int = 1):
    from imx_client import fetch_negocio
    n = _imx(lambda: fetch_negocio(proyecto_id, id_venta))
    if n is None:
        raise HttpError(404, f"Negocio {id_venta} no encontrado en proyecto {proyecto_id}")
    return n


# ---------------------------------------------------------------------------
# Motor
# ---------------------------------------------------------------------------

@api.post("/evaluar", auth=asesor_o_gerente, tags=["motor"])
def evaluar_propuesta(request, req: EvaluarRequest):
    from proyectos.models import ProyectoConfig
    from engine.engine import ConfigProyecto, evaluar

    try:
        proyecto = ProyectoConfig.objects.get(id_imx=req.proyecto_id, activo=True)
    except ProyectoConfig.DoesNotExist:
        raise HttpError(404, "Proyecto no encontrado")

    cfg = ConfigProyecto(
        metodo=proyecto.metodo,
        tasa_cia=proyecto.tasa_cia,
        tasa_cliente=proyecto.tasa_cliente,
        tasa_vpn=proyecto.tasa_vpn,
        tope_pct=proyecto.tope_pct,
        umbral_pct=proyecto.umbral_pct,
        cuota_min=proyecto.cuota_min,
        concepto=proyecto.concepto,
        concepto_abono=proyecto.concepto_abono,
    )
    pactado = [{"fecha": p.fecha, "valor": p.valor} for p in req.pactado]
    recaudo = [{"fecha": p.fecha, "valor": p.valor} for p in req.recaudo]
    propuesta = [{"fecha": p.fecha, "valor": p.valor} for p in req.propuesta]
    res = evaluar(pactado, recaudo, propuesta, cfg, req.valor_venta)
    return {
        "ajuste_calculado": res.ajuste_calculado,
        "ajuste": res.ajuste,
        "topado": res.topado,
        "tope": res.tope,
        "requiere_aprobacion": res.requiere_aprobacion,
    }
