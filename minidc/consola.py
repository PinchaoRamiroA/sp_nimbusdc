"""Intérprete de comandos de administración de NimbusDC.

Implementa los comandos obligatorios del núcleo simulado y los equivalentes
de Windows como bonificación. Los errores siempre se devuelven como cadenas
de texto que comienzan por ``Error:``.
"""
import shlex

from minidc import archivos, disco, kernel, memoria, procesos
from minidc.errores import ErrorNoExiste, ErrorPermiso, ErrorSistema, ErrorYaExiste

# ---------------------------------------------------------------- estado interno
_directorios: dict[str, str] = {}
_historiales: dict[str, list[str]] = {}


def reiniciar() -> None:
    """Reinicia el estado de la consola (directorios actuales e historial)."""
    global _directorios, _historiales
    _directorios = {}
    _historiales = {}


def directorio_actual(usuario: str = "admin") -> str:
    """Devuelve la ruta del directorio de trabajo actual de ``usuario``."""
    return _directorios.get(usuario, "/")


def historial(usuario: str = "admin") -> list:
    """Devuelve una copia de la lista de comandos ejecutados por ``usuario``."""
    return list(_historiales.get(usuario, []))


def _resolver_ruta(ruta: str, usuario: str) -> str:
    """Resuelve una ruta relativa o absoluta al espacio canónico absoluto del sistema."""
    if not ruta:
        return directorio_actual(usuario)

    ruta_norm = ruta.replace("\\", "/")
    if ruta_norm.startswith("/"):
        partes_base = []
        segmentos = ruta_norm.strip("/").split("/")
    else:
        actual = directorio_actual(usuario)
        partes_base = [p for p in actual.strip("/").split("/") if p]
        segmentos = ruta_norm.split("/")

    for seg in segmentos:
        if not seg or seg == ".":
            continue
        elif seg == "..":
            if partes_base:
                partes_base.pop()
        else:
            partes_base.append(seg)

    return "/" + "/".join(partes_base)


# ---------------------------------------------------------------- comandos: procesos
def _cmd_ps(args: list[str], usuario: str) -> str:
    """Muestra la lista de procesos simulados."""
    procs = procesos.listar_procesos()
    lineas = ["PID NOMBRE USUARIO ESTADO"]
    for p in procs:
        lineas.append(f"{p['pid']} {p['nombre']} {p['usuario']} {p['estado']}")
    return "\n".join(lineas)


def _cmd_kill(args: list[str], usuario: str) -> str:
    """Termina un proceso por su PID."""
    if not args:
        return "Error: se requiere el PID del proceso"

    pid_str = args[0]
    # Soporte para banderas tipo Windows: taskkill /pid 2 o taskkill /PID 2
    if pid_str.lower() in ("/pid", "-pid") and len(args) > 1:
        pid_str = args[1]

    try:
        pid = int(pid_str)
    except ValueError:
        return f"Error: PID inválido '{pid_str}'"

    try:
        procesos.terminar_proceso(pid)
    except ErrorNoExiste as e:
        return f"Error: {e}"
    except ErrorSistema as e:
        return f"Error: {e}"

    return f"Proceso {pid} terminado"


def _cmd_run(args: list[str], usuario: str) -> str:
    """Crea y encola un proceso a partir de un servicio del catálogo del escenario."""
    if not args:
        return "Error: se requiere el nombre del servicio a ejecutar"

    nombre = args[0]
    catalogo = kernel.obtener_catalogo()

    if nombre not in catalogo:
        return f"Error: servicio '{nombre}' no encontrado en el catálogo del escenario"

    servicio = catalogo[nombre]
    try:
        pid = procesos.crear_proceso(
            nombre=nombre,
            usuario=usuario,
            programa=servicio["programa"],
            memoria_bytes=servicio.get("memoria_bytes", 4096),
            cuota_marcos=servicio.get("cuota_marcos", 4),
            prioridad=servicio.get("prioridad", 0),
        )
    except ErrorSistema as e:
        return f"Error: {e}"

    return f"Proceso {nombre} creado con PID {pid}"


def _cmd_tick(args: list[str], usuario: str) -> str:
    """Avanza 1 o N ticks en el reloj discreto del sistema."""
    if not args:
        n = 1
    else:
        try:
            n = int(args[0])
        except ValueError:
            return f"Error: cantidad de ticks inválida '{args[0]}'"

    if n <= 0:
        return "Error: la cantidad de ticks debe ser mayor que cero"

    if n == 1:
        kernel.tick()
        return f"Avanzado 1 tick. Reloj actual: {kernel.reloj_actual()}"

    kernel.ejecutar_ticks(n)
    return f"Avanzados {n} ticks. Reloj actual: {kernel.reloj_actual()}"


def _cmd_top(args: list[str], usuario: str) -> str:
    """Muestra una instantánea de métricas y procesos activos del sistema."""
    reloj = kernel.reloj_actual()
    metricas = procesos.metricas_planificacion()
    todos = procesos.listar_procesos()
    activos = [p for p in todos if p["estado"] != "TERMINADO"]

    util_pct = round(metricas.get("utilizacion_cpu", 0.0) * 100, 2)
    lineas = [
        f"Reloj: {reloj} | Utilización CPU: {util_pct}% | Cambios de contexto: {metricas.get('cambios_contexto', 0)}",
        f"Procesos terminados: {metricas.get('procesos_terminados', 0)} | Activos: {len(activos)} | Espera prom: {metricas.get('espera_promedio', 0.0):.2f}",
        "PID NOMBRE USUARIO ESTADO PRIORIDAD CPU_USADA TIEMPO_ESPERA",
    ]
    for p in activos:
        lineas.append(
            f"{p['pid']} {p['nombre']} {p['usuario']} {p['estado']} "
            f"{p['prioridad']} {p['cpu_usada']} {p['tiempo_espera']}"
        )
    return "\n".join(lineas)


# ---------------------------------------------------------------- comandos: archivos
def _cmd_pwd(args: list[str], usuario: str) -> str:
    """Devuelve el directorio actual del usuario."""
    return directorio_actual(usuario)


def _cmd_cd(args: list[str], usuario: str) -> str:
    """Cambia el directorio actual del usuario."""
    destino = args[0] if args else "/"
    nueva_ruta = _resolver_ruta(destino, usuario)

    # Si la ruta existe en archivos, verificar que sea directorio y permisos de paso
    try:
        info = archivos.fs_info(nueva_ruta)
        if info["tipo"] != "directorio":
            return f"Error: no es un directorio: {nueva_ruta}"
        archivos.fs_listar(nueva_ruta, usuario)
    except ErrorPermiso as e:
        return f"Error: {e}"
    except (ErrorNoExiste, ErrorSistema):
        # Permitir navegación si no está restringida explícitamente
        pass

    _directorios[usuario] = nueva_ruta
    return ""


def _cmd_ls(args: list[str], usuario: str, forzar_largo: bool = False) -> str:
    """Lista las entradas de un directorio (soporta -l y dir)."""
    formato_largo = forzar_largo
    rutas = []
    for a in args:
        if a in ("-l", "-la", "-al"):
            formato_largo = True
        elif not a.startswith("-"):
            rutas.append(a)

    destino = rutas[0] if rutas else "."
    ruta_abs = _resolver_ruta(destino, usuario)

    try:
        entradas = archivos.fs_listar(ruta_abs, usuario)
    except ErrorSistema as e:
        # Puede ser un archivo individual
        try:
            info = archivos.fs_info(ruta_abs)
            nombre = ruta_abs.split("/")[-1] or "/"
            if formato_largo:
                prefix = "d" if info["tipo"] == "directorio" else ("l" if info["tipo"] == "enlace" else "-")
                return f"{prefix}{info['modo']} {info['propietario']} {info['grupo']} {info['tamano']:>6} {nombre}"
            return nombre
        except Exception:
            return f"Error: {e}"

    if not entradas:
        return ""

    if formato_largo:
        lineas = []
        for nombre in entradas:
            subruta = f"{ruta_abs.rstrip('/')}/{nombre}"
            try:
                info = archivos.fs_info(subruta)
                prefix = "d" if info["tipo"] == "directorio" else ("l" if info["tipo"] == "enlace" else "-")
                lineas.append(
                    f"{prefix}{info['modo']} {info['propietario']} {info['grupo']} {info['tamano']:>6} {nombre}"
                )
            except ErrorSistema:
                lineas.append(f"?????? ??? ??? ?????? {nombre}")
        return "\n".join(lineas)

    return "  ".join(entradas)


def _cmd_mkdir(args: list[str], usuario: str) -> str:
    """Crea un directorio."""
    if not args:
        return "Error: se requiere la ruta del directorio"
    ruta_abs = _resolver_ruta(args[0], usuario)
    try:
        archivos.fs_mkdir(ruta_abs, usuario)
        return ""
    except ErrorSistema as e:
        return f"Error: {e}"


def _cmd_touch(args: list[str], usuario: str) -> str:
    """Crea un archivo vacío o actualiza su existencia."""
    if not args:
        return "Error: se requiere la ruta del archivo"
    ruta_abs = _resolver_ruta(args[0], usuario)
    try:
        archivos.fs_escribir(ruta_abs, "", usuario, agregar=True)
        return ""
    except ErrorSistema as e:
        return f"Error: {e}"


def _cmd_cat(args: list[str], usuario: str) -> str:
    """Muestra el contenido de un archivo."""
    if not args:
        return "Error: se requiere la ruta del archivo"
    ruta_abs = _resolver_ruta(args[0], usuario)
    try:
        return archivos.fs_leer(ruta_abs, usuario)
    except ErrorSistema as e:
        return f"Error: {e}"


def _cmd_echo(args: list[str], usuario: str) -> str:
    """Imprime texto o lo redirige a un archivo (> sobrescribe, >> agrega)."""
    # 1. Caso estándar: operador separado ">" o ">>"
    idx_redir = -1
    agregar = False
    for i, a in enumerate(args):
        if a == ">>":
            idx_redir = i
            agregar = True
            break
        elif a == ">":
            idx_redir = i
            agregar = False
            break

    if idx_redir != -1:
        texto = " ".join(args[:idx_redir])
        if idx_redir + 1 >= len(args):
            return "Error: se requiere la ruta del archivo de destino para la redirección"
        destino = args[idx_redir + 1]
        ruta_abs = _resolver_ruta(destino, usuario)
        try:
            archivos.fs_escribir(ruta_abs, texto, usuario, agregar=agregar)
            return ""
        except ErrorSistema as e:
            return f"Error: {e}"

    # 2. Caso con operador pegado dentro de un token, e.g. "echo texto>archivo" o ">archivo"
    for i, a in enumerate(args):
        if ">>" in a:
            antes, dest = a.split(">>", 1)
            texto = (" ".join(args[:i]) + (" " + antes if antes else "")).strip()
            if not dest:
                if i + 1 < len(args):
                    dest = args[i + 1]
                else:
                    return "Error: se requiere la ruta del archivo de destino para la redirección"
            ruta_abs = _resolver_ruta(dest, usuario)
            try:
                archivos.fs_escribir(ruta_abs, texto, usuario, agregar=True)
                return ""
            except ErrorSistema as e:
                return f"Error: {e}"
        elif ">" in a:
            antes, dest = a.split(">", 1)
            texto = (" ".join(args[:i]) + (" " + antes if antes else "")).strip()
            if not dest:
                if i + 1 < len(args):
                    dest = args[i + 1]
                else:
                    return "Error: se requiere la ruta del archivo de destino para la redirección"
            ruta_abs = _resolver_ruta(dest, usuario)
            try:
                archivos.fs_escribir(ruta_abs, texto, usuario, agregar=False)
                return ""
            except ErrorSistema as e:
                return f"Error: {e}"

    return " ".join(args)


def _cmd_rm(args: list[str], usuario: str) -> str:
    """Elimina un archivo o directorio (recursivo con -r / -R)."""
    if not args:
        return "Error: se requiere la ruta a eliminar"

    recursivo = False
    rutas = []
    for a in args:
        if a in ("-r", "-R", "-rf", "-fr", "/s", "/S"):
            recursivo = True
        else:
            rutas.append(a)

    if not rutas:
        return "Error: se requiere la ruta a eliminar"

    ruta_abs = _resolver_ruta(rutas[0], usuario)
    try:
        archivos.fs_eliminar(ruta_abs, usuario, recursivo=recursivo)
        return ""
    except ErrorSistema as e:
        return f"Error: {e}"


def _cmd_chmod(args: list[str], usuario: str) -> str:
    """Cambia los permisos octales de una ruta."""
    if len(args) < 2:
        return "Error: uso: chmod <modo> <ruta>"
    modo = args[0]
    ruta_abs = _resolver_ruta(args[1], usuario)
    try:
        archivos.fs_chmod(ruta_abs, modo, usuario)
        return ""
    except ErrorSistema as e:
        return f"Error: {e}"


def _cmd_ln(args: list[str], usuario: str) -> str:
    """Crea un enlace simbólico (ln -s <destino> <ruta_enlace>)."""
    es_simbolico = False
    rutas = []
    for a in args:
        if a == "-s":
            es_simbolico = True
        else:
            rutas.append(a)

    if not es_simbolico or len(rutas) < 2:
        return "Error: uso: ln -s <destino> <ruta_enlace>"

    destino_abs = _resolver_ruta(rutas[0], usuario)
    enlace_abs = _resolver_ruta(rutas[1], usuario)
    try:
        archivos.fs_enlace_simbolico(destino_abs, enlace_abs, usuario)
        return ""
    except ErrorSistema as e:
        return f"Error: {e}"


def _cmd_mklink(args: list[str], usuario: str) -> str:
    """Equivalente en Windows para enlaces (mklink [/d] <enlace> <destino>)."""
    # Filtrar banderas de Windows como /D, /H, /J
    rutas = [a for a in args if a.lower() not in ("/d", "/h", "/j")]
    if len(rutas) < 2:
        return "Error: uso: mklink <enlace> <destino>"
    enlace_abs = _resolver_ruta(rutas[0], usuario)
    destino_abs = _resolver_ruta(rutas[1], usuario)
    try:
        archivos.fs_enlace_simbolico(destino_abs, enlace_abs, usuario)
        return ""
    except ErrorSistema as e:
        return f"Error: {e}"


def _cmd_tree(args: list[str], usuario: str) -> str:
    """Muestra el árbol de directorios y archivos de forma jerárquica."""
    ruta = args[0] if args else "."
    ruta_abs = _resolver_ruta(ruta, usuario)

    try:
        info_raiz = archivos.fs_info(ruta_abs)
    except ErrorSistema as e:
        return f"Error: {e}"

    if info_raiz["tipo"] != "directorio":
        return f"Error: no es un directorio: {ruta_abs}"

    lineas = [ruta_abs]

    def _recorrer(dir_abs: str, prefijo: str = "") -> None:
        try:
            entradas = archivos.fs_listar(dir_abs, usuario)
        except ErrorPermiso:
            lineas.append(f"{prefijo}[permiso denegado]")
            return
        except ErrorSistema:
            return

        total = len(entradas)
        for i, nombre in enumerate(entradas):
            es_ultimo = (i == total - 1)
            conector = "└── " if es_ultimo else "├── "
            subruta = f"{dir_abs.rstrip('/')}/{nombre}"

            try:
                info = archivos.fs_info(subruta)
                tipo = info["tipo"]
            except ErrorSistema:
                tipo = "desconocido"

            if tipo == "directorio":
                lineas.append(f"{prefijo}{conector}{nombre}")
                nuevo_prefijo = prefijo + ("    " if es_ultimo else "│   ")
                _recorrer(subruta, nuevo_prefijo)
            elif tipo == "enlace":
                lineas.append(f"{prefijo}{conector}{nombre} -> [enlace]")
            else:
                lineas.append(f"{prefijo}{conector}{nombre}")

    _recorrer(ruta_abs)
    return "\n".join(lineas)


# ---------------------------------------------------------------- comandos: recursos
def _cmd_free(args: list[str], usuario: str) -> str:
    """Muestra el estado y estadísticas de la memoria virtual."""
    est = memoria.estado_memoria()
    met = memoria.metricas_memoria()

    totales = est.get("marcos_totales", 0)
    libres = est.get("marcos_libres", 0)
    usados = totales - libres
    frag = est.get("fragmentacion_interna_bytes", 0)

    tasa = met.get("tasa_fallos", 0.0) * 100

    return (
        f"Memoria física (política: {memoria.politica_reemplazo()}):\n"
        f"  Total: {totales} marcos | Usados: {usados} | Libres: {libres} | Fragmentación interna: {frag} bytes\n"
        f"Métricas:\n"
        f"  Accesos: {met.get('accesos', 0)} | Fallos de página: {met.get('fallos_pagina', 0)} ({tasa:.1f}%) | "
        f"Reemplazos: {met.get('reemplazos', 0)} | Swap: {met.get('escrituras_a_swap', 0)}"
    )


def _cmd_df(args: list[str], usuario: str) -> str:
    """Muestra el uso y disponibilidad del disco virtual."""
    est = archivos.fs_estado_disco()
    tot = est.get("bloques_totales", 0)
    lib = est.get("bloques_libres", 0)
    usados = tot - lib
    huecos = est.get("huecos_libres", 0)
    pct = (usados / tot * 100) if tot > 0 else 0.0

    return (
        "SistemaArchivos  Bloques  Usados  Libres   Uso%  Huecos  Política\n"
        f"/dev/disco0       {tot:>6}  {usados:>6}  {lib:>6}  {pct:>4.1f}%  {huecos:>6}  {archivos.politica_asignacion_archivos()}"
    )


def _cmd_whoami(args: list[str], usuario: str) -> str:
    """Devuelve el nombre del usuario actual."""
    return str(usuario)


# ---------------------------------------------------------------- comandos: utilidades
def _cmd_load(args: list[str], usuario: str) -> str:
    """Carga un escenario JSON en el sistema."""
    if not args:
        return "Error: se requiere la ruta del archivo de escenario JSON"
    # Soportar rutas con espacios aunque no estén entrecomilladas
    ruta = " ".join(args).strip("\"'")
    try:
        kernel.cargar_escenario(ruta)
        cat = kernel.obtener_catalogo()
        servicios = ", ".join(cat.keys()) if cat else "ninguno"
        return f"Escenario cargado exitosamente desde '{ruta}'. Catálogo disponible: [{servicios}]"
    except ErrorSistema as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error: {e}"


def _cmd_clear(args: list[str], usuario: str) -> str:
    """Limpia la pantalla de la consola."""
    import os
    os.system("cls" if os.name == "nt" else "clear")
    return ""


def _cmd_help(args: list[str], usuario: str) -> str:
    """Muestra la lista de comandos disponibles en la consola."""
    return (
        "Comandos disponibles (Prototipo 2):\n"
        "  Procesos:\n"
        "    ps / tasklist       : Lista los procesos del sistema (PID NOMBRE USUARIO ESTADO)\n"
        "    run NOMBRE          : Crea y encola un proceso del catálogo del escenario\n"
        "    kill PID / taskkill : Termina un proceso y libera sus recursos\n"
        "    tick [N]            : Avanza 1 o N ticks discretos en el reloj del kernel\n"
        "    top                 : Muestra una instantánea de métricas y procesos activos\n"
        "  Archivos:\n"
        "    pwd                 : Muestra el directorio de trabajo actual\n"
        "    cd [RUTA]           : Cambia de directorio de trabajo\n"
        "    ls [-l] / dir [RUTA]: Lista entradas de un directorio (soporta formato largo)\n"
        "    mkdir / md RUTA     : Crea un directorio\n"
        "    touch RUTA          : Crea un archivo vacío\n"
        "    cat / type RUTA     : Muestra el contenido de un archivo\n"
        "    echo TEXTO [> | >>]: Imprime o redirige texto a un archivo (> escribe, >> agrega)\n"
        "    rm [-r] / del RUTA  : Elimina un archivo o directorio (recursivo con -r)\n"
        "    chmod MODO RUTA     : Cambia los permisos octales de una ruta (ej. 640)\n"
        "    ln -s DEST ENLACE   : Crea un enlace simbólico (o mklink ENLACE DEST)\n"
        "    tree [RUTA]         : Muestra el árbol jerárquico de archivos y directorios\n"
        "  Recursos:\n"
        "    free                : Muestra estado, marcos, fragmentación y fallos de memoria\n"
        "    df                  : Muestra estado, bloques y fragmentación del disco\n"
        "    whoami              : Muestra el usuario activo actual\n"
        "  Utilidades:\n"
        "    load RUTA           : Carga un escenario JSON (usuarios, semáforos, catálogo)\n"
        "    clear / cls         : Limpia la pantalla de la consola\n"
        "    su USUARIO          : Cambia el usuario activo (en modo interactivo)\n"
        "    salir / exit / quit : Cierra la sesión interactiva"
    )


# Mapa de comandos soportados en el Prototipo 2 (y equivalentes de Windows)
_COMANDOS = {
    # Procesos
    "ps": _cmd_ps,
    "tasklist": _cmd_ps,
    "kill": _cmd_kill,
    "taskkill": _cmd_kill,
    "run": _cmd_run,
    "tick": _cmd_tick,
    "top": _cmd_top,
    # Archivos
    "pwd": _cmd_pwd,
    "cd": _cmd_cd,
    "ls": _cmd_ls,
    "dir": lambda args, u: _cmd_ls(args, u, forzar_largo=True),
    "mkdir": _cmd_mkdir,
    "md": _cmd_mkdir,
    "touch": _cmd_touch,
    "cat": _cmd_cat,
    "type": _cmd_cat,
    "echo": _cmd_echo,
    "rm": _cmd_rm,
    "del": _cmd_rm,
    "chmod": _cmd_chmod,
    "ln": _cmd_ln,
    "mklink": _cmd_mklink,
    "tree": _cmd_tree,
    # Recursos
    "free": _cmd_free,
    "df": _cmd_df,
    "whoami": _cmd_whoami,
    # Utilidades
    "load": _cmd_load,
    "cargar": _cmd_load,
    "clear": _cmd_clear,
    "cls": _cmd_clear,
    "help": _cmd_help,
}


def ejecutar_comando(linea: str, usuario: str = "admin") -> str:
    """Ejecuta un comando de consola en nombre de ``usuario`` y devuelve su salida.

    Los errores se devuelven como texto que comienza por ``Error:``.
    Comandos soportados en el Prototipo 2:
    - Procesos: ``ps`` / ``tasklist``, ``kill`` / ``taskkill``, ``run``, ``tick``, ``top``
    - Archivos: ``pwd``, ``cd``, ``ls`` / ``dir``, ``mkdir`` / ``md``, ``touch``,
                ``cat`` / ``type``, ``echo ... > / >>``, ``rm`` / ``del``,
                ``chmod``, ``ln -s`` / ``mklink``, ``tree``
    - Recursos: ``free``, ``df``, ``whoami``
    """
    if not isinstance(linea, str):
        return "Error: la línea de comando debe ser una cadena de texto"

    linea_limpia = linea.strip()
    if not linea_limpia:
        return ""

    # Registrar en el historial del usuario
    _historiales.setdefault(usuario, []).append(linea_limpia)

    try:
        partes = shlex.split(linea_limpia.replace("\\", "/"))
    except ValueError as e:
        return f"Error: sintaxis de comando inválida ({e})"

    if not partes:
        return ""

    cmd = partes[0].lower()
    args = partes[1:]

    manejador = _COMANDOS.get(cmd)
    if manejador is None:
        return f"Error: comando '{cmd}' no reconocido"

    try:
        return manejador(args, usuario)
    except ErrorSistema as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error: {e}"


def iniciar_consola_interactiva(
    escenario_inicial: str | None = None,
    usuario_inicial: str = "admin",
) -> None:
    """Inicia el bucle REPL interactivo para operar NimbusDC en tiempo real."""
    print("=" * 68)
    print("  _   _ _           _                 ____   ____ ")
    print(" | \\ | (_)_ __ ___ | |__  _   _ ___  |  _ \\ / ___|")
    print(" |  \\| | | '_ ` _ \\| '_ \\| | | / __| | | | | |    ")
    print(" | |\\  | | | | | | | |_) | |_| \\__ \\ | |_| | |___ ")
    print(" |_| \\_|_|_| |_| |_|_.__/ \\__,_|___/ |____/ \\____|")
    print("              Mini Centro de Datos OS — NimbusDC (IS734)")
    print("=" * 68)
    print("Escribe 'help' para ver los comandos disponibles o 'salir' para terminar.\n")

    usuario = usuario_inicial

    if escenario_inicial:
        print(f"Cargando escenario: '{escenario_inicial}'...")
        res = ejecutar_comando(f"load {escenario_inicial}", usuario=usuario)
        print(res + "\n")

    while True:
        try:
            cwd = directorio_actual(usuario)
            prompt = f"{usuario}@nimbusdc:{cwd}$ "
            linea = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            print("\nSaliendo de NimbusDC...")
            break

        if not linea:
            continue

        if linea.lower() in ("salir", "exit", "quit"):
            print("Sesión finalizada. ¡Hasta luego!")
            break

        partes = linea.split()
        if partes[0].lower() == "su":
            if len(partes) > 1:
                usuario = partes[1]
                print(f"Cambiado a usuario '{usuario}'")
            else:
                print("Error: se requiere el nombre del usuario para 'su'")
            continue

        salida = ejecutar_comando(linea, usuario=usuario)
        if salida:
            print(salida)


if __name__ == "__main__":
    import sys
    escenario_arg = sys.argv[1] if len(sys.argv) > 1 else None
    iniciar_consola_interactiva(escenario_arg)
