from typing import List

from ninja import NinjaAPI, Schema
from ninja.errors import HttpError

api = NinjaAPI(title="Replantea API", version="0.1.0", docs_url="/docs")


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


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@api.get("/health")
def health(request):
    import os
    return {"status": "ok", "version": "0.2.0", "imx_token_set": bool(os.environ.get("IMX_TOKEN"))}


@api.get("/proyectos")
def get_proyectos(request):
    from proyectos.models import ProyectoConfig
    return list(
        ProyectoConfig.objects.filter(activo=True).values(
            "id", "id_imx", "nombre", "metodo",
            "tasa_cia", "tasa_cliente", "tope_pct", "umbral_pct", "cuota_min",
        )
    )


@api.get("/negocios")
async def get_negocios(request, proyecto_id: int = 1):
    from imx_client import fetch_negocios
    try:
        return await fetch_negocios(proyecto_id)
    except ValueError as e:
        raise HttpError(503, str(e))
    except Exception as e:
        raise HttpError(502, f"Error IngeMAX: {e}")


@api.get("/negocio/{id_venta}")
async def get_negocio(request, id_venta: int, proyecto_id: int = 1):
    from imx_client import fetch_negocios
    try:
        negocios = await fetch_negocios(proyecto_id)
    except ValueError as e:
        raise HttpError(503, str(e))
    for n in negocios:
        if n.get("id_venta") == id_venta or n.get("id") == id_venta:
            return n
    raise HttpError(404, f"Negocio {id_venta} no encontrado en proyecto {proyecto_id}")


@api.post("/evaluar")
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
