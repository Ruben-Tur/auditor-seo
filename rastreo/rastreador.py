"""Rastreador asíncrono: recorre las páginas internas de una web respetando robots.txt."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from . import USER_AGENT
from .analisis import analizar_html
from .formato import miles
from .modelos import Respuesta, ResultadoRastreo
from .urls import anfitrion, es_host_privado, nombre_host, normalizar

MAX_SALTOS_INICIO = 5
MAX_CRAWL_DELAY = 60.0  # un valor absurdo no debe dejar el rastreo colgado durante días
MAX_BYTES_ROBOTS = 500_000  # el mismo límite que aplica Google
TIPOS_HTML = ("text/html", "application/xhtml+xml")


class ErrorRastreo(Exception):
    """Error que impide empezar el rastreo (URL inválida, web caída, robots.txt lo prohíbe…)."""


@dataclass
class Opciones:
    concurrencia: int = 5
    por_segundo: float = 5.0
    max_paginas: int = 500
    timeout: float = 10.0
    externos: bool = False
    user_agent: str = USER_AGENT
    max_bytes: int = 5_000_000  # se deja de leer una respuesta HTML al pasar de este tamaño


class LimitadorPeticiones:
    """Reparte las peticiones en el tiempo para no pasar de N por segundo, sea cual sea la concurrencia."""

    def __init__(self, por_segundo: float) -> None:
        self.intervalo = 1.0 / por_segundo
        self._siguiente = 0.0
        self._cerrojo = asyncio.Lock()

    async def esperar(self) -> None:
        async with self._cerrojo:
            ahora = time.monotonic()
            if self._siguiente > ahora:
                await asyncio.sleep(self._siguiente - ahora)
                ahora = time.monotonic()
            self._siguiente = max(ahora, self._siguiente) + self.intervalo


def crawl_delay(robots: str, user_agent: str) -> float | None:
    """Lee Crawl-delay admitiendo decimales (urllib.robotparser solo acepta enteros).

    Usa el grupo cuyo User-agent coincide con el nuestro y, si no hay, el de «*».
    """
    nombre = user_agent.split("/")[0].lower()
    retrasos: dict[str, float] = {}
    agentes: list[str] = []
    leyendo_agentes = False
    for linea in robots.splitlines():
        clave, _, valor = linea.split("#")[0].partition(":")
        clave, valor = clave.strip().lower(), valor.strip()
        if clave == "user-agent":
            agentes = agentes + [valor.lower()] if leyendo_agentes else [valor.lower()]
            leyendo_agentes = True
            continue
        leyendo_agentes = False
        if clave == "crawl-delay":
            try:
                segundos = float(valor)
            except ValueError:
                continue
            if segundos > 0:
                for agente in agentes:
                    retrasos[agente] = min(segundos, MAX_CRAWL_DELAY)
    propio = next((v for a, v in retrasos.items() if a != "*" and a in nombre), None)
    return propio if propio is not None else retrasos.get("*")


def _describir_error(error: httpx.HTTPError) -> str:
    if isinstance(error, httpx.TimeoutException):
        return "Tiempo de espera agotado"
    if isinstance(error, httpx.ConnectError):
        return "No se pudo conectar"
    if isinstance(error, httpx.RemoteProtocolError):
        return "Respuesta HTTP no válida"
    return f"Error de red ({type(error).__name__})"


class Rastreador:
    def __init__(
        self,
        inicio: str,
        opciones: Opciones | None = None,
        al_progresar: Callable[[int, int], None] | None = None,
        transporte: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        url = normalizar(inicio)
        if url is None:
            raise ErrorRastreo(f"La URL «{inicio}» no es válida: tiene que empezar por http:// o https://")
        self.opciones = opciones or Opciones()
        self.resultado = ResultadoRastreo(inicio=url, host=anfitrion(url))
        self._al_progresar = al_progresar
        self._transporte = transporte
        self._limitador = LimitadorPeticiones(self.opciones.por_segundo)
        self._robots = RobotFileParser()
        self._cola: asyncio.Queue[str] = asyncio.Queue()
        self._vistas: set[str] = set()
        self._inicio_local = False

    # --- API pública -------------------------------------------------------

    async def ejecutar(self) -> ResultadoRastreo:
        comienzo = time.monotonic()
        async with httpx.AsyncClient(
            headers={"User-Agent": self.opciones.user_agent, "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5"},
            timeout=self.opciones.timeout,
            follow_redirects=False,
            limits=httpx.Limits(max_connections=self.opciones.concurrencia),
            transport=self._transporte,
        ) as self._cliente:
            await self._preparar_inicio()
            self._descubrir(self.resultado.inicio, None, "inicio")
            trabajadores = [asyncio.create_task(self._trabajador()) for _ in range(self.opciones.concurrencia)]
            try:
                await self._cola.join()
            finally:
                for t in trabajadores:
                    t.cancel()
                await asyncio.gather(*trabajadores, return_exceptions=True)
            await self._comprobar_llms_txt()
            if self.opciones.externos:
                await self._comprobar_externos()
        self.resultado.duracion = time.monotonic() - comienzo
        return self.resultado

    # --- Preparación -------------------------------------------------------

    async def _preparar_inicio(self) -> None:
        """Carga robots.txt y, si la URL inicial redirige a otro host (www, https…), audita ese host."""
        self._inicio_local = await es_host_privado(nombre_host(self.resultado.inicio))
        for _ in range(MAX_SALTOS_INICIO):
            await self._cargar_robots()
            url = self.resultado.inicio
            if not self._permitida(url):
                raise ErrorRastreo(f"El robots.txt de {self.resultado.host} no permite rastrear {url}")
            await self._limitador.esperar()
            try:
                async with self._cliente.stream("GET", url) as r:
                    destino = r.headers.get("location") if r.is_redirect else None
            except httpx.HTTPError as error:
                raise ErrorRastreo(f"No se pudo acceder a {url}: {_describir_error(error)}") from error
            nuevo = normalizar(urljoin(url, destino)) if destino else None
            if not nuevo or anfitrion(nuevo) == self.resultado.host:
                return
            if not self._inicio_local and await es_host_privado(nombre_host(nuevo)):
                raise ErrorRastreo(f"{url} redirige a una dirección privada ({nuevo}); no se sigue")
            self.resultado.avisos.append(f"{url} redirige a {nuevo}: se audita {anfitrion(nuevo)}")
            self.resultado.inicio, self.resultado.host = nuevo, anfitrion(nuevo)
        raise ErrorRastreo("La URL inicial redirige demasiadas veces entre dominios")

    async def _cargar_robots(self) -> None:
        esquema = urlsplit(self.resultado.inicio).scheme
        url_robots = f"{esquema}://{self.resultado.host}/robots.txt"
        self._robots = RobotFileParser(url_robots)
        await self._limitador.esperar()
        try:
            async with self._cliente.stream("GET", url_robots, follow_redirects=True) as r:
                estado = r.status_code
                texto = (await self._leer_limitado(r, MAX_BYTES_ROBOTS)).decode("utf-8", "replace") if estado == 200 else ""
        except httpx.HTTPError as error:
            raise ErrorRastreo(f"No se pudo leer {url_robots}: {_describir_error(error)}") from error
        if estado >= 500:
            # RFC 9309: si robots.txt no está disponible por un error del servidor, se asume que no se permite nada.
            raise ErrorRastreo(f"{url_robots} responde {estado}: por prudencia no se rastrea")
        # Con un 4xx (no hay robots.txt) todo está permitido, igual que hacen los buscadores.
        self._robots.parse(texto.splitlines())
        retraso = crawl_delay(texto, self.opciones.user_agent)
        if retraso and retraso > self._limitador.intervalo:
            self._limitador.intervalo = retraso
            self.resultado.avisos.append(f"robots.txt pide Crawl-delay: {retraso} s; se respeta")

    def _permitida(self, url: str) -> bool:
        return self._robots.can_fetch(self.opciones.user_agent, url)

    # --- Rastreo -----------------------------------------------------------

    def _descubrir(self, url: str | None, origen: str | None, tipo: str) -> None:
        """Registra una URL encontrada y la encola si es interna, está permitida y no se ha visto."""
        if url is None:
            return
        if anfitrion(url) != self.resultado.host:
            if tipo == "enlace" and origen:
                self.resultado.enlaces_externos[url].add(origen)
            return
        procedencia = self.resultado.origenes[url].setdefault(tipo, set())
        if origen:
            procedencia.add(origen)
        if url in self._vistas:
            return
        if url in self.resultado.bloqueadas or not self._permitida(url):
            bloqueada = self.resultado.bloqueadas.setdefault(url, set())
            if origen:
                bloqueada.add(origen)
            return
        if len(self._vistas) >= self.opciones.max_paginas:
            self.resultado.limite_alcanzado = True
            return
        self._vistas.add(url)
        self._cola.put_nowait(url)

    async def _trabajador(self) -> None:
        while True:
            url = await self._cola.get()
            try:
                try:
                    respuesta = await self._pedir(url, leer_html=True)
                except Exception as error:  # noqa: BLE001 - una página rara no debe tumbar el rastreo entero
                    respuesta = Respuesta(url=url, error=f"Error inesperado ({type(error).__name__})")
                self.resultado.respuestas[url] = respuesta
                if respuesta.es_redireccion:
                    self._descubrir(respuesta.destino, url, "redireccion")
                if respuesta.pagina:
                    for enlace in respuesta.pagina.enlaces:
                        self._descubrir(enlace, url, "enlace")
                    for canonica in respuesta.pagina.canonicas[:1]:
                        self._descubrir(canonica, url, "canonica")
            finally:
                self._cola.task_done()
                if self._al_progresar:
                    self._al_progresar(len(self.resultado.respuestas), self._cola.qsize())

    async def _pedir(self, url: str, leer_html: bool) -> Respuesta:
        respuesta = Respuesta(url=url)
        await self._limitador.esperar()
        comienzo = time.perf_counter()
        cuerpo: bytes | None = None
        try:
            async with self._cliente.stream("GET", url) as r:
                respuesta.estado = r.status_code
                respuesta.tipo = r.headers.get("content-type", "")
                if r.is_redirect and r.headers.get("location"):
                    respuesta.destino = normalizar(urljoin(url, r.headers["location"]))
                etiquetas_robots = r.headers.get("x-robots-tag", "").lower()
                respuesta.noindex_cabecera = "noindex" in etiquetas_robots or "none" in etiquetas_robots
                if leer_html and r.status_code == 200 and respuesta.tipo.lower().startswith(TIPOS_HTML):
                    cuerpo = await self._leer_limitado(r, self.opciones.max_bytes)
        except httpx.HTTPError as error:
            respuesta.error = _describir_error(error)
        respuesta.ms = round((time.perf_counter() - comienzo) * 1000)
        if cuerpo is not None:
            # El análisis es CPU pura: en un hilo para no frenar las descargas en curso.
            respuesta.pagina = await asyncio.to_thread(analizar_html, cuerpo, url)
        return respuesta

    async def _leer_limitado(self, r: httpx.Response, limite: int) -> bytes:
        trozos: list[bytes] = []
        total = 0
        async for trozo in r.aiter_bytes():
            total += len(trozo)
            if total > limite:
                self.resultado.avisos.append(f"{r.url} pasa de {miles(limite // 1000)} kB: se analiza solo el principio")
                break
            trozos.append(trozo)
        return b"".join(trozos)

    # --- Comprobaciones extra ---------------------------------------------

    async def _comprobar_llms_txt(self) -> None:
        esquema = urlsplit(self.resultado.inicio).scheme
        url = f"{esquema}://{self.resultado.host}/llms.txt"
        if self._permitida(url):
            self.resultado.llms_txt = await self._pedir(url, leer_html=False)

    async def _comprobar_externos(self) -> None:
        """Comprueba los enlaces a otros dominios con HEAD (y GET si el servidor no acepta HEAD)."""
        pendientes = sorted(self.resultado.enlaces_externos)[: self.opciones.max_paginas]
        semaforo = asyncio.Semaphore(self.opciones.concurrencia)

        async def comprobar(url: str) -> None:
            async with semaforo:
                try:
                    self.resultado.externos[url] = await self._comprobar_externo(url)
                except Exception as error:  # noqa: BLE001
                    self.resultado.externos[url] = Respuesta(url=url, error=f"Error inesperado ({type(error).__name__})")

        await asyncio.gather(*(comprobar(u) for u in pendientes))

    async def _comprobar_externo(self, url: str) -> Respuesta:
        """Sigue a mano las redirecciones para no acabar pidiendo nada a la red local."""
        respuesta = Respuesta(url=url)
        actual = url
        try:
            for _ in range(MAX_SALTOS_INICIO + 1):
                if not self._inicio_local and await es_host_privado(nombre_host(actual)):
                    respuesta.error = "Dirección privada: no se comprueba"
                    respuesta.omitida = True
                    self.resultado.externos_omitidos.append(actual)
                    return respuesta
                for metodo in ("HEAD", "GET"):  # hay servidores que no aceptan HEAD
                    await self._limitador.esperar()
                    async with self._cliente.stream(metodo, actual) as r:
                        respuesta.estado = r.status_code
                        siguiente = r.headers.get("location") if r.is_redirect else None
                    if r.status_code < 400:
                        break
                if not siguiente:
                    return respuesta
                actual = normalizar(urljoin(actual, siguiente)) or ""
                if not actual:
                    respuesta.error = "Redirección a un esquema no http(s)"
                    return respuesta
            respuesta.error = "Demasiadas redirecciones"
        except httpx.HTTPError as error:
            respuesta.error = _describir_error(error)
        return respuesta
