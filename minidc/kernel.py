"""Núcleo principal y reloj discreto del sistema operativo simulado NimbusDC."""


def iniciar_sistema(config: dict) -> None:
    """Reinicia todo el estado del sistema con la configuración dada.

    Claves esperadas en ``config``:
    ``num_cpus``, ``marcos_fisicos``, ``tam_pagina``, ``bloques_disco``,
    ``tam_bloque``, ``cache_bloques``.
    """
    raise NotImplementedError("Pendiente de implementación")


def apagar_sistema() -> dict:
    """Finaliza la ejecución simulada y devuelve un resumen final del sistema."""
    raise NotImplementedError("Pendiente de implementación")


def tick() -> None:
    """Avanza el reloj en 1 tick y ejecuta un ciclo completo del núcleo.

    Orden obligatorio por tick:
    1. Llegada de procesos del escenario.
    2. Atención de la E/S terminada (interrupción).
    3. Ejecución de 1 tick por cada CPU.
    4. Actualización de métricas.
    """
    raise NotImplementedError("Pendiente de implementación")


def ejecutar_ticks(n: int) -> None:
    """Ejecuta ``n`` ticks consecutivos del reloj discreto."""
    raise NotImplementedError("Pendiente de implementación")


def reloj_actual() -> int:
    """Devuelve el valor actual del reloj discreto."""
    raise NotImplementedError("Pendiente de implementación")


def cargar_escenario(ruta_json: str) -> None:
    """Carga un escenario JSON, inicializa el sistema, usuarios, semáforos y llegadas."""
    raise NotImplementedError("Pendiente de implementación")


def resumen_sistema() -> dict:
    """Devuelve resumen con claves: ``reloj``, ``procesos_activos``, ``marcos_libres``, ``bloques_libres``."""
    raise NotImplementedError("Pendiente de implementación")
