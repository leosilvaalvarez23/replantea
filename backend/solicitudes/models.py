import secrets
import uuid

from django.db import models
from django.utils import timezone


def _token():
    return secrets.token_urlsafe(32)


def _vence_en():
    from datetime import timedelta
    return timezone.now() + timedelta(days=7)


class Solicitud(models.Model):
    ESTADO_CHOICES = [
        ("borrador", "Borrador"),
        ("pendiente_firma", "Pendiente firma"),
        ("firmada", "Firmada"),
        ("pendiente_aprobacion", "Pendiente aprobación"),
        ("aprobada", "Aprobada"),
        ("rechazada", "Rechazada"),
        ("cargada", "Cargada en IngeMAX"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    token_comprador = models.CharField(
        max_length=64, unique=True, db_index=True, default=_token
    )
    proyecto = models.ForeignKey(
        "proyectos.ProyectoConfig", on_delete=models.PROTECT, related_name="solicitudes"
    )
    id_venta = models.IntegerField(verbose_name="ID venta IngeMAX")
    asesor = models.ForeignKey(
        "usuarios.Usuario", on_delete=models.PROTECT, related_name="solicitudes"
    )
    estado = models.CharField(max_length=30, choices=ESTADO_CHOICES, default="borrador")

    # Plan de pagos (listas de {fecha, valor})
    plan_pactado = models.JSONField(default=list)
    recaudo = models.JSONField(default=list)
    plan_propuesto = models.JSONField(default=list)

    # Resultado del motor
    ajuste_calculado = models.FloatField(null=True, blank=True)
    ajuste_final = models.FloatField(null=True, blank=True)
    topado = models.BooleanField(null=True, blank=True)
    requiere_aprobacion = models.BooleanField(default=False)

    # Firma electrónica
    firma_nombre = models.CharField(max_length=200, blank=True)
    firma_documento = models.CharField(max_length=50, blank=True)
    firma_ip = models.GenericIPAddressField(null=True, blank=True)
    firma_hash = models.CharField(max_length=64, blank=True)
    firmada_en = models.DateTimeField(null=True, blank=True)

    # Aprobación
    aprobada_por = models.ForeignKey(
        "usuarios.Usuario",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="aprobaciones",
    )
    aprobada_en = models.DateTimeField(null=True, blank=True)

    creada_en = models.DateTimeField(auto_now_add=True)
    vence_en = models.DateTimeField(default=_vence_en)

    @property
    def activa(self) -> bool:
        cerrada = {"firmada", "aprobada", "rechazada", "cargada"}
        return self.estado not in cerrada and timezone.now() < self.vence_en

    class Meta:
        verbose_name = "Solicitud"
        verbose_name_plural = "Solicitudes"
        ordering = ["-creada_en"]

    def __str__(self):
        return f"Solicitud {self.id_venta} [{self.estado}] {self.creada_en:%Y-%m-%d}"
