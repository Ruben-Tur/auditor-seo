"""Normalización de URL y comprobaciones de host."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urljoin, urlsplit, urlunsplit

PUERTOS_POR_DEFECTO = {"http": 80, "https": 443}
ESQUEMAS_IGNORADOS = ("javascript:", "mailto:", "tel:", "data:", "sms:", "ftp:", "file:")


def normalizar(url: str) -> str | None:
    """Devuelve la URL en forma canónica (sin fragmento ni credenciales) o None si no es http(s)."""
    try:
        partes = urlsplit(url.strip())
        esquema = partes.scheme.lower()
        if esquema not in PUERTOS_POR_DEFECTO or not partes.hostname:
            return None
        host = partes.hostname.lower()
        puerto = partes.port
    except ValueError:
        return None
    if ":" in host:  # IPv6
        host = f"[{host}]"
    netloc = host if puerto in (None, PUERTOS_POR_DEFECTO[esquema]) else f"{host}:{puerto}"
    return urlunsplit((esquema, netloc, partes.path or "/", partes.query, ""))


def resolver(base: str, href: str | None) -> str | None:
    """Resuelve un href relativo frente a la URL base. Ignora esquemas que no son http(s)."""
    if not href:
        return None
    href = href.strip()
    if not href or href.startswith("#") or href.lower().startswith(ESQUEMAS_IGNORADOS):
        return None
    try:
        return normalizar(urljoin(base, href))
    except ValueError:
        return None


def anfitrion(url: str) -> str:
    """Host con puerto (sin esquema): http y https del mismo host cuentan como la misma web."""
    return urlsplit(url).netloc.lower()


def nombre_host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def ruta(url: str) -> str:
    partes = urlsplit(url)
    return partes.path + (f"?{partes.query}" if partes.query else "")


def _ip_privada(ip: str) -> bool:
    try:
        direccion = ipaddress.ip_address(ip.split("%")[0])
    except ValueError:
        return False
    return not direccion.is_global


async def es_host_privado(host: str) -> bool:
    """True si el host es una IP privada, de loopback o local, o si resuelve a una.

    Evita que una web pública nos haga pedir recursos de la red local
    (por ejemplo con un enlace o una redirección a http://192.168.1.1/).
    """
    host = host.strip("[]").lower()
    if host == "localhost" or host.endswith(".localhost"):
        return True
    if _ip_privada(host):
        return True
    try:
        ipaddress.ip_address(host)
        return False  # IP pública literal
    except ValueError:
        pass
    try:
        bucle = asyncio.get_running_loop()
        infos = await bucle.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except OSError:
        return False  # no resuelve: la petición fallará sola y se informará como error
    return any(_ip_privada(info[4][0]) for info in infos)
