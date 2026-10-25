"""Tests de la API de solicitudes: sesión y roles, flujo del comprador y de gerencia.

Se ejecutan con:  python manage.py test
IngeMAX se simula: no se hace ninguna llamada de red.
"""
from datetime import timedelta
from unittest import mock

from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone

from proyectos.models import ProyectoConfig
from solicitudes import servicios as sv
from solicitudes.models import Solicitud
from usuarios.models import Usuario


def _mes(i: int) -> str:
    """i=0 es el mes actual, día 28 (siempre existe)."""
    hoy = timezone.localdate()
    y, m = divmod(hoy.month - 1 + i, 12)
    return f"{hoy.year + y}-{m + 1:02d}-28"


def negocio_demo(n_cuotas=8, valor=6_000_000, pagadas=2):
    """Negocio al día: `pagadas` cuotas ya cubiertas (meses pasados) y el resto por pagar.

    Los meses van de -pagadas a -1 (siempre pasados) y de +1 en adelante (siempre futuros);
    se salta el mes actual para que el resultado no dependa del día en que corran los tests.
    """
    def mes_de(i):
        return _mes(i - pagadas + (1 if i >= pagadas else 0))

    plan = [{"fecha_pp": mes_de(i), "concepto": "Cuota inicial", "valor": valor} for i in range(n_cuotas)]
    recaudo = [{"fecha": mes_de(i), "concepto": "Recursos Propios", "valor": valor} for i in range(pagadas)]
    return {
        "id_venta": 777, "inmueble": "T9 - 101", "cliente_negocio": "Comprador de Prueba",
        "cliente_identificacion": "1000000001", "correo": "comprador@ejemplo.co",
        "valor_venta": 300_000_000, "valor_credito": 180_000_000,
        "fecha_escrituracion_programada": _mes(n_cuotas + 2),
        "plan_pagos": plan, "recaudo": recaudo,
    }


class BaseTest(TestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()                  # el bloqueo de login y el tope de códigos usan la caché
        self.proyecto = ProyectoConfig.objects.create(
            nombre="Proyecto Prueba", id_imx=99, metodo="liquidacion",
            tasa_cia=0.006, tasa_cliente=0.01, tope_pct=0.03, umbral_pct=0.0005,
            cuota_min=1_000_000, concepto="Descuento financiero plan de pagos", concepto_abono="Recursos Propios",
        )
        self.asesor = Usuario.objects.create_user("asesor1", password="clave-asesor-1", rol="asesor")
        self.otro_asesor = Usuario.objects.create_user("asesor2", password="clave-asesor-2", rol="asesor")
        self.gerente = Usuario.objects.create_user("gerente1", password="clave-gerente-1", rol="gerente")
        self.admin = Usuario.objects.create_user("admin1", password="clave-admin-1", rol="administrador")
        patcher = mock.patch("imx_client.fetch_negocio", side_effect=lambda pid, vid: negocio_demo())
        self.fetch = patcher.start()
        self.addCleanup(patcher.stop)

    def entrar(self, usuario):
        self.client.force_login(usuario)

    def crear(self, usuario=None):
        self.entrar(usuario or self.asesor)
        r = self.client.post("/api/solicitudes", {"proyecto_id": self.proyecto.id, "id_venta": 777},
                             content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()

    def enviar(self, sid):
        r = self.client.post(f"/api/solicitudes/{sid}/enviar", content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()

    def propuesta_adelantada(self, token):
        """Junta las dos últimas cuotas en la primera: paga antes -> descuento."""
        s = Solicitud.objects.get(token_comprador=token)
        p = [dict(x) for x in s.plan_propuesto]
        ultimas = p[-2:]
        p = p[:-2]
        p[0]["valor"] += sum(x["valor"] for x in ultimas)
        return p


@override_settings(OTP_MOSTRAR=True)
class SesionYRolesTest(BaseTest):
    def test_sin_sesion_todo_es_401(self):
        for url in ("/api/proyectos", "/api/solicitudes", "/api/negocios", "/api/auth/yo"):
            self.assertEqual(self.client.get(url).status_code, 401, url)

    def test_patch_proyecto_sin_sesion_es_401(self):
        r = self.client.patch(f"/api/proyectos/{self.proyecto.id}", {"tasa_cia": 0.05}, content_type="application/json")
        self.assertEqual(r.status_code, 401)
        self.proyecto.refresh_from_db()
        self.assertEqual(self.proyecto.tasa_cia, 0.006)

    def test_asesor_no_puede_editar_tasas(self):
        self.entrar(self.asesor)
        r = self.client.patch(f"/api/proyectos/{self.proyecto.id}", {"tasa_cia": 0.05}, content_type="application/json")
        self.assertEqual(r.status_code, 401)

    def test_gerente_edita_tasas_con_validacion(self):
        self.entrar(self.gerente)
        url = f"/api/proyectos/{self.proyecto.id}"
        ok = self.client.patch(url, {"tasa_cia": 0.012}, content_type="application/json")
        self.assertEqual(ok.status_code, 200)
        self.proyecto.refresh_from_db()
        self.assertEqual(self.proyecto.tasa_cia, 0.012)
        for malo in ({"tasa_cia": 0.5}, {"tasa_cia": -0.01}, {"metodo": "otro"}, {"concepto": "  "},
                     {"umbral_pct": 0.1, "tope_pct": 0.03}):
            r = self.client.patch(url, malo, content_type="application/json")
            self.assertEqual(r.status_code, 422, malo)

    def test_login_logout_y_yo(self):
        r = self.client.post("/api/auth/login", {"username": "asesor1", "password": "mala"}, content_type="application/json")
        self.assertEqual(r.status_code, 401)
        r = self.client.post("/api/auth/login", {"username": "asesor1", "password": "clave-asesor-1"}, content_type="application/json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["rol"], "asesor")
        self.assertEqual(self.client.get("/api/auth/yo").json()["username"], "asesor1")
        self.client.post("/api/auth/logout", content_type="application/json")
        self.assertEqual(self.client.get("/api/auth/yo").status_code, 401)

    def test_login_se_bloquea_tras_cinco_fallos(self):
        from django.core.cache import cache
        cache.clear()
        for _ in range(5):
            self.client.post("/api/auth/login", {"username": "asesor1", "password": "x"}, content_type="application/json")
        r = self.client.post("/api/auth/login", {"username": "asesor1", "password": "clave-asesor-1"}, content_type="application/json")
        self.assertEqual(r.status_code, 429)
        cache.clear()

    def test_asesor_solo_ve_sus_solicitudes(self):
        s = self.crear(self.asesor)
        self.entrar(self.otro_asesor)
        self.assertEqual(self.client.get("/api/solicitudes").json(), [])
        self.assertEqual(self.client.get(f"/api/solicitudes/{s['id']}").status_code, 404)
        self.entrar(self.gerente)
        self.assertEqual(len(self.client.get("/api/solicitudes").json()), 1)

    def test_asesor_no_aprueba(self):
        s = self.crear()
        r = self.client.post(f"/api/solicitudes/{s['id']}/aprobar", content_type="application/json")
        self.assertEqual(r.status_code, 401)


@override_settings(OTP_MOSTRAR=True)
class CrearYEnviarTest(BaseTest):
    def test_crear_guarda_la_foto_del_negocio_y_calcula(self):
        s = self.crear()
        self.assertEqual(s["estado_ui"], "borrador")
        self.assertEqual(s["inmueble"], "T9 - 101")
        self.assertEqual(s["comprador"]["documento"], "1000000001")
        self.assertEqual(s["valor_credito"], 180_000_000)
        self.assertTrue(s["resultado"]["valido"])
        self.assertEqual(s["resultado"]["dif"], 0)

    def test_no_se_duplica_una_solicitud_abierta(self):
        self.crear()
        r = self.client.post("/api/solicitudes", {"proyecto_id": self.proyecto.id, "id_venta": 777}, content_type="application/json")
        self.assertEqual(r.status_code, 409)

    def test_negocio_inexistente_es_404(self):
        self.fetch.side_effect = lambda pid, vid: None
        self.entrar(self.asesor)
        r = self.client.post("/api/solicitudes", {"proyecto_id": self.proyecto.id, "id_venta": 1}, content_type="application/json")
        self.assertEqual(r.status_code, 404)

    def test_enviar_genera_link_vigente_siete_dias(self):
        s = self.crear()
        env = self.enviar(s["id"])
        self.assertEqual(env["estado_ui"], "enviada")
        self.assertTrue(env["link"].startswith("/comprador/"))
        fila = Solicitud.objects.get(pk=s["id"])
        self.assertAlmostEqual((fila.vence_en - fila.enviada_en).days, 7, delta=0)

    def test_enviar_exige_correo_del_comprador(self):
        neg = negocio_demo()
        neg.pop("correo")
        self.fetch.side_effect = lambda pid, vid: neg
        s = self.crear()
        r = self.client.post(f"/api/solicitudes/{s['id']}/enviar", content_type="application/json")
        self.assertEqual(r.status_code, 422)

    def test_link_vencido_se_puede_regenerar(self):
        s = self.crear()
        env = self.enviar(s["id"])
        token_viejo = env["link"].split("/")[-1]
        Solicitud.objects.filter(pk=s["id"]).update(vence_en=timezone.now() - timedelta(minutes=1))
        self.assertEqual(self.client.get(f"/api/solicitudes/{s['id']}").json()["estado_ui"], "vencida")
        self.assertEqual(self.client.get(f"/api/comprador/{token_viejo}").status_code, 410)
        nuevo = self.enviar(s["id"])
        self.assertNotEqual(nuevo["link"].split("/")[-1], token_viejo)
        self.assertEqual(nuevo["estado_ui"], "enviada")


@override_settings(OTP_MOSTRAR=True)
class CompradorTest(BaseTest):
    def preparar(self):
        s = self.crear()
        env = self.enviar(s["id"])
        self.client.logout()                       # el comprador no tiene sesión
        return s["id"], env["link"].split("/")[-1]

    def test_borrador_no_es_accesible(self):
        s = self.crear()
        token = Solicitud.objects.get(pk=s["id"]).token_comprador
        self.client.logout()
        self.assertEqual(self.client.get(f"/api/comprador/{token}").status_code, 404)

    def test_token_inexistente_es_404(self):
        self.assertEqual(self.client.get("/api/comprador/no-existe").status_code, 404)

    def test_la_vista_del_comprador_no_expone_tasas_ni_correo_completo(self):
        _, token = self.preparar()
        r = self.client.get(f"/api/comprador/{token}")
        self.assertEqual(r.status_code, 200)
        cuerpo = r.content.decode()
        for prohibido in ("tasa_cia", "tasa_cliente", "tasa_vpn", "tope_pct", "umbral_pct", "comprador@ejemplo.co"):
            self.assertNotIn(prohibido, cuerpo)
        self.assertEqual(r.json()["comprador"]["correo"], "c•••@ejemplo.co")

    def test_evaluar_recalcula_en_el_servidor(self):
        _, token = self.preparar()
        base = self.client.get(f"/api/comprador/{token}").json()["propuesta"]
        igual = self.client.post(f"/api/comprador/{token}/evaluar", {"propuesta": base}, content_type="application/json")
        self.assertEqual(igual.status_code, 200)
        self.assertTrue(igual.json()["valido"])
        adelantada = self.client.post(f"/api/comprador/{token}/evaluar",
                                      {"propuesta": self.propuesta_adelantada(token)}, content_type="application/json")
        self.assertLess(adelantada.json()["ajuste"], igual.json()["ajuste"])     # paga antes: más descuento

    def test_evaluar_rechaza_conceptos_inventados(self):
        _, token = self.preparar()
        malo = [dict(x, concepto="Cualquier cosa") for x in self.client.get(f"/api/comprador/{token}").json()["propuesta"]]
        r = self.client.post(f"/api/comprador/{token}/evaluar", {"propuesta": malo}, content_type="application/json")
        self.assertEqual(r.status_code, 422)

    def test_codigo_exige_propuesta_valida(self):
        _, token = self.preparar()
        p = self.client.get(f"/api/comprador/{token}").json()["propuesta"]
        p[0]["valor"] -= 1_000_000                 # deja un faltante
        r = self.client.post(f"/api/comprador/{token}/codigo", {"propuesta": p}, content_type="application/json")
        self.assertEqual(r.status_code, 422)
        self.assertTrue(any("Faltan" in e for e in r.json()["errores"]))
        self.assertEqual(len(mail.outbox), 0)

    def test_flujo_completo_de_firma_sin_aprobacion(self):
        # umbral alto: el descuento de esta propuesta no requiere gerencia
        ProyectoConfig.objects.filter(pk=self.proyecto.pk).update(umbral_pct=0.03, tope_pct=0.03)
        sid, token = self.preparar()
        p = self.propuesta_adelantada(token)
        c = self.client.post(f"/api/comprador/{token}/codigo", {"propuesta": p}, content_type="application/json")
        self.assertEqual(c.status_code, 200, c.content)
        codigo = c.json()["codigo_prueba"]
        self.assertEqual(len(codigo), 6)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(codigo, mail.outbox[0].body)

        mal = self.client.post(f"/api/comprador/{token}/firmar", {"propuesta": p, "codigo": "000000", "acepta": True},
                               content_type="application/json")
        self.assertEqual(mal.status_code, 422)
        sin_aceptar = self.client.post(f"/api/comprador/{token}/firmar", {"propuesta": p, "codigo": codigo, "acepta": False},
                                       content_type="application/json")
        self.assertEqual(sin_aceptar.status_code, 422)

        ok = self.client.post(f"/api/comprador/{token}/firmar", {"propuesta": p, "codigo": codigo, "acepta": True},
                              content_type="application/json", HTTP_X_FORWARDED_FOR="203.0.113.7")
        self.assertEqual(ok.status_code, 200, ok.content)
        self.assertEqual(ok.json()["estado_ui"], "por_cargar")
        self.assertFalse(ok.json()["requiere_aprobacion"])
        self.assertLess(ok.json()["ajuste"], 0)

        s = Solicitud.objects.get(pk=sid)
        self.assertEqual(s.estado, "firmada")
        self.assertEqual(s.firma_ip, "203.0.113.7")
        self.assertEqual(len(s.firma_hash), 64)
        import hashlib
        self.assertEqual(hashlib.sha256(s.firma_doc.encode()).hexdigest(), s.firma_hash)
        self.assertEqual(s.otp_hash, "")                       # el código se consume

        # el link se cierra: no se puede firmar dos veces
        otra = self.client.post(f"/api/comprador/{token}/firmar", {"propuesta": p, "codigo": codigo, "acepta": True},
                                content_type="application/json")
        self.assertEqual(otra.status_code, 409)

    def test_la_firma_recalcula_y_no_confia_en_el_navegador(self):
        """El cliente no envía el resultado: aunque mande otra cosa, se guarda lo que calcula el servidor."""
        ProyectoConfig.objects.filter(pk=self.proyecto.pk).update(umbral_pct=0.03, tope_pct=0.03)
        sid, token = self.preparar()
        p = self.propuesta_adelantada(token)
        codigo = self.client.post(f"/api/comprador/{token}/codigo", {"propuesta": p}, content_type="application/json").json()["codigo_prueba"]
        self.client.post(f"/api/comprador/{token}/firmar", {"propuesta": p, "codigo": codigo, "acepta": True, "ajuste": -99999999},
                         content_type="application/json")
        s = Solicitud.objects.get(pk=sid)
        esperado = sv.evaluar(s, s.plan_propuesto)[1].ev.ajuste
        self.assertEqual(s.ajuste_final, esperado)
        self.assertNotEqual(s.ajuste_final, -99999999)

    def test_cinco_codigos_equivocados_bloquean_el_codigo(self):
        sid, token = self.preparar()
        p = self.client.get(f"/api/comprador/{token}").json()["propuesta"]
        codigo = self.client.post(f"/api/comprador/{token}/codigo", {"propuesta": p}, content_type="application/json").json()["codigo_prueba"]
        for _ in range(5):
            self.client.post(f"/api/comprador/{token}/firmar", {"propuesta": p, "codigo": "000000", "acepta": True},
                             content_type="application/json")
        r = self.client.post(f"/api/comprador/{token}/firmar", {"propuesta": p, "codigo": codigo, "acepta": True},
                             content_type="application/json")
        self.assertEqual(r.status_code, 429)

    def test_codigo_vencido(self):
        sid, token = self.preparar()
        p = self.client.get(f"/api/comprador/{token}").json()["propuesta"]
        codigo = self.client.post(f"/api/comprador/{token}/codigo", {"propuesta": p}, content_type="application/json").json()["codigo_prueba"]
        Solicitud.objects.filter(pk=sid).update(otp_vence=timezone.now() - timedelta(seconds=1))
        r = self.client.post(f"/api/comprador/{token}/firmar", {"propuesta": p, "codigo": codigo, "acepta": True},
                             content_type="application/json")
        self.assertEqual(r.status_code, 422)

    @override_settings(OTP_MOSTRAR=False)
    def test_sin_otp_mostrar_el_codigo_no_viaja_en_la_respuesta(self):
        sid, token = self.preparar()
        p = self.client.get(f"/api/comprador/{token}").json()["propuesta"]
        c = self.client.post(f"/api/comprador/{token}/codigo", {"propuesta": p}, content_type="application/json").json()
        self.assertIsNone(c["codigo_prueba"])
        self.assertEqual(len(mail.outbox), 1)

    def test_el_codigo_no_se_guarda_en_claro(self):
        sid, token = self.preparar()
        p = self.client.get(f"/api/comprador/{token}").json()["propuesta"]
        codigo = self.client.post(f"/api/comprador/{token}/codigo", {"propuesta": p}, content_type="application/json").json()["codigo_prueba"]
        s = Solicitud.objects.get(pk=sid)
        self.assertNotEqual(codigo, s.otp_hash)
        self.assertEqual(len(s.otp_hash), 64)
        self.assertEqual(s.otp_hash, sv._hash_otp(s, codigo))


@override_settings(OTP_MOSTRAR=True)
class GerenciaYCargaTest(BaseTest):
    def firmada_con_aprobacion(self):
        """Solicitud firmada cuyo descuento supera el umbral (0,05 % del valor de venta)."""
        s = self.crear()
        token = self.enviar(s["id"])["link"].split("/")[-1]
        self.client.logout()
        p = self.propuesta_adelantada(token)
        codigo = self.client.post(f"/api/comprador/{token}/codigo", {"propuesta": p}, content_type="application/json").json()["codigo_prueba"]
        r = self.client.post(f"/api/comprador/{token}/firmar", {"propuesta": p, "codigo": codigo, "acepta": True},
                             content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()["requiere_aprobacion"])
        return s["id"]

    def test_firmada_con_descuento_alto_queda_pendiente_de_aprobacion(self):
        sid = self.firmada_con_aprobacion()
        self.assertEqual(Solicitud.objects.get(pk=sid).estado, "pendiente_aprobacion")

    def test_gerente_aprueba_y_el_asesor_puede_cargar(self):
        sid = self.firmada_con_aprobacion()
        self.entrar(self.asesor)
        self.assertEqual(self.client.post(f"/api/solicitudes/{sid}/cargada", content_type="application/json").status_code, 409)
        self.entrar(self.gerente)
        r = self.client.post(f"/api/solicitudes/{sid}/aprobar", content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["estado_ui"], "por_cargar")
        self.assertEqual(r.json()["decision"]["por"], "gerente1")
        self.entrar(self.asesor)
        self.assertEqual(self.client.post(f"/api/solicitudes/{sid}/cargada", content_type="application/json").json()["estado_ui"], "cargada")

    def test_devolver_exige_comentario_y_permite_reabrir(self):
        sid = self.firmada_con_aprobacion()
        self.entrar(self.gerente)
        corto = self.client.post(f"/api/solicitudes/{sid}/devolver", {"comentario": "no"}, content_type="application/json")
        self.assertEqual(corto.status_code, 422)
        ok = self.client.post(f"/api/solicitudes/{sid}/devolver", {"comentario": "Revisar la fecha de la segunda cuota."},
                              content_type="application/json")
        self.assertEqual(ok.json()["estado_ui"], "devuelta")
        self.assertIn("segunda cuota", ok.json()["decision"]["comentario"])
        self.entrar(self.asesor)
        re = self.client.post(f"/api/solicitudes/{sid}/reabrir", content_type="application/json")
        self.assertEqual(re.json()["estado_ui"], "borrador")
        self.assertIsNone(re.json()["firma"])

    def test_aprobar_dos_veces_es_conflicto(self):
        sid = self.firmada_con_aprobacion()
        self.entrar(self.gerente)
        self.client.post(f"/api/solicitudes/{sid}/aprobar", content_type="application/json")
        self.assertEqual(self.client.post(f"/api/solicitudes/{sid}/aprobar", content_type="application/json").status_code, 409)

    def test_lineas_de_carga_incluyen_el_ajuste_con_el_concepto_del_proyecto(self):
        sid = self.firmada_con_aprobacion()
        self.entrar(self.gerente)
        d = self.client.post(f"/api/solicitudes/{sid}/aprobar", content_type="application/json").json()
        lineas = d["lineas_carga"]
        ajuste = [l for l in lineas if l["ajuste"]]
        self.assertEqual(len(ajuste), 1)
        self.assertEqual(ajuste[0]["concepto"], "Descuento financiero plan de pagos")
        self.assertLess(ajuste[0]["valor"], 0)
        self.assertEqual(sum(l["valor"] for l in lineas if not l["ajuste"]), d["resultado"]["tot_prop"])

    def _cargada(self):
        sid = self.firmada_con_aprobacion()
        self.entrar(self.gerente)
        self.client.post(f"/api/solicitudes/{sid}/aprobar", content_type="application/json")
        self.entrar(self.asesor)
        self.client.post(f"/api/solicitudes/{sid}/cargada", content_type="application/json")
        return sid

    def _negocio_en_imx(self, sid, cambio=None):
        """El negocio como quedaría en IngeMAX tras cargar el plan firmado."""
        s = Solicitud.objects.get(pk=sid)
        lineas = sv.lineas_carga(s)
        neg = negocio_demo()
        neg["plan_pagos"] = [{"fecha_pp": l["fecha"], "concepto": l["concepto"], "valor": l["valor"]} for l in lineas]
        neg["valor_credito"] = round(s.nuevo_credito)
        if cambio:
            cambio(neg)
        return neg

    def test_verificar_ok_cierra_la_solicitud(self):
        sid = self._cargada()
        self.fetch.side_effect = lambda pid, vid: self._negocio_en_imx(sid)
        r = self.client.post(f"/api/solicitudes/{sid}/verificar", content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()["verificacion"]["ok"])
        self.assertEqual(r.json()["solicitud"]["estado_ui"], "verificada")

    def test_verificar_con_diferencia_no_cierra(self):
        sid = self._cargada()
        def cambio(neg):
            neg["plan_pagos"][1]["valor"] += 1_000_000
        self.fetch.side_effect = lambda pid, vid: self._negocio_en_imx(sid, cambio)
        r = self.client.post(f"/api/solicitudes/{sid}/verificar", content_type="application/json")
        v = r.json()["verificacion"]
        self.assertFalse(v["ok"])
        self.assertEqual(v["diferencias"], 1)
        self.assertEqual(r.json()["solicitud"]["estado_ui"], "cargada")

    def test_verificar_detecta_linea_ausente(self):
        sid = self._cargada()
        def cambio(neg):
            neg["plan_pagos"].pop()
        self.fetch.side_effect = lambda pid, vid: self._negocio_en_imx(sid, cambio)
        v = self.client.post(f"/api/solicitudes/{sid}/verificar", content_type="application/json").json()["verificacion"]
        self.assertFalse(v["ok"])
        self.assertTrue(any(i["visto"] is None and not i["ok"] for i in v["items"]))

    def test_verificar_antes_de_cargar_es_conflicto(self):
        s = self.crear()
        r = self.client.post(f"/api/solicitudes/{s['id']}/verificar", content_type="application/json")
        self.assertEqual(r.status_code, 409)


class PaginasTest(BaseTest):
    """Las pantallas se sirven desde /app/ y el comprador entra por /comprador/<token>."""

    def test_la_raiz_lleva_al_login(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r["Location"], "/app/login.html")

    def test_pagina_de_login_y_recursos(self):
        for ruta in ("/app/login.html", "/app/api.js", "/app/motor.js", "/app/img/logo-vyp.svg"):
            r = self.client.get(ruta)
            self.assertEqual(r.status_code, 200, ruta)
            r.close()
        self.assertEqual(self.client.get("/app/login.html")["Cache-Control"], "no-cache")

    def test_no_se_puede_salir_de_la_carpeta_de_la_aplicacion(self):
        for ruta in ("/app/../backend/replantea/settings.py", "/app/%2e%2e/backend/manage.py", "/app/../../etc/passwd", "/app/no-existe.html"):
            self.assertEqual(self.client.get(ruta).status_code, 404, ruta)

    def test_la_pagina_del_comprador_no_se_guarda_ni_filtra_el_token(self):
        r = self.client.get("/comprador/cualquier-token")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Cache-Control"], "no-store")
        self.assertEqual(r["Referrer-Policy"], "no-referrer")
        r.close()
