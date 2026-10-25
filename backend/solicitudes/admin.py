from django.contrib import admin

from .models import Solicitud


@admin.register(Solicitud)
class SolicitudAdmin(admin.ModelAdmin):
    list_display = ("id_venta", "inmueble", "proyecto", "asesor", "estado", "requiere_aprobacion", "creada_en", "vence_en")
    list_filter = ("estado", "proyecto", "requiere_aprobacion")
    search_fields = ("inmueble", "comprador_nombre", "comprador_documento", "id_venta")
    readonly_fields = (
        "id", "token_comprador", "creada_en", "enviada_en", "cargada_en", "verificada_en",
        "firma_hash", "firma_doc", "firmada_en", "firma_ip",
        "ajuste_calculado", "ajuste_final", "topado", "nuevo_credito",
        "otp_vence", "otp_intentos",
    )
    # El código de firma (otp_hash) no se muestra ni se edita desde el admin
    exclude = ("otp_hash",)
    fieldsets = (
        (None, {"fields": ("id", "token_comprador", "proyecto", "id_venta", "inmueble", "asesor", "estado", "vence_en")}),
        ("Comprador", {"fields": ("comprador_nombre", "comprador_documento", "comprador_correo")}),
        ("Negocio", {"fields": ("valor_venta", "valor_credito", "nuevo_credito", "negocio"), "classes": ("collapse",)}),
        ("Plan de pagos", {"fields": ("plan_pactado", "recaudo", "plan_propuesto"), "classes": ("collapse",)}),
        ("Resultado", {"fields": ("ajuste_calculado", "ajuste_final", "topado", "requiere_aprobacion")}),
        ("Firma", {"fields": ("firma_nombre", "firma_documento", "firma_ip", "firma_hash", "firma_doc", "firmada_en", "otp_vence", "otp_intentos")}),
        ("Decisión de gerencia", {"fields": ("aprobada_por", "aprobada_en", "decision_comentario")}),
        ("Seguimiento", {"fields": ("creada_en", "enviada_en", "cargada_en", "verificada_en")}),
    )
