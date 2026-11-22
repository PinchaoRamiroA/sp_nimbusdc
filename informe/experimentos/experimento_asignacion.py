"""Experimento: asignación contigua, enlazada e indexada con la misma carga.

Las tres políticas atienden la misma secuencia de operaciones (crear, crecer y
borrar archivos), generada con una semilla fija para que cualquiera obtenga los
mismos números. Se repite con 5 semillas y se promedia.

Enlazada e indexada reparten los bloques igual (cualquier bloque libre sirve);
la diferencia entre ellas está en cuántos accesos cuesta llegar a un bloque.

Ejecutar desde la raíz del repositorio:
    python informe/experimentos/experimento_asignacion.py
"""
import random

BLOQUES = 200           # tamaño del disco del escenario de ejemplo
OPERACIONES = 400
SEMILLAS = range(5)


# ------------------------------------------------------------------ carga
def generar_carga(semilla):
    """Devuelve la lista de operaciones: (tipo, id_archivo, cantidad_de_bloques).

    35 % crear (1 a 12 bloques), 30 % crecer (1 a 6 bloques) y 35 % borrar:
    con esa mezcla el disco se va llenando, en algunas semillas por encima del
    90 %, pero sin quedar saturado todo el tiempo.
    """
    azar = random.Random(semilla)
    carga = []
    vivos = []
    siguiente_id = 0
    for _ in range(OPERACIONES):
        tirada = azar.random()
        if tirada < 0.35 or not vivos:
            carga.append(("crear", siguiente_id, azar.randint(1, 12)))
            vivos.append(siguiente_id)
            siguiente_id += 1
        elif tirada < 0.65:
            carga.append(("crecer", azar.choice(vivos), azar.randint(1, 6)))
        else:
            id_archivo = azar.choice(vivos)
            vivos.remove(id_archivo)
            carga.append(("borrar", id_archivo, 0))
    return carga


# ------------------------------------------------------------ ayudas del disco
def marcar(mapa, bloques, ocupado):
    for numero in bloques:
        mapa[numero] = ocupado


def libres_desde(mapa, inicio, cantidad):
    """Indica si los ``cantidad`` bloques que empiezan en ``inicio`` están libres."""
    if inicio + cantidad > len(mapa):
        return False
    for numero in range(inicio, inicio + cantidad):
        if mapa[numero]:
            return False
    return True


def primer_hueco(mapa, cantidad):
    """Primer bloque desde donde caben ``cantidad`` bloques seguidos, o None."""
    for inicio in range(len(mapa)):
        if libres_desde(mapa, inicio, cantidad):
            return inicio
    return None


def contar_huecos(mapa):
    """Grupos de bloques libres seguidos (la misma cuenta que fs_estado_disco)."""
    huecos = 0
    anterior_ocupado = True
    for ocupado in mapa:
        if not ocupado and anterior_ocupado:
            huecos += 1
        anterior_ocupado = ocupado
    return huecos


# --------------------------------------------------------------- políticas
def crecer_contigua(mapa, bloques, cantidad, resultado):
    """Los bloques deben quedar seguidos. Si lo de al lado está ocupado, hay que mover el archivo."""
    if bloques and libres_desde(mapa, bloques[-1] + 1, cantidad):
        nuevos = list(range(bloques[-1] + 1, bloques[-1] + 1 + cantidad))
        marcar(mapa, nuevos, True)
        return bloques + nuevos
    total = len(bloques) + cantidad
    marcar(mapa, bloques, False)                # se suelta para buscarle un hueco entero
    inicio = primer_hueco(mapa, total)
    if inicio is None:
        marcar(mapa, bloques, True)             # no cupo: se deja como estaba
        return None
    resultado["bloques_movidos"] += len(bloques)
    nuevos = list(range(inicio, inicio + total))
    marcar(mapa, nuevos, True)
    return nuevos


def crecer_dispersa(mapa, bloques, cantidad, resultado):
    """Enlazada e indexada: sirven los primeros bloques libres, estén donde estén."""
    libres = [numero for numero, ocupado in enumerate(mapa) if not ocupado]
    if len(libres) < cantidad:
        return None
    nuevos = libres[:cantidad]
    marcar(mapa, nuevos, True)
    return bloques + nuevos


def accesos_para_un_bloque(politica, tamano):
    """Accesos promedio al disco para llegar a un bloque cualquiera de un archivo."""
    if politica == "enlazada":
        return (tamano + 1) / 2     # hay que recorrer la cadena desde el primer bloque
    return 1                        # contigua: inicio + k; indexada: el índice dice dónde está


# --------------------------------------------------------------- simulación
def simular(politica, carga):
    crecer = crecer_contigua if politica == "contigua" else crecer_dispersa
    mapa = [False] * BLOQUES
    archivos = {}               # id -> lista de bloques
    resultado = {"fallidas": 0, "fallidas_con_espacio": 0, "bloques_movidos": 0}
    suma_huecos = 0
    for tipo, id_archivo, cantidad in carga:
        if tipo == "borrar" or (tipo == "crecer" and id_archivo not in archivos):
            if id_archivo in archivos:
                marcar(mapa, archivos.pop(id_archivo), False)
        else:
            libres_antes = mapa.count(False)
            bloques = crecer(mapa, archivos.get(id_archivo, []), cantidad, resultado)
            if bloques is None:
                resultado["fallidas"] += 1
                if libres_antes >= cantidad:
                    resultado["fallidas_con_espacio"] += 1
            else:
                archivos[id_archivo] = bloques
        suma_huecos += contar_huecos(mapa)
    resultado["huecos_promedio"] = suma_huecos / len(carga)
    tamanos = [len(b) for b in archivos.values()]
    resultado["accesos_promedio"] = sum(accesos_para_un_bloque(politica, t) for t in tamanos) / len(tamanos)
    return resultado


def main():
    politicas = ["contigua", "enlazada", "indexada"]
    metricas = ["fallidas", "fallidas_con_espacio", "huecos_promedio", "bloques_movidos", "accesos_promedio"]
    promedios = {p: {m: 0.0 for m in metricas} for p in politicas}
    for semilla in SEMILLAS:
        carga = generar_carga(semilla)
        for politica in politicas:
            resultado = simular(politica, carga)
            for m in metricas:
                promedios[politica][m] += resultado[m] / len(SEMILLAS)

    print(f"Disco de {BLOQUES} bloques, {OPERACIONES} operaciones, promedio de {len(SEMILLAS)} semillas\n")
    print(f"{'métrica':<24}" + "".join(f"{p:>12}" for p in politicas))
    for m in metricas:
        print(f"{m:<24}" + "".join(f"{promedios[p][m]:>12.1f}" for p in politicas))


if __name__ == "__main__":
    main()
