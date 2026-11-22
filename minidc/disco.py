"""Planificación de E/S de disco y caché de bloques.

Prototipo 2: política C-LOOK y caché LRU de lectura.

- C-LOOK: el cabezal atiende las solicitudes en orden creciente de bloque desde
  su posición. Cuando ya no quedan bloques por delante, salta al bloque más
  bajo pendiente y vuelve a subir. Reduce el desplazamiento frente a FCFS.
  Las solicitudes que llegan al bloque donde ya está el cabezal esperan a la
  siguiente pasada; así ninguna solicitud queda esperando para siempre (RD1).
- Caché LRU: guarda los últimos ``cache_bloques`` bloques leídos o escritos.
  Una lectura de un bloque en caché no mueve el cabezal y termina en 1 tick.

Este módulo NO importa `procesos` ni `kernel`: solo devuelve PIDs.
El kernel pregunta (avanzar_tick) y `procesos` cambia los estados.
"""
from collections import OrderedDict
import itertools

from minidc.errores import ErrorSistema

# ------------------------------------------------------------ parámetros
_POLITICA = "C-LOOK"     # política activa: "C-LOOK", "SSTF" o "FCFS"

# ---------------------------------------------------------------- estado
_bloques_totales = 200
_cache_capacidad = 8
_cache = OrderedDict()  # bloque -> None; el primero es el menos usado recientemente
_aciertos = 0
_fallos = 0
_reloj = 0              # ticks del disco: avanza una vez por cada avanzar_tick()
_cabezal = 0
_id_limite = 0          # último id que existía cuando el cabezal llegó a su bloque actual
_ultimo_id = 0          # último id de solicitud entregado
_cola = []              # solicitudes al disco: {"id", "pid", "bloque", "operacion", "llegada"}
_desde_cache = []       # lecturas que acertaron en la caché (no usan el cabezal)
_en_servicio = None     # solicitud atendiéndose, con "restante" (ticks)
_contador_ids = itertools.count(1)
_atendidas = 0
_desplazamiento = 0
_espera_maxima = 0
_espera_total = 0
_esperas_medidas = 0


def reiniciar(config: dict) -> None:
    """Deja el disco como nuevo. Lo llama kernel.iniciar_sistema."""

    global _bloques_totales, _cache_capacidad, _cache, _aciertos, _fallos, _reloj
    global _cabezal, _id_limite, _ultimo_id, _cola, _desde_cache, _en_servicio
    global _contador_ids, _atendidas
    global _desplazamiento, _espera_maxima, _espera_total, _esperas_medidas
    _bloques_totales = int(config.get("bloques_disco", 200))
    _cache_capacidad = int(config.get("cache_bloques", 8))
    if _bloques_totales < 1 or _cache_capacidad < 0:
        raise ErrorSistema("bloques_disco debe ser >= 1 y cache_bloques >= 0")
    _cache = OrderedDict()
    _aciertos = 0
    _fallos = 0
    _reloj = 0
    _cabezal = 0
    _id_limite = 0
    _ultimo_id = 0
    _cola = []
    _desde_cache = []
    _en_servicio = None
    _contador_ids = itertools.count(1)
    _atendidas = 0
    _desplazamiento = 0
    _espera_maxima = 0
    _espera_total = 0
    _esperas_medidas = 0


# ------------------------------------------------- políticas (intercambiables)
def _clook(cola: list, cabezal: int, id_limite: float) -> int:
    """C-LOOK: el menor bloque mayor o igual al cabezal; si no hay, el más bajo de todos.

    Detalle anti-inanición: en el MISMO bloque del cabezal solo cuentan como
    "por delante" las solicitudes que ya existían cuando el cabezal llegó
    (``id <= id_limite``). Las que llegan después esperan a la siguiente pasada;
    si no, un flujo constante a ese bloque dejaría esperando a las demás.
    """

    por_delante = [i for i, s in enumerate(cola)
                   if s["bloque"] > cabezal or (s["bloque"] == cabezal and s["id"] <= id_limite)]
    candidatos = por_delante if por_delante else range(len(cola))
    # A igual bloque, la más antigua (menor id)
    return min(candidatos, key=lambda i: (cola[i]["bloque"], cola[i]["id"]))


def _sstf(cola: list, cabezal: int, id_limite: float) -> int:
    """SSTF: la solicitud más cercana al cabezal, hacia cualquier lado."""

    return min(range(len(cola)), key=lambda i: (abs(cola[i]["bloque"] - cabezal), cola[i]["id"]))


def _fcfs(cola: list, cabezal: int, id_limite: float) -> int:
    """FCFS: la más antigua."""

    return 0


_POLITICAS = {"C-LOOK": _clook, "SSTF": _sstf, "FCFS": _fcfs}


def _fijar_politica(nombre: str) -> None:
    """Cambia la política activa. Solo se usa en los experimentos del informe."""

    global _POLITICA
    if nombre not in _POLITICAS:
        raise ErrorSistema(f"Política de disco desconocida: {nombre!r}")
    _POLITICA = nombre


def _elegir_siguiente(cola: list, cabezal: int, id_limite: float = float("inf")) -> int:
    """Devuelve el ÍNDICE de la solicitud a atender según la política activa.

    Aquí se cambia la política (C-LOOK, SSTF o FCFS). ``id_limite`` solo lo usa
    C-LOOK (ver ``_clook``).
    """

    return _POLITICAS[_POLITICA](cola, cabezal, id_limite)


def _tiempo_servicio(cabezal: int, bloque: int) -> int:
    """Fórmula del enunciado."""

    return 1 + abs(cabezal - bloque) // 10


def _orden_previsto() -> list:
    """Bloques pendientes en el orden en que se atenderían (sin modificar nada).

    Primero las lecturas servidas por la caché y luego las del cabezal.
    """

    copia = list(_cola)
    pos, limite = _cabezal, _id_limite
    orden = [s["bloque"] for s in _desde_cache]
    while copia:
        sol = copia.pop(_elegir_siguiente(copia, pos, limite))
        orden.append(sol["bloque"])
        if sol["bloque"] != pos:            # al llegar a otro bloque, todas ya existían
            pos, limite = sol["bloque"], float("inf")
    return orden


def _iniciar_servicio() -> None:
    """Toma la siguiente solicitud y mueve el cabezal hasta su bloque."""

    global _en_servicio, _cabezal, _desplazamiento, _id_limite
    sol = _cola.pop(_elegir_siguiente(_cola, _cabezal, _id_limite))
    sol["restante"] = _tiempo_servicio(_cabezal, sol["bloque"])
    _desplazamiento += abs(_cabezal - sol["bloque"])
    if sol["bloque"] != _cabezal:           # llega a otro bloque: anota qué ya existía
        _id_limite = _ultimo_id
    _cabezal = sol["bloque"]
    _en_servicio = sol


def _guardar_en_cache(bloque: int) -> None:
    """Pone ``bloque`` como el más reciente; si no cabe, saca el menos usado (LRU)."""

    if _cache_capacidad <= 0:
        return
    _cache[bloque] = None
    _cache.move_to_end(bloque)
    while len(_cache) > _cache_capacidad:
        _cache.popitem(last=False)


def _terminar(sol: dict) -> None:
    """Registra una solicitud terminada: métricas de espera y caché."""

    global _atendidas, _espera_maxima, _espera_total, _esperas_medidas
    _atendidas += 1
    espera = _reloj - sol["llegada"]
    _espera_maxima = max(_espera_maxima, espera)
    _espera_total += espera
    _esperas_medidas += 1
    _guardar_en_cache(sol["bloque"])


# ---------------------------------------------------- funciones internas
def avanzar_tick() -> list:
    """Avanza 1 tick el disco. Devuelve los PID cuya E/S terminó en este tick.

    Las lecturas servidas por la caché terminan en el primer tick después de
    pedirse; en paralelo, el cabezal sigue con su solicitud en servicio.
    """

    global _en_servicio, _desde_cache, _reloj
    _reloj += 1
    terminados = []
    for sol in _desde_cache:
        _terminar(sol)
        terminados.append(sol["pid"])
    _desde_cache = []

    if _en_servicio is None and _cola:
        _iniciar_servicio()
    if _en_servicio is not None:
        _en_servicio["restante"] -= 1
        if _en_servicio["restante"] <= 0:
            _terminar(_en_servicio)
            terminados.append(_en_servicio["pid"])
            _en_servicio = None
    return terminados


def cancelar_solicitudes(pid: int) -> int:
    """Quita las solicitudes de un proceso (terminó o fue eliminado)."""

    global _cola, _desde_cache, _en_servicio
    antes = len(_cola) + len(_desde_cache)
    _cola = [s for s in _cola if s["pid"] != pid]
    _desde_cache = [s for s in _desde_cache if s["pid"] != pid]
    cancelados = antes - len(_cola) - len(_desde_cache)
    if _en_servicio is not None and _en_servicio["pid"] == pid:
        _en_servicio = None     # el cabezal ya se movió: no se devuelve
        cancelados += 1
    return cancelados


def estadisticas_espera() -> dict:
    """Espera de las solicitudes terminadas, en ticks: espera_maxima y espera_promedio.

    La espera va desde que se encola la solicitud hasta que termina. Solo la
    miden los ticks del disco (avanzar_tick); procesar_disco no consume ticks.
    """

    return {
        "espera_maxima": _espera_maxima,
        "espera_promedio": _espera_total / _esperas_medidas if _esperas_medidas else 0.0,
    }


# ------------------------------------------------- funciones del enunciado
def encolar_solicitud_disco(pid: int, bloque: int, operacion: str) -> int:
    """Encola una solicitud de disco (``operacion``: ``"L"`` o ``"E"``) y devuelve su ID.

    Una lectura de un bloque que está en la caché es un acierto: no pasa por el
    cabezal. Las escrituras siempre van al disco (escritura directa).
    """

    global _aciertos, _fallos, _ultimo_id
    if operacion not in ("L", "E"):
        raise ErrorSistema(f"Operación de disco inválida: {operacion!r}")
    if (not isinstance(bloque, int) or isinstance(bloque, bool)
            or not 0 <= bloque < _bloques_totales):
        raise ErrorSistema(f"Bloque {bloque!r} fuera del disco (0..{_bloques_totales - 1})")
    id_solicitud = next(_contador_ids)
    _ultimo_id = id_solicitud
    sol = {"id": id_solicitud, "pid": pid, "bloque": bloque, "operacion": operacion,
           "llegada": _reloj}
    if operacion == "L":
        if bloque in _cache:
            _aciertos += 1
            _cache.move_to_end(bloque)          # recién usado
            _desde_cache.append(sol)
            return id_solicitud
        _fallos += 1
    _cola.append(sol)
    return id_solicitud


def procesar_disco() -> list:
    """Atiende todas las solicitudes pendientes y devuelve el orden de bloques atendidos.

    Es una función de medición/prueba: no consume ticks del reloj ni libera
    procesos. Los procesos solo se liberan por avanzar_tick().
    """

    global _en_servicio, _desde_cache
    orden = []
    for sol in _desde_cache:            # primero lo que ya estaba en la caché
        orden.append(sol["bloque"])
        _terminar(sol)
    _desde_cache = []
    if _en_servicio is not None:        # luego termina la que estaba en curso
        orden.append(_en_servicio["bloque"])
        _terminar(_en_servicio)
        _en_servicio = None
    while _cola:
        _iniciar_servicio()
        orden.append(_en_servicio["bloque"])
        _terminar(_en_servicio)
        _en_servicio = None
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

    Solo cuentan las lecturas: cada lectura es un acierto o un fallo.
    """

    consultas = _aciertos + _fallos
    return {
        "capacidad_bloques": _cache_capacidad,
        "aciertos": _aciertos,
        "fallos": _fallos,
        "tasa_aciertos": _aciertos / consultas if consultas else 0.0,
    }


def politica_disco() -> str:
    """Devuelve el nombre de la política de planificación de disco elegida."""

    return _POLITICA


reiniciar({})   # estado válido desde el import
