"""Gestión de memoria virtual paginada.

Paginación por demanda con reemplazo LOCAL usando el algoritmo del Reloj
(segunda oportunidad), el plan del equipo. LRU y FIFO quedan implementados
como alternativas para el experimento del informe (``_fijar_politica``).

Ideas principales:
- Cada proceso tiene un espacio virtual de ``memoria_bytes`` bytes, dividido en
  ``ceil(memoria_bytes / tam_pagina)`` páginas. Una dirección se traduce con
  ``pagina, desplazamiento = divmod(direccion, tam_pagina)``.
- La memoria física son ``marcos_fisicos`` marcos. En operación normal un
  proceso nunca tiene más de ``cuota_marcos`` páginas residentes a la vez
  (reemplazo local).
- Un acceso fuera del espacio del proceso lanza ``ErrorMemoria`` ANTES de tocar
  cualquier estado: no afecta a otros procesos (RM3).
- Hiperpaginación (RM2, Prototipo 3): ``detectar_hiperpaginacion`` mira si más
  de la mitad de los últimos accesos fueron fallos que obligaron a reemplazar
  una página. ``controlar_hiperpaginacion`` (la llama ``kernel.tick`` una vez
  por tick) reacciona con control de carga por conjunto de trabajo: deja en
  memoria a los procesos más importantes con todas las páginas que están
  usando y suspende a los demás (sus páginas salen al swap) hasta que vuelva a
  haber marcos para ellos.

Este módulo no importa ``kernel``. Consulta ``procesos`` (con un import
diferido) para leer ``memoria_bytes`` y ``cuota_marcos`` de un PID que nadie
registró, y para suspender y reanudar procesos con sus funciones públicas
(``procesos`` es el único dueño del estado de cada proceso). El bloqueo de 5
ticks por fallo de página lo aplica ``procesos``; aquí solo se informa
``fallo_pagina``.
"""
from collections import deque
import math

from minidc.errores import ErrorMemoria, ErrorNoExiste

# ------------------------------------------------------------ parámetros
_POLITICA = "RELOJ"           # política activa: "RELOJ", "LRU" o "FIFO"
_VENTANA_HIPERPAGINACION = 32  # últimos accesos que se miran
_MINIMO_ACCESOS_VENTANA = 16   # sin suficientes datos no se diagnostica
_UMBRAL_HIPERPAGINACION = 0.5  # más de la mitad de los accesos fueron fallos con reemplazo
_VENTANA_CONJUNTO_TRABAJO = 16  # últimos accesos de cada proceso para estimar su conjunto de trabajo
_ACCESOS_ENTRE_REACCIONES = 8   # accesos nuevos antes de volver a evaluar mientras siga la hiperpaginación
_MAX_TICKS_SUSPENDIDO = 300     # envejecimiento: tras estos ticks suspendido, se reanuda aunque no quepa
_REACCION = "CONJUNTO_TRABAJO"  # reacción a la hiperpaginación (ver _REACCIONES)

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
_ventana = deque()    # True = fallo con reemplazo, False = otro acceso, para los últimos accesos
_suspendidos = []     # PID suspendidos por el control de carga (RM2), en orden de suspensión
_ticks_suspendido = {}  # pid suspendido -> ticks que lleva suspendido
_accesos_ultima_reaccion = None  # valor de _accesos en la última reacción (None = nunca)
_reacciones = 0       # cuántas veces se reaccionó a la hiperpaginación


def reiniciar(config: dict) -> None:
    """Deja la memoria como nueva. Lo llama ``kernel.iniciar_sistema``."""
    global _marcos_totales, _tam_pagina, _marcos, _procesos, _contador_accesos
    global _accesos, _fallos, _reemplazos, _escrituras_swap, _ventana
    global _suspendidos, _ticks_suspendido, _accesos_ultima_reaccion, _reacciones
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
    _suspendidos = []
    _ticks_suspendido = {}
    _accesos_ultima_reaccion = None
    _reacciones = 0


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
        # RM2: páginas de los últimos accesos (estiman el conjunto de trabajo) y
        # límite de marcos que fija el control de carga (None = su cuota).
        "historial": deque(maxlen=_VENTANA_CONJUNTO_TRABAJO),
        "limite": None,
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
def _limite(reg: dict) -> int:
    """Máximo de marcos residentes del proceso: su cuota, salvo que el control
    de carga (RM2) le haya fijado otro límite."""
    return reg["cuota"] if reg["limite"] is None else reg["limite"]


def _expulsar(pid: int, pagina: int, es_reemplazo: bool = True) -> int:
    """Saca ``pagina`` de memoria y devuelve el marco que queda libre.

    ``es_reemplazo=False`` cuando no la saca un fallo de página sino el control
    de carga (suspender o achicar a un proceso): no cuenta como reemplazo, pero
    una página modificada igual se escribe al swap.
    """
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
    if es_reemplazo:
        _reemplazos += 1
    return marco


def _conseguir_marco(pid: int) -> tuple:
    """Devuelve ``(marco, pagina_reemplazada)`` para cargar una página de ``pid``.

    Reemplazo LOCAL: un proceso solo saca páginas SUYAS.
    1. Si no llegó a su límite (su cuota, o el que fijó el control de carga)
       y hay un marco libre, lo usa.
    2. Si no, la víctima es una de sus propias páginas.
    3. Única excepción: si no tiene ninguna página residente y no hay marcos
       libres, no podría avanzar; entonces toma un marco del proceso con más
       marcos. Solo pasa si la suma de las cuotas supera los marcos físicos.
    """
    reg = _procesos[pid]
    if len(reg["residentes"]) < _limite(reg) and None in _marcos:
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
    reg["historial"].append(pagina)
    # Para la hiperpaginación solo cuentan los fallos que obligaron a sacar una
    # página: los primeros fallos de un proceso que llena marcos libres no lo son.
    _ventana.append(reemplazada is not None)
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
    if pid in _suspendidos:
        _suspendidos.remove(pid)
    _ticks_suspendido.pop(pid, None)
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

    Se diagnostica cuando, en los últimos 32 accesos (ventana), más de la mitad
    fueron fallos de página que obligaron a sacar otra página: cada fallo saca
    una página que se va a necesitar enseguida. Los fallos que solo llenan un
    marco libre (al arrancar un proceso) no cuentan. Con menos de 16 accesos no
    se diagnostica.
    """
    if len(_ventana) < _MINIMO_ACCESOS_VENTANA:
        return False
    return sum(_ventana) / len(_ventana) > _UMBRAL_HIPERPAGINACION


# ------------------------------------- reacción a la hiperpaginación (RM2)
def _vivo(pid: int) -> bool:
    """True si ``procesos`` conoce al proceso y no ha terminado."""
    datos = _tabla_procesos().get(pid)
    return datos is not None and datos.get("estado") != "TERMINADO"


def _importancia(pid: int) -> tuple:
    """Orden de importancia para quedarse en memoria: primero la prioridad
    original (0 = la más alta, los servicios web) y luego el más antiguo."""
    datos = _tabla_procesos().get(pid, {})
    return datos.get("prioridad_original", datos.get("prioridad", 0)), pid


def _conjunto_trabajo(pid: int) -> int:
    """Páginas distintas de los últimos accesos del proceso (mínimo 1, máximo
    todos los marcos): los marcos que necesita para no fallar en su fase actual."""
    reg = _procesos[pid]
    return min(_marcos_totales, max(1, len(set(reg["historial"]))))


def _demanda(pid: int) -> int:
    """Marcos que la reacción activa le reserva a un proceso que se queda en memoria.

    Con ``CONJUNTO_TRABAJO`` es su cuota o, si su conjunto de trabajo es más
    grande, su conjunto de trabajo. La cuota es el mínimo porque con poco
    historial el conjunto de trabajo se queda corto (un proceso suspendido
    tras 3 accesos parecería necesitar solo 3 marcos).
    """
    cuota = _procesos[pid]["cuota"]
    if _REACCION == "SUSPENDER":                     # alternativa: nunca pasar de la cuota
        return min(cuota, _marcos_totales)
    return min(_marcos_totales, max(cuota, _conjunto_trabajo(pid)))


def _participantes() -> list:
    """Procesos vivos en memoria que no están suspendidos y ya usaron memoria."""
    return [pid for pid, reg in _procesos.items()
            if pid not in _suspendidos and _vivo(pid) and (reg["residentes"] or reg["historial"])]


def _ajustar_a_limite(pid: int) -> None:
    """Si el proceso tiene más páginas que su límite, saca las sobrantes con la
    política de reemplazo (salen al swap si estaban modificadas)."""
    reg = _procesos[pid]
    while len(reg["residentes"]) > _limite(reg):
        _expulsar(pid, _ELEGIR_VICTIMA[_POLITICA](reg), es_reemplazo=False)


def _suspender(pid: int, procesos) -> bool:
    """Suspende al proceso y saca todas sus páginas de memoria (swap-out)."""
    if not procesos.suspender_proceso(pid):
        return False
    reg = _procesos[pid]
    for pagina in list(reg["residentes"]):
        _expulsar(pid, pagina, es_reemplazo=False)
    reg["limite"] = None
    _suspendidos.append(pid)
    _ticks_suspendido[pid] = 0
    return True


def _reaccionar(procesos) -> list:
    """Reparte la memoria según la reacción activa. Devuelve los PID suspendidos.

    ``CONJUNTO_TRABAJO`` (la elegida) y ``SUSPENDER``: los procesos que no se
    pueden suspender (con hilos, semáforos, mutex o E/S en curso) se quedan con
    al menos 1 marco. Después, en orden de importancia, cada proceso se queda en
    memoria si su demanda cabe en los marcos que quedan; si no cabe, se
    suspende. Si nadie cupo, el más importante se queda con lo que haya, para
    que el sistema siempre avance.
    """
    participantes = sorted(_participantes(), key=_importancia)
    if _REACCION == "PRESTAR_LIBRES":
        # Alternativa: sin suspender a nadie, los marcos libres se prestan a
        # quien necesita más de los que tiene, en orden de importancia.
        libres = _marcos.count(None)
        for pid in participantes:
            reg = _procesos[pid]
            falta = _conjunto_trabajo(pid) - _limite(reg)
            if falta > 0 and libres > 0:
                prestados = min(falta, libres)
                reg["limite"] = _limite(reg) + prestados
                libres -= prestados
        return []

    fijos = [pid for pid in participantes if not procesos.puede_suspenderse(pid)]
    movibles = [pid for pid in participantes if pid not in fijos]
    presupuesto = _marcos_totales - len(fijos)       # cada fijo conserva al menos 1 marco
    limites, a_suspender = {}, []
    for pid in fijos:
        extra = _demanda(pid) - 1
        if extra <= presupuesto:
            limites[pid] = _demanda(pid)
            presupuesto -= extra
        else:
            limites[pid] = 1
    for pid in movibles:
        if _demanda(pid) <= presupuesto:
            limites[pid] = _demanda(pid)
            presupuesto -= _demanda(pid)
        else:
            a_suspender.append(pid)
    if movibles and len(a_suspender) == len(movibles) and presupuesto > 0:
        primero = a_suspender.pop(0)                 # nadie cupo: avanza el más importante
        limites[primero] = presupuesto

    suspendidos = []
    for pid in a_suspender:
        if _suspender(pid, procesos):
            suspendidos.append(pid)
        else:
            limites[pid] = 1
    for pid, limite in limites.items():
        reg = _procesos[pid]
        reg["limite"] = None if _REACCION == "SUSPENDER" else limite
        _ajustar_a_limite(pid)
    return suspendidos


def _reanudar_si_caben(procesos) -> list:
    """Reanuda, en orden de importancia, a los suspendidos cuyo conjunto de
    trabajo cabe en los marcos libres que nadie más tiene reservados.

    Si ya no queda ningún proceso activo, reanuda al más importante aunque no
    quepa entero, para que el sistema nunca se quede parado. Con el
    envejecimiento, un suspendido que lleva 300 ticks así también se reanuda
    aunque no quepa: si vuelve la hiperpaginación, en la siguiente evaluación
    se queda él (es más antiguo) y se suspende a uno más nuevo. Cuando no queda
    nadie suspendido, los procesos a los que se les bajó el límite por debajo de
    su cuota vuelven a su cuota en cuanto los marcos libres alcanzan.
    """
    if not _suspendidos and all(reg["limite"] is None for reg in _procesos.values()):
        return []                                    # caso común: no hay nada que devolver
    libres = _marcos.count(None)
    reservados = sum(max(0, _limite(_procesos[pid]) - len(_procesos[pid]["residentes"]))
                     for pid in _participantes())
    disponibles = libres - reservados
    if not _suspendidos:
        for pid in sorted(_procesos, key=_importancia):
            reg = _procesos[pid]
            if reg["limite"] is not None and reg["limite"] < reg["cuota"]:
                falta = reg["cuota"] - reg["limite"]
                if falta <= disponibles:
                    reg["limite"] = None
                    disponibles -= falta
        return []
    activos = [pid for pid in _tabla_procesos() if _vivo(pid) and pid not in _suspendidos]
    reanudados = []
    for pid in sorted(_suspendidos, key=_importancia):
        demanda = _demanda(pid)
        envejecido = _ticks_suspendido.get(pid, 0) >= _MAX_TICKS_SUSPENDIDO
        if demanda <= disponibles or (not activos and not reanudados) or envejecido:
            procesos.reanudar_proceso(pid)
            _suspendidos.remove(pid)
            _ticks_suspendido.pop(pid, None)
            reg = _procesos[pid]
            if _REACCION != "SUSPENDER":
                reg["limite"] = max(1, min(demanda, libres))
            disponibles -= demanda
            libres -= min(demanda, libres)
            reanudados.append(pid)
    return reanudados


def controlar_hiperpaginacion() -> dict:
    """Control de carga de la memoria (RM2). Lo llama ``kernel.tick`` en el paso 4.

    - Si se detecta hiperpaginación, reacciona: los procesos más importantes se
      quedan en memoria con su conjunto de trabajo (las páginas distintas de sus
      últimos 16 accesos), aunque pase de su cuota, y los que no caben se
      suspenden: sus páginas salen al swap y no ejecutan. Si la hiperpaginación
      sigue, vuelve a evaluar cada 8 accesos nuevos: el conjunto de trabajo de
      cada proceso se estima mejor a medida que tiene más historial.
    - Si no, reanuda a los suspendidos que ya caben.

    Devuelve ``{"reaccion": bool, "suspendidos": [PID], "reanudados": [PID]}``.
    """
    global _accesos_ultima_reaccion, _reacciones
    from minidc import procesos      # import diferido: evita dependencias circulares
    # Los terminados no se liberan aquí (ya lo hace procesos.terminar_proceso);
    # solo se dejan fuera de las cuentas.
    _suspendidos[:] = [pid for pid in _suspendidos if _vivo(pid) and pid in _procesos]
    for pid in _suspendidos:
        _ticks_suspendido[pid] = _ticks_suspendido.get(pid, 0) + 1
    resultado = {"reaccion": False, "suspendidos": [], "reanudados": []}
    if _REACCION == "NINGUNA":
        return resultado
    espero_ventana = (_accesos_ultima_reaccion is None
                      or _accesos - _accesos_ultima_reaccion >= _ACCESOS_ENTRE_REACCIONES)
    if detectar_hiperpaginacion() and espero_ventana:
        _accesos_ultima_reaccion = _accesos
        _reacciones += 1
        resultado["reaccion"] = True
        resultado["suspendidos"] = _reaccionar(procesos)
    else:
        resultado["reanudados"] = _reanudar_si_caben(procesos)
    return resultado


def estado_control_carga() -> dict:
    """Estado de la reacción a la hiperpaginación (para la consola y el informe).

    Devuelve ``{"reaccion": str, "reacciones": int, "suspendidos": [PID],
    "limites": {pid: marcos}}``; ``limites`` solo incluye a los procesos cuyo
    límite no es su cuota.
    """
    return {
        "reaccion": _REACCION,
        "reacciones": _reacciones,
        "suspendidos": list(_suspendidos),
        "limites": {pid: reg["limite"] for pid, reg in _procesos.items() if reg["limite"] is not None},
    }


_REACCIONES = ("CONJUNTO_TRABAJO", "SUSPENDER", "PRESTAR_LIBRES", "NINGUNA")


def _fijar_reaccion(nombre: str) -> None:
    """Cambia la reacción a la hiperpaginación. Solo se usa en los experimentos."""
    global _REACCION
    if nombre not in _REACCIONES:
        raise ErrorMemoria(f"Reacción desconocida: {nombre!r}")
    _REACCION = nombre


def politica_reemplazo() -> str:
    """Devuelve el nombre de la política de reemplazo de páginas elegida."""
    return {"RELOJ": "Reloj (segunda oportunidad) con reemplazo local",
            "LRU": "LRU con reemplazo local",
            "FIFO": "FIFO con reemplazo local"}[_POLITICA]


reiniciar({})   # estado válido desde el import
