"""Salida por terminal: colores (si procede), línea de progreso y resumen final."""

from __future__ import annotations

import os
import time
from typing import TextIO

from .formato import decimal, miles
from .puntuacion import Auditoria

COLORES = {"rojo": "31", "ambar": "33", "verde": "32", "azul": "36", "tenue": "2", "negrita": "1", "subrayado": "4"}
MARCAS = {"error": ("✗", "rojo"), "aviso": ("!", "ambar"), "info": ("i", "azul")}
ANCHO_BARRA = 24


def _activar_vt_windows(flujo: TextIO) -> bool:
    """Activa las secuencias ANSI en la consola de Windows. Devuelve False si no se puede."""
    if os.name != "nt":
        return True
    try:
        import ctypes
        import msvcrt

        kernel32 = ctypes.windll.kernel32
        manejador = msvcrt.get_osfhandle(flujo.fileno())
        modo = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(manejador, ctypes.byref(modo)):
            return False
        return bool(kernel32.SetConsoleMode(manejador, modo.value | 0x0004))  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    except (OSError, AttributeError, ValueError):
        return False


def usar_colores(flujo: TextIO) -> bool:
    # https://no-color.org: cualquier valor no vacío de NO_COLOR desactiva el color.
    if os.environ.get("NO_COLOR") or os.environ.get("TERM") == "dumb":
        return False
    try:
        es_tty = flujo.isatty()
    except (AttributeError, ValueError):
        return False
    return es_tty and _activar_vt_windows(flujo)


def asegurar_utf8(flujo: TextIO) -> None:
    """Si la salida va a un archivo con una codificación antigua (cp1252), los símbolos ✗ ✓ fallarían."""
    try:
        "✗✓→█".encode(flujo.encoding or "ascii")
    except (UnicodeEncodeError, LookupError):
        try:
            flujo.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


class Terminal:
    def __init__(self, salida: TextIO, progreso: TextIO) -> None:
        asegurar_utf8(salida)
        asegurar_utf8(progreso)
        self.salida = salida
        self.progreso = progreso
        self.color = usar_colores(salida)
        self._progreso_activo = progreso.isatty() if hasattr(progreso, "isatty") else False
        self._color_progreso = usar_colores(progreso)
        self._inicio = time.monotonic()
        self._ultimo = 0.0

    def c(self, texto: str, *estilos: str, color: bool | None = None) -> str:
        if not (self.color if color is None else color) or not estilos:
            return texto
        codigos = ";".join(COLORES[e] for e in estilos)
        return f"\033[{codigos}m{texto}\033[0m"

    def linea(self, texto: str = "") -> None:
        print(texto, file=self.salida, flush=True)  # flush: que no se desordene con lo que va por stderr

    def error(self, texto: str) -> None:
        print(self.c("✗ ", "rojo", color=self._color_progreso) + texto, file=self.progreso)

    def aviso(self, texto: str) -> None:
        print(self.c("! ", "ambar", color=self._color_progreso) + texto, file=self.progreso)

    def actualizar_progreso(self, rastreadas: int, en_cola: int) -> None:
        if not self._progreso_activo:
            return
        ahora = time.monotonic()
        if ahora - self._ultimo < 0.1:  # sin parpadeo: como mucho 10 refrescos por segundo
            return
        self._ultimo = ahora
        texto = f"Rastreando… {miles(rastreadas)} URL rastreadas · {miles(en_cola)} en cola · {round(ahora - self._inicio)} s"
        self.progreso.write("\r\033[2K" + self.c(texto, "tenue", color=self._color_progreso))
        self.progreso.flush()

    def terminar_progreso(self) -> None:
        if self._progreso_activo:
            self.progreso.write("\r\033[2K")
            self.progreso.flush()

    def resumen(self, auditoria: Auditoria, ruta_informe: str | None) -> None:
        r = auditoria.resultado
        partes = [f"Rastreadas {miles(len(r.respuestas))} URL en {decimal(r.duracion)} s",
                  f"{miles(auditoria.paginas_analizadas)} páginas analizadas"]
        if r.bloqueadas:
            n = len(r.bloqueadas)
            partes.append(f"{miles(n)} {'bloqueada' if n == 1 else 'bloqueadas'} por robots.txt")
        self.linea(self.c(" · ".join(partes), "tenue"))
        for aviso in r.avisos:
            self.linea(self.c("! ", "ambar") + self.c(aviso, "tenue"))
        if r.limite_alcanzado:
            self.linea(self.c("! ", "ambar") + self.c("Límite de páginas alcanzado: sube --max-paginas para cubrir toda la web", "tenue"))
        self.linea()

        filas: list[tuple[str, str, str, int]] = []
        for p in auditoria.problemas:
            marca, color = MARCAS[p.tipo.gravedad]
            filas.append((marca, color, p.tipo.titulo, p.total))
        for etiqueta in auditoria.superadas:
            filas.append(("✓", "verde", etiqueta, auditoria.paginas_analizadas))
        ancho = max((len(f[2]) for f in filas), default=0) + 4
        for marca, color, titulo, total in filas:
            self.linea(f"{self.c(marca, color)} {titulo.ljust(ancho)}{self.c(miles(total), color)}")

        self.linea()
        if ruta_informe:
            self.linea(f"{self.c('→', 'verde')} Informe guardado en {self.c(ruta_informe, 'subrayado')}")
            self.linea()
        if auditoria.puntuacion is None:
            self.linea(self.c("Puntuación  sin datos: no se ha podido analizar ninguna página", "tenue"))
            return
        llenas = round(auditoria.puntuacion / 100 * ANCHO_BARRA)
        if self.color:
            barra = self.c("█" * llenas, "azul") + self.c("█" * (ANCHO_BARRA - llenas), "tenue")
        else:
            barra = "█" * llenas + "░" * (ANCHO_BARRA - llenas)
        self.linea(f"{self.c('Puntuación', 'tenue')}  {barra}  {self.c(f'{auditoria.puntuacion}/100', 'azul', 'negrita')}")
