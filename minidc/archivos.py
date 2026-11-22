"""Sistema de archivos virtual, asignación de bloques y control de permisos.

El árbol de archivos son diccionarios anidados: cada nodo es un diccionario
y cada directorio guarda a sus hijos por nombre.

Asignación indexada: cada archivo guarda en su nodo la lista de bloques que
ocupa (su índice), como los punteros de un inodo en Unix. Los bloques no
tienen que estar seguidos.
Este módulo NO importa `kernel`, `procesos` ni `disco`: solo usa `errores`.
"""
import math

from minidc.errores import ErrorNoExiste, ErrorPermiso, ErrorSistema, ErrorYaExiste

# ---------------------------------------------------------------- estado
_bloques_totales = 200
_tam_bloque = 512       # bytes que caben en un bloque
_mapa_bloques = []      # un valor por bloque: True = ocupado, False = libre
_usuarios = {}          # nombre de usuario -> grupo
_raiz = None            # nodo del directorio "/"

_VALOR_PERMISO = {"r": 4, "w": 2, "x": 1}   # leer, escribir y pasar (entrar)
_MAX_SALTOS_ENLACE = 40                     # como Linux: evita dar vueltas para siempre


def reiniciar(config: dict) -> None:
    """Deja el sistema de archivos como nuevo. Lo llama kernel.iniciar_sistema."""
    global _bloques_totales, _tam_bloque
    _bloques_totales = config.get("bloques_disco", 200)
    _tam_bloque = config.get("tam_bloque", 512)
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
        "bloques": [],          # solo en archivos: su índice de bloques
        "destino": "",          # solo en enlaces: la ruta a la que apuntan
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


def _exigir_dueno(nodo: dict, usuario: str, ruta: str) -> None:
    """Lanza ErrorPermiso si ``usuario`` no es el dueño del nodo ni ``admin``."""
    if usuario != "admin" and usuario != nodo["propietario"]:
        raise ErrorPermiso(f"{usuario} no es el dueño de {ruta}")


def _exigir_directorio(nodo: dict, ruta: str) -> None:
    """Lanza ErrorSistema si el nodo no es un directorio."""
    if nodo["tipo"] != "directorio":
        raise ErrorSistema(f"No es un directorio: {ruta}")


def _modo_valido(modo: str) -> bool:
    """Indica si el modo son tres dígitos del 0 al 7, por ejemplo "640"."""
    if len(modo) != 3:
        return False
    for digito in modo:
        if digito not in "01234567":
            return False
    return True


def _partes(ruta: str) -> list:
    """Separa una ruta absoluta en nombres: "/a/b" -> ["a", "b"] y "/" -> []."""
    if not ruta.startswith("/"):
        raise ErrorSistema(f"La ruta debe empezar por '/': {ruta!r}")
    return [nombre for nombre in ruta.split("/") if nombre]


def _buscar(nombres: list, ruta: str, usuario: str | None,
            seguir_ultimo: bool = True, saltos: int = 0) -> dict:
    """Baja por el árbol desde la raíz siguiendo ``nombres`` y devuelve el nodo final.

    Si se indica ``usuario``, necesita permiso de paso ("x") en cada directorio
    que atraviesa. Los enlaces del camino se siguen; el del final solo si
    ``seguir_ultimo`` es True. ``ruta`` solo se usa en los mensajes de error.
    """
    nodo = _raiz
    for posicion, nombre in enumerate(nombres):
        if nodo["tipo"] != "directorio":
            raise ErrorNoExiste(f"No existe la ruta {ruta}")
        if usuario is not None:
            _exigir_permiso(nodo, usuario, "x", ruta)
        if nombre not in nodo["hijos"]:
            raise ErrorNoExiste(f"No existe la ruta {ruta}")
        nodo = nodo["hijos"][nombre]
        es_el_ultimo = posicion == len(nombres) - 1
        if nodo["tipo"] == "enlace" and (seguir_ultimo or not es_el_ultimo):
            nodo = _seguir_enlace(nodo, usuario, saltos)
    return nodo


def _seguir_enlace(enlace: dict, usuario: str | None, saltos: int) -> dict:
    """Devuelve el nodo al que apunta ``enlace``; si es otro enlace, lo sigue también."""
    if saltos >= _MAX_SALTOS_ENLACE:
        raise ErrorSistema("Demasiados enlaces seguidos (posible ciclo)")
    destino = enlace["destino"]
    return _buscar(_partes(destino), destino, usuario, True, saltos + 1)


def _buscar_padre(ruta: str, usuario: str) -> tuple:
    """Devuelve el directorio que contiene a ``ruta`` y el nombre final de la ruta."""
    nombres = _partes(ruta)
    if not nombres:
        raise ErrorSistema("Esta operación no se puede hacer sobre la raíz")
    padre = _buscar(nombres[:-1], ruta, usuario)
    _exigir_directorio(padre, ruta)
    return padre, nombres[-1]


def _bloques_necesarios(contenido: str) -> int:
    """Cuántos bloques ocupa un contenido: sus bytes entre el tamaño de bloque, hacia arriba."""
    return math.ceil(len(contenido.encode("utf-8")) / _tam_bloque)


def _ajustar_bloques(nodo: dict, necesarios: int) -> None:
    """Deja al nodo con ``necesarios`` bloques: reserva los que faltan o libera los que sobran.

    Es la política de asignación: los bloques nuevos son los primeros libres del
    disco, estén seguidos o no. Si no alcanzan, lanza ErrorSistema antes de
    cambiar nada, así el mapa nunca se descuadra.
    """
    faltan = necesarios - len(nodo["bloques"])
    if faltan > _mapa_bloques.count(False):
        raise ErrorSistema("No hay espacio suficiente en el disco")
    for numero in range(_bloques_totales):
        if faltan <= 0:
            break
        if not _mapa_bloques[numero]:
            _mapa_bloques[numero] = True
            nodo["bloques"].append(numero)
            faltan -= 1
    while len(nodo["bloques"]) > necesarios:
        numero = nodo["bloques"].pop()          # libera desde el final del índice
        _mapa_bloques[numero] = False


def _liberar_arbol(nodo: dict) -> None:
    """Devuelve al disco los bloques del nodo y los de todo lo que tenga dentro."""
    _ajustar_bloques(nodo, 0)
    for hijo in nodo["hijos"].values():
        _liberar_arbol(hijo)


def _revisar_borrado(directorio: dict, usuario: str, ruta: str) -> None:
    """Antes de un borrado recursivo, revisa que el usuario pueda borrar todo lo de adentro.

    Así, si algo no se puede borrar, se lanza ErrorPermiso sin haber borrado nada.
    """
    _exigir_permiso(directorio, usuario, "rwx", ruta)
    for hijo in directorio["hijos"].values():
        _exigir_dueno(hijo, usuario, ruta)
        if hijo["tipo"] == "directorio":
            _revisar_borrado(hijo, usuario, ruta)


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
    if not _partes(ruta):
        raise ErrorYaExiste("El directorio raíz ya existe")
    padre, nombre = _buscar_padre(ruta, usuario)
    _exigir_permiso(padre, usuario, "wx", ruta)
    if nombre in padre["hijos"]:
        raise ErrorYaExiste(f"Ya existe {ruta}")
    padre["hijos"][nombre] = _nuevo_nodo("directorio", usuario, "755")


def fs_escribir(
    ruta: str,
    contenido: str,
    usuario: str,
    agregar: bool = False,
) -> int:
    """Escribe o agrega ``contenido`` en el archivo indicado y devuelve los bytes escritos.

    Si el archivo no existe, lo crea con modo 644 (pide escribir y entrar en la
    carpeta). Si ya existe, pide permiso de escribir en el archivo. Si no hay
    espacio en el disco, lanza ErrorSistema sin cambiar nada.
    """
    _verificar_usuario(usuario)
    padre, nombre = _buscar_padre(ruta, usuario)
    existe = nombre in padre["hijos"]
    if existe:
        archivo = padre["hijos"][nombre]
        if archivo["tipo"] == "enlace":
            archivo = _seguir_enlace(archivo, usuario, 0)
        if archivo["tipo"] != "archivo":
            raise ErrorSistema(f"No es un archivo: {ruta}")
        _exigir_permiso(archivo, usuario, "w", ruta)
    else:
        _exigir_permiso(padre, usuario, "wx", ruta)
        archivo = _nuevo_nodo("archivo", usuario, "644")

    if agregar:
        nuevo_contenido = archivo["contenido"] + contenido
    else:
        nuevo_contenido = contenido
    _ajustar_bloques(archivo, _bloques_necesarios(nuevo_contenido))    # error si no cabe
    archivo["contenido"] = nuevo_contenido
    if not existe:
        padre["hijos"][nombre] = archivo        # se agrega solo si todo salió bien
    return len(contenido.encode("utf-8"))


def fs_leer(ruta: str, usuario: str) -> str:
    """Lee y devuelve el contenido completo del archivo en ``ruta``."""
    _verificar_usuario(usuario)
    archivo = _buscar(_partes(ruta), ruta, usuario)
    if archivo["tipo"] != "archivo":
        raise ErrorSistema(f"No es un archivo: {ruta}")
    _exigir_permiso(archivo, usuario, "r", ruta)
    return archivo["contenido"]


def fs_listar(ruta: str, usuario: str) -> list:
    """Lista los nombres de las entradas del directorio ``ruta``, en orden alfabético."""
    _verificar_usuario(usuario)
    directorio = _buscar(_partes(ruta), ruta, usuario)
    _exigir_directorio(directorio, ruta)
    _exigir_permiso(directorio, usuario, "r", ruta)
    return sorted(directorio["hijos"])


def fs_eliminar(ruta: str, usuario: str, recursivo: bool = False) -> None:
    """Elimina un archivo, enlace o directorio y libera sus bloques.

    Pide escribir y entrar en la carpeta que lo contiene y, además, ser el dueño
    o ``admin``. Un directorio con contenido solo se borra con ``recursivo=True``.
    Si es un enlace, se borra el enlace y no aquello a lo que apunta.
    """
    _verificar_usuario(usuario)
    padre, nombre = _buscar_padre(ruta, usuario)
    if nombre not in padre["hijos"]:
        raise ErrorNoExiste(f"No existe la ruta {ruta}")
    nodo = padre["hijos"][nombre]
    _exigir_permiso(padre, usuario, "wx", ruta)
    _exigir_dueno(nodo, usuario, ruta)
    if nodo["tipo"] == "directorio" and nodo["hijos"]:
        if not recursivo:
            raise ErrorSistema(f"El directorio no está vacío: {ruta}")
        _revisar_borrado(nodo, usuario, ruta)
    _liberar_arbol(nodo)
    del padre["hijos"][nombre]


def fs_chmod(ruta: str, modo: str, usuario: str) -> None:
    """Cambia los permisos de ``ruta`` a ``modo`` (tres dígitos octales, p. ej. ``"640"``).

    Solo puede hacerlo el dueño o ``admin``. Si la ruta es un enlace, cambia
    aquello a lo que apunta, como en Unix.
    """
    _verificar_usuario(usuario)
    modo = str(modo)
    if not _modo_valido(modo):
        raise ErrorSistema(f"Modo inválido: {modo!r} (deben ser tres dígitos del 0 al 7)")
    nodo = _buscar(_partes(ruta), ruta, usuario)
    _exigir_dueno(nodo, usuario, ruta)
    nodo["modo"] = modo


def fs_enlace_simbolico(destino: str, ruta_enlace: str, usuario: str) -> None:
    """Crea en ``ruta_enlace`` un enlace simbólico que apunta a ``destino``.

    El destino debe existir. Pide escribir y entrar en la carpeta donde se crea
    el enlace. El enlace queda con modo 777, porque los permisos que cuentan
    son los del destino, como en Unix.
    """
    _verificar_usuario(usuario)
    _buscar(_partes(destino), destino, usuario)     # ErrorNoExiste si el destino no existe
    padre, nombre = _buscar_padre(ruta_enlace, usuario)
    _exigir_permiso(padre, usuario, "wx", ruta_enlace)
    if nombre in padre["hijos"]:
        raise ErrorYaExiste(f"Ya existe {ruta_enlace}")
    enlace = _nuevo_nodo("enlace", usuario, "777")
    enlace["destino"] = destino
    padre["hijos"][nombre] = enlace


def fs_info(ruta: str) -> dict:
    """Devuelve metadatos: ``tipo``, ``tamano``, ``propietario``, ``grupo``, ``modo``, ``bloques``.

    ``tamano`` va en bytes y ``bloques`` es la lista de bloques que ocupa.
    Si la ruta es un enlace, describe al enlace mismo (su tamaño es el de la
    ruta destino). No recibe usuario, así que no revisa permisos.
    """
    nodo = _buscar(_partes(ruta), ruta, None, seguir_ultimo=False)
    if nodo["tipo"] == "enlace":
        tamano = len(nodo["destino"].encode("utf-8"))
    else:
        tamano = len(nodo["contenido"].encode("utf-8"))
    return {
        "tipo": nodo["tipo"],
        "tamano": tamano,
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
    """Devuelve el nombre de la política de asignación de bloques elegida."""
    return "indexada"


reiniciar({})   # estado válido desde el import
