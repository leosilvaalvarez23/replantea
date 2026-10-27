"""Endpoints de solicitudes.

  /api/solicitudes/...   asesores y gerentes (sesión iniciada, con roles)
  /api/comprador/...     el comprador, sin sesión: entra con el token de su link
"""
import ipaddress
from typing import List, Optional

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.utils import timezone
from ninja import Router, Schema
from ninja.errors import HttpError

import imx_client
from proyectos.models import ProyectoConfig
from replantea.auth import asesor_o_gerente, solo_gerente

from . import servicios as sv
from .models import Solicitud

router = Router(tags=["solicitudes"], auth=asesor_o_gerente)
comprador = Router(tags=["comprador"])      # sin sesión: acceso por token


# ---------------------------------------------------------------------------
# Esquemas
# ---------------------------------------------------------------------------

class CrearIn(Schema):
    proyecto_id: int
    id_venta: int
    correo: str = ""


class DevolverIn(Schema):
    comentario: str


class CuotaIn(Schema):
    fecha: str
    valor: float
    concepto: str = ""
    abono: bool = False
    fijo: bool = False
    orig: Optional[float] = None
    orig_fecha: Optional[str] = None


class PropuestaIn(Schema):
    propuesta: List[CuotaIn]


class FirmaIn(Schema):
    codigo: str
    acepta: bool


class RechazoIn(Schema):
    observacion: str


# ---------------------------------------------------------------------------
# Serialización
# ---------------------------------------------------------------------------

def _iso(dt):
    return timezone.localtime(dt).isoformat() if dt else None


def _dia(dt):
    return timezone.localtime(dt).date().isoformat()


def _eventos(s: Solicitud) -> list:
    aprobada_ok = s.aprobada_por_id and s.estado != "rechazada"
    pares = [
        ("creada", s.creada_en),
        ("enviada", s.enviada_en),
        ("aprobada", s.aprobada_en if aprobada_ok else None),
        ("devuelta", s.aprobada_en if s.estado == "rechazada" else None),
        ("firmada", s.firmada_en),
        ("cargada", s.cargada_en),
        ("verificada", s.verificada_en),
    ]
    return [{"t": t, "fecha": _dia(f)} for t, f in pares if f]


def _resumen(s: Solicitud) -> dict:
    if s.firmada_en:
        ajuste, requiere = s.ajuste_final, s.requiere_aprobacion
    else:
        _, r = sv.evaluar(s, s.plan_propuesto)
        ajuste, requiere = r.ev.ajuste, r.ev.requiere_aprobacion
    return {
        "id": str(s.id), "id_venta": s.id_venta, "estado": s.estado, "estado_ui": sv.estado_ui(s),
        "inmueble": s.inmueble,
        "proyecto": {"id": s.proyecto_id, "nombre": s.proyecto.nombre},
        "comprador": {"nombre": s.comprador_nombre, "documento": s.comprador_documento, "correo": s.comprador_correo},
        "asesor": s.asesor.get_full_name() or s.asesor.username,
        "ajuste": ajuste, "requiere_aprobacion": requiere,
        "creada_en": _iso(s.creada_en),
        "vence_en": _iso(s.vence_en) if s.estado == "pendiente_firma" else None,
        "firmada_en": _iso(s.firmada_en),
    }


def _detalle(s: Solicitud) -> dict:
    a, r = sv.evaluar(s, s.plan_propuesto)
    decision = None
    if s.estado in ("aprobada", "rechazada", "pendiente_firma", "firmada",
                    "rechazada_comprador", "cargada", "verificada") and s.aprobada_por_id:
        decision = {
            "por": s.aprobada_por.get_full_name() or s.aprobada_por.username,
            "fecha": _dia(s.aprobada_en), "comentario": s.decision_comentario,
        }
    firma = None
    if s.firmada_en:
        firma = {
            "nombre": s.firma_nombre, "documento": s.firma_documento, "ip": s.firma_ip,
            "hash": s.firma_hash, "fecha": _iso(s.firmada_en),
        }
    rechazo = None
    if s.estado == "rechazada_comprador":
        rechazo = {"observacion": s.rechazo_observacion}

    return {
        **_resumen(s),
        "valor_venta": s.valor_venta, "valor_credito": s.valor_credito, "nuevo_credito": r.nuevo_cred,
        "umbral": round(s.valor_venta * s.proyecto.umbral_pct),
        "analisis": sv.analisis_a_dict(a), "propuesta": s.plan_propuesto, "resultado": sv.resultado_a_dict(r),
        "reglas": {
            "cuota_min": s.proyecto.cuota_min, "concepto_abono": s.proyecto.concepto_abono,
            "fecha_limite": a.fecha_limite, "hoy": sv.hoy(),
        },
        "eventos": _eventos(s), "firma": firma, "decision": decision, "rechazo": rechazo,
        "lineas_carga": sv.lineas_carga(s),
        "link": f"/comprador/{s.token_comprador}" if s.estado == "pendiente_firma" else None,
    }


# ---------------------------------------------------------------------------
# Acceso
# ---------------------------------------------------------------------------

def _visibles(usuario):
    qs = Solicitud.objects.select_related("proyecto", "asesor", "aprobada_por")
    return qs if usuario.rol in ("gerente", "administrador") else qs.filter(asesor=usuario)


def _obtener(request, solicitud_id: str) -> Solicitud:
    try:
        return _visibles(request.auth).get(pk=solicitud_id)
    except (Solicitud.DoesNotExist, ValidationError, ValueError):
        raise HttpError(404, "No encontramos esa solicitud.")


def _imx(llamada):
    try:
        return llamada()
    except ValueError as e:
        raise HttpError(503, str(e))
    except Exception as e:
        raise HttpError(502, f"No pudimos consultar IngeMAX: {e}")


# ---------------------------------------------------------------------------
# Asesor y gerente
# ---------------------------------------------------------------------------

@router.get("/negocios/buscar")
def buscar_negocios(request, proyecto_id: int, q: str = ""):
    proyecto = ProyectoConfig.objects.filter(id=proyecto_id, activo=True).first()
    if not proyecto or not proyecto.id_imx:
        raise HttpError(404, "Proyecto no encontrado o sin ID de IngeMAX.")
    negocios = _imx(lambda: imx_client.fetch_negocios(proyecto.id_imx))
    abiertas = set(
        Solicitud.objects.filter(proyecto=proyecto)
        .exclude(estado__in=sv.ESTADOS_ABIERTOS_PARA_DUPLICADO)
        .values_list("id_venta", flat=True)
    )
    q = q.strip().lower()
    out = []
    for n in negocios:
        id_venta = n.get("id_venta") or n.get("id")
        fila = {
            "id_venta": id_venta, "inmueble": sv._texto(n, "inmueble"),
            "comprador": sv._texto(n, "cliente_negocio", "cliente", "nombre_cliente"),
            "documento": sv._texto(n, "cliente_identificacion", "documento"),
            "correo": sv._texto(n, "correo", "email", "cliente_correo"),
            "valor_venta": n.get("valor_venta") or 0, "abierta": id_venta in abiertas,
            "estado_negocio": sv._texto(n, "estado_negocio"),
        }
        if not q or q in " ".join(str(v) for v in fila.values()).lower():
            out.append(fila)
    return out[:50]


@router.get("")
def listar(request, estado_ui: str = "", q: str = ""):
    q = q.strip().lower()
    out = []
    for s in _visibles(request.auth):
        fila = _resumen(s)
        if estado_ui and fila["estado_ui"] != estado_ui:
            continue
        if q and q not in " ".join([
            fila["inmueble"], fila["comprador"]["nombre"], fila["comprador"]["documento"], fila["proyecto"]["nombre"],
        ]).lower():
            continue
        out.append(fila)
    return out


@router.post("")
def crear(request, datos: CrearIn):
    proyecto = ProyectoConfig.objects.filter(id=datos.proyecto_id, activo=True).first()
    if not proyecto or not proyecto.id_imx:
        raise HttpError(404, "Proyecto no encontrado o sin ID de IngeMAX.")
    negocio = _imx(lambda: imx_client.fetch_negocio(proyecto.id_imx, datos.id_venta))
    if negocio is None:
        raise HttpError(404, f"El negocio {datos.id_venta} no existe en el proyecto {proyecto.nombre}.")
    s = sv.crear_solicitud(request.auth, proyecto, negocio, datos.correo)
    return _detalle(_visibles(request.auth).get(pk=s.pk))


@router.get("/{solicitud_id}")
def detalle(request, solicitud_id: str):
    return _detalle(_obtener(request, solicitud_id))


@router.post("/{solicitud_id}/evaluar")
def evaluar_plan(request, solicitud_id: str, datos: PropuestaIn):
    """Evalúa una propuesta sin guardarla (para feedback en tiempo real mientras el asesor edita)."""
    s = _obtener(request, solicitud_id)
    if s.estado != "borrador":
        raise HttpError(409, "Solo se puede evaluar el plan de un borrador.")
    a = sv.analisis_de(s)
    propuesta = sv.normalizar_propuesta([c.dict() for c in datos.propuesta], a, s.proyecto)
    _, r = sv.evaluar(s, propuesta)
    return sv.resultado_a_dict(r)


@router.patch("/{solicitud_id}/plan")
def actualizar_plan(request, solicitud_id: str, datos: PropuestaIn):
    """Asesor guarda el plan propuesto (solo en borrador)."""
    s = _obtener(request, solicitud_id)
    return _detalle(sv.actualizar_plan(s, [c.dict() for c in datos.propuesta]))


@router.delete("/{solicitud_id}")
def eliminar(request, solicitud_id: str):
    s = _obtener(request, solicitud_id)
    sv.eliminar(s)
    return {"ok": True}


@router.post("/{solicitud_id}/enviar")
def enviar(request, solicitud_id: str):
    return _detalle(sv.enviar(_obtener(request, solicitud_id)))


@router.post("/{solicitud_id}/enviar_comprador")
def enviar_a_comprador(request, solicitud_id: str):
    """Asesor envía el link al comprador después de que gerencia aprobó."""
    return _detalle(sv.enviar_a_comprador(_obtener(request, solicitud_id)))


@router.post("/{solicitud_id}/reabrir")
def reabrir(request, solicitud_id: str):
    return _detalle(sv.reabrir(_obtener(request, solicitud_id)))


@router.post("/{solicitud_id}/cargada")
def cargada(request, solicitud_id: str):
    return _detalle(sv.marcar_cargada(_obtener(request, solicitud_id)))


@router.post("/{solicitud_id}/verificar")
def verificar(request, solicitud_id: str):
    s = _obtener(request, solicitud_id)
    if s.estado != "cargada":
        raise sv.ErrorNegocio(409, "Solo se verifica una solicitud ya cargada en IngeMAX.")
    negocio = _imx(lambda: imx_client.fetch_negocio(s.proyecto.id_imx, s.id_venta))
    if negocio is None:
        raise HttpError(404, "El negocio ya no aparece en IngeMAX.")
    resultado = sv.verificar(s, negocio)
    return {"verificacion": resultado, "solicitud": _detalle(s)}


@router.post("/{solicitud_id}/aprobar", auth=solo_gerente)
def aprobar(request, solicitud_id: str):
    return _detalle(sv.aprobar(_obtener(request, solicitud_id), request.auth))


@router.post("/{solicitud_id}/devolver", auth=solo_gerente)
def devolver(request, solicitud_id: str, datos: DevolverIn):
    return _detalle(sv.devolver(_obtener(request, solicitud_id), request.auth, datos.comentario))


# ---------------------------------------------------------------------------
# Comprador (por token, sin sesión)
# ---------------------------------------------------------------------------

def _ip(request) -> Optional[str]:
    crudo = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip() or request.META.get("REMOTE_ADDR", "")
    try:
        return str(ipaddress.ip_address(crudo))
    except ValueError:
        return None


def _limitar(clave: str, maximo: int, segundos: int, mensaje: str):
    cache.add(clave, 0, timeout=segundos)
    try:
        usados = cache.incr(clave)
    except ValueError:
        usados = 1
    if usados > maximo:
        raise sv.ErrorNegocio(429, mensaje)


@comprador.get("/{token}")
def ver(request, token: str):
    s = sv.solicitud_para_comprador(token)
    if sv.vencido_el_link(s):
        raise sv.ErrorNegocio(410, "Este link venció. Pídele a tu asesor uno nuevo.")
    base = {
        "estado_ui": sv.estado_ui(s), "inmueble": s.inmueble, "proyecto": s.proyecto.nombre,
        "valor_venta": s.valor_venta, "valor_credito": s.valor_credito,
        "comprador": {"nombre": s.comprador_nombre, "documento": s.comprador_documento,
                      "correo": sv.enmascarar_correo(s.comprador_correo)},
        "vence_en": _iso(s.vence_en),
    }
    if s.estado == "pendiente_firma":
        a, r = sv.evaluar(s, s.plan_propuesto)
        base.update({
            "analisis": sv.analisis_a_dict(a), "propuesta": s.plan_propuesto, "resultado": sv.resultado_a_dict(r),
        })
    elif s.estado == "rechazada_comprador":
        base["rechazo"] = {"observacion": s.rechazo_observacion}
    else:
        base["firma"] = {
            "fecha": _iso(s.firmada_en), "hash": s.firma_hash,
            "ajuste": s.ajuste_final, "requiere_aprobacion": s.requiere_aprobacion,
        }
    return base


@comprador.post("/{token}/codigo")
def codigo(request, token: str):
    s = sv.solicitud_para_comprador(token)
    _limitar(f"otp:{s.id}", 5, 3600, "Pediste demasiados códigos. Intenta de nuevo en una hora.")
    return sv.generar_codigo(s)


@comprador.post("/{token}/firmar")
def firmar(request, token: str, datos: FirmaIn):
    s = sv.solicitud_para_comprador(token)
    firmada = sv.firmar(s.id, datos.codigo, datos.acepta, _ip(request))
    return {
        "estado_ui": sv.estado_ui(firmada), "firmada_en": _iso(firmada.firmada_en),
        "hash": firmada.firma_hash, "ajuste": firmada.ajuste_final,
        "requiere_aprobacion": firmada.requiere_aprobacion,
    }


@comprador.post("/{token}/rechazar")
def rechazar(request, token: str, datos: RechazoIn):
    sv.rechazar_comprador(token, datos.observacion)
    return {"ok": True}
