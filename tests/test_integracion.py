"""Pruebas de integración: el sistema completo, con todos los módulos a la vez.

Reglas de estas pruebas:
- Caja negra: solo se usan las funciones del enunciado, importadas como lo hace
  el profesor. Nada que empiece por "_".
- Los escenarios usan el formato del enunciado y se cargan con kernel.cargar_escenario.
- Lo que depende de algo que todavía no existe se salta (skip) o se marca como
  fallo esperado (xfail), siempre con el motivo escrito.
"""
import ast
import json
import os
import re
import sys

import pytest

from minidc import archivos, consola, disco, kernel, memoria, procesos, sincronizacion
from minidc.errores import ErrorNoExiste, ErrorSistema

CONFIG = {"num_cpus": 1, "marcos_fisicos": 16, "tam_pagina": 256,
          "bloques_disco": 200, "tam_bloque": 512, "cache_bloques": 8}
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CARPETA_ESCENARIOS = os.path.join(RAIZ, "tests", "escenarios")
CARPETA_MINIDC = os.path.join(RAIZ, "minidc")
MODULOS_OBLIGATORIOS = ["__init__", "errores", "kernel", "procesos", "memoria",
                        "disco", "archivos", "sincronizacion", "consola"]


@pytest.fixture(autouse=True)
def sistema_limpio():
    """Antes de cada prueba: el sistema recién iniciado, como lo deja el profesor."""
    kernel.iniciar_sistema(CONFIG)


@pytest.fixture
def con_sincronizacion():
    """Salta la prueba mientras sincronizacion.py no esté implementado."""
    try:
        sincronizacion.crear_semaforo("prueba_disponible", 1)
    except NotImplementedError:
        pytest.skip("pendiente: sincronizacion.py todavía no está implementado")
    kernel.iniciar_sistema(CONFIG)


# ------------------------------------------------------------------ ayudas
def ruta_escenario(nombre):
    return os.path.join(CARPETA_ESCENARIOS, nombre)


def leer_escenario(nombre):
    with open(ruta_escenario(nombre), encoding="utf-8") as f:
        return json.load(f)


def todos_terminados():
    return all(p["estado"] == "TERMINADO" for p in procesos.listar_procesos())


def correr_hasta_que_terminen(ultima_llegada, maximo=3000):
    """Avanza ticks hasta que llegaron todos y todos están TERMINADO. Devuelve el reloj."""
    while kernel.reloj_actual() < maximo:
        kernel.tick()
        if kernel.reloj_actual() >= ultima_llegada and todos_terminados():
            return kernel.reloj_actual()
    raise AssertionError(f"Los procesos no terminaron en {maximo} ticks")


def estados_por_tick(pid, ticks):
    """Corre ``ticks`` ticks y devuelve el estado de ``pid`` después de cada uno."""
    estados = []
    for _ in range(ticks):
        kernel.tick()
        estados.append(procesos.estado_proceso(pid))
    return estados


def archivos_de_minidc():
    return [os.path.join(CARPETA_MINIDC, nombre + ".py") for nombre in MODULOS_OBLIGATORIOS]


def modulos_importados(ruta):
    """Nombres de primer nivel de todo lo que importa un archivo (``os.path`` -> ``os``)."""
    with open(ruta, encoding="utf-8") as f:
        arbol = ast.parse(f.read())
    nombres = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            nombres |= {alias.name.split(".")[0] for alias in nodo.names}
        elif isinstance(nodo, ast.ImportFrom) and nodo.level == 0:
            nombres.add(nodo.module.split(".")[0])
    return nombres


# ------------------------------------------------- reglas del enunciado
def test_estructura_obligatoria_y_readme():
    for ruta in archivos_de_minidc():
        assert os.path.isfile(ruta), ruta
    assert os.path.isdir(os.path.join(RAIZ, "tests"))
    assert os.path.isdir(os.path.join(RAIZ, "informe"))
    with open(os.path.join(RAIZ, "README.md"), encoding="utf-8") as f:
        assert "python -m pytest" in f.read()


def test_solo_se_usa_la_biblioteca_estandar():
    permitidos = set(sys.stdlib_module_names) | {"minidc", "rich"}
    for ruta in archivos_de_minidc():
        externos = modulos_importados(ruta) - permitidos
        assert not externos, f"{os.path.basename(ruta)} importa {externos}"


def test_hilos_y_hora_real_solo_en_la_demo_de_carrera():
    """threading solo en sincronizacion.py, y de time solo time.sleep(0) ahí mismo."""
    for ruta in archivos_de_minidc():
        importados = modulos_importados(ruta)
        assert "datetime" not in importados, ruta
        if not ruta.endswith("sincronizacion.py"):
            assert "threading" not in importados, ruta
            assert "time" not in importados, ruta
    with open(os.path.join(CARPETA_MINIDC, "sincronizacion.py"), encoding="utf-8") as f:
        arbol = ast.parse(f.read())
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.ImportFrom) and nodo.module == "time":
            assert [alias.name for alias in nodo.names] == ["sleep"]
        llama_a_time = (isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Attribute)
                        and isinstance(nodo.func.value, ast.Name) and nodo.func.value.id == "time")
        llama_a_sleep = isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name) and nodo.func.id == "sleep"
        if llama_a_time or llama_a_sleep:
            assert llama_a_sleep or nodo.func.attr == "sleep"
            assert [ast.unparse(argumento) for argumento in nodo.args] == ["0"], "solo se permite time.sleep(0)"


# ------------------------------------------------------- sistema completo
def test_ejemplo_del_enunciado_de_punta_a_punta():
    """CPU 2, ES 40 y CPU 1: bloqueado 1 + 40 // 10 = 5 ticks y termina en el tick 8."""
    kernel.cargar_escenario(ruta_escenario("ejemplo_enunciado.json"))
    pid = procesos.listar_procesos()[0]["pid"]
    estados = estados_por_tick(pid, 8)
    assert estados[2:7] == ["BLOQUEADO"] * 5
    assert estados[7] == "TERMINADO"
    assert disco.metricas_disco() == {"solicitudes_atendidas": 1, "desplazamiento_total": 40,
                                      "posicion_cabezal": 40}
    metricas = procesos.metricas_planificacion()
    assert metricas["procesos_terminados"] == 1
    assert metricas["utilizacion_cpu"] == pytest.approx(3 / 8)   # 3 ticks de CPU en 8 ticks
    resumen_final = kernel.apagar_sistema()
    assert resumen_final["reloj"] == 8
    assert resumen_final["procesos_terminados"] == 1


def test_escenario_de_integracion_completo():
    """2 CPU, 3 usuarios y las 5 instrucciones: todo termina y cada módulo cuadra."""
    escenario = leer_escenario("integracion.json")
    kernel.cargar_escenario(ruta_escenario("integracion.json"))
    correr_hasta_que_terminen(escenario["llegadas"][-1]["tick"])

    instrucciones = [instr[0] for llegada in escenario["llegadas"]
                     for instr in escenario["catalogo"][llegada["programa"]]["programa"]]
    assert len(procesos.listar_procesos()) == len(escenario["llegadas"])
    assert procesos.metricas_planificacion()["procesos_terminados"] == len(escenario["llegadas"])
    assert memoria.metricas_memoria()["accesos"] == instrucciones.count("MEM")
    assert disco.metricas_disco()["solicitudes_atendidas"] == instrucciones.count("ES")
    assert disco.cola_disco() == []
    estado_memoria = memoria.estado_memoria()
    assert estado_memoria["marcos_libres"] == estado_memoria["marcos_totales"]
    resumen = kernel.resumen_sistema()
    assert resumen["procesos_activos"] == 0
    assert resumen["marcos_libres"] == estado_memoria["marcos_libres"]
    assert resumen["bloques_libres"] == archivos.fs_estado_disco()["bloques_libres"]


def test_iniciar_sistema_reinicia_todo():
    kernel.cargar_escenario(ruta_escenario("integracion.json"))
    kernel.ejecutar_ticks(20)
    archivos.fs_mkdir("/datos", "cliente_a")
    archivos.fs_escribir("/datos/nota.txt", "x" * 2000, "cliente_a")
    consola.ejecutar_comando("cd /datos", "cliente_a")

    kernel.iniciar_sistema(CONFIG)

    assert kernel.reloj_actual() == 0
    assert procesos.listar_procesos() == []
    assert procesos.cola_listos() == []
    assert procesos.metricas_planificacion()["cambios_contexto"] == 0
    assert memoria.estado_memoria()["marcos_libres"] == CONFIG["marcos_fisicos"]
    assert memoria.metricas_memoria()["accesos"] == 0
    assert disco.metricas_disco() == {"solicitudes_atendidas": 0, "desplazamiento_total": 0,
                                      "posicion_cabezal": 0}
    assert disco.cola_disco() == []
    assert disco.info_cache()["aciertos"] == disco.info_cache()["fallos"] == 0
    assert archivos.fs_listar("/", "admin") == []
    assert archivos.fs_estado_disco()["bloques_libres"] == CONFIG["bloques_disco"]
    with pytest.raises(ErrorNoExiste):
        archivos.fs_listar("/", "cliente_a")        # los usuarios del escenario ya no existen
    assert consola.directorio_actual("cliente_a") == "/"
    assert consola.historial("cliente_a") == []
    assert procesos.crear_proceso("nuevo", "admin", [("CPU", 1)]) == 1     # los PID vuelven a 1


def test_cargar_un_escenario_sobre_otro_no_arrastra_nada():
    kernel.cargar_escenario(ruta_escenario("integracion.json"))
    kernel.ejecutar_ticks(30)
    kernel.cargar_escenario(ruta_escenario("ejemplo_enunciado.json"))
    assert kernel.reloj_actual() == 0
    assert [(p["pid"], p["nombre"], p["usuario"]) for p in procesos.listar_procesos()] == [(1, "web", "cliente_a")]
    assert memoria.metricas_memoria()["accesos"] == 0
    assert disco.metricas_disco()["solicitudes_atendidas"] == 0
    kernel.ejecutar_ticks(8)
    assert procesos.estado_proceso(1) == "TERMINADO"    # se comporta igual que recién cargado


def test_mismo_escenario_da_siempre_el_mismo_resultado():
    def correr_y_resumir():
        kernel.cargar_escenario(ruta_escenario("integracion.json"))
        kernel.ejecutar_ticks(150)
        return (procesos.listar_procesos(), procesos.metricas_planificacion(),
                memoria.metricas_memoria(), memoria.estado_memoria(),
                disco.metricas_disco(), disco.info_cache())
    assert correr_y_resumir() == correr_y_resumir()


def test_llegada_con_programa_fuera_del_catalogo_lanza_error(tmp_path):
    escenario = leer_escenario("ejemplo_enunciado.json")
    escenario["llegadas"] = [{"tick": 0, "programa": "no_existe", "usuario": "cliente_a"}]
    ruta = tmp_path / "escenario.json"
    ruta.write_text(json.dumps(escenario), encoding="utf-8")
    with pytest.raises(ErrorNoExiste):
        kernel.cargar_escenario(str(ruta))


# ------------------------------------------------- cada instrucción y su módulo
def test_es_bloquea_segun_la_formula_y_pasa_por_el_disco():
    """Cabezal en 0: ES 40 tarda 1 + 40 // 10 = 5 ticks; luego ES 45 tarda 1 + 5 // 10 = 1."""
    pid = procesos.crear_proceso("respaldo", "admin", [("ES", 40), ("ES", 45), ("CPU", 1)])
    assert estados_por_tick(pid, 7) == ["BLOQUEADO"] * 6 + ["TERMINADO"]
    assert disco.metricas_disco() == {"solicitudes_atendidas": 2, "desplazamiento_total": 45,
                                      "posicion_cabezal": 45}


def test_mem_con_fallo_de_pagina_bloquea_5_ticks_y_memoria_lo_cuenta():
    """MEM 10 falla (bloquea 5 ticks); MEM 20 está en la misma página y ya no falla."""
    pid = procesos.crear_proceso("analitica", "admin", [("MEM", 10), ("MEM", 20), ("CPU", 1)],
                                 memoria_bytes=1024)
    estados = estados_por_tick(pid, 7)
    assert estados[:5] == ["BLOQUEADO"] * 5
    assert estados[5] != "BLOQUEADO"
    assert estados[6] == "TERMINADO"
    metricas = memoria.metricas_memoria()
    assert (metricas["accesos"], metricas["fallos_pagina"]) == (2, 1)


def test_terminar_libera_la_memoria_y_las_solicitudes_de_disco():
    """Un proceso que termina, por kill o por sí solo, devuelve todo lo que tenía."""
    analitica = procesos.crear_proceso("analitica", "admin", [("MEM", 10), ("MEM", 300), ("CPU", 100)],
                                       memoria_bytes=1024)
    respaldo = procesos.crear_proceso("respaldo", "admin", [("ES", 190), ("CPU", 1)])
    copia = procesos.crear_proceso("copia", "admin", [("ES", 100), ("CPU", 1)])
    kernel.ejecutar_ticks(20)
    assert memoria.estado_memoria()["marcos_por_proceso"].get(analitica, 0) == 2
    assert disco.cola_disco() == [100]              # la de 190 está en servicio, la de 100 espera

    procesos.terminar_proceso(analitica)            # lo mismo que hace kill
    procesos.terminar_proceso(copia)
    assert memoria.estado_memoria()["marcos_por_proceso"].get(analitica, 0) == 0
    assert disco.cola_disco() == []

    correr_hasta_que_terminen(0)
    assert procesos.estado_proceso(respaldo) == "TERMINADO"
    estado_memoria = memoria.estado_memoria()
    assert estado_memoria["marcos_libres"] == estado_memoria["marcos_totales"]


def test_wait_y_signal_bloquean_y_despiertan(con_sincronizacion):
    sincronizacion.crear_semaforo("bd", 0)
    lector = procesos.crear_proceso("lector", "cliente_a", [("WAIT", "bd"), ("CPU", 1)])
    kernel.tick()
    assert procesos.estado_proceso(lector) == "BLOQUEADO"
    assert sincronizacion.estado_semaforo("bd")["cola_espera"] == [lector]

    procesos.crear_proceso("escritor", "cliente_b", [("SIGNAL", "bd")])
    kernel.ejecutar_ticks(5)
    assert procesos.estado_proceso(lector) == "TERMINADO"
    assert sincronizacion.estado_semaforo("bd")["cola_espera"] == []

    kernel.iniciar_sistema(CONFIG)                  # reiniciar también borra los semáforos
    with pytest.raises(ErrorSistema):
        sincronizacion.estado_semaforo("bd")


def test_terminar_libera_semaforos_y_mutex(con_sincronizacion):
    sincronizacion.crear_semaforo("bd", 1)
    duenio = procesos.crear_proceso("duenio", "cliente_a", [("WAIT", "bd"), ("CPU", 100)])
    esperando = procesos.crear_proceso("esperando", "cliente_b", [("WAIT", "bd"), ("CPU", 1)])
    kernel.ejecutar_ticks(5)
    assert procesos.estado_proceso(esperando) == "BLOQUEADO"

    sincronizacion.crear_mutex("m")
    assert sincronizacion.mutex_lock("m", duenio) is True
    procesos.terminar_proceso(duenio)               # termina sin hacer SIGNAL ni unlock
    assert sincronizacion.mutex_lock("m", esperando) is True
    kernel.ejecutar_ticks(5)
    assert procesos.estado_proceso(esperando) == "TERMINADO"


# ---------------------------------------- un programa malo no tumba el sistema
@pytest.mark.parametrize("programa", [
    pytest.param([("CPU", 1), ("MEM", 999999)], id="MEM fuera del espacio (RM3)"),
    pytest.param([("FOO", 3), ("CPU", 1)], id="instruccion desconocida"),
    pytest.param([("CPU", 1), ("ES", 999)], id="ES a un bloque que no existe"),
    pytest.param([("CPU", 0), ("CPU", 1)], id="CPU 0"),
])
def test_un_programa_invalido_solo_afecta_a_su_proceso(programa):
    malo = procesos.crear_proceso("malo", "cliente_a", programa, memoria_bytes=1024)
    sanos = [procesos.crear_proceso(f"sano_{i}", "cliente_b",
                                    [("CPU", 3), ("MEM", 100), ("ES", 20), ("CPU", 2)], memoria_bytes=1024)
             for i in range(3)]
    for _ in range(200):
        kernel.tick()
        if todos_terminados():
            break
    assert all(procesos.estado_proceso(pid) == "TERMINADO" for pid in [malo] + sanos)
    estado_memoria = memoria.estado_memoria()
    assert estado_memoria["marcos_libres"] == estado_memoria["marcos_totales"]


# ------------------------------------------------------------------ consola
def test_consola_flujo_de_procesos():
    ruta = ruta_escenario("integracion.json")
    assert not consola.ejecutar_comando(f'load "{ruta}"').startswith("Error:")
    antes = len(procesos.listar_procesos())
    assert not consola.ejecutar_comando("run web", "cliente_a").startswith("Error:")
    assert len(procesos.listar_procesos()) == antes + 1
    nuevo = procesos.listar_procesos()[-1]
    assert (nuevo["nombre"], nuevo["usuario"]) == ("web", "cliente_a")

    assert not consola.ejecutar_comando("tick 5").startswith("Error:")
    assert kernel.reloj_actual() == 5

    salida_ps = consola.ejecutar_comando("ps")
    assert salida_ps.startswith("PID NOMBRE USUARIO ESTADO")
    lineas = salida_ps.splitlines()[1:]
    assert len(lineas) == len(procesos.listar_procesos())
    for p, linea in zip(procesos.listar_procesos(), lineas):
        assert linea.split()[0] == str(p["pid"])
        assert p["estado"] in linea

    assert not consola.ejecutar_comando(f"kill {nuevo['pid']}").startswith("Error:")
    assert procesos.estado_proceso(nuevo["pid"]) == "TERMINADO"
    assert consola.ejecutar_comando("top").strip()


def test_consola_flujo_de_archivos_con_dos_usuarios():
    kernel.cargar_escenario(ruta_escenario("integracion.json"))     # crea cliente_a y cliente_b

    def como_a(linea):
        return consola.ejecutar_comando(linea, "cliente_a")

    def como_b(linea):
        return consola.ejecutar_comando(linea, "cliente_b")

    for linea in ["mkdir /proyecto", "cd /proyecto", 'echo "hola" > nota.txt', 'echo " mundo" >> nota.txt',
                  "mkdir datos", "ln -s /proyecto/nota.txt enlace", "chmod 600 nota.txt"]:
        assert not como_a(linea).startswith("Error:"), linea
    assert como_a("pwd") == "/proyecto"
    assert como_a("cat nota.txt") == "hola mundo"
    assert como_a("cat enlace") == "hola mundo"
    listado = como_a("ls -l")
    assert all(nombre in listado for nombre in ("nota.txt", "datos", "enlace"))
    assert "proyecto" in como_a("tree /")

    assert como_b("cat /proyecto/nota.txt").startswith("Error:")          # 600: solo la dueña lee
    assert como_b("rm /proyecto/nota.txt").startswith("Error:")           # no es la dueña
    assert como_b("mkdir /proyecto/intruso").startswith("Error:")         # 755: los demás no escriben

    assert not como_a("rm -r /proyecto").startswith("Error:")
    assert archivos.fs_listar("/", "admin") == []
    assert archivos.fs_estado_disco()["bloques_libres"] == CONFIG["bloques_disco"]


def test_free_y_df_muestran_los_numeros_de_los_modulos():
    kernel.cargar_escenario(ruta_escenario("integracion.json"))
    kernel.ejecutar_ticks(30)
    archivos.fs_escribir("/datos.bin", "x" * 3000, "admin")

    salida_free = consola.ejecutar_comando("free")
    estado_memoria = memoria.estado_memoria()
    metricas = memoria.metricas_memoria()
    assert int(re.search(r"Total:\s*(\d+)", salida_free).group(1)) == estado_memoria["marcos_totales"]
    assert int(re.search(r"Libres:\s*(\d+)", salida_free).group(1)) == estado_memoria["marcos_libres"]
    assert int(re.search(r"Accesos:\s*(\d+)", salida_free).group(1)) == metricas["accesos"]
    assert int(re.search(r"Fallos de página:\s*(\d+)", salida_free).group(1)) == metricas["fallos_pagina"]

    datos_df = consola.ejecutar_comando("df").splitlines()[1].split()
    estado_disco = archivos.fs_estado_disco()
    totales, usados, libres = int(datos_df[1]), int(datos_df[2]), int(datos_df[3])
    assert totales == estado_disco["bloques_totales"]
    assert libres == estado_disco["bloques_libres"]
    assert usados == totales - libres == 6          # 3000 bytes en bloques de 512


@pytest.mark.parametrize("linea", [
    "comando_que_no_existe", "kill 999", "kill abc", "kill", "run no_existe", "tick -3", "tick abc",
    "cat /no_existe.txt", "cd /no_existe", "cd /archivo.txt", "mkdir /no_existe/hijo", "rm /no_existe",
    "rm /", "chmod 999 /archivo.txt", "ln -s /no_existe /enlace", 'echo "sin cerrar',
])
def test_consola_entradas_invalidas_devuelven_texto_de_error(linea):
    kernel.cargar_escenario(ruta_escenario("integracion.json"))
    consola.ejecutar_comando('echo "hola" > /archivo.txt', "cliente_a")
    salida = consola.ejecutar_comando(linea, "cliente_a")
    assert isinstance(salida, str)
    assert salida.startswith("Error:")
    assert consola.directorio_actual("cliente_a") == "/"     # un cd fallido no cambia de carpeta


# ------------------------------------------ requisitos del Prototipo 3
def test_rs1_hilos_reales_no_pierden_actualizaciones(con_sincronizacion):
    assert sincronizacion.demo_condicion_carrera(True, 8, 1000) == 8000
    assert sincronizacion.demo_condicion_carrera(False, 8, 1000) <= 8000


def test_rs1_exclusion_mutua_entre_procesos_simulados(con_sincronizacion):
    """3 CPU y 6 procesos WAIT, CPU 3, SIGNAL sobre "bd" = 1: nunca hay dos dentro a la vez.

    Un proceso está dentro de la sección crítica cuando ya usó CPU (pasó el WAIT)
    y todavía no terminó (el SIGNAL es su última instrucción).
    """
    kernel.iniciar_sistema({**CONFIG, "num_cpus": 3})
    sincronizacion.crear_semaforo("bd", 1)
    for i in range(6):
        procesos.crear_proceso(f"bd_{i}", "admin", [("WAIT", "bd"), ("CPU", 3), ("SIGNAL", "bd")])
    for _ in range(100):
        kernel.tick()
        lista = procesos.listar_procesos()
        dentro = [p for p in lista if p["cpu_usada"] > 0 and p["estado"] != "TERMINADO"]
        assert len(dentro) <= 1
        estado = sincronizacion.estado_semaforo("bd")
        assert 0 <= estado["valor"] <= 1
        bloqueados = {p["pid"] for p in lista if p["estado"] == "BLOQUEADO"}
        assert set(estado["cola_espera"]) <= bloqueados
        if todos_terminados():
            break
    assert todos_terminados()
    assert sincronizacion.estado_semaforo("bd") == {"valor": 1, "cola_espera": []}


def test_rs2_resolver_deja_el_sistema_sin_interbloqueos(con_sincronizacion):
    """Dos procesos toman "a" y "b" en orden cruzado: cada uno espera al otro."""
    kernel.iniciar_sistema({**CONFIG, "num_cpus": 2})
    sincronizacion.crear_semaforo("a", 1)
    sincronizacion.crear_semaforo("b", 1)
    uno = procesos.crear_proceso("uno", "admin",
                                 [("WAIT", "a"), ("CPU", 2), ("WAIT", "b"), ("SIGNAL", "b"), ("SIGNAL", "a")])
    dos = procesos.crear_proceso("dos", "admin",
                                 [("WAIT", "b"), ("CPU", 2), ("WAIT", "a"), ("SIGNAL", "a"), ("SIGNAL", "b")])
    kernel.ejecutar_ticks(10)
    assert procesos.estado_proceso(uno) == procesos.estado_proceso(dos) == "BLOQUEADO"
    assert any(set(ciclo) == {uno, dos} for ciclo in sincronizacion.detectar_interbloqueo())

    afectados = sincronizacion.resolver_interbloqueo()
    assert afectados and set(afectados) <= {uno, dos}
    assert sincronizacion.detectar_interbloqueo() == []
    kernel.ejecutar_ticks(20)
    assert todos_terminados()


def test_rm2_la_tasa_de_fallos_baja_despues_de_detectar_hiperpaginacion():
    """6 procesos recorren 8 páginas en ciclo con cuota de 2 marcos: hiperpaginación segura."""
    recorrido = [("MEM", pagina * 256) for pagina in range(8)] * 30
    for i in range(6):
        procesos.crear_proceso(f"analitica_{i}", "admin", recorrido, memoria_bytes=2048, cuota_marcos=2)
    for _ in range(300):
        kernel.tick()
        if memoria.detectar_hiperpaginacion():
            break
    assert memoria.detectar_hiperpaginacion(), "el escenario debía provocar hiperpaginación"
    antes = memoria.metricas_memoria()
    kernel.ejecutar_ticks(50)
    despues = memoria.metricas_memoria()
    tasa_ventana = (despues["fallos_pagina"] - antes["fallos_pagina"]) / max(1, despues["accesos"] - antes["accesos"])
    assert tasa_ventana < antes["tasa_fallos"]
