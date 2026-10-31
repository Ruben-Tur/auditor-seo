"""Estructuras de datos compartidas entre el rastreador, las comprobaciones y el informe."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class DatosPagina:
    """Lo que interesa de una página HTML para el SEO técnico."""

    titulos: list[str] = field(default_factory=list)
    descripciones: list[str] = field(default_factory=list)
    h1: list[str] = field(default_factory=list)
    imagenes_sin_alt: list[str] = field(default_factory=list)
    canonicas: list[str] = field(default_factory=list)
    noindex: bool = False
    idioma: str | None = None
    enlaces: list[str] = field(default_factory=list)
    recursos: list[str] = field(default_factory=list)
    jsonld_tipos: list[str] = field(default_factory=list)
    jsonld_errores: list[str] = field(default_factory=list)


@dataclass
class Respuesta:
    """Resultado de pedir una URL (sin seguir redirecciones: cada salto es su propia Respuesta)."""

    url: str
    estado: int | None = None
    error: str | None = None
    destino: str | None = None
    tipo: str = ""
    ms: int = 0
    noindex_cabecera: bool = False
    omitida: bool = False  # no se pidió por seguridad (p. ej. apunta a la red local)
    pagina: DatosPagina | None = None

    @property
    def es_redireccion(self) -> bool:
        return self.estado is not None and 300 <= self.estado < 400 and self.destino is not None

    @property
    def es_error(self) -> bool:
        return self.estado is None or self.estado >= 400

    def describir_estado(self) -> str:
        return str(self.estado) if self.estado is not None else (self.error or "sin respuesta")


def _origenes() -> defaultdict[str, defaultdict[str, set[str]]]:
    return defaultdict(lambda: defaultdict(set))


@dataclass
class ResultadoRastreo:
    inicio: str
    host: str
    respuestas: dict[str, Respuesta] = field(default_factory=dict)
    # url -> tipo de origen ("enlace", "redireccion", "canonica", "inicio") -> páginas de origen
    origenes: defaultdict[str, defaultdict[str, set[str]]] = field(default_factory=_origenes)
    bloqueadas: defaultdict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    enlaces_externos: defaultdict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    externos: dict[str, Respuesta] = field(default_factory=dict)
    externos_omitidos: list[str] = field(default_factory=list)
    llms_txt: Respuesta | None = None
    limite_alcanzado: bool = False
    avisos: list[str] = field(default_factory=list)
    duracion: float = 0.0

    @property
    def paginas(self) -> dict[str, DatosPagina]:
        return {u: r.pagina for u, r in self.respuestas.items() if r.pagina is not None}
