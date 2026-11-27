"""Hiperpaginación y su reacción, RM2 (Integrante 2, Prototipo 3).

- Detección: solo cuentan los fallos que obligan a sacar una página.
- Reacción (memoria.controlar_hiperpaginacion, la llama kernel.tick): control de
  carga por conjunto de trabajo. Los procesos más importantes se quedan con las
  páginas que están usando y los que no caben se suspenden hasta que haya marcos.
- procesos.suspender_proceso / reanudar_proceso / puede_suspenderse.
- RM2 con el kernel: tests/escenarios/hiperpaginacion.json (lo genera
  informe/experimentos/experimento_hiperpaginacion.py) y el caso de cuota chica.
"""
import json
import os

import pytest

from minidc import kernel, memoria, procesos
from minidc.errores import ErrorMemoria

CONFIG = {"num_cpus": 1, "marcos_fisicos": 16, "tam_pagina": 256,
          "bloques_disco": 200, "tam_bloque": 512, "cache_bloques": 8}
ESC_HIPERPAGINACION = os.path.join(os.path.dirname(__file__), "escenarios", "hiperpaginacion.json")
PAGINA = CONFIG["tam_pagina"]


@pytest.fixture(autouse=True)
def sistema_limpio():
    """Antes de cada prueba: el sistema recién iniciado y la reacción elegida."""
    memoria._fijar_reaccion("CONJUNTO_TRABAJO")
    kernel.iniciar_sistema(CONFIG)
    yield
    memoria._fijar_reaccion("CONJUNTO_TRABAJO")


def leer(ruta):
    with open(ruta, encoding="utf-8") as f:
        return json.load(f)


def ciclo(paginas, vueltas):
    """Programa que recorre ``paginas`` páginas en ciclo ``vueltas`` veces."""
    return [("MEM", pagina * PAGINA) for pagina in range(paginas)] * vueltas


def todos_terminados():
    return all(p["estado"] == "TERMINADO" for p in procesos.listar_procesos())


def correr_hasta_detectar(maximo=500):
    for _ in range(maximo):
        kernel.tick()
        if memoria.detectar_hiperpaginacion():
            return kernel.reloj_actual()
    raise AssertionError("el escenario debía provocar hiperpaginación")


def tasa_en_los_siguientes(ticks):
    """Tasa de fallos de los accesos hechos en los próximos ``ticks`` ticks, y la de antes."""
    antes = memoria.metricas_memoria()
    kernel.ejecutar_ticks(ticks)
    despues = memoria.metricas_memoria()
    accesos = despues["accesos"] - antes["accesos"]
    assert accesos > 0, "debía haber accesos después de reaccionar"
    return (despues["fallos_pagina"] - antes["fallos_pagina"]) / accesos, antes["tasa_fallos"]


def revisar_suspendidos():
    """Un suspendido está BLOQUEADO, no está en la cola ni en una CPU y no tiene marcos."""
    estado = memoria.estado_memoria()
    for pid in memoria.estado_control_carga()["suspendidos"]:
        assert procesos.estado_proceso(pid) == "BLOQUEADO"
        assert pid not in procesos.cola_listos()
        assert procesos.proceso_en_ejecucion(0) != pid
        assert estado["marcos_por_proceso"].get(pid, 0) == 0


# ------------------------------------------------------------- detección
def test_fallos_que_llenan_marcos_libres_no_son_hiperpaginacion():
    """32 páginas distintas con cuota 32: todos son fallos, pero ninguno saca a otra página."""
    kernel.iniciar_sistema(dict(CONFIG, marcos_fisicos=32))
    memoria.registrar_proceso(1, 32 * PAGINA, 32)
    for pagina in range(32):
        assert memoria.acceder_memoria(1, pagina * PAGINA)["fallo_pagina"] is True
    assert memoria.detectar_hiperpaginacion() is False


def test_fallos_que_sacan_paginas_si_son_hiperpaginacion():
    memoria.registrar_proceso(1, 8 * PAGINA, 2)
    for direccion, _ in zip(ciclo(8, 4), range(32)):
        memoria.acceder_memoria(1, direccion[1])
    assert memoria.detectar_hiperpaginacion() is True


# ---------------------------------------------- suspender y reanudar (procesos)
def test_suspender_un_proceso_listo_lo_saca_de_la_cola_y_reanudar_lo_devuelve():
    pid = procesos.crear_proceso("analitica", "admin", [("CPU", 5)])
    assert procesos.suspender_proceso(pid) is True
    assert procesos.estado_proceso(pid) == "BLOQUEADO"
    assert pid not in procesos.cola_listos()
    kernel.ejecutar_ticks(3)                         # suspendido: no usa la CPU
    assert procesos.listar_procesos()[0]["cpu_usada"] == 0
    assert procesos.reanudar_proceso(pid) is True
    assert procesos.estado_proceso(pid) == "LISTO"
    assert procesos.cola_listos() == [pid]


def test_suspender_al_que_esta_en_la_cpu_la_libera():
    pid = procesos.crear_proceso("analitica", "admin", [("CPU", 5)])
    kernel.tick()
    assert procesos.proceso_en_ejecucion(0) == pid
    assert procesos.suspender_proceso(pid) is True
    assert procesos.proceso_en_ejecucion(0) is None
    procesos.reanudar_proceso(pid)
    kernel.ejecutar_ticks(4)                         # termina las 4 ráfagas que le faltaban
    assert procesos.estado_proceso(pid) == "TERMINADO"


def test_un_suspendido_que_termina_su_fallo_de_pagina_sigue_bloqueado():
    pid = procesos.crear_proceso("analitica", "admin", [("MEM", 0), ("CPU", 1)], memoria_bytes=PAGINA)
    kernel.tick()                                    # fallo de página: 5 ticks bloqueado
    assert procesos.suspender_proceso(pid) is True
    kernel.ejecutar_ticks(10)
    assert procesos.estado_proceso(pid) == "BLOQUEADO"
    procesos.reanudar_proceso(pid)
    assert procesos.estado_proceso(pid) == "LISTO"


def test_no_se_suspende_a_quien_espera_disco_tiene_hilos_o_semaforos():
    disco_pid = procesos.crear_proceso("respaldo", "admin", [("ES", 150), ("CPU", 1)])
    hilos_pid = procesos.crear_proceso("web", "admin", [("CPU", 3)])
    procesos.crear_hilo(hilos_pid, [("CPU", 2)])
    kernel.tick()                                    # el respaldo queda esperando al disco
    assert procesos.estado_proceso(disco_pid) == "BLOQUEADO"
    assert procesos.puede_suspenderse(disco_pid) is False
    assert procesos.puede_suspenderse(hilos_pid) is False
    procesos._procesos[hilos_pid]["hilos"] = []      # sin hilos, pero con un semáforo tomado
    procesos._procesos[hilos_pid]["semaforos_adquiridos"] = ["bd"]
    assert procesos.puede_suspenderse(hilos_pid) is False
    assert procesos.suspender_proceso(disco_pid) is False
    assert procesos.puede_suspenderse(999) is False
    assert procesos.reanudar_proceso(disco_pid) is False   # no estaba suspendido


def test_terminar_a_un_suspendido_lo_quita_del_control():
    for i in range(6):
        procesos.crear_proceso(f"analitica_{i}", "admin", ciclo(8, 30), memoria_bytes=8 * PAGINA, cuota_marcos=2)
    correr_hasta_detectar()
    suspendidos = memoria.estado_control_carga()["suspendidos"]
    assert suspendidos
    procesos.terminar_proceso(suspendidos[0])        # lo mismo que hace kill
    assert suspendidos[0] not in memoria.estado_control_carga()["suspendidos"]
    kernel.tick()
    revisar_suspendidos()


# ---------------------------------------------------------- reacción (memoria)
def test_sin_hiperpaginacion_no_se_hace_nada():
    pid = procesos.crear_proceso("web", "admin", [("CPU", 1)], memoria_bytes=PAGINA * 2, cuota_marcos=2)
    memoria.acceder_memoria(pid, 0)
    resultado = memoria.controlar_hiperpaginacion()
    assert resultado == {"reaccion": False, "suspendidos": [], "reanudados": []}
    assert memoria.estado_control_carga()["limites"] == {}


def test_reaccion_suspende_a_los_que_no_caben_y_da_su_conjunto_de_trabajo_a_los_demas():
    """6 procesos que recorren 8 páginas con cuota 2 en 16 marcos: caben 2 con sus 8 páginas."""
    pids = [procesos.crear_proceso(f"analitica_{i}", "admin", ciclo(8, 30),
                                   memoria_bytes=8 * PAGINA, cuota_marcos=2) for i in range(6)]
    correr_hasta_detectar()
    kernel.ejecutar_ticks(30)                        # unas cuantas evaluaciones más
    control = memoria.estado_control_carga()
    activos = [pid for pid in pids if pid not in control["suspendidos"]]
    assert len(activos) == 2 and activos == pids[:2]   # los más antiguos (misma prioridad)
    assert all(control["limites"][pid] == 8 for pid in activos)   # pasan de su cuota de 2
    assert sum(control["limites"].values()) <= CONFIG["marcos_fisicos"]
    revisar_suspendidos()


def test_la_reaccion_respeta_la_prioridad():
    """Con la misma carga, un servicio web (prioridad 0) se queda en memoria aunque llegue último."""
    for i in range(5):
        procesos.crear_proceso(f"analitica_{i}", "admin", ciclo(8, 30),
                               memoria_bytes=8 * PAGINA, cuota_marcos=2, prioridad=2)
    web = procesos.crear_proceso("web", "admin", ciclo(8, 30), memoria_bytes=8 * PAGINA,
                                 cuota_marcos=2, prioridad=0)
    correr_hasta_detectar()
    kernel.ejecutar_ticks(30)
    assert web not in memoria.estado_control_carga()["suspendidos"]


def test_suspender_escribe_al_swap_las_paginas_modificadas_y_no_cuenta_reemplazos():
    pid = procesos.crear_proceso("analitica", "admin", [("CPU", 1)], memoria_bytes=4 * PAGINA, cuota_marcos=4)
    for pagina in range(3):
        memoria.acceder_memoria(pid, pagina * PAGINA, escritura=(pagina < 2))
    antes = memoria.metricas_memoria()
    assert memoria._suspender(pid, procesos) is True
    despues = memoria.metricas_memoria()
    assert despues["escrituras_a_swap"] - antes["escrituras_a_swap"] == 2
    assert despues["reemplazos"] == antes["reemplazos"]
    assert memoria.estado_memoria()["marcos_por_proceso"][pid] == 0
    assert all(not entrada["presente"] for entrada in memoria.tabla_paginas(pid).values())


def test_los_suspendidos_se_reanudan_y_todos_terminan_sin_dejar_memoria():
    for i in range(6):
        procesos.crear_proceso(f"analitica_{i}", "admin", ciclo(8, 10), memoria_bytes=8 * PAGINA, cuota_marcos=2)
    correr_hasta_detectar()
    while not todos_terminados():
        kernel.tick()
        revisar_suspendidos()
        assert kernel.reloj_actual() < 5000
    assert memoria.estado_control_carga()["suspendidos"] == []
    assert memoria.estado_memoria()["marcos_libres"] == CONFIG["marcos_fisicos"]


def test_envejecimiento_ningun_proceso_queda_suspendido_mas_de_300_ticks():
    for i in range(6):
        procesos.crear_proceso(f"analitica_{i}", "admin", ciclo(8, 60), memoria_bytes=8 * PAGINA, cuota_marcos=2)
    correr_hasta_detectar()
    seguidos, peor = {}, 0
    while not todos_terminados():
        kernel.tick()
        suspendidos = memoria.estado_control_carga()["suspendidos"]
        seguidos = {pid: seguidos.get(pid, 0) + 1 for pid in suspendidos}
        peor = max([peor] + list(seguidos.values()))
        assert kernel.reloj_actual() < 10_000
    assert 0 < peor <= memoria._MAX_TICKS_SUSPENDIDO + 1


def test_fijar_reaccion_desconocida_lanza_error():
    with pytest.raises(ErrorMemoria):
        memoria._fijar_reaccion("MAGIA")


def test_sin_reaccion_la_hiperpaginacion_no_baja():
    """Línea base del experimento: sin reaccionar, la tasa sigue en 100 %."""
    memoria._fijar_reaccion("NINGUNA")
    for i in range(6):
        procesos.crear_proceso(f"analitica_{i}", "admin", ciclo(8, 30), memoria_bytes=8 * PAGINA, cuota_marcos=2)
    correr_hasta_detectar()
    tasa_despues, _ = tasa_en_los_siguientes(50)
    assert tasa_despues == 1.0
    assert memoria.estado_control_carga()["suspendidos"] == []


# ------------------------------------------------------- RM2 con el kernel
def test_escenario_hiperpaginacion_tiene_el_formato_y_sobrecarga_la_memoria():
    datos = leer(ESC_HIPERPAGINACION)
    assert set(datos) == {"config", "usuarios", "semaforos", "catalogo", "llegadas"}
    assert set(datos["config"]) == set(CONFIG)
    cuotas = sum(datos["catalogo"][llegada["programa"]]["cuota_marcos"] for llegada in datos["llegadas"])
    assert cuotas > datos["config"]["marcos_fisicos"]


def test_rm2_escenario_de_hiperpaginacion_con_el_kernel():
    kernel.cargar_escenario(ESC_HIPERPAGINACION)
    correr_hasta_detectar()
    tasa_despues, tasa_antes = tasa_en_los_siguientes(50)
    assert tasa_despues < tasa_antes
    assert tasa_despues <= 0.5
    while not todos_terminados():
        kernel.tick()
        revisar_suspendidos()
        assert kernel.reloj_actual() < 5000
    assert memoria.metricas_memoria()["tasa_fallos"] <= 0.25
    assert memoria.estado_memoria()["marcos_libres"] == leer(ESC_HIPERPAGINACION)["config"]["marcos_fisicos"]


def test_rm2_cuota_chica_con_el_kernel():
    """Las cuotas caben, pero cada proceso necesita 8 páginas y solo puede tener 2."""
    for i in range(6):
        procesos.crear_proceso(f"analitica_{i}", "admin", ciclo(8, 30), memoria_bytes=8 * PAGINA, cuota_marcos=2)
    correr_hasta_detectar()
    tasa_despues, tasa_antes = tasa_en_los_siguientes(50)
    assert tasa_despues < tasa_antes
    tasa_despues_2, _ = tasa_en_los_siguientes(50)     # ya cargaron su conjunto de trabajo
    assert tasa_despues_2 == 0.0


def test_rm2_sin_hiperpaginacion_el_escenario_de_memoria_no_cambia():
    """En memoria.json no hay hiperpaginación: nadie se suspende y RM1 sigue en 16,5 %."""
    kernel.cargar_escenario(os.path.join(os.path.dirname(ESC_HIPERPAGINACION), "memoria.json"))
    while not todos_terminados():
        kernel.tick()
        assert memoria.estado_control_carga()["suspendidos"] == []
    assert memoria.estado_control_carga()["reacciones"] == 0
    assert round(memoria.metricas_memoria()["tasa_fallos"], 3) == 0.165
