"""Planificación de E/S de disco y caché de bloques.

Prototipo 1: disco simple con política FCFS.
Este módulo NO importa `procesos` ni `kernel`: solo devuelve PIDs.
El kernel pregunta (avanzar_tick) y `procesos` cambia los estados.
"""
import itertools

from minidc.errores import ErrorSistema

# ---------------------------------------------------------------- estado
_bloques_totales = 200
_cache_capacidad = 8
_cabezal = 0
_cola = []              # solicitudes pendientes: {"id", "pid", "bloque", "operacion"}
_en_servicio = None     # solicitud atendiéndose, con "restante" (ticks)
_contador_ids = itertools.count(1)
_atendidas = 0
_desplazamiento = 0


def reiniciar(config: dict) -> None:
    """Deja el disco como nuevo. Lo llama kernel.iniciar_sistema."""

    global _bloques_totales, _cache_capacidad, _cabezal, _cola
    global _en_servicio, _contador_ids, _atendidas, _desplazamiento
    _bloques_totales = config.get("bloques_disco", 200)
    _cache_capacidad = config.get("cache_bloques", 8)
    _cabezal = 0
    _cola = []
    _en_servicio = None
    _contador_ids = itertools.count(1)
    _atendidas = 0
    _desplazamiento = 0


# ------------------------------------------------- política (intercambiable)
def _elegir_siguiente(cola: list, cabezal: int) -> int:
    """Devuelve el ÍNDICE de la solicitud a atender. FCFS: la más antigua.

    En el Prototipo 2 solo se cambia esta función (SSTF, C-LOOK...).
    """

    return 0


def _tiempo_servicio(cabezal: int, bloque: int) -> int:
    """Fórmula del enunciado."""

    return 1 + abs(cabezal - bloque) // 10


def _orden_previsto() -> list:
    """Bloques pendientes en el orden en que se atenderían (sin modificar nada)."""

    copia = list(_cola)
    pos = _cabezal
    orden = []
    while copia:
        sol = copia.pop(_elegir_siguiente(copia, pos))
        orden.append(sol["bloque"])
        pos = sol["bloque"]
    return orden


def _iniciar_servicio() -> None:
    """Toma la siguiente solicitud y mueve el cabezal hasta su bloque."""

    global _en_servicio, _cabezal, _desplazamiento
    sol = _cola.pop(_elegir_siguiente(_cola, _cabezal))
    sol["restante"] = _tiempo_servicio(_cabezal, sol["bloque"])
    _desplazamiento += abs(_cabezal - sol["bloque"])
    _cabezal = sol["bloque"]
    _en_servicio = sol


# ---------------------------------------------------- funciones internas
def avanzar_tick() -> list:
    """Avanza 1 tick el disco. Devuelve los PID cuya E/S terminó en este tick."""

    global _en_servicio, _atendidas
    if _en_servicio is None and _cola:
        _iniciar_servicio()
    if _en_servicio is None:
        return []
    _en_servicio["restante"] -= 1
    if _en_servicio["restante"] > 0:
        return []
    pid = _en_servicio["pid"]
    _en_servicio = None
    _atendidas += 1
    return [pid]


def cancelar_solicitudes(pid: int) -> int:
    """Quita las solicitudes de un proceso (terminó o fue eliminado)."""

    global _cola, _en_servicio
    antes = len(_cola)
    _cola = [s for s in _cola if s["pid"] != pid]
    cancelados = antes - len(_cola)
    if _en_servicio is not None and _en_servicio["pid"] == pid:
        _en_servicio = None     # el cabezal ya se movió: no se devuelve
        cancelados += 1
    return cancelados


# ------------------------------------------------- funciones del enunciado
def encolar_solicitud_disco(pid: int, bloque: int, operacion: str) -> int:
    """Encola una solicitud de disco (``operacion``: ``"L"`` o ``"E"``) y devuelve su ID."""

    if operacion not in ("L", "E"):
        raise ErrorSistema(f"Operación de disco inválida: {operacion!r}")
    if not 0 <= bloque < _bloques_totales:
        raise ErrorSistema(f"Bloque {bloque} fuera del disco (0..{_bloques_totales - 1})")
    id_solicitud = next(_contador_ids)
    _cola.append({"id": id_solicitud, "pid": pid, "bloque": bloque, "operacion": operacion})
    return id_solicitud


def procesar_disco() -> list:
    """Atiende todas las solicitudes pendientes y devuelve el orden de bloques atendidos.

    Es una función de medición/prueba: no consume ticks del reloj ni libera
    procesos. Los procesos solo se liberan por avanzar_tick().
    """

    global _en_servicio, _atendidas
    orden = []
    if _en_servicio is not None:        # primero termina la que estaba en curso
        orden.append(_en_servicio["bloque"])
        _en_servicio = None
        _atendidas += 1
    while _cola:
        _iniciar_servicio()
        orden.append(_en_servicio["bloque"])
        _en_servicio = None
        _atendidas += 1
    return orden


def cola_disco() -> list:
    """Devuelve los bloques pendientes en el orden de atención previsto."""

    return _orden_previsto()


def metricas_disco() -> dict:
    """Devuelve: solicitudes_atendidas, desplazamiento_total, posicion_cabezal."""

    return {
        "solicitudes_atendidas": _atendidas,
        "desplazamiento_total": _desplazamiento,
        "posicion_cabezal": _cabezal,
    }


def info_cache() -> dict:
    """Devuelve: capacidad_bloques, aciertos, fallos, tasa_aciertos.

    Prototipo 1: la caché aún no se implementa (llega en el Prototipo 2).
    """

    return {
        "capacidad_bloques": _cache_capacidad,
        "aciertos": 0,
        "fallos": 0,
        "tasa_aciertos": 0.0,
    }


def politica_disco() -> str:
    """Devuelve el nombre de la política de planificación de disco elegida."""
    
    return "FCFS"


reiniciar({})   # estado válido desde el import
