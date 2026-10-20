from django.contrib.auth.models import AbstractUser
from django.db import models


class Usuario(AbstractUser):
    ROL_CHOICES = [
        ("administrador", "Administrador"),
        ("gerente", "Gerente"),
        ("asesor", "Asesor"),
    ]
    rol = models.CharField(max_length=20, choices=ROL_CHOICES, default="asesor")

    class Meta:
        verbose_name = "Usuario"
        verbose_name_plural = "Usuarios"

    def __str__(self):
        return f"{self.get_full_name() or self.username} ({self.get_rol_display()})"
