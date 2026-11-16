"""Pruebas con los escenarios JSON de ``tests/escenarios/`` (formato del enunciado).

Cada escenario se ejecuta "desde fuera": la prueba lee el JSON, crea cada
proceso en su tick con ``procesos.crear_proceso`` y avanza con ``kernel.tick``.
Así se miden RP1, RP2 y RP3 usando solo funciones del enunciado.

Pendiente del núcleo: ``kernel.cargar_escenario`` todavía no lee este formato
(usuarios como lista, semáforos como diccionario y llegadas que apuntan al
catálogo). Por eso la última prueba está marcada como fallo esperado (xfail).
"""
import json
import os

import pytest

from minidc import kernel, procesos

CARPETA = os.path.join(os.path.dirname(__file__), "escenarios")
ESCENARIOS = ["ejemplo_enunciado.json", "base.json", "inanicion.json", "carga_cpu.json"]

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


def crear_llegada(escenario, llegada, observados):
    """Crea el proceso de una llegada y abre su registro de observación."""
    servicio = escenario["catalogo"][llegada["programa"]]
    pid = procesos.crear_proceso(
        nombre=llegada["programa"],
        usuario=llegada["usuario"],
        programa=servicio["programa"],
        memoria_bytes=servicio["memoria_bytes"],
        cuota_marcos=servicio["cuota_marcos"],
        prioridad=servicio["prioridad"],
    )
    observados[pid] = {
        "programa": llegada["programa"],
        "llegada": llegada["tick"],
        "primer_inicio": None,      # tick en que usó la CPU por primera vez
        "cpu_usada": 0,
        "espera_seguida": 0,        # ticks seguidos en LISTO sin ejecutarse
        "peor_espera": 0,           # el máximo que alcanzó espera_seguida
    }


def observar_tick(observados):
    """Anota, después de un tick, qué proceso corrió y cuál se quedó esperando."""
    ahora = kernel.reloj_actual()
    cpu_usada = {p["pid"]: p["cpu_usada"] for p in procesos.listar_procesos()}
    for pid, registro in observados.items():
        corrio = cpu_usada[pid] > registro["cpu_usada"]
        registro["cpu_usada"] = cpu_usada[pid]
        if corrio and registro["primer_inicio"] is None:
            registro["primer_inicio"] = ahora
        if procesos.estado_proceso(pid) == "LISTO" and not corrio:
            registro["espera_seguida"] += 1
            registro["peor_espera"] = max(registro["peor_espera"], registro["espera_seguida"])
        else:
            registro["espera_seguida"] = 0


def ejecutar_escenario(nombre, ticks):
    """Ejecuta el escenario durante ``ticks`` ticks y devuelve un registro por proceso.

    Un proceso con llegada en el tick N se crea justo antes de ejecutar el
    tick N (los de tick 0, antes del primer tick), igual que hace el kernel.
    """
    escenario = leer_escenario(nombre)
    kernel.iniciar_sistema(escenario["config"])
    pendientes = list(escenario["llegadas"])        # vienen ordenadas por tick
    observados = {}                                 # pid -> registro
    for _ in range(ticks):
        tick_siguiente = kernel.reloj_actual() + 1
        while pendientes and pendientes[0]["tick"] <= tick_siguiente:
            crear_llegada(escenario, pendientes.pop(0), observados)
        kernel.tick()
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


def test_ejemplo_del_enunciado_termina_en_8_ticks():
    """CPU 2 + ES 40 (5 ticks bloqueado) + CPU 1, con el proceso solo en el sistema."""
    ejecutar_escenario("ejemplo_enunciado.json", ticks=8)
    assert [p["estado"] for p in procesos.listar_procesos()] == ["TERMINADO"]


# ------------------------------------------------ pendiente del núcleo (P2)
@pytest.mark.xfail(reason="kernel.cargar_escenario aún no lee el formato del enunciado")
@pytest.mark.parametrize("nombre", ESCENARIOS)
def test_el_kernel_carga_el_escenario_directamente(nombre):
    escenario = leer_escenario(nombre)
    kernel.cargar_escenario(ruta_de(nombre))
    kernel.ejecutar_ticks(escenario["llegadas"][-1]["tick"] + 1)
    assert len(procesos.listar_procesos()) == len(escenario["llegadas"])
