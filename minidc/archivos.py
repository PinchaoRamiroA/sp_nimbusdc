"""Sistema de archivos virtual, asignación de bloques y control de permisos."""


def formatear_disco() -> None:
    """Formatea el disco virtual, crea el usuario ``admin`` y el directorio raíz ``/``."""
    raise NotImplementedError("Pendiente de implementación")


def crear_usuario(nombre: str, grupo: str = "usuarios") -> None:
    """Crea un usuario en el sistema de archivos."""
    raise NotImplementedError("Pendiente de implementación")


def fs_mkdir(ruta: str, usuario: str) -> None:
    """Crea un directorio en ``ruta`` en nombre de ``usuario``."""
    raise NotImplementedError("Pendiente de implementación")


def fs_escribir(
    ruta: str,
    contenido: str,
    usuario: str,
    agregar: bool = False,
) -> int:
    """Escribe o agrega ``contenido`` en el archivo indicado y devuelve bytes escritos."""
    raise NotImplementedError("Pendiente de implementación")


def fs_leer(ruta: str, usuario: str) -> str:
    """Lee y devuelve el contenido completo del archivo en ``ruta``."""
    raise NotImplementedError("Pendiente de implementación")


def fs_listar(ruta: str, usuario: str) -> list:
    """Lista las entradas del directorio ``ruta``."""
    raise NotImplementedError("Pendiente de implementación")


def fs_eliminar(ruta: str, usuario: str, recursivo: bool = False) -> None:
    """Elimina un archivo o directorio (recursivamente si ``recursivo=True``)."""
    raise NotImplementedError("Pendiente de implementación")


def fs_chmod(ruta: str, modo: str, usuario: str) -> None:
    """Cambia los permisos octales (p. ej. ``"640"``) de ``ruta``."""
    raise NotImplementedError("Pendiente de implementación")


def fs_enlace_simbolico(destino: str, ruta_enlace: str, usuario: str) -> None:
    """Crea un enlace simbólico en ``ruta_enlace`` apuntando a ``destino``."""
    raise NotImplementedError("Pendiente de implementación")


def fs_info(ruta: str) -> dict:
    """Devuelve metadatos: ``tipo``, ``tamano``, ``propietario``, ``grupo``, ``modo``, ``bloques``."""
    raise NotImplementedError("Pendiente de implementación")


def fs_estado_disco() -> dict:
    """Devuelve ocupación del disco: ``bloques_totales``, ``bloques_libres``, ``huecos_libres``."""
    raise NotImplementedError("Pendiente de implementación")


def politica_asignacion_archivos() -> str:
    """Devuelve el nombre de la política de asignación de bloques elegida."""
    raise NotImplementedError("Pendiente de implementación")
