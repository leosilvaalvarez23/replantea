import os

import httpx

IMX_BASE = "https://comercial-vyp.gerpro.co/api/"


def _headers() -> dict:
    token = os.environ.get("IMX_TOKEN", "")
    if not token:
        raise ValueError("IMX_TOKEN no configurado")
    return {"IMX-TOKEN": token}


def _extract_negocios(data) -> list:
    if isinstance(data, list):
        return data
    for key in ("negs", "negocios", "results", "data"):
        if key in data and isinstance(data[key], list):
            return data[key]
    return []


async def fetch_negocios(proyecto_id: int) -> list:
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(
            f"{IMX_BASE}obtener-negocios-ext/?proyecto={proyecto_id}",
            headers=_headers(),
        )
    r.raise_for_status()
    return _extract_negocios(r.json())
