"""Pruebas de ``archivos``: usuarios, directorios, archivos, permisos, enlaces y bloques (RF1)."""
import random

import pytest

from minidc import archivos
from minidc.errores import ErrorNoExiste, ErrorPermiso, ErrorSistema, ErrorYaExiste

CONFIG = {"bloques_disco": 200, "tam_bloque": 512}


@pytest.fixture(autouse=True)
def estado_limpio():
    """Se ejecuta antes de CADA prueba: disco formateado y dos clientes creados."""
    archivos.reiniciar(CONFIG)
    archivos.crear_usuario("cliente_a")
    archivos.crear_usuario("cliente_b")


def todos_los_archivos(ruta="/"):
    """Recorre el árbol como admin y devuelve el fs_info de cada archivo (no sigue enlaces)."""
    encontrados = []
    for nombre in archivos.fs_listar(ruta, "admin"):
        hijo = ruta.rstrip("/") + "/" + nombre
        info = archivos.fs_info(hijo)
        if info["tipo"] == "archivo":
            encontrados.append(info)
        elif info["tipo"] == "directorio":
            encontrados += todos_los_archivos(hijo)
    return encontrados


def verificar_rf1():
    """RF1: bloques usados + bloques libres = bloques totales, y ningún bloque se repite."""
    usados = [b for info in todos_los_archivos() for b in info["bloques"]]
    estado = archivos.fs_estado_disco()
    assert len(usados) + estado["bloques_libres"] == estado["bloques_totales"]
    assert len(set(usados)) == len(usados)


# ------------------------------------------------------- formateo y usuarios
def test_formatear_deja_la_raiz_vacia_y_de_admin():
    info = archivos.fs_info("/")
    assert info["tipo"] == "directorio"
    assert info["propietario"] == "admin"
    assert archivos.fs_listar("/", "admin") == []


def test_formatear_borra_todo_y_libera_los_bloques():
    archivos.fs_mkdir("/datos", "cliente_a")
    archivos.fs_escribir("/datos/nota.txt", "x" * 2000, "cliente_a")
    archivos.formatear_disco()
    assert archivos.fs_listar("/", "admin") == []
    assert archivos.fs_estado_disco()["bloques_libres"] == 200
    with pytest.raises(ErrorNoExiste):
        archivos.fs_listar("/", "cliente_a")        # el usuario ya no existe


def test_crear_usuario_repetido_lanza_error():
    with pytest.raises(ErrorYaExiste):
        archivos.crear_usuario("cliente_a")
    with pytest.raises(ErrorYaExiste):
        archivos.crear_usuario("admin")


def test_usuario_desconocido_lanza_error():
    with pytest.raises(ErrorNoExiste):
        archivos.fs_mkdir("/datos", "fantasma")
    with pytest.raises(ErrorNoExiste):
        archivos.fs_escribir("/nota.txt", "hola", "fantasma")


# --------------------------------------------------------------- directorios
def test_mkdir_crea_el_directorio_con_sus_datos():
    archivos.fs_mkdir("/datos", "cliente_a")
    assert archivos.fs_info("/datos") == {
        "tipo": "directorio",
        "tamano": 0,
        "propietario": "cliente_a",
        "grupo": "usuarios",
        "modo": "755",
        "bloques": [],
    }


def test_mkdir_anidado_y_listado_en_orden_alfabetico():
    archivos.fs_mkdir("/datos", "cliente_a")
    archivos.fs_mkdir("/datos/web", "cliente_a")
    archivos.fs_mkdir("/datos/bd", "cliente_a")
    assert archivos.fs_listar("/", "cliente_a") == ["datos"]
    assert archivos.fs_listar("/datos", "cliente_a") == ["bd", "web"]


def test_listar_devuelve_una_copia():
    archivos.fs_mkdir("/datos", "admin")
    lista = archivos.fs_listar("/", "admin")
    lista.append("intruso")                         # alterar la copia...
    assert archivos.fs_listar("/", "admin") == ["datos"]    # ...no afecta al sistema


def test_mkdir_repetido_lanza_error():
    archivos.fs_mkdir("/datos", "admin")
    with pytest.raises(ErrorYaExiste):
        archivos.fs_mkdir("/datos", "admin")
    with pytest.raises(ErrorYaExiste):
        archivos.fs_mkdir("/", "admin")


def test_ruta_que_no_existe_lanza_error():
    with pytest.raises(ErrorNoExiste):
        archivos.fs_mkdir("/no_existe/datos", "admin")      # falta el directorio padre
    with pytest.raises(ErrorNoExiste):
        archivos.fs_listar("/no_existe", "admin")
    with pytest.raises(ErrorNoExiste):
        archivos.fs_info("/no_existe")


def test_ruta_relativa_lanza_error():
    with pytest.raises(ErrorSistema):
        archivos.fs_mkdir("datos", "admin")


def test_un_archivo_no_se_puede_listar_ni_atravesar():
    archivos.fs_escribir("/nota.txt", "hola", "admin")
    with pytest.raises(ErrorSistema):
        archivos.fs_listar("/nota.txt", "admin")
    with pytest.raises(ErrorSistema):
        archivos.fs_mkdir("/nota.txt/datos", "admin")
    with pytest.raises(ErrorNoExiste):
        archivos.fs_info("/nota.txt/datos/otro")


# ------------------------------------------------- rutas y entradas inválidas
def test_las_rutas_resuelven_punto_y_punto_punto():
    archivos.fs_mkdir("/datos", "admin")
    archivos.fs_mkdir("/datos/./web", "admin")                      # "." no cambia nada
    archivos.fs_escribir("/datos/web/../nota.txt", "hola", "admin")  # ".." sube a /datos
    assert archivos.fs_listar("/datos", "admin") == ["nota.txt", "web"]
    assert archivos.fs_leer("/datos/./web/../nota.txt", "admin") == "hola"


def test_punto_punto_en_la_raiz_se_queda_en_la_raiz():
    archivos.fs_mkdir("/datos", "admin")
    assert archivos.fs_listar("/..", "admin") == ["datos"]
    assert archivos.fs_listar("/../../datos/..", "admin") == ["datos"]
    with pytest.raises(ErrorYaExiste):
        archivos.fs_mkdir("/..", "admin")               # es la raíz, que ya existe
    assert archivos.fs_listar("/", "admin") == ["datos"]    # no se creó una carpeta ".."


@pytest.mark.parametrize("ruta", [None, 123, ["/datos"]])
def test_ruta_que_no_es_texto_lanza_error_sistema(ruta):
    with pytest.raises(ErrorSistema):
        archivos.fs_listar(ruta, "admin")
    with pytest.raises(ErrorSistema):
        archivos.fs_info(ruta)


@pytest.mark.parametrize("contenido", [None, 123, b"bytes"])
def test_contenido_que_no_es_texto_lanza_error_y_no_crea_nada(contenido):
    with pytest.raises(ErrorSistema):
        archivos.fs_escribir("/nota.txt", contenido, "admin")
    assert archivos.fs_listar("/", "admin") == []
    assert archivos.fs_estado_disco()["bloques_libres"] == 200


@pytest.mark.parametrize("nombre, grupo", [("", "usuarios"), (None, "usuarios"), (5, "usuarios"), ("auditor", "")])
def test_usuario_con_nombre_o_grupo_invalido_lanza_error(nombre, grupo):
    with pytest.raises(ErrorSistema):
        archivos.crear_usuario(nombre, grupo)


# ------------------------------------------------------- escribir y leer
def test_escribir_crea_el_archivo_y_leer_lo_devuelve():
    assert archivos.fs_escribir("/nota.txt", "hola mundo", "cliente_a") == 10
    assert archivos.fs_leer("/nota.txt", "cliente_a") == "hola mundo"
    info = archivos.fs_info("/nota.txt")
    assert info["tipo"] == "archivo"
    assert info["tamano"] == 10
    assert info["propietario"] == "cliente_a"
    assert info["grupo"] == "usuarios"
    assert info["modo"] == "644"


def test_el_tamano_se_cuenta_en_bytes_y_no_en_letras():
    assert archivos.fs_escribir("/nota.txt", "ñandú", "admin") == 7    # ñ y ú ocupan 2
    assert archivos.fs_info("/nota.txt")["tamano"] == 7


def test_escribir_reemplaza_y_agregar_pega_al_final():
    archivos.fs_escribir("/nota.txt", "uno", "admin")
    archivos.fs_escribir("/nota.txt", "dos", "admin")
    assert archivos.fs_leer("/nota.txt", "admin") == "dos"
    assert archivos.fs_escribir("/nota.txt", " tres", "admin", agregar=True) == 5
    assert archivos.fs_leer("/nota.txt", "admin") == "dos tres"


def test_agregar_a_un_archivo_que_no_existe_lo_crea():
    archivos.fs_escribir("/log.txt", "inicio", "admin", agregar=True)
    assert archivos.fs_leer("/log.txt", "admin") == "inicio"


@pytest.mark.parametrize("nbytes, bloques", [(0, 0), (1, 1), (512, 1), (513, 2), (1024, 2), (1025, 3)])
def test_cantidad_de_bloques_segun_el_tamano(nbytes, bloques):
    """Con bloques de 512 bytes: bloques = bytes / 512, redondeado hacia arriba."""
    archivos.fs_escribir("/datos.bin", "x" * nbytes, "admin")
    assert len(archivos.fs_info("/datos.bin")["bloques"]) == bloques
    assert archivos.fs_estado_disco()["bloques_libres"] == 200 - bloques


def test_el_tamano_de_bloque_sale_de_la_configuracion():
    archivos.reiniciar({"bloques_disco": 50, "tam_bloque": 100})
    archivos.fs_escribir("/nota.txt", "x" * 250, "admin")
    assert len(archivos.fs_info("/nota.txt")["bloques"]) == 3


def test_achicar_un_archivo_devuelve_bloques_al_disco():
    archivos.fs_escribir("/nota.txt", "x" * 1500, "admin")     # 3 bloques
    archivos.fs_escribir("/nota.txt", "corto", "admin")        # 1 bloque
    assert archivos.fs_info("/nota.txt")["bloques"] == [0]
    assert archivos.fs_estado_disco()["bloques_libres"] == 199


def test_los_bloques_de_un_archivo_no_tienen_que_estar_seguidos():
    archivos.fs_escribir("/a.txt", "x" * 512, "admin")         # bloque 0
    archivos.fs_escribir("/b.txt", "x" * 512, "admin")         # bloque 1
    archivos.fs_escribir("/a.txt", "x" * 1024, "admin", agregar=True)
    assert archivos.fs_info("/a.txt")["bloques"] == [0, 2, 3]  # usa los primeros libres


def test_sin_espacio_lanza_error_y_no_cambia_nada():
    archivos.reiniciar({"bloques_disco": 4, "tam_bloque": 512})
    archivos.fs_escribir("/lleno.txt", "x" * 2048, "admin")    # ocupa los 4 bloques
    with pytest.raises(ErrorSistema):
        archivos.fs_escribir("/otro.txt", "y", "admin")
    with pytest.raises(ErrorSistema):
        archivos.fs_escribir("/lleno.txt", "z", "admin", agregar=True)
    assert archivos.fs_listar("/", "admin") == ["lleno.txt"]  # no se creó otro.txt
    assert archivos.fs_leer("/lleno.txt", "admin") == "x" * 2048
    assert archivos.fs_estado_disco()["bloques_libres"] == 0


def test_escribir_o_leer_un_directorio_lanza_error():
    archivos.fs_mkdir("/datos", "admin")
    with pytest.raises(ErrorSistema):
        archivos.fs_escribir("/datos", "hola", "admin")
    with pytest.raises(ErrorSistema):
        archivos.fs_leer("/datos", "admin")
    with pytest.raises(ErrorSistema):
        archivos.fs_escribir("/", "hola", "admin")


def test_leer_o_escribir_donde_no_existe_lanza_error():
    with pytest.raises(ErrorNoExiste):
        archivos.fs_leer("/no_existe.txt", "admin")
    with pytest.raises(ErrorNoExiste):
        archivos.fs_escribir("/no_existe/nota.txt", "hola", "admin")


# ----------------------------------------------------------------- eliminar
def test_eliminar_un_archivo_libera_sus_bloques():
    archivos.fs_escribir("/nota.txt", "x" * 1500, "cliente_a")
    archivos.fs_eliminar("/nota.txt", "cliente_a")
    assert archivos.fs_listar("/", "admin") == []
    assert archivos.fs_estado_disco()["bloques_libres"] == 200


def test_un_directorio_vacio_se_borra_sin_recursivo():
    archivos.fs_mkdir("/vacio", "cliente_a")
    archivos.fs_eliminar("/vacio", "cliente_a")
    assert archivos.fs_listar("/", "admin") == []


def test_un_directorio_con_contenido_necesita_recursivo():
    archivos.fs_mkdir("/datos", "cliente_a")
    archivos.fs_mkdir("/datos/web", "cliente_a")
    archivos.fs_escribir("/datos/web/index.html", "x" * 1000, "cliente_a")
    with pytest.raises(ErrorSistema):
        archivos.fs_eliminar("/datos", "cliente_a")
    archivos.fs_eliminar("/datos", "cliente_a", recursivo=True)
    assert archivos.fs_listar("/", "admin") == []
    assert archivos.fs_estado_disco()["bloques_libres"] == 200


def test_borrado_recursivo_con_algo_ajeno_no_borra_nada():
    archivos.fs_mkdir("/compartido", "cliente_a")
    archivos.fs_chmod("/compartido", "777", "cliente_a")
    archivos.fs_escribir("/compartido/de_a.txt", "a", "cliente_a")
    archivos.fs_escribir("/compartido/de_b.txt", "b", "cliente_b")
    with pytest.raises(ErrorPermiso):
        archivos.fs_eliminar("/compartido", "cliente_a", recursivo=True)
    assert archivos.fs_listar("/compartido", "admin") == ["de_a.txt", "de_b.txt"]
    archivos.fs_eliminar("/compartido", "admin", recursivo=True)     # admin sí puede
    assert archivos.fs_listar("/", "admin") == []


def test_la_raiz_no_se_puede_eliminar():
    with pytest.raises(ErrorSistema):
        archivos.fs_eliminar("/", "admin", recursivo=True)


def test_eliminar_lo_que_no_existe_lanza_error():
    with pytest.raises(ErrorNoExiste):
        archivos.fs_eliminar("/no_existe.txt", "admin")


# -------------------------------------------------------------------- chmod
def test_chmod_cambia_el_modo_y_se_aplica():
    archivos.fs_escribir("/nota.txt", "secreto", "cliente_a")
    assert archivos.fs_leer("/nota.txt", "cliente_b") == "secreto"   # 644: otros leen
    archivos.fs_chmod("/nota.txt", "600", "cliente_a")
    assert archivos.fs_info("/nota.txt")["modo"] == "600"
    with pytest.raises(ErrorPermiso):
        archivos.fs_leer("/nota.txt", "cliente_b")


@pytest.mark.parametrize("modo", ["9", "64", "1234", "abc", "780"])
def test_chmod_con_modo_invalido_lanza_error(modo):
    archivos.fs_escribir("/nota.txt", "hola", "admin")
    with pytest.raises(ErrorSistema):
        archivos.fs_chmod("/nota.txt", modo, "admin")


# ------------------------------------------------------------------ enlaces
def test_enlace_a_un_archivo_lee_y_escribe_en_el_destino():
    archivos.fs_escribir("/nota.txt", "hola", "cliente_a")
    archivos.fs_chmod("/nota.txt", "666", "cliente_a")
    archivos.fs_enlace_simbolico("/nota.txt", "/atajo", "cliente_b")
    assert archivos.fs_leer("/atajo", "cliente_b") == "hola"
    archivos.fs_escribir("/atajo", " mundo", "cliente_b", agregar=True)
    assert archivos.fs_leer("/nota.txt", "cliente_a") == "hola mundo"


def test_enlace_a_un_directorio_sirve_para_listar_y_en_medio_de_rutas():
    archivos.fs_mkdir("/datos", "admin")
    archivos.fs_escribir("/datos/nota.txt", "hola", "admin")
    archivos.fs_enlace_simbolico("/datos", "/atajo", "admin")
    assert archivos.fs_listar("/atajo", "admin") == ["nota.txt"]
    assert archivos.fs_leer("/atajo/nota.txt", "admin") == "hola"
    archivos.fs_mkdir("/atajo/nuevo", "admin")          # se crea dentro de /datos
    assert archivos.fs_listar("/datos", "admin") == ["nota.txt", "nuevo"]


def test_info_de_un_enlace_describe_al_enlace():
    archivos.fs_escribir("/nota.txt", "x" * 1000, "admin")
    archivos.fs_enlace_simbolico("/nota.txt", "/atajo", "cliente_a")
    assert archivos.fs_info("/atajo") == {
        "tipo": "enlace",
        "tamano": len("/nota.txt"),
        "propietario": "cliente_a",
        "grupo": "usuarios",
        "modo": "777",
        "bloques": [],
    }


def test_eliminar_un_enlace_no_borra_el_destino():
    archivos.fs_escribir("/nota.txt", "hola", "admin")
    archivos.fs_enlace_simbolico("/nota.txt", "/atajo", "admin")
    archivos.fs_eliminar("/atajo", "admin")
    assert archivos.fs_listar("/", "admin") == ["nota.txt"]


def test_chmod_sobre_un_enlace_cambia_el_destino():
    archivos.fs_escribir("/nota.txt", "hola", "admin")
    archivos.fs_enlace_simbolico("/nota.txt", "/atajo", "admin")
    archivos.fs_chmod("/atajo", "600", "admin")
    assert archivos.fs_info("/nota.txt")["modo"] == "600"
    assert archivos.fs_info("/atajo")["modo"] == "777"


def test_enlace_a_destino_inexistente_o_repetido_lanza_error():
    with pytest.raises(ErrorNoExiste):
        archivos.fs_enlace_simbolico("/no_existe", "/atajo", "admin")
    archivos.fs_escribir("/nota.txt", "hola", "admin")
    archivos.fs_enlace_simbolico("/nota.txt", "/atajo", "admin")
    with pytest.raises(ErrorYaExiste):
        archivos.fs_enlace_simbolico("/nota.txt", "/atajo", "admin")


def test_enlace_cuyo_destino_se_borro_lanza_error_al_usarlo():
    archivos.fs_escribir("/nota.txt", "hola", "admin")
    archivos.fs_enlace_simbolico("/nota.txt", "/atajo", "admin")
    archivos.fs_eliminar("/nota.txt", "admin")
    with pytest.raises(ErrorNoExiste):
        archivos.fs_leer("/atajo", "admin")


def test_enlaces_circulares_no_se_quedan_dando_vueltas():
    # Con las funciones públicas no se puede armar un ciclo (el destino debe
    # existir), así que se arma a mano para probar el límite de saltos.
    archivos.fs_escribir("/nota.txt", "hola", "admin")
    archivos.fs_enlace_simbolico("/nota.txt", "/a", "admin")
    archivos.fs_enlace_simbolico("/a", "/b", "admin")
    archivos._raiz["hijos"]["a"]["destino"] = "/b"      # ahora /a -> /b -> /a
    with pytest.raises(ErrorSistema):
        archivos.fs_leer("/a", "admin")


# ------------------------------------------------------------------ permisos
def test_otro_usuario_no_puede_crear_en_directorio_ajeno():
    archivos.fs_mkdir("/datos", "cliente_a")        # modo 755: los demás solo leen
    with pytest.raises(ErrorPermiso):
        archivos.fs_mkdir("/datos/intruso", "cliente_b")
    assert archivos.fs_listar("/datos", "cliente_b") == []      # leer sí puede


@pytest.mark.parametrize("modo, puede_listar, puede_crear", [
    ("700", False, False),      # solo el propietario
    ("750", True, False),       # el grupo lee y pasa, pero no escribe
    ("770", True, True),        # el grupo también escribe
])
def test_permisos_del_grupo(modo, puede_listar, puede_crear):
    """cliente_a y cliente_b están en el mismo grupo: manda el segundo dígito."""
    archivos.fs_mkdir("/datos", "cliente_a")
    archivos.fs_chmod("/datos", modo, "cliente_a")
    if puede_listar:
        assert archivos.fs_listar("/datos", "cliente_b") == []
    else:
        with pytest.raises(ErrorPermiso):
            archivos.fs_listar("/datos", "cliente_b")
    if puede_crear:
        archivos.fs_mkdir("/datos/nuevo", "cliente_b")
    else:
        with pytest.raises(ErrorPermiso):
            archivos.fs_mkdir("/datos/nuevo", "cliente_b")


def test_usuario_de_otro_grupo_usa_el_tercer_digito():
    archivos.crear_usuario("auditor", grupo="auditoria")
    archivos.fs_mkdir("/datos", "cliente_a")
    archivos.fs_chmod("/datos", "770", "cliente_a")
    with pytest.raises(ErrorPermiso):
        archivos.fs_listar("/datos", "auditor")


def test_sin_permiso_de_paso_no_se_llega_a_los_hijos():
    archivos.fs_mkdir("/datos", "cliente_a")
    archivos.fs_mkdir("/datos/web", "cliente_a")
    archivos.fs_chmod("/datos", "700", "cliente_a")
    with pytest.raises(ErrorPermiso):
        archivos.fs_listar("/datos/web", "cliente_b")


def preparar_archivos_de_cliente_a():
    """/nota.txt (600), /privado (700) con privado/nota.txt, y /datos (755)."""
    archivos.fs_escribir("/nota.txt", "de a", "cliente_a")
    archivos.fs_chmod("/nota.txt", "600", "cliente_a")
    archivos.fs_mkdir("/privado", "cliente_a")
    archivos.fs_escribir("/privado/nota.txt", "de a", "cliente_a")
    archivos.fs_chmod("/privado", "700", "cliente_a")
    archivos.fs_mkdir("/datos", "cliente_a")


OPERACIONES_SIN_PERMISO = [
    ("leer un archivo 600 ajeno", archivos.fs_leer, ("/nota.txt", "cliente_b")),
    ("escribir un archivo 600 ajeno", archivos.fs_escribir, ("/nota.txt", "x", "cliente_b")),
    ("agregar a un archivo 600 ajeno", archivos.fs_escribir, ("/nota.txt", "x", "cliente_b", True)),
    ("listar un directorio 700 ajeno", archivos.fs_listar, ("/privado", "cliente_b")),
    ("leer dentro de un directorio 700", archivos.fs_leer, ("/privado/nota.txt", "cliente_b")),
    ("crear directorio en uno 755 ajeno", archivos.fs_mkdir, ("/datos/x", "cliente_b")),
    ("crear archivo en uno 755 ajeno", archivos.fs_escribir, ("/datos/x.txt", "x", "cliente_b")),
    ("eliminar un archivo ajeno", archivos.fs_eliminar, ("/nota.txt", "cliente_b")),
    ("eliminar un directorio ajeno", archivos.fs_eliminar, ("/privado", "cliente_b", True)),
    ("chmod de un archivo ajeno", archivos.fs_chmod, ("/nota.txt", "777", "cliente_b")),
    ("crear enlace en un directorio 755 ajeno", archivos.fs_enlace_simbolico,
     ("/nota.txt", "/datos/atajo", "cliente_b")),
    ("enlace a algo dentro de un 700", archivos.fs_enlace_simbolico,
     ("/privado/nota.txt", "/atajo", "cliente_b")),
]


@pytest.mark.parametrize("descripcion, funcion, argumentos", OPERACIONES_SIN_PERMISO)
def test_rf1_toda_operacion_sin_permiso_lanza_error_permiso(descripcion, funcion, argumentos):
    preparar_archivos_de_cliente_a()
    antes = archivos.fs_estado_disco()
    with pytest.raises(ErrorPermiso):
        funcion(*argumentos)
    assert archivos.fs_estado_disco() == antes      # no cambió nada en el disco


@pytest.mark.parametrize("descripcion, funcion, argumentos", OPERACIONES_SIN_PERMISO)
def test_admin_ignora_los_permisos(descripcion, funcion, argumentos):
    preparar_archivos_de_cliente_a()
    argumentos = tuple("admin" if a == "cliente_b" else a for a in argumentos)
    funcion(*argumentos)                            # no debe lanzar ErrorPermiso


# ------------------------------------------------------------ estado del disco
def test_disco_recien_formateado_esta_todo_libre():
    assert archivos.fs_estado_disco() == {
        "bloques_totales": 200,
        "bloques_libres": 200,
        "huecos_libres": 1,
    }


def test_los_bloques_totales_salen_de_la_configuracion():
    archivos.reiniciar({"bloques_disco": 50})
    assert archivos.fs_estado_disco()["bloques_totales"] == 50
    assert archivos.fs_estado_disco()["bloques_libres"] == 50


def test_crear_directorios_y_enlaces_no_gasta_bloques():
    archivos.fs_mkdir("/datos", "admin")
    archivos.fs_enlace_simbolico("/datos", "/atajo", "admin")
    assert archivos.fs_estado_disco()["bloques_libres"] == 200


def test_bloques_ocupados_y_huecos_se_cuentan_bien():
    for nombre in ("/a.txt", "/b.txt", "/c.txt"):
        archivos.fs_escribir(nombre, "x" * 512, "admin")   # bloques 0, 1 y 2
    archivos.fs_eliminar("/b.txt", "admin")
    estado = archivos.fs_estado_disco()
    assert estado["bloques_libres"] == 198
    assert estado["huecos_libres"] == 2             # el bloque 1 y del 3 al 199
    verificar_rf1()


def test_rf1_usados_mas_libres_da_el_total_en_todo_momento():
    """300 operaciones al azar (semilla fija) en un disco chico que se llena."""
    archivos.reiniciar({"bloques_disco": 40, "tam_bloque": 16})
    archivos.fs_mkdir("/datos", "admin")
    rutas = ["/a.txt", "/b.txt", "/c.txt", "/datos/d.txt", "/datos/e.txt"]
    azar = random.Random(2026)
    for _ in range(300):
        operacion = azar.choice(["escribir", "agregar", "eliminar", "borrar_datos"])
        ruta = azar.choice(rutas)
        texto = "x" * azar.randint(0, 200)      # hasta 13 bloques: el disco se llena seguido
        try:
            if operacion == "escribir":
                archivos.fs_escribir(ruta, texto, "admin")
            elif operacion == "agregar":
                archivos.fs_escribir(ruta, texto, "admin", agregar=True)
            elif operacion == "eliminar":
                archivos.fs_eliminar(ruta, "admin")
            else:
                archivos.fs_eliminar("/datos", "admin", recursivo=True)
                archivos.fs_mkdir("/datos", "admin")
        except ErrorSistema:
            pass        # disco lleno o archivo que no existe: tampoco debe descuadrar nada
        verificar_rf1()


def test_politica_asignacion_devuelve_texto():
    assert archivos.politica_asignacion_archivos() == "indexada"
