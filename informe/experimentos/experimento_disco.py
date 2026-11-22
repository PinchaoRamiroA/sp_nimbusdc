"""Experimento de disco (informe, sección 2.3): C-LOOK vs. SSTF vs. FCFS.

Con 5 semillas fijas mide, para la misma carga y cada política:
  A) Lote: el cabezal arranca en un bloque al azar y se atienden 40
     solicitudes al azar con ``procesar_disco()``.
  B) Dinámico: un escenario de respaldo corrido con el kernel real (E/S que
     llega mientras otras se atienden). Mide desplazamiento y espera máxima.
  C) Inanición: una solicitud lejana (bloque 190) mientras llega una solicitud
     cercana por tick (bloques 0-30). Se mide cuánto espera la lejana.
  D) Carga creciente: solicitudes a bloques al azar con probabilidad ``tasa``
     por tick durante 2000 ticks. Se mide la espera máxima (RD1 pide <= 200).
El ahorro es ``1 - desplazamiento / desplazamiento_FCFS`` (RD1 pide >= 30 %).

Uso (desde la raíz del repositorio):
    python informe/experimentos/experimento_disco.py
    python informe/experimentos/experimento_disco.py --guardar tests/escenarios/disco.json
"""
from contextlib import contextmanager
import json
import os
import random
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from minidc import disco, kernel, procesos  # noqa: E402

CONFIG = {"num_cpus": 1, "marcos_fisicos": 16, "tam_pagina": 256,
          "bloques_disco": 200, "tam_bloque": 512, "cache_bloques": 0}
SEMILLAS = [1, 2, 3, 4, 5]
POLITICAS = ["FCFS", "SSTF", "C-LOOK"]


@contextmanager
def politica(nombre: str):
    """Activa una política durante el bloque ``with`` y siempre deja C-LOOK al salir."""

    disco._fijar_politica(nombre)
    try:
        yield
    finally:
        disco._fijar_politica("C-LOOK")


def lote(semilla: int, nombre: str, n: int = 40) -> int:
    """Desplazamiento de ``n`` solicitudes al azar con el cabezal en un bloque al azar."""

    r = random.Random(semilla)
    with politica(nombre):
        disco.reiniciar(CONFIG)
        disco.encolar_solicitud_disco(0, r.randrange(CONFIG["bloques_disco"]), "L")
        disco.procesar_disco()                         # lleva el cabezal al bloque inicial
        inicial = disco.metricas_disco()["desplazamiento_total"]
        for pid in range(1, n + 1):
            disco.encolar_solicitud_disco(pid, r.randrange(CONFIG["bloques_disco"]), "L")
        disco.procesar_disco()
        return disco.metricas_disco()["desplazamiento_total"] - inicial


def escenario_json(semilla: int, n_procesos: int = 10, n_es: int = 8) -> dict:
    """Escenario de respaldo con el formato del enunciado: E/S a bloques al azar."""

    r = random.Random(semilla)
    catalogo, llegadas = {}, []
    for i in range(n_procesos):
        programa = []
        for _ in range(n_es):
            programa += [["CPU", 1], ["ES", r.randrange(CONFIG["bloques_disco"])]]
        programa.append(["CPU", 1])
        catalogo[f"respaldo_{i}"] = {"memoria_bytes": 1024, "cuota_marcos": 2,
                                     "prioridad": 1, "programa": programa}
        llegadas.append({"tick": r.randrange(20), "programa": f"respaldo_{i}",
                         "usuario": "cliente_a" if i % 2 == 0 else "cliente_b"})
    return {"config": CONFIG, "usuarios": ["cliente_a", "cliente_b"], "semaforos": {},
            "catalogo": catalogo, "llegadas": llegadas}


def correr_escenario(ruta: str, nombre: str, max_ticks: int = 5000) -> dict:
    """Corre un escenario con el kernel real hasta que todos los procesos terminen.

    Si no terminan en ``max_ticks`` lanza un error: las métricas parciales
    subestimarían la espera máxima (solo cuentan solicitudes terminadas).
    """

    with politica(nombre):
        kernel.cargar_escenario(ruta)
        while kernel.reloj_actual() < max_ticks:
            kernel.tick()
            lista = procesos.listar_procesos()
            if lista and all(p["estado"] == "TERMINADO" for p in lista) and not kernel._llegadas_pendientes:
                break
        else:
            raise RuntimeError(f"{nombre}: el escenario no terminó en {max_ticks} ticks")
        return dict(disco.metricas_disco(), **disco.estadisticas_espera(), ticks=kernel.reloj_actual())


def dinamico(semilla: int, nombre: str) -> dict:
    """Genera el escenario de la semilla en un archivo temporal y lo corre."""

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(escenario_json(semilla), f)
    try:
        return correr_escenario(f.name, nombre)
    finally:
        os.unlink(f.name)


def inanicion(nombre: str, ticks: int = 400) -> int | None:
    """Ticks que espera la solicitud del bloque 190 (None si no la atendió)."""

    r = random.Random(7)
    with politica(nombre):
        disco.reiniciar(CONFIG)
        disco.encolar_solicitud_disco(1, 20, "L")           # el cabezal arranca abajo
        disco.encolar_solicitud_disco(999, 190, "L")        # la solicitud lejana
        for t in range(1, ticks + 1):
            if 999 in disco.avanzar_tick():
                return t
            disco.encolar_solicitud_disco(2, r.randrange(31), "L")   # una cercana por tick
        return None


def carga_creciente(nombre: str, tasa: float, semilla: int, ticks: int = 2000) -> int:
    """Espera máxima (ticks) con llegadas al azar: probabilidad ``tasa`` por tick."""

    r = random.Random(semilla)
    with politica(nombre):
        disco.reiniciar(CONFIG)
        encoladas = 0
        for _ in range(ticks):
            if r.random() < tasa:
                disco.encolar_solicitud_disco(1, r.randrange(CONFIG["bloques_disco"]), "L")
                encoladas += 1
            disco.avanzar_tick()
        while disco.metricas_disco()["solicitudes_atendidas"] < encoladas:   # vaciar la cola
            disco.avanzar_tick()
        return disco.estadisticas_espera()["espera_maxima"]


def main() -> None:
    if "--guardar" in sys.argv:
        ruta = sys.argv[sys.argv.index("--guardar") + 1]
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump(escenario_json(SEMILLAS[0]), f, indent=1)
        print(f"Escenario guardado en {ruta}")
        return

    print("=== A) LOTE: 40 solicitudes, cabezal inicial al azar — desplazamiento (ahorro vs FCFS) ===")
    for semilla in SEMILLAS:
        resultados = {p: lote(semilla, p) for p in POLITICAS}
        base = resultados["FCFS"]
        print(f"semilla {semilla}: " + " | ".join(
            f"{p} {v:>5} ({1 - v / base:>5.1%})" for p, v in resultados.items()))

    print("\n=== B) DINÁMICO: escenario de respaldo con el kernel real ===")
    print("semilla | política | desplazamiento | ahorro vs FCFS | espera máx | espera prom | ticks")
    for semilla in SEMILLAS:
        resultados = {p: dinamico(semilla, p) for p in POLITICAS}
        base = resultados["FCFS"]["desplazamiento_total"]
        for p, m in resultados.items():
            print(f"{semilla:>7} | {p:<8} | {m['desplazamiento_total']:>14} | "
                  f"{1 - m['desplazamiento_total'] / base:>14.1%} | {m['espera_maxima']:>10} | "
                  f"{m['espera_promedio']:>11.1f} | {m['ticks']:>5}")

    print("\n=== C) INANICIÓN: espera de la solicitud al bloque 190 (400 ticks máx.) ===")
    for p in POLITICAS:
        espera = inanicion(p)
        print(f"{p:<7}: " + (f"{espera} ticks" if espera is not None else "nunca la atiende (inanición)"))

    print("\n=== D) CARGA CRECIENTE: espera máxima en ticks (peor de las 5 semillas) ===")
    tasas = [0.1, 0.2, 0.4, 0.6, 0.7, 0.8, 0.9]
    print("política | " + " | ".join(f"tasa {t:<4}" for t in tasas))
    for p in POLITICAS:
        fila = [max(carga_creciente(p, t, s) for s in SEMILLAS) for t in tasas]
        print(f"{p:<8} | " + " | ".join(f"{v:>9}" for v in fila))


if __name__ == "__main__":
    main()
