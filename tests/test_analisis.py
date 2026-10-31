from rastreo.analisis import analizar_html
from rastreo.urls import normalizar, resolver

BASE = "https://ejemplo.es/blog/entrada"


def test_extrae_metadatos_basicos():
    datos = analizar_html("""
        <html lang="es"><head>
          <title>  Cómo   pintar\n una pared </title>
          <meta name="Description" content=" Guía paso a paso ">
          <link rel="canonical" href="/blog/entrada">
        </head><body>
          <svg><title>Icono</title></svg>
          <h1>Pintar una pared</h1>
        </body></html>""", BASE)
    assert datos.titulos == ["Cómo pintar una pared"]  # el <title> del svg no cuenta
    assert datos.descripciones == ["Guía paso a paso"]
    assert datos.h1 == ["Pintar una pared"]
    assert datos.canonicas == ["https://ejemplo.es/blog/entrada"]
    assert datos.idioma == "es"
    assert not datos.noindex


def test_imagenes_sin_alt_ignora_las_decorativas():
    datos = analizar_html('<img src="a.jpg"><img src="b.jpg" alt=""><img src="c.jpg" alt="Rodillo"><img>', BASE)
    assert datos.imagenes_sin_alt == ["https://ejemplo.es/blog/a.jpg", "(sin src)"]


def test_enlaces_resueltos_sin_duplicados_ni_esquemas_raros():
    datos = analizar_html("""
        <a href="otra">1</a><a href="/blog/otra#comentarios">2</a><a href="#arriba">3</a>
        <a href="mailto:hola@ejemplo.es">4</a><a href="javascript:alert(1)">5</a><a href="tel:+34600000000">6</a>
        <a href="HTTPS://Ejemplo.ES:443/Contacto?x=1">7</a><a href="ftp://ejemplo.es/a">8</a>
        <map><area href="/mapa" alt="Mapa"></map>""", BASE)
    assert datos.enlaces == ["https://ejemplo.es/blog/otra", "https://ejemplo.es/Contacto?x=1", "https://ejemplo.es/mapa"]


def test_respeta_base_href():
    datos = analizar_html('<base href="https://ejemplo.es/tienda/"><a href="silla">Silla</a>', BASE)
    assert datos.enlaces == ["https://ejemplo.es/tienda/silla"]


def test_noindex_por_meta_robots_o_none():
    assert analizar_html('<meta name="robots" content="index, NOINDEX">', BASE).noindex
    assert analizar_html('<meta name="googlebot" content="none">', BASE).noindex
    assert not analizar_html('<meta name="robots" content="index, follow">', BASE).noindex


def test_recursos_para_contenido_mixto():
    datos = analizar_html("""
        <link rel="stylesheet" href="http://cdn.ejemplo.es/estilo.css"><link rel="alternate" href="http://x.es/feed">
        <script src="http://cdn.ejemplo.es/app.js"></script><img src="/foto.jpg" alt="Foto">
        <iframe src="http://mapas.ejemplo.es/"></iframe>""", BASE)
    assert datos.recursos == ["http://cdn.ejemplo.es/estilo.css", "http://cdn.ejemplo.es/app.js",
                              "https://ejemplo.es/foto.jpg", "http://mapas.ejemplo.es/"]


def test_json_ld_valido_e_invalido():
    datos = analizar_html("""
        <script type="application/ld+json">{"@context":"https://schema.org","@graph":[{"@type":"WebSite"},{"@type":["Person","Thing"]}]}</script>
        <script type="application/ld+json">{"@type": "Product", "name": "Taladro",}</script>""", BASE)
    assert datos.jsonld_tipos == ["WebSite", "Person", "Thing"]
    assert len(datos.jsonld_errores) == 1 and datos.jsonld_errores[0].startswith("Bloque 2:")


def test_normalizar_urls():
    assert normalizar("HTTP://Ejemplo.es:80") == "http://ejemplo.es/"
    assert normalizar("https://usuario:clave@ejemplo.es/a#b") == "https://ejemplo.es/a"  # sin credenciales
    assert normalizar("https://ejemplo.es:8443/a?b=1") == "https://ejemplo.es:8443/a?b=1"
    assert normalizar("file:///etc/passwd") is None
    assert normalizar("https://[::1]:8000/") == "https://[::1]:8000/"
    assert normalizar("http://ejemplo.es:99999/") is None
    assert resolver(BASE, "  ../sobre  ") == "https://ejemplo.es/sobre"
    assert resolver(BASE, "data:text/html,hola") is None
