"""Pruebas del Prototipo 2: Núcleo y Planificación (NimbusDC).

Valida los requisitos de los Hitos 1, 2, 3 y 4 del Prototipo 2:
- Hito 1: Gestión y despacho de hilos simulados (`crear_hilo`), TIDs únicos e incrementales,
  aislamiento de contadores `pc`, listas inmutables de instrucciones y compartición de recursos
  (memoria, marcos y usuario).
- Hito 2: Integración de la instrucción ("MEM", dir, [escritura]), llamada a `memoria.acceder_memoria`,
  y bloqueo determinista de exactamente 5 ticks ante fallo de página antes de volver a LISTO.
- Hito 3: Cumplimiento de RM3: captura robusta de `ErrorMemoria` ante accesos fuera de rango,
  terminación limpia del proceso infractor (`terminar_proceso`), liberación de recursos y
  continuidad normal del núcleo y de los demás procesos.
- Hito 4: Integración completa de hilos, memoria, disco y métricas del sistema.
"""
from unittest.mock import patch
import pytest

from minidc import disco, kernel, procesos
from minidc.errores import ErrorMemoria, ErrorNoExiste, ErrorSistema


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
# HITO 1: GESTIÓN Y DESPACHO DE HILOS SIMULADOS
# =====================================================================

def test_crear_hilo_tids_incrementales_por_proceso():
    """Verifica que cada proceso gestione sus propios TIDs incrementales independientes."""
    pid1 = procesos.crear_proceso("p1", "admin", [])
    pid2 = procesos.crear_proceso("p2", "cliente_a", [])

    # Hilos de p1
    tid1_1 = procesos.crear_hilo(pid1, [("CPU", 1)])
    tid1_2 = procesos.crear_hilo(pid1, [("CPU", 2)])
    tid1_3 = procesos.crear_hilo(pid1, [("CPU", 3)])

    # Hilos de p2
    tid2_1 = procesos.crear_hilo(pid2, [("CPU", 5)])
    tid2_2 = procesos.crear_hilo(pid2, [("CPU", 6)])

    assert (tid1_1, tid1_2, tid1_3) == (1, 2, 3)
    assert (tid2_1, tid2_2) == (1, 2)
    assert len(procesos._procesos[pid1]["hilos"]) == 3
    assert len(procesos._procesos[pid2]["hilos"]) == 2


def test_crear_hilo_valida_pid_existente():
    """Verifica que crear_hilo lance ErrorNoExiste cuando el PID padre no existe."""
    with pytest.raises(ErrorNoExiste):
        procesos.crear_hilo(99999, [("CPU", 1)])


def test_crear_hilo_inmutabilidad_instrucciones_y_recursos_compartidos():
    """Verifica que las instrucciones sean tuplas inmutables y compartan recursos del padre."""
    pid = procesos.crear_proceso(
        "padre_recursos",
        "cliente_b",
        [],
        memoria_bytes=2048,
        cuota_marcos=8,
        prioridad=1,
    )
    tid = procesos.crear_hilo(pid, [["CPU", 2], ["MEM", 128, True]])
    hilo = procesos._procesos[pid]["hilos"][0]

    assert hilo["tid"] == tid
    assert hilo["pid"] == pid
    assert hilo["pc"] == 0
    assert hilo["estado"] == "LISTO"
    assert all(isinstance(inst, tuple) for inst in hilo["programa"])
    assert hilo["programa"] == [("CPU", 2), ("MEM", 128, True)]

    # Recursos compartidos del proceso padre
    proceso = procesos._procesos[pid]
    assert proceso["memoria_bytes"] == 2048
    assert proceso["cuota_marcos"] == 8
    assert proceso["usuario"] == "cliente_b"


def test_despacho_hilos_avance_independiente_pc():
    """Verifica el despacho alternado (Round-Robin) y avance independiente de PC en hilos."""
    pid = procesos.crear_proceso("p_hilos", "admin", [])
    tid1 = procesos.crear_hilo(pid, [("CPU", 1), ("CPU", 1)])
    tid2 = procesos.crear_hilo(pid, [("CPU", 1), ("CPU", 1)])

    hilos = procesos._procesos[pid]["hilos"]
    hilo1 = hilos[0]
    hilo2 = hilos[1]

    # Tick 1: Debe despachar hilo 1 (primer tick de CPU 1)
    kernel.tick()
    assert hilo1["pc"] == 1
    assert hilo2["pc"] == 0
    assert procesos.estado_proceso(pid) == "LISTO"

    # Tick 2: Debe despachar hilo 2 (primer tick de CPU 1)
    kernel.tick()
    assert hilo1["pc"] == 1
    assert hilo2["pc"] == 1
    assert procesos.estado_proceso(pid) == "LISTO"

    # Tick 3: Debe despachar hilo 1 (segundo tick -> completa su programa)
    kernel.tick()
    assert hilo1["pc"] == 2
    assert hilo1["estado"] == "TERMINADO"
    assert hilo2["pc"] == 1
    assert procesos.estado_proceso(pid) == "LISTO"

    # Tick 4: Debe despachar hilo 2 (segundo tick -> completa su programa)
    kernel.tick()
    assert hilo2["pc"] == 2
    assert hilo2["estado"] == "TERMINADO"

    # Con ambos hilos terminados, el proceso padre debe quedar TERMINADO
    assert procesos.estado_proceso(pid) == "TERMINADO"


def test_proceso_termina_solo_cuando_todos_los_hilos_terminan():
    """Verifica que un proceso permanezca activo mientras al menos un hilo siga en ejecución."""
    pid = procesos.crear_proceso("p_parcial", "admin", [])
    procesos.crear_hilo(pid, [("CPU", 1)])  # Termina en 1 tick de ejecución
    procesos.crear_hilo(pid, [("CPU", 4)])  # Termina tras 4 ticks de ejecución

    # Ejecutar 2 ticks (1 tick para hilo 1 que termina, y 1 tick para hilo 2)
    kernel.ejecutar_ticks(2)
    hilos = procesos._procesos[pid]["hilos"]
    assert hilos[0]["estado"] == "TERMINADO"
    assert hilos[1]["estado"] in ("LISTO", "EJECUTANDO")
    assert procesos.estado_proceso(pid) != "TERMINADO"

    # Ejecutar los ticks restantes
    kernel.ejecutar_ticks(3)
    assert hilos[1]["estado"] == "TERMINADO"
    assert procesos.estado_proceso(pid) == "TERMINADO"


# =====================================================================
# HITO 2: INSTRUCCIÓN MEM Y FALLO DE PÁGINA (5 TICKS EXACTOS)
# =====================================================================

def test_memoria_acceso_exitoso_sin_fallo():
    """Verifica que un acceso a memoria sin fallo de página no bloquee el proceso y avance PC."""
    pid = procesos.crear_proceso("p_mem_hit", "admin", [("MEM", 50), ("CPU", 1)])

    with patch("minidc.memoria.acceder_memoria") as mock_acceder:
        mock_acceder.return_value = {"marco": 3, "fallo_pagina": False, "pagina_reemplazada": None}

        # Tick 1: Ejecuta ("MEM", 50)
        kernel.tick()
        mock_acceder.assert_called_once_with(pid, 50, False)
        assert procesos._procesos[pid]["pc"] == 1
        assert procesos.estado_proceso(pid) == "LISTO"

        # Tick 2: Ejecuta ("CPU", 1) y termina
        kernel.tick()
        assert procesos._procesos[pid]["pc"] == 2
        assert procesos.estado_proceso(pid) == "TERMINADO"


def test_memoria_escritura_pasa_parametro_escritura():
    """Verifica que ("MEM", dir, True) envíe escritura=True a acceder_memoria."""
    pid = procesos.crear_proceso("p_write", "admin", [("MEM", 120, True)])

    with patch("minidc.memoria.acceder_memoria") as mock_acceder:
        mock_acceder.return_value = {"marco": 5, "fallo_pagina": False, "pagina_reemplazada": None}
        kernel.tick()
        mock_acceder.assert_called_once_with(pid, 120, True)


def test_fallo_pagina_bloqueo_determinista_exacto_5_ticks():
    """Verifica el bloqueo exacto de 5 ticks discretos ante un fallo de página."""
    # Programa: ("MEM", 200) genera fallo, seguido de ("CPU", 1)
    pid = procesos.crear_proceso("p_fault", "admin", [("MEM", 200), ("CPU", 1)])

    with patch("minidc.memoria.acceder_memoria") as mock_acceder:
        mock_acceder.return_value = {"marco": 1, "fallo_pagina": True, "pagina_reemplazada": None}

        # Tick 1: Se ejecuta ("MEM", 200) y ocurre el fallo de página
        kernel.tick()
        assert procesos.estado_proceso(pid) == "BLOQUEADO"
        assert procesos._procesos[pid]["espera_fallo_memoria"] == 5
        assert procesos._procesos[pid]["tiempo_bloqueado"] == 1

        # Ticks 2, 3, 4, 5: El proceso DEBE permanecer estrictamente BLOQUEADO
        for tick_idx in range(2, 6):
            kernel.tick()
            assert procesos.estado_proceso(pid) == "BLOQUEADO", f"Debe seguir BLOQUEADO en tick {tick_idx}"
            assert procesos._procesos[pid]["tiempo_bloqueado"] == tick_idx

        # En este punto completó exactamente 5 ticks en estado BLOQUEADO
        assert procesos._procesos[pid]["tiempo_bloqueado"] == 5

        # Tick 6: En Paso 2 se cumplen los 5 ticks, transiciona a LISTO y en Paso 3 ejecuta CPU 1
        kernel.tick()
        # Habiendo ejecutado CPU 1, el programa terminó
        assert procesos.estado_proceso(pid) == "TERMINADO"
        # El tiempo total bloqueado no aumentó más allá de 5
        assert procesos._procesos[pid]["tiempo_bloqueado"] == 5


def test_hilo_con_fallo_pagina_no_bloquea_otros_hilos_del_mismo_proceso():
    """Verifica que un fallo de página en un hilo no bloquee la ejecución de otros hilos listos."""
    pid = procesos.crear_proceso("p_multi_fallo", "admin", [])
    tid1 = procesos.crear_hilo(pid, [("MEM", 300), ("CPU", 1)])
    tid2 = procesos.crear_hilo(pid, [("CPU", 1), ("CPU", 1)])

    with patch("minidc.memoria.acceder_memoria") as mock_acceder:
        # Hilo 1 causa fallo de página en MEM
        mock_acceder.return_value = {"marco": 2, "fallo_pagina": True, "pagina_reemplazada": None}

        # Tick 1: Hilo 1 ejecuta MEM y queda BLOQUEADO por 5 ticks
        kernel.tick()
        hilos = procesos._procesos[pid]["hilos"]
        assert hilos[0]["estado"] == "BLOQUEADO"
        assert hilos[1]["estado"] == "LISTO"
        # El proceso como un todo sigue LISTO porque tiene al hilo 2 listo
        assert procesos.estado_proceso(pid) == "LISTO"

        # Tick 2: Hilo 2 ejecuta ("CPU", 1) exitosamente mientras Hilo 1 sigue bloqueado
        kernel.tick()
        assert hilos[0]["estado"] == "BLOQUEADO"
        assert hilos[1]["pc"] == 1
        assert procesos.estado_proceso(pid) == "LISTO"

        # Tick 3: Hilo 2 ejecuta su segunda instrucción ("CPU", 1) y termina
        kernel.tick()
        assert hilos[1]["estado"] == "TERMINADO"
        # Hilo 1 sigue bloqueado, ahora que Hilo 2 terminó, el proceso pasa a BLOQUEADO
        assert hilos[0]["estado"] == "BLOQUEADO"
        assert procesos.estado_proceso(pid) == "BLOQUEADO"

        # Ticks 4 y 5: Hilo 1 sigue bloqueado esperando completar sus 5 ticks
        kernel.tick()
        kernel.tick()
        assert hilos[0]["estado"] == "BLOQUEADO"

        # Tick 6: Hilo 1 despierta y ejecuta ("CPU", 1), terminando todo el proceso
        kernel.tick()
        assert hilos[0]["estado"] == "TERMINADO"
        assert procesos.estado_proceso(pid) == "TERMINADO"


# =====================================================================
# HITO 3: MANEJO ROBUSTO DE RM3 (PROTECCIÓN DE MEMORIA)
# =====================================================================

def test_rm3_direccion_fuera_de_espacio_termina_proceso_y_libera_recursos():
    """Verifica que un acceso fuera de memoria lance ErrorMemoria y termine solo al infractor."""
    # Proceso con memoria_bytes = 1024; dirección 2048 está fuera del rango [0, 1023]
    pid = procesos.crear_proceso("infractor", "cliente_a", [("MEM", 2048)], memoria_bytes=1024)

    with patch("minidc.memoria.liberar_memoria") as mock_liberar:
        kernel.tick()
        assert procesos.estado_proceso(pid) == "TERMINADO"
        mock_liberar.assert_called_once_with(pid)
        assert pid not in procesos.cola_listos()


def test_rm3_proceso_infractor_no_afecta_a_otros_procesos():
    """Verifica que el error de memoria no detenga el kernel ni perjudique a procesos normales."""
    pid_bueno1 = procesos.crear_proceso("bueno1", "admin", [("CPU", 2)], prioridad=0)
    pid_malo = procesos.crear_proceso("malo", "cliente_b", [("MEM", 9999)], memoria_bytes=512, prioridad=0)
    pid_bueno2 = procesos.crear_proceso("bueno2", "admin", [("CPU", 2)], prioridad=0)

    # Ejecutar suficientes ticks para que todos se procesen
    kernel.ejecutar_ticks(10)

    # El infractor fue terminado por violar RM3
    assert procesos.estado_proceso(pid_malo) == "TERMINADO"

    # Los procesos normales completaron su ejecución íntegramente
    assert procesos.estado_proceso(pid_bueno1) == "TERMINADO"
    assert procesos.estado_proceso(pid_bueno2) == "TERMINADO"
    assert procesos._procesos[pid_bueno1]["pc"] == 1
    assert procesos._procesos[pid_bueno2]["pc"] == 1

    # El reloj del kernel avanzó con normalidad
    assert kernel.reloj_actual() == 10


def test_rm3_con_excepcion_directa_desde_modulo_memoria():
    """Verifica captura robusta cuando memoria.acceder_memoria lanza ErrorMemoria explícitamente."""
    pid_culpable = procesos.crear_proceso("culpable", "cliente_a", [("MEM", 500)], memoria_bytes=1024)
    pid_inocente = procesos.crear_proceso("inocente", "cliente_a", [("CPU", 3)], memoria_bytes=1024)

    with patch("minidc.memoria.acceder_memoria") as mock_acceder:
        mock_acceder.side_effect = ErrorMemoria("Acceso ilegal simulado")

        kernel.tick()  # Intenta acceder memoria y captura ErrorMemoria
        assert procesos.estado_proceso(pid_culpable) == "TERMINADO"

    # Siguientes ticks ejecutan al proceso inocente sin fallos
    kernel.ejecutar_ticks(4)
    assert procesos.estado_proceso(pid_inocente) == "TERMINADO"


def test_rm3_infraccion_dentro_de_un_hilo():
    """Verifica que una violación RM3 dentro de un hilo termine limpiamente a todo el proceso."""
    pid = procesos.crear_proceso("padre_con_hilo_rebelde", "cliente_a", [], memoria_bytes=1024)
    tid_bueno = procesos.crear_hilo(pid, [("CPU", 5)])
    tid_malo = procesos.crear_hilo(pid, [("MEM", 5000)])  # Ilegal: 5000 >= 1024

    with patch("minidc.memoria.liberar_memoria") as mock_liberar:
        kernel.ejecutar_ticks(5)

        # Tanto el proceso como todos sus hilos deben quedar TERMINADOS
        assert procesos.estado_proceso(pid) == "TERMINADO"
        for h in procesos._procesos[pid]["hilos"]:
            assert h["estado"] == "TERMINADO"
        mock_liberar.assert_called_with(pid)


# =====================================================================
# HITO 4: INTEGRACIÓN COMPLETA (HILOS, MEMORIA, DISCO Y MÉTRICAS)
# =====================================================================

def test_integracion_hilos_con_disco_y_memoria():
    """Verifica ejecución concurrente de hilos realizando E/S a disco y accesos a memoria."""
    pid = procesos.crear_proceso("integrado", "admin", [])
    # Hilo 1: Lee disco (bloque 10 tarda 2 ticks en atenderse)
    tid1 = procesos.crear_hilo(pid, [("ES", 10), ("CPU", 1)])
    # Hilo 2: Hace acceso a memoria hit (1 tick) y CPU (1 tick)
    tid2 = procesos.crear_hilo(pid, [("MEM", 100), ("CPU", 1)])

    with patch("minidc.memoria.acceder_memoria") as mock_mem:
        mock_mem.return_value = {"marco": 0, "fallo_pagina": False, "pagina_reemplazada": None}

        # Ejecutar suficientes ticks para que ambos hilos completen sus operaciones
        kernel.ejecutar_ticks(10)

        assert procesos.estado_proceso(pid) == "TERMINADO"
        hilos = procesos._procesos[pid]["hilos"]
        assert all(h["estado"] == "TERMINADO" for h in hilos)
        assert hilos[0]["pc"] == 2
        assert hilos[1]["pc"] == 2


def test_metricas_globales_con_hilos_y_memoria():
    """Verifica que las métricas de planificación y apagar_sistema reflejen hilos y fallos."""
    pid1 = procesos.crear_proceso("p_metricas1", "admin", [("CPU", 2)])
    pid2 = procesos.crear_proceso("p_metricas2", "admin", [("MEM", 100)])

    with patch("minidc.memoria.acceder_memoria") as mock_mem:
        mock_mem.return_value = {"marco": 1, "fallo_pagina": False, "pagina_reemplazada": None}
        kernel.ejecutar_ticks(5)

    metricas = procesos.metricas_planificacion()
    assert metricas["procesos_terminados"] == 2
    assert metricas["utilizacion_cpu"] > 0.0

    resumen = kernel.apagar_sistema()
    assert resumen["procesos_activos"] == 0
    assert resumen["procesos_terminados"] == 2
    assert resumen["reloj"] == 5


def test_rm3_direccion_negativa():
    """Verifica que direcciones negativas sean rechazadas bajo RM3 con ErrorMemoria."""
    pid = procesos.crear_proceso("p_negativo", "cliente_a", [("MEM", -10)], memoria_bytes=1024)
    kernel.tick()
    assert procesos.estado_proceso(pid) == "TERMINADO"


def test_varios_procesos_con_fallos_de_pagina_simultaneos():
    """Verifica que dos procesos con fallo de página mantengan conteos independientes de 5 ticks."""
    pid1 = procesos.crear_proceso("p1", "admin", [("MEM", 100), ("CPU", 1)], prioridad=0)
    pid2 = procesos.crear_proceso("p2", "admin", [("MEM", 200), ("CPU", 1)], prioridad=0)

    with patch("minidc.memoria.acceder_memoria") as mock_mem:
        mock_mem.return_value = {"marco": 1, "fallo_pagina": True, "pagina_reemplazada": None}

        # Tick 1: P1 ejecuta MEM y falla
        kernel.tick()
        assert procesos.estado_proceso(pid1) == "BLOQUEADO"
        assert procesos.estado_proceso(pid2) == "LISTO"

        # Tick 2: P2 ejecuta MEM y falla
        kernel.tick()
        assert procesos.estado_proceso(pid1) == "BLOQUEADO"
        assert procesos.estado_proceso(pid2) == "BLOQUEADO"

        # P1 falló en tick 1 -> debe despertar en tick 6 (5 ticks bloqueado)
        # P2 falló en tick 2 -> debe despertar en tick 7 (5 ticks bloqueado)
        kernel.tick()  # Tick 3
        kernel.tick()  # Tick 4
        kernel.tick()  # Tick 5
        assert procesos.estado_proceso(pid1) == "BLOQUEADO"
        assert procesos.estado_proceso(pid2) == "BLOQUEADO"

        # Tick 6: P1 despierta en Paso 2 y ejecuta ("CPU", 1) en Paso 3
        kernel.tick()
        assert procesos.estado_proceso(pid1) == "TERMINADO"
        assert procesos.estado_proceso(pid2) == "BLOQUEADO"

        # Tick 7: P2 despierta en Paso 2 y ejecuta ("CPU", 1) en Paso 3
        kernel.tick()
        assert procesos.estado_proceso(pid2) == "TERMINADO"


def test_terminar_proceso_con_hilos_activos_cancela_todo():
    """Verifica que terminar_proceso manual termine todos los hilos y limpie la cola."""
    pid = procesos.crear_proceso("padre_cancelar", "admin", [])
    tid1 = procesos.crear_hilo(pid, [("CPU", 10)])
    tid2 = procesos.crear_hilo(pid, [("ES", 50)])

    kernel.tick()  # Inicia ejecución
    procesos.terminar_proceso(pid)

    assert procesos.estado_proceso(pid) == "TERMINADO"
    assert pid not in procesos.cola_listos()
    hilos = procesos._procesos[pid]["hilos"]
    assert all(h["estado"] == "TERMINADO" for h in hilos)


def test_multiprocesador_con_hilos():
    """Verifica que en sistema multi-CPU dos procesos con hilos se atiendan en paralelo."""
    kernel.iniciar_sistema({"num_cpus": 2, "bloques_disco": 200})

    pid1 = procesos.crear_proceso("p1_multi", "admin", [], prioridad=0)
    procesos.crear_hilo(pid1, [("CPU", 5)])
    pid2 = procesos.crear_proceso("p2_multi", "admin", [], prioridad=0)
    procesos.crear_hilo(pid2, [("CPU", 5)])

    kernel.tick()

    en_cpu0 = procesos.proceso_en_ejecucion(0)
    en_cpu1 = procesos.proceso_en_ejecucion(1)
    assert {en_cpu0, en_cpu1} == {pid1, pid2}

