"""Pruebas completas del Prototipo 1: Núcleo y Planificación (NimbusDC).

Valida los requisitos fundamentales:
- RP1: Tiempo de respuesta promedio de servicios web <= 10 ticks.
- RP2: Anti-inanición por envejecimiento (ningún proceso supera 150 ticks consecutivos en LISTO).
- RP3: Utilización de CPU >= 85% con carga continua.
Y las pruebas unitarias y de integración para `minidc/procesos.py` y `minidc/kernel.py`.
"""
import json
import os
import tempfile
import pytest

from minidc import disco, kernel, procesos
from minidc.errores import ErrorNoExiste, ErrorSistema


@pytest.fixture(autouse=True)
def reiniciar_entorno():
    """Reinicia el estado del kernel y subsistemas antes de cada prueba."""
    kernel.iniciar_sistema({
        "num_cpus": 1,
        "marcos_fisicos": 64,
        "tam_pagina": 256,
        "bloques_disco": 200,
        "tam_bloque": 512,
        "cache_bloques": 8,
    })


# =====================================================================
# Pruebas Unitarias: minidc/procesos.py
# =====================================================================

def test_crear_proceso_normaliza_prioridad_y_convierte_tuplas():
    """Valida normalización de prioridades a [0, 2] y conversión a tuplas inmutables."""
    pid1 = procesos.crear_proceso("test_negativo", "admin", [["CPU", 5], ["ES", 10]], prioridad=-5)
    pid2 = procesos.crear_proceso("test_exceso", "admin", [("CPU", 3)], prioridad=99)
    pid3 = procesos.crear_proceso("test_normal", "admin", [["CPU", 2]], prioridad=1)

    lista = {p["pid"]: p for p in procesos.listar_procesos()}
    assert lista[pid1]["prioridad"] == 0
    assert lista[pid2]["prioridad"] == 2
    assert lista[pid3]["prioridad"] == 1

    proc1_obj = procesos._procesos[pid1]
    assert all(isinstance(inst, tuple) for inst in proc1_obj["programa"])
    assert proc1_obj["programa"] == [("CPU", 5), ("ES", 10)]


def test_estado_proceso_y_error_no_existe():
    """Verifica consulta de estado y lanzamiento de ErrorNoExiste para PIDs inválidos."""
    pid = procesos.crear_proceso("p1", "admin", [("CPU", 1)])
    assert procesos.estado_proceso(pid) == "LISTO"

    with pytest.raises(ErrorNoExiste):
        procesos.estado_proceso(9999)


def test_crear_hilo_exito_y_error():
    """Verifica creación de hilos y validación de existencia del proceso padre."""
    pid = procesos.crear_proceso("padre", "admin", [("CPU", 1)])
    tid1 = procesos.crear_hilo(pid, [["CPU", 2]])
    tid2 = procesos.crear_hilo(pid, [("CPU", 3)])

    assert tid1 == 1
    assert tid2 == 2
    assert len(procesos._procesos[pid]["hilos"]) == 2

    with pytest.raises(ErrorNoExiste):
        procesos.crear_hilo(8888, [("CPU", 1)])


def test_terminar_proceso_libera_recursos():
    """Verifica que terminar_proceso cambie estado, limpie colas y cancele solicitudes de disco."""
    pid = procesos.crear_proceso("a_terminar", "admin", [("ES", 50)])
    disco.encolar_solicitud_disco(pid, 50, "L")
    assert any(s["pid"] == pid for s in disco._cola)

    procesos.terminar_proceso(pid)
    assert procesos.estado_proceso(pid) == "TERMINADO"
    assert pid not in procesos.cola_listos()
    assert not any(s["pid"] == pid for s in disco._cola)

    with pytest.raises(ErrorNoExiste):
        procesos.terminar_proceso(7777)


def test_listar_procesos_claves_obligatorias():
    """Verifica que listar_procesos contenga exactamente las claves exigidas."""
    procesos.crear_proceso("p_claves", "cliente_a", [("CPU", 2)], prioridad=1)
    lista = procesos.listar_procesos()
    assert len(lista) >= 1
    p = lista[0]
    for clave in ("pid", "nombre", "usuario", "estado", "prioridad", "cpu_usada", "tiempo_espera"):
        assert clave in p


def test_cola_listos_orden_prioridad():
    """Verifica que cola_listos ordene los procesos según la jerarquía de prioridad MLFQ (0, 1, 2)."""
    pid_baja = procesos.crear_proceso("baja", "admin", [("CPU", 10)], prioridad=2)
    pid_media = procesos.crear_proceso("media", "admin", [("CPU", 10)], prioridad=1)
    pid_alta = procesos.crear_proceso("alta", "admin", [("CPU", 10)], prioridad=0)

    cola = procesos.cola_listos()
    assert cola.index(pid_alta) < cola.index(pid_media) < cola.index(pid_baja)


def test_politica_planificacion():
    """Verifica que devuelva el nombre de la política implementada."""
    assert "MLFQ" in procesos.politica_planificacion()


def test_metricas_planificacion_sin_procesos():
    """Verifica que las métricas manejen divisiones por cero sin errores."""
    metricas = procesos.metricas_planificacion()
    assert metricas["espera_promedio"] == 0.0
    assert metricas["respuesta_promedio"] == 0.0
    assert metricas["retorno_promedio"] == 0.0
    assert metricas["espera_maxima"] == 0
    assert metricas["utilizacion_cpu"] == 0.0
    assert metricas["procesos_terminados"] == 0


# =====================================================================
# Pruebas Unitarias: minidc/kernel.py
# =====================================================================

def test_kernel_reloj_y_ejecutar_ticks():
    """Verifica el avance discreto del reloj y ejecución consecutiva de ticks."""
    assert kernel.reloj_actual() == 0
    kernel.tick()
    assert kernel.reloj_actual() == 1
    kernel.ejecutar_ticks(5)
    assert kernel.reloj_actual() == 6


def test_kernel_resumen_y_apagar():
    """Verifica las claves obligatorias en resumen_sistema y apagar_sistema."""
    procesos.crear_proceso("proc", "admin", [("CPU", 5)])
    resumen = kernel.resumen_sistema()
    for clave in ("reloj", "procesos_activos", "marcos_libres", "bloques_libres"):
        assert clave in resumen
    assert resumen["procesos_activos"] == 1

    kernel.ejecutar_ticks(5)
    apagado = kernel.apagar_sistema()
    for clave in ("reloj", "utilizacion_cpu", "metricas_planificacion", "metricas_disco", "procesos_activos", "procesos_terminados"):
        assert clave in apagado
    assert apagado["procesos_terminados"] == 1


def test_cargar_escenario_errores():
    """Verifica validación de rutas inexistentes y archivos JSON corruptos."""
    with pytest.raises(ErrorNoExiste):
        kernel.cargar_escenario("ruta_que_no_existe_jamás.json")

    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json") as f:
        f.write("{ json_invalido: no_comillas ")
        nombre_temp = f.name

    try:
        with pytest.raises(ErrorSistema):
            kernel.cargar_escenario(nombre_temp)
    finally:
        os.remove(nombre_temp)


def test_cargar_escenario_valido():
    """Verifica carga de un escenario válido con llegadas inmediatas (tick 0) y futuras."""
    datos = {
        "config": {"num_cpus": 1, "bloques_disco": 200},
        "llegadas": [
            {
                "tick": 0,
                "nombre": "servicio_base",
                "usuario": "admin",
                "programa": [["CPU", 2]],
                "prioridad": 0,
            },
            {
                "tick": 3,
                "nombre": "servicio_futuro",
                "usuario": "cliente_a",
                "programa": [["CPU", 1]],
                "prioridad": 1,
            },
        ],
    }

    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json") as f:
        json.dump(datos, f)
        nombre_temp = f.name

    try:
        kernel.cargar_escenario(nombre_temp)
        assert len(procesos.listar_procesos()) == 1
        assert procesos.listar_procesos()[0]["nombre"] == "servicio_base"

        kernel.ejecutar_ticks(2)
        assert len(procesos.listar_procesos()) == 1

        kernel.tick()  # Tick 3: llega servicio_futuro
        assert len(procesos.listar_procesos()) == 2
        nombres = [p["nombre"] for p in procesos.listar_procesos()]
        assert "servicio_futuro" in nombres
    finally:
        os.remove(nombre_temp)


# =====================================================================
# Pruebas de Integración y Ciclo de 4 Pasos del Kernel
# =====================================================================

def test_contrato_disco_kernel_integrado():
    """Ejecuta el ciclo de 4 pasos real del kernel con [('CPU', 2), ('ES', 40), ('CPU', 1)].
    Verifica que el proceso se bloquee exactamente 5 ticks (1 + 40 // 10) y termine en tick 8.
    """
    pid = procesos.crear_proceso("proc_es", "admin", [("CPU", 2), ("ES", 40), ("CPU", 1)])

    # Tick 1: corre CPU (restante 1)
    kernel.tick()
    assert kernel.reloj_actual() == 1
    assert procesos.estado_proceso(pid) == "EJECUTANDO"

    # Tick 2: corre CPU (restante 0 -> completa ráfaga, cede CPU)
    kernel.tick()
    assert kernel.reloj_actual() == 2
    assert procesos.estado_proceso(pid) == "LISTO"

    # Tick 3: ejecuta ES bloque 40 -> pasa a BLOQUEADO
    kernel.tick()
    assert kernel.reloj_actual() == 3
    assert procesos.estado_proceso(pid) == "BLOQUEADO"

    # Ticks 4 a 7: permanece BLOQUEADO en disco
    for _ in range(4):
        kernel.tick()
        assert procesos.estado_proceso(pid) == "BLOQUEADO"
    assert kernel.reloj_actual() == 7

    # Tick 8: Paso 2 despierta al proceso -> Paso 3 ejecuta último CPU 1 -> TERMINADO
    kernel.tick()
    assert kernel.reloj_actual() == 8
    assert procesos.estado_proceso(pid) == "TERMINADO"
    assert disco.metricas_disco()["solicitudes_atendidas"] == 1


# =====================================================================
# Requisitos Principales: RP1, RP2, RP3
# =====================================================================

def test_rp1_tiempo_respuesta_promedio_web_menor_o_igual_a_10():
    """Valida RP1: El tiempo de respuesta promedio de servicios web (primer_inicio - llegada) es <= 10 ticks.
    Incluso con procesos analíticos de fondo en ejecución, la preempción y colas de prioridad 0
    garantizan respuesta inmediata para cargas web.
    """
    # Proceso de fondo largo (prioridad 2)
    procesos.crear_proceso("analitica_pesada", "admin", [("CPU", 50)], prioridad=2)

    # El proceso de fondo comienza a ejecutarse
    kernel.ejecutar_ticks(5)

    # Llegan solicitudes de servicios web (prioridad 0)
    pids_web = []
    pids_web.append(procesos.crear_proceso("web_1", "cliente_a", [("CPU", 2)], prioridad=0))
    kernel.tick()  # web_1 debe ser atendido de inmediato por preempción
    pids_web.append(procesos.crear_proceso("web_2", "cliente_b", [("CPU", 2)], prioridad=0))
    kernel.tick()
    pids_web.append(procesos.crear_proceso("web_3", "cliente_a", [("CPU", 1)], prioridad=0))

    # Ejecutar hasta que las solicitudes web terminen
    kernel.ejecutar_ticks(10)

    lista = {p["pid"]: p for p in procesos.listar_procesos()}
    tiempos_respuesta_web = [
        lista[pid]["primer_inicio"] - lista[pid]["tick_llegada"]
        for pid in pids_web
    ]
    promedio_web = sum(tiempos_respuesta_web) / len(tiempos_respuesta_web)

    print(f"\nTiempos de respuesta web: {tiempos_respuesta_web}, Promedio: {promedio_web}")
    assert promedio_web <= 10, f"RP1 violado: respuesta promedio web fue {promedio_web} > 10"


def test_rp2_anti_inanicion_envejecimiento():
    """Valida RP2: Ningún proceso supera 150 ticks consecutivos en LISTO.
    Con carga continua de alta prioridad, el mecanismo de aging (promoción a los 30 ticks)
    evita que un proceso de prioridad baja muera de inanición.
    """
    # Proceso de baja prioridad (prioridad 2)
    pid_baja = procesos.crear_proceso("proceso_baja", "cliente_a", [("CPU", 5)], prioridad=2)

    max_espera_consecutiva = 0

    # Inyectar continuamente procesos de alta prioridad (prioridad 0) durante 160 ticks
    for tick_num in range(160):
        if tick_num % 2 == 0:
            procesos.crear_proceso(f"alta_{tick_num}", "admin", [("CPU", 2)], prioridad=0)
        kernel.tick()

        proc = procesos._procesos[pid_baja]
        if proc["estado"] == "LISTO":
            if proc["espera_consecutiva"] > max_espera_consecutiva:
                max_espera_consecutiva = proc["espera_consecutiva"]

        # En ningún momento la espera consecutiva en LISTO debe ser >= 150
        assert proc["espera_consecutiva"] < 150, (
            f"RP2 violado: Proceso {pid_baja} alcanzó {proc['espera_consecutiva']} ticks consecutivos en LISTO"
        )

    proc_final = procesos._procesos[pid_baja]
    # Comprobar que gracias a la promoción por aging, el proceso recibió CPU
    assert proc_final["primer_inicio"] is not None
    assert max_espera_consecutiva < 150
    print(f"\nMáxima espera consecutiva observada: {max_espera_consecutiva} ticks (garantizado < 150)")


def test_rp3_utilizacion_cpu_mayor_o_igual_85_por_ciento():
    """Valida RP3: Utilización de CPU >= 85% (0.85) con carga continua."""
    # Carga continua de CPU con ráfagas consecutivas
    procesos.crear_proceso("carga_continua_1", "cliente_a", [("CPU", 40)], prioridad=1)
    procesos.crear_proceso("carga_continua_2", "cliente_b", [("CPU", 40)], prioridad=1)

    kernel.ejecutar_ticks(60)

    metricas = procesos.metricas_planificacion()
    utilizacion = metricas["utilizacion_cpu"]
    print(f"\nUtilización de CPU alcanzada: {utilizacion * 100:.2f}%")

    assert utilizacion >= 0.85, f"RP3 violado: utilización de CPU fue {utilizacion:.4f} < 0.85"


def test_multiprocesador_dos_cpus():
    """Verifica que el planificador soporte num_cpus > 1 ejecutando 2 procesos en paralelo."""
    kernel.iniciar_sistema({"num_cpus": 2, "bloques_disco": 200})

    pid1 = procesos.crear_proceso("p_cpu0", "admin", [("CPU", 10)], prioridad=0)
    pid2 = procesos.crear_proceso("p_cpu1", "admin", [("CPU", 10)], prioridad=0)

    kernel.tick()

    assert procesos.proceso_en_ejecucion(0) in (pid1, pid2)
    assert procesos.proceso_en_ejecucion(1) in (pid1, pid2)
    assert procesos.proceso_en_ejecucion(0) != procesos.proceso_en_ejecucion(1)
