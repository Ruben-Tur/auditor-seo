# rastreo · auditor de SEO técnico

Herramienta de línea de comandos que recorre todas las páginas de una web, igual que lo haría un buscador, y genera un informe HTML con los fallos de SEO técnico ordenados por prioridad y con la URL exacta de cada uno.

```text
$ python -m rastreo https://ejemplo.es --informe
Rastreadas 412 URL en 38,2 s · 398 páginas analizadas · 3 bloqueadas por robots.txt

✗ Enlaces internos rotos                        17
✗ Páginas sin <h1>                              9
! Títulos duplicados                            23
! Imágenes sin alt                              64
! Meta descriptions de más de 160 caracteres    31
✓ Canónicas correctas                           398

→ Informe guardado en informe-ejemplo-es.html

Puntuación  █████████████████░░░░░░░  72/100
```

## Características

- **Rastreo asíncrono** con httpx: varias peticiones a la vez (`--concurrencia`) pero con un límite de peticiones por segundo (`--por-segundo`) para no cargar el servidor que se analiza.
- **Respeta robots.txt** (`urllib.robotparser`), incluido `Crawl-delay` con decimales, y se identifica con un User-Agent propio: `rastreo/0.1.0 (+https://github.com/Ruben-Tur/auditor-seo)`.
- Sigue solo los enlaces del mismo host y registra el código de estado de cada URL y cada salto de redirección.
- **Comprobaciones:**
  - Enlaces internos rotos (4xx, 5xx o sin respuesta) con las páginas que los enlazan; enlaces externos rotos con `--externos`.
  - Redirecciones en cadena (2 saltos o más), bucles de redirección y enlaces internos que apuntan a una redirección.
  - Títulos que faltan, duplicados o de más de 60 caracteres.
  - Meta descriptions que faltan, duplicadas o de más de 160 caracteres.
  - Páginas sin `<h1>` o con varios.
  - Imágenes sin atributo `alt` (`alt=""` se acepta: es lo correcto en imágenes decorativas).
  - Canónicas que faltan, varias en la misma página, que apuntan a otro dominio o a una URL que no responde 200.
  - Páginas con `noindex` (meta robots o cabecera `X-Robots-Tag`) y sin atributo `lang`.
  - Contenido mixto: recursos por `http://` en páginas `https://`.
  - Datos estructurados JSON-LD con errores de sintaxis o páginas sin ninguno, y si la web publica `/llms.txt` (para motores generativos).
  - URL enlazadas que robots.txt impide rastrear (informativo: sirve para comprobar que se bloquea lo que debe).
- **Puntuación de 0 a 100** y problemas ordenados por impacto (ver «Cómo se puntúa»).
- **Informe HTML autocontenido**: un solo archivo, sin peticiones externas ni JavaScript, con modo claro y oscuro, y listas de URL plegables.
- **Salida JSON** (`--json`) para automatizar, y `--minimo N` para que un proceso de CI falle si la nota baja de N.
- Salida por terminal con colores que se desactivan solos si la salida no es una terminal o si existe la variable `NO_COLOR`.

## Tecnologías

| Pieza | Para qué |
| --- | --- |
| Python 3.11+ | Lenguaje (probado con 3.13) |
| httpx | Peticiones HTTP asíncronas con límite de conexiones y tiempos de espera |
| BeautifulSoup 4 | Análisis del HTML (con lxml si está instalado; si no, el parser de la biblioteca estándar) |
| Jinja2 | Plantilla del informe HTML, con autoescape activado |
| pytest | Pruebas, con una web de prueba local servida por `http.server` |

## Requisitos

- Python 3.11 o superior.
- Conexión con la web que se quiere auditar. Las pruebas no necesitan red.

## Instalación

```powershell
git clone https://github.com/Ruben-Tur/auditor-seo.git
cd auditor-seo
python -m venv .venv
.venv\Scripts\activate           # en macOS o Linux: source .venv/bin/activate
pip install httpx beautifulsoup4 jinja2 lxml pytest
```

Con eso ya funciona `python -m rastreo` desde la carpeta del proyecto. Para tener además el comando `rastreo` en cualquier carpeta, instala el paquete (descarga setuptools para construirlo):

```powershell
pip install -e ".[rapido,dev]"
```

`lxml` es opcional: acelera el análisis, pero si tu sistema no lo admite (por ejemplo, Windows con Control inteligente de aplicaciones bloqueando binarios recién compilados) la herramienta usa `html.parser` sin tocar nada.

## Uso

```powershell
# Rastreo con informe HTML (sin ruta: informe-<dominio>.html)
python -m rastreo https://ejemplo.es --informe
python -m rastreo https://ejemplo.es --informe auditorias/ejemplo.html

# Más despacio y con enlaces externos
python -m rastreo https://ejemplo.es --informe --por-segundo 1 --concurrencia 2 --externos

# JSON por la salida estándar (el resumen va entonces por stderr) y fallo si la nota baja de 80
python -m rastreo https://ejemplo.es --json --minimo 80 > resultado.json
```

| Opción | Por defecto | Qué hace |
| --- | --- | --- |
| `--informe [RUTA]` | — | Guarda el informe HTML |
| `--json [RUTA]` | — | Guarda el resultado en JSON (sin ruta o con `-`, por la salida estándar) |
| `--concurrencia N` | 5 | Peticiones simultáneas (1–50) |
| `--por-segundo N` | 5 | Máximo de peticiones por segundo (0,1–50) |
| `--max-paginas N` | 500 | Máximo de URL internas a rastrear |
| `--timeout S` | 10 | Tiempo de espera por petición, en segundos |
| `--externos` | no | Comprueba también los enlaces a otros dominios (HEAD y, si falla, GET) |
| `--minimo N` | — | Código de salida 1 si la puntuación queda por debajo de N |

Códigos de salida: `0` todo bien, `1` no se pudo rastrear o la nota no llega a `--minimo`, `2` argumentos incorrectos, `130` interrumpido con Ctrl+C.

### Cómo se puntúa

Cada tipo de problema tiene un peso (lo máximo que puede restar: 12 los enlaces internos rotos, 6 las páginas sin h1, 1 las descripciones largas…). Lo que resta depende de la proporción de páginas afectadas:

```text
impacto = peso × (0,3 + 0,7 × √(URL afectadas / páginas analizadas))
puntuación = 100 − suma de impactos   (mínimo 0)
```

Un problema en una sola URL ya resta el 30 % de su peso; si afecta a todas las páginas, lo resta entero. La raíz cuadrada hace que los primeros casos se noten sin que una web grande se hunda por unas pocas URL. El informe ordena los problemas por ese impacto: los primeros son los que más suben la nota al arreglarlos.

### Límites y seguridad

- Solo se siguen URL `http://` y `https://` del mismo host; `mailto:`, `javascript:`, `data:`, `file:` y similares se ignoran.
- Si la URL inicial es pública, nunca se piden direcciones privadas, de loopback o locales (por ejemplo, un enlace o una redirección a `http://192.168.1.1/`). Si la URL inicial es local (`localhost`, `127.0.0.1`…), se permite, porque es lo que se ha pedido auditar.
- De cada página HTML se leen como mucho 5 MB y de robots.txt 500 kB; del resto de archivos (PDF, imágenes) solo se miran las cabeceras.
- Tiempo de espera por petición configurable, `Crawl-delay` limitado a 60 s y un máximo de páginas por rastreo.
- Si robots.txt responde con un error 5xx no se rastrea nada (lo que indica el RFC 9309); si no existe (4xx), todo está permitido.
- Todo lo que viene de la web rastreada (títulos, URL, descripciones, texto alternativo) se trata como entrada no fiable: la plantilla escapa siempre y el informe lleva una Content-Security-Policy sin scripts (`default-src 'none'` y el CSS autorizado por su hash), `referrer` desactivado y `noindex`.

### Datos que guarda

Ninguno por su cuenta: no hay base de datos, caché ni registros. Solo escribe los archivos que le pidas con `--informe` y `--json`, en la ruta indicada. Esos informes pueden contener URL internas de la web auditada, así que el `.gitignore` los excluye y el HTML lleva `noindex` por si acaba publicado por error.

## Estructura

```text
auditor-seo/
├── rastreo/
│   ├── __main__.py        # python -m rastreo
│   ├── cli.py             # argumentos, validación y flujo principal
│   ├── rastreador.py      # rastreo asíncrono, robots.txt, límite de peticiones
│   ├── analisis.py        # extracción de título, h1, canónicas, enlaces… con BeautifulSoup
│   ├── comprobaciones.py  # tipos de problema (gravedad, peso, explicación) y comprobaciones
│   ├── puntuacion.py      # agrupación, impacto y puntuación global
│   ├── informe.py         # informe HTML (Jinja) y JSON
│   ├── terminal.py        # colores, progreso y resumen final
│   ├── urls.py            # normalización de URL y detección de direcciones privadas
│   ├── formato.py         # números y fechas en español
│   └── plantillas/        # informe.html y estilos.css
├── tests/
│   ├── conftest.py        # servidor http.server en un hilo con la web de prueba
│   ├── sitio/             # páginas con fallos a propósito, robots.txt y una página con XSS
│   ├── test_rastreo.py    # rastreo completo: encuentra exactamente los fallos sembrados
│   ├── test_seguridad.py  # https, red local, robots.txt, límites (con httpx.MockTransport)
│   ├── test_analisis.py   # análisis de HTML y normalización de URL
│   └── test_puntuacion.py # fórmula de impacto, orden y puntuación
└── pyproject.toml
```

## Pruebas

```powershell
python -m pytest
```

Las pruebas levantan una web local en un puerto libre con páginas que tienen fallos a propósito (enlaces rotos, un 500, una cadena de redirecciones, un bucle, títulos y descripciones duplicados, canónicas mal puestas, una zona bloqueada por robots.txt…) y comprueban que el rastreo encuentra exactamente esos problemas, ni uno más. También comprueban que nunca se pide nada de lo que prohíbe robots.txt, que el informe escapa una página con `<script>` y atributos `onerror` inyectados, que no se sale a la red local y que se respetan los límites de páginas y de peticiones por segundo. No necesitan conexión a internet.

---

Hecho por [Rubén Tur](https://github.com/Ruben-Tur).
