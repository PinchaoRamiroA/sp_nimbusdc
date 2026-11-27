"""Gestión de procesos, hilos y planificación de CPU.

Implementa un planificador de colas multinivel con retroalimentación (MLFQ)
con 3 niveles de prioridad (0: alta, 1: media, 2: baja), turno rotativo con un
quantum de 2 ticks dentro de cada cola y envejecimiento (aging) para evitar
inanición y satisfacer RP1 y RP2.
Soporta gestión y despacho de hilos simulados, instrucción MEM y fallos de página
deterministas de 5 ticks, y manejo robusto de protección de memoria (RM3).
Este módulo no debe importar a `kernel.py`.
"""
from collections import deque
import itertools

from minidc import disco
from minidc.errores import ErrorMemoria, ErrorNoExiste, ErrorSincronizacion, ErrorSistema

# ---------------------------------------------------------------- estado interno
_procesos = {}
_colas = {0: deque(), 1: deque(), 2: deque()}
_en_ejecucion = {}
_num_cpus = 1
_reloj_actual = 0
_contador_pids = itertools.count(1)
_cambios_contexto = 0
_pids_ejecutados_tick = set()
_espera_semaforos = {}

_QUANTUM = 2                    # ticks seguidos de CPU antes de ceder el turno a otro de la misma cola
_UMBRAL_ENVEJECIMIENTO = 30     # ticks esperando en LISTO para subir un nivel de prioridad


def reiniciar(config: dict | None = None) -> None:
    """Reinicia el estado del subsistema de procesos."""
    global _procesos, _colas, _en_ejecucion, _num_cpus, _reloj_actual
    global _contador_pids, _cambios_contexto, _pids_ejecutados_tick, _espera_semaforos
    if config is None:
        config = {}
    _procesos = {}
    _colas = {0: deque(), 1: deque(), 2: deque()}
    _en_ejecucion = {}
    _num_cpus = max(1, int(config.get("num_cpus", 1)))
    _reloj_actual = 0
    _contador_pids = itertools.count(1)
    _cambios_contexto = 0
    _pids_ejecutados_tick = set()
    _espera_semaforos = {}


def fijar_reloj(reloj: int) -> None:
    """Actualiza la referencia de reloj actual sincronizada por el kernel."""
    global _reloj_actual
    _reloj_actual = reloj


def crear_proceso(
    nombre: str,
    usuario: str,
    programa: list,
    memoria_bytes: int = 4096,
    cuota_marcos: int = 4,
    prioridad: int = 0,
) -> int:
    """Crea un proceso nuevo y devuelve su PID."""
    pid = next(_contador_pids)
    prio_norm = max(0, min(2, int(prioridad)))
    prog_tuplas = [tuple(inst) if isinstance(inst, (list, tuple)) else inst for inst in programa]

    proceso = {
        "pid": pid,
        "nombre": str(nombre),
        "usuario": str(usuario),
        "programa": prog_tuplas,
        "memoria_bytes": int(memoria_bytes),
        "cuota_marcos": int(cuota_marcos),
        "prioridad": prio_norm,
        "prioridad_original": prio_norm,
        "estado": "LISTO",
        "pc": 0,
        "restante_instruccion": None,
        "tick_llegada": _reloj_actual,
        "primer_inicio": None,
        "tick_fin": None,
        "cpu_usada": 0,
        "tiempo_espera": 0,
        "espera_consecutiva": 0,
        "ticks_turno": 0,
        "tiempo_bloqueado": 0,
        "espera_fallo_memoria": None,
        "semaforos_adquiridos": [],
        "mutexes_adquiridos": set(),
        "espera_semaforo": None,
        "hilos": [],
        "siguiente_tid": 1,
        "ultimo_tid_ejecutado": 0,
        "suspendido": False,     # lo suspende el control de memoria ante la hiperpaginación (RM2)
    }
    _procesos[pid] = proceso
    _colas[prio_norm].append(pid)
    return pid


def crear_hilo(pid: int, programa: list) -> int:
    """Crea un hilo asociado al proceso ``pid`` y devuelve su TID creciente único por proceso."""
    if pid not in _procesos:
        raise ErrorNoExiste(f"Proceso con PID {pid} no existe")
    p = _procesos[pid]
    prog_tuplas = [tuple(inst) if isinstance(inst, (list, tuple)) else inst for inst in programa]
    tid = p.get("siguiente_tid", len(p.get("hilos", [])) + 1)
    p["siguiente_tid"] = tid + 1
    hilo = {
        "tid": tid,
        "pid": pid,
        "programa": prog_tuplas,
        "pc": 0,
        "estado": "LISTO",
        "restante_instruccion": None,
        "cpu_usada": 0,
        "tiempo_bloqueado": 0,
        "espera_fallo_memoria": None,
        "espera_semaforo": None,
    }
    p.setdefault("hilos", []).append(hilo)
    return tid


def _despertar_por_semaforo(
    nombre: str,
    pid_despertado: int | None = None,
    tid_despertado: int | None = None,
) -> int | None:
    """Despierta a un proceso o hilo bloqueado en el semáforo ``nombre``.

    Reincorpora el proceso a la cola de listos en MLFQ.
    """
    global _procesos, _colas, _espera_semaforos

    candidato_pid = pid_despertado
    candidato_tid = tid_despertado

    # Si no se pasó un PID específico, consultar la cola interna de espera
    if candidato_pid is None:
        cola_sem = _espera_semaforos.get(nombre)
        while cola_sem:
            item = cola_sem.popleft()
            if item[0] in _procesos and _procesos[item[0]]["estado"] != "TERMINADO":
                candidato_pid, candidato_tid = item
                break
    else:
        # Remover de la cola interna si estaba registrado
        cola_sem = _espera_semaforos.get(nombre)
        if cola_sem:
            for item in list(cola_sem):
                if item[0] == candidato_pid:
                    cola_sem.remove(item)
                    if candidato_tid is None:
                        candidato_tid = item[1]
                    break

    if candidato_pid is None or candidato_pid not in _procesos:
        return None

    p = _procesos[candidato_pid]
    if p["estado"] == "TERMINADO":
        return None

    # Caso 1: Proceso con hilos
    if p.get("hilos"):
        desperto_hilo = False
        for h in p["hilos"]:
            if h["estado"] == "BLOQUEADO" and h.get("espera_semaforo") == nombre:
                if candidato_tid is None or h["tid"] == candidato_tid:
                    h["estado"] = "LISTO"
                    h["espera_semaforo"] = None
                    desperto_hilo = True
                    break

        if desperto_hilo:
            if p["estado"] == "BLOQUEADO":
                p["estado"] = "LISTO"
                p["espera_consecutiva"] = 0
                if p["prioridad"] < p["prioridad_original"]:
                    p["prioridad"] = p["prioridad_original"]
                if candidato_pid not in _colas[p["prioridad"]]:
                    _colas[p["prioridad"]].append(candidato_pid)
            elif p["estado"] == "LISTO":
                if candidato_pid not in _colas[p["prioridad"]]:
                    _colas[p["prioridad"]].append(candidato_pid)

    # Caso 2: Proceso sin hilos
    else:
        if p["estado"] == "BLOQUEADO" and p.get("espera_semaforo") == nombre:
            p["estado"] = "LISTO"
            p["espera_semaforo"] = None
            p["espera_consecutiva"] = 0
            if p["prioridad"] < p["prioridad_original"]:
                p["prioridad"] = p["prioridad_original"]
            if candidato_pid not in _colas[p["prioridad"]]:
                _colas[p["prioridad"]].append(candidato_pid)

    return candidato_pid


def terminar_proceso(pid: int) -> None:
    """Termina el proceso ``pid`` y libera su memoria, semáforos y mutex."""
    if pid not in _procesos:
        raise ErrorNoExiste(f"Proceso con PID {pid} no existe")
    p = _procesos[pid]
    p["estado"] = "TERMINADO"
    if p["tick_fin"] is None:
        p["tick_fin"] = _reloj_actual

    # Terminar todos los hilos del proceso
    for h in p.get("hilos", []):
        h["estado"] = "TERMINADO"

    # Remover de colas de listos
    for cola in _colas.values():
        try:
            cola.remove(pid)
        except ValueError:
            pass

    # Si estaba en ejecución en alguna CPU, liberarla
    for cpu, cur_pid in list(_en_ejecucion.items()):
        if cur_pid == pid:
            _en_ejecucion[cpu] = None

    # Cancelar solicitudes pendientes en el disco
    disco.cancelar_solicitudes(pid)

    # Intentar liberar memoria si el módulo memoria está disponible
    try:
        from minidc import memoria
        memoria.liberar_memoria(pid)
    except (ErrorSistema, NotImplementedError, AttributeError):
        pass

    # Liberar recursos de sincronización (semáforos y mutex) retenidos
    for sem_nom in list(p.get("semaforos_adquiridos", [])):
        try:
            from minidc import sincronizacion
            sincronizacion.semaforo_signal(sem_nom, pid)
        except Exception:
            pass
        _despertar_por_semaforo(sem_nom)
    p["semaforos_adquiridos"] = []

    for mutex_nom in list(p.get("mutexes_adquiridos", set())):
        try:
            from minidc import sincronizacion
            sincronizacion.mutex_unlock(mutex_nom, pid)
        except Exception:
            pass
    p["mutexes_adquiridos"] = set()

    try:
        from minidc import sincronizacion
        if hasattr(sincronizacion, "liberar_recursos"):
            sincronizacion.liberar_recursos(pid)
        elif hasattr(sincronizacion, "liberar_proceso"):
            sincronizacion.liberar_proceso(pid)
    except Exception:
        pass

    p["espera_semaforo"] = None
    for h in p.get("hilos", []):
        h["espera_semaforo"] = None
    for sem_nom, cola_esp in list(_espera_semaforos.items()):
        _espera_semaforos[sem_nom] = deque([item for item in cola_esp if item[0] != pid])


def estado_proceso(pid: int) -> str:
    """Devuelve el estado del proceso: NUEVO, LISTO, EJECUTANDO, BLOQUEADO o TERMINADO."""
    if pid not in _procesos:
        raise ErrorNoExiste(f"Proceso con PID {pid} no existe")
    return _procesos[pid]["estado"]


def listar_procesos() -> list:
    """Lista diccionarios con: pid, nombre, usuario, estado, prioridad, cpu_usada, tiempo_espera."""
    return [
        {
            "pid": p["pid"],
            "nombre": p["nombre"],
            "usuario": p["usuario"],
            "estado": p["estado"],
            "prioridad": p["prioridad"],
            "cpu_usada": p["cpu_usada"],
            "tiempo_espera": p["tiempo_espera"],
            "primer_inicio": p["primer_inicio"],
            "tick_llegada": p["tick_llegada"],
            "tick_fin": p["tick_fin"],
            "hilos": [dict(h) for h in p.get("hilos", [])],
        }
        for p in _procesos.values()
    ]


def cola_listos() -> list:
    """Devuelve los PID en la cola de listos en el orden en que serán atendidos."""
    return list(_colas[0]) + list(_colas[1]) + list(_colas[2])


def proceso_en_ejecucion(cpu: int = 0) -> int | None:
    """Devuelve el PID en ejecución en la CPU indicada, o ``None`` si está libre."""
    return _en_ejecucion.get(cpu)


def puede_suspenderse(pid: int) -> bool:
    """Indica si el control de memoria puede suspender a ``pid`` (reacción a la hiperpaginación, RM2).

    Solo se suspenden procesos sin hilos que no tengan semáforos ni mutex, que
    no esperen un semáforo y que no esperen una E/S de disco (sus páginas
    estarían en uso por la transferencia). Pueden estar LISTO, EJECUTANDO o
    BLOQUEADO por un fallo de página.
    """
    p = _procesos.get(pid)
    if p is None or p["estado"] == "TERMINADO" or p.get("suspendido"):
        return False
    if (p.get("hilos") or p.get("semaforos_adquiridos") or p.get("mutexes_adquiridos")
            or p.get("espera_semaforo") is not None):
        return False
    if p["estado"] == "BLOQUEADO" and p.get("espera_fallo_memoria") is None:
        return False
    return True


def suspender_proceso(pid: int) -> bool:
    """Suspende a ``pid``: queda BLOQUEADO y no vuelve a LISTO hasta ``reanudar_proceso``.

    Si estaba en la cola de listos sale de ella; si estaba en una CPU la libera
    (cuenta un cambio de contexto); si esperaba un fallo de página, la espera
    sigue corriendo. Devuelve False si no se puede suspender (``puede_suspenderse``).
    """
    global _cambios_contexto
    if not puede_suspenderse(pid):
        return False
    p = _procesos[pid]
    if p["estado"] == "LISTO":
        for cola in _colas.values():
            if pid in cola:
                cola.remove(pid)
    elif p["estado"] == "EJECUTANDO":
        for cpu, actual in list(_en_ejecucion.items()):
            if actual == pid:
                _en_ejecucion[cpu] = None
        _cambios_contexto += 1
    p["estado"] = "BLOQUEADO"
    p["suspendido"] = True
    p["espera_consecutiva"] = 0
    return True


def reanudar_proceso(pid: int) -> bool:
    """Quita la suspensión de ``pid``. Si ya no espera nada, vuelve a LISTO.

    Devuelve False si el proceso no estaba suspendido.
    """
    p = _procesos.get(pid)
    if p is None or not p.get("suspendido"):
        return False
    p["suspendido"] = False
    if p["estado"] == "BLOQUEADO" and p.get("espera_fallo_memoria") is None:
        if p["pc"] >= len(p["programa"]):
            terminar_proceso(pid)
        else:
            p["estado"] = "LISTO"
            p["espera_consecutiva"] = 0
            if pid not in _colas[p["prioridad"]]:
                _colas[p["prioridad"]].append(pid)
    return True


def despertar_proceso(pid: int) -> None:
    """Despierta a un proceso que completó su E/S y lo reincorpora a la cola de listos."""
    if pid not in _procesos:
        return
    p = _procesos[pid]
    if p.get("hilos"):
        desperto_alguno = False
        for h in p["hilos"]:
            if (
                h["estado"] == "BLOQUEADO"
                and h.get("espera_fallo_memoria") is None
                and h.get("espera_semaforo") is None
            ):
                if h["pc"] >= len(h["programa"]):
                    h["estado"] = "TERMINADO"
                else:
                    h["estado"] = "LISTO"
                    desperto_alguno = True
        if p["estado"] == "BLOQUEADO" and desperto_alguno:
            p["estado"] = "LISTO"
            p["espera_consecutiva"] = 0
            if pid not in _colas[p["prioridad"]]:
                _colas[p["prioridad"]].append(pid)
    else:
        if (
            p["estado"] == "BLOQUEADO"
            and p.get("espera_fallo_memoria") is None
            and p.get("espera_semaforo") is None
            and not p.get("suspendido")
        ):
            if p["pc"] >= len(p["programa"]):
                terminar_proceso(pid)
            else:
                p["estado"] = "LISTO"
                p["espera_consecutiva"] = 0
                if pid not in _colas[p["prioridad"]]:
                    _colas[p["prioridad"]].append(pid)


def avanzar_esperas_memoria() -> None:
    """Avanza los contadores de espera por fallo de página de procesos e hilos bloqueados."""
    for pid, p in list(_procesos.items()):
        if p["estado"] == "TERMINADO":
            continue

        # 1. Proceso con hilos
        if p.get("hilos"):
            desperto_hilo = False
            for h in p["hilos"]:
                if h["estado"] == "BLOQUEADO" and h.get("espera_fallo_memoria") is not None:
                    h["espera_fallo_memoria"] -= 1
                    if h["espera_fallo_memoria"] <= 0:
                        h["espera_fallo_memoria"] = None
                        if h["pc"] >= len(h["programa"]):
                            h["estado"] = "TERMINADO"
                        else:
                            h["estado"] = "LISTO"
                            desperto_hilo = True

            # Si el proceso estaba bloqueado y ahora tiene al menos un hilo listo
            if p["estado"] == "BLOQUEADO" and desperto_hilo:
                p["estado"] = "LISTO"
                p["espera_consecutiva"] = 0
                if p["prioridad"] < p["prioridad_original"]:
                    p["prioridad"] = p["prioridad_original"]
                if pid not in _colas[p["prioridad"]]:
                    _colas[p["prioridad"]].append(pid)

        # 2. Proceso sin hilos
        else:
            if p["estado"] == "BLOQUEADO" and p.get("espera_fallo_memoria") is not None:
                p["espera_fallo_memoria"] -= 1
                if p["espera_fallo_memoria"] <= 0:
                    p["espera_fallo_memoria"] = None
                    if p["pc"] >= len(p["programa"]):
                        terminar_proceso(pid)
                    elif p.get("suspendido"):
                        pass    # suspendido por el control de memoria: sigue BLOQUEADO hasta reanudar_proceso
                    else:
                        p["estado"] = "LISTO"
                        p["espera_consecutiva"] = 0
                        if p["prioridad"] < p["prioridad_original"]:
                            p["prioridad"] = p["prioridad_original"]
                        if pid not in _colas[p["prioridad"]]:
                            _colas[p["prioridad"]].append(pid)


def planificar_y_ejecutar_cpu(reloj: int) -> None:
    """Despacha y ejecuta 1 tick de CPU en cada CPU disponible siguiendo política MLFQ."""
    global _reloj_actual, _cambios_contexto
    _reloj_actual = reloj
    _pids_ejecutados_tick.clear()

    for cpu in range(_num_cpus):
        pid_actual = _en_ejecucion.get(cpu)

        # Preempción: si hay un proceso en espera con prioridad estrictamente más alta,
        # o si el proceso ya gastó su quantum y hay otro esperando en su misma cola
        if pid_actual is not None:
            p_actual = _procesos[pid_actual]
            hay_mayor_prioridad = any(len(_colas[prio]) > 0 for prio in range(p_actual["prioridad"]))
            agoto_quantum = p_actual["ticks_turno"] >= _QUANTUM and len(_colas[p_actual["prioridad"]]) > 0
            if hay_mayor_prioridad or agoto_quantum:
                p_actual["estado"] = "LISTO"
                if hay_mayor_prioridad:
                    _colas[p_actual["prioridad"]].appendleft(pid_actual)   # sigue primero en su cola
                else:
                    _colas[p_actual["prioridad"]].append(pid_actual)       # turno rotativo: al final
                _en_ejecucion[cpu] = None
                _cambios_contexto += 1
                pid_actual = None

        # Asignar proceso si la CPU está desocupada
        if pid_actual is None:
            for prio in (0, 1, 2):
                if _colas[prio]:
                    pid_actual = _colas[prio].popleft()
                    _en_ejecucion[cpu] = pid_actual
                    p = _procesos[pid_actual]
                    p["estado"] = "EJECUTANDO"
                    p["espera_consecutiva"] = 0
                    p["ticks_turno"] = 0
                    if p["primer_inicio"] is None:
                        p["primer_inicio"] = reloj
                    break

        if pid_actual is None:
            continue

        p = _procesos[pid_actual]
        _pids_ejecutados_tick.add(pid_actual)
        p["ticks_turno"] += 1

        # ---------------------------------------------------- Caso A: Proceso con hilos
        hilos = p.get("hilos", [])
        hilos_activos = [h for h in hilos if h["estado"] != "TERMINADO"]
        if hilos_activos:
            hilos_listos = [h for h in hilos_activos if h["estado"] in ("LISTO", "EJECUTANDO")]
            if not hilos_listos:
                # Todos los hilos están bloqueados
                p["estado"] = "BLOQUEADO"
                _en_ejecucion[cpu] = None
                continue

            # Despacho Round-Robin entre los hilos listos
            ultimo_tid = p.get("ultimo_tid_ejecutado", 0)
            candidatos = [h for h in hilos_listos if h["tid"] > ultimo_tid]
            if not candidatos:
                candidatos = hilos_listos
            hilo = candidatos[0]
            p["ultimo_tid_ejecutado"] = hilo["tid"]
            hilo["estado"] = "EJECUTANDO"

            if hilo["pc"] >= len(hilo["programa"]):
                hilo["estado"] = "TERMINADO"
                if all(th["estado"] == "TERMINADO" for th in p["hilos"]):
                    terminar_proceso(pid_actual)
                    _en_ejecucion[cpu] = None
                elif not any(th["estado"] == "LISTO" for th in p["hilos"]):
                    p["estado"] = "BLOQUEADO"
                    if p["prioridad"] < p["prioridad_original"]:
                        p["prioridad"] = p["prioridad_original"]
                    _en_ejecucion[cpu] = None
                else:
                    p["estado"] = "LISTO"
                    _colas[p["prioridad"]].append(pid_actual)
                    _en_ejecucion[cpu] = None
                continue

            inst = hilo["programa"][hilo["pc"]]
            tipo = inst[0]
            valor = inst[1]

            if tipo == "CPU":
                if hilo["restante_instruccion"] is None:
                    hilo["restante_instruccion"] = int(valor)

                hilo["restante_instruccion"] -= 1
                hilo["cpu_usada"] = hilo.get("cpu_usada", 0) + 1
                p["cpu_usada"] += 1

                if hilo["restante_instruccion"] <= 0:     # con <=, un ("CPU", 0) dura 1 tick y no se queda pegado
                    hilo["restante_instruccion"] = None
                    hilo["pc"] += 1
                    if hilo["pc"] >= len(hilo["programa"]):
                        hilo["estado"] = "TERMINADO"
                        if all(th["estado"] == "TERMINADO" for th in p["hilos"]):
                            terminar_proceso(pid_actual)
                            _en_ejecucion[cpu] = None
                        elif not any(th["estado"] == "LISTO" for th in p["hilos"]):
                            p["estado"] = "BLOQUEADO"
                            if p["prioridad"] < p["prioridad_original"]:
                                p["prioridad"] = p["prioridad_original"]
                            _en_ejecucion[cpu] = None
                        else:
                            p["estado"] = "LISTO"
                            p["espera_consecutiva"] = 0
                            if p["prioridad"] < p["prioridad_original"]:
                                p["prioridad"] = p["prioridad_original"]
                            _colas[p["prioridad"]].append(pid_actual)
                            _en_ejecucion[cpu] = None
                    else:
                        hilo["estado"] = "LISTO"
                        p["estado"] = "LISTO"
                        p["espera_consecutiva"] = 0
                        if p["prioridad"] < p["prioridad_original"]:
                            p["prioridad"] = p["prioridad_original"]
                        _colas[p["prioridad"]].append(pid_actual)
                        _en_ejecucion[cpu] = None
                else:
                    # La instrucción aún tiene ráfaga pendiente: permanece ejecutando en la CPU
                    hilo["estado"] = "LISTO"
                    p["estado"] = "EJECUTANDO"

            elif tipo == "MEM":
                direccion = int(valor)
                escritura = bool(inst[2]) if len(inst) > 2 else False

                try:
                    from minidc import memoria
                    res = memoria.acceder_memoria(pid_actual, direccion, escritura)
                except NotImplementedError:
                    if direccion < 0 or direccion >= p["memoria_bytes"]:
                        terminar_proceso(pid_actual)
                        _en_ejecucion[cpu] = None
                        continue
                    res = {"marco": 0, "fallo_pagina": False, "pagina_reemplazada": None}
                except ErrorMemoria:
                    # RM3: Acceso inválido termina cleanly al proceso infractor
                    terminar_proceso(pid_actual)
                    _en_ejecucion[cpu] = None
                    continue

                hilo["cpu_usada"] = hilo.get("cpu_usada", 0) + 1
                p["cpu_usada"] += 1
                hilo["pc"] += 1

                if res.get("fallo_pagina", False):
                    hilo["estado"] = "BLOQUEADO"
                    hilo["espera_fallo_memoria"] = 5
                    if not any(th["estado"] == "LISTO" for th in p["hilos"]):
                        p["estado"] = "BLOQUEADO"
                        if p["prioridad"] < p["prioridad_original"]:
                            p["prioridad"] = p["prioridad_original"]
                        _en_ejecucion[cpu] = None
                    else:
                        p["estado"] = "LISTO"
                        if p["prioridad"] < p["prioridad_original"]:
                            p["prioridad"] = p["prioridad_original"]
                        _colas[p["prioridad"]].append(pid_actual)
                        _en_ejecucion[cpu] = None
                else:
                    if hilo["pc"] >= len(hilo["programa"]):
                        hilo["estado"] = "TERMINADO"
                        if all(th["estado"] == "TERMINADO" for th in p["hilos"]):
                            terminar_proceso(pid_actual)
                            _en_ejecucion[cpu] = None
                        elif not any(th["estado"] == "LISTO" for th in p["hilos"]):
                            p["estado"] = "BLOQUEADO"
                            if p["prioridad"] < p["prioridad_original"]:
                                p["prioridad"] = p["prioridad_original"]
                            _en_ejecucion[cpu] = None
                        else:
                            p["estado"] = "LISTO"
                            _colas[p["prioridad"]].append(pid_actual)
                            _en_ejecucion[cpu] = None
                    else:
                        hilo["estado"] = "LISTO"
                        p["estado"] = "LISTO"
                        _colas[p["prioridad"]].append(pid_actual)
                        _en_ejecucion[cpu] = None

            elif tipo == "ES":
                bloque = int(valor)
                operacion = str(inst[2]) if len(inst) > 2 else "L"
                try:
                    disco.encolar_solicitud_disco(pid_actual, bloque, operacion)
                except ErrorSistema:
                    # Bloque u operación inválidos: termina solo al proceso culpable, como en RM3
                    terminar_proceso(pid_actual)
                    _en_ejecucion[cpu] = None
                    continue
                hilo["pc"] += 1
                hilo["estado"] = "BLOQUEADO"
                if not any(th["estado"] == "LISTO" for th in p["hilos"]):
                    p["estado"] = "BLOQUEADO"
                    if p["prioridad"] < p["prioridad_original"]:
                        p["prioridad"] = p["prioridad_original"]
                    _en_ejecucion[cpu] = None
                else:
                    p["estado"] = "LISTO"
                    if p["prioridad"] < p["prioridad_original"]:
                        p["prioridad"] = p["prioridad_original"]
                    _colas[p["prioridad"]].append(pid_actual)
                    _en_ejecucion[cpu] = None

            elif tipo == "WAIT":
                nombre = str(valor)
                try:
                    from minidc import sincronizacion
                    adquirido = sincronizacion.semaforo_wait(nombre, pid_actual)
                except NotImplementedError:
                    adquirido = True
                except ErrorSistema:
                    terminar_proceso(pid_actual)
                    _en_ejecucion[cpu] = None
                    continue

                if adquirido:
                    p.setdefault("semaforos_adquiridos", []).append(nombre)
                    hilo["pc"] += 1
                    hilo["cpu_usada"] = hilo.get("cpu_usada", 0) + 1
                    p["cpu_usada"] += 1
                    hilo["espera_semaforo"] = None
                    if hilo["pc"] >= len(hilo["programa"]):
                        hilo["estado"] = "TERMINADO"
                        if all(th["estado"] == "TERMINADO" for th in p["hilos"]):
                            terminar_proceso(pid_actual)
                            _en_ejecucion[cpu] = None
                        elif not any(th["estado"] == "LISTO" for th in p["hilos"]):
                            p["estado"] = "BLOQUEADO"
                            if p["prioridad"] < p["prioridad_original"]:
                                p["prioridad"] = p["prioridad_original"]
                            _en_ejecucion[cpu] = None
                        else:
                            p["estado"] = "LISTO"
                            p["espera_consecutiva"] = 0
                            if p["prioridad"] < p["prioridad_original"]:
                                p["prioridad"] = p["prioridad_original"]
                            _colas[p["prioridad"]].append(pid_actual)
                            _en_ejecucion[cpu] = None
                    else:
                        hilo["estado"] = "LISTO"
                        p["estado"] = "LISTO"
                        p["espera_consecutiva"] = 0
                        if p["prioridad"] < p["prioridad_original"]:
                            p["prioridad"] = p["prioridad_original"]
                        _colas[p["prioridad"]].append(pid_actual)
                        _en_ejecucion[cpu] = None
                else:
                    hilo["estado"] = "BLOQUEADO"
                    hilo["espera_semaforo"] = nombre
                    _espera_semaforos.setdefault(nombre, deque()).append((pid_actual, hilo["tid"]))
                    if not any(th["estado"] == "LISTO" for th in p["hilos"]):
                        p["estado"] = "BLOQUEADO"
                        if p["prioridad"] < p["prioridad_original"]:
                            p["prioridad"] = p["prioridad_original"]
                        _en_ejecucion[cpu] = None
                    else:
                        p["estado"] = "LISTO"
                        p["espera_consecutiva"] = 0
                        if p["prioridad"] < p["prioridad_original"]:
                            p["prioridad"] = p["prioridad_original"]
                        _colas[p["prioridad"]].append(pid_actual)
                        _en_ejecucion[cpu] = None

            elif tipo == "SIGNAL":
                nombre = str(valor)
                if nombre in p.get("semaforos_adquiridos", []):
                    p["semaforos_adquiridos"].remove(nombre)

                cola_antes = []
                try:
                    from minidc import sincronizacion
                    est = sincronizacion.estado_semaforo(nombre)
                    if isinstance(est, dict):
                        cola_antes = list(est.get("cola_espera", []))
                except Exception:
                    pass

                ret_signal = None
                try:
                    from minidc import sincronizacion
                    ret_signal = sincronizacion.semaforo_signal(nombre, pid_actual)
                except NotImplementedError:
                    pass
                except ErrorSistema:
                    terminar_proceso(pid_actual)
                    _en_ejecucion[cpu] = None
                    continue

                pid_despertado = None
                if isinstance(ret_signal, int):
                    pid_despertado = ret_signal
                elif cola_antes:
                    cola_despues = []
                    try:
                        from minidc import sincronizacion
                        est = sincronizacion.estado_semaforo(nombre)
                        if isinstance(est, dict):
                            cola_despues = list(est.get("cola_espera", []))
                    except Exception:
                        pass
                    if len(cola_despues) < len(cola_antes):
                        pid_despertado = cola_antes[0]

                _despertar_por_semaforo(nombre, pid_despertado=pid_despertado)

                hilo["pc"] += 1
                hilo["cpu_usada"] = hilo.get("cpu_usada", 0) + 1
                p["cpu_usada"] += 1
                if hilo["pc"] >= len(hilo["programa"]):
                    hilo["estado"] = "TERMINADO"
                    if all(th["estado"] == "TERMINADO" for th in p["hilos"]):
                        terminar_proceso(pid_actual)
                        _en_ejecucion[cpu] = None
                    elif not any(th["estado"] == "LISTO" for th in p["hilos"]):
                        p["estado"] = "BLOQUEADO"
                        if p["prioridad"] < p["prioridad_original"]:
                            p["prioridad"] = p["prioridad_original"]
                        _en_ejecucion[cpu] = None
                    else:
                        p["estado"] = "LISTO"
                        p["espera_consecutiva"] = 0
                        if p["prioridad"] < p["prioridad_original"]:
                            p["prioridad"] = p["prioridad_original"]
                        _colas[p["prioridad"]].append(pid_actual)
                        _en_ejecucion[cpu] = None
                else:
                    hilo["estado"] = "LISTO"
                    p["estado"] = "LISTO"
                    p["espera_consecutiva"] = 0
                    if p["prioridad"] < p["prioridad_original"]:
                        p["prioridad"] = p["prioridad_original"]
                    _colas[p["prioridad"]].append(pid_actual)
                    _en_ejecucion[cpu] = None

            else:
                hilo["pc"] += 1
                if hilo["pc"] >= len(hilo["programa"]):
                    hilo["estado"] = "TERMINADO"
                    if all(th["estado"] == "TERMINADO" for th in p["hilos"]):
                        terminar_proceso(pid_actual)
                        _en_ejecucion[cpu] = None
                    elif not any(th["estado"] == "LISTO" for th in p["hilos"]):
                        p["estado"] = "BLOQUEADO"
                        if p["prioridad"] < p["prioridad_original"]:
                            p["prioridad"] = p["prioridad_original"]
                        _en_ejecucion[cpu] = None
                    else:
                        p["estado"] = "LISTO"
                        _colas[p["prioridad"]].append(pid_actual)
                        _en_ejecucion[cpu] = None
                else:
                    hilo["estado"] = "LISTO"
                    p["estado"] = "LISTO"
                    _colas[p["prioridad"]].append(pid_actual)
                    _en_ejecucion[cpu] = None

        # ---------------------------------------------------- Caso B: Proceso secuencial (sin hilos)
        else:
            if p["pc"] >= len(p["programa"]):
                terminar_proceso(pid_actual)
                _en_ejecucion[cpu] = None
                continue

            inst = p["programa"][p["pc"]]
            tipo = inst[0]
            valor = inst[1]

            if tipo == "CPU":
                if p["restante_instruccion"] is None:
                    p["restante_instruccion"] = int(valor)

                p["restante_instruccion"] -= 1
                p["cpu_usada"] += 1

                if p["restante_instruccion"] <= 0:     # con <=, un ("CPU", 0) dura 1 tick y no se queda pegado
                    p["restante_instruccion"] = None
                    p["pc"] += 1
                    if p["pc"] >= len(p["programa"]):
                        terminar_proceso(pid_actual)
                        _en_ejecucion[cpu] = None
                    else:
                        # Ráfaga completada: cede CPU y rota al final de su cola
                        if p["prioridad"] < p["prioridad_original"]:
                            p["prioridad"] = p["prioridad_original"]
                        p["estado"] = "LISTO"
                        p["espera_consecutiva"] = 0
                        _colas[p["prioridad"]].append(pid_actual)
                        _en_ejecucion[cpu] = None

            elif tipo == "MEM":
                direccion = int(valor)
                escritura = bool(inst[2]) if len(inst) > 2 else False

                try:
                    from minidc import memoria
                    res = memoria.acceder_memoria(pid_actual, direccion, escritura)
                except NotImplementedError:
                    if direccion < 0 or direccion >= p["memoria_bytes"]:
                        terminar_proceso(pid_actual)
                        _en_ejecucion[cpu] = None
                        continue
                    res = {"marco": 0, "fallo_pagina": False, "pagina_reemplazada": None}
                except ErrorMemoria:
                    # RM3: Acceso inválido termina cleanly al proceso infractor
                    terminar_proceso(pid_actual)
                    _en_ejecucion[cpu] = None
                    continue

                p["cpu_usada"] += 1
                p["pc"] += 1

                if res.get("fallo_pagina", False):
                    p["estado"] = "BLOQUEADO"
                    p["espera_fallo_memoria"] = 5
                    if p["prioridad"] < p["prioridad_original"]:
                        p["prioridad"] = p["prioridad_original"]
                    _en_ejecucion[cpu] = None
                else:
                    if p["pc"] >= len(p["programa"]):
                        terminar_proceso(pid_actual)
                        _en_ejecucion[cpu] = None
                    else:
                        if p["prioridad"] < p["prioridad_original"]:
                            p["prioridad"] = p["prioridad_original"]
                        p["estado"] = "LISTO"
                        p["espera_consecutiva"] = 0
                        _colas[p["prioridad"]].append(pid_actual)
                        _en_ejecucion[cpu] = None

            elif tipo == "ES":
                bloque = int(valor)
                operacion = str(inst[2]) if len(inst) > 2 else "L"
                try:
                    disco.encolar_solicitud_disco(pid_actual, bloque, operacion)
                except ErrorSistema:
                    # Bloque u operación inválidos: termina solo al proceso culpable, como en RM3
                    terminar_proceso(pid_actual)
                    _en_ejecucion[cpu] = None
                    continue
                p["estado"] = "BLOQUEADO"
                p["pc"] += 1
                if p["prioridad"] < p["prioridad_original"]:
                    p["prioridad"] = p["prioridad_original"]
                _en_ejecucion[cpu] = None

            elif tipo == "WAIT":
                nombre = str(valor)
                try:
                    from minidc import sincronizacion
                    adquirido = sincronizacion.semaforo_wait(nombre, pid_actual)
                except NotImplementedError:
                    adquirido = True
                except ErrorSistema:
                    terminar_proceso(pid_actual)
                    _en_ejecucion[cpu] = None
                    continue

                if adquirido:
                    p.setdefault("semaforos_adquiridos", []).append(nombre)
                    p["pc"] += 1
                    p["cpu_usada"] += 1
                    p["espera_semaforo"] = None
                    if p["pc"] >= len(p["programa"]):
                        terminar_proceso(pid_actual)
                        _en_ejecucion[cpu] = None
                    else:
                        if p["prioridad"] < p["prioridad_original"]:
                            p["prioridad"] = p["prioridad_original"]
                        p["estado"] = "LISTO"
                        p["espera_consecutiva"] = 0
                        _colas[p["prioridad"]].append(pid_actual)
                        _en_ejecucion[cpu] = None
                else:
                    p["estado"] = "BLOQUEADO"
                    p["espera_semaforo"] = nombre
                    _espera_semaforos.setdefault(nombre, deque()).append((pid_actual, None))
                    if p["prioridad"] < p["prioridad_original"]:
                        p["prioridad"] = p["prioridad_original"]
                    _en_ejecucion[cpu] = None

            elif tipo == "SIGNAL":
                nombre = str(valor)
                if nombre in p.get("semaforos_adquiridos", []):
                    p["semaforos_adquiridos"].remove(nombre)

                cola_antes = []
                try:
                    from minidc import sincronizacion
                    est = sincronizacion.estado_semaforo(nombre)
                    if isinstance(est, dict):
                        cola_antes = list(est.get("cola_espera", []))
                except Exception:
                    pass

                ret_signal = None
                try:
                    from minidc import sincronizacion
                    ret_signal = sincronizacion.semaforo_signal(nombre, pid_actual)
                except NotImplementedError:
                    pass
                except ErrorSistema:
                    terminar_proceso(pid_actual)
                    _en_ejecucion[cpu] = None
                    continue

                pid_despertado = None
                if isinstance(ret_signal, int):
                    pid_despertado = ret_signal
                elif cola_antes:
                    cola_despues = []
                    try:
                        from minidc import sincronizacion
                        est = sincronizacion.estado_semaforo(nombre)
                        if isinstance(est, dict):
                            cola_despues = list(est.get("cola_espera", []))
                    except Exception:
                        pass
                    if len(cola_despues) < len(cola_antes):
                        pid_despertado = cola_antes[0]

                _despertar_por_semaforo(nombre, pid_despertado=pid_despertado)

                p["pc"] += 1
                p["cpu_usada"] += 1
                if p["pc"] >= len(p["programa"]):
                    terminar_proceso(pid_actual)
                    _en_ejecucion[cpu] = None
                else:
                    if p["prioridad"] < p["prioridad_original"]:
                        p["prioridad"] = p["prioridad_original"]
                    p["estado"] = "LISTO"
                    p["espera_consecutiva"] = 0
                    _colas[p["prioridad"]].append(pid_actual)
                    _en_ejecucion[cpu] = None

            else:
                p["pc"] += 1
                if p["pc"] >= len(p["programa"]):
                    terminar_proceso(pid_actual)
                    _en_ejecucion[cpu] = None


def actualizar_metricas_espera() -> None:
    """Actualiza tiempos de espera, tiempo bloqueado y envejecimiento (aging)."""
    for pid, p in _procesos.items():
        if p["estado"] == "LISTO":
            if pid not in _pids_ejecutados_tick:
                p["tiempo_espera"] += 1
                p["espera_consecutiva"] += 1
                # Envejecimiento: tras _UMBRAL_ENVEJECIMIENTO ticks esperando sube un nivel
                if p["espera_consecutiva"] >= _UMBRAL_ENVEJECIMIENTO and p["prioridad"] > 0:
                    old_prio = p["prioridad"]
                    new_prio = old_prio - 1
                    try:
                        _colas[old_prio].remove(pid)
                    except ValueError:
                        pass
                    p["prioridad"] = new_prio
                    _colas[new_prio].append(pid)
                    p["espera_consecutiva"] = 0
            else:
                p["espera_consecutiva"] = 0
        elif p["estado"] == "BLOQUEADO":
            p["tiempo_bloqueado"] += 1
            for h in p.get("hilos", []):
                if h["estado"] == "BLOQUEADO":
                    h["tiempo_bloqueado"] = h.get("tiempo_bloqueado", 0) + 1
        elif p["estado"] == "EJECUTANDO":
            p["espera_consecutiva"] = 0


def metricas_planificacion() -> dict:
    """Devuelve métricas: espera_promedio, respuesta_promedio, retorno_promedio,
    espera_maxima, utilizacion_cpu, cambios_contexto y procesos_terminados.
    """
    terminados = [p for p in _procesos.values() if p["estado"] == "TERMINADO"]
    iniciados = [p for p in _procesos.values() if p["primer_inicio"] is not None]

    espera_promedio = (
        sum(p["tiempo_espera"] for p in terminados) / len(terminados)
        if terminados
        else 0.0
    )
    respuesta_promedio = (
        sum(p["primer_inicio"] - p["tick_llegada"] for p in iniciados) / len(iniciados)
        if iniciados
        else 0.0
    )
    retorno_promedio = (
        sum(p["tick_fin"] - p["tick_llegada"] for p in terminados if p["tick_fin"] is not None) / len(terminados)
        if terminados
        else 0.0
    )
    espera_maxima = (
        max((p["tiempo_espera"] for p in _procesos.values()), default=0)
        if _procesos
        else 0
    )
    cpu_usada_total = sum(p["cpu_usada"] for p in _procesos.values())
    denom = _reloj_actual * _num_cpus
    utilizacion_cpu = round(min(1.0, max(0.0, cpu_usada_total / denom)), 4) if denom > 0 else 0.0

    return {
        "espera_promedio": espera_promedio,
        "respuesta_promedio": respuesta_promedio,
        "retorno_promedio": retorno_promedio,
        "espera_maxima": espera_maxima,
        "utilizacion_cpu": utilizacion_cpu,
        "cambios_contexto": _cambios_contexto,
        "procesos_terminados": len(terminados),
    }


def politica_planificacion() -> str:
    """Devuelve el nombre de la política de planificación elegida."""
    return "MLFQ"


reiniciar({})
