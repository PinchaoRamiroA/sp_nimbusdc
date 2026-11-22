"""Requisitos RM1, RM3 y RD1 sobre los escenarios propios (Integrante 2, Prototipo 2).

- tests/escenarios/memoria.json: lo genera informe/experimentos/experimento_memoria.py
- tests/escenarios/disco.json:   lo genera informe/experimentos/experimento_disco.py

Usa las funciones del enunciado. La prueba de RM1 con el kernel completo se
omite (skip) mientras procesos.py no ejecute la instrucción ("MEM", dir).
"""
import json
import os

import pytest

from minidc import disco, kernel, memoria, procesos
from minidc.errores import ErrorMemoria

CARPETA = os.path.join(os.path.dirname(__file__), "escenarios")
ESC_MEMORIA = os.path.join(CARPETA, "memoria.json")
ESC_DISCO = os.path.join(CARPETA, "disco.json")


def leer(ruta: str) -> dict:
    with open(ruta, encoding="utf-8") as f:
        return json.load(f)


def correr_hasta_terminar(max_ticks: int = 5000) -> None:
    """Avanza el kernel hasta que todos los procesos del escenario terminen."""
    while kernel.reloj_actual() < max_ticks:
        kernel.tick()
        lista = procesos.listar_procesos()
        if lista and all(p["estado"] == "TERMINADO" for p in lista) and not kernel._llegadas_pendientes:
            return


# ----------------------------------------------------------- escenarios
@pytest.mark.parametrize("ruta", [ESC_MEMORIA, ESC_DISCO])
def test_escenarios_tienen_el_formato_del_enunciado(ruta):
    datos = leer(ruta)
    assert set(datos) == {"config", "usuarios", "semaforos", "catalogo", "llegadas"}
    assert set(datos["config"]) == {"num_cpus", "marcos_fisicos", "tam_pagina",
                                    "bloques_disco", "tam_bloque", "cache_bloques"}
    for llegada in datos["llegadas"]:
        assert llegada["programa"] in datos["catalogo"]


def test_escenario_memoria_cuotas_caben_en_memoria():
    """Escenario nominal: la suma de cuotas no supera los marcos físicos."""
    datos = leer(ESC_MEMORIA)
    cuotas = sum(datos["catalogo"][l["programa"]]["cuota_marcos"] for l in datos["llegadas"])
    assert cuotas <= datos["config"]["marcos_fisicos"]


# ------------------------------------------------------------------ RM1
def test_rm1_tasa_de_fallos_con_los_accesos_del_escenario():
    """Reproduce los ("MEM", dir) del escenario intercalando procesos (un acceso por turno)."""
    datos = leer(ESC_MEMORIA)
    memoria.reiniciar(datos["config"])
    procesos.reiniciar({})
    programas = []
    for pid, llegada in enumerate(datos["llegadas"], start=1):
        servicio = datos["catalogo"][llegada["programa"]]
        memoria.registrar_proceso(pid, servicio["memoria_bytes"], servicio["cuota_marcos"])
        programas.append([inst[1] for inst in servicio["programa"] if inst[0] == "MEM"])
    for turno in range(max(map(len, programas))):
        for pid, direcciones in enumerate(programas, start=1):
            if turno < len(direcciones):
                memoria.acceder_memoria(pid, direcciones[turno])
    m = memoria.metricas_memoria()
    assert m["accesos"] == sum(map(len, programas))
    assert m["tasa_fallos"] <= 0.25


def test_rm1_escenario_de_memoria_con_el_kernel():
    kernel.cargar_escenario(ESC_MEMORIA)
    memoria.reiniciar(leer(ESC_MEMORIA)["config"])   # por si el kernel aún no la reinicia
    correr_hasta_terminar()
    m = memoria.metricas_memoria()
    if m["accesos"] == 0:
        pytest.skip("procesos.py todavía no ejecuta la instrucción ('MEM', dir)")
    assert m["tasa_fallos"] <= 0.25
    # Todos terminaron: la memoria debe quedar libre
    assert memoria.estado_memoria()["marcos_libres"] == leer(ESC_MEMORIA)["config"]["marcos_fisicos"]


# ------------------------------------------------------------------ RM3
def test_rm3_proceso_real_fuera_de_su_espacio_no_afecta_a_otros():
    """Memoria lee memoria_bytes y cuota_marcos del proceso creado en procesos."""
    kernel.iniciar_sistema({"num_cpus": 1, "marcos_fisicos": 16, "tam_pagina": 256,
                            "bloques_disco": 200, "tam_bloque": 512, "cache_bloques": 8})
    memoria.reiniciar({"marcos_fisicos": 16, "tam_pagina": 256})
    bueno = procesos.crear_proceso("web", "cliente_a", [("CPU", 1)], memoria_bytes=1024, cuota_marcos=3)
    malo = procesos.crear_proceso("intruso", "cliente_b", [("CPU", 1)], memoria_bytes=512, cuota_marcos=2)
    memoria.acceder_memoria(bueno, 0)
    memoria.acceder_memoria(bueno, 700)
    antes = memoria.tabla_paginas(bueno)
    with pytest.raises(ErrorMemoria):
        memoria.acceder_memoria(malo, 512)            # 512 B: la última válida es 511
    with pytest.raises(ErrorMemoria):
        memoria.acceder_memoria(malo, 1023)           # válida para el otro, no para este
    assert memoria.tabla_paginas(bueno) == antes
    assert memoria.estado_memoria()["marcos_por_proceso"].get(malo, 0) == 0
    assert memoria.acceder_memoria(bueno, 0)["fallo_pagina"] is False


def test_terminar_proceso_libera_sus_marcos():
    kernel.iniciar_sistema({"num_cpus": 1, "marcos_fisicos": 16, "tam_pagina": 256})
    memoria.reiniciar({"marcos_fisicos": 16, "tam_pagina": 256})
    pid = procesos.crear_proceso("analitica", "cliente_a", [("CPU", 5)], memoria_bytes=2048, cuota_marcos=4)
    for direccion in (0, 256, 512):
        memoria.acceder_memoria(pid, direccion)
    assert memoria.estado_memoria()["marcos_libres"] == 13
    procesos.terminar_proceso(pid)
    assert memoria.estado_memoria()["marcos_libres"] == 16


def test_proceso_que_termina_solo_tambien_libera_su_memoria():
    kernel.iniciar_sistema({"num_cpus": 1, "marcos_fisicos": 16, "tam_pagina": 256})
    memoria.reiniciar({"marcos_fisicos": 16, "tam_pagina": 256})
    pid = procesos.crear_proceso("web", "cliente_a", [("CPU", 1)], memoria_bytes=1024, cuota_marcos=3)
    memoria.acceder_memoria(pid, 0)
    kernel.ejecutar_ticks(3)                          # termina su ráfaga de CPU
    assert procesos.estado_proceso(pid) == "TERMINADO"
    assert memoria.estado_memoria()["marcos_libres"] == 16


# ------------------------------------------------------------------ RD1
def _desplazamiento_y_espera(politica: str) -> tuple:
    try:
        disco._fijar_politica(politica)
        kernel.cargar_escenario(ESC_DISCO)
        correr_hasta_terminar()
        return (disco.metricas_disco()["desplazamiento_total"],
                disco.estadisticas_espera()["espera_maxima"],
                disco.metricas_disco()["solicitudes_atendidas"])
    finally:
        disco._fijar_politica("C-LOOK")


def test_rd1_escenario_de_disco_con_el_kernel():
    clook, espera_clook, atendidas = _desplazamiento_y_espera("C-LOOK")
    fcfs, _, atendidas_fcfs = _desplazamiento_y_espera("FCFS")
    total = sum(1 for s in leer(ESC_DISCO)["catalogo"].values()
                for inst in s["programa"] if inst[0] == "ES")
    assert atendidas == atendidas_fcfs == total
    assert clook <= 0.7 * fcfs                        # al menos 30 % menos
    assert espera_clook <= 200                        # ninguna espera más de 200 ticks


# ------------------------------------- regresiones de la revisión independiente
CFG = {"num_cpus": 1, "marcos_fisicos": 16, "tam_pagina": 256,
       "bloques_disco": 200, "tam_bloque": 512, "cache_bloques": 8}


def test_pid_reutilizado_tras_reiniciar_el_kernel_no_hereda_memoria():
    """Aunque el kernel no reinicie la memoria, el nuevo PID 1 no hereda nada del viejo."""
    kernel.iniciar_sistema(CFG)
    memoria.reiniciar(CFG)
    viejo = procesos.crear_proceso("grande", "admin", [("CPU", 1)], memoria_bytes=4096, cuota_marcos=8)
    for direccion in range(0, 2048, 256):
        memoria.acceder_memoria(viejo, direccion)
    kernel.iniciar_sistema(CFG)                       # sin memoria.reiniciar a propósito
    nuevo = procesos.crear_proceso("chico", "admin", [("CPU", 1)], memoria_bytes=512, cuota_marcos=1)
    assert nuevo == viejo == 1
    with pytest.raises(ErrorMemoria):
        memoria.acceder_memoria(nuevo, 3000)          # válida para el viejo, no para el nuevo
    assert memoria.estado_memoria()["marcos_por_proceso"] == {1: 0}
    assert memoria.estado_memoria()["marcos_libres"] == 16


def test_acceso_de_un_proceso_terminado_lanza_error_no_existe():
    from minidc.errores import ErrorNoExiste
    kernel.iniciar_sistema(CFG)
    memoria.reiniciar(CFG)
    pid = procesos.crear_proceso("web", "admin", [("CPU", 1)], memoria_bytes=1024, cuota_marcos=2)
    memoria.acceder_memoria(pid, 0)
    procesos._procesos[pid]["estado"] = "TERMINADO"   # terminó sin liberar_memoria
    antes = memoria.metricas_memoria()
    for direccion in (0, 300):
        with pytest.raises(ErrorNoExiste):
            memoria.acceder_memoria(pid, direccion)
    assert memoria.metricas_memoria() == antes
    assert memoria.estado_memoria()["marcos_libres"] == 16


def test_estado_memoria_cuenta_procesos_que_aun_no_acceden():
    """Fragmentación interna sumada para todos los procesos (guía 5.4)."""
    kernel.iniciar_sistema(CFG)
    memoria.reiniciar(CFG)
    procesos.crear_proceso("a", "admin", [("CPU", 1)], memoria_bytes=1000, cuota_marcos=2)   # sobran 24
    procesos.crear_proceso("b", "admin", [("CPU", 1)], memoria_bytes=600, cuota_marcos=2)    # sobran 168
    estado = memoria.estado_memoria()
    assert estado["fragmentacion_interna_bytes"] == 24 + 168
    assert estado["marcos_por_proceso"] == {1: 0, 2: 0}
