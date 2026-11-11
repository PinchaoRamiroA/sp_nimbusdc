"""Intérprete de comandos de administración de NimbusDC."""


def ejecutar_comando(linea: str, usuario: str = "admin") -> str:
    """Ejecuta un comando de consola en nombre de ``usuario`` y devuelve su salida.

    Los errores se devuelven como texto que comienza por ``Error:``.
    Comandos obligatorios:
    - Archivos: pwd, cd, ls, ls -l, mkdir, touch, cat, echo ... > / >>, rm, rm -r, chmod, ln -s, tree
    - Procesos: ps, kill PID, run NOMBRE, top, tick N
    - Recursos: free, df, whoami
    """
    raise NotImplementedError("Pendiente de implementación")


def directorio_actual(usuario: str = "admin") -> str:
    """Devuelve la ruta del directorio de trabajo actual de ``usuario``."""
    raise NotImplementedError("Pendiente de implementación")


def historial(usuario: str = "admin") -> list:
    """Devuelve la lista de comandos ejecutados por ``usuario``."""
    raise NotImplementedError("Pendiente de implementación")
