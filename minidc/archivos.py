"""Sistema de archivos virtual, asignación de bloques y control de permisos.

Prototipo 1 (avance): usuarios, directorios, permisos tipo Unix y mapa de bloques.
Quedan para el Prototipo 2: escribir, leer, eliminar, chmod y enlaces simbólicos.

El árbol de archivos son diccionarios anidados: cada nodo es un diccionario
y cada directorio guarda a sus hijos por nombre.
Este módulo NO importa `kernel`, `procesos` ni `disco`: solo usa `errores`.
"""
from minidc.errores import ErrorNoExiste, ErrorPermiso, ErrorSistema, ErrorYaExiste

# ---------------------------------------------------------------- estado
_bloques_totales = 200
_mapa_bloques = []      # un valor por bloque: True = ocupado, False = libre
_usuarios = {}          # nombre de usuario -> grupo
_raiz = None            # nodo del directorio "/"

_VALOR_PERMISO = {"r": 4, "w": 2, "x": 1}   # leer, escribir y pasar (entrar)


def reiniciar(config: dict) -> None:
    """Deja el sistema de archivos como nuevo. Lo debe llamar kernel.iniciar_sistema."""
    global _bloques_totales
    _bloques_totales = config.get("bloques_disco", 200)
    formatear_disco()


# ---------------------------------------------------- funciones internas
def _nuevo_nodo(tipo: str, propietario: str, modo: str) -> dict:
    """Crea un nodo del árbol. ``tipo``: "archivo", "directorio" o "enlace"."""
    return {
        "tipo": tipo,
        "propietario": propietario,
        "grupo": _usuarios[propietario],
        "modo": modo,           # permisos en octal: propietario, grupo y otros
        "hijos": {},            # solo en directorios: nombre -> nodo
        "contenido": "",        # solo en archivos
        "bloques": [],          # números de los bloques de disco que ocupa
    }


def _verificar_usuario(usuario: str) -> None:
    """Lanza ErrorNoExiste si el usuario no fue creado."""
    if usuario not in _usuarios:
        raise ErrorNoExiste(f"No existe el usuario {usuario!r}")


def _tiene_permiso(nodo: dict, usuario: str, permiso: str) -> bool:
    """Indica si ``usuario`` tiene el permiso "r", "w" o "x" sobre ``nodo``.

    Como en Unix: se mira un solo dígito del modo, según si el usuario es el
    propietario, es de su grupo o es otro. ``admin`` ignora los permisos.
    """
    if usuario == "admin":
        return True
    if usuario == nodo["propietario"]:
        digito = nodo["modo"][0]
    elif _usuarios[usuario] == nodo["grupo"]:
        digito = nodo["modo"][1]
    else:
        digito = nodo["modo"][2]
    return (int(digito) & _VALOR_PERMISO[permiso]) != 0


def _exigir_permiso(nodo: dict, usuario: str, permisos: str, ruta: str) -> None:
    """Lanza ErrorPermiso si a ``usuario`` le falta alguno de los ``permisos``."""
    for permiso in permisos:
        if not _tiene_permiso(nodo, usuario, permiso):
            raise ErrorPermiso(f"{usuario} no tiene permiso '{permiso}' en {ruta}")


def _exigir_directorio(nodo: dict, ruta: str) -> None:
    """Lanza ErrorSistema si el nodo no es un directorio."""
    if nodo["tipo"] != "directorio":
        raise ErrorSistema(f"No es un directorio: {ruta}")


def _partes(ruta: str) -> list:
    """Separa una ruta absoluta en nombres: "/a/b" -> ["a", "b"] y "/" -> []."""
    if not ruta.startswith("/"):
        raise ErrorSistema(f"La ruta debe empezar por '/': {ruta!r}")
    return [nombre for nombre in ruta.split("/") if nombre]


def _buscar(nombres: list, ruta: str, usuario: str | None) -> dict:
    """Baja por el árbol desde la raíz siguiendo ``nombres`` y devuelve el nodo final.

    Si se indica ``usuario``, necesita permiso de paso ("x") en cada directorio
    que atraviesa. ``ruta`` solo se usa en los mensajes de error.
    """
    nodo = _raiz
    for nombre in nombres:
        if nodo["tipo"] != "directorio":
            raise ErrorNoExiste(f"No existe la ruta {ruta}")
        if usuario is not None:
            _exigir_permiso(nodo, usuario, "x", ruta)
        if nombre not in nodo["hijos"]:
            raise ErrorNoExiste(f"No existe la ruta {ruta}")
        nodo = nodo["hijos"][nombre]
    return nodo


def _contar_huecos() -> int:
    """Cuenta los grupos de bloques libres seguidos (mide la fragmentación)."""
    huecos = 0
    anterior_ocupado = True
    for ocupado in _mapa_bloques:
        if not ocupado and anterior_ocupado:
            huecos += 1
        anterior_ocupado = ocupado
    return huecos


# ------------------------------------------------- funciones del enunciado
def formatear_disco() -> None:
    """Formatea el disco virtual, crea el usuario ``admin`` y el directorio raíz ``/``.

    Borra los archivos y usuarios anteriores y deja todos los bloques libres.
    La raíz queda con modo 777 para que cualquier usuario pueda crear dentro de
    ella (el enunciado no tiene una función para cambiar el propietario).
    """
    global _mapa_bloques, _usuarios, _raiz
    _mapa_bloques = [False] * _bloques_totales
    _usuarios = {"admin": "admin"}
    _raiz = _nuevo_nodo("directorio", "admin", "777")


def crear_usuario(nombre: str, grupo: str = "usuarios") -> None:
    """Crea un usuario en el sistema de archivos."""
    if nombre in _usuarios:
        raise ErrorYaExiste(f"Ya existe el usuario {nombre!r}")
    _usuarios[nombre] = grupo


def fs_mkdir(ruta: str, usuario: str) -> None:
    """Crea un directorio en ``ruta`` en nombre de ``usuario``."""
    _verificar_usuario(usuario)
    nombres = _partes(ruta)
    if not nombres:
        raise ErrorYaExiste("El directorio raíz ya existe")
    padre = _buscar(nombres[:-1], ruta, usuario)
    _exigir_directorio(padre, ruta)
    _exigir_permiso(padre, usuario, "wx", ruta)
    nombre = nombres[-1]
    if nombre in padre["hijos"]:
        raise ErrorYaExiste(f"Ya existe {ruta}")
    padre["hijos"][nombre] = _nuevo_nodo("directorio", usuario, "755")


def fs_escribir(
    ruta: str,
    contenido: str,
    usuario: str,
    agregar: bool = False,
) -> int:
    """Escribe o agrega ``contenido`` en el archivo indicado y devuelve bytes escritos."""
    raise NotImplementedError("Pendiente: Prototipo 2")


def fs_leer(ruta: str, usuario: str) -> str:
    """Lee y devuelve el contenido completo del archivo en ``ruta``."""
    raise NotImplementedError("Pendiente: Prototipo 2")


def fs_listar(ruta: str, usuario: str) -> list:
    """Lista los nombres de las entradas del directorio ``ruta``, en orden alfabético."""
    _verificar_usuario(usuario)
    directorio = _buscar(_partes(ruta), ruta, usuario)
    _exigir_directorio(directorio, ruta)
    _exigir_permiso(directorio, usuario, "r", ruta)
    return sorted(directorio["hijos"])


def fs_eliminar(ruta: str, usuario: str, recursivo: bool = False) -> None:
    """Elimina un archivo o directorio (recursivamente si ``recursivo=True``)."""
    raise NotImplementedError("Pendiente: Prototipo 2")


def fs_chmod(ruta: str, modo: str, usuario: str) -> None:
    """Cambia los permisos octales (p. ej. ``"640"``) de ``ruta``."""
    raise NotImplementedError("Pendiente: Prototipo 2")


def fs_enlace_simbolico(destino: str, ruta_enlace: str, usuario: str) -> None:
    """Crea un enlace simbólico en ``ruta_enlace`` apuntando a ``destino``."""
    raise NotImplementedError("Pendiente: Prototipo 2")


def fs_info(ruta: str) -> dict:
    """Devuelve metadatos: ``tipo``, ``tamano``, ``propietario``, ``grupo``, ``modo``, ``bloques``.

    ``tamano`` va en bytes y ``bloques`` es la lista de bloques que ocupa.
    No recibe usuario, así que no revisa permisos.
    """
    nodo = _buscar(_partes(ruta), ruta, None)
    return {
        "tipo": nodo["tipo"],
        "tamano": len(nodo["contenido"].encode("utf-8")),
        "propietario": nodo["propietario"],
        "grupo": nodo["grupo"],
        "modo": nodo["modo"],
        "bloques": list(nodo["bloques"]),   # copia: no se entrega la lista interna
    }


def fs_estado_disco() -> dict:
    """Devuelve ocupación del disco: ``bloques_totales``, ``bloques_libres``, ``huecos_libres``."""
    return {
        "bloques_totales": _bloques_totales,
        "bloques_libres": _mapa_bloques.count(False),
        "huecos_libres": _contar_huecos(),
    }


def politica_asignacion_archivos() -> str:
    """Devuelve el nombre de la política de asignación de bloques elegida.

    Prototipo 1: todavía no se reservan bloques; eso llega con fs_escribir
    en el Prototipo 2.
    """
    return "indexada"


reiniciar({})   # estado válido desde el import
