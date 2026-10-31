"""Rastreo completo de la web de prueba local: tiene que encontrar exactamente los fallos sembrados."""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict

import pytest
from bs4 import BeautifulSoup

from rastreo import USER_AGENT
from rastreo.cli import main
from rastreo.informe import generar_html, generar_json
from rastreo.puntuacion import auditar
from rastreo.rastreador import Opciones, Rastreador
from rastreo.urls import ruta

RAPIDO = dict(concurrencia=4, por_segundo=50, timeout=5)

# tipo de problema -> rutas afectadas que la web de prueba tiene sembradas a propósito
ESPERADOS = {
    "enlace_roto_interno": {"/roto.html", "/caida", "/\"><script>alert(3)</script>"},
    "enlace_roto_externo": {"/desaparecida.html"},
    "bucle_redireccion": {"/bucle-a"},
    "cadena_redirecciones": {"/antigua"},
    "enlace_a_redireccion": {"/antigua", "/bucle-a"},
    "sin_titulo": {"/contacto.html"},
    "titulo_duplicado": {"/blog/", "/blog/entrada.html"},
    "titulo_largo": {"/productos.html"},
    "sin_descripcion": {"/contacto.html"},
    "descripcion_duplicada": {"/blog/", "/blog/entrada.html"},
    "descripcion_larga": {"/productos.html"},
    "sin_h1": {"/productos.html"},
    "varios_h1": {"/blog/entrada.html"},
    "imagenes_sin_alt": {"/productos.html", "/xss.html"},
    "sin_canonica": {"/faq.html"},
    "canonica_no_200": {"/contacto.html"},
    "canonica_otro_dominio": {"/legal.html"},
    "noindex": {"/contacto.html"},
    "sin_idioma": {"/faq.html"},
    "datos_estructurados_invalidos": {"/sobre.html"},
    "sin_datos_estructurados": {"/productos.html", "/blog/", "/blog/entrada.html", "/contacto.html",
                                "/legal.html", "/faq.html", "/xss.html"},
    "sin_llms_txt": {"/llms.txt"},
    "bloqueada_robots": {"/privado/ficha.html"},
}


def rastrear(servidor, **opciones):
    servidor.registro.clear()
    return asyncio.run(Rastreador(servidor.url, Opciones(**{**RAPIDO, **opciones})).ejecutar())


@pytest.fixture(scope="module")
def auditoria(servidor):
    return auditar(rastrear(servidor, externos=True))


def test_encuentra_exactamente_los_fallos_sembrados(auditoria):
    encontrados = defaultdict(set)
    for problema in auditoria.problemas:
        for h in problema.hallazgos:
            encontrados[problema.tipo.id].add(ruta(h.url))
    assert dict(encontrados) == ESPERADOS


def test_cuenta_paginas_y_urls(auditoria):
    r = auditoria.resultado
    assert auditoria.paginas_analizadas == 9
    # 9 páginas + 3 rotas + 4 saltos de redirección + /intermedia... + canónica rota
    assert sorted(ruta(u) for u in r.respuestas) == sorted([
        "/", "/sobre.html", "/productos.html", "/blog/", "/blog/entrada.html", "/contacto.html", "/legal.html",
        "/faq.html", "/xss.html", "/roto.html", "/caida", "/\"><script>alert(3)</script>", "/antigua",
        "/intermedia", "/bucle-a", "/bucle-b", "/no-existe.html",
    ])
    assert not r.limite_alcanzado
    assert 0 < auditoria.puntuacion < 100


def test_detalles_de_los_hallazgos(auditoria):
    por_tipo = {p.tipo.id: p for p in auditoria.problemas}
    cadena = por_tipo["cadena_redirecciones"].hallazgos[0]
    assert cadena.detalle.startswith("2 saltos:") and cadena.detalle.endswith("/sobre.html")
    roto = next(h for h in por_tipo["enlace_roto_interno"].hallazgos if h.url.endswith("/caida"))
    assert roto.detalle == "500" and [ruta(u) for u in roto.relacionadas] == ["/"]
    assert por_tipo["imagenes_sin_alt"].total == 2  # alt="" es válido: solo cuentan las que no tienen el atributo
    assert por_tipo["canonica_no_200"].hallazgos[0].detalle.endswith("(404)")


def test_problemas_ordenados_por_impacto(auditoria):
    impactos = [p.impacto for p in auditoria.problemas]
    assert impactos == sorted(impactos, reverse=True)
    assert auditoria.problemas[0].tipo.id == "enlace_roto_interno"


def test_respeta_robots_y_se_identifica(servidor):
    rastrear(servidor)
    rutas = [r for _, _, r, _ in servidor.registro]
    assert rutas[0] == "/robots.txt"
    assert not any(r.startswith("/privado/") for r in rutas)
    assert {ua for *_, ua in servidor.registro} == {USER_AGENT}
    # Cada URL se pide una sola vez (más la comprobación inicial de la portada)
    assert rutas.count("/sobre.html") == 1 and rutas.count("/") == 2


def test_sin_externos_no_sale_del_dominio(servidor):
    resultado = rastrear(servidor)
    assert all(host.startswith("127.0.0.1") for _, host, _, _ in servidor.registro)
    assert resultado.externos == {}
    assert len(resultado.enlaces_externos) == 2


def test_limite_de_paginas(servidor):
    resultado = rastrear(servidor, max_paginas=3)
    assert len(resultado.respuestas) == 3
    assert resultado.limite_alcanzado


def test_limite_de_peticiones_por_segundo(servidor):
    resultado = rastrear(servidor, max_paginas=4, por_segundo=10, concurrencia=4)
    # robots.txt + portada (comprobación) + 4 URL + llms.txt = 7 peticiones a 10/s: al menos 0,6 s
    assert resultado.duracion >= 0.55


def test_informe_html_escapa_el_contenido_de_la_web(auditoria):
    html = generar_html(auditoria)
    sopa = BeautifulSoup(html, "html.parser")
    assert "<script" not in html.lower()
    assert sopa.find("script") is None and sopa.find("img") is None
    for etiqueta in sopa.find_all(True):
        assert not any(atributo.startswith("on") for atributo in etiqueta.attrs), etiqueta
    # El texto hostil sí aparece, pero como texto
    assert "\"><script>alert('título')</script>" not in html
    assert "&lt;script&gt;alert(3)&lt;/script&gt;" in html
    for enlace in sopa.find_all("a"):
        assert enlace["href"].startswith(("http://", "https://", "#"))


def test_informe_html_es_autocontenido_y_privado(auditoria):
    sopa = BeautifulSoup(generar_html(auditoria), "html.parser")
    csp = sopa.find("meta", attrs={"http-equiv": "Content-Security-Policy"})["content"]
    assert "default-src 'none'" in csp and "unsafe-inline" not in csp and "style-src 'sha256-" in csp
    assert sopa.find("meta", attrs={"name": "robots"})["content"].startswith("noindex")
    assert sopa.find("link") is None  # ni hojas de estilo ni fuentes externas
    assert sopa.html["lang"] == "es"


def test_json(auditoria):
    datos = json.loads(generar_json(auditoria))
    assert datos["puntuacion"] == auditoria.puntuacion
    assert datos["rastreo"]["paginas_analizadas"] == 9
    assert {p["id"] for p in datos["problemas"]} == set(ESPERADOS)


def test_cli_genera_informe_y_json(servidor, tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    informe, salida_json = tmp_path / "informe.html", tmp_path / "resultado.json"
    codigo = main([servidor.url, "--informe", str(informe), "--json", str(salida_json), "--por-segundo", "50"])
    salida = capsys.readouterr().out
    assert codigo == 0
    assert informe.read_text(encoding="utf-8").startswith("<!doctype html>")
    assert json.loads(salida_json.read_text(encoding="utf-8"))["rastreo"]["paginas_analizadas"] == 9
    assert "\033[" not in salida  # NO_COLOR y salida que no es una terminal: sin códigos de color
    assert "✗ Enlaces internos rotos" in salida and "Puntuación" in salida and "Informe guardado en" in salida


def test_cli_minimo_y_json_por_salida_estandar(servidor, capsys):
    codigo = main([servidor.url, "--json", "--por-segundo", "50", "--minimo", "99"])
    captura = capsys.readouterr()
    assert codigo == 1
    assert json.loads(captura.out)["herramienta"] == "rastreo"  # stdout lleva solo el JSON
    assert "Puntuación" in captura.err


def test_cli_rechaza_urls_no_http(capsys):
    with pytest.raises(SystemExit) as salida:
        main(["file:///C:/Windows/win.ini"])
    assert salida.value.code == 2
    assert "no es una URL" in capsys.readouterr().err
