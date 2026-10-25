from pathlib import Path

from django.contrib import admin
from django.http import FileResponse, Http404
from django.shortcuts import redirect
from django.urls import path

from replantea.api import api

# Pantallas de la aplicación (HTML + motor.js + imágenes)
APP = Path("/app/prototipo/v2")


def _archivo(ruta: str, **cabeceras):
    destino = (APP / ruta).resolve()
    # solo se sirve lo que está dentro de la carpeta de la aplicación
    if APP.resolve() not in destino.parents or not destino.is_file():
        raise Http404()
    respuesta = FileResponse(open(destino, "rb"))
    for k, v in cabeceras.items():
        respuesta[k.replace("_", "-")] = v
    return respuesta


def app(request, ruta):
    # las páginas cambian con cada despliegue: que el navegador las revalide
    return _archivo(ruta, Cache_Control="no-cache")


def pagina_comprador(request, token):
    # el token va en la URL: que no se filtre por la cabecera Referer
    return _archivo("comprador.html", Cache_Control="no-store", Referrer_Policy="no-referrer")


def inicio(request):
    return redirect("/app/login.html")


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", api.urls),
    path("app/<path:ruta>", app),
    path("comprador/<str:token>", pagina_comprador),
    path("", inicio),
]
