"""Extracción de los datos SEO de una página HTML con BeautifulSoup."""

from __future__ import annotations

import json
import re

from bs4 import BeautifulSoup, Tag

from .modelos import DatosPagina
from .urls import resolver

try:  # lxml es más rápido; si no está (o el sistema lo bloquea) basta con el parser de la biblioteca estándar
    import lxml  # noqa: F401

    PARSER = "lxml"
except ImportError:  # pragma: no cover - depende del entorno
    PARSER = "html.parser"

_ESPACIOS = re.compile(r"\s+")
_RELS_RECURSO = {"stylesheet", "icon", "preload", "modulepreload", "manifest"}
_ETIQUETAS_SRC = ("img", "script", "iframe", "source", "video", "audio", "embed", "track")


def limpiar(texto: str | None) -> str:
    return _ESPACIOS.sub(" ", texto or "").strip()


def _rels(etiqueta: Tag) -> set[str]:
    rel = etiqueta.get("rel") or []
    if isinstance(rel, str):
        rel = rel.split()
    return {r.lower() for r in rel}


def _meta(sopa: BeautifulSoup, *nombres: str) -> list[Tag]:
    patron = re.compile(r"^(" + "|".join(map(re.escape, nombres)) + r")$", re.I)
    return sopa.find_all("meta", attrs={"name": patron})


def _tipos_jsonld(dato: object) -> list[str]:
    """Recoge los @type de un bloque JSON-LD (puede ser objeto, lista o tener @graph)."""
    tipos: list[str] = []
    if isinstance(dato, list):
        for elemento in dato:
            tipos += _tipos_jsonld(elemento)
    elif isinstance(dato, dict):
        tipo = dato.get("@type")
        if isinstance(tipo, str):
            tipos.append(tipo)
        elif isinstance(tipo, list):
            tipos += [t for t in tipo if isinstance(t, str)]
        tipos += _tipos_jsonld(dato.get("@graph", []))
    return tipos


def analizar_html(contenido: bytes | str, url: str) -> DatosPagina:
    sopa = BeautifulSoup(contenido, PARSER)
    datos = DatosPagina()

    base = url
    etiqueta_base = sopa.find("base", href=True)
    if etiqueta_base:
        base = resolver(url, etiqueta_base["href"]) or url

    # Los <title> dentro de un <svg> son descripciones del gráfico, no el título de la página.
    datos.titulos = [limpiar(t.get_text()) for t in sopa.find_all("title") if not t.find_parent("svg")]
    datos.descripciones = [limpiar(m.get("content")) for m in _meta(sopa, "description")]
    datos.h1 = [limpiar(h.get_text()) for h in sopa.find_all("h1")]

    html = sopa.find("html")
    if html and html.get("lang"):
        datos.idioma = limpiar(html["lang"]) or None

    # alt="" es correcto para imágenes decorativas: solo falla si falta el atributo.
    for img in sopa.find_all("img"):
        if not img.has_attr("alt"):
            datos.imagenes_sin_alt.append(resolver(base, img.get("src")) or limpiar(img.get("src")) or "(sin src)")

    for link in sopa.find_all("link", href=True):
        rels = _rels(link)
        if "canonical" in rels:
            canonica = resolver(base, link["href"])
            if canonica:
                datos.canonicas.append(canonica)
        if rels & _RELS_RECURSO:
            recurso = resolver(base, link["href"])
            if recurso:
                datos.recursos.append(recurso)

    for meta in _meta(sopa, "robots", "googlebot"):
        directivas = {d.strip().lower() for d in (meta.get("content") or "").split(",")}
        if directivas & {"noindex", "none"}:
            datos.noindex = True

    vistos: set[str] = set()
    for a in sopa.find_all(["a", "area"], href=True):
        destino = resolver(base, a["href"])
        if destino and destino not in vistos:
            vistos.add(destino)
            datos.enlaces.append(destino)

    for etiqueta in sopa.find_all(_ETIQUETAS_SRC, src=True):
        recurso = resolver(base, etiqueta["src"])
        if recurso:
            datos.recursos.append(recurso)
    for objeto in sopa.find_all("object", data=True):
        recurso = resolver(base, objeto["data"])
        if recurso:
            datos.recursos.append(recurso)

    for numero, bloque in enumerate(sopa.find_all("script", type=re.compile(r"^application/ld\+json$", re.I)), 1):
        try:
            datos.jsonld_tipos += _tipos_jsonld(json.loads(bloque.string or ""))
        except json.JSONDecodeError as error:
            datos.jsonld_errores.append(f"Bloque {numero}: {error.msg} (línea {error.lineno}, columna {error.colno})")

    return datos
