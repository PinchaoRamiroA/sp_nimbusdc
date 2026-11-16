"""Pruebas del avance de ``archivos`` (Prototipo 1): usuarios, directorios, permisos y bloques."""
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


# ------------------------------------------------------- formateo y usuarios
def test_formatear_deja_la_raiz_vacia_y_de_admin():
    info = archivos.fs_info("/")
    assert info["tipo"] == "directorio"
    assert info["propietario"] == "admin"
    assert archivos.fs_listar("/", "admin") == []


def test_formatear_borra_directorios_y_usuarios_anteriores():
    archivos.fs_mkdir("/datos", "cliente_a")
    archivos.formatear_disco()
    assert archivos.fs_listar("/", "admin") == []
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
    # Todavía no existe fs_escribir: el archivo se coloca a mano en el árbol.
    archivos._raiz["hijos"]["nota.txt"] = archivos._nuevo_nodo("archivo", "admin", "644")
    with pytest.raises(ErrorSistema):
        archivos.fs_listar("/nota.txt", "admin")
    with pytest.raises(ErrorSistema):
        archivos.fs_mkdir("/nota.txt/datos", "admin")
    with pytest.raises(ErrorNoExiste):
        archivos.fs_info("/nota.txt/datos/otro")


# ------------------------------------------------------------------ permisos
def test_otro_usuario_no_puede_crear_en_directorio_ajeno():
    archivos.fs_mkdir("/datos", "cliente_a")        # modo 755: los demás solo leen
    with pytest.raises(ErrorPermiso):
        archivos.fs_mkdir("/datos/intruso", "cliente_b")
    assert archivos.fs_listar("/datos", "cliente_b") == []      # leer sí puede


def test_admin_ignora_los_permisos():
    archivos.fs_mkdir("/datos", "cliente_a")
    archivos.fs_mkdir("/datos/respaldo", "admin")
    assert archivos.fs_listar("/datos", "admin") == ["respaldo"]


@pytest.mark.parametrize("modo, puede_listar, puede_crear", [
    ("700", False, False),      # solo el propietario
    ("750", True, False),       # el grupo lee y pasa, pero no escribe
    ("770", True, True),        # el grupo también escribe
])
def test_permisos_del_grupo(modo, puede_listar, puede_crear):
    """cliente_a y cliente_b están en el mismo grupo: manda el segundo dígito."""
    archivos.fs_mkdir("/datos", "cliente_a")
    archivos._raiz["hijos"]["datos"]["modo"] = modo     # aún no existe fs_chmod
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
    archivos._raiz["hijos"]["datos"]["modo"] = "770"    # aún no existe fs_chmod
    with pytest.raises(ErrorPermiso):
        archivos.fs_listar("/datos", "auditor")


def test_sin_permiso_de_paso_no_se_llega_a_los_hijos():
    archivos.fs_mkdir("/datos", "cliente_a")
    archivos.fs_mkdir("/datos/web", "cliente_a")
    archivos._raiz["hijos"]["datos"]["modo"] = "700"    # aún no existe fs_chmod
    with pytest.raises(ErrorPermiso):
        archivos.fs_listar("/datos/web", "cliente_b")


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


def test_crear_directorios_no_gasta_bloques():
    archivos.fs_mkdir("/datos", "admin")
    assert archivos.fs_estado_disco()["bloques_libres"] == 200


def test_bloques_ocupados_y_huecos_se_cuentan_bien():
    # Todavía no existe fs_escribir: los bloques se ocupan a mano en el mapa.
    for bloque in (0, 1, 10, 199):
        archivos._mapa_bloques[bloque] = True
    estado = archivos.fs_estado_disco()
    assert estado["bloques_libres"] == 196
    assert estado["huecos_libres"] == 2             # del 2 al 9 y del 11 al 198
    usados = archivos._mapa_bloques.count(True)
    assert usados + estado["bloques_libres"] == estado["bloques_totales"]


def test_politica_asignacion_devuelve_texto():
    assert isinstance(archivos.politica_asignacion_archivos(), str)
