"""Gestión de procesos, hilos y planificación de CPU.

Implementa un planificador de colas multinivel con retroalimentación (MLFQ)
con 3 niveles de prioridad (0: alta, 1: media, 2: baja) y envejecimiento (aging)
para evitar inanición y satisfacer RP1 y RP2.
Este módulo no debe importar a `kernel.py`.
"""
from collections import deque
import itertools

from minidc import disco
from minidc.errores import ErrorNoExiste, ErrorSistema

# ---------------------------------------------------------------- estado interno
_procesos = {}
_colas = {0: deque(), 1: deque(), 2: deque()}
_en_ejecucion = {}
_num_cpus = 1
_reloj_actual = 0
_contador_pids = itertools.count(1)
_cambios_contexto = 0
_pids_ejecutados_tick = set()


def reiniciar(config: dict | None = None) -> None:
    """Reinicia el estado del subsistema de procesos."""
    global _procesos, _colas, _en_ejecucion, _num_cpus, _reloj_actual
    global _contador_pids, _cambios_contexto, _pids_ejecutados_tick
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
        "tiempo_bloqueado": 0,
        "hilos": [],
    }
    _procesos[pid] = proceso
    _colas[prio_norm].append(pid)
    return pid


def crear_hilo(pid: int, programa: list) -> int:
    """Crea un hilo asociado al proceso ``pid`` y devuelve su TID."""
    if pid not in _procesos:
        raise ErrorNoExiste(f"Proceso con PID {pid} no existe")
    p = _procesos[pid]
    prog_tuplas = [tuple(inst) if isinstance(inst, (list, tuple)) else inst for inst in programa]
    tid = len(p["hilos"]) + 1
    hilo = {
        "tid": tid,
        "pid": pid,
        "programa": prog_tuplas,
        "pc": 0,
        "estado": "LISTO",
    }
    p["hilos"].append(hilo)
    return tid


def terminar_proceso(pid: int) -> None:
    """Termina el proceso ``pid`` y libera su memoria, semáforos y mutex."""
    if pid not in _procesos:
        raise ErrorNoExiste(f"Proceso con PID {pid} no existe")
    p = _procesos[pid]
    p["estado"] = "TERMINADO"
    if p["tick_fin"] is None:
        p["tick_fin"] = _reloj_actual

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
        }
        for p in _procesos.values()
    ]


def cola_listos() -> list:
    """Devuelve los PID en la cola de listos en el orden en que serán atendidos."""
    return list(_colas[0]) + list(_colas[1]) + list(_colas[2])


def proceso_en_ejecucion(cpu: int = 0) -> int | None:
    """Devuelve el PID en ejecución en la CPU indicada, o ``None`` si está libre."""
    return _en_ejecucion.get(cpu)


def despertar_proceso(pid: int) -> None:
    """Despierta a un proceso que completó su E/S y lo reincorpora a la cola de listos."""
    if pid not in _procesos:
        return
    p = _procesos[pid]
    if p["estado"] == "BLOQUEADO":
        if p["pc"] >= len(p["programa"]):
            p["estado"] = "TERMINADO"
            p["tick_fin"] = _reloj_actual
        else:
            p["estado"] = "LISTO"
            p["espera_consecutiva"] = 0
            _colas[p["prioridad"]].append(pid)


def planificar_y_ejecutar_cpu(reloj: int) -> None:
    """Despacha y ejecuta 1 tick de CPU en cada CPU disponible siguiendo política MLFQ."""
    global _reloj_actual, _cambios_contexto
    _reloj_actual = reloj
    _pids_ejecutados_tick.clear()

    for cpu in range(_num_cpus):
        pid_actual = _en_ejecucion.get(cpu)

        # Preempción: si hay un proceso en espera con prioridad estrictamente más alta
        if pid_actual is not None:
            p_actual = _procesos[pid_actual]
            hay_mayor_prioridad = any(len(_colas[prio]) > 0 for prio in range(p_actual["prioridad"]))
            if hay_mayor_prioridad:
                p_actual["estado"] = "LISTO"
                _colas[p_actual["prioridad"]].appendleft(pid_actual)
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
                    if p["primer_inicio"] is None:
                        p["primer_inicio"] = reloj
                    break

        if pid_actual is None:
            continue

        p = _procesos[pid_actual]
        _pids_ejecutados_tick.add(pid_actual)

        if p["pc"] >= len(p["programa"]):
            p["estado"] = "TERMINADO"
            p["tick_fin"] = reloj
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

            if p["restante_instruccion"] == 0:
                p["restante_instruccion"] = None
                p["pc"] += 1
                if p["pc"] >= len(p["programa"]):
                    p["estado"] = "TERMINADO"
                    p["tick_fin"] = reloj
                    _en_ejecucion[cpu] = None
                else:
                    # Ráfaga completada: cede CPU y rota al final de su cola
                    if p["prioridad"] < p["prioridad_original"]:
                        p["prioridad"] = p["prioridad_original"]
                    p["estado"] = "LISTO"
                    p["espera_consecutiva"] = 0
                    _colas[p["prioridad"]].append(pid_actual)
                    _en_ejecucion[cpu] = None

        elif tipo == "ES":
            bloque = int(valor)
            operacion = str(inst[2]) if len(inst) > 2 else "L"
            disco.encolar_solicitud_disco(pid_actual, bloque, operacion)
            p["estado"] = "BLOQUEADO"
            p["pc"] += 1
            if p["prioridad"] < p["prioridad_original"]:
                p["prioridad"] = p["prioridad_original"]
            _en_ejecucion[cpu] = None

        else:
            p["pc"] += 1
            if p["pc"] >= len(p["programa"]):
                p["estado"] = "TERMINADO"
                p["tick_fin"] = reloj
                _en_ejecucion[cpu] = None


def actualizar_metricas_espera() -> None:
    """Actualiza tiempos de espera, tiempo bloqueado y envejecimiento (aging)."""
    for pid, p in _procesos.items():
        if p["estado"] == "LISTO":
            if pid not in _pids_ejecutados_tick:
                p["tiempo_espera"] += 1
                p["espera_consecutiva"] += 1
                # Envejecimiento: umbral de 50 ticks
                if p["espera_consecutiva"] >= 50 and p["prioridad"] > 0:
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
