"""Pruebas completas para el intérprete de consola de NimbusDC (`minidc/consola.py`)."""
import json
import os
import tempfile
import pytest

from minidc import consola, kernel, procesos


@pytest.fixture(autouse=True)
def preparar_consola():
    """Reinicia el kernel y el estado de la consola antes de cada prueba."""
    kernel.iniciar_sistema({
        "num_cpus": 1,
        "marcos_fisicos": 16,
        "tam_pagina": 256,
        "bloques_disco": 200,
        "tam_bloque": 512,
        "cache_bloques": 8,
    })
    consola.reiniciar()


# ---------------------------------------------------------------- ps y tasklist
def test_consola_ps_vacio():
    salida = consola.ejecutar_comando("ps")
    assert salida.startswith("PID NOMBRE USUARIO ESTADO")
    assert salida.strip() == "PID NOMBRE USUARIO ESTADO"


def test_consola_ps_con_procesos():
    procesos.crear_proceso("web_1", "cliente_a", [("CPU", 2)])
    procesos.crear_proceso("analitica_1", "admin", [("CPU", 5)])

    salida = consola.ejecutar_comando("ps")
    lineas = salida.strip().splitlines()
    assert lineas[0] == "PID NOMBRE USUARIO ESTADO"
    assert len(lineas) == 3
    assert "web_1 cliente_a LISTO" in lineas[1]
    assert "analitica_1 admin LISTO" in lineas[2]


def test_consola_tasklist_alias():
    procesos.crear_proceso("p_win", "admin", [("CPU", 1)])
    salida_ps = consola.ejecutar_comando("ps")
    salida_tasklist = consola.ejecutar_comando("tasklist")
    assert salida_ps == salida_tasklist


# ---------------------------------------------------------------- kill y taskkill
def test_consola_kill_sin_argumentos():
    salida = consola.ejecutar_comando("kill")
    assert salida.startswith("Error:")


def test_consola_kill_pid_invalido():
    salida = consola.ejecutar_comando("kill abc")
    assert salida.startswith("Error:")


def test_consola_kill_pid_no_existe():
    salida = consola.ejecutar_comando("kill 9999")
    assert salida.startswith("Error:")


def test_consola_kill_exito():
    pid = procesos.crear_proceso("victima", "cliente_a", [("CPU", 10)])
    assert procesos.estado_proceso(pid) == "LISTO"

    salida = consola.ejecutar_comando(f"kill {pid}")
    assert not salida.startswith("Error:")
    assert f"Proceso {pid} terminado" in salida
    assert procesos.estado_proceso(pid) == "TERMINADO"


def test_consola_taskkill_variantes():
    pid1 = procesos.crear_proceso("victima1", "admin", [("CPU", 10)])
    salida1 = consola.ejecutar_comando(f"taskkill {pid1}")
    assert not salida1.startswith("Error:")
    assert procesos.estado_proceso(pid1) == "TERMINADO"

    pid2 = procesos.crear_proceso("victima2", "admin", [("CPU", 10)])
    salida2 = consola.ejecutar_comando(f"taskkill /pid {pid2}")
    assert not salida2.startswith("Error:")
    assert procesos.estado_proceso(pid2) == "TERMINADO"


# ---------------------------------------------------------------- run con catálogo
def test_consola_run_sin_argumentos():
    salida = consola.ejecutar_comando("run")
    assert salida.startswith("Error:")


def test_consola_run_servicio_no_existe():
    salida = consola.ejecutar_comando("run servicio_fantasma")
    assert salida.startswith("Error:")
    assert "no encontrado" in salida


def test_consola_run_con_escenario_cargado():
    datos = {
        "config": {"num_cpus": 1, "bloques_disco": 200},
        "catalogo": {
            "web": {
                "memoria_bytes": 1024,
                "cuota_marcos": 3,
                "prioridad": 1,
                "programa": [["CPU", 2], ["ES", 10]],
            }
        },
        "llegadas": [],
    }
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json") as f:
        json.dump(datos, f)
        ruta = f.name

    try:
        kernel.cargar_escenario(ruta)
        salida = consola.ejecutar_comando("run web", usuario="cliente_b")
        assert not salida.startswith("Error:")
        assert "Proceso web creado con PID" in salida

        procs = procesos.listar_procesos()
        assert len(procs) == 1
        p = procs[0]
        assert p["nombre"] == "web"
        assert p["usuario"] == "cliente_b"
        assert p["prioridad"] == 1
    finally:
        os.remove(ruta)


# ---------------------------------------------------------------- tick
def test_consola_tick_simple():
    assert kernel.reloj_actual() == 0
    salida = consola.ejecutar_comando("tick")
    assert not salida.startswith("Error:")
    assert kernel.reloj_actual() == 1


def test_consola_tick_multiple():
    salida = consola.ejecutar_comando("tick 10")
    assert not salida.startswith("Error:")
    assert kernel.reloj_actual() == 10


def test_consola_tick_invalido():
    salida = consola.ejecutar_comando("tick abc")
    assert salida.startswith("Error:")

    salida_cero = consola.ejecutar_comando("tick 0")
    assert salida_cero.startswith("Error:")


# ---------------------------------------------------------------- top
def test_consola_top():
    procesos.crear_proceso("top_p1", "admin", [("CPU", 5)])
    salida = consola.ejecutar_comando("top")
    assert not salida.startswith("Error:")
    assert "Reloj:" in salida
    assert "Utilización CPU:" in salida
    assert "PID NOMBRE USUARIO ESTADO" in salida
    assert "top_p1" in salida


# ---------------------------------------------------------------- whoami, pwd, cd
def test_consola_whoami():
    assert consola.ejecutar_comando("whoami", usuario="admin") == "admin"
    assert consola.ejecutar_comando("whoami", usuario="cliente_a") == "cliente_a"


def test_consola_pwd_y_cd():
    assert consola.directorio_actual("admin") == "/"
    assert consola.ejecutar_comando("pwd", usuario="admin") == "/"

    consola.ejecutar_comando("cd /var/log", usuario="admin")
    assert consola.directorio_actual("admin") == "/var/log"
    assert consola.ejecutar_comando("pwd", usuario="admin") == "/var/log"

    # cd ..
    consola.ejecutar_comando("cd ..", usuario="admin")
    assert consola.directorio_actual("admin") == "/var"

    # cd a la raíz
    consola.ejecutar_comando("cd /", usuario="admin")
    assert consola.directorio_actual("admin") == "/"


# ---------------------------------------------------------------- historial
def test_consola_historial():
    consola.ejecutar_comando("ps", usuario="admin")
    consola.ejecutar_comando("tick 2", usuario="admin")
    consola.ejecutar_comando("whoami", usuario="cliente_a")

    hist_admin = consola.historial("admin")
    hist_cliente = consola.historial("cliente_a")

    assert hist_admin == ["ps", "tick 2"]
    assert hist_cliente == ["whoami"]


# ---------------------------------------------------------------- archivos y recursos (Prototipo 2)
def test_consola_mkdir_y_md():
    salida1 = consola.ejecutar_comando("mkdir /datos")
    assert salida1 == ""

    salida2 = consola.ejecutar_comando("md /datos/sub")
    assert salida2 == ""

    salida_dup = consola.ejecutar_comando("mkdir /datos")
    assert salida_dup.startswith("Error:")

    salida_vacia = consola.ejecutar_comando("mkdir")
    assert salida_vacia.startswith("Error:")


def test_consola_touch_y_cat_type():
    consola.ejecutar_comando("mkdir /archivos")
    salida_touch = consola.ejecutar_comando("touch /archivos/vacio.txt")
    assert salida_touch == ""

    salida_cat = consola.ejecutar_comando("cat /archivos/vacio.txt")
    assert salida_cat == ""

    salida_type = consola.ejecutar_comando("type /archivos/vacio.txt")
    assert salida_type == ""

    salida_error = consola.ejecutar_comando("cat /archivos/no_existe.txt")
    assert salida_error.startswith("Error:")


def test_consola_echo_redirecciones():
    salida1 = consola.ejecutar_comando('echo "primer linea" > /mensaje.txt')
    assert salida1 == ""
    assert consola.ejecutar_comando("cat /mensaje.txt") == "primer linea"

    salida2 = consola.ejecutar_comando('echo " segunda linea" >> /mensaje.txt')
    assert salida2 == ""
    assert consola.ejecutar_comando("cat /mensaje.txt") == "primer linea segunda linea"

    # Redirección con operador pegado
    salida3 = consola.ejecutar_comando('echo "pegado">/pegado.txt')
    assert salida3 == ""
    assert consola.ejecutar_comando("cat /pegado.txt") == "pegado"

    # Echo sin redirección
    salida_echo = consola.ejecutar_comando('echo hola mundo')
    assert salida_echo == "hola mundo"

    # Error si falta destino
    salida_err = consola.ejecutar_comando('echo texto >')
    assert salida_err.startswith("Error:")


def test_consola_ls_y_dir():
    consola.ejecutar_comando("mkdir /carpeta")
    consola.ejecutar_comando('echo "contenido" > /carpeta/archivo.txt')
    consola.ejecutar_comando("mkdir /carpeta/sub")

    salida_ls = consola.ejecutar_comando("ls /carpeta")
    assert "archivo.txt" in salida_ls
    assert "sub" in salida_ls

    salida_lsl = consola.ejecutar_comando("ls -l /carpeta")
    assert "-644 admin usuarios" in salida_lsl or "archivo.txt" in salida_lsl
    assert "d755 admin usuarios" in salida_lsl or "sub" in salida_lsl

    salida_dir = consola.ejecutar_comando("dir /carpeta")
    assert salida_dir == salida_lsl


def test_consola_rm_y_del():
    consola.ejecutar_comando('echo "a borrar" > /borrar.txt')
    salida_rm = consola.ejecutar_comando("rm /borrar.txt")
    assert salida_rm == ""
    assert consola.ejecutar_comando("cat /borrar.txt").startswith("Error:")

    consola.ejecutar_comando('echo "con del" > /borrar2.txt')
    salida_del = consola.ejecutar_comando("del /borrar2.txt")
    assert salida_del == ""
    assert consola.ejecutar_comando("cat /borrar2.txt").startswith("Error:")

    # Directorio no vacío sin -r falla
    consola.ejecutar_comando("mkdir /arbol")
    consola.ejecutar_comando('echo "x" > /arbol/hijo.txt')
    salida_rm_dir = consola.ejecutar_comando("rm /arbol")
    assert salida_rm_dir.startswith("Error:")

    # Con -r tiene éxito
    salida_rm_r = consola.ejecutar_comando("rm -r /arbol")
    assert salida_rm_r == ""
    assert consola.ejecutar_comando("ls /arbol").startswith("Error:")


def test_consola_chmod():
    consola.ejecutar_comando('echo "privado" > /privado.txt')
    salida_chmod = consola.ejecutar_comando("chmod 600 /privado.txt")
    assert salida_chmod == ""

    info = consola.ejecutar_comando("ls -l /privado.txt")
    assert "600" in info

    salida_invalido = consola.ejecutar_comando("chmod 999 /privado.txt")
    assert salida_invalido.startswith("Error:")


def test_consola_enlaces_simbolicos():
    consola.ejecutar_comando('echo "destino real" > /real.txt')
    salida_ln = consola.ejecutar_comando("ln -s /real.txt /acceso.txt")
    assert salida_ln == ""
    assert consola.ejecutar_comando("cat /acceso.txt") == "destino real"

    salida_mklink = consola.ejecutar_comando("mklink /acceso2.txt /real.txt")
    assert salida_mklink == ""
    assert consola.ejecutar_comando("cat /acceso2.txt") == "destino real"


def test_consola_tree():
    consola.ejecutar_comando("mkdir /sistema")
    consola.ejecutar_comando("mkdir /sistema/sub")
    consola.ejecutar_comando('echo "1" > /sistema/sub/doc.txt')

    salida = consola.ejecutar_comando("tree /sistema")
    assert not salida.startswith("Error:")
    assert "/sistema" in salida
    assert "sub" in salida
    assert "doc.txt" in salida


def test_consola_free():
    salida = consola.ejecutar_comando("free")
    assert not salida.startswith("Error:")
    assert "Memoria física" in salida
    assert "marcos" in salida
    assert "Fallos de página" in salida


def test_consola_df():
    salida = consola.ejecutar_comando("df")
    assert not salida.startswith("Error:")
    assert "SistemaArchivos" in salida
    assert "/dev/disco0" in salida
    assert "Bloques" in salida
    assert "Libres" in salida


def test_consola_permisos_archivos_cliente():
    from minidc import archivos
    archivos.crear_usuario("cliente_a", "usuarios")
    archivos.crear_usuario("cliente_b", "usuarios")

    consola.ejecutar_comando("mkdir /privado_b", usuario="cliente_b")
    consola.ejecutar_comando("chmod 700 /privado_b", usuario="cliente_b")
    consola.ejecutar_comando('echo "secreto" > /privado_b/clave.txt', usuario="cliente_b")

    # cliente_a no puede leer ni entrar
    salida_denegada = consola.ejecutar_comando("cat /privado_b/clave.txt", usuario="cliente_a")
    assert salida_denegada.startswith("Error:")

    # admin sí puede ignorando permisos
    salida_admin = consola.ejecutar_comando("cat /privado_b/clave.txt", usuario="admin")
    assert salida_admin == "secreto"


def test_consola_load_con_espacios_en_ruta():
    with tempfile.TemporaryDirectory() as tempdir:
        dir_con_espacios = os.path.join(tempdir, "carpeta con espacios")
        os.makedirs(dir_con_espacios, exist_ok=True)
        ruta_json = os.path.join(dir_con_espacios, "escenario prueba.json")

        datos = {
            "config": {"num_cpus": 1, "bloques_disco": 100},
            "catalogo": {},
            "llegadas": [],
        }
        with open(ruta_json, "w", encoding="utf-8") as f:
            json.dump(datos, f)

        # Cargar con ruta sin comillas
        salida = consola.ejecutar_comando(f"load {ruta_json}")
        assert not salida.startswith("Error:")
        assert "Escenario cargado exitosamente" in salida


# ---------------------------------------------------------------- errores y casos borde
def test_consola_comando_help():
    salida = consola.ejecutar_comando("help")
    assert not salida.startswith("Error:")
    assert "Comandos disponibles" in salida
    assert "ps" in salida
    assert "top" in salida


def test_consola_comando_load():
    ruta = os.path.join(os.path.dirname(__file__), "escenarios", "base.json")
    salida = consola.ejecutar_comando(f"load {ruta}")
    assert not salida.startswith("Error:")
    assert "Escenario cargado exitosamente" in salida
    assert "web" in salida


def test_consola_comando_desconocido():
    salida = consola.ejecutar_comando("comando_inexistente")
    assert salida.startswith("Error:")


def test_consola_linea_vacia():
    assert consola.ejecutar_comando("") == ""
    assert consola.ejecutar_comando("   ") == ""


def test_consola_error_sintaxis_comillas():
    salida = consola.ejecutar_comando('echo "comilla sin cerrar')
    assert salida.startswith("Error:")
