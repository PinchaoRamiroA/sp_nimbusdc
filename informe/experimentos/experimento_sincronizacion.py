"""Experimento reproducible de sincronización y prevención/resolución de interbloqueos.

Evalúa y documenta métricas cuantitativas para el informe de diseño:
1. Condición de carrera (RS1): comparación cuantitativa con y sin sincronización.
2. Detección y resolución de interbloqueos (RS2): verificación de ciclos en WFG y resolución determinista.
3. Exclusión mutua en procesos simulados concurrentes sobre recursos compartidos ("bd").
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from minidc import kernel, procesos, sincronizacion


def experimento_condicion_carrera():
    print("=== 1. CONDICIÓN DE CARRERA CON HILOS REALES (RS1) ===")
    print(f"{'Hilos':>6} | {'Iteraciones':>11} | {'Esperado':>10} | {'Con Sync':>10} | {'Sin Sync':>10} | {'Pérdida Sin Sync (%)':>20}")
    print("-" * 80)

    configuraciones = [
        (2, 1000),
        (4, 1000),
        (8, 1000),
        (8, 5000),
    ]

    for hilos, iters in configuraciones:
        esperado = hilos * iters
        con_sync = sincronizacion.demo_condicion_carrera(True, hilos, iters)
        sin_sync = sincronizacion.demo_condicion_carrera(False, hilos, iters)
        perdida_pct = ((esperado - sin_sync) / esperado) * 100.0
        print(f"{hilos:>6} | {iters:>11} | {esperado:>10} | {con_sync:>10} | {sin_sync:>10} | {perdida_pct:>19.1f}%")
    print()


def experimento_interbloqueos():
    print("=== 2. DETECCIÓN Y RESOLUCIÓN DE INTERBLOQUEOS (RS2) ===")
    sincronizacion.reiniciar()

    # Escenario de interbloqueo circular de N procesos (P0 -> P1 -> P2 -> ... -> P0)
    for n in [2, 4, 8]:
        sincronizacion.reiniciar()
        # Crear N mutexes
        for i in range(n):
            sincronizacion.crear_mutex(f"res_{i}")
        # Cada proceso i adquiere res_i
        for i in range(n):
            sincronizacion.mutex_lock(f"res_{i}", i)
        # Cada proceso i intenta adquirir res_{(i+1)%n} (quedando en espera)
        for i in range(n):
            sincronizacion.mutex_lock(f"res_{(i + 1) % n}", i)

        t0 = time.perf_counter()
        ciclos = sincronizacion.detectar_interbloqueo()
        t_detect = (time.perf_counter() - t0) * 1000

        assert len(ciclos) >= 1, f"Debía detectarse ciclo para n={n}"
        longitud_ciclo = len(ciclos[0])

        t0 = time.perf_counter()
        afectados = sincronizacion.resolver_interbloqueo()
        t_resolv = (time.perf_counter() - t0) * 1000

        ciclos_post = sincronizacion.detectar_interbloqueo()
        assert ciclos_post == [], "RS2 violado: quedaron interbloqueos"

        print(f"N={n:2d} procesos | Ciclos detectados: {len(ciclos)} (longitud {longitud_ciclo}) en {t_detect:.3f} ms | "
              f"Víctimas abortadas: {afectados} en {t_resolv:.3f} ms | Ciclos tras resolución: {len(ciclos_post)} (RS2 OK)")
    print()


def experimento_exclusion_mutua_simulada():
    print("=== 3. EXCLUSIÓN MUTUA EN RECURSO COMPARTIDO SIMULADO (bd) ===")
    config = {
        "num_cpus": 3,
        "marcos_fisicos": 16,
        "tam_pagina": 256,
        "bloques_disco": 200,
        "tam_bloque": 512,
        "cache_bloques": 8,
    }
    kernel.iniciar_sistema(config)
    sincronizacion.crear_semaforo("bd", 1)

    num_procesos = 6
    for i in range(num_procesos):
        procesos.crear_proceso(f"cliente_{i}", "admin", [("WAIT", "bd"), ("CPU", 3), ("SIGNAL", "bd")])

    max_dentro = 0
    ticks = 0
    while not all(p["estado"] == "TERMINADO" for p in procesos.listar_procesos()) and ticks < 100:
        kernel.tick()
        ticks += 1
        lista = procesos.listar_procesos()
        dentro = [p for p in lista if p["cpu_usada"] > 0 and p["estado"] != "TERMINADO"]
        if len(dentro) > max_dentro:
            max_dentro = len(dentro)
        assert len(dentro) <= 1, f"Violación de exclusión mutua: {len(dentro)} procesos dentro de la sección crítica"

    estado_final = sincronizacion.estado_semaforo("bd")
    print(f"6 procesos concurrentes en 3 CPUs | Máx procesos simultáneos en SC: {max_dentro} | Ticks: {ticks} | Estado final semáforo: {estado_final}")
    print()


if __name__ == "__main__":
    experimento_condicion_carrera()
    experimento_interbloqueos()
    experimento_exclusion_mutua_simulada()
