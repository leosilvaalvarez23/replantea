from django.contrib import admin

from .models import ProyectoConfig


@admin.register(ProyectoConfig)
class ProyectoConfigAdmin(admin.ModelAdmin):
    list_display = ("nombre", "id_imx", "metodo", "tasa_cia", "tasa_cliente", "tope_pct", "activo")
    list_filter = ("metodo", "activo")
    fieldsets = (
        (None, {"fields": ("nombre", "id_imx", "activo")}),
        ("Método de cálculo", {"fields": ("metodo",)}),
        ("Tasas", {"fields": ("tasa_cia", "tasa_cliente", "tasa_vpn")}),
        ("Límites", {"fields": ("tope_pct", "umbral_pct", "cuota_min")}),
        ("Conceptos IngeMAX", {"fields": ("concepto", "concepto_abono")}),
    )
