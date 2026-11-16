"""Intérprete de comandos de administración de NimbusDC.

Implementa los comandos obligatorios del núcleo simulado y los equivalentes
de Windows como bonificación. Los errores siempre se devuelven como cadenas
de texto que comienzan por ``Error:``.
"""
import shlex

from minidc import kernel, procesos
from minidc.errores import ErrorNoExiste, ErrorSistema

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


# ---------------------------------------------------------------- comandos
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


def _cmd_whoami(args: list[str], usuario: str) -> str:
    """Devuelve el nombre del usuario actual."""
    return str(usuario)


def _cmd_pwd(args: list[str], usuario: str) -> str:
    """Devuelve el directorio actual del usuario."""
    return directorio_actual(usuario)


def _cmd_cd(args: list[str], usuario: str) -> str:
    """Cambia el directorio actual del usuario."""
    destino = args[0] if args else "/"
    actual = directorio_actual(usuario)

    if destino == "/":
        nueva_ruta = "/"
    elif destino.startswith("/"):
        nueva_ruta = destino.rstrip("/") or "/"
    else:
        partes = [p for p in actual.strip("/").split("/") if p]
        for seg in destino.split("/"):
            if seg in ("", "."):
                continue
            elif seg == "..":
                if partes:
                    partes.pop()
            else:
                partes.append(seg)
        nueva_ruta = "/" + "/".join(partes)

    _directorios[usuario] = nueva_ruta
    return ""


def _cmd_load(args: list[str], usuario: str) -> str:
    """Carga un escenario JSON en el sistema."""
    if not args:
        return "Error: se requiere la ruta del archivo de escenario JSON"
    ruta = args[0]
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
        "Comandos disponibles (Prototipo 1):\n"
        "  ps / tasklist       : Lista los procesos del sistema (PID NOMBRE USUARIO ESTADO)\n"
        "  run NOMBRE          : Crea y encola un proceso del catálogo del escenario\n"
        "  kill PID / taskkill : Termina un proceso y libera sus recursos\n"
        "  tick [N]            : Avanza 1 o N ticks discretos en el reloj del kernel\n"
        "  top                 : Muestra una instantánea de métricas y procesos activos\n"
        "  load RUTA           : Carga un escenario JSON (usuarios, semáforos, catálogo)\n"
        "  whoami              : Muestra el usuario activo actual\n"
        "  pwd                 : Muestra el directorio de trabajo actual\n"
        "  cd [RUTA]           : Cambia de directorio de trabajo\n"
        "  clear / cls         : Limpia la pantalla de la consola\n"
        "  su USUARIO          : Cambia el usuario activo (en modo interactivo)\n"
        "  salir / exit / quit : Cierra la sesión interactiva"
    )


# Mapa de comandos soportados en el Prototipo 1 (y equivalentes de Windows)
_COMANDOS = {
    "ps": _cmd_ps,
    "tasklist": _cmd_ps,
    "kill": _cmd_kill,
    "taskkill": _cmd_kill,
    "run": _cmd_run,
    "tick": _cmd_tick,
    "top": _cmd_top,
    "whoami": _cmd_whoami,
    "pwd": _cmd_pwd,
    "cd": _cmd_cd,
    "load": _cmd_load,
    "cargar": _cmd_load,
    "clear": _cmd_clear,
    "cls": _cmd_clear,
    "help": _cmd_help,
}


def ejecutar_comando(linea: str, usuario: str = "admin") -> str:
    """Ejecuta un comando de consola en nombre de ``usuario`` y devuelve su salida.

    Los errores se devuelven como texto que comienza por ``Error:``.
    Comandos de procesos soportados en el Prototipo 1:
    - ``ps`` / ``tasklist``
    - ``kill PID`` / ``taskkill PID``
    - ``run NOMBRE`` (crea un proceso desde el catálogo del escenario)
    - ``tick [N]``
    - ``top`` (instantánea)
    - ``whoami``, ``pwd``, ``cd``
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
