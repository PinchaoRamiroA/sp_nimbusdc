"""Núcleo principal y reloj discreto del sistema operativo simulado NimbusDC."""
import json
import os

from minidc import archivos, disco, procesos
from minidc.errores import ErrorNoExiste, ErrorSistema

# ---------------------------------------------------------------- estado interno
_reloj = 0
_config = {}
_llegadas_pendientes = []
_catalogo = {}


def iniciar_sistema(config: dict) -> None:
    """Reinicia todo el estado del sistema con la configuración dada.

    Claves esperadas en ``config``:
    ``num_cpus``, ``marcos_fisicos``, ``tam_pagina``, ``bloques_disco``,
    ``tam_bloque``, ``cache_bloques``.
    """
    global _reloj, _config, _llegadas_pendientes, _catalogo
    _config = dict(config)
    _reloj = 0
    _llegadas_pendientes = []
    _catalogo = {}
    disco.reiniciar(_config)
    procesos.reiniciar(_config)
    try:
        from minidc import memoria
        if hasattr(memoria, "reiniciar"):
            memoria.reiniciar(_config)
    except Exception:
        pass
    try:
        from minidc import archivos
        archivos.reiniciar(_config)
    except Exception:
        pass


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

    # 2. Atención de la E/S terminada (interrupción) y fallos de memoria
    pids_es = disco.avanzar_tick()
    for pid in pids_es:
        procesos.despertar_proceso(pid)

    procesos.avanzar_esperas_memoria()

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

    global _catalogo
    _catalogo = dict(datos.get("catalogo", {}))

    # Inicialización de usuarios y semáforos si están presentes
    for u in datos.get("usuarios", []):
        try:
            from minidc import archivos
            if isinstance(u, dict):
                archivos.crear_usuario(u["nombre"], u.get("grupo", "usuarios"))
            elif isinstance(u, str):
                archivos.crear_usuario(u, "usuarios")
        except (ErrorSistema, NotImplementedError, AttributeError):
            pass

    sem_data = datos.get("semaforos", {})
    if isinstance(sem_data, dict):
        for s_nom, s_val in sem_data.items():
            try:
                from minidc import sincronizacion
                sincronizacion.crear_semaforo(s_nom, s_val)
            except (ErrorSistema, NotImplementedError, AttributeError):
                pass
    elif isinstance(sem_data, list):
        for s in sem_data:
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
        prog_raw = item.get("programa")
        nom_raw = item.get("nombre")

        if isinstance(prog_raw, str) and prog_raw in _catalogo:
            serv = _catalogo[prog_raw]
            nom = nom_raw if nom_raw is not None else prog_raw
            prog = serv["programa"]
            mem_b = item.get("memoria_bytes", serv.get("memoria_bytes", 4096))
            c_marcos = item.get("cuota_marcos", serv.get("cuota_marcos", 4))
            prio = item.get("prioridad", serv.get("prioridad", 0))
        elif isinstance(prog_raw, list):
            nom = nom_raw if nom_raw is not None else "proceso"
            prog = prog_raw
            mem_b = item.get("memoria_bytes", 4096)
            c_marcos = item.get("cuota_marcos", 4)
            prio = item.get("prioridad", 0)
        else:
            nom = nom_raw if nom_raw is not None else str(prog_raw)
            prog = []
            mem_b = item.get("memoria_bytes", 4096)
            c_marcos = item.get("cuota_marcos", 4)
            prio = item.get("prioridad", 0)

        llegada_dict = {
            "tick": tick_prog,
            "nombre": nom,
            "usuario": item.get("usuario", "admin"),
            "programa": prog,
            "memoria_bytes": mem_b,
            "cuota_marcos": c_marcos,
            "prioridad": prio,
        }

        if tick_prog <= 0:
            procesos.crear_proceso(
                nombre=llegada_dict["nombre"],
                usuario=llegada_dict["usuario"],
                programa=llegada_dict["programa"],
                memoria_bytes=llegada_dict["memoria_bytes"],
                cuota_marcos=llegada_dict["cuota_marcos"],
                prioridad=llegada_dict["prioridad"],
            )
        else:
            _llegadas_pendientes.append(llegada_dict)


def obtener_catalogo() -> dict:
    """Devuelve una copia del catálogo de servicios cargado en el escenario."""
    return dict(_catalogo)


def resumen_sistema() -> dict:
    """Devuelve resumen con claves: ``reloj``, ``procesos_activos``, ``marcos_libres``, ``bloques_libres``."""
    activos = len([p for p in procesos.listar_procesos() if p["estado"] != "TERMINADO"])
    marcos_libres = _config.get("marcos_fisicos", 64)
    try:
        from minidc import memoria
        est_mem = memoria.estado_memoria()
        if isinstance(est_mem, dict) and "marcos_libres" in est_mem:
            marcos_libres = est_mem["marcos_libres"]
    except (ErrorSistema, NotImplementedError, AttributeError):
        pass

    return {
        "reloj": _reloj,
        "procesos_activos": activos,
        "marcos_libres": marcos_libres,
        "bloques_libres": archivos.fs_estado_disco()["bloques_libres"],
    }


iniciar_sistema({})
