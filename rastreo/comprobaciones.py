"""Comprobaciones de SEO técnico sobre el resultado de un rastreo.

Cada tipo de problema tiene una gravedad y un peso (lo que puede llegar a restar
de la puntuación). Las comprobaciones devuelven hallazgos concretos con su URL.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from .modelos import Respuesta, ResultadoRastreo
from .urls import anfitrion

ERROR, AVISO, INFO = "error", "aviso", "info"
ORDEN_GRAVEDAD = {ERROR: 0, AVISO: 1, INFO: 2}

LARGO_MAX_TITULO = 60
LARGO_MAX_DESCRIPCION = 160
MIN_SALTOS_CADENA = 2


@dataclass(frozen=True)
class TipoProblema:
    id: str
    titulo: str
    gravedad: str
    peso: float
    familia: str
    porque: str
    como: str
    agrupar: bool = False  # agrupa los hallazgos por su detalle (p. ej. el título duplicado)
    unidad: str = "URL"  # qué se cuenta: URL o elementos sueltos (imágenes)


@dataclass
class Hallazgo:
    tipo: str
    url: str
    detalle: str = ""
    relacionadas: list[str] = field(default_factory=list)
    etiqueta_relacionadas: str = ""
    elementos: int = 1


# Familias de comprobaciones: si una familia no tiene ningún problema, se muestra como superada.
FAMILIAS = {
    "enlaces": "Sin enlaces rotos",
    "redirecciones": "Redirecciones directas",
    "titulos": "Títulos correctos",
    "descripciones": "Meta descriptions correctas",
    "encabezados": "Un <h1> por página",
    "imagenes": "Imágenes con alt",
    "canonicas": "Canónicas correctas",
    "indexacion": "Páginas indexables",
    "idioma": "Idioma declarado",
    "seguridad": "Sin contenido mixto",
    "estructurados": "Datos estructurados válidos",
    "geo": "llms.txt publicado",
}

_TIPOS = [
    TipoProblema(
        "enlace_roto_interno", "Enlaces internos rotos", ERROR, 12, "enlaces",
        "Hay páginas que enlazan a URL de la propia web que devuelven un error (4xx o 5xx) o no responden. "
        "Las visitas llegan a un callejón sin salida y el buscador gasta rastreo en páginas que no existen.",
        "Corrige el enlace en cada página de origen o redirige con un 301 la URL rota a su equivalente actual."),
    TipoProblema(
        "bucle_redireccion", "Bucles de redirección", ERROR, 8, "redirecciones",
        "La URL redirige en círculo y nunca llega a una página: ni las personas ni los buscadores pueden verla.",
        "Revisa las reglas de redirección (servidor, plugin o .htaccess) y deja un único destino final con 200."),
    TipoProblema(
        "canonica_no_200", "Canónicas que no apuntan a una página válida", ERROR, 6, "canonicas",
        "La etiqueta canónica señala una URL que redirige o da error, así que el buscador recibe una señal contradictoria.",
        "Haz que la canónica apunte a la URL final que responde 200."),
    TipoProblema(
        "contenido_mixto", "Contenido mixto (recursos http en páginas https)", ERROR, 6, "seguridad",
        "Una página segura carga imágenes, scripts o estilos por http. El navegador los bloquea o marca la página como no segura.",
        "Cambia esos recursos a https o a rutas relativas."),
    TipoProblema(
        "sin_titulo", "Páginas sin <title>", ERROR, 8, "titulos",
        "El título es lo primero que se ve en los resultados de búsqueda. Sin él, el buscador se inventa uno.",
        "Añade un <title> único y descriptivo de menos de 60 caracteres."),
    TipoProblema(
        "sin_h1", "Páginas sin <h1>", ERROR, 6, "encabezados",
        "El h1 resume de qué trata la página para buscadores, lectores de pantalla y motores generativos.",
        "Añade un único <h1> con el tema principal de la página."),
    TipoProblema(
        "titulo_duplicado", "Títulos duplicados", AVISO, 5, "titulos",
        "Varias páginas con el mismo título compiten entre sí y el buscador no sabe cuál mostrar.",
        "Escribe un título distinto para cada página.", agrupar=True),
    TipoProblema(
        "canonica_otro_dominio", "Canónicas que apuntan a otro dominio", AVISO, 5, "canonicas",
        "La página le dice al buscador que la versión buena está en otra web, así que esta deja de posicionar.",
        "Si no es intencionado (contenido sindicado), apunta la canónica a la propia URL."),
    TipoProblema(
        "datos_estructurados_invalidos", "Datos estructurados con errores", AVISO, 4, "estructurados",
        "Un bloque JSON-LD que no es JSON válido se ignora entero: se pierden los resultados enriquecidos.",
        "Valida el bloque (comas finales, comillas sin escapar) y vuelve a publicarlo."),
    TipoProblema(
        "cadena_redirecciones", "Redirecciones en cadena", AVISO, 4, "redirecciones",
        "Cada salto añade latencia y el buscador puede dejar de seguir la cadena antes de llegar al final.",
        "Redirige directamente de la primera URL a la final con un solo 301."),
    TipoProblema(
        "enlace_roto_externo", "Enlaces externos rotos", AVISO, 4, "enlaces",
        "Enlaces a otras webs que ya no existen: empeoran la experiencia y la confianza en el contenido.",
        "Actualiza el enlace a la nueva dirección o quítalo."),
    TipoProblema(
        "imagenes_sin_alt", "Imágenes sin alt", AVISO, 4, "imagenes",
        "Sin texto alternativo, ni los lectores de pantalla ni los buscadores saben qué muestra la imagen.",
        "Añade alt descriptivo; si la imagen es decorativa, usa alt=\"\".", unidad="imágenes"),
    TipoProblema(
        "sin_descripcion", "Páginas sin meta description", AVISO, 3, "descripciones",
        "Sin descripción, el buscador elige un fragmento cualquiera de la página para el resultado.",
        "Escribe una descripción de 120–160 caracteres que invite a hacer clic."),
    TipoProblema(
        "descripcion_duplicada", "Meta descriptions duplicadas", AVISO, 3, "descripciones",
        "Las descripciones repetidas no ayudan a distinguir las páginas en los resultados.",
        "Escribe una descripción propia para cada página.", agrupar=True),
    TipoProblema(
        "canonica_multiple", "Varias canónicas en la misma página", AVISO, 3, "canonicas",
        "Con varias canónicas distintas el buscador las ignora todas.",
        "Deja una sola etiqueta <link rel=\"canonical\">."),
    TipoProblema(
        "noindex", "Páginas con noindex", AVISO, 3, "indexacion",
        "Estas páginas piden no aparecer en los buscadores. Está bien si es a propósito; si no, son visitas perdidas.",
        "Quita el noindex (meta robots o cabecera X-Robots-Tag) de las páginas que deban posicionar."),
    TipoProblema(
        "titulo_largo", f"Títulos de más de {LARGO_MAX_TITULO} caracteres", AVISO, 2, "titulos",
        "Los títulos largos se cortan con «…» en los resultados y pierden el final del mensaje.",
        "Resume el título y pon lo importante al principio."),
    TipoProblema(
        "varios_h1", "Páginas con varios <h1>", AVISO, 2, "encabezados",
        "Varios h1 diluyen el tema principal y rompen la jerarquía de encabezados.",
        "Deja un h1 y convierte el resto en h2."),
    TipoProblema(
        "sin_canonica", "Páginas sin canónica", AVISO, 2, "canonicas",
        "Sin canónica, parámetros o versiones duplicadas de la URL pueden competir entre sí.",
        "Añade <link rel=\"canonical\"> apuntando a la propia URL limpia."),
    TipoProblema(
        "sin_idioma", "Páginas sin atributo lang", AVISO, 2, "idioma",
        "El atributo lang indica el idioma a buscadores y lectores de pantalla.",
        "Añade lang=\"es\" (o el idioma que toque) a la etiqueta <html>."),
    TipoProblema(
        "descripcion_larga", f"Meta descriptions de más de {LARGO_MAX_DESCRIPCION} caracteres", AVISO, 1, "descripciones",
        "Las descripciones largas se cortan en los resultados.",
        f"Déjala por debajo de {LARGO_MAX_DESCRIPCION} caracteres."),
    TipoProblema(
        "enlace_a_redireccion", "Enlaces internos a redirecciones", INFO, 1, "redirecciones",
        "El enlace funciona, pero obliga a un salto extra en cada visita y en cada rastreo.",
        "Enlaza directamente a la URL final."),
    TipoProblema(
        "sin_datos_estructurados", "Páginas sin datos estructurados", INFO, 1, "estructurados",
        "Los datos estructurados (JSON-LD de Schema.org) ayudan a buscadores y motores generativos a entender la página.",
        "Añade un bloque <script type=\"application/ld+json\"> con el tipo que corresponda (Article, Product, Organization…)."),
    TipoProblema(
        "sin_llms_txt", "Sin llms.txt", INFO, 1, "geo",
        "llms.txt es una propuesta para resumir la web a los modelos de lenguaje. No afecta a Google, pero ayuda en motores generativos.",
        "Publica /llms.txt con un resumen de la web y enlaces a las páginas clave."),
    TipoProblema(
        "bloqueada_robots", "URL no rastreadas por robots.txt", INFO, 0, "rastreo",
        "Enlaces internos que robots.txt impide rastrear. No resta puntos: es para comprobar que se bloquea lo que debe.",
        "Si alguna debería aparecer en buscadores, quítala del Disallow de robots.txt."),
]
TIPOS: dict[str, TipoProblema] = {t.id: t for t in _TIPOS}


def _cadena(url: str, respuestas: dict[str, Respuesta]) -> tuple[list[str], bool]:
    """Reconstruye la cadena de redirecciones que empieza en url. Devuelve (saltos, es_bucle)."""
    cadena, vistos = [url], {url}
    actual = respuestas.get(url)
    while actual is not None and actual.es_redireccion:
        siguiente = actual.destino
        cadena.append(siguiente)
        if siguiente in vistos:
            return cadena, True
        vistos.add(siguiente)
        actual = respuestas.get(siguiente)
    return cadena, False


def _origenes_navegables(resultado: ResultadoRastreo, url: str) -> list[str]:
    tipos = resultado.origenes.get(url, {})
    return sorted(tipos.get("enlace", set()) | tipos.get("redireccion", set()))


def comprobar_enlaces(resultado: ResultadoRastreo) -> list[Hallazgo]:
    hallazgos = []
    for url, r in resultado.respuestas.items():
        tipos = resultado.origenes.get(url, {})
        # Una URL que solo aparece como canónica se trata en las comprobaciones de canónicas.
        if r.es_error and tipos.keys() & {"enlace", "redireccion", "inicio"}:
            hallazgos.append(Hallazgo("enlace_roto_interno", url, r.describir_estado(),
                                      _origenes_navegables(resultado, url), "Enlazada desde"))
    for url, r in resultado.externos.items():
        if not r.omitida and (r.es_error or r.error):
            hallazgos.append(Hallazgo("enlace_roto_externo", url, r.describir_estado() if not r.error else r.error,
                                      sorted(resultado.enlaces_externos[url]), "Enlazada desde"))
    return hallazgos


def comprobar_redirecciones(resultado: ResultadoRastreo) -> list[Hallazgo]:
    hallazgos = []
    for url, r in resultado.respuestas.items():
        if not r.es_redireccion:
            continue
        tipos = resultado.origenes.get(url, {})
        # Solo se informa desde el principio de cada cadena, no desde sus saltos intermedios.
        if not tipos.keys() - {"redireccion"}:
            continue
        cadena, bucle = _cadena(url, resultado.respuestas)
        recorrido = " → ".join(cadena)
        origen = sorted(tipos.get("enlace", set()))
        if bucle:
            hallazgos.append(Hallazgo("bucle_redireccion", url, recorrido, origen, "Enlazada desde"))
        elif len(cadena) - 1 >= MIN_SALTOS_CADENA:
            hallazgos.append(Hallazgo("cadena_redirecciones", url, f"{len(cadena) - 1} saltos: {recorrido}", origen, "Enlazada desde"))
        if origen:
            hallazgos.append(Hallazgo("enlace_a_redireccion", url, f"→ {cadena[-1]}", origen, "Enlazada desde"))
    return hallazgos


def _duplicados(valores: dict[str, str], tipo: str) -> list[Hallazgo]:
    grupos: defaultdict[str, list[str]] = defaultdict(list)
    for url, valor in valores.items():
        grupos[valor].append(url)
    return [Hallazgo(tipo, url, valor) for valor, urls in grupos.items() if len(urls) > 1 for url in sorted(urls)]


def comprobar_paginas(resultado: ResultadoRastreo) -> list[Hallazgo]:
    hallazgos: list[Hallazgo] = []
    titulos: dict[str, str] = {}
    descripciones: dict[str, str] = {}
    for url, p in sorted(resultado.paginas.items()):
        noindex_cabecera = resultado.respuestas[url].noindex_cabecera
        # Solo compiten entre sí las páginas indexables: si una tiene noindex o su canónica apunta
        # a otra URL, que repita título o descripción no es un problema.
        indexable = not (p.noindex or noindex_cabecera) and (not p.canonicas or p.canonicas[0] == url)

        titulo = next((t for t in p.titulos if t), "")
        if not titulo:
            hallazgos.append(Hallazgo("sin_titulo", url))
        else:
            if indexable:
                titulos[url] = titulo
            if len(titulo) > LARGO_MAX_TITULO:
                hallazgos.append(Hallazgo("titulo_largo", url, f"{len(titulo)} caracteres: {titulo}"))

        descripcion = next((d for d in p.descripciones if d), "")
        if not descripcion:
            hallazgos.append(Hallazgo("sin_descripcion", url))
        else:
            if indexable:
                descripciones[url] = descripcion
            if len(descripcion) > LARGO_MAX_DESCRIPCION:
                hallazgos.append(Hallazgo("descripcion_larga", url, f"{len(descripcion)} caracteres: {descripcion}"))

        if not p.h1:
            hallazgos.append(Hallazgo("sin_h1", url))
        elif len(p.h1) > 1:
            hallazgos.append(Hallazgo("varios_h1", url, f"{len(p.h1)} h1", p.h1, "Encabezados"))

        if p.imagenes_sin_alt:
            n = len(p.imagenes_sin_alt)
            hallazgos.append(Hallazgo("imagenes_sin_alt", url, f"{n} {'imagen' if n == 1 else 'imágenes'}",
                                      p.imagenes_sin_alt, "Imágenes", elementos=n))

        if not p.idioma:
            hallazgos.append(Hallazgo("sin_idioma", url))

        if p.noindex or noindex_cabecera:
            hallazgos.append(Hallazgo("noindex", url, "cabecera X-Robots-Tag" if noindex_cabecera else "meta robots"))

        if urlsplit(url).scheme == "https":
            inseguros = sorted({r for r in p.recursos if r.startswith("http://")})
            if inseguros:
                hallazgos.append(Hallazgo("contenido_mixto", url, f"{len(inseguros)} recursos por http", inseguros, "Recursos"))

        if p.jsonld_errores:
            hallazgos.append(Hallazgo("datos_estructurados_invalidos", url, f"{len(p.jsonld_errores)} bloques con errores",
                                      p.jsonld_errores, "Errores"))
        elif not p.jsonld_tipos:
            hallazgos.append(Hallazgo("sin_datos_estructurados", url))

        hallazgos += _comprobar_canonica(resultado, url, p.canonicas)

    hallazgos += _duplicados(titulos, "titulo_duplicado")
    hallazgos += _duplicados(descripciones, "descripcion_duplicada")
    return hallazgos


def _comprobar_canonica(resultado: ResultadoRastreo, url: str, canonicas: list[str]) -> list[Hallazgo]:
    if not canonicas:
        return [Hallazgo("sin_canonica", url)]
    hallazgos = []
    if len(set(canonicas)) > 1:
        hallazgos.append(Hallazgo("canonica_multiple", url, f"{len(set(canonicas))} canónicas distintas",
                                  sorted(set(canonicas)), "Canónicas"))
    canonica = canonicas[0]
    if anfitrion(canonica) != resultado.host:
        hallazgos.append(Hallazgo("canonica_otro_dominio", url, f"→ {canonica}"))
    elif canonica != url:
        destino = resultado.respuestas.get(canonica)
        # Si no se pudo pedir (robots.txt o límite de páginas) no se puede afirmar nada.
        if destino is not None and destino.estado != 200:
            hallazgos.append(Hallazgo("canonica_no_200", url, f"→ {canonica} ({destino.describir_estado()})"))
    return hallazgos


def comprobar_sitio(resultado: ResultadoRastreo) -> list[Hallazgo]:
    hallazgos = []
    llms = resultado.llms_txt
    if llms is not None and llms.estado != 200:
        hallazgos.append(Hallazgo("sin_llms_txt", llms.url, llms.describir_estado()))
    for url, origenes in sorted(resultado.bloqueadas.items()):
        hallazgos.append(Hallazgo("bloqueada_robots", url, "Disallow en robots.txt", sorted(origenes), "Enlazada desde"))
    return hallazgos


def comprobar(resultado: ResultadoRastreo) -> list[Hallazgo]:
    return (comprobar_enlaces(resultado) + comprobar_redirecciones(resultado)
            + comprobar_paginas(resultado) + comprobar_sitio(resultado))
