"""Prueba de contrato entre el disco y el kernel (kernel de juguete).

Un mini 'kernel' sigue el orden del tick del enunciado (paso 2: atender la
E/S terminada; paso 3: ejecutar 1 tick de CPU) y corre el programa
[("CPU", 2), ("ES", 40), ("CPU", 1)] con un solo proceso. Comprueba que el
proceso queda BLOQUEADO el tiempo que dice la fórmula del enunciado.

No usa el kernel real: documenta cómo debe usar `disco` el Integrante 1.
Para ver la traza:  python -m pytest tests/test_disco_kernel_simulado.py -s -v
"""
import pytest

from minidc import disco

CONFIG = {"bloques_disco": 200, "cache_bloques": 8}
PID = 1
PROGRAMA = [("CPU", 2), ("ES", 40), ("CPU", 1)]


def simular(programa, max_ticks=30):
    """Ejecuta el programa tick a tick. Devuelve [(tick, estado, evento), ...]."""
    disco.reiniciar(CONFIG)
    estado, pc, restante = "LISTO", 0, None
    traza = []
    for reloj in range(1, max_ticks + 1):
        evento = ""
        # Paso 2 del tick: atender la E/S terminada (interrupción)
        if PID in disco.avanzar_tick():
            estado = "LISTO"
            evento = "el disco terminó la E/S -> LISTO. "
        # Paso 3 del tick: ejecutar 1 tick del proceso
        if estado == "LISTO":
            tipo, valor = programa[pc]
            if tipo == "CPU":
                restante = valor if restante is None else restante
                restante -= 1
                evento += f"CPU (quedan {restante})"
                if restante == 0:
                    restante = None
                    pc += 1
            elif tipo == "ES":
                disco.encolar_solicitud_disco(PID, valor, "L")
                estado = "BLOQUEADO"
                pc += 1
                evento += f"ES bloque {valor} -> BLOQUEADO"
            if estado == "LISTO" and pc == len(programa):
                estado = "TERMINADO"
        traza.append((reloj, estado, evento))
        if estado == "TERMINADO":
            break
    return traza


def test_proceso_con_es_40_queda_bloqueado_5_ticks():
    traza = simular(PROGRAMA)

    print("\n tick | estado     | qué pasó")
    print(" -----+------------+------------------------------------------")
    for reloj, estado, evento in traza:
        print(f" {reloj:>4} | {estado:<10} | {evento}")

    tick_es = next(t for t, _, ev in traza if "ES bloque" in ev)
    tick_libre = next(t for t, _, ev in traza if "terminó la E/S" in ev)
    print(f"\n ES emitida en el tick {tick_es}, liberada en el tick {tick_libre}")

    assert tick_libre - tick_es == 5                 # 1 + 40 // 10
    estados = {t: e for t, e, _ in traza}
    for t in range(tick_es, tick_libre):             # bloqueado todo ese lapso
        assert estados[t] == "BLOQUEADO"
    assert estados[tick_libre] == "TERMINADO"        # corre su último CPU 1
    assert disco.metricas_disco()["solicitudes_atendidas"] == 1


@pytest.mark.parametrize("bloque, ticks", [(0, 1), (9, 1), (10, 2), (40, 5), (199, 20)])
def test_ticks_de_bloqueo_siguen_la_formula(bloque, ticks):
    """Con el cabezal en 0: ticks = 1 + bloque // 10."""
    disco.reiniciar(CONFIG)
    disco.encolar_solicitud_disco(PID, bloque, "L")
    llamadas = 0
    while not disco.avanzar_tick():
        llamadas += 1
    assert llamadas + 1 == ticks