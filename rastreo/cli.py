"""Interfaz de línea de comandos: python -m rastreo https://ejemplo.es --informe informe.html"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path

from . import AUTOR, URL_AUTOR, USER_AGENT, __version__
from .informe import generar_html, generar_json, guardar
from .puntuacion import auditar
from .rastreador import ErrorRastreo, Opciones, Rastreador
from .terminal import Terminal, asegurar_utf8
from .urls import nombre_host, normalizar

SALIDA_OK, SALIDA_ERROR, SALIDA_USO, SALIDA_INTERRUMPIDO = 0, 1, 2, 130


def _rango(tipo, minimo, maximo):
    """Crea un validador de argparse que exige un número dentro de [minimo, maximo]."""
    def validar(texto: str):
        try:
            valor = tipo(texto)
        except ValueError:
            raise argparse.ArgumentTypeError(f"«{texto}» no es un número válido") from None
        if not minimo <= valor <= maximo:
            raise argparse.ArgumentTypeError(f"tiene que estar entre {minimo} y {maximo}")
        return valor
    return validar


def _url(texto: str) -> str:
    url = normalizar(texto) if len(texto) <= 2000 else None
    if url is None:
        raise argparse.ArgumentTypeError(f"«{texto[:80]}» no es una URL http:// o https:// válida")
    return url


def nombre_informe(url: str) -> str:
    return "informe-" + re.sub(r"[^a-z0-9]+", "-", nombre_host(url)).strip("-") + ".html"


def _ruta_legible(ruta: Path) -> str:
    """Ruta relativa si el archivo queda dentro de la carpeta actual; si no, absoluta."""
    try:
        return str(ruta.relative_to(Path.cwd()))
    except ValueError:
        return str(ruta)


class _Formato(argparse.HelpFormatter):
    def add_usage(self, usage, actions, groups, prefix=None):
        super().add_usage(usage, actions, groups, prefix="Uso: ")


class _Parser(argparse.ArgumentParser):
    # argparse solo trae sus mensajes en inglés: se traducen los más habituales.
    TRADUCCIONES = (("the following arguments are required", "faltan argumentos obligatorios"),
                    ("unrecognized arguments", "argumentos desconocidos"),
                    ("expected one argument", "falta el valor"),
                    ("argument ", "argumento "))

    def error(self, message: str):
        for ingles, espanol in self.TRADUCCIONES:
            message = message.replace(ingles, espanol)
        self.print_usage(sys.stderr)
        self.exit(SALIDA_USO, f"{self.prog}: error: {message}\n")


def crear_parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="rastreo",
        add_help=False,
        formatter_class=_Formato,
        description="Rastrea una web entera y genera un informe con los fallos de SEO técnico ordenados por prioridad.",
        epilog=f"Ejemplo: rastreo https://ejemplo.es --informe informe.html · Hecho por {AUTOR} ({URL_AUTOR})",
    )
    parser._positionals.title = "Argumentos"
    parser._optionals.title = "Opciones"
    parser.add_argument("-h", "--ayuda", action="help", help="muestra esta ayuda y termina")
    parser.add_argument("url", type=_url, help="URL de inicio del rastreo (http:// o https://)")
    parser.add_argument("--informe", nargs="?", const="", metavar="RUTA",
                        help="guarda el informe HTML (sin RUTA: informe-<dominio>.html)")
    parser.add_argument("--json", nargs="?", const="-", metavar="RUTA",
                        help="guarda el resultado en JSON (sin RUTA o con «-»: por la salida estándar)")
    parser.add_argument("--concurrencia", type=_rango(int, 1, 50), default=5, metavar="N",
                        help="peticiones simultáneas (1–50, por defecto 5)")
    parser.add_argument("--por-segundo", type=_rango(float, 0.1, 50), default=5.0, metavar="N",
                        help="máximo de peticiones por segundo (0.1–50, por defecto 5)")
    parser.add_argument("--max-paginas", type=_rango(int, 1, 100_000), default=500, metavar="N",
                        help="máximo de URL internas a rastrear (por defecto 500)")
    parser.add_argument("--timeout", type=_rango(float, 1, 120), default=10.0, metavar="S",
                        help="tiempo de espera por petición en segundos (por defecto 10)")
    parser.add_argument("--externos", action="store_true", help="comprueba también los enlaces a otros dominios")
    parser.add_argument("--minimo", type=_rango(int, 0, 100), metavar="N",
                        help="termina con código 1 si la puntuación queda por debajo de N (útil en CI)")
    parser.add_argument("--version", action="version", help="muestra la versión y termina",
                        version=f"rastreo {__version__} · Hecho por {AUTOR} · {URL_AUTOR}")
    return parser


def main(argv: list[str] | None = None) -> int:
    asegurar_utf8(sys.stdout)
    asegurar_utf8(sys.stderr)
    args = crear_parser().parse_args(argv)
    json_por_salida = args.json == "-"
    # Si el JSON va por stdout, todo lo demás va por stderr para no mezclarlo.
    terminal = Terminal(sys.stderr if json_por_salida else sys.stdout, sys.stderr)

    opciones = Opciones(
        concurrencia=args.concurrencia,
        por_segundo=args.por_segundo,
        max_paginas=args.max_paginas,
        timeout=args.timeout,
        externos=args.externos,
        user_agent=USER_AGENT,
    )
    terminal.linea(terminal.c("$ ", "azul") + f"rastreo {args.url}")
    try:
        rastreador = Rastreador(args.url, opciones, al_progresar=terminal.actualizar_progreso)
        resultado = asyncio.run(rastreador.ejecutar())
    except ErrorRastreo as error:
        terminal.terminar_progreso()
        terminal.error(str(error))
        return SALIDA_ERROR
    except KeyboardInterrupt:
        terminal.terminar_progreso()
        terminal.error("Rastreo interrumpido")
        return SALIDA_INTERRUMPIDO
    terminal.terminar_progreso()

    auditoria = auditar(resultado)
    ruta_informe = None
    try:
        if args.informe is not None:
            ruta = Path(args.informe or nombre_informe(resultado.inicio))
            ruta_informe = _ruta_legible(guardar(generar_html(auditoria), ruta))
        if args.json is not None:
            if json_por_salida:
                sys.stdout.write(generar_json(auditoria) + "\n")
            else:
                guardar(generar_json(auditoria), Path(args.json))
    except OSError as error:
        terminal.error(f"No se pudo guardar el archivo: {error.strerror or error}")
        return SALIDA_ERROR

    terminal.resumen(auditoria, ruta_informe)
    if args.minimo is not None and (auditoria.puntuacion or 0) < args.minimo:
        terminal.aviso(f"La puntuación ({auditoria.puntuacion}) está por debajo del mínimo exigido ({args.minimo})")
        return SALIDA_ERROR
    return SALIDA_OK
