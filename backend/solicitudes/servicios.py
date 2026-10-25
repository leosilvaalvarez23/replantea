"""Reglas de negocio de las solicitudes (sin HTTP).

El servidor es la fuente de verdad: todo lo que el comprador ve y firma se
recalcula aquí con el motor de `engine/`, sobre la foto del negocio guardada
en la solicitud.
"""
import hashlib
import hmac
import json
import secrets
from datetime import date, timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from engine.analisis import AnalisisNegocio, ResultadoCalculo, analizar, calcular, init_propuesta
from engine.engine import ConfigProyecto

from .models import Solicitud

LINK_DIAS = 7
OTP_MINUTOS = 10
OTP_MAX_INTENTOS = 5
ESTADOS_ABIERTOS_PARA_DUPLICADO = ("verificada", "rechazada")


class ErrorNegocio(Exception):
    """Error esperado de una regla de negocio; la API lo convierte en HTTP."""

    def __init__(self, status: int, mensaje: str, detalle=None):
        super().__init__(mensaje)
        self.status = status
        self.mensaje = mensaje
        self.detalle = detalle


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def hoy() -> str:
    return timezone.localdate().isoformat()


def cfg_de(proyecto) -> ConfigProyecto:
    return ConfigProyecto(
        metodo=proyecto.metodo, tasa_cia=proyecto.tasa_cia, tasa_cliente=proyecto.tasa_cliente,
        tasa_vpn=proyecto.tasa_vpn, tope_pct=proyecto.tope_pct, umbral_pct=proyecto.umbral_pct,
        cuota_min=proyecto.cuota_min, concepto=proyecto.concepto, concepto_abono=proyecto.concepto_abono,
    )


def vencido_el_link(s: Solicitud) -> bool:
    return s.estado == "pendiente_firma" and timezone.now() >= s.vence_en


def estado_ui(s: Solicitud) -> str:
    """Estado tal como lo muestran las pantallas."""
    if vencido_el_link(s):
        return "vencida"
    return {
        "borrador": "borrador",
        "pendiente_firma": "enviada",
        "firmada": "por_cargar",          # firmada y no requiere aprobación
        "pendiente_aprobacion": "por_aprobar",
        "aprobada": "por_cargar",
        "rechazada": "devuelta",
        "cargada": "cargada",
        "verificada": "verificada",
    }[s.estado]


def enmascarar_correo(correo: str) -> str:
    if "@" not in correo:
        return ""
    usuario, dominio = correo.split("@", 1)
    return f"{usuario[:1]}•••@{dominio}"


def corte_de(s: Solicitud) -> str:
    """Fecha de referencia del análisis: la firma, si ya se firmó; si no, hoy."""
    return timezone.localtime(s.firmada_en).date().isoformat() if s.firmada_en else hoy()


def analisis_de(s: Solicitud, corte: str = None) -> AnalisisNegocio:
    return analizar(s.negocio, corte or corte_de(s))


def conceptos_permitidos(a: AnalisisNegocio, proyecto) -> set:
    return {p["concepto"] for p in a.pend} | {proyecto.concepto_abono}


# ---------------------------------------------------------------------------
# Propuesta
# ---------------------------------------------------------------------------

def normalizar_propuesta(items, a: AnalisisNegocio, proyecto) -> list:
    """Valida el formato de lo que llega del navegador y lo deja en forma canónica."""
    if not items:
        raise ErrorNegocio(422, "La propuesta no tiene cuotas.")
    if len(items) > 120:
        raise ErrorNegocio(422, "La propuesta tiene demasiadas cuotas.")
    permitidos = conceptos_permitidos(a, proyecto)
    out = []
    for it in items:
        try:
            date.fromisoformat(it["fecha"])
        except (ValueError, TypeError, KeyError):
            raise ErrorNegocio(422, "Hay una fecha con formato inválido.")
        valor = it.get("valor")
        if isinstance(valor, bool) or not isinstance(valor, (int, float)) or valor < 0 or valor > 1e12:
            raise ErrorNegocio(422, "Hay un valor inválido en la propuesta.")
        abono = bool(it.get("abono"))
        concepto = proyecto.concepto_abono if abono else (it.get("concepto") or "")
        if concepto not in permitidos:
            raise ErrorNegocio(422, f"El concepto «{concepto}» no está permitido en este proyecto.")
        extra = {}
        # ayudas de la interfaz (qué era la cuota antes de editarla); no afectan el cálculo
        try:
            if it.get("orig") is not None and it.get("orig_fecha"):
                date.fromisoformat(it["orig_fecha"])
                extra = {"fijo": bool(it.get("fijo")), "orig": round(it["orig"]), "orig_fecha": it["orig_fecha"]}
        except (ValueError, TypeError):
            extra = {}
        out.append({"fecha": it["fecha"], "valor": round(valor), "concepto": concepto, "abono": abono, **extra})
    return sorted(out, key=lambda p: p["fecha"])


def evaluar(s: Solicitud, propuesta: list):
    """(analisis, resultado) de una propuesta ya normalizada, con las reglas del proyecto."""
    corte = corte_de(s)
    a = analizar(s.negocio, corte)
    return a, calcular(propuesta, a, s.negocio, cfg_de(s.proyecto), corte)


def propuesta_inicial(s: Solicitud) -> list:
    a = analizar(s.negocio, hoy())
    return [
        {"fecha": p["fecha"], "valor": round(p["valor"]), "concepto": p["concepto"],
         "abono": False, "fijo": p["fijo"], "orig": round(p["orig"]), "orig_fecha": p["orig_fecha"]}
        for p in init_propuesta(a, hoy())
    ]


def resultado_a_dict(r: ResultadoCalculo) -> dict:
    return {
        "ajuste": r.ev.ajuste, "ajuste_calculado": r.ev.ajuste_calculado, "topado": r.ev.topado,
        "tope": r.ev.tope, "requiere_aprobacion": r.ev.requiere_aprobacion,
        "tot_prop": r.tot_prop, "dif": r.dif, "excedente": r.excedente,
        "nuevo_credito": r.nuevo_cred, "errores": r.errores, "valido": r.valido,
    }


def analisis_a_dict(a: AnalisisNegocio) -> dict:
    return {
        "pendiente": a.pend, "vencido": a.vencido, "mora": a.mora, "saldo": a.saldo,
        "pagado": a.tot_rec, "credito": a.credito, "fecha_credito": a.fecha_credito,
        "fecha_limite": a.fecha_limite, "recaudo": a.recaudo,
    }


# ---------------------------------------------------------------------------
# Asesor
# ---------------------------------------------------------------------------

def _texto(n: dict, *claves) -> str:
    for k in claves:
        v = n.get(k)
        if v:
            return str(v).strip()
    return ""


@transaction.atomic
def crear_solicitud(usuario, proyecto, negocio: dict, correo: str = "") -> Solicitud:
    id_venta = negocio.get("id_venta") or negocio.get("id")
    if not id_venta:
        raise ErrorNegocio(502, "IngeMAX devolvió un negocio sin identificador.")
    abierta = (
        Solicitud.objects.filter(proyecto=proyecto, id_venta=id_venta)
        .exclude(estado__in=ESTADOS_ABIERTOS_PARA_DUPLICADO)
        .exists()
    )
    if abierta:
        raise ErrorNegocio(409, "Ese negocio ya tiene una solicitud abierta.")

    if not negocio.get("plan_pagos"):
        raise ErrorNegocio(422, "El negocio no tiene plan de pagos en IngeMAX.")
    if not negocio.get("valor_venta"):
        raise ErrorNegocio(422, "El negocio no tiene valor de venta en IngeMAX.")

    s = Solicitud(
        proyecto=proyecto, id_venta=id_venta, asesor=usuario, negocio=negocio,
        inmueble=_texto(negocio, "inmueble"),
        comprador_nombre=_texto(negocio, "cliente_negocio", "cliente", "nombre_cliente"),
        comprador_documento=_texto(negocio, "cliente_identificacion", "documento"),
        comprador_correo=(correo or _texto(negocio, "correo", "email", "cliente_correo")).strip(),
        valor_venta=round(negocio.get("valor_venta") or 0),
        valor_credito=round(negocio.get("valor_credito") or 0),
    )
    s.plan_propuesto = propuesta_inicial(s)
    a, r = evaluar(s, s.plan_propuesto)
    s.plan_pactado, s.recaudo = a.pend, a.recaudo
    s.ajuste_calculado, s.ajuste_final = r.ev.ajuste_calculado, r.ev.ajuste
    s.topado, s.requiere_aprobacion, s.nuevo_credito = r.ev.topado, r.ev.requiere_aprobacion, r.nuevo_cred
    s.save()
    return s


def enviar(s: Solicitud) -> Solicitud:
    """Genera (o regenera) el link del comprador. Vence a los 7 días."""
    if not (s.estado == "borrador" or vencido_el_link(s)):
        raise ErrorNegocio(409, "Solo se puede generar el link de un borrador o de un link vencido.")
    if not s.comprador_correo:
        raise ErrorNegocio(422, "Falta el correo del comprador: sin él no se le puede enviar el código de firma.")
    s.token_comprador = secrets.token_urlsafe(32)
    s.estado = "pendiente_firma"
    s.enviada_en = timezone.now()
    s.vence_en = s.enviada_en + timedelta(days=LINK_DIAS)
    s.otp_hash, s.otp_vence, s.otp_intentos = "", None, 0
    s.save()
    return s


def reabrir(s: Solicitud) -> Solicitud:
    """Una propuesta devuelta por gerencia vuelve a borrador para empezar de nuevo."""
    if s.estado != "rechazada":
        raise ErrorNegocio(409, "Solo se puede reabrir una solicitud devuelta.")
    s.estado = "borrador"
    s.firma_nombre = s.firma_documento = s.firma_hash = s.firma_doc = ""
    s.firma_ip, s.firmada_en = None, None
    s.aprobada_por, s.aprobada_en = None, None
    s.otp_hash, s.otp_vence, s.otp_intentos = "", None, 0
    s.plan_propuesto = propuesta_inicial(s)
    a, r = evaluar(s, s.plan_propuesto)
    s.ajuste_calculado, s.ajuste_final = r.ev.ajuste_calculado, r.ev.ajuste
    s.topado, s.requiere_aprobacion, s.nuevo_credito = r.ev.topado, r.ev.requiere_aprobacion, r.nuevo_cred
    s.save()
    return s


def lineas_carga(s: Solicitud) -> list:
    """Líneas que el asesor debe cargar en IngeMAX: las cuotas y la línea de ajuste."""
    if not s.firmada_en:
        return []
    out = [
        {"concepto": p["concepto"], "fecha": p["fecha"], "valor": round(p["valor"]), "ajuste": False}
        for p in sorted(s.plan_propuesto, key=lambda p: p["fecha"])
    ]
    ajuste = round(s.ajuste_final or 0)
    if ajuste != 0:
        out.append({
            "concepto": s.proyecto.concepto,
            "fecha": timezone.localtime(s.firmada_en).date().isoformat(),
            "valor": ajuste, "ajuste": True,
        })
    return out


def marcar_cargada(s: Solicitud) -> Solicitud:
    if s.estado not in ("firmada", "aprobada"):
        raise ErrorNegocio(409, "La solicitud todavía no está lista para cargar en IngeMAX.")
    s.estado, s.cargada_en = "cargada", timezone.now()
    s.save()
    return s


def verificar(s: Solicitud, negocio_imx: dict) -> dict:
    """Compara lo que hay hoy en IngeMAX con lo que firmó el comprador."""
    if s.estado != "cargada":
        raise ErrorNegocio(409, "Solo se verifica una solicitud ya cargada en IngeMAX.")
    en_imx = [
        {"fecha": p.get("fecha_pp"), "concepto": p.get("concepto"), "valor": p.get("valor") or 0}
        for p in negocio_imx.get("plan_pagos", [])
    ]
    usadas, items = set(), []
    for esperado in lineas_carga(s):
        visto, ok = None, False
        for i, l in enumerate(en_imx):
            if i in usadas or l["fecha"] != esperado["fecha"] or l["concepto"] != esperado["concepto"]:
                continue
            visto = l["valor"]
            if abs(l["valor"] - esperado["valor"]) <= 1:
                usadas.add(i)
                ok = True
                break
        items.append({**esperado, "visto": visto, "ok": ok})

    if s.valor_credito > 0 and s.nuevo_credito is not None:
        visto = negocio_imx.get("valor_credito") or 0
        items.append({
            "concepto": "Crédito hipotecario", "fecha": None, "valor": round(s.nuevo_credito),
            "ajuste": False, "visto": visto, "ok": abs(visto - s.nuevo_credito) <= 1,
        })

    ok = all(i["ok"] for i in items)
    if ok:
        s.estado, s.verificada_en = "verificada", timezone.now()
        s.save()
    return {"ok": ok, "diferencias": sum(1 for i in items if not i["ok"]), "items": items}


# ---------------------------------------------------------------------------
# Gerencia
# ---------------------------------------------------------------------------

def aprobar(s: Solicitud, usuario) -> Solicitud:
    if s.estado != "pendiente_aprobacion":
        raise ErrorNegocio(409, "Esta solicitud no está pendiente de aprobación.")
    s.estado, s.aprobada_por, s.aprobada_en, s.decision_comentario = "aprobada", usuario, timezone.now(), ""
    s.save()
    return s


def devolver(s: Solicitud, usuario, comentario: str) -> Solicitud:
    if s.estado != "pendiente_aprobacion":
        raise ErrorNegocio(409, "Esta solicitud no está pendiente de aprobación.")
    comentario = (comentario or "").strip()
    if len(comentario) < 10:
        raise ErrorNegocio(422, "Escribe al menos 10 caracteres para explicarle al asesor qué corregir.")
    s.estado, s.aprobada_por, s.aprobada_en, s.decision_comentario = "rechazada", usuario, timezone.now(), comentario
    s.save()
    return s


# ---------------------------------------------------------------------------
# Comprador
# ---------------------------------------------------------------------------

def solicitud_para_comprador(token: str) -> Solicitud:
    try:
        s = Solicitud.objects.select_related("proyecto").get(token_comprador=token)
    except Solicitud.DoesNotExist:
        raise ErrorNegocio(404, "Este link no existe.")
    if s.estado == "borrador":
        raise ErrorNegocio(404, "Este link no existe.")
    return s


def exigir_firmable(s: Solicitud):
    if vencido_el_link(s):
        raise ErrorNegocio(410, "Este link venció. Pídele a tu asesor uno nuevo.")
    if s.estado != "pendiente_firma":
        raise ErrorNegocio(409, "Esta propuesta ya fue firmada.")


def _hash_otp(s: Solicitud, codigo: str) -> str:
    return hashlib.sha256(f"{settings.SECRET_KEY}:{s.id}:{codigo}".encode()).hexdigest()


def generar_codigo(s: Solicitud, propuesta_items) -> dict:
    """Valida la propuesta, guarda el borrador y envía el código de un solo uso al correo."""
    exigir_firmable(s)
    a = analisis_de(s)
    propuesta = normalizar_propuesta(propuesta_items, a, s.proyecto)
    _, r = evaluar(s, propuesta)
    if not r.valido:
        raise ErrorNegocio(422, "La propuesta tiene errores.", r.errores)
    if not s.comprador_correo:
        raise ErrorNegocio(422, "No hay un correo registrado para enviarte el código. Habla con tu asesor.")

    codigo = f"{secrets.randbelow(10 ** 6):06d}"
    s.plan_propuesto = propuesta
    s.otp_hash = _hash_otp(s, codigo)
    s.otp_vence = timezone.now() + timedelta(minutes=OTP_MINUTOS)
    s.otp_intentos = 0
    s.save(update_fields=["plan_propuesto", "otp_hash", "otp_vence", "otp_intentos"])

    send_mail(
        subject="Tu código para firmar la propuesta de plan de pagos",
        message=(
            f"Tu código de verificación es {codigo}.\n\n"
            f"Vence en {OTP_MINUTOS} minutos. Si no lo pediste, ignora este mensaje."
        ),
        from_email=None,
        recipient_list=[s.comprador_correo],
        fail_silently=False,
    )
    return {"enviado_a": enmascarar_correo(s.comprador_correo), "codigo_prueba": codigo if settings.OTP_MOSTRAR else None}


def firmar(solicitud_id, propuesta_items, codigo: str, acepta: bool, ip: str) -> Solicitud:
    if not acepta:
        raise ErrorNegocio(422, "Debes aceptar la firma electrónica y el tratamiento de tus datos.")
    error_codigo = None   # se lanza al salir de la transacción: si no, el conteo de intentos se revertiría
    with transaction.atomic():
        s = Solicitud.objects.select_for_update().select_related("proyecto").get(pk=solicitud_id)
        exigir_firmable(s)

        if not s.otp_hash or not s.otp_vence:
            raise ErrorNegocio(422, "Primero pide el código de verificación.")
        if timezone.now() >= s.otp_vence:
            raise ErrorNegocio(422, "El código venció. Pide uno nuevo.")
        if s.otp_intentos >= OTP_MAX_INTENTOS:
            raise ErrorNegocio(429, "Demasiados intentos. Pide un código nuevo.")
        if not hmac.compare_digest(_hash_otp(s, (codigo or "").strip()), s.otp_hash):
            s.otp_intentos += 1
            s.save(update_fields=["otp_intentos"])
            error_codigo = ErrorNegocio(422, "El código no coincide. Revísalo e inténtalo de nuevo.")
        else:
            s = _registrar_firma(s, propuesta_items, ip)
    if error_codigo:
        raise error_codigo
    return s


def _registrar_firma(s: Solicitud, propuesta_items, ip: str) -> Solicitud:
    """Recalcula, valida y guarda la firma. Se llama dentro de la transacción de `firmar`."""
    a = analisis_de(s)
    propuesta = normalizar_propuesta(propuesta_items, a, s.proyecto)
    _, r = evaluar(s, propuesta)
    if not r.valido:
        raise ErrorNegocio(422, "La propuesta tiene errores.", r.errores)

    ahora = timezone.now()
    doc = json.dumps({
        "solicitud": str(s.id), "venta": s.id_venta, "inmueble": s.inmueble,
        "firmante": s.comprador_nombre, "documento": s.comprador_documento, "correo": s.comprador_correo,
        "propuesta": [[p["fecha"], p["concepto"], p["valor"]] for p in propuesta],
        "credito": r.nuevo_cred, "ajuste": r.ev.ajuste, "metodo": s.proyecto.metodo,
        "fecha": ahora.isoformat(),
    }, sort_keys=True, ensure_ascii=False, separators=(",", ":"))

    s.plan_propuesto = propuesta
    s.ajuste_calculado, s.ajuste_final, s.topado = r.ev.ajuste_calculado, r.ev.ajuste, r.ev.topado
    s.requiere_aprobacion, s.nuevo_credito = r.ev.requiere_aprobacion, r.nuevo_cred
    s.firma_nombre, s.firma_documento, s.firma_ip = s.comprador_nombre, s.comprador_documento, ip or None
    s.firma_doc, s.firma_hash = doc, hashlib.sha256(doc.encode()).hexdigest()
    s.firmada_en = ahora
    s.estado = "pendiente_aprobacion" if r.ev.requiere_aprobacion else "firmada"
    s.otp_hash, s.otp_vence, s.otp_intentos = "", None, 0
    s.save()
    return s
