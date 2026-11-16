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


# ---------------------------------------------------------------- errores y casos borde
def test_consola_comando_desconocido():
    salida = consola.ejecutar_comando("comando_inexistente")
    assert salida.startswith("Error:")


def test_consola_linea_vacia():
    assert consola.ejecutar_comando("") == ""
    assert consola.ejecutar_comando("   ") == ""


def test_consola_error_sintaxis_comillas():
    salida = consola.ejecutar_comando('echo "comilla sin cerrar')
    assert salida.startswith("Error:")
