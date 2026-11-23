"""Pruebas completas del Prototipo 3: Núcleo y Sincronización (NimbusDC).

Valida los requisitos fundamentales del Prototipo 3 para el Núcleo:
- RS1 / RS2: Sincronización mediante semáforos, primitivas WAIT y SIGNAL, exclusión mutua,
  coordinación de hilos concurrentes, prevención de interbloqueos huérfanos y métricas.
- Cobertura exhaustiva de las 15 pruebas obligatorias del Paso 2.
"""
from unittest.mock import patch
import pytest

from minidc import disco, kernel, procesos
from minidc.errores import ErrorMemoria, ErrorNoExiste, ErrorSincronizacion, ErrorSistema


# =====================================================================
# SIMULADOR / TEST DOUBLE DE SINCRONIZACIÓN PARA PRUEBAS AISLADAS
# =====================================================================

class SemSimulado:
    """Estructura interna simulada para semáforos en las pruebas del Núcleo."""

    def __init__(self, nombre: str, valor: int):
        self.nombre = nombre
        self.valor = int(valor)
        self.cola_espera = []
        self.reservados = set()


class GestorSincronizacionTest:
    """Simulador determinista de sincronización para pruebas unitarias de kernel y procesos."""

    def __init__(self):
        self.semaforos: dict[str, SemSimulado] = {}
        self.mutexes: dict[str, int | None] = {}

    def crear_semaforo(self, nombre: str, valor_inicial: int) -> None:
        self.semaforos[nombre] = SemSimulado(nombre, valor_inicial)

    def semaforo_wait(self, nombre: str, pid: int) -> bool:
        if nombre not in self.semaforos:
            raise ErrorSincronizacion(f"Semáforo '{nombre}' no existe")
        sem = self.semaforos[nombre]
        if pid in sem.reservados:
            sem.reservados.remove(pid)
            return True
        elif sem.valor > 0:
            sem.valor -= 1
            return True
        else:
            if pid not in sem.cola_espera:
                sem.cola_espera.append(pid)
            return False

    def semaforo_signal(self, nombre: str, pid: int) -> int | None:
        if nombre not in self.semaforos:
            raise ErrorSincronizacion(f"Semáforo '{nombre}' no existe")
        sem = self.semaforos[nombre]
        if sem.cola_espera:
            despertado = sem.cola_espera.pop(0)
            sem.reservados.add(despertado)
            return despertado
        else:
            sem.valor += 1
            return None

    def estado_semaforo(self, nombre: str) -> dict:
        if nombre not in self.semaforos:
            raise ErrorSincronizacion(f"Semáforo '{nombre}' no existe")
        sem = self.semaforos[nombre]
        return {"valor": sem.valor, "cola_espera": list(sem.cola_espera)}

    def reiniciar(self, config: dict | None = None) -> None:
        self.semaforos.clear()
        self.mutexes.clear()


@pytest.fixture(autouse=True)
def entorno_prototipo3():
    """Reinicia el kernel y subsistemas parcheando sincronizacion con un simulador determinista."""
    gestor = GestorSincronizacionTest()
    with patch("minidc.sincronizacion.crear_semaforo", side_effect=gestor.crear_semaforo), \
         patch("minidc.sincronizacion.semaforo_wait", side_effect=gestor.semaforo_wait), \
         patch("minidc.sincronizacion.semaforo_signal", side_effect=gestor.semaforo_signal), \
         patch("minidc.sincronizacion.estado_semaforo", side_effect=gestor.estado_semaforo), \
         patch("minidc.sincronizacion.reiniciar", side_effect=gestor.reiniciar, create=True), \
         patch("minidc.sincronizacion._semaforos", gestor.semaforos, create=True):
        kernel.iniciar_sistema({
            "num_cpus": 1,
            "marcos_fisicos": 64,
            "tam_pagina": 256,
            "bloques_disco": 200,
            "tam_bloque": 512,
            "cache_bloques": 8,
        })
        yield gestor


# =====================================================================
# SUITE DE PRUEBAS DEL PROTOTIPO 3 (REQUISITOS OBLIGATORIOS 1 AL 15)
# =====================================================================

def test_adquisicion_inmediata_semaforo_disponible(entorno_prototipo3):
    """1. Adquisición inmediata de semáforo con valor inicial >= 1 (pc avanza, estado LISTO)."""
    entorno_prototipo3.crear_semaforo("sem_disponible", 1)
    pid = procesos.crear_proceso("p_adquiere", "admin", [("WAIT", "sem_disponible"), ("CPU", 2)])

    # Tick 1: Ejecuta ("WAIT", "sem_disponible")
    kernel.tick()

    assert procesos._procesos[pid]["pc"] == 1
    assert procesos.estado_proceso(pid) in ("LISTO", "EJECUTANDO")
    assert "sem_disponible" in procesos._procesos[pid]["semaforos_adquiridos"]
    assert procesos._procesos[pid]["cpu_usada"] == 1
    assert entorno_prototipo3.semaforos["sem_disponible"].valor == 0


def test_bloqueo_determinista_wait_semaforo_en_cero(entorno_prototipo3):
    """2. Bloqueo determinista ante WAIT sobre semáforo en 0 (pasa a BLOQUEADO, pc NO avanza, CPU libre)."""
    entorno_prototipo3.crear_semaforo("sem_cero", 0)
    pid = procesos.crear_proceso("p_bloqueado", "admin", [("WAIT", "sem_cero"), ("CPU", 2)])

    # Tick 1: Se ejecuta WAIT y debe bloquearse de inmediato
    kernel.tick()

    assert procesos.estado_proceso(pid) == "BLOQUEADO"
    assert procesos._procesos[pid]["pc"] == 0
    assert procesos.proceso_en_ejecucion(0) is None
    assert procesos._procesos[pid]["tiempo_bloqueado"] == 1

    # Ticks 2 y 3: Debe continuar estrictamente BLOQUEADO acumulando tiempo de bloqueo
    kernel.tick()
    assert procesos.estado_proceso(pid) == "BLOQUEADO"
    assert procesos._procesos[pid]["tiempo_bloqueado"] == 2

    kernel.tick()
    assert procesos.estado_proceso(pid) == "BLOQUEADO"
    assert procesos._procesos[pid]["tiempo_bloqueado"] == 3


def test_despertar_inmediato_reincorporacion_mlfq_tras_signal(entorno_prototipo3):
    """3. Despertar inmediato y reincorporación a LISTO en la cola MLFQ tras ejecutarse SIGNAL por otro proceso."""
    entorno_prototipo3.crear_semaforo("sem_espera", 0)
    pid1 = procesos.crear_proceso("p1_wait", "admin", [("WAIT", "sem_espera"), ("CPU", 1)], prioridad=1)

    # Tick 1: p1 intenta WAIT y queda BLOQUEADO
    kernel.tick()
    assert procesos.estado_proceso(pid1) == "BLOQUEADO"

    # p2 emite SIGNAL sobre sem_espera
    pid2 = procesos.crear_proceso("p2_signal", "admin", [("SIGNAL", "sem_espera")], prioridad=0)

    # Tick 2: p2 corre, emite SIGNAL y termina
    kernel.tick()
    assert procesos.estado_proceso(pid2) == "TERMINADO"
    assert procesos.estado_proceso(pid1) == "LISTO"
    assert pid1 in procesos.cola_listos()

    # Tick 3: p1 es despachado, consume la reserva del semáforo y avanza pc
    kernel.tick()
    assert procesos._procesos[pid1]["pc"] == 1
    assert "sem_espera" in procesos._procesos[pid1]["semaforos_adquiridos"]


def test_exclusion_mutua_estricta_recurso_compartido(entorno_prototipo3):
    """4. Exclusión mutua estricta con recurso compartido ('WAIT', 'bd'):

    Proceso 1 entra en sección crítica, Proceso 2 se bloquea en WAIT y solo puede entrar
    después de que Proceso 1 ejecuta ('SIGNAL', 'bd').
    """
    entorno_prototipo3.crear_semaforo("bd", 1)

    # p1 adquiere 'bd' y ejecuta 2 ticks de CPU en sección crítica
    pid1 = procesos.crear_proceso("p1_critico", "admin", [("WAIT", "bd"), ("CPU", 2), ("SIGNAL", "bd")], prioridad=1)

    # Tick 1: p1 adquiere 'bd'
    kernel.tick()
    assert procesos._procesos[pid1]["pc"] == 1
    assert "bd" in procesos._procesos[pid1]["semaforos_adquiridos"]

    # Llega p2 con mayor prioridad (0) solicitando el mismo recurso
    pid2 = procesos.crear_proceso("p2_competidor", "admin", [("WAIT", "bd"), ("CPU", 1), ("SIGNAL", "bd")], prioridad=0)

    # Tick 2: p2 corre por tener mayor prioridad, pero 'bd' está ocupado por p1 -> p2 pasa a BLOQUEADO
    kernel.tick()
    assert procesos.estado_proceso(pid2) == "BLOQUEADO"
    assert procesos._procesos[pid2]["pc"] == 0

    # Ticks 3 y 4: p1 ejecuta su sección crítica mientras p2 sigue bloqueado
    kernel.tick()
    assert procesos.estado_proceso(pid2) == "BLOQUEADO"
    kernel.tick()
    assert procesos.estado_proceso(pid2) == "BLOQUEADO"

    # Tick 5: p1 ejecuta SIGNAL 'bd' y termina
    kernel.tick()
    assert procesos.estado_proceso(pid1) == "TERMINADO"
    assert procesos.estado_proceso(pid2) == "LISTO"

    # Tick 6: p2 (prioridad 0) ahora puede adquirir 'bd' y avanzar a su sección crítica
    kernel.tick()
    assert procesos._procesos[pid2]["pc"] == 1
    assert "bd" in procesos._procesos[pid2]["semaforos_adquiridos"]

    # Ticks 7 y 8: p2 ejecuta su CPU y emite SIGNAL terminando limpiamente
    kernel.tick()
    kernel.tick()
    assert procesos.estado_proceso(pid2) == "TERMINADO"
    assert entorno_prototipo3.semaforos["bd"].valor == 1


def test_concurrencia_multihilo_hilo_bloqueado_no_detiene_hilo_listo(entorno_prototipo3):
    """5. Concurrencia multihilo con semáforos:

    Un Hilo A bloqueado en WAIT no detiene la ejecución de un Hilo B en LISTO del mismo proceso padre.
    """
    entorno_prototipo3.crear_semaforo("sem_bloqueado", 0)
    pid = procesos.crear_proceso("p_multihilo", "admin", [])
    tid_a = procesos.crear_hilo(pid, [("WAIT", "sem_bloqueado"), ("CPU", 1)])
    tid_b = procesos.crear_hilo(pid, [("CPU", 2)])

    # Tick 1: Hilo A ejecuta WAIT -> se bloquea de inmediato
    kernel.tick()
    hilos = procesos._procesos[pid]["hilos"]
    assert hilos[0]["estado"] == "BLOQUEADO"
    assert hilos[1]["estado"] == "LISTO"
    assert procesos.estado_proceso(pid) == "LISTO"

    # Tick 2: Hilo B se despacha y ejecuta su primer tick de CPU
    kernel.tick()
    assert hilos[1]["cpu_usada"] == 1
    assert hilos[0]["estado"] == "BLOQUEADO"
    assert procesos.estado_proceso(pid) in ("LISTO", "EJECUTANDO")

    # Tick 3: Hilo B ejecuta su segundo tick de CPU y termina
    kernel.tick()
    assert hilos[1]["estado"] == "TERMINADO"
    # Ahora que Hilo B terminó e Hilo A sigue bloqueado, el proceso padre pasa a BLOQUEADO
    assert hilos[0]["estado"] == "BLOQUEADO"
    assert procesos.estado_proceso(pid) == "BLOQUEADO"


def test_proceso_padre_solo_bloqueado_si_todos_los_hilos_bloqueados(entorno_prototipo3):
    """6. El proceso padre solo transiciona a BLOQUEADO si todos sus hilos están bloqueados."""
    entorno_prototipo3.crear_semaforo("sem_1", 0)
    entorno_prototipo3.crear_semaforo("sem_2", 0)

    pid = procesos.crear_proceso("p_padre_bloqueos", "admin", [])
    tid1 = procesos.crear_hilo(pid, [("WAIT", "sem_1")])
    tid2 = procesos.crear_hilo(pid, [("WAIT", "sem_2")])

    # Tick 1: Hilo 1 se bloquea en sem_1. Hilo 2 está LISTO -> Proceso padre sigue LISTO
    kernel.tick()
    hilos = procesos._procesos[pid]["hilos"]
    assert hilos[0]["estado"] == "BLOQUEADO"
    assert hilos[1]["estado"] == "LISTO"
    assert procesos.estado_proceso(pid) == "LISTO"

    # Tick 2: Hilo 2 se bloquea en sem_2 -> Ahora todos los hilos activos están bloqueados
    kernel.tick()
    assert hilos[0]["estado"] == "BLOQUEADO"
    assert hilos[1]["estado"] == "BLOQUEADO"
    assert procesos.estado_proceso(pid) == "BLOQUEADO"

    # Despertar Hilo 1 mediante un SIGNAL externo
    pid_despertador = procesos.crear_proceso("p_wake", "admin", [("SIGNAL", "sem_1")])
    kernel.tick()

    assert hilos[0]["estado"] == "LISTO"
    assert hilos[1]["estado"] == "BLOQUEADO"
    assert procesos.estado_proceso(pid) == "LISTO"


def test_liberacion_semaforos_al_terminar_proceso_intempestivamente(entorno_prototipo3):
    """7. Liberación limpia de semáforos retenidos al invocarse terminar_proceso(pid) intempestivamente.

    Evita interbloqueos huérfanos para procesos en la cola de espera.
    """
    entorno_prototipo3.crear_semaforo("recurso_huerfano", 1)

    pid1 = procesos.crear_proceso("p_poseedor", "admin", [("WAIT", "recurso_huerfano"), ("CPU", 10)], prioridad=1)
    kernel.tick()
    assert "recurso_huerfano" in procesos._procesos[pid1]["semaforos_adquiridos"]

    pid2 = procesos.crear_proceso("p_en_espera", "admin", [("WAIT", "recurso_huerfano"), ("CPU", 1)], prioridad=0)
    kernel.tick()
    assert procesos.estado_proceso(pid2) == "BLOQUEADO"

    # Terminación intempestiva (kill o error) de pid1
    procesos.terminar_proceso(pid1)
    assert procesos.estado_proceso(pid1) == "TERMINADO"

    # pid2 debe haber sido despertado automáticamente para evitar interbloqueo huérfano
    assert procesos.estado_proceso(pid2) == "LISTO"
    assert pid2 in procesos.cola_listos()

    # En el siguiente tick, pid2 adquiere el recurso liberado
    kernel.tick()
    assert procesos._procesos[pid2]["pc"] == 1
    assert "recurso_huerfano" in procesos._procesos[pid2]["semaforos_adquiridos"]


def test_liberacion_recursos_al_terminar_normalmente_sin_signal(entorno_prototipo3):
    """8. Liberación de recursos y semáforos cuando un proceso termina normalmente tras completar su programa."""
    entorno_prototipo3.crear_semaforo("sem_olvidado", 1)

    # Proceso que hace WAIT pero nunca hace SIGNAL explícito antes de finalizar
    pid = procesos.crear_proceso("p_sin_signal", "admin", [("WAIT", "sem_olvidado"), ("CPU", 1)])

    kernel.tick()  # WAIT
    assert entorno_prototipo3.semaforos["sem_olvidado"].valor == 0

    kernel.tick()  # CPU 1 y termina naturalmente
    assert procesos.estado_proceso(pid) == "TERMINADO"

    # El semáforo debió haber sido liberado por la terminación limpia
    assert entorno_prototipo3.semaforos["sem_olvidado"].valor == 1


def test_proceso_bloqueado_en_wait_terminado_se_remueve_de_cola_semaforo(entorno_prototipo3):
    """9. Proceso bloqueado en WAIT que es terminado por terminar_proceso: se remueve limpiamente de la cola."""
    entorno_prototipo3.crear_semaforo("sem_cola_limpia", 0)
    pid = procesos.crear_proceso("p_cancelado", "admin", [("WAIT", "sem_cola_limpia"), ("CPU", 2)])

    kernel.tick()  # Se bloquea en el semáforo
    assert procesos.estado_proceso(pid) == "BLOQUEADO"

    # Terminar proceso antes de que reciba señal
    procesos.terminar_proceso(pid)
    assert procesos.estado_proceso(pid) == "TERMINADO"
    assert procesos._procesos[pid]["espera_semaforo"] is None
    assert not any(item[0] == pid for item in procesos._espera_semaforos.get("sem_cola_limpia", []))

    # Emitir un SIGNAL posterior no debe reincorporar ni despertar al proceso ya terminado
    pid_sig = procesos.crear_proceso("p_emisor", "admin", [("SIGNAL", "sem_cola_limpia")])
    kernel.tick()
    assert procesos.estado_proceso(pid) == "TERMINADO"
    assert pid not in procesos.cola_listos()


def test_preservacion_aging_y_prioridades_mlfq_tras_despertar(entorno_prototipo3):
    """10. Preservación del envejecimiento (Aging) y prioridades MLFQ para procesos que despiertan tras SIGNAL."""
    entorno_prototipo3.crear_semaforo("sem_aging", 0)

    # Proceso en baja prioridad (prioridad 2)
    pid_baja = procesos.crear_proceso("p_baja_prioridad", "admin", [("WAIT", "sem_aging"), ("CPU", 1)], prioridad=2)
    kernel.tick()
    assert procesos.estado_proceso(pid_baja) == "BLOQUEADO"

    # Despertar pid_baja con SIGNAL
    pid_sig = procesos.crear_proceso("p_sig_aging", "admin", [("SIGNAL", "sem_aging")], prioridad=0)
    kernel.tick()

    assert procesos.estado_proceso(pid_baja) == "LISTO"
    assert procesos._procesos[pid_baja]["prioridad"] == 2
    # Al final del tick en que corrió p_sig, pid_baja esperó en LISTO
    assert procesos._procesos[pid_baja]["espera_consecutiva"] == 1

    # Crear carga continua en prioridad 0 para que pid_baja espere y envejezca
    for i in range(25):
        procesos.crear_proceso(f"p_alta_{i}", "admin", [("CPU", 2)], prioridad=0)

    # Avanzar 50 ticks para forzar el umbral de aging (promoción de prioridad 2 a prioridad 1)
    for _ in range(50):
        kernel.tick()

    assert procesos._procesos[pid_baja]["prioridad"] == 1


def test_integracion_completa_cinco_instrucciones_en_un_proceso(entorno_prototipo3):
    """11. Integración completa de las 5 instrucciones en un solo proceso:

    ('MEM', dir), ('ES', bloque), ('WAIT', sem), ('CPU', n) y ('SIGNAL', sem).
    """
    entorno_prototipo3.crear_semaforo("sem_integ", 1)
    pid = procesos.crear_proceso(
        "p_full_stack",
        "admin",
        [
            ("MEM", 128),
            ("ES", 15),
            ("WAIT", "sem_integ"),
            ("CPU", 2),
            ("SIGNAL", "sem_integ"),
        ],
    )

    with patch("minidc.memoria.acceder_memoria", return_value={"marco": 3, "fallo_pagina": False}):
        # Tick 1: MEM 128
        kernel.tick()
        assert procesos._procesos[pid]["pc"] == 1

        # Tick 2: ES 15 -> Pasa a BLOQUEADO por E/S
        kernel.tick()
        assert procesos.estado_proceso(pid) == "BLOQUEADO"
        assert procesos._procesos[pid]["pc"] == 2

        # Avanzar hasta que la E/S termine y el proceso despierte y ejecute WAIT
        while procesos.estado_proceso(pid) == "BLOQUEADO":
            kernel.tick()

        # Al completar la E/S en el Paso 2, en el Paso 3 ejecuta WAIT "sem_integ"
        assert procesos._procesos[pid]["pc"] == 3
        assert "sem_integ" in procesos._procesos[pid]["semaforos_adquiridos"]

        # Siguientes 2 ticks: CPU 2
        kernel.tick()
        assert procesos._procesos[pid]["pc"] == 3
        kernel.tick()
        assert procesos._procesos[pid]["pc"] == 4

        # Siguiente tick: SIGNAL "sem_integ" y culminación
        kernel.tick()
        assert procesos.estado_proceso(pid) == "TERMINADO"
        assert entorno_prototipo3.semaforos["sem_integ"].valor == 1


def test_ejecucion_multiples_cpus_compitiendo_por_semaforos(entorno_prototipo3):
    """12. Ejecución con múltiples CPUs (num_cpus = 2) compitiendo por semáforos binarios y contadores."""
    kernel.iniciar_sistema({"num_cpus": 2, "bloques_disco": 200})
    entorno_prototipo3.crear_semaforo("binario", 1)

    # 1. Competencia por semáforo binario
    pid1 = procesos.crear_proceso("p1_cpu", "admin", [("WAIT", "binario"), ("CPU", 3)], prioridad=0)
    pid2 = procesos.crear_proceso("p2_cpu", "admin", [("WAIT", "binario"), ("CPU", 3)], prioridad=0)

    # Tick 1: Ambas CPUs despachan simultáneamente
    kernel.tick()

    # Uno adquiere el semáforo y el otro se bloquea inmediatamente en el mismo tick
    estados = {procesos.estado_proceso(pid1), procesos.estado_proceso(pid2)}
    assert "BLOQUEADO" in estados
    assert any(est in ("LISTO", "EJECUTANDO") for est in estados)
    assert entorno_prototipo3.semaforos["binario"].valor == 0

    # 2. Semáforo contador con valor 2
    kernel.iniciar_sistema({"num_cpus": 2, "bloques_disco": 200})
    entorno_prototipo3.crear_semaforo("contador_2", 2)

    pid3 = procesos.crear_proceso("p3_cpu", "admin", [("WAIT", "contador_2"), ("CPU", 2)], prioridad=0)
    pid4 = procesos.crear_proceso("p4_cpu", "admin", [("WAIT", "contador_2"), ("CPU", 2)], prioridad=0)

    # Tick 1: Ambas CPUs adquieren un permiso cada una
    kernel.tick()
    assert procesos._procesos[pid3]["pc"] == 1
    assert procesos._procesos[pid4]["pc"] == 1
    assert entorno_prototipo3.semaforos["contador_2"].valor == 0


def test_manejo_wait_signal_semaforos_no_existentes(entorno_prototipo3):
    """13. Manejo de WAIT/SIGNAL con nombres de semáforos no existentes.

    Verificar captura de excepción ErrorSincronizacion o ErrorNoExiste y terminación limpia del proceso.
    """
    # WAIT sobre semáforo que no fue creado
    pid_wait_err = procesos.crear_proceso("p_wait_err", "admin", [("WAIT", "sem_fantasma"), ("CPU", 1)])
    kernel.tick()

    # El proceso infractor debe terminar limpiamente sin tirar el sistema
    assert procesos.estado_proceso(pid_wait_err) == "TERMINADO"
    assert procesos.proceso_en_ejecucion(0) is None

    # SIGNAL sobre semáforo no existente
    pid_sig_err = procesos.crear_proceso("p_sig_err", "admin", [("SIGNAL", "sem_fantasma"), ("CPU", 1)])
    kernel.tick()

    assert procesos.estado_proceso(pid_sig_err) == "TERMINADO"
    assert procesos.proceso_en_ejecucion(0) is None


def test_multiples_procesos_esperando_cola_fifo_despertar_ordenado(entorno_prototipo3):
    """14. Múltiples procesos esperando en el mismo semáforo en cola FIFO y verificación de despertar ordenado."""
    entorno_prototipo3.crear_semaforo("cola_fifo", 0)

    pid1 = procesos.crear_proceso("p1_fifo", "admin", [("WAIT", "cola_fifo"), ("CPU", 1)], prioridad=1)
    pid2 = procesos.crear_proceso("p2_fifo", "admin", [("WAIT", "cola_fifo"), ("CPU", 1)], prioridad=1)
    pid3 = procesos.crear_proceso("p3_fifo", "admin", [("WAIT", "cola_fifo"), ("CPU", 1)], prioridad=1)

    # Se bloquean secuencialmente en orden: pid1, luego pid2, luego pid3
    kernel.tick()
    assert procesos.estado_proceso(pid1) == "BLOQUEADO"

    kernel.tick()
    assert procesos.estado_proceso(pid2) == "BLOQUEADO"

    kernel.tick()
    assert procesos.estado_proceso(pid3) == "BLOQUEADO"

    # Primera señal: debe despertar estrictamente a pid1 (primero en llegar)
    pid_s1 = procesos.crear_proceso("p_sig_1", "admin", [("SIGNAL", "cola_fifo")], prioridad=0)
    kernel.tick()
    assert procesos.estado_proceso(pid1) == "LISTO"
    assert procesos.estado_proceso(pid2) == "BLOQUEADO"
    assert procesos.estado_proceso(pid3) == "BLOQUEADO"

    # Segunda señal: debe despertar a pid2
    pid_s2 = procesos.crear_proceso("p_sig_2", "admin", [("SIGNAL", "cola_fifo")], prioridad=0)
    kernel.tick()
    assert procesos.estado_proceso(pid2) == "LISTO"
    assert procesos.estado_proceso(pid3) == "BLOQUEADO"

    # Tercera señal: debe despertar a pid3
    pid_s3 = procesos.crear_proceso("p_sig_3", "admin", [("SIGNAL", "cola_fifo")], prioridad=0)
    kernel.tick()
    assert procesos.estado_proceso(pid3) == "LISTO"


def test_metricas_finales_apagar_sistema_contabilizan_sincronizacion(entorno_prototipo3):
    """15. Verificación de que las métricas finales en kernel.apagar_sistema() contabilicen correctamente.

    Contabiliza procesos terminados y cambios de contexto inducidos por sincronización.
    """
    entorno_prototipo3.crear_semaforo("sem_metricas", 1)

    pids = [
        procesos.crear_proceso(f"p_met_{i}", "admin", [("WAIT", "sem_metricas"), ("CPU", 1), ("SIGNAL", "sem_metricas")])
        for i in range(3)
    ]

    for _ in range(15):
        kernel.tick()

    resumen = kernel.apagar_sistema()
    assert resumen["procesos_activos"] == 0
    assert resumen["procesos_terminados"] == 3
    assert 0.0 <= resumen["utilizacion_cpu"] <= 1.0
    assert "metricas_planificacion" in resumen
    assert resumen["metricas_planificacion"]["procesos_terminados"] == 3
    assert resumen["metricas_planificacion"]["cambios_contexto"] >= 0


# =====================================================================
# PRUEBAS ADICIONALES DE ROBUSTEZ Y ESCENARIOS JSON
# =====================================================================

def test_cargar_escenario_con_semaforos_inicializa_correctamente(entorno_prototipo3):
    """16. Verifica que cargar_escenario registre los semáforos del archivo JSON y funcionen en el núcleo."""
    import tempfile
    import json
    import os

    escenario_data = {
        "config": {"num_cpus": 1, "marcos_fisicos": 16, "tam_pagina": 256,
                   "bloques_disco": 200, "tam_bloque": 512, "cache_bloques": 8},
        "usuarios": ["admin", "cliente_sync"],
        "semaforos": {"lock_db": 1},
        "catalogo": {
            "servicio_sync": {
                "memoria_bytes": 1024,
                "cuota_marcos": 3,
                "prioridad": 0,
                "programa": [["WAIT", "lock_db"], ["CPU", 2], ["SIGNAL", "lock_db"]],
            }
        },
        "llegadas": [
            {"tick": 0, "programa": "servicio_sync", "usuario": "cliente_sync"}
        ],
    }

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(escenario_data, f)
        ruta = f.name

    try:
        kernel.cargar_escenario(ruta)
        assert "lock_db" in entorno_prototipo3.semaforos
        assert entorno_prototipo3.semaforos["lock_db"].valor == 1

        # Ejecutar ticks del escenario cargado
        kernel.ejecutar_ticks(5)
        lista = procesos.listar_procesos()
        assert len(lista) == 1
        assert lista[0]["estado"] == "TERMINADO"
        assert entorno_prototipo3.semaforos["lock_db"].valor == 1
    finally:
        if os.path.exists(ruta):
            os.remove(ruta)


def test_exclusion_mutua_entre_hilos_del_mismo_proceso(entorno_prototipo3):
    """17. Verifica la exclusión mutua estricta con semáforos entre hilos del mismo proceso."""
    entorno_prototipo3.crear_semaforo("lock_hilos", 1)

    pid = procesos.crear_proceso("p_padre_mutex", "admin", [])
    t1 = procesos.crear_hilo(pid, [("WAIT", "lock_hilos"), ("CPU", 2), ("SIGNAL", "lock_hilos")])
    t2 = procesos.crear_hilo(pid, [("WAIT", "lock_hilos"), ("CPU", 1), ("SIGNAL", "lock_hilos")])

    # Tick 1: Hilo 1 adquiere lock_hilos
    kernel.tick()
    hilos = procesos._procesos[pid]["hilos"]
    assert hilos[0]["pc"] == 1
    assert hilos[0]["estado"] in ("LISTO", "EJECUTANDO")

    # Tick 2: Hilo 2 intenta WAIT lock_hilos pero ya está ocupado -> se bloquea
    kernel.tick()
    assert hilos[1]["estado"] == "BLOQUEADO"
    assert hilos[1]["pc"] == 0

    # Ticks 3, 4: Hilo 1 avanza su CPU 2
    kernel.tick()
    kernel.tick()

    # Tick 5: Hilo 1 emite SIGNAL y termina
    kernel.tick()
    assert hilos[0]["estado"] == "TERMINADO"
    # Hilo 2 debe haberse despertado
    assert hilos[1]["estado"] == "LISTO"

    # Siguiente tick: Hilo 2 adquiere lock_hilos
    kernel.tick()
    assert hilos[1]["pc"] == 1

    # Finalizar Hilo 2
    kernel.tick()
    kernel.tick()
    assert all(h["estado"] == "TERMINADO" for h in hilos)
    assert procesos.estado_proceso(pid) == "TERMINADO"
