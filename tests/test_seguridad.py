"""Rastreos contra una web simulada (httpx.MockTransport): https, redirecciones de dominio y red local."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from rastreo import rastreador as modulo_rastreador
from rastreo.puntuacion import auditar
from rastreo.rastreador import ErrorRastreo, Opciones, Rastreador
from rastreo.urls import es_host_privado

HOSTS_PRIVADOS_FALSOS = {"192.168.1.10", "intranet.local"}


async def _privado_falso(host: str) -> bool:
    """Sustituye a la resolución DNS real: las pruebas no necesitan red."""
    return host in HOSTS_PRIVADOS_FALSOS


def web_simulada(paginas: dict[str, tuple[int, dict, str]], peticiones: list[str]) -> httpx.MockTransport:
    def responder(peticion: httpx.Request) -> httpx.Response:
        url = str(peticion.url)
        peticiones.append(url)
        estado, cabeceras, cuerpo = paginas.get(url, (404, {}, "No encontrada"))
        return httpx.Response(estado, headers={"content-type": "text/html; charset=utf-8", **cabeceras}, text=cuerpo)
    return httpx.MockTransport(responder)


def rastrear(inicio, paginas, **opciones):
    peticiones: list[str] = []
    transporte = web_simulada(paginas, peticiones)
    resultado = asyncio.run(Rastreador(inicio, Opciones(por_segundo=50, **opciones), transporte=transporte).ejecutar())
    return resultado, peticiones


@pytest.fixture(autouse=True)
def sin_dns(monkeypatch):
    monkeypatch.setattr(modulo_rastreador, "es_host_privado", _privado_falso)


PORTADA = """<html lang="es"><head><title>Inicio</title><meta name="description" content="Tienda de ejemplo">
<link rel="canonical" href="https://www.ejemplo.es/"></head><body><h1>Inicio</h1>
<img src="http://www.ejemplo.es/logo.png" alt="Logo"><script src="http://cdn.ejemplo.es/app.js"></script>
<a href="http://192.168.1.10/admin">Router</a><a href="https://intranet.local/">Intranet</a>
<a href="https://proveedor.es/catalogo">Proveedor</a></body></html>"""


def test_contenido_mixto_y_externos_privados():
    resultado, peticiones = rastrear("https://www.ejemplo.es/", {
        "https://www.ejemplo.es/robots.txt": (200, {"content-type": "text/plain"}, "User-agent: *\nAllow: /\n"),
        "https://www.ejemplo.es/": (200, {}, PORTADA),
        "https://proveedor.es/catalogo": (410, {}, "Ya no existe"),
    }, externos=True)
    problemas = {p.tipo.id: p for p in auditar(resultado).problemas}
    mixto = problemas["contenido_mixto"].hallazgos[0]
    assert mixto.relacionadas == ["http://cdn.ejemplo.es/app.js", "http://www.ejemplo.es/logo.png"]
    # Los enlaces a la red local no se piden nunca; el externo público sí
    assert not any("192.168" in p or "intranet" in p for p in peticiones)
    assert sorted(resultado.externos_omitidos) == ["http://192.168.1.10/admin", "https://intranet.local/"]
    assert [h.url for h in problemas["enlace_roto_externo"].hallazgos] == ["https://proveedor.es/catalogo"]


def test_inicio_que_redirige_a_otro_host_se_adopta():
    resultado, _ = rastrear("http://ejemplo.es/", {
        "http://ejemplo.es/robots.txt": (404, {}, ""),
        "http://ejemplo.es/": (301, {"location": "https://www.ejemplo.es/"}, ""),
        "https://www.ejemplo.es/robots.txt": (404, {}, ""),
        "https://www.ejemplo.es/": (200, {}, "<title>Inicio</title><h1>Hola</h1>"),
    })
    assert resultado.host == "www.ejemplo.es"
    assert list(resultado.paginas) == ["https://www.ejemplo.es/"]
    assert "redirige a https://www.ejemplo.es/" in resultado.avisos[0]


def test_no_sigue_redireccion_inicial_a_la_red_local():
    with pytest.raises(ErrorRastreo, match="dirección privada"):
        rastrear("https://ejemplo.es/", {
            "https://ejemplo.es/robots.txt": (404, {}, ""),
            "https://ejemplo.es/": (302, {"location": "http://192.168.1.10/"}, ""),
        })


def test_robots_que_lo_prohibe_todo_o_falla():
    with pytest.raises(ErrorRastreo, match="no permite"):
        rastrear("https://ejemplo.es/", {"https://ejemplo.es/robots.txt": (200, {}, "User-agent: *\nDisallow: /\n")})
    with pytest.raises(ErrorRastreo, match="503"):
        rastrear("https://ejemplo.es/", {"https://ejemplo.es/robots.txt": (503, {}, "")})


def test_x_robots_tag_y_respuestas_grandes():
    enorme = "<title>Grande</title><h1>Grande</h1>" + "<p>relleno</p>" * 50_000
    resultado, _ = rastrear("https://ejemplo.es/", {
        "https://ejemplo.es/robots.txt": (404, {}, ""),
        "https://ejemplo.es/": (200, {"x-robots-tag": "noindex"}, enorme),
    }, max_bytes=100_000)
    problemas = {p.tipo.id: p for p in auditar(resultado).problemas}
    assert problemas["noindex"].hallazgos[0].detalle == "cabecera X-Robots-Tag"
    assert any("se analiza solo el principio" in a for a in resultado.avisos)


def test_crawl_delay_reduce_el_ritmo():
    resultado, _ = rastrear("https://ejemplo.es/", {
        "https://ejemplo.es/robots.txt": (200, {}, "User-agent: *\nCrawl-delay: 0.3\n"),
        "https://ejemplo.es/": (200, {}, "<title>Inicio</title>"),
    })
    assert any("Crawl-delay" in a for a in resultado.avisos)
    # Tras leer robots.txt: comprobación de la portada, portada y llms.txt, separadas 0,3 s
    assert resultado.duracion >= 0.55


def test_url_inicial_no_valida():
    with pytest.raises(ErrorRastreo):
        Rastreador("ftp://ejemplo.es/")


@pytest.mark.parametrize("host, privado", [
    ("127.0.0.1", True), ("10.1.2.3", True), ("192.168.0.1", True), ("169.254.169.254", True),
    ("[::1]", True), ("localhost", True), ("app.localhost", True), ("8.8.8.8", False), ("2606:4700::1111", False),
])
def test_es_host_privado_con_ips_literales(host, privado):
    assert asyncio.run(es_host_privado(host)) is privado


def test_lectura_de_crawl_delay():
    from rastreo.rastreador import crawl_delay
    robots = "User-agent: Googlebot\nCrawl-delay: 5\n\nUser-agent: rastreo\nUser-agent: otro\nCrawl-delay: 0.5\n\nUser-agent: *\nCrawl-delay: 2\n"
    assert crawl_delay(robots, "rastreo/0.1 (+https://github.com/Ruben-Tur/auditor-seo)") == 0.5
    assert crawl_delay(robots, "buscador/1.0") == 2
    assert crawl_delay("User-agent: *\nCrawl-delay: 9999\n", "rastreo/0.1") == 60
    assert crawl_delay("", "rastreo/0.1") is None


def test_duplicados_solo_entre_paginas_indexables():
    pagina = '<html lang="es"><title>Proyectos</title><meta name="description" content="Lista de proyectos"><h1>P</h1>{}'
    resultado, _ = rastrear("https://ejemplo.es/", {
        "https://ejemplo.es/robots.txt": (404, {}, ""),
        "https://ejemplo.es/": (200, {}, pagina.format('<a href="/?filtro=php">PHP</a><a href="/?filtro=go">Go</a>')),
        # Filtro con canónica a la página principal y filtro con noindex: no cuentan como duplicados
        "https://ejemplo.es/?filtro=php": (200, {}, pagina.format('<link rel="canonical" href="/">')),
        "https://ejemplo.es/?filtro=go": (200, {}, pagina.format('<meta name="robots" content="noindex">')),
    })
    tipos = {p.tipo.id for p in auditar(resultado).problemas}
    assert "titulo_duplicado" not in tipos and "descripcion_duplicada" not in tipos
