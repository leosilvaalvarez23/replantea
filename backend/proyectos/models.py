from django.db import models


class ProyectoConfig(models.Model):
    METODO_CHOICES = [
        ("liquidacion", "Liquidación de saldo"),
        ("vpn", "VPN"),
    ]

    id_imx = models.IntegerField(unique=True, null=True, blank=True, verbose_name="ID IngeMAX")
    nombre = models.CharField(max_length=200)
    metodo = models.CharField(max_length=20, choices=METODO_CHOICES, default="liquidacion")
    tasa_cia = models.FloatField(default=0.006, verbose_name="Tasa compañía (MV)")
    tasa_cliente = models.FloatField(default=0.024, verbose_name="Tasa cliente (MV)")
    tasa_vpn = models.FloatField(default=0.01, verbose_name="Tasa VPN (MV)")
    tope_pct = models.FloatField(default=0.03, verbose_name="Tope descuento (%)")
    umbral_pct = models.FloatField(default=0.015, verbose_name="Umbral aprobación (%)")
    cuota_min = models.BigIntegerField(default=1_000_000, verbose_name="Cuota mínima (COP)")
    concepto = models.CharField(
        max_length=100,
        default="Descuento financiero plan de pagos",
        verbose_name="Concepto ajuste",
    )
    concepto_abono = models.CharField(
        max_length=100,
        default="Recursos Propios",
        verbose_name="Concepto abono",
    )
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Proyecto"
        verbose_name_plural = "Proyectos"
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre
