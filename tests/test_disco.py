import pytest

from minidc import disco
from minidc.errores import ErrorSistema

CONFIG = {"bloques_disco": 200, "cache_bloques": 8}


@pytest.fixture(autouse=True)
def estado_limpio():
    """Se ejecuta antes de CADA prueba: ninguna depende de otra."""
    disco.reiniciar(CONFIG)


def ticks_hasta_terminar(max_ticks=100):
    """Llama avanzar_tick() hasta que algún PID termine. Devuelve (ticks, pids)."""
    for n in range(1, max_ticks + 1):
        terminados = disco.avanzar_tick()
        if terminados:
            return n, terminados
    return None, []


# ---------------------------------------------------------- tiempo de servicio
def test_bloque_40_con_cabezal_en_0_tarda_5_ticks():
    disco.encolar_solicitud_disco(pid=1, bloque=40, operacion="L")
    for _ in range(4):
        assert disco.avanzar_tick() == []       # ni antes...
    assert disco.avanzar_tick() == [1]          # ...ni después


def test_tiempo_depende_de_la_posicion_del_cabezal():
    disco.encolar_solicitud_disco(1, 40, "L")
    ticks_hasta_terminar()                      # el cabezal queda en 40
    disco.encolar_solicitud_disco(2, 45, "L")   # 1 + 5 // 10 = 1 tick
    assert disco.avanzar_tick() == [2]


def test_disco_libre_no_devuelve_nada():
    assert disco.avanzar_tick() == []


# ------------------------------------------------------------- orden y cola
def test_dos_solicitudes_en_orden_de_llegada_sin_tick_perdido():
    disco.encolar_solicitud_disco(1, 40, "L")   # 5 ticks
    disco.encolar_solicitud_disco(2, 40, "L")   # distancia 0 -> 1 tick
    assert ticks_hasta_terminar() == (5, [1])
    assert disco.avanzar_tick() == [2]          # el siguiente tick, sin hueco


def test_cola_disco_en_orden_de_atencion_y_es_copia():
    disco.encolar_solicitud_disco(1, 30, "L")
    disco.encolar_solicitud_disco(2, 10, "E")
    cola = disco.cola_disco()
    assert cola == [30, 10]
    cola.append(999)                            # alterar la copia...
    assert disco.cola_disco() == [30, 10]       # ...no afecta al disco


def test_ids_de_solicitud_unicos_y_crecientes():
    a = disco.encolar_solicitud_disco(1, 5, "L")
    b = disco.encolar_solicitud_disco(1, 6, "L")
    assert b > a


# ------------------------------------------------------------ procesar_disco
def test_procesar_disco_orden_y_desplazamiento():
    for pid, bloque in enumerate((30, 10, 50), start=1):
        disco.encolar_solicitud_disco(pid, bloque, "L")
    assert disco.procesar_disco() == [30, 10, 50]
    m = disco.metricas_disco()
    assert m["desplazamiento_total"] == 30 + 20 + 40
    assert m["solicitudes_atendidas"] == 3
    assert m["posicion_cabezal"] == 50
    assert disco.cola_disco() == []


# --------------------------------------------------------------- cancelar
def test_cancelar_solicitudes_limpia_la_cola():
    disco.encolar_solicitud_disco(1, 40, "L")
    disco.encolar_solicitud_disco(2, 50, "L")
    assert disco.cancelar_solicitudes(1) == 1
    assert disco.cola_disco() == [50]


def test_cancelar_la_solicitud_en_servicio_no_libera_al_pid():
    disco.encolar_solicitud_disco(1, 40, "L")
    disco.avanzar_tick()                        # ya está en servicio
    disco.cancelar_solicitudes(1)
    assert ticks_hasta_terminar(20) == (None, [])


# ---------------------------------------------------------------- reinicio
def test_reiniciar_deja_todo_en_cero():
    disco.encolar_solicitud_disco(1, 40, "L")
    disco.avanzar_tick()
    disco.reiniciar(CONFIG)
    assert disco.cola_disco() == []
    assert disco.metricas_disco() == {
        "solicitudes_atendidas": 0,
        "desplazamiento_total": 0,
        "posicion_cabezal": 0,
    }
    assert disco.avanzar_tick() == []


# ------------------------------------------------------------ validaciones
@pytest.mark.parametrize("bloque", [-1, 200, 999])
def test_bloque_fuera_de_rango_lanza_error(bloque):
    with pytest.raises(ErrorSistema):
        disco.encolar_solicitud_disco(1, bloque, "L")


def test_operacion_invalida_lanza_error():
    with pytest.raises(ErrorSistema):
        disco.encolar_solicitud_disco(1, 10, "X")


# ----------------------------------------------------- métricas y caché
def test_metricas_sin_solicitudes_no_fallan():
    assert disco.metricas_disco()["solicitudes_atendidas"] == 0


def test_info_cache_sin_accesos_tasa_cero():
    info = disco.info_cache()
    assert info["capacidad_bloques"] == 8
    assert info["tasa_aciertos"] == 0.0


def test_politica_disco_devuelve_texto():
    assert isinstance(disco.politica_disco(), str)



# ----------------------------------------------------- verificación documento guía

def test_solicitud_que_llega_durante_un_servicio_no_lo_interrumpe():
    disco.encolar_solicitud_disco(pid=1, bloque=40, operacion="L")   # 5 ticks
    for _ in range(2):                                               # llamadas 1 y 2
        assert disco.avanzar_tick() == []
    disco.encolar_solicitud_disco(pid=2, bloque=5, operacion="L")    # llega con el 1 en servicio
    for _ in range(2):                                               # llamadas 3 y 4
        assert disco.avanzar_tick() == []
    assert disco.avanzar_tick() == [1]                               # llamada 5: sale el PID 1
    for _ in range(3):                                               # llamadas 6, 7 y 8
        assert disco.avanzar_tick() == []
    assert disco.avanzar_tick() == [2]                               # llamada 9: 1 + 35 // 10 = 4 ticks