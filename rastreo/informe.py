"""Genera el informe HTML autocontenido y la salida JSON."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

from jinja2 import Environment, PackageLoader, StrictUndefined

from . import AUTOR, URL_AUTOR, __version__
from .formato import decimal, fecha_larga, miles
from .puntuacion import Auditoria, valoracion

MAX_RELACIONADAS = 10  # en el HTML; el JSON lleva la lista completa


def es_url(texto: str) -> bool:
    """Solo se convierten en enlace las URL http(s); el resto se muestra como texto."""
    return texto.startswith(("http://", "https://"))


def _entorno() -> Environment:
    # autoescape=True a mano: select_autoescape decide por la extensión y aquí no queremos depender de eso.
    entorno = Environment(
        loader=PackageLoader("rastreo", "plantillas"),
        autoescape=True,
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    entorno.filters.update(decimal=decimal, miles=miles, fecha_larga=fecha_larga)
    entorno.tests["url"] = es_url
    return entorno


def generar_html(auditoria: Auditoria) -> str:
    entorno = _entorno()
    contexto = {
        "a": auditoria,
        "r": auditoria.resultado,
        "valoracion": valoracion(auditoria.puntuacion),
        "version": __version__,
        "autor": AUTOR,
        "url_autor": URL_AUTOR,
        "max_relacionadas": MAX_RELACIONADAS,
    }
    # El CSS lleva los anchos de las barras, así que se genera primero y su hash entra en la CSP:
    # el informe no necesita 'unsafe-inline' ni ningún script.
    css = entorno.get_template("estilos.css").render(contexto).strip()
    huella = base64.b64encode(hashlib.sha256(css.encode("utf-8")).digest()).decode("ascii")
    return entorno.get_template("informe.html").render(contexto, css=css, huella_css=huella)


def a_diccionario(auditoria: Auditoria) -> dict:
    r = auditoria.resultado
    return {
        "herramienta": "rastreo",
        "version": __version__,
        "url": r.inicio,
        "fecha": auditoria.fecha.isoformat(timespec="seconds"),
        "duracion_s": round(r.duracion, 1),
        "rastreo": {
            "urls_rastreadas": len(r.respuestas),
            "paginas_analizadas": auditoria.paginas_analizadas,
            "bloqueadas_robots": len(r.bloqueadas),
            "enlaces_externos": len(r.enlaces_externos),
            "externos_comprobados": len(r.externos),
            "limite_alcanzado": r.limite_alcanzado,
            "avisos": r.avisos,
        },
        "puntuacion": auditoria.puntuacion,
        "valoracion": valoracion(auditoria.puntuacion),
        "problemas": [
            {
                "id": p.tipo.id,
                "titulo": p.tipo.titulo,
                "gravedad": p.tipo.gravedad,
                "peso": p.tipo.peso,
                "impacto": round(p.impacto, 1),
                "total": p.total,
                "unidad": p.tipo.unidad,
                "hallazgos": [{"url": h.url, "detalle": h.detalle, "relacionadas": h.relacionadas} for h in p.hallazgos],
            }
            for p in auditoria.problemas
        ],
        "superadas": auditoria.superadas,
    }


def generar_json(auditoria: Auditoria) -> str:
    return json.dumps(a_diccionario(auditoria), ensure_ascii=False, indent=2)


def guardar(texto: str, ruta: Path) -> Path:
    ruta = ruta.expanduser().resolve()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(texto, encoding="utf-8")
    return ruta
