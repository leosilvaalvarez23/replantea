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


def fetch_negocios(proyecto_id: int) -> list:
    """Negocios de un proyecto de IngeMAX. Síncrono: Ninja lo ejecuta en un hilo."""
    with httpx.Client(timeout=20) as client:
        r = client.get(
            f"{IMX_BASE}obtener-negocios-ext/?proyecto={proyecto_id}",
            headers=_headers(),
        )
    r.raise_for_status()
    return _extract_negocios(r.json())


def fetch_negocio(proyecto_id: int, id_venta: int):
    """Un negocio por id de venta, o None si no existe."""
    for n in fetch_negocios(proyecto_id):
        if n.get("id_venta") == id_venta or n.get("id") == id_venta:
            return n
    return None
