"""Primitivas de sincronización, interbloqueos y demostración de condición de carrera.

Módulo del Prototipo 3 de NimbusDC (`minidc`).
Responsabilidad: Integrante 4 (Consola, sincronización e infraestructura).
Cumple los requisitos RS1 y RS2 del enunciado.
"""
from __future__ import annotations

import threading
from time import sleep

from minidc.errores import ErrorNoExiste, ErrorSincronizacion, ErrorYaExiste

# ---------------------------------------------------------------- estado interno
_semaforos: dict[str, dict] = {}
_mutexes: dict[str, dict] = {}


def reiniciar(config: dict | None = None) -> None:
    """Reinicia todo el estado interno del módulo de sincronización."""
    global _semaforos, _mutexes
    _semaforos.clear()
    _mutexes.clear()


def crear_semaforo(nombre: str, valor_inicial: int) -> None:
    """Crea un semáforo con nombre y valor inicial.

    Lanza ``ErrorSincronizacion`` si el valor inicial es negativo o el nombre es inválido.
    Lanza ``ErrorYaExiste`` si ya existe un semáforo con dicho nombre.
    """
    if not isinstance(nombre, str) or not nombre:
        raise ErrorSincronizacion("Nombre de semáforo inválido")
    if not isinstance(valor_inicial, int) or valor_inicial < 0:
        raise ErrorSincronizacion("El valor inicial no puede ser negativo")
    if nombre in _semaforos:
        raise ErrorYaExiste(f"El semáforo '{nombre}' ya existe")

    _semaforos[nombre] = {
        "valor": valor_inicial,
        "valor_inicial": valor_inicial,
        "cola_espera": [],
        "reservados": set(),
        "poseedores": {},
    }


def semaforo_wait(nombre: str, pid: int) -> bool:
    """Ejecuta wait sobre el semáforo.

    Devuelve ``True`` si ``pid`` obtiene el recurso o ``False`` si queda BLOQUEADO.
    Lanza ``ErrorSincronizacion`` si el semáforo no existe.
    """
    if nombre not in _semaforos:
        raise ErrorSincronizacion(f"Semáforo '{nombre}' no existe")

    sem = _semaforos[nombre]
    # Si este proceso ya tenía un permiso reservado por un signal previo:
    if pid in sem["reservados"]:
        sem["reservados"].remove(pid)
        sem["poseedores"][pid] = sem["poseedores"].get(pid, 0) + 1
        return True

    # Si hay permisos disponibles en el contador:
    if sem["valor"] > 0:
        sem["valor"] -= 1
        sem["poseedores"][pid] = sem["poseedores"].get(pid, 0) + 1
        return True

    # Si no hay permisos, queda en cola de espera (FIFO)
    if pid not in sem["cola_espera"]:
        sem["cola_espera"].append(pid)
    return False


def semaforo_signal(nombre: str, pid: int) -> int | None:
    """Ejecuta signal sobre el semáforo y despierta a un proceso en espera si lo hay.

    Devuelve el PID del proceso despertado si había alguien esperando, o ``None``.
    Lanza ``ErrorSincronizacion`` si el semáforo no existe.
    """
    if nombre not in _semaforos:
        raise ErrorSincronizacion(f"Semáforo '{nombre}' no existe")

    sem = _semaforos[nombre]
    # Si el proceso que emite el signal lo poseía, decrementamos su posesión
    if pid in sem["poseedores"]:
        sem["poseedores"][pid] -= 1
        if sem["poseedores"][pid] <= 0:
            del sem["poseedores"][pid]

    # Si hay procesos en espera (política FIFO estricta):
    if sem["cola_espera"]:
        despertado = sem["cola_espera"].pop(0)
        sem["reservados"].add(despertado)
        return despertado

    # Si no hay nadie en espera, incrementamos el contador
    sem["valor"] += 1
    return None


def estado_semaforo(nombre: str) -> dict:
    """Devuelve ``{"valor": int, "cola_espera": list[int]}``.

    Lanza ``ErrorSincronizacion`` si el semáforo no existe.
    """
    if nombre not in _semaforos:
        raise ErrorSincronizacion(f"Semáforo '{nombre}' no existe")

    sem = _semaforos[nombre]
    return {
        "valor": sem["valor"],
        "cola_espera": list(sem["cola_espera"]),
    }


def crear_mutex(nombre: str) -> None:
    """Crea un mutex sin dueño.

    Lanza ``ErrorSincronizacion`` si el nombre es inválido.
    Lanza ``ErrorYaExiste`` si ya existe un mutex con dicho nombre.
    """
    if not isinstance(nombre, str) or not nombre:
        raise ErrorSincronizacion("Nombre de mutex inválido")
    if nombre in _mutexes:
        raise ErrorYaExiste(f"El mutex '{nombre}' ya existe")

    _mutexes[nombre] = {
        "duenio": None,
        "cola_espera": [],
    }


def mutex_lock(nombre: str, pid: int) -> bool:
    """Intenta adquirir el mutex para ``pid``.

    Devuelve ``True`` si lo adquiere inmediatamente o ``False`` si queda en espera.
    Lanza ``ErrorSincronizacion`` si el mutex no existe.
    """
    if nombre not in _mutexes:
        raise ErrorSincronizacion(f"Mutex '{nombre}' no existe")

    m = _mutexes[nombre]
    if m["duenio"] is None:
        m["duenio"] = pid
        return True
    if m["duenio"] == pid:
        return True

    if pid not in m["cola_espera"]:
        m["cola_espera"].append(pid)
    return False


def mutex_unlock(nombre: str, pid: int) -> None:
    """Libera el mutex. Lanza ``ErrorSincronizacion`` si ``pid`` no es el dueño."""
    if nombre not in _mutexes:
        raise ErrorSincronizacion(f"Mutex '{nombre}' no existe")

    m = _mutexes[nombre]
    if m["duenio"] != pid:
        raise ErrorSincronizacion(f"El proceso {pid} no es el dueño del mutex '{nombre}'")

    if m["cola_espera"]:
        m["duenio"] = m["cola_espera"].pop(0)
    else:
        m["duenio"] = None


def liberar_recursos(pid: int) -> None:
    """Libera todos los recursos retenidos por ``pid`` y lo remueve de las colas de espera.

    Invocado automáticamente por ``procesos.terminar_proceso`` al finalizar o abortar un proceso.
    """
    # Liberar o transferir mutexes cuyo dueño era pid
    for m in _mutexes.values():
        if m["duenio"] == pid:
            if m["cola_espera"]:
                m["duenio"] = m["cola_espera"].pop(0)
            else:
                m["duenio"] = None
        if pid in m["cola_espera"]:
            m["cola_espera"] = [p for p in m["cola_espera"] if p != pid]

    # Liberar o transferir semáforos
    for sem in _semaforos.values():
        if pid in sem["cola_espera"]:
            sem["cola_espera"] = [p for p in sem["cola_espera"] if p != pid]

        if pid in sem["reservados"]:
            sem["reservados"].remove(pid)
            if sem["cola_espera"]:
                despertado = sem["cola_espera"].pop(0)
                sem["reservados"].add(despertado)
            else:
                sem["valor"] += 1

        if pid in sem["poseedores"]:
            cant = sem["poseedores"].pop(pid, 0)
            for _ in range(cant):
                if sem["cola_espera"]:
                    despertado = sem["cola_espera"].pop(0)
                    sem["reservados"].add(despertado)
                else:
                    sem["valor"] += 1


liberar_proceso = liberar_recursos


def _obtener_grafo_espera() -> dict[int, set[int]]:
    """Construye el Grafo de Asignación y Espera (Wait-For Graph).

    Un arco dirigido A -> B significa que el proceso A está en cola de espera
    por un recurso retenido por el proceso B.
    """
    grafo: dict[int, set[int]] = {}

    # Dependencias por Mutexes
    for m in _mutexes.values():
        duenio = m["duenio"]
        if duenio is not None:
            for esperando in m["cola_espera"]:
                if esperando != duenio:
                    grafo.setdefault(esperando, set()).add(duenio)

    # Dependencias por Semáforos
    for sem in _semaforos.values():
        poseedores = sem.get("poseedores", {})
        for esperando in sem["cola_espera"]:
            for posee, cant in poseedores.items():
                if cant > 0 and posee != esperando:
                    grafo.setdefault(esperando, set()).add(posee)

    return grafo


def detectar_interbloqueo() -> list[list[int]]:
    """Detecta ciclos de interbloqueo y devuelve una lista de ciclos (listas de PID).

    Utiliza búsqueda en profundidad (DFS) sobre el grafo de espera para encontrar
    todos los ciclos elementales cerrados, normalizados sin duplicados.
    """
    grafo = _obtener_grafo_espera()
    ciclos_encontrados: set[tuple[int, ...]] = set()
    resultado: list[list[int]] = []

    def dfs(nodo: int, camino: list[int], visitados_en_camino: set[int]) -> None:
        for vecino in grafo.get(nodo, ()):
            if vecino in visitados_en_camino:
                idx = camino.index(vecino)
                ciclo = camino[idx:]
                if ciclo:
                    min_idx = ciclo.index(min(ciclo))
                    ciclo_normalizado = tuple(ciclo[min_idx:] + ciclo[:min_idx])
                    if ciclo_normalizado not in ciclos_encontrados:
                        ciclos_encontrados.add(ciclo_normalizado)
                        resultado.append(list(ciclo_normalizado))
            elif vecino not in camino:
                dfs(vecino, camino + [vecino], visitados_en_camino | {vecino})

    for nodo in list(grafo.keys()):
        dfs(nodo, [nodo], {nodo})

    return resultado


def resolver_interbloqueo() -> list[int]:
    """Resuelve interbloqueos activos y devuelve la lista de PID afectados.

    Cumple el requisito RS2: tras la resolución, ``detectar_interbloqueo()``
    devuelve una lista vacía.
    """
    afectados: list[int] = []

    while True:
        ciclos = detectar_interbloqueo()
        if not ciclos:
            break

        # Seleccionar víctima del primer ciclo detectado (estrategia determinista: primer PID del ciclo)
        victima = ciclos[0][0]
        if victima not in afectados:
            afectados.append(victima)

        # Abortar/terminar proceso en el núcleo si está registrado
        try:
            from minidc import procesos
            if hasattr(procesos, "terminar_proceso"):
                procesos.terminar_proceso(victima)
        except Exception:
            pass

        # Liberar inmediatamente cualquier recurso o espera en sincronización
        liberar_recursos(victima)

    return afectados


def demo_condicion_carrera(
    usar_sincronizacion: bool,
    num_hilos: int,
    iteraciones: int,
) -> int:
    """Demuestra condición de carrera usando hilos reales sobre un contador compartido.

    Con ``usar_sincronizacion=False`` el resultado puede ser menor que
    ``num_hilos * iteraciones``; con ``True`` debe ser exactamente igual (RS1).
    """
    contador = 0
    cerrojo = threading.Lock()

    def trabajador() -> None:
        nonlocal contador
        for _ in range(iteraciones):
            if usar_sincronizacion:
                with cerrojo:
                    temp = contador
                    sleep(0)
                    contador = temp + 1
            else:
                temp = contador
                sleep(0)
                contador = temp + 1

    hilos = [threading.Thread(target=trabajador) for _ in range(num_hilos)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()

    return contador
