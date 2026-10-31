"""Web de prueba local: http.server en un hilo sirviendo tests/sitio con fallos a propósito."""

from __future__ import annotations

import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest

CARPETA_SITIO = Path(__file__).parent / "sitio"

REDIRECCIONES = {
    "/antigua": (301, "/intermedia"),
    "/intermedia": (302, "/sobre.html"),
    "/bucle-a": (301, "/bucle-b"),
    "/bucle-b": (301, "/bucle-a"),
}


class Manejador(SimpleHTTPRequestHandler):
    server: "ServidorPrueba"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(CARPETA_SITIO), **kwargs)

    def log_message(self, *args):  # silencio en la salida de pytest
        pass

    def do_GET(self):
        self._responder(con_cuerpo=True)

    def do_HEAD(self):
        self._responder(con_cuerpo=False)

    def _responder(self, con_cuerpo: bool) -> None:
        self.server.registro.append(
            (self.command, self.headers.get("Host", ""), unquote(self.path), self.headers.get("User-Agent", ""))
        )
        ruta = urlsplit(self.path).path
        if ruta in REDIRECCIONES:
            codigo, destino = REDIRECCIONES[ruta]
            self.send_response(codigo)
            self.send_header("Location", destino)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if ruta == "/caida":
            self.send_error(500)
            return
        fichero = Path(self.translate_path(self.path))
        if fichero.is_dir():
            fichero = fichero / "index.html"
        if not fichero.is_file():
            self.send_error(404)
            return
        # Las páginas llevan __PUERTO__ para poder enlazar a "otro dominio" (localhost) del mismo servidor.
        cuerpo = fichero.read_bytes().replace(b"__PUERTO__", str(self.server.server_port).encode())
        tipo = "text/html; charset=utf-8" if fichero.suffix == ".html" else "text/plain; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        if con_cuerpo:
            self.wfile.write(cuerpo)


class ServidorPrueba(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self):
        super().__init__(("127.0.0.1", 0), Manejador)
        self.registro: list[tuple[str, str, str, str]] = []  # (método, host, ruta, user-agent)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_port}/"


@pytest.fixture(scope="session")
def servidor():
    srv = ServidorPrueba()
    hilo = threading.Thread(target=srv.serve_forever, daemon=True)
    hilo.start()
    yield srv
    srv.shutdown()
    srv.server_close()
