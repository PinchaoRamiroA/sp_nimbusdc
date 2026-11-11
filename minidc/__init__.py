"""Paquete principal del sistema operativo simulado NimbusDC (`minidc`)."""

from . import (
    archivos,
    consola,
    disco,
    errores,
    kernel,
    memoria,
    procesos,
    sincronizacion,
)

__all__ = [
    "errores",
    "kernel",
    "procesos",
    "memoria",
    "disco",
    "archivos",
    "sincronizacion",
    "consola",
]
