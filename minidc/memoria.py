"""Gestión de memoria virtual paginada."""


def acceder_memoria(pid: int, direccion_virtual: int, escritura: bool = False) -> dict:
    """Traduce y accede a una dirección virtual del proceso ``pid``.

    Devuelve ``{"marco": int, "fallo_pagina": bool, "pagina_reemplazada": (pid, pagina) | None}``.
    Lanza ``ErrorMemoria`` si la dirección está fuera del espacio del proceso.
    """
    raise NotImplementedError("Pendiente de implementación")


def tabla_paginas(pid: int) -> dict:
    """Devuelve la tabla de páginas de ``pid``.

    Formato: ``{pagina: {"marco": int | None, "presente": bool, "modificada": bool, "referenciada": bool}}``.
    """
    raise NotImplementedError("Pendiente de implementación")


def liberar_memoria(pid: int) -> int:
    """Libera los marcos asignados al proceso ``pid`` y devuelve la cantidad liberada."""
    raise NotImplementedError("Pendiente de implementación")


def estado_memoria() -> dict:
    """Devuelve: marcos_totales, marcos_libres, marcos_por_proceso, fragmentacion_interna_bytes."""
    raise NotImplementedError("Pendiente de implementación")


def metricas_memoria() -> dict:
    """Devuelve: accesos, fallos_pagina, tasa_fallos, reemplazos, escrituras_a_swap."""
    raise NotImplementedError("Pendiente de implementación")


def detectar_hiperpaginacion() -> bool:
    """Indica si el sistema se encuentra en estado de hiperpaginación (thrashing)."""
    raise NotImplementedError("Pendiente de implementación")


def politica_reemplazo() -> str:
    """Devuelve el nombre de la política de reemplazo de páginas elegida."""
    raise NotImplementedError("Pendiente de implementación")
