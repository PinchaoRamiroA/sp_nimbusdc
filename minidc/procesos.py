"""Gestión de procesos, hilos y planificación de CPU."""


def crear_proceso(
    nombre: str,
    usuario: str,
    programa: list,
    memoria_bytes: int = 4096,
    cuota_marcos: int = 4,
    prioridad: int = 0,
) -> int:
    """Crea un proceso nuevo y devuelve su PID."""
    raise NotImplementedError("Pendiente de implementación")


def crear_hilo(pid: int, programa: list) -> int:
    """Crea un hilo asociado al proceso ``pid`` y devuelve su TID."""
    raise NotImplementedError("Pendiente de implementación")


def terminar_proceso(pid: int) -> None:
    """Termina el proceso ``pid`` y libera su memoria, semáforos y mutex."""
    raise NotImplementedError("Pendiente de implementación")


def estado_proceso(pid: int) -> str:
    """Devuelve el estado del proceso: NUEVO, LISTO, EJECUTANDO, BLOQUEADO o TERMINADO."""
    raise NotImplementedError("Pendiente de implementación")


def listar_procesos() -> list:
    """Lista diccionarios con: pid, nombre, usuario, estado, prioridad, cpu_usada, tiempo_espera."""
    raise NotImplementedError("Pendiente de implementación")


def cola_listos() -> list:
    """Devuelve los PID en la cola de listos en el orden en que serán atendidos."""
    raise NotImplementedError("Pendiente de implementación")


def proceso_en_ejecucion(cpu: int = 0) -> int | None:
    """Devuelve el PID en ejecución en la CPU indicada, o ``None`` si está libre."""
    raise NotImplementedError("Pendiente de implementación")


def metricas_planificacion() -> dict:
    """Devuelve métricas: espera_promedio, respuesta_promedio, retorno_promedio,
    espera_maxima, utilizacion_cpu, cambios_contexto y procesos_terminados.
    """
    raise NotImplementedError("Pendiente de implementación")


def politica_planificacion() -> str:
    """Devuelve el nombre de la política de planificación elegida."""
    raise NotImplementedError("Pendiente de implementación")
