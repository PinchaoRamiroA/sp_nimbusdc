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
    assert cola == [10, 30]                     # C-LOOK: subiendo desde el cabezal (0)
    cola.append(999)                            # alterar la copia...
    assert disco.cola_disco() == [10, 30]       # ...no afecta al disco


def test_ids_de_solicitud_unicos_y_crecientes():
    a = disco.encolar_solicitud_disco(1, 5, "L")
    b = disco.encolar_solicitud_disco(1, 6, "L")
    assert b > a


# ------------------------------------------------------------ procesar_disco
def test_procesar_disco_orden_y_desplazamiento():
    for pid, bloque in enumerate((30, 10, 50), start=1):
        disco.encolar_solicitud_disco(pid, bloque, "L")
    assert disco.procesar_disco() == [10, 30, 50]     # C-LOOK desde el bloque 0
    m = disco.metricas_disco()
    assert m["desplazamiento_total"] == 10 + 20 + 20
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
@pytest.mark.parametrize("bloque", [-1, 200, 999, True, 3.0])
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

# ================================================== Prototipo 2: C-LOOK
def test_politica_disco_es_clook():
    assert disco.politica_disco() == "C-LOOK"


def test_clook_sube_y_luego_salta_al_mas_bajo():
    disco.procesar_disco()                      # nada pendiente
    disco.encolar_solicitud_disco(1, 100, "L")
    disco.procesar_disco()                      # cabezal en 100
    for pid, bloque in enumerate((150, 20, 120, 60, 199), start=2):
        disco.encolar_solicitud_disco(pid, bloque, "L")
    assert disco.cola_disco() == [120, 150, 199, 20, 60]
    assert disco.procesar_disco() == [120, 150, 199, 20, 60]
    # 100 -> 120 -> 150 -> 199 (99) + salto a 20 (179) + 20 -> 60 (40)
    assert disco.metricas_disco()["desplazamiento_total"] == 100 + 99 + 179 + 40


def test_clook_mismo_bloque_atiende_primero_la_mas_antigua():
    disco.encolar_solicitud_disco(1, 50, "L")
    disco.encolar_solicitud_disco(2, 50, "E")
    disco.encolar_solicitud_disco(3, 10, "L")
    _, pids = ticks_hasta_terminar()
    assert pids == [3]                          # 10 está antes que 50 subiendo desde 0
    _, pids = ticks_hasta_terminar()
    assert pids == [1]


def test_clook_reduce_desplazamiento_al_menos_30_por_ciento():
    """RD1 en lote: misma carga, C-LOOK frente al orden de llegada (FCFS)."""
    import random
    for semilla in range(1, 6):
        r = random.Random(semilla)
        bloques = [r.randrange(200) for _ in range(30)]
        fcfs = sum(abs(b - a) for a, b in zip([0] + bloques, bloques))
        disco.reiniciar(CONFIG)
        for pid, bloque in enumerate(bloques, start=1):
            disco.encolar_solicitud_disco(pid, bloque, "L")
        disco.procesar_disco()
        assert disco.metricas_disco()["desplazamiento_total"] <= 0.7 * fcfs


def test_politicas_alternativas_para_el_experimento():
    try:
        disco._fijar_politica("FCFS")
        disco.encolar_solicitud_disco(1, 30, "L")
        disco.encolar_solicitud_disco(2, 10, "L")
        assert disco.cola_disco() == [30, 10]
        disco._fijar_politica("SSTF")
        disco.procesar_disco()                  # cabezal en 10 (SSTF: 10 y luego 30)
        assert disco.metricas_disco()["posicion_cabezal"] == 30
        with pytest.raises(ErrorSistema):
            disco._fijar_politica("SCAN-mágico")
    finally:
        disco._fijar_politica("C-LOOK")


# ------------------------------------------------------------ inanición
def test_clook_no_deja_esperando_a_una_solicitud_lejana():
    """Una solicitud lejana con un flujo constante de cercanas: se atiende a tiempo."""
    import random
    r = random.Random(7)
    disco.encolar_solicitud_disco(1, 20, "L")
    disco.encolar_solicitud_disco(999, 190, "L")
    for t in range(1, 401):
        if 999 in disco.avanzar_tick():
            break
        disco.encolar_solicitud_disco(2, r.randrange(31), "L")
    assert t <= 200                             # RD1: ninguna espera más de 200 ticks


def test_estadisticas_espera():
    assert disco.estadisticas_espera() == {"espera_maxima": 0, "espera_promedio": 0.0}
    disco.encolar_solicitud_disco(1, 40, "L")   # 5 ticks
    disco.encolar_solicitud_disco(2, 40, "L")   # 1 tick más
    ticks_hasta_terminar()
    disco.avanzar_tick()
    e = disco.estadisticas_espera()
    assert e["espera_maxima"] == 6
    assert e["espera_promedio"] == (5 + 6) / 2


# --------------------------------------------------------------- caché
def test_lectura_repetida_acierta_en_cache_sin_mover_el_cabezal():
    disco.encolar_solicitud_disco(1, 150, "L")
    ticks_hasta_terminar()                      # 150 queda en caché
    disco.encolar_solicitud_disco(2, 10, "L")
    ticks_hasta_terminar()                      # el cabezal se va a 10
    disco.encolar_solicitud_disco(3, 150, "L")  # acierto: no hace falta volver a 150
    assert disco.avanzar_tick() == [3]          # termina en 1 tick
    assert disco.metricas_disco()["posicion_cabezal"] == 10
    info = disco.info_cache()
    assert (info["aciertos"], info["fallos"]) == (1, 2)
    assert info["tasa_aciertos"] == pytest.approx(1 / 3)


def test_cache_lru_saca_el_bloque_usado_hace_mas_tiempo():
    disco.reiniciar({"bloques_disco": 200, "cache_bloques": 2})
    for pid, bloque in enumerate((10, 20), start=1):
        disco.encolar_solicitud_disco(pid, bloque, "L")
    disco.procesar_disco()                      # caché: 10, 20
    disco.encolar_solicitud_disco(3, 10, "L")   # acierto: 10 pasa a ser el más reciente
    disco.encolar_solicitud_disco(4, 30, "L")   # fallo
    disco.procesar_disco()                      # entra 30, sale 20
    disco.encolar_solicitud_disco(5, 20, "L")
    disco.encolar_solicitud_disco(6, 10, "L")
    info = disco.info_cache()
    assert (info["aciertos"], info["fallos"]) == (2, 4)   # 20 falla, 10 acierta


def test_escritura_va_al_disco_y_actualiza_la_cache():
    disco.encolar_solicitud_disco(1, 80, "E")
    assert disco.cola_disco() == [80]           # la escritura usa el cabezal
    disco.procesar_disco()
    disco.encolar_solicitud_disco(2, 80, "L")   # el bloque escrito quedó en caché
    info = disco.info_cache()
    assert (info["aciertos"], info["fallos"]) == (1, 0)   # solo cuentan lecturas


def test_cache_de_capacidad_cero_no_guarda_nada():
    disco.reiniciar({"bloques_disco": 200, "cache_bloques": 0})
    disco.encolar_solicitud_disco(1, 10, "L")
    disco.procesar_disco()
    disco.encolar_solicitud_disco(2, 10, "L")
    assert disco.info_cache()["aciertos"] == 0


def test_aciertos_aparecen_en_cola_y_en_procesar_disco():
    disco.encolar_solicitud_disco(1, 60, "L")
    disco.procesar_disco()
    disco.encolar_solicitud_disco(2, 90, "L")
    disco.encolar_solicitud_disco(3, 60, "L")   # acierto
    assert disco.cola_disco() == [60, 90]       # la caché responde primero
    assert disco.procesar_disco() == [60, 90]
    assert disco.metricas_disco()["solicitudes_atendidas"] == 3


def test_cancelar_quita_tambien_los_aciertos_pendientes():
    disco.encolar_solicitud_disco(1, 60, "L")
    disco.procesar_disco()
    disco.encolar_solicitud_disco(2, 60, "L")   # acierto pendiente
    assert disco.cancelar_solicitudes(2) == 1
    assert disco.avanzar_tick() == []


def test_reiniciar_vacia_la_cache():
    disco.encolar_solicitud_disco(1, 60, "L")
    disco.procesar_disco()
    disco.reiniciar(CONFIG)
    disco.encolar_solicitud_disco(2, 60, "L")
    assert disco.info_cache() == {"capacidad_bloques": 8, "aciertos": 0,
                                  "fallos": 1, "tasa_aciertos": 0.0}


# ----------------------------------- ejemplo comparativo de la guía (6.5)
@pytest.mark.parametrize("politica, orden, desplazamiento", [
    ("FCFS", [98, 183, 37, 122, 14, 124, 65, 67], 640),
    ("SSTF", [65, 67, 37, 14, 98, 122, 124, 183], 236),
    ("C-LOOK", [65, 67, 98, 122, 124, 183, 14, 37], 322),
])
def test_ejemplo_de_la_guia_cabezal_en_53(politica, orden, desplazamiento):
    try:
        disco._fijar_politica(politica)
        disco.encolar_solicitud_disco(0, 53, "E")       # llevar el cabezal a 53
        disco.procesar_disco()
        inicial = disco.metricas_disco()["desplazamiento_total"]
        for pid, bloque in enumerate([98, 183, 37, 122, 14, 124, 65, 67], start=1):
            disco.encolar_solicitud_disco(pid, bloque, "L")
        assert disco.cola_disco() == orden
        assert disco.procesar_disco() == orden
        assert disco.metricas_disco()["desplazamiento_total"] - inicial == desplazamiento
    finally:
        disco._fijar_politica("C-LOOK")


def test_clook_un_flujo_al_mismo_bloque_no_deja_esperando_a_otra():
    """Regresión: llegan sin parar solicitudes al bloque donde está el cabezal."""
    disco.reiniciar({"bloques_disco": 200, "cache_bloques": 0})
    disco.encolar_solicitud_disco(1, 50, "E")
    disco.encolar_solicitud_disco(2, 60, "E")
    for t in range(1, 101):
        terminados = disco.avanzar_tick()
        if 2 in terminados:
            break
        for pid in terminados:                       # el 1 vuelve a pedir el bloque 50
            disco.encolar_solicitud_disco(pid, 50, "E")
    assert 2 in terminados and t <= 10


def test_clook_atiende_en_la_siguiente_pasada_el_bloque_del_cabezal():
    disco.encolar_solicitud_disco(1, 50, "L")
    disco.procesar_disco()                          # cabezal en 50
    disco.encolar_solicitud_disco(2, 50, "L")       # mismo bloque (acierto de caché)
    disco.encolar_solicitud_disco(3, 50, "E")       # mismo bloque, al disco
    disco.encolar_solicitud_disco(4, 70, "E")
    disco.encolar_solicitud_disco(5, 20, "E")
    assert disco.cola_disco() == [50, 70, 20, 50]   # caché, por delante, salto, siguiente pasada


@pytest.mark.parametrize("config", [{"bloques_disco": 0}, {"cache_bloques": -1}])
def test_reiniciar_valida_la_configuracion(config):
    with pytest.raises(ErrorSistema):
        disco.reiniciar(config)
