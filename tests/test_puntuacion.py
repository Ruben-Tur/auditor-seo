import pytest

from rastreo.comprobaciones import TIPOS, Hallazgo
from rastreo.puntuacion import agrupar, calcular_puntuacion, impacto, valoracion


def test_impacto_crece_con_la_proporcion_y_no_pasa_del_peso():
    tipo = TIPOS["sin_h1"]  # peso 6
    assert impacto(tipo, 0, 100) == 0
    assert impacto(tipo, 1, 1) == pytest.approx(6)
    assert impacto(tipo, 500, 100) == pytest.approx(6)  # proporción limitada a 1
    una, diez, cien = (impacto(tipo, n, 100) for n in (1, 10, 100))
    assert una == pytest.approx(6 * (0.3 + 0.7 * 0.1))
    assert una < diez < cien


def test_tipos_sin_peso_no_restan():
    assert impacto(TIPOS["bloqueada_robots"], 40, 10) == 0


def test_puntuacion_y_orden():
    hallazgos = [Hallazgo("titulo_largo", f"https://ejemplo.es/{i}") for i in range(10)]
    hallazgos += [Hallazgo("enlace_roto_interno", "https://ejemplo.es/roto", "404")]
    hallazgos += [Hallazgo("bloqueada_robots", "https://ejemplo.es/admin")]
    problemas = agrupar(hallazgos, paginas=10)
    assert [p.tipo.id for p in problemas] == ["enlace_roto_interno", "titulo_largo", "bloqueada_robots"]
    # 12 × (0,3 + 0,7 × √0,1) + 2 × 1 = 6,26 + 2 → 92
    assert calcular_puntuacion(problemas) == 92


def test_todo_mal_hunde_la_puntuacion_sin_bajar_de_cero():
    problemas = agrupar([Hallazgo(t, "https://ejemplo.es/") for t in TIPOS], paginas=1)
    assert calcular_puntuacion(problemas) < 10
    for p in problemas:
        p.impacto *= 10
    assert calcular_puntuacion(problemas) == 0


def test_imagenes_cuentan_elementos():
    problemas = agrupar([Hallazgo("imagenes_sin_alt", "https://ejemplo.es/a", elementos=4),
                         Hallazgo("imagenes_sin_alt", "https://ejemplo.es/b", elementos=2)], paginas=2)
    assert problemas[0].total == 6 and problemas[0].urls == 2


def test_valoracion():
    assert [valoracion(p) for p in (None, 95, 72, 50, 10)] == ["Sin datos", "Buena", "Mejorable", "Deficiente", "Crítica"]
