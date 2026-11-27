"""Pruebas con los escenarios JSON de ``tests/escenarios/`` (formato del enunciado).

Cada escenario se carga con ``kernel.cargar_escenario``, igual que en las
pruebas del profesor, y se ejecuta tick a tick. Después de cada tick se observa
qué proceso corrió y cuál se quedó esperando, usando solo funciones del
enunciado. Así se miden RP1, RP2 y RP3.
"""
import json
import os

import pytest

from minidc import kernel, procesos

CARPETA = os.path.join(os.path.dirname(__file__), "escenarios")
ESCENARIOS = ["ejemplo_enunciado.json", "base.json", "inanicion.json", "carga_cpu.json", "integracion.json"]

SECCIONES = {"config", "usuarios", "semaforos", "catalogo", "llegadas"}
CLAVES_CONFIG = {"num_cpus", "marcos_fisicos", "tam_pagina", "bloques_disco", "tam_bloque", "cache_bloques"}
CLAVES_SERVICIO = {"memoria_bytes", "cuota_marcos", "prioridad", "programa"}
INSTRUCCIONES = {"CPU", "ES", "MEM", "WAIT", "SIGNAL"}


# ------------------------------------------------------------------ ayudas
def ruta_de(nombre):
    return os.path.join(CARPETA, nombre)


def leer_escenario(nombre):
    with open(ruta_de(nombre), encoding="utf-8") as f:
        return json.load(f)


def anotar_llegadas(observados):
    """Abre un registro para cada proceso que aparece por primera vez: su llegada es el tick actual."""
    for p in procesos.listar_procesos():
        if p["pid"] not in observados:
            observados[p["pid"]] = {
                "programa": p["nombre"],
                "llegada": kernel.reloj_actual(),
                "primer_inicio": None,      # tick en que usó la CPU por primera vez
                "cpu_usada": 0,
                "espera_seguida": 0,        # ticks seguidos en LISTO sin ejecutarse
                "peor_espera": 0,           # el máximo que alcanzó espera_seguida
            }


def observar_tick(observados):
    """Anota, después de un tick, qué proceso corrió y cuál se quedó esperando."""
    ahora = kernel.reloj_actual()
    for p in procesos.listar_procesos():
        registro = observados[p["pid"]]
        corrio = p["cpu_usada"] > registro["cpu_usada"]
        registro["cpu_usada"] = p["cpu_usada"]
        if corrio and registro["primer_inicio"] is None:
            registro["primer_inicio"] = ahora
        if p["estado"] == "LISTO" and not corrio:
            registro["espera_seguida"] += 1
            registro["peor_espera"] = max(registro["peor_espera"], registro["espera_seguida"])
        else:
            registro["espera_seguida"] = 0


def ejecutar_escenario(nombre, ticks):
    """Carga el escenario con el kernel, lo corre ``ticks`` ticks y devuelve un registro por proceso.

    Los procesos del tick 0 existen desde la carga; los demás aparecen en el
    paso 1 del tick de su llegada y pueden correr en ese mismo tick.
    """
    kernel.cargar_escenario(ruta_de(nombre))
    observados = {}                                 # pid -> registro
    anotar_llegadas(observados)
    for _ in range(ticks):
        kernel.tick()
        anotar_llegadas(observados)
        observar_tick(observados)
    return list(observados.values())


# ------------------------------------------------- formato de los escenarios
@pytest.mark.parametrize("nombre", ESCENARIOS)
def test_escenario_tiene_las_secciones_del_enunciado(nombre):
    escenario = leer_escenario(nombre)
    assert set(escenario) == SECCIONES
    assert set(escenario["config"]) == CLAVES_CONFIG


@pytest.mark.parametrize("nombre", ESCENARIOS)
def test_programas_del_catalogo_son_validos(nombre):
    escenario = leer_escenario(nombre)
    for servicio in escenario["catalogo"].values():
        assert set(servicio) == CLAVES_SERVICIO
        for tipo, valor in servicio["programa"]:
            assert tipo in INSTRUCCIONES
            if tipo == "CPU":
                assert valor > 0
            elif tipo == "ES":
                assert 0 <= valor < escenario["config"]["bloques_disco"]
            elif tipo == "MEM":
                assert 0 <= valor < servicio["memoria_bytes"]
            else:                                   # WAIT o SIGNAL
                assert valor in escenario["semaforos"]


@pytest.mark.parametrize("nombre", ESCENARIOS)
def test_llegadas_son_validas_y_estan_ordenadas(nombre):
    escenario = leer_escenario(nombre)
    usuarios = set(escenario["usuarios"]) | {"admin"}
    ticks = [llegada["tick"] for llegada in escenario["llegadas"]]
    assert ticks == sorted(ticks)
    assert ticks[0] >= 0
    for llegada in escenario["llegadas"]:
        assert llegada["programa"] in escenario["catalogo"]
        assert llegada["usuario"] in usuarios


@pytest.mark.parametrize("nombre", ESCENARIOS)
def test_cada_llegada_crea_su_proceso_en_su_tick(nombre):
    escenario = leer_escenario(nombre)
    ultimo_tick = escenario["llegadas"][-1]["tick"]
    registros = ejecutar_escenario(nombre, ticks=ultimo_tick)
    esperadas = [(llegada["tick"], llegada["programa"]) for llegada in escenario["llegadas"]]
    vistas = [(r["llegada"], r["programa"]) for r in registros]
    assert vistas == esperadas                      # mismo orden, mismo tick, mismo programa


# ----------------------------------------------------------- RP1, RP2 y RP3
def test_rp1_los_servicios_web_empiezan_en_10_ticks_o_menos():
    registros = ejecutar_escenario("base.json", ticks=300)
    web = [r for r in registros if r["programa"] == "web"]
    assert all(r["primer_inicio"] is not None for r in web)
    respuestas = [r["primer_inicio"] - r["llegada"] for r in web]
    assert sum(respuestas) / len(respuestas) <= 10


@pytest.mark.parametrize("nombre", ["base.json", "inanicion.json", "carga_cpu.json"])
def test_rp2_nadie_espera_mas_de_150_ticks_seguidos(nombre):
    registros = ejecutar_escenario(nombre, ticks=450)
    assert max(r["peor_espera"] for r in registros) <= 150


def test_rp2_el_proceso_de_baja_prioridad_llega_a_ejecutarse():
    """En inanicion.json llega un servicio web cada 4 ticks y ocupa toda la CPU."""
    registros = ejecutar_escenario("inanicion.json", ticks=450)
    analitica = [r for r in registros if r["programa"] == "analitica"]
    assert all(r["primer_inicio"] is not None for r in analitica)


def test_rp3_utilizacion_de_cpu_de_al_menos_85_por_ciento():
    ejecutar_escenario("carga_cpu.json", ticks=150)
    assert procesos.metricas_planificacion()["utilizacion_cpu"] >= 0.85


# ------------------------------------------------------- recorrido completo
def test_escenario_base_termina_todos_sus_procesos():
    registros = ejecutar_escenario("base.json", ticks=300)
    estados = [p["estado"] for p in procesos.listar_procesos()]
    assert len(estados) == len(registros) == 16
    assert set(estados) == {"TERMINADO"}
    assert kernel.resumen_sistema()["procesos_activos"] == 0
