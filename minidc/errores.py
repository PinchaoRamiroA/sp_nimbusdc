"""Excepciones del núcleo simulado NimbusDC (`minidc`)."""


class ErrorSistema(Exception):
    """Excepción base para todos los errores del sistema operativo simulado."""


class ErrorPermiso(ErrorSistema):
    """Error lanzado cuando un usuario intenta una operación sin permisos."""


class ErrorNoExiste(ErrorSistema):
    """Error lanzado cuando un recurso solicitado no existe."""


class ErrorYaExiste(ErrorSistema):
    """Error lanzado cuando se intenta crear un recurso que ya existe."""


class ErrorMemoria(ErrorSistema):
    """Error lanzado ante accesos inválidos o fallos de gestión de memoria."""


class ErrorSincronizacion(ErrorSistema):
    """Error lanzado ante operaciones inválidas de semáforos o mutex."""
