from django.contrib import admin

from .models import Solicitud


@admin.register(Solicitud)
class SolicitudAdmin(admin.ModelAdmin):
    list_display = ("id_venta", "proyecto", "asesor", "estado", "requiere_aprobacion", "creada_en", "vence_en")
    list_filter = ("estado", "proyecto", "requiere_aprobacion")
    readonly_fields = (
        "id", "token_comprador", "creada_en",
        "firma_hash", "firmada_en", "firma_ip",
        "ajuste_calculado", "ajuste_final", "topado",
    )
    fieldsets = (
        (None, {"fields": ("id", "token_comprador", "proyecto", "id_venta", "asesor", "estado", "vence_en")}),
        ("Plan de pagos", {"fields": ("plan_pactado", "recaudo", "plan_propuesto"), "classes": ("collapse",)}),
        ("Resultado", {"fields": ("ajuste_calculado", "ajuste_final", "topado", "requiere_aprobacion")}),
        ("Firma", {"fields": ("firma_nombre", "firma_documento", "firma_ip", "firma_hash", "firmada_en")}),
        ("Aprobación", {"fields": ("aprobada_por", "aprobada_en")}),
        ("Auditoría", {"fields": ("creada_en",)}),
    )
