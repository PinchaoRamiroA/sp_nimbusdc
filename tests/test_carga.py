"""Pruebas de carga: muchos escenarios distintos, generados al azar con semilla fija.

En la sustentación se usan escenarios distintos a los publicados. Por eso aquí
el sistema se prueba con escenarios generados (siempre los mismos para cada
semilla) y en cada tick se revisa que nada se descuadre. Solo se usan funciones
del enunciado y los escenarios se cargan con kernel.cargar_escenario.
"""
import json
import random

import pytest

from minidc import archivos, consola, disco, kernel, memoria, procesos

ESTADOS = {"NUEVO", "LISTO", "EJECUTANDO", "BLOQUEADO", "TERMINADO"}
SEMILLAS = range(25)


# ------------------------------------------------------------------ escenarios
def generar_escenario(semilla, llegadas=30, ultima_llegada=150):
    """Arma un escenario al azar con el formato del enunciado y sus 4 tipos de servicio.

    Mientras sincronizacion.py no esté implementado, procesos.py deja pasar los
    WAIT y SIGNAL de "bd", así que el escenario sirve igual.
    """
    azar = random.Random(semilla)
    config = {"num_cpus": azar.randint(1, 3), "marcos_fisicos": azar.choice([8, 16, 32]),
              "tam_pagina": azar.choice([128, 256, 512]), "bloques_disco": azar.choice([100, 200, 500]),
              "tam_bloque": 512, "cache_bloques": azar.choice([0, 4, 8])}
    bloques = config["bloques_disco"]

    web = []                                        # ráfagas cortas de CPU y E/S frecuente
    for _ in range(azar.randint(1, 3)):
        web += [["CPU", azar.randint(1, 3)], ["ES", azar.randrange(bloques)], ["MEM", azar.randrange(1024)]]
    analitica = []                                  # ráfagas largas de CPU y mucha memoria
    for _ in range(azar.randint(2, 3)):
        analitica += [["CPU", azar.randint(20, 60)], ["MEM", azar.randrange(8192)]]
    respaldo = [["CPU", 1]] + [["ES", azar.randrange(bloques)] for _ in range(azar.randint(3, 5))] + [["CPU", 1]]
    bd = [["CPU", 1], ["WAIT", "bd"], ["MEM", azar.randrange(1024)],    # sección crítica con el semáforo
          ["CPU", azar.randint(1, 4)], ["SIGNAL", "bd"], ["CPU", 1]]

    catalogo = {
        "web": {"memoria_bytes": 1024, "cuota_marcos": 2, "prioridad": 0, "programa": web},
        "analitica": {"memoria_bytes": 8192, "cuota_marcos": azar.randint(2, 6), "prioridad": 2,
                      "programa": analitica},
        "respaldo": {"memoria_bytes": 2048, "cuota_marcos": 2, "prioridad": 1, "programa": respaldo},
        "bd": {"memoria_bytes": 1024, "cuota_marcos": 2, "prioridad": 1, "programa": bd},
    }
    lista_llegadas = [{"tick": azar.randint(0, ultima_llegada), "programa": azar.choice(list(catalogo)),
                       "usuario": azar.choice(["admin", "cliente_a", "cliente_b"])} for _ in range(llegadas)]
    lista_llegadas.sort(key=lambda llegada: llegada["tick"])
    return {"config": config, "usuarios": ["cliente_a", "cliente_b"], "semaforos": {"bd": 1},
            "catalogo": catalogo, "llegadas": lista_llegadas}


def guardar_escenario(tmp_path, escenario):
    """Escribe el escenario como JSON y devuelve su ruta, para cargarlo como lo hace el profesor."""
    ruta = tmp_path / "escenario.json"
    ruta.write_text(json.dumps(escenario), encoding="utf-8")
    return str(ruta)


# ------------------------------------------------------- revisión y ejecución
def verificar_sistema(num_cpus):
    """Revisa las reglas que nunca deben romperse, usando solo funciones del enunciado.

    Devuelve la lista de procesos que revisó, para no tener que pedirla otra vez.
    """
    lista = procesos.listar_procesos()
    estados = {p["pid"]: p["estado"] for p in lista}
    assert set(estados.values()) <= ESTADOS
    listos = sorted(pid for pid in estados if estados[pid] == "LISTO")
    ejecutando = sorted(pid for pid in estados if estados[pid] == "EJECUTANDO")
    terminados = list(estados.values()).count("TERMINADO")

    # Cada proceso LISTO está una sola vez en la cola y cada EJECUTANDO está en una sola CPU
    assert sorted(procesos.cola_listos()) == listos
    en_cpus = [procesos.proceso_en_ejecucion(cpu) for cpu in range(num_cpus)]
    assert sorted(pid for pid in en_cpus if pid is not None) == ejecutando

    # Los marcos cuadran y un proceso terminado no conserva marcos
    estado_memoria = memoria.estado_memoria()
    usados = sum(estado_memoria["marcos_por_proceso"].values())
    assert usados + estado_memoria["marcos_libres"] == estado_memoria["marcos_totales"]
    for pid, marcos in estado_memoria["marcos_por_proceso"].items():
        assert marcos == 0 or estados[pid] != "TERMINADO"

    # El resumen del kernel y las métricas coinciden con lo que dice cada módulo
    resumen = kernel.resumen_sistema()
    assert resumen["marcos_libres"] == estado_memoria["marcos_libres"]
    assert resumen["bloques_libres"] == archivos.fs_estado_disco()["bloques_libres"]
    assert resumen["procesos_activos"] == len(lista) - terminados
    metricas = procesos.metricas_planificacion()
    assert 0 <= metricas["utilizacion_cpu"] <= 1
    assert metricas["procesos_terminados"] == terminados
    return lista


def correr_revisando_cada_tick(num_cpus, ultima_llegada, maximo=5000):
    """Avanza tick a tick, revisando el sistema, hasta que llegaron y terminaron todos.

    Devuelve la peor espera seguida en LISTO (ticks sin usar la CPU) de cualquier proceso: RP2.
    """
    cpu_usada, espera_seguida, peor_espera = {}, {}, 0
    while kernel.reloj_actual() < maximo:
        reloj_antes = kernel.reloj_actual()
        kernel.tick()
        assert kernel.reloj_actual() == reloj_antes + 1
        lista = verificar_sistema(num_cpus)
        for p in lista:
            corrio = p["cpu_usada"] > cpu_usada.get(p["pid"], 0)
            cpu_usada[p["pid"]] = p["cpu_usada"]
            if p["estado"] == "LISTO" and not corrio:
                espera_seguida[p["pid"]] = espera_seguida.get(p["pid"], 0) + 1
            else:
                espera_seguida[p["pid"]] = 0
            peor_espera = max(peor_espera, espera_seguida[p["pid"]])
        if kernel.reloj_actual() >= ultima_llegada and all(p["estado"] == "TERMINADO" for p in lista):
            return peor_espera
    raise AssertionError(f"Los procesos no terminaron en {maximo} ticks")


def correr_escenario(tmp_path, escenario):
    """Carga el escenario con el kernel y lo corre hasta el final. Devuelve la peor espera (RP2)."""
    kernel.cargar_escenario(guardar_escenario(tmp_path, escenario))
    return correr_revisando_cada_tick(escenario["config"]["num_cpus"], escenario["llegadas"][-1]["tick"])


def bloques_de_los_archivos(ruta="/"):
    """Suma los bloques de todos los archivos del árbol, recorriéndolo como admin."""
    total = 0
    for nombre in archivos.fs_listar(ruta, "admin"):
        hijo = ruta.rstrip("/") + "/" + nombre
        info = archivos.fs_info(hijo)               # un enlace no se sigue: no ocupa bloques
        if info["tipo"] == "directorio":
            total += bloques_de_los_archivos(hijo)
        else:
            total += len(info["bloques"])
    return total


# -------------------------------------------------------------------- pruebas
@pytest.mark.parametrize("semilla", SEMILLAS)
def test_carga_cuadra_en_cada_tick_cumple_rp2_y_termina_limpio(tmp_path, semilla):
    """Cada escenario se corre una sola vez y se revisa todo.

    En cada tick todo cuadra, nadie espera más de 150 ticks seguidos en LISTO (RP2)
    y al final todos terminaron sin dejar memoria ni E/S pendiente.
    """
    escenario = generar_escenario(semilla)
    assert correr_escenario(tmp_path, escenario) <= 150
    assert procesos.metricas_planificacion()["procesos_terminados"] == len(escenario["llegadas"])
    estado_memoria = memoria.estado_memoria()
    assert estado_memoria["marcos_libres"] == estado_memoria["marcos_totales"]
    assert disco.cola_disco() == []


@pytest.mark.parametrize("cantidad, rafaga, prioridad", [(2, 200, 0), (2, 200, 1), (3, 100, 2), (4, 60, 0)])
def test_rp2_procesos_largos_con_la_misma_prioridad(cantidad, rafaga, prioridad):
    """El caso que rompía RP2 antes del quantum: ráfagas largas que no sueltan la CPU."""
    kernel.iniciar_sistema({"num_cpus": 1})
    for numero in range(cantidad):
        procesos.crear_proceso(f"analitica_{numero}", "admin", [("CPU", rafaga)], prioridad=prioridad)
    assert correr_revisando_cada_tick(1, 0) <= 150


@pytest.mark.parametrize("num_cpus", [1, 2, 3])
def test_rp3_utilizacion_de_al_menos_85_por_ciento_con_carga_continua(tmp_path, num_cpus):
    """Llega un servicio de analítica cada 5 ticks: ninguna CPU debería quedarse quieta."""
    escenario = generar_escenario(0, llegadas=0)
    escenario["config"]["num_cpus"] = num_cpus
    escenario["llegadas"] = [{"tick": tick, "programa": "analitica", "usuario": "cliente_a"}
                             for tick in range(0, 200, 5)]
    kernel.cargar_escenario(guardar_escenario(tmp_path, escenario))
    kernel.ejecutar_ticks(200)
    assert procesos.metricas_planificacion()["utilizacion_cpu"] >= 0.85


def test_estres_100_procesos_en_3_cpu(tmp_path):
    escenario = generar_escenario(2026, llegadas=100, ultima_llegada=300)
    escenario["config"]["num_cpus"] = 3
    assert correr_escenario(tmp_path, escenario) <= 150
    assert procesos.metricas_planificacion()["procesos_terminados"] == 100


def test_consola_bajo_carga_con_tres_usuarios(tmp_path):
    """500 comandos al azar de 3 usuarios: siempre hay respuesta en texto, todo cuadra y se cumple RF1."""
    escenario = generar_escenario(7)
    ruta = guardar_escenario(tmp_path, escenario)
    assert not consola.ejecutar_comando(f'load "{ruta}"').startswith("Error:")
    azar = random.Random(7)
    plantillas = ["mkdir {d}", "cd {d}", "cd /", 'echo "{t}" > {f}', 'echo "{t}" >> {f}', "cat {f}", "touch {f}",
                  "rm {f}", "rm -r {d}", "chmod {m} {f}", "ln -s {f} {d}/enlace", "ls", "ls -l", "tree /",
                  "pwd", "whoami", "df", "free", "ps", "top", "tick 3", "run web", "run analitica", "kill {p}"]
    for _ in range(500):
        linea = azar.choice(plantillas).format(
            d=azar.choice(["/a", "/b", "/a/c", "c"]), f=azar.choice(["/x.txt", "/a/y.txt", "z.txt"]),
            t="w" * azar.randint(0, 900), m=azar.choice(["600", "644", "777", "000"]), p=azar.randint(1, 40))
        usuario = azar.choice(["admin", "cliente_a", "cliente_b"])
        assert isinstance(consola.ejecutar_comando(linea, usuario), str)
        verificar_sistema(escenario["config"]["num_cpus"])
        estado_disco = archivos.fs_estado_disco()   # RF1: usados + libres = total
        assert bloques_de_los_archivos() + estado_disco["bloques_libres"] == estado_disco["bloques_totales"]
