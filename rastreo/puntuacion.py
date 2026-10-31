"""Agrupa los hallazgos por tipo, calcula su impacto y la puntuación global (0–100).

Cada tipo de problema resta como máximo su peso. Cuánto resta depende de la
proporción de páginas afectadas, con raíz cuadrada para que unas pocas URL ya
se noten pero no hundan la nota de una web grande:

    impacto = peso × (0,3 + 0,7 × √(afectadas / páginas analizadas))

Un problema en una sola URL resta al menos el 30 % de su peso; si afecta a
todas las páginas, resta el peso entero.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from .comprobaciones import FAMILIAS, ORDEN_GRAVEDAD, TIPOS, Hallazgo, TipoProblema, comprobar
from .modelos import ResultadoRastreo

FACTOR_MINIMO = 0.3


@dataclass
class Problema:
    tipo: TipoProblema
    hallazgos: list[Hallazgo]
    impacto: float = 0.0

    @property
    def urls(self) -> int:
        return len({h.url for h in self.hallazgos})

    @property
    def total(self) -> int:
        """Lo que se cuenta en el resumen: URL afectadas o elementos (imágenes sin alt)."""
        if self.tipo.unidad == "URL":
            return self.urls
        return sum(h.elementos for h in self.hallazgos)

    def grupos(self) -> list[tuple[str, list[Hallazgo]]]:
        por_detalle: defaultdict[str, list[Hallazgo]] = defaultdict(list)
        for h in self.hallazgos:
            por_detalle[h.detalle].append(h)
        return sorted(por_detalle.items(), key=lambda g: (-len(g[1]), g[0]))


@dataclass
class Auditoria:
    resultado: ResultadoRastreo
    problemas: list[Problema]
    puntuacion: int | None
    superadas: list[str]
    fecha: datetime = field(default_factory=lambda: datetime.now().astimezone())

    @property
    def paginas_analizadas(self) -> int:
        return len(self.resultado.paginas)

    def contar(self, gravedad: str) -> int:
        """URL distintas con algún problema de esa gravedad (una URL con dos errores cuenta una vez)."""
        return len({h.url for p in self.problemas if p.tipo.gravedad == gravedad for h in p.hallazgos})


def impacto(tipo: TipoProblema, afectadas: int, total: int) -> float:
    if afectadas <= 0 or tipo.peso <= 0:
        return 0.0
    proporcion = min(1.0, afectadas / max(1, total))
    return tipo.peso * (FACTOR_MINIMO + (1 - FACTOR_MINIMO) * math.sqrt(proporcion))


def calcular_puntuacion(problemas: list[Problema]) -> int:
    return max(0, round(100 - sum(p.impacto for p in problemas)))


def valoracion(puntuacion: int | None) -> str:
    if puntuacion is None:
        return "Sin datos"
    if puntuacion >= 90:
        return "Buena"
    if puntuacion >= 70:
        return "Mejorable"
    if puntuacion >= 50:
        return "Deficiente"
    return "Crítica"


def agrupar(hallazgos: list[Hallazgo], paginas: int) -> list[Problema]:
    por_tipo: defaultdict[str, list[Hallazgo]] = defaultdict(list)
    for h in hallazgos:
        por_tipo[h.tipo].append(h)
    problemas = []
    for id_tipo, lista in por_tipo.items():
        problema = Problema(TIPOS[id_tipo], sorted(lista, key=lambda h: (h.detalle, h.url)) if TIPOS[id_tipo].agrupar
                            else sorted(lista, key=lambda h: h.url))
        problema.impacto = impacto(problema.tipo, problema.urls, paginas)
        problemas.append(problema)
    # Primero lo que más resta; a igual impacto, lo más grave.
    problemas.sort(key=lambda p: (-p.impacto, ORDEN_GRAVEDAD[p.tipo.gravedad], p.tipo.titulo))
    return problemas


def auditar(resultado: ResultadoRastreo) -> Auditoria:
    paginas = len(resultado.paginas)
    problemas = agrupar(comprobar(resultado), paginas)
    con_problemas = {p.tipo.familia for p in problemas}
    superadas = [etiqueta for familia, etiqueta in FAMILIAS.items()
                 if familia not in con_problemas and paginas > 0
                 and (familia != "geo" or resultado.llms_txt is not None)]
    # Sin páginas analizadas no hay base para puntuar (web caída, todo bloqueado…).
    puntuacion = calcular_puntuacion(problemas) if paginas else None
    return Auditoria(resultado, problemas, puntuacion, superadas)
