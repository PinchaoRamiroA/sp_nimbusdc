"""Núcleo principal y reloj discreto del sistema operativo simulado NimbusDC."""
import json
import os

from minidc import disco, procesos
from minidc.errores import ErrorNoExiste, ErrorSistema

# ---------------------------------------------------------------- estado interno
_reloj = 0
_config = {}
_llegadas_pendientes = []


def iniciar_sistema(config: dict) -> None:
    """Reinicia todo el estado del sistema con la configuración dada.

    Claves esperadas en ``config``:
    ``num_cpus``, ``marcos_fisicos``, ``tam_pagina``, ``bloques_disco``,
    ``tam_bloque``, ``cache_bloques``.
    """
    global _reloj, _config, _llegadas_pendientes
    _config = dict(config)
    _reloj = 0
    _llegadas_pendientes = []
    disco.reiniciar(_config)
    procesos.reiniciar(_config)


def apagar_sistema() -> dict:
    """Finaliza la ejecución simulada y devuelve un resumen final del sistema."""
    metricas = procesos.metricas_planificacion()
    metricas_d = disco.metricas_disco()
    activos = len([p for p in procesos.listar_procesos() if p["estado"] != "TERMINADO"])
    return {
        "reloj": _reloj,
        "utilizacion_cpu": metricas["utilizacion_cpu"],
        "metricas_planificacion": metricas,
        "metricas_disco": metricas_d,
        "procesos_activos": activos,
        "procesos_terminados": metricas["procesos_terminados"],
    }


def tick() -> None:
    """Avanza el reloj en 1 tick y ejecuta un ciclo completo del núcleo.

    Orden obligatorio por tick:
    1. Llegada de procesos del escenario.
    2. Atención de la E/S terminada (interrupción).
    3. Ejecución de 1 tick por cada CPU.
    4. Actualización de métricas.
    """
    global _reloj, _llegadas_pendientes
    _reloj += 1
    procesos.fijar_reloj(_reloj)

    # 1. Llegada de procesos del escenario
    restantes = []
    for llegada in _llegadas_pendientes:
        if llegada.get("tick", 0) <= _reloj:
            procesos.crear_proceso(
                nombre=llegada["nombre"],
                usuario=llegada.get("usuario", "admin"),
                programa=llegada["programa"],
                memoria_bytes=llegada.get("memoria_bytes", 4096),
                cuota_marcos=llegada.get("cuota_marcos", 4),
                prioridad=llegada.get("prioridad", 0),
            )
        else:
            restantes.append(llegada)
    _llegadas_pendientes = restantes

    # 2. Atención de la E/S terminada (interrupción)
    pids_es = disco.avanzar_tick()
    for pid in pids_es:
        procesos.despertar_proceso(pid)

    # 3. Ejecución de 1 tick por cada CPU
    procesos.planificar_y_ejecutar_cpu(_reloj)

    # 4. Actualización de métricas y envejecimiento
    procesos.actualizar_metricas_espera()


def ejecutar_ticks(n: int) -> None:
    """Ejecuta ``n`` ticks consecutivos del reloj discreto."""
    for _ in range(n):
        tick()


def reloj_actual() -> int:
    """Devuelve el valor actual del reloj discreto."""
    return _reloj


def cargar_escenario(ruta_json: str) -> None:
    """Carga un escenario JSON, inicializa el sistema, usuarios, semáforos y llegadas."""
    global _llegadas_pendientes
    if not os.path.isfile(ruta_json):
        raise ErrorNoExiste(f"Archivo de escenario no encontrado: {ruta_json}")

    try:
        with open(ruta_json, "r", encoding="utf-8") as f:
            datos = json.load(f)
    except Exception as e:
        raise ErrorSistema(f"Error al parsear el archivo JSON: {e}")

    if not isinstance(datos, dict):
        raise ErrorSistema("El contenido del archivo JSON debe ser un objeto/diccionario")

    config = dict(datos.get("config", {}))
    for clave in ("num_cpus", "marcos_fisicos", "tam_pagina", "bloques_disco", "tam_bloque", "cache_bloques"):
        if clave in datos and clave not in config:
            config[clave] = datos[clave]

    iniciar_sistema(config)

    # Inicialización de usuarios y semáforos si están presentes
    for u in datos.get("usuarios", []):
        try:
            from minidc import archivos
            archivos.crear_usuario(u["nombre"], u.get("grupo", "usuarios"))
        except (ErrorSistema, NotImplementedError, AttributeError):
            pass

    for s in datos.get("semaforos", []):
        try:
            from minidc import sincronizacion
            sincronizacion.crear_semaforo(s["nombre"], s.get("valor_inicial", 1))
        except (ErrorSistema, NotImplementedError, AttributeError):
            pass

    # Procesar llegadas
    llegadas = datos.get("llegadas", datos.get("procesos", []))
    _llegadas_pendientes = []
    for item in llegadas:
        tick_prog = item.get("tick", 0)
        if tick_prog <= 0:
            procesos.crear_proceso(
                nombre=item["nombre"],
                usuario=item.get("usuario", "admin"),
                programa=item["programa"],
                memoria_bytes=item.get("memoria_bytes", 4096),
                cuota_marcos=item.get("cuota_marcos", 4),
                prioridad=item.get("prioridad", 0),
            )
        else:
            _llegadas_pendientes.append(item)


def resumen_sistema() -> dict:
    """Devuelve resumen con claves: ``reloj``, ``procesos_activos``, ``marcos_libres``, ``bloques_libres``."""
    activos = len([p for p in procesos.listar_procesos() if p["estado"] != "TERMINADO"])
    return {
        "reloj": _reloj,
        "procesos_activos": activos,
        "marcos_libres": _config.get("marcos_fisicos", 64),
        "bloques_libres": _config.get("bloques_disco", 200),
    }


iniciar_sistema({})
