"""Experimento de memoria (informe, sección 2.2): Reloj vs. LRU vs. FIFO.

Genera, con 5 semillas fijas, la misma carga para cada política y mide
``tasa_fallos``, ``reemplazos`` y ``escrituras_a_swap`` con las funciones
del enunciado. También puede guardar el escenario de memoria de las pruebas.

Uso (desde la raíz del repositorio):
    python informe/experimentos/experimento_memoria.py
    python informe/experimentos/experimento_memoria.py --guardar tests/escenarios/memoria.json
"""
import json
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from minidc import memoria  # noqa: E402

CONFIG = {"num_cpus": 1, "marcos_fisicos": 16, "tam_pagina": 256,
          "bloques_disco": 200, "tam_bloque": 512, "cache_bloques": 8}
# Servicios: (nombre, memoria_bytes, cuota_marcos, prioridad, fases, accesos por fase, copias)
# Nominal: las cuotas suman 15 <= 16 marcos (memoria bien dimensionada). Se exige RM1.
NOMINAL = [
    ("analitica", 4096, 6, 2, 3, 60, 1),
    ("web", 1024, 3, 0, 2, 25, 2),
    ("respaldo", 2048, 3, 1, 2, 30, 1),
]
# Sobrecarga: las cuotas suman 22 > 16 marcos y las fases son cortas (estrés; ver RM2).
SOBRECARGA = [
    ("analitica", 4096, 5, 2, 4, 30, 2),
    ("web", 1024, 3, 0, 3, 12, 2),
    ("respaldo", 2048, 3, 1, 3, 15, 2),
]
SEMILLAS = [1, 2, 3, 4, 5]
POLITICAS = ["RELOJ", "FIFO", "LRU"]


def generar_accesos(r: random.Random, memoria_bytes: int, cuota: int, fases: int, por_fase: int) -> list:
    """Direcciones con localidad: en cada fase, el 85 % de los accesos va a un
    conjunto "caliente" de (cuota - 1) páginas y el 15 % a cualquier página."""

    paginas = memoria_bytes // CONFIG["tam_pagina"]
    direcciones = []
    for _ in range(fases):
        calientes = r.sample(range(paginas), min(cuota - 1, paginas))
        for _ in range(por_fase):
            pagina = r.choice(calientes) if r.random() < 0.85 else r.randrange(paginas)
            direcciones.append(pagina * CONFIG["tam_pagina"] + r.randrange(CONFIG["tam_pagina"]))
    return direcciones


def generar_carga(semilla: int, servicios: list = NOMINAL) -> list:
    """Lista de procesos: (nombre, memoria_bytes, cuota, prioridad, direcciones, escrituras)."""

    r = random.Random(semilla)
    carga = []
    for nombre, mem, cuota, prio, fases, por_fase, copias in servicios:
        for copia in range(copias):
            direcciones = generar_accesos(r, mem, cuota, fases, por_fase)
            escrituras = [r.random() < 0.3 for _ in direcciones]
            carga.append((f"{nombre}_{copia}", mem, cuota, prio, direcciones, escrituras))
    return carga


def medir(carga: list, politica: str) -> dict:
    """Ejecuta la carga intercalando los procesos (un acceso de cada uno por turno)."""

    memoria._fijar_politica(politica)
    try:
        memoria.reiniciar(CONFIG)
        for pid, (_, mem, cuota, _, _, _) in enumerate(carga, start=1):
            memoria.registrar_proceso(pid, mem, cuota)
        turno = 0
        pendientes = True
        while pendientes:
            pendientes = False
            for pid, (_, _, _, _, direcciones, escrituras) in enumerate(carga, start=1):
                if turno < len(direcciones):
                    memoria.acceder_memoria(pid, direcciones[turno], escrituras[turno])
                    pendientes = True
            turno += 1
        return memoria.metricas_memoria()
    finally:
        memoria._fijar_politica("RELOJ")   # siempre se deja la política elegida


def escenario_json(semilla: int) -> dict:
    """Escenario con el formato del enunciado: instrucciones ("MEM", dir) y ráfagas de CPU."""

    carga = generar_carga(semilla)
    catalogo, llegadas = {}, []
    for i, (nombre, mem, cuota, prio, direcciones, _) in enumerate(carga):
        programa = []
        for j, direccion in enumerate(direcciones):
            programa.append(["MEM", direccion])
            if j % 5 == 4:
                programa.append(["CPU", 1])
        programa.append(["CPU", 1])
        catalogo[nombre] = {"memoria_bytes": mem, "cuota_marcos": cuota,
                            "prioridad": prio, "programa": programa}
        llegadas.append({"tick": i * 2, "programa": nombre,
                         "usuario": "cliente_a" if i % 2 == 0 else "cliente_b"})
    return {"config": CONFIG, "usuarios": ["cliente_a", "cliente_b"], "semaforos": {},
            "catalogo": catalogo, "llegadas": llegadas}


def main() -> None:
    if "--guardar" in sys.argv:
        ruta = sys.argv[sys.argv.index("--guardar") + 1]
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump(escenario_json(SEMILLAS[0]), f, indent=1)
        print(f"Escenario guardado en {ruta}")
        return

    for titulo, servicios in (("NOMINAL (RM1)", NOMINAL), ("SOBRECARGA (estrés)", SOBRECARGA)):
        print(f"\n=== {titulo} ===")
        print(f"{'semilla':>7} | " + " | ".join(f"{p:^26}" for p in POLITICAS))
        print(f"{'':>7} | " + " | ".join(f"{'tasa':>8} {'reempl':>7} {'swap':>7}" for _ in POLITICAS))
        totales = {p: 0.0 for p in POLITICAS}
        for semilla in SEMILLAS:
            carga = generar_carga(semilla, servicios)
            fila = []
            for politica in POLITICAS:
                m = medir(carga, politica)
                totales[politica] += m["tasa_fallos"]
                fila.append(f"{m['tasa_fallos']:>8.3f} {m['reemplazos']:>7} {m['escrituras_a_swap']:>7}")
            print(f"{semilla:>7} | " + " | ".join(fila))
        print("Promedio tasa_fallos: " + ", ".join(
            f"{p} = {totales[p] / len(SEMILLAS):.3f}" for p in POLITICAS))


if __name__ == "__main__":
    main()
