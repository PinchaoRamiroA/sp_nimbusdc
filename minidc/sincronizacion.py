"""Primitivas de sincronización, interbloqueos y demostración de condición de carrera."""


def crear_semaforo(nombre: str, valor_inicial: int) -> None:
    """Crea un semáforo con nombre y valor inicial."""
    raise NotImplementedError("Pendiente de implementación")


def semaforo_wait(nombre: str, pid: int) -> bool:
    """Ejecuta wait sobre el semáforo.

    Devuelve ``True`` si ``pid`` obtiene el recurso o ``False`` si queda BLOQUEADO.
    """
    raise NotImplementedError("Pendiente de implementación")


def semaforo_signal(nombre: str, pid: int) -> None:
    """Ejecuta signal sobre el semáforo y despierta a un proceso en espera si lo hay."""
    raise NotImplementedError("Pendiente de implementación")


def estado_semaforo(nombre: str) -> dict:
    """Devuelve ``{"valor": int, "cola_espera": list[int]}``."""
    raise NotImplementedError("Pendiente de implementación")


def crear_mutex(nombre: str) -> None:
    """Crea un mutex sin dueño."""
    raise NotImplementedError("Pendiente de implementación")


def mutex_lock(nombre: str, pid: int) -> bool:
    """Intenta adquirir el mutex para ``pid``."""
    raise NotImplementedError("Pendiente de implementación")


def mutex_unlock(nombre: str, pid: int) -> None:
    """Libera el mutex. Lanza ``ErrorSincronizacion`` si ``pid`` no es el dueño."""
    raise NotImplementedError("Pendiente de implementación")


def detectar_interbloqueo() -> list:
    """Detecta ciclos de interbloqueo y devuelve una lista de ciclos (listas de PID)."""
    raise NotImplementedError("Pendiente de implementación")


def resolver_interbloqueo() -> list:
    """Resuelve interbloqueos activos y devuelve la lista de PID afectados."""
    raise NotImplementedError("Pendiente de implementación")


def demo_condicion_carrera(
    usar_sincronizacion: bool,
    num_hilos: int,
    iteraciones: int,
) -> int:
    """Demuestra condición de carrera usando hilos reales sobre un contador compartido.

    Con ``usar_sincronizacion=False`` el resultado puede ser menor que
    ``num_hilos * iteraciones``; con ``True`` debe ser exactamente igual.
    """
    raise NotImplementedError("Pendiente de implementación")
