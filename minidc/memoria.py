"""Gestión de memoria virtual paginada.

Prototipo 2: paginación por demanda con reemplazo LOCAL usando el algoritmo
del Reloj (segunda oportunidad), el plan del equipo. LRU y FIFO quedan
implementados como alternativas para el experimento del informe
(``_fijar_politica``).

Ideas principales:
- Cada proceso tiene un espacio virtual de ``memoria_bytes`` bytes, dividido en
  ``ceil(memoria_bytes / tam_pagina)`` páginas. Una dirección se traduce con
  ``pagina, desplazamiento = divmod(direccion, tam_pagina)``.
- La memoria física son ``marcos_fisicos`` marcos. Un proceso nunca tiene más
  de ``cuota_marcos`` páginas residentes a la vez (reemplazo local).
- Un acceso fuera del espacio del proceso lanza ``ErrorMemoria`` ANTES de tocar
  cualquier estado: no afecta a otros procesos (RM3).

Este módulo no importa ``kernel``. Solo consulta ``procesos`` (con un import
diferido) cuando le preguntan por un PID que nadie registró, para leer su
``memoria_bytes`` y su ``cuota_marcos``. El bloqueo de 5 ticks por fallo de
página lo aplica ``procesos``; aquí solo se informa ``fallo_pagina``.
"""
from collections import deque
import math

from minidc.errores import ErrorMemoria, ErrorNoExiste

# ------------------------------------------------------------ parámetros
_POLITICA = "RELOJ"           # política activa: "RELOJ", "LRU" o "FIFO"
_VENTANA_HIPERPAGINACION = 32  # últimos accesos que se miran
_MINIMO_ACCESOS_VENTANA = 16   # sin suficientes datos no se diagnostica
_UMBRAL_HIPERPAGINACION = 0.5  # más de la mitad de fallos en la ventana

# ---------------------------------------------------------------- estado
_marcos_totales = 64
_tam_pagina = 256
_marcos = []          # un valor por marco físico: (pid, pagina) o None si está libre
_procesos = {}        # pid -> registro del proceso (ver registrar_proceso)
_contador_accesos = 0  # "reloj" de accesos: lo usan LRU y FIFO para comparar antigüedad
_accesos = 0
_fallos = 0
_reemplazos = 0
_escrituras_swap = 0
_ventana = deque()    # True = fallo, False = acierto, para los últimos accesos


def reiniciar(config: dict) -> None:
    """Deja la memoria como nueva. Lo llama ``kernel.iniciar_sistema``."""
    global _marcos_totales, _tam_pagina, _marcos, _procesos, _contador_accesos
    global _accesos, _fallos, _reemplazos, _escrituras_swap, _ventana
    _marcos_totales = int(config.get("marcos_fisicos", 64))
    _tam_pagina = int(config.get("tam_pagina", 256))
    if _marcos_totales < 1 or _tam_pagina < 1:
        raise ErrorMemoria("marcos_fisicos y tam_pagina deben ser mayores que 0")
    _marcos = [None] * _marcos_totales
    _procesos = {}
    _contador_accesos = 0
    _accesos = 0
    _fallos = 0
    _reemplazos = 0
    _escrituras_swap = 0
    _ventana = deque(maxlen=_VENTANA_HIPERPAGINACION)


# ---------------------------------------------------- registro de procesos
def registrar_proceso(pid: int, memoria_bytes: int, cuota_marcos: int) -> None:
    """Da de alta el espacio virtual de un proceso (todas sus páginas no presentes).

    Si el PID ya estaba registrado, primero libera su memoria anterior.
    """
    if memoria_bytes < 1:
        raise ErrorMemoria(f"El proceso {pid} debe tener al menos 1 byte de memoria")
    if cuota_marcos < 1:
        raise ErrorMemoria(f"La cuota de marcos del proceso {pid} debe ser al menos 1")
    if pid in _procesos:
        liberar_memoria(pid)
    num_paginas = math.ceil(memoria_bytes / _tam_pagina)
    _procesos[pid] = {
        "memoria_bytes": memoria_bytes,
        "cuota": cuota_marcos,
        # Tabla de páginas con el formato exacto del enunciado
        "tabla": {
            pagina: {"marco": None, "presente": False, "modificada": False, "referenciada": False}
            for pagina in range(num_paginas)
        },
        "residentes": [],     # páginas en memoria, en orden de carga (lo recorre el Reloj)
        "manecilla": 0,       # posición de la manecilla del Reloj dentro de "residentes"
        "ultimo_uso": {},     # pagina -> número de acceso (solo para LRU)
        "cargada_en": {},     # pagina -> número de acceso en que se cargó (solo para FIFO)
        "origen": None,       # el proceso de ``procesos`` del que salió (None si fue a mano)
    }


def _tabla_procesos() -> dict:
    """La tabla de procesos de ``procesos`` (solo lectura; import diferido)."""
    from minidc import procesos      # import diferido: evita dependencias circulares
    return getattr(procesos, "_procesos", {})


def _registro(pid: int) -> dict:
    """Devuelve el registro de ``pid``. Si no existe, lo crea leyendo ``procesos``.

    Así ``memoria`` funciona aunque ``procesos.crear_proceso`` no llame a
    ``registrar_proceso``. Lanza ErrorNoExiste si el proceso no existe o ya terminó.
    """
    datos = _tabla_procesos().get(pid)
    reg = _procesos.get(pid)
    if datos is not None and datos.get("estado") == "TERMINADO":
        liberar_memoria(pid)
        raise ErrorNoExiste(f"El proceso {pid} ya terminó")
    if reg is not None and (datos is None or reg["origen"] is None or reg["origen"] is datos):
        return reg
    # Sin registro, o registro de un proceso anterior con el mismo PID
    # (el kernel se reinició y los PID volvieron a empezar): se registra de nuevo.
    if datos is None:
        raise ErrorNoExiste(f"El proceso {pid} no existe")
    registrar_proceso(pid, datos.get("memoria_bytes", 4096), datos.get("cuota_marcos", 4))
    _procesos[pid]["origen"] = datos
    return _procesos[pid]


def _liberar_terminados() -> None:
    """Libera la memoria de los procesos que ``procesos`` ya marcó como TERMINADO.

    El enunciado exige que un proceso que termina libere su memoria. Esto lo
    garantiza aunque el proceso haya terminado sin llamar a ``liberar_memoria``.
    Los PID registrados a mano que ``procesos`` no conoce no se tocan.
    """
    tabla = _tabla_procesos()
    for pid in [p for p in _procesos if tabla.get(p, {}).get("estado") == "TERMINADO"]:
        liberar_memoria(pid)


def _sincronizar_con_procesos() -> None:
    """Libera los TERMINADO y registra los procesos vivos que aún no tocaron memoria,
    para que ``estado_memoria`` cuente a todos (p. ej. la fragmentación interna)."""
    _liberar_terminados()
    for pid, datos in _tabla_procesos().items():
        if datos.get("estado") != "TERMINADO":
            _registro(pid)


# ------------------------------------------- políticas de reemplazo (víctima)
def _victima_reloj(reg: dict) -> int:
    """Reloj: la manecilla da una segunda oportunidad a las páginas referenciadas."""
    residentes = reg["residentes"]
    while True:
        pagina = residentes[reg["manecilla"]]
        entrada = reg["tabla"][pagina]
        if entrada["referenciada"]:
            entrada["referenciada"] = False                  # segunda oportunidad
            reg["manecilla"] = (reg["manecilla"] + 1) % len(residentes)
        else:
            return pagina


def _victima_fifo(reg: dict) -> int:
    """FIFO: la página que lleva más tiempo cargada."""
    return min(reg["residentes"], key=lambda pagina: reg["cargada_en"][pagina])


def _victima_lru(reg: dict) -> int:
    """LRU: la página usada hace más tiempo."""
    return min(reg["residentes"], key=lambda pagina: reg["ultimo_uso"][pagina])


_ELEGIR_VICTIMA = {"RELOJ": _victima_reloj, "FIFO": _victima_fifo, "LRU": _victima_lru}


def _fijar_politica(nombre: str) -> None:
    """Cambia la política activa. Solo se usa en los experimentos del informe."""
    global _POLITICA
    if nombre not in _ELEGIR_VICTIMA:
        raise ErrorMemoria(f"Política desconocida: {nombre!r}")
    _POLITICA = nombre


# ---------------------------------------------------- funciones internas
def _expulsar(pid: int, pagina: int) -> int:
    """Saca ``pagina`` de memoria y devuelve el marco que queda libre."""
    global _reemplazos, _escrituras_swap
    reg = _procesos[pid]
    entrada = reg["tabla"][pagina]
    marco = entrada["marco"]
    if entrada["modificada"]:
        _escrituras_swap += 1             # la página sucia se guarda en el swap
    entrada.update(marco=None, presente=False, modificada=False, referenciada=False)
    posicion = reg["residentes"].index(pagina)
    reg["residentes"].pop(posicion)
    if posicion < reg["manecilla"]:
        reg["manecilla"] -= 1             # la manecilla sigue apuntando a la misma página
    if reg["residentes"]:
        reg["manecilla"] %= len(reg["residentes"])
    else:
        reg["manecilla"] = 0
    reg["ultimo_uso"].pop(pagina, None)
    reg["cargada_en"].pop(pagina, None)
    _marcos[marco] = None
    _reemplazos += 1
    return marco


def _conseguir_marco(pid: int) -> tuple:
    """Devuelve ``(marco, pagina_reemplazada)`` para cargar una página de ``pid``.

    Reemplazo LOCAL: un proceso solo saca páginas SUYAS.
    1. Si tiene cuota libre y hay un marco libre, lo usa.
    2. Si no, la víctima es una de sus propias páginas.
    3. Única excepción: si no tiene ninguna página residente y no hay marcos
       libres, no podría avanzar; entonces toma un marco del proceso con más
       marcos. Solo pasa si la suma de las cuotas supera los marcos físicos.
    """
    reg = _procesos[pid]
    if len(reg["residentes"]) < reg["cuota"] and None in _marcos:
        return _marcos.index(None), None
    if reg["residentes"]:
        duenio = pid
    else:
        duenio = max(_procesos, key=lambda otro: (len(_procesos[otro]["residentes"]), -otro))
    pagina = _ELEGIR_VICTIMA[_POLITICA](_procesos[duenio])
    return _expulsar(duenio, pagina), (duenio, pagina)


def _cargar(pid: int, pagina: int, marco: int) -> None:
    """Pone ``pagina`` en ``marco`` y la agrega a las residentes del proceso."""
    reg = _procesos[pid]
    reg["tabla"][pagina].update(marco=marco, presente=True)
    _marcos[marco] = (pid, pagina)
    reg["cargada_en"][pagina] = _contador_accesos
    # Se inserta justo "detrás" de la manecilla: será la última en revisarse.
    reg["residentes"].insert(reg["manecilla"], pagina)
    reg["manecilla"] = (reg["manecilla"] + 1) % len(reg["residentes"])


# ------------------------------------------------- funciones del enunciado
def acceder_memoria(pid: int, direccion_virtual: int, escritura: bool = False) -> dict:
    """Traduce y accede a una dirección virtual del proceso ``pid``.

    Devuelve ``{"marco": int, "fallo_pagina": bool, "pagina_reemplazada": (pid, pagina) | None}``.
    Lanza ``ErrorMemoria`` si la dirección está fuera del espacio del proceso.
    """
    global _contador_accesos, _accesos, _fallos
    reg = _registro(pid)
    # RM3: validar ANTES de modificar cualquier estado
    if (not isinstance(direccion_virtual, int) or isinstance(direccion_virtual, bool)
            or not 0 <= direccion_virtual < reg["memoria_bytes"]):
        raise ErrorMemoria(
            f"Dirección {direccion_virtual!r} fuera del espacio del proceso {pid} "
            f"(0..{reg['memoria_bytes'] - 1})"
        )

    pagina, _desplazamiento = divmod(direccion_virtual, _tam_pagina)
    entrada = reg["tabla"][pagina]
    _accesos += 1
    _contador_accesos += 1
    fallo = not entrada["presente"]
    reemplazada = None
    if fallo:
        _fallos += 1
        _liberar_terminados()
        marco, reemplazada = _conseguir_marco(pid)
        _cargar(pid, pagina, marco)

    entrada["referenciada"] = True
    if escritura:
        entrada["modificada"] = True
    reg["ultimo_uso"][pagina] = _contador_accesos
    _ventana.append(fallo)
    return {"marco": entrada["marco"], "fallo_pagina": fallo, "pagina_reemplazada": reemplazada}


def tabla_paginas(pid: int) -> dict:
    """Devuelve la tabla de páginas de ``pid`` (una copia).

    Formato: ``{pagina: {"marco": int | None, "presente": bool, "modificada": bool, "referenciada": bool}}``.
    """
    reg = _registro(pid)
    return {pagina: dict(entrada) for pagina, entrada in reg["tabla"].items()}


def liberar_memoria(pid: int) -> int:
    """Libera los marcos asignados al proceso ``pid`` y devuelve la cantidad liberada.

    Si el proceso no tenía memoria registrada devuelve 0 (no es un error).
    """
    reg = _procesos.pop(pid, None)
    if reg is None:
        return 0
    for pagina in reg["residentes"]:
        _marcos[reg["tabla"][pagina]["marco"]] = None
    return len(reg["residentes"])


def estado_memoria() -> dict:
    """Devuelve: marcos_totales, marcos_libres, marcos_por_proceso, fragmentacion_interna_bytes.

    La fragmentación interna de un proceso es lo que sobra en su última página:
    ``ceil(memoria_bytes / tam_pagina) * tam_pagina - memoria_bytes``. Se suma
    para todos los procesos vivos.
    """
    _sincronizar_con_procesos()
    fragmentacion = sum(len(reg["tabla"]) * _tam_pagina - reg["memoria_bytes"]
                        for reg in _procesos.values())
    return {
        "marcos_totales": _marcos_totales,
        "marcos_libres": _marcos.count(None),
        "marcos_por_proceso": {pid: len(reg["residentes"]) for pid, reg in _procesos.items()},
        "fragmentacion_interna_bytes": fragmentacion,
    }


def metricas_memoria() -> dict:
    """Devuelve: accesos, fallos_pagina, tasa_fallos, reemplazos, escrituras_a_swap."""
    return {
        "accesos": _accesos,
        "fallos_pagina": _fallos,
        "tasa_fallos": _fallos / _accesos if _accesos else 0.0,
        "reemplazos": _reemplazos,
        "escrituras_a_swap": _escrituras_swap,
    }


def detectar_hiperpaginacion() -> bool:
    """Indica si el sistema se encuentra en estado de hiperpaginación (thrashing).

    Se diagnostica cuando, en los últimos accesos (ventana), más de la mitad
    fueron fallos de página. Con pocos accesos no se diagnostica.
    """
    if len(_ventana) < _MINIMO_ACCESOS_VENTANA:
        return False
    return sum(_ventana) / len(_ventana) > _UMBRAL_HIPERPAGINACION


def politica_reemplazo() -> str:
    """Devuelve el nombre de la política de reemplazo de páginas elegida."""
    return {"RELOJ": "Reloj (segunda oportunidad) con reemplazo local",
            "LRU": "LRU con reemplazo local",
            "FIFO": "FIFO con reemplazo local"}[_POLITICA]


reiniciar({})   # estado válido desde el import
