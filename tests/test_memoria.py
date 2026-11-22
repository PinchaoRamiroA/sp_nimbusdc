"""Pruebas unitarias de memoria.py (Integrante 2, Prototipo 2).

Usan solo memoria: cada proceso se registra con registrar_proceso para no
depender de procesos.py. Las pruebas de requisitos con escenarios están en
tests/test_requisitos_memoria_disco.py.
"""
import pytest

from minidc import memoria, procesos
from minidc.errores import ErrorMemoria, ErrorNoExiste, ErrorSistema

CONFIG = {"marcos_fisicos": 8, "tam_pagina": 100}


@pytest.fixture(autouse=True)
def estado_limpio():
    """Antes de CADA prueba: memoria nueva y la política elegida (Reloj).

    También se reinicia procesos: memoria libera sola los PID que procesos
    marcó como TERMINADO, y otras pruebas pueden dejar procesos viejos.
    """
    procesos.reiniciar({})
    memoria._fijar_politica("RELOJ")
    memoria.reiniciar(CONFIG)
    yield
    memoria._fijar_politica("RELOJ")


# ------------------------------------------------------- traducción básica
def test_primer_acceso_es_fallo_y_el_segundo_acierto():
    memoria.registrar_proceso(1, 1000, 4)
    r1 = memoria.acceder_memoria(1, 250)
    assert r1 == {"marco": 0, "fallo_pagina": True, "pagina_reemplazada": None}
    r2 = memoria.acceder_memoria(1, 299)            # misma página (2)
    assert r2 == {"marco": 0, "fallo_pagina": False, "pagina_reemplazada": None}


def test_tabla_paginas_formato_del_enunciado():
    memoria.registrar_proceso(1, 250, 4)            # 250 B / 100 B -> 3 páginas
    memoria.acceder_memoria(1, 120, escritura=True)
    tabla = memoria.tabla_paginas(1)
    assert set(tabla) == {0, 1, 2}
    assert tabla[1] == {"marco": 0, "presente": True, "modificada": True, "referenciada": True}
    assert tabla[0] == {"marco": None, "presente": False, "modificada": False, "referenciada": False}


def test_tabla_paginas_es_copia():
    memoria.registrar_proceso(1, 300, 2)
    tabla = memoria.tabla_paginas(1)
    tabla[0]["presente"] = True
    assert memoria.tabla_paginas(1)[0]["presente"] is False


def test_lectura_no_marca_modificada():
    memoria.registrar_proceso(1, 300, 2)
    memoria.acceder_memoria(1, 0)
    assert memoria.tabla_paginas(1)[0]["modificada"] is False


# ------------------------------------------------------------- RM3
@pytest.mark.parametrize("direccion", [-1, 1000, 5000])
def test_fuera_del_espacio_lanza_error_memoria(direccion):
    memoria.registrar_proceso(1, 1000, 4)
    with pytest.raises(ErrorMemoria):
        memoria.acceder_memoria(1, direccion)


def test_error_memoria_es_error_sistema():
    memoria.registrar_proceso(1, 100, 1)
    with pytest.raises(ErrorSistema):
        memoria.acceder_memoria(1, 100)            # la última válida es 99


def test_ultima_direccion_valida_si_se_puede_usar():
    memoria.registrar_proceso(1, 1000, 4)
    assert memoria.acceder_memoria(1, 999)["fallo_pagina"] is True


def test_acceso_invalido_no_cambia_ningun_estado():
    """RM3: el error no afecta a otros procesos ni a las métricas."""
    memoria.registrar_proceso(1, 500, 3)
    memoria.registrar_proceso(2, 500, 3)
    memoria.acceder_memoria(1, 0)
    memoria.acceder_memoria(2, 0)
    antes = (memoria.estado_memoria(), memoria.metricas_memoria(),
             memoria.tabla_paginas(1), memoria.tabla_paginas(2))
    with pytest.raises(ErrorMemoria):
        memoria.acceder_memoria(2, 10_000)
    despues = (memoria.estado_memoria(), memoria.metricas_memoria(),
               memoria.tabla_paginas(1), memoria.tabla_paginas(2))
    assert antes == despues
    assert memoria.acceder_memoria(1, 0)["fallo_pagina"] is False   # el otro sigue igual


def test_pid_desconocido_lanza_error_no_existe():
    with pytest.raises(ErrorNoExiste):
        memoria.acceder_memoria(77, 0)


# ------------------------------------------------- cuota y reemplazo local
def test_nunca_supera_la_cuota_de_marcos():
    memoria.registrar_proceso(1, 1000, 3)
    for direccion in range(0, 1000, 100):          # 10 páginas distintas
        memoria.acceder_memoria(1, direccion)
        assert memoria.estado_memoria()["marcos_por_proceso"][1] <= 3


def test_lru_reemplaza_la_usada_hace_mas_tiempo():
    memoria._fijar_politica("LRU")
    memoria.registrar_proceso(1, 1000, 3)
    for direccion in (0, 100, 200):                # páginas 0, 1, 2
        memoria.acceder_memoria(1, direccion)
    memoria.acceder_memoria(1, 0)                  # la 0 se vuelve reciente
    r = memoria.acceder_memoria(1, 300)            # página 3: sale la 1 (LRU)
    assert r["fallo_pagina"] is True
    assert r["pagina_reemplazada"] == (1, 1)
    assert memoria.tabla_paginas(1)[1]["presente"] is False


def test_fifo_reemplaza_la_cargada_primero():
    memoria._fijar_politica("FIFO")
    memoria.registrar_proceso(1, 1000, 3)
    for direccion in (0, 100, 200, 0):
        memoria.acceder_memoria(1, direccion)
    assert memoria.acceder_memoria(1, 300)["pagina_reemplazada"] == (1, 0)


def test_reloj_da_segunda_oportunidad():
    memoria.registrar_proceso(1, 1000, 3)
    for direccion in (0, 100, 200, 0):             # todas referenciadas
        memoria.acceder_memoria(1, direccion)
    # La manecilla limpia los bits de 0, 1 y 2 y vuelve a la 0: sale la 0
    assert memoria.acceder_memoria(1, 300)["pagina_reemplazada"] == (1, 0)
    memoria.acceder_memoria(1, 100)                # la 1 vuelve a estar referenciada
    # La manecilla está en la 1 (referenciada): segunda oportunidad; sale la 2
    assert memoria.acceder_memoria(1, 400)["pagina_reemplazada"] == (1, 2)


def test_reemplazo_local_no_quita_marcos_a_otro_proceso():
    memoria.registrar_proceso(1, 1000, 2)
    memoria.registrar_proceso(2, 1000, 2)
    memoria.acceder_memoria(2, 0)
    memoria.acceder_memoria(2, 100)
    for direccion in range(0, 1000, 100):          # el 1 recorre sus 10 páginas
        r = memoria.acceder_memoria(1, direccion)
        if r["pagina_reemplazada"] is not None:
            assert r["pagina_reemplazada"][0] == 1
    assert memoria.estado_memoria()["marcos_por_proceso"][2] == 2


def test_sin_marcos_libres_reemplaza_una_pagina_propia():
    """8 marcos y cuotas 6 + 6: el 2 no llega a su cuota, pero no toca al 1."""
    memoria.registrar_proceso(1, 1000, 6)
    memoria.registrar_proceso(2, 1000, 6)
    for direccion in range(0, 600, 100):           # el 1 ocupa 6 marcos
        memoria.acceder_memoria(1, direccion)
    for direccion in (0, 100):                     # 6 + 2 = 8: no quedan libres
        memoria.acceder_memoria(2, direccion)
    r = memoria.acceder_memoria(2, 200)
    assert r["pagina_reemplazada"][0] == 2         # local: una página suya
    assert memoria.estado_memoria()["marcos_por_proceso"] == {1: 6, 2: 2}


def test_sin_paginas_ni_marcos_libres_toma_un_marco_del_que_mas_tiene():
    """Única excepción al reemplazo local: sin ninguna página no podría avanzar."""
    memoria.registrar_proceso(1, 1000, 8)
    memoria.registrar_proceso(2, 1000, 2)
    for direccion in range(0, 800, 100):           # el 1 ocupa los 8 marcos
        memoria.acceder_memoria(1, direccion)
    r = memoria.acceder_memoria(2, 0)
    assert r["fallo_pagina"] is True
    assert r["pagina_reemplazada"][0] == 1
    assert memoria.estado_memoria()["marcos_por_proceso"] == {1: 7, 2: 1}


def test_escritura_de_pagina_modificada_va_al_swap():
    memoria.registrar_proceso(1, 1000, 1)
    memoria.acceder_memoria(1, 0, escritura=True)
    memoria.acceder_memoria(1, 100)                # expulsa la 0, que estaba sucia
    memoria.acceder_memoria(1, 200)                # expulsa la 1, limpia
    m = memoria.metricas_memoria()
    assert m["reemplazos"] == 2
    assert m["escrituras_a_swap"] == 1


# ------------------------------------------------------- liberar y estado
def test_liberar_memoria_devuelve_marcos_y_los_deja_libres():
    memoria.registrar_proceso(1, 1000, 4)
    for direccion in (0, 100, 200):
        memoria.acceder_memoria(1, direccion)
    assert memoria.liberar_memoria(1) == 3
    assert memoria.estado_memoria()["marcos_libres"] == 8
    assert memoria.liberar_memoria(1) == 0         # ya no tiene nada


def test_liberar_pid_desconocido_devuelve_cero():
    assert memoria.liberar_memoria(123) == 0


def test_estado_memoria_claves_y_fragmentacion_interna():
    memoria.registrar_proceso(1, 250, 4)           # 3 páginas = 300 B: sobran 50
    memoria.registrar_proceso(2, 1000, 4)          # 10 páginas exactas: sobran 0
    memoria.registrar_proceso(3, 120, 4)           # 2 páginas = 200 B: sobran 80
    memoria.acceder_memoria(1, 0)
    estado = memoria.estado_memoria()
    assert set(estado) == {"marcos_totales", "marcos_libres", "marcos_por_proceso",
                           "fragmentacion_interna_bytes"}
    assert estado["fragmentacion_interna_bytes"] == 50 + 0 + 80   # suma de todos
    assert estado["marcos_libres"] == 7
    assert estado["marcos_por_proceso"] == {1: 1, 2: 0, 3: 0}
    memoria.liberar_memoria(3)
    assert memoria.estado_memoria()["fragmentacion_interna_bytes"] == 50


def test_estado_memoria_es_copia():
    memoria.registrar_proceso(1, 300, 2)
    memoria.estado_memoria()["marcos_por_proceso"][1] = 99
    assert memoria.estado_memoria()["marcos_por_proceso"][1] == 0


def test_metricas_claves_y_tasa():
    memoria.registrar_proceso(1, 1000, 4)
    for direccion in (0, 0, 0, 100):               # 2 fallos de 4 accesos
        memoria.acceder_memoria(1, direccion)
    m = memoria.metricas_memoria()
    assert set(m) == {"accesos", "fallos_pagina", "tasa_fallos", "reemplazos", "escrituras_a_swap"}
    assert (m["accesos"], m["fallos_pagina"], m["tasa_fallos"]) == (4, 2, 0.5)


def test_metricas_sin_accesos_no_fallan():
    assert memoria.metricas_memoria()["tasa_fallos"] == 0.0


def test_reiniciar_deja_todo_en_cero():
    memoria.registrar_proceso(1, 1000, 4)
    memoria.acceder_memoria(1, 0)
    memoria.reiniciar({"marcos_fisicos": 16, "tam_pagina": 256})
    assert memoria.estado_memoria()["marcos_totales"] == 16
    assert memoria.estado_memoria()["marcos_libres"] == 16
    assert memoria.metricas_memoria()["accesos"] == 0


# -------------------------------------------------------- hiperpaginación
def test_hiperpaginacion_con_muchos_fallos_seguidos():
    memoria.registrar_proceso(1, 10_000, 1)        # cuota 1: cada página nueva es un fallo
    for direccion in range(0, 3200, 100):
        memoria.acceder_memoria(1, direccion)
    assert memoria.detectar_hiperpaginacion() is True


def test_sin_hiperpaginacion_con_buena_localidad():
    memoria.registrar_proceso(1, 1000, 4)
    for _ in range(40):
        memoria.acceder_memoria(1, 0)
    assert memoria.detectar_hiperpaginacion() is False


def test_politica_reemplazo_devuelve_texto():
    assert "Reloj" in memoria.politica_reemplazo()


# ------------------------------------- ejemplos de la guía conceptual (5.7)
def contar_fallos(secuencia: list, marcos: int, politica: str) -> int:
    """Un proceso con cuota = marcos y páginas de 1 byte: dirección = página."""
    memoria._fijar_politica(politica)
    memoria.reiniciar({"marcos_fisicos": marcos, "tam_pagina": 1})
    memoria.registrar_proceso(1, 10, marcos)
    for pagina in secuencia:
        memoria.acceder_memoria(1, pagina)
    return memoria.metricas_memoria()["fallos_pagina"]


def test_ejemplo_del_reloj_paso_a_paso_de_la_guia():
    """3 marcos, accesos 1, 2, 3, 1, 4, 5: el 4 saca al 1 y el 5 saca al 2."""
    memoria.reiniciar({"marcos_fisicos": 3, "tam_pagina": 1})
    memoria.registrar_proceso(1, 10, 3)
    for pagina in (1, 2, 3, 1):
        memoria.acceder_memoria(1, pagina)
    assert memoria.acceder_memoria(1, 4)["pagina_reemplazada"] == (1, 1)
    assert memoria.acceder_memoria(1, 5)["pagina_reemplazada"] == (1, 2)
    tabla = memoria.tabla_paginas(1)
    assert {p for p, e in tabla.items() if e["presente"]} == {3, 4, 5}


@pytest.mark.parametrize("politica, fallos", [("LRU", 12), ("RELOJ", 14), ("FIFO", 15)])
def test_secuencia_clasica_de_20_accesos_con_3_marcos(politica, fallos):
    secuencia = [7, 0, 1, 2, 0, 3, 0, 4, 2, 3, 0, 3, 2, 1, 2, 0, 1, 7, 0, 1]
    assert contar_fallos(secuencia, 3, politica) == fallos


@pytest.mark.parametrize("politica, con_3, con_4", [("FIFO", 9, 10), ("LRU", 10, 8), ("RELOJ", 9, 10)])
def test_anomalia_de_belady(politica, con_3, con_4):
    secuencia = [1, 2, 3, 4, 1, 2, 5, 1, 2, 3, 4, 5]
    assert contar_fallos(secuencia, 3, politica) == con_3
    assert contar_fallos(secuencia, 4, politica) == con_4
