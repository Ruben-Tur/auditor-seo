"""Formato de números y fechas en español de España."""

from __future__ import annotations

from datetime import datetime

MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre")


def decimal(valor: float, cifras: int = 1) -> str:
    return f"{valor:.{cifras}f}".replace(".", ",")


def miles(valor: int) -> str:
    return f"{valor:,}".replace(",", ".")


def fecha_larga(fecha: datetime) -> str:
    return f"{fecha.day} de {MESES[fecha.month - 1]} de {fecha.year}, {fecha:%H:%M}"
