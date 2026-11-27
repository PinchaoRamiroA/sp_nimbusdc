"""Experimento de hiperpaginación (informe, sección 2.2, RM2): ¿cómo reaccionar?

Compara cuatro reacciones con el kernel completo, cargando cada escenario con
``kernel.cargar_escenario`` (como lo hace el docente):

- NINGUNA: solo se detecta (línea base).
- SUSPENDER: se suspenden los procesos menos importantes hasta que las cuotas
  de los que quedan quepan en memoria; nadie pasa de su cuota.
- PRESTAR_LIBRES: sin suspender a nadie, los marcos libres se prestan a quien
  necesita más de los que tiene.
- CONJUNTO_TRABAJO (la elegida): los más importantes se quedan con todas las
  páginas que están usando (su conjunto de trabajo, aunque pase de su cuota) y
  los que no caben se suspenden hasta que haya marcos.

Escenarios:
- A) Cuota chica: 6 analíticas recorren 8 páginas en ciclo con cuota de 2
  marcos (la suma de cuotas, 12, cabe en los 16 marcos). Es el de la prueba
  ``test_rm2_la_tasa_de_fallos_baja_despues_de_detectar_hiperpaginacion``.
- B) Sobrecarga: 6 analíticas con fases de localidad (4 páginas calientes) y
  cuota 4, más 2 servicios web, en 12 marcos (la suma de cuotas, 28, no cabe).
  5 semillas; la semilla 1 es ``tests/escenarios/hiperpaginacion.json``.
- C) Nominal: ``tests/escenarios/memoria.json`` (RM1). Sin hiperpaginación, la
  reacción no debe cambiar nada.

Métricas: tasa de fallos total, tick de la primera detección, tasa de fallos
de los accesos de los 50 ticks siguientes (RM2), ticks hasta terminar y
utilización de CPU.

Uso (desde la raíz del repositorio):
    python informe/experimentos/experimento_hiperpaginacion.py
    python informe/experimentos/experimento_hiperpaginacion.py --guardar tests/escenarios/hiperpaginacion.json
"""
import json
import os
import random
import sys
import tempfile

RAIZ = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, RAIZ)

from minidc import kernel, memoria, procesos  # noqa: E402

REACCIONES = ["NINGUNA", "SUSPENDER", "PRESTAR_LIBRES", "CONJUNTO_TRABAJO"]
SEMILLAS = [1, 2, 3, 4, 5]
TAM_PAGINA = 256
MAXIMO_TICKS = 20_000


def escenario_cuota_chica() -> dict:
    """A) 6 analíticas que recorren 8 páginas en ciclo con cuota 2."""
    recorrido = [["MEM", pagina * TAM_PAGINA] for pagina in range(8)] * 30
    return {
        "config": {"num_cpus": 1, "marcos_fisicos": 16, "tam_pagina": TAM_PAGINA,
                   "bloques_disco": 200, "tam_bloque": 512, "cache_bloques": 8},
        "usuarios": ["cliente_a", "cliente_b"],
        "semaforos": {},
        "catalogo": {"analitica": {"memoria_bytes": 2048, "cuota_marcos": 2, "prioridad": 2,
                                   "programa": recorrido}},
        "llegadas": [{"tick": 0, "programa": "analitica", "usuario": "cliente_a"} for _ in range(6)],
    }


def programa_con_fases(r: random.Random, paginas: int, calientes: int, fases: int, por_fase: int) -> list:
    """En cada fase, los accesos recorren un conjunto de ``calientes`` páginas
    elegidas al azar; cada 4 accesos hay 1 tick de CPU."""
    programa = []
    for _ in range(fases):
        conjunto = r.sample(range(paginas), calientes)
        for i in range(por_fase):
            programa.append(["MEM", conjunto[i % calientes] * TAM_PAGINA + r.randrange(TAM_PAGINA)])
            if i % 4 == 3:
                programa.append(["CPU", 1])
    return programa


def escenario_sobrecarga(semilla: int) -> dict:
    """B) 6 analíticas (cuota 4) y 2 web (cuota 2) en 12 marcos: las cuotas suman 28."""
    r = random.Random(semilla)
    catalogo, llegadas = {}, []
    for i in range(6):
        nombre = f"analitica_{i}"
        catalogo[nombre] = {"memoria_bytes": 4096, "cuota_marcos": 4, "prioridad": 2,
                            "programa": programa_con_fases(r, 16, 4, 3, 40)}
        llegadas.append({"tick": r.randint(0, 10), "programa": nombre, "usuario": "cliente_a"})
    for i in range(2):
        nombre = f"web_{i}"
        web = []
        for _ in range(6):
            web += [["CPU", 1], ["MEM", r.randrange(2) * TAM_PAGINA], ["ES", r.randrange(200)]]
        catalogo[nombre] = {"memoria_bytes": 1024, "cuota_marcos": 2, "prioridad": 0, "programa": web}
        llegadas.append({"tick": r.randint(0, 30), "programa": nombre, "usuario": "cliente_b"})
    llegadas.sort(key=lambda llegada: llegada["tick"])
    return {
        "config": {"num_cpus": 1, "marcos_fisicos": 12, "tam_pagina": TAM_PAGINA,
                   "bloques_disco": 200, "tam_bloque": 512, "cache_bloques": 8},
        "usuarios": ["cliente_a", "cliente_b"],
        "semaforos": {},
        "catalogo": catalogo,
        "llegadas": llegadas,
    }


def escenario_nominal() -> dict:
    """C) El escenario de memoria de las pruebas (RM1)."""
    with open(os.path.join(RAIZ, "tests", "escenarios", "memoria.json"), encoding="utf-8") as f:
        return json.load(f)


def correr(escenario: dict, reaccion: str) -> dict:
    """Carga el escenario con el kernel, lo corre hasta el final y mide."""
    memoria._fijar_reaccion(reaccion)
    try:
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = os.path.join(carpeta, "escenario.json")
            with open(ruta, "w", encoding="utf-8") as f:
                json.dump(escenario, f)
            kernel.cargar_escenario(ruta)
        ultima_llegada = max(llegada["tick"] for llegada in escenario["llegadas"])
        deteccion, antes, despues = None, None, None
        while kernel.reloj_actual() < MAXIMO_TICKS:
            kernel.tick()
            reloj = kernel.reloj_actual()
            if deteccion is None and memoria.detectar_hiperpaginacion():
                deteccion, antes = reloj, memoria.metricas_memoria()
            if deteccion is not None and reloj == deteccion + 50:
                despues = memoria.metricas_memoria()
            if reloj >= ultima_llegada and all(p["estado"] == "TERMINADO" for p in procesos.listar_procesos()):
                break
        else:
            raise RuntimeError(f"El escenario no terminó en {MAXIMO_TICKS} ticks con {reaccion}")
        if deteccion is not None and despues is None:
            despues = memoria.metricas_memoria()   # terminó antes de 50 ticks
        final = memoria.metricas_memoria()
        tasa_50 = None
        if deteccion is not None:
            accesos = despues["accesos"] - antes["accesos"]
            tasa_50 = (despues["fallos_pagina"] - antes["fallos_pagina"]) / accesos if accesos else 0.0
        return {
            "tasa_total": final["tasa_fallos"],
            "deteccion": deteccion,
            "tasa_antes": antes["tasa_fallos"] if antes else None,
            "tasa_50": tasa_50,
            "ticks": kernel.reloj_actual(),
            "utilizacion": procesos.metricas_planificacion()["utilizacion_cpu"],
            "reacciones": memoria.estado_control_carga()["reacciones"],
        }
    finally:
        memoria._fijar_reaccion("CONJUNTO_TRABAJO")


def formato(valor, decimales=3) -> str:
    return "-" if valor is None else f"{valor:.{decimales}f}"


def imprimir(titulo: str, filas: dict) -> None:
    print(f"\n{titulo}")
    print(f"{'Reacción':<17} {'tasa total':>10} {'detección':>9} {'tasa antes':>10} "
          f"{'tasa 50 t':>9} {'ticks':>6} {'CPU':>6} {'reacc.':>6}")
    for reaccion, m in filas.items():
        print(f"{reaccion:<17} {formato(m['tasa_total']):>10} {str(m['deteccion'] or '-'):>9} "
              f"{formato(m['tasa_antes']):>10} {formato(m['tasa_50']):>9} {m['ticks']:>6} "
              f"{formato(m['utilizacion'], 2):>6} {m['reacciones']:>6}")


def promedio(medidas: list, clave: str):
    valores = [m[clave] for m in medidas if m[clave] is not None]
    return sum(valores) / len(valores) if valores else None


def main() -> None:
    if "--guardar" in sys.argv:
        ruta = sys.argv[sys.argv.index("--guardar") + 1]
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump(escenario_sobrecarga(SEMILLAS[0]), f, indent=1, ensure_ascii=False)
            f.write("\n")
        print(f"Escenario guardado en {ruta}")
        return

    imprimir("A) Cuota chica (6 analíticas, ciclo de 8 páginas, cuota 2, 16 marcos)",
             {r: correr(escenario_cuota_chica(), r) for r in REACCIONES})

    print("\nB) Sobrecarga (cuotas 28 en 12 marcos), por semilla: tasa total / tasa 50 ticks / ticks")
    resumen = {}
    for reaccion in REACCIONES:
        medidas = [correr(escenario_sobrecarga(s), reaccion) for s in SEMILLAS]
        resumen[reaccion] = medidas
        detalle = "  ".join(f"{formato(m['tasa_total'], 2)}/{formato(m['tasa_50'], 2)}/{m['ticks']}"
                            for m in medidas)
        print(f"{reaccion:<17} {detalle}")
    print("\nB) Promedio de las 5 semillas")
    print(f"{'Reacción':<17} {'tasa total':>10} {'tasa antes':>10} {'tasa 50 t':>9} {'ticks':>7} {'CPU':>6}")
    for reaccion, medidas in resumen.items():
        print(f"{reaccion:<17} {formato(promedio(medidas, 'tasa_total')):>10} "
              f"{formato(promedio(medidas, 'tasa_antes')):>10} {formato(promedio(medidas, 'tasa_50')):>9} "
              f"{promedio(medidas, 'ticks'):>7.1f} {formato(promedio(medidas, 'utilizacion'), 2):>6}")

    imprimir("C) Nominal (tests/escenarios/memoria.json, RM1)",
             {r: correr(escenario_nominal(), r) for r in REACCIONES})


if __name__ == "__main__":
    main()
