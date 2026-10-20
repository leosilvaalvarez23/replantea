from django.contrib import admin
from django.http import FileResponse
from django.urls import path

from replantea.api import api


def prototipo(request):
    return FileResponse(open("/app/prototipo/replantea.html", "rb"), content_type="text/html")


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", api.urls),
    path("", prototipo),
]
