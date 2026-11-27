"""Pruebas unitarias y de integración para el módulo sincronizacion.py (Prototipo 3).

Valida exhaustivamente:
- Semáforos contadores y binarios (FIFO, wait, signal, estado, reservas).
- Mutexes (adquisición, cola de espera FIFO, liberación exclusiva, verificación de dueño).
- Liberación automática de recursos (liberar_recursos / liberar_proceso).
- Grafo de espera y detección de ciclos de interbloqueo (detectar_interbloqueo).
- Resolución determinista de interbloqueos (resolver_interbloqueo) satisfaciendo RS2.
- Demostración de condición de carrera con hilos reales satisfaciendo RS1.
- Casos borde, excepciones y validaciones de robustez.
"""
import pytest

from minidc import sincronizacion
from minidc.errores import ErrorSincronizacion, ErrorSistema, ErrorYaExiste


@pytest.fixture(autouse=True)
def limpiar_sincronizacion():
    """Reinicia el estado del módulo antes de cada prueba."""
    sincronizacion.reiniciar()
    yield
    sincronizacion.reiniciar()


# =====================================================================
# 1. SEMÁFOROS
# =====================================================================

def test_crear_semaforo_exitoso_y_estado():
    sincronizacion.crear_semaforo("sem1", 3)
    est = sincronizacion.estado_semaforo("sem1")
    assert est == {"valor": 3, "cola_espera": []}


def test_crear_semaforo_valor_cero():
    sincronizacion.crear_semaforo("sem_cero", 0)
    assert sincronizacion.estado_semaforo("sem_cero")["valor"] == 0


def test_crear_semaforo_valor_negativo_lanza_error():
    with pytest.raises(ErrorSincronizacion):
        sincronizacion.crear_semaforo("invalido", -1)


def test_crear_semaforo_nombre_invalido_lanza_error():
    with pytest.raises(ErrorSincronizacion):
        sincronizacion.crear_semaforo("", 1)
    with pytest.raises(ErrorSincronizacion):
        sincronizacion.crear_semaforo(123, 1)  # type: ignore


def test_crear_semaforo_duplicado_lanza_error():
    sincronizacion.crear_semaforo("duplicado", 1)
    with pytest.raises(ErrorYaExiste):
        sincronizacion.crear_semaforo("duplicado", 2)


def test_semaforo_inexistente_lanza_error():
    with pytest.raises(ErrorSincronizacion):
        sincronizacion.estado_semaforo("no_existe")
    with pytest.raises(ErrorSincronizacion):
        sincronizacion.semaforo_wait("no_existe", 1)
    with pytest.raises(ErrorSincronizacion):
        sincronizacion.semaforo_signal("no_existe", 1)


def test_semaforo_wait_adquisicion_inmediata():
    sincronizacion.crear_semaforo("recurso", 2)
    assert sincronizacion.semaforo_wait("recurso", 10) is True
    assert sincronizacion.estado_semaforo("recurso")["valor"] == 1

    assert sincronizacion.semaforo_wait("recurso", 20) is True
    assert sincronizacion.estado_semaforo("recurso")["valor"] == 0


def test_semaforo_wait_bloqueo_y_cola_fifo():
    sincronizacion.crear_semaforo("binario", 1)
    assert sincronizacion.semaforo_wait("binario", 1) is True

    # Los siguientes deben quedar bloqueados en orden FIFO
    assert sincronizacion.semaforo_wait("binario", 2) is False
    assert sincronizacion.semaforo_wait("binario", 3) is False
    assert sincronizacion.semaforo_wait("binario", 4) is False

    est = sincronizacion.estado_semaforo("binario")
    assert est["valor"] == 0
    assert est["cola_espera"] == [2, 3, 4]


def test_semaforo_signal_sin_espera_incrementa_valor():
    sincronizacion.crear_semaforo("contador", 0)
    ret = sincronizacion.semaforo_signal("contador", 99)
    assert ret is None
    assert sincronizacion.estado_semaforo("contador")["valor"] == 1


def test_semaforo_signal_despierta_en_orden_fifo_y_reserva():
    sincronizacion.crear_semaforo("s", 0)
    sincronizacion.semaforo_wait("s", 101)
    sincronizacion.semaforo_wait("s", 102)
    sincronizacion.semaforo_wait("s", 103)

    # Primer signal despierta al 101
    despertado = sincronizacion.semaforo_signal("s", 200)
    assert despertado == 101
    assert sincronizacion.estado_semaforo("s")["cola_espera"] == [102, 103]

    # Cuando 101 vuelve a ejecutar wait, obtiene el recurso reservado de inmediato
    assert sincronizacion.semaforo_wait("s", 101) is True

    # Segundo signal despierta al 102
    despertado = sincronizacion.semaforo_signal("s", 200)
    assert despertado == 102
    assert sincronizacion.estado_semaforo("s")["cola_espera"] == [103]
    assert sincronizacion.semaforo_wait("s", 102) is True


# =====================================================================
# 2. MUTEX
# =====================================================================

def test_crear_mutex_exitoso():
    sincronizacion.crear_mutex("m1")
    assert "m1" in sincronizacion._mutexes
    assert sincronizacion._mutexes["m1"]["duenio"] is None
    assert sincronizacion._mutexes["m1"]["cola_espera"] == []


def test_crear_mutex_invalido_o_duplicado():
    with pytest.raises(ErrorSincronizacion):
        sincronizacion.crear_mutex("")
    sincronizacion.crear_mutex("m_dup")
    with pytest.raises(ErrorYaExiste):
        sincronizacion.crear_mutex("m_dup")


def test_mutex_inexistente_lanza_error():
    with pytest.raises(ErrorSincronizacion):
        sincronizacion.mutex_lock("m_fantasma", 1)
    with pytest.raises(ErrorSincronizacion):
        sincronizacion.mutex_unlock("m_fantasma", 1)


def test_mutex_lock_y_unlock_basico():
    sincronizacion.crear_mutex("candado")
    assert sincronizacion.mutex_lock("candado", 1) is True
    assert sincronizacion._mutexes["candado"]["duenio"] == 1

    # Reentrancia por el mismo proceso devuelve True
    assert sincronizacion.mutex_lock("candado", 1) is True

    # Desbloqueo exitoso
    sincronizacion.mutex_unlock("candado", 1)
    assert sincronizacion._mutexes["candado"]["duenio"] is None


def test_mutex_lock_bloqueo_y_cola_fifo():
    sincronizacion.crear_mutex("seccion_critica")
    assert sincronizacion.mutex_lock("seccion_critica", 10) is True

    # Otro proceso intenta entrar y se encola
    assert sincronizacion.mutex_lock("seccion_critica", 20) is False
    assert sincronizacion.mutex_lock("seccion_critica", 30) is False
    assert sincronizacion._mutexes["seccion_critica"]["cola_espera"] == [20, 30]

    # Dueño libera: se transfiere al 20
    sincronizacion.mutex_unlock("seccion_critica", 10)
    assert sincronizacion._mutexes["seccion_critica"]["duenio"] == 20
    assert sincronizacion._mutexes["seccion_critica"]["cola_espera"] == [30]

    # Proceso 20 libera: se transfiere al 30
    sincronizacion.mutex_unlock("seccion_critica", 20)
    assert sincronizacion._mutexes["seccion_critica"]["duenio"] == 30
    assert sincronizacion._mutexes["seccion_critica"]["cola_espera"] == []

    # Proceso 30 libera: queda libre (None)
    sincronizacion.mutex_unlock("seccion_critica", 30)
    assert sincronizacion._mutexes["seccion_critica"]["duenio"] is None


def test_mutex_unlock_por_no_duenio_lanza_error():
    sincronizacion.crear_mutex("exclusivo")
    sincronizacion.mutex_lock("exclusivo", 1)

    with pytest.raises(ErrorSincronizacion):
        sincronizacion.mutex_unlock("exclusivo", 2)  # proceso 2 no es el dueño


# =====================================================================
# 3. LIBERACIÓN DE RECURSOS
# =====================================================================

def test_liberar_recursos_proceso_duenio_de_mutex():
    sincronizacion.crear_mutex("m_liberar")
    sincronizacion.mutex_lock("m_liberar", 1)
    sincronizacion.mutex_lock("m_liberar", 2)

    sincronizacion.liberar_recursos(1)
    # Debe haberse transferido al proceso 2
    assert sincronizacion._mutexes["m_liberar"]["duenio"] == 2
    assert sincronizacion._mutexes["m_liberar"]["cola_espera"] == []


def test_liberar_recursos_proceso_en_cola_de_espera():
    sincronizacion.crear_mutex("m_cola")
    sincronizacion.mutex_lock("m_cola", 1)
    sincronizacion.mutex_lock("m_cola", 2)
    sincronizacion.mutex_lock("m_cola", 3)

    # 2 se cancela/termina mientras estaba en espera
    sincronizacion.liberar_recursos(2)
    assert sincronizacion._mutexes["m_cola"]["cola_espera"] == [3]


def test_liberar_recursos_poseedor_de_semaforo():
    sincronizacion.crear_semaforo("sem_res", 1)
    sincronizacion.semaforo_wait("sem_res", 1)
    sincronizacion.semaforo_wait("sem_res", 2)

    # 1 muere reteniendo el semáforo
    sincronizacion.liberar_recursos(1)
    # Debe haber despertado a 2 o haber liberado el permiso
    assert 2 in sincronizacion._semaforos["sem_res"]["reservados"]
    assert sincronizacion.semaforo_wait("sem_res", 2) is True


# =====================================================================
# 4. INTERBLOQUEOS (DEADLOCKS) Y RS2
# =====================================================================

def test_sin_interbloqueo_devuelve_lista_vacia():
    sincronizacion.crear_mutex("m1")
    sincronizacion.crear_mutex("m2")
    sincronizacion.mutex_lock("m1", 1)
    sincronizacion.mutex_lock("m2", 2)
    # Ninguno espera al otro
    assert sincronizacion.detectar_interbloqueo() == []


def test_detectar_interbloqueo_ciclo_dos_procesos_mutex():
    sincronizacion.crear_mutex("m1")
    sincronizacion.crear_mutex("m2")

    sincronizacion.mutex_lock("m1", 10)
    sincronizacion.mutex_lock("m2", 20)

    # 10 espera por m2 (que tiene 20)
    sincronizacion.mutex_lock("m2", 10)
    # 20 espera por m1 (que tiene 10)
    sincronizacion.mutex_lock("m1", 20)

    ciclos = sincronizacion.detectar_interbloqueo()
    assert len(ciclos) == 1
    assert set(ciclos[0]) == {10, 20}


def test_detectar_interbloqueo_ciclo_tres_procesos():
    sincronizacion.crear_mutex("r1")
    sincronizacion.crear_mutex("r2")
    sincronizacion.crear_mutex("r3")

    sincronizacion.mutex_lock("r1", 1)
    sincronizacion.mutex_lock("r2", 2)
    sincronizacion.mutex_lock("r3", 3)

    sincronizacion.mutex_lock("r2", 1)  # 1 espera a 2
    sincronizacion.mutex_lock("r3", 2)  # 2 espera a 3
    sincronizacion.mutex_lock("r1", 3)  # 3 espera a 1

    ciclos = sincronizacion.detectar_interbloqueo()
    assert len(ciclos) == 1
    assert set(ciclos[0]) == {1, 2, 3}


def test_resolver_interbloqueo_cumple_rs2():
    """RS2: Tras llamar resolver_interbloqueo(), detectar_interbloqueo() devuelve []"""
    sincronizacion.crear_mutex("a")
    sincronizacion.crear_mutex("b")
    sincronizacion.mutex_lock("a", 1)
    sincronizacion.mutex_lock("b", 2)
    sincronizacion.mutex_lock("b", 1)
    sincronizacion.mutex_lock("a", 2)

    assert len(sincronizacion.detectar_interbloqueo()) > 0

    afectados = sincronizacion.resolver_interbloqueo()
    assert len(afectados) >= 1
    assert set(afectados).issubset({1, 2})
    # RS2 estricto
    assert sincronizacion.detectar_interbloqueo() == []


def test_resolver_interbloqueos_multiples_independientes():
    # Ciclo 1: 1 <-> 2
    sincronizacion.crear_mutex("m1")
    sincronizacion.crear_mutex("m2")
    sincronizacion.mutex_lock("m1", 1)
    sincronizacion.mutex_lock("m2", 2)
    sincronizacion.mutex_lock("m2", 1)
    sincronizacion.mutex_lock("m1", 2)

    # Ciclo 2: 3 <-> 4
    sincronizacion.crear_mutex("m3")
    sincronizacion.crear_mutex("m4")
    sincronizacion.mutex_lock("m3", 3)
    sincronizacion.mutex_lock("m4", 4)
    sincronizacion.mutex_lock("m4", 3)
    sincronizacion.mutex_lock("m3", 4)

    assert len(sincronizacion.detectar_interbloqueo()) == 2

    afectados = sincronizacion.resolver_interbloqueo()
    assert len(afectados) == 2
    assert sincronizacion.detectar_interbloqueo() == []


# =====================================================================
# 5. DEMOSTRACIÓN DE CONDICIÓN DE CARRERA Y RS1
# =====================================================================

def test_demo_condicion_carrera_con_sincronizacion_rs1():
    """RS1: Con sincronización el resultado es exactamente num_hilos * iteraciones."""
    total = sincronizacion.demo_condicion_carrera(True, num_hilos=8, iteraciones=1000)
    assert total == 8000


def test_demo_condicion_carrera_sin_sincronizacion_pierde_actualizaciones():
    """Sin sincronización se producen condiciones de carrera y pérdida de datos."""
    total = sincronizacion.demo_condicion_carrera(False, num_hilos=8, iteraciones=1000)
    assert total < 8000
    assert total > 0


# =====================================================================
# 6. REINICIO DEL MÓDULO
# =====================================================================

def test_reiniciar_modulo():
    sincronizacion.crear_semaforo("s_temp", 1)
    sincronizacion.crear_mutex("m_temp")
    assert "s_temp" in sincronizacion._semaforos
    assert "m_temp" in sincronizacion._mutexes

    sincronizacion.reiniciar()
    assert sincronizacion._semaforos == {}
    assert sincronizacion._mutexes == {}
