"""Autenticación por sesión de Django con roles fijos.

Los roles (administrador, gerente, asesor) viven en `Usuario.rol`. El
administrador pasa siempre. Si la sesión no existe o el rol no alcanza, la
API responde 401; si falta el token CSRF en una petición que modifica datos,
403.
"""
from ninja.security import SessionAuth


class AuthRol(SessionAuth):
    """Exige sesión iniciada y, si se indican roles, que el usuario tenga uno de ellos."""

    def __init__(self, *roles: str):
        super().__init__()          # csrf=True: las peticiones POST/PATCH/PUT/DELETE exigen X-CSRFToken
        self.roles = set(roles)

    def authenticate(self, request, key):
        user = super().authenticate(request, key)
        if user is None or not user.is_active:
            return None
        if not self.roles or user.rol == "administrador" or user.rol in self.roles:
            return user
        return None


# Atajos de uso común
cualquier_usuario = AuthRol()
asesor_o_gerente = AuthRol("asesor", "gerente")
solo_gerente = AuthRol("gerente")
