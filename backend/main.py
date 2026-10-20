"""Replantea — API backend (MVP).

Endpoints:
  GET  /api/health
  GET  /api/proyectos
  GET  /api/negocios?proyecto_id=1
  GET  /api/negocio/{id_venta}?proyecto_id=1
  POST /api/evaluar
  GET  /                  → prototipo HTML
"""
from __future__ import annotations

import os
from typing import List

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from engine.engine import ConfigProyecto, evaluar

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

IMX_BASE = "https://comercial-vyp.gerpro.co/api/"
IMX_TOKEN = os.environ.get("IMX_TOKEN", "")

PROYECTOS: dict[int, dict] = {
    1: {
        "id": 1,
        "nombre": "Pruebas · IngeMAX VyP",
        "cfg": ConfigProyecto(
            metodo="liquidacion",
            tasa_cia=0.006,
            tasa_cliente=0.024,
            tasa_vpn=0.01,
            tope_pct=0.03,
            umbral_pct=0.015,
            cuota_min=1_000_000,
            concepto="Descuento financiero plan de pagos",
            concepto_abono="Recursos Propios",
        ),
    }
}

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="Replantea API", version="0.1.0", docs_url="/api/docs")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _imx_headers() -> dict:
    if not IMX_TOKEN:
        raise HTTPException(status_code=503, detail="IMX_TOKEN no configurado en el servidor")
    return {"IMX-TOKEN": IMX_TOKEN}


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------


@app.get("/api/health")
def health():
    return {"status": "ok", "version": "0.1.0", "imx_token_set": bool(IMX_TOKEN)}


@app.get("/api/proyectos")
def get_proyectos():
    return [
        {
            "id": p["id"],
            "nombre": p["nombre"],
            "metodo": p["cfg"].metodo,
            "tasa_cia": p["cfg"].tasa_cia,
            "tasa_cliente": p["cfg"].tasa_cliente,
            "tope_pct": p["cfg"].tope_pct,
            "umbral_pct": p["cfg"].umbral_pct,
            "cuota_min": p["cfg"].cuota_min,
        }
        for p in PROYECTOS.values()
    ]


@app.get("/api/negocios")
async def get_negocios(proyecto_id: int = 1):
    headers = _imx_headers()
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(
            f"{IMX_BASE}obtener-negocios-ext/?proyecto={proyecto_id}",
            headers=headers,
        )
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=f"IngeMAX: {r.text[:200]}")
    return r.json()


@app.get("/api/negocio/{id_venta}")
async def get_negocio(id_venta: int, proyecto_id: int = 1):
    data = await get_negocios(proyecto_id)
    negocios = data if isinstance(data, list) else data.get("negocios", data.get("results", []))
    for n in negocios:
        if n.get("id_venta") == id_venta or n.get("id") == id_venta:
            return n
    raise HTTPException(status_code=404, detail=f"Negocio {id_venta} no encontrado en proyecto {proyecto_id}")


# ---------------------------------------------------------------------------
# Motor de cálculo
# ---------------------------------------------------------------------------


class PagoIn(BaseModel):
    fecha: str
    valor: float


class EvaluarRequest(BaseModel):
    pactado: List[PagoIn]
    recaudo: List[PagoIn] = []
    propuesta: List[PagoIn]
    proyecto_id: int = 1
    valor_venta: float


@app.post("/api/evaluar")
def evaluar_propuesta(req: EvaluarRequest):
    proyecto = PROYECTOS.get(req.proyecto_id)
    if not proyecto:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")
    cfg: ConfigProyecto = proyecto["cfg"]
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


# ---------------------------------------------------------------------------
# Sirve el prototipo estático en /
# ---------------------------------------------------------------------------

_PROTO = "/app/prototipo"

@app.get("/", include_in_schema=False)
def index():
    return FileResponse(f"{_PROTO}/replantea.html")


app.mount("/static", StaticFiles(directory=_PROTO), name="static")
