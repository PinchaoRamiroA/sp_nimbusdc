"""Planificación de E/S de disco y caché de bloques."""


def encolar_solicitud_disco(pid: int, bloque: int, operacion: str) -> int:
    """Encola una solicitud de disco (``operacion``: ``"L"`` o ``"E"``) y devuelve su ID."""
    raise NotImplementedError("Pendiente de implementación")


def procesar_disco() -> list:
    """Atiende todas las solicitudes pendientes y devuelve el orden de bloques atendidos."""
    raise NotImplementedError("Pendiente de implementación")


def cola_disco() -> list:
    """Devuelve los bloques pendientes en el orden de atención previsto."""
    raise NotImplementedError("Pendiente de implementación")


def metricas_disco() -> dict:
    """Devuelve: solicitudes_atendidas, desplazamiento_total, posicion_cabezal."""
    raise NotImplementedError("Pendiente de implementación")


def info_cache() -> dict:
    """Devuelve: capacidad_bloques, aciertos, fallos, tasa_aciertos."""
    raise NotImplementedError("Pendiente de implementación")


def politica_disco() -> str:
    """Devuelve el nombre de la política de planificación de disco elegida."""
    raise NotImplementedError("Pendiente de implementación")
