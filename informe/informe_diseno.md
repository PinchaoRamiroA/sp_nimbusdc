# Informe de decisiones de diseño — NimbusDC (`minidc`)

> **Curso:** Sistemas Operativos 1 (IS734) — Universidad Tecnológica de Pereira  
> **Periodo:** Noviembre–diciembre de 2026  
> **Equipo:** Santiago Ardila - Ramiro Pinchao - Santiago Ramirez - Kenneth Rodriguez

---

## 1. Diagrama y descripción de la arquitectura

*(Incluir diagrama de arquitectura que muestre la interacción entre `kernel`, `procesos`, `memoria`, `disco`, `archivos`, `sincronizacion`, `consola` y `errores`.)*

---

## 2. Decisiones de diseño por subsistema

### 2.1 Gestión de CPU y procesos (`procesos.py` y `kernel.py`)
> **Estado:** Prototipo 1 y Prototipo 2 completos.

- **Algoritmo elegido:**
  - **Planificador multinivel con colas de prioridad (MLFQ) y envejecimiento (Aging):** Tres colas ordenadas por prioridad (0: Alta/Web, 1: Media, 2: Baja/Analítica).
  - **Preempción inmediata por prioridad:** Si un proceso de mayor prioridad pasa a estado `LISTO` (por llegada o por despertar de E/S o memoria), desaloja inmediatamente a un proceso de menor prioridad que ocupe la CPU, registrando un cambio de contexto y garantizando baja latencia de respuesta.
  - **Envejecimiento anti-inanición:** Promoción automática de prioridad ($P \leftarrow P - 1$) para todo proceso en `LISTO` que acumule 50 ticks consecutivos sin recibir CPU.
  - **Gestión multihilo cooperativa/Round-Robin (Prototipo 2):** Implementación de `crear_hilo(pid, programa)`, asignando a cada hilo un `tid` único incremental, su propio contador de programa (`pc`) y estado. Dentro del turno de CPU asignado a un proceso padre, sus hilos listos se despachan equitativamente. Si un hilo se bloquea (por E/S o fallo de página), los demás hilos listos del mismo proceso pueden seguir ejecutando ráfagas.
  - **Orquestación en tiempo discreto (`kernel.py`):** Reloj entero global coordinado en `tick()` bajo el ciclo estricto de 4 pasos fijado por el enunciado: (1) Llegadas del escenario, (2) Atención de E/S y resolución de fallos de memoria terminados (despertar a `LISTO`), (3) Despacho y ejecución de CPU, y (4) Actualización de esperas consecutivas, envejecimiento y métricas.

- **Alternativas evaluadas (mínimo 2):**
  1. **First-Come, First-Served (FCFS):** Despacho estricto por orden de llegada sin preempción. Aunque posee costo computacional de selección $O(1)$ y cero cambios de contexto adicionales, genera el efecto convoy cuando procesos analíticos con ráfagas de cómputo largas acaparan la CPU, elevando inaceptablemente el tiempo de respuesta de las solicitudes web e incurriendo en inanición temporal.
  2. **Round-Robin puro (RR):** Asignación equitativa mediante rodajas de tiempo fijas. Si bien previene la inanición sin requerir contadores de envejecimiento, trata a todas las cargas por igual; una solicitud web interactiva sufre latencias elevadas si coincide detrás de múltiples procesos analíticos en la misma cola circular, impidiendo cumplir la cota estricta de RP1 ($T_r \le 10$).

- **Experimento y métricas comparativas:**
  - **Carga de prueba:** Escenario sintético reproducible con semilla fija compuesto por 1 proceso de analítica pesada ($50$ ticks continuos de CPU) y ráfagas periódicas de 5 servicios web ($2$ ticks de CPU, $1$ E/S) inyectados concurrentemente.
  - **Resultados medidos:**
    * *FCFS:* Tiempo de respuesta promedio web: $26.4$ ticks; Utilización de CPU: $94\%$; Espera máxima en baja prioridad: $48$ ticks. (Falla RP1).
    * *Round-Robin (quantum = 2):* Tiempo de respuesta promedio web: $13.2$ ticks; Utilización de CPU: $89\%$; Espera máxima: $62$ ticks. (Falla RP1).
    * *MLFQ con Preempción + Aging (Elegido):* Tiempo de respuesta promedio web: $1.2$ ticks; Utilización de CPU: $91\%$; Espera máxima en baja prioridad: $52$ ticks (promovido antes de inanición). (Cumple RP1, RP2 y RP3).

- **Justificación frente a los requisitos:**
  - **RP1 ($T_r \le 10$ en web):** Cumplido. La prioridad 0 asignada a servicios web combinada con preempción inmediata permite que cualquier ráfaga web reciba CPU en $0$ o $1$ tick tras su llegada, sin esperar a que culminen las ráfagas analíticas.
  - **RP2 (Espera consecutiva $< 150$ ticks):** Cumplido. El umbral de envejecimiento de 50 ticks garantiza que un proceso en prioridad 2 ascienda a prioridad 1 a los 50 ticks y a prioridad 0 a los 100 ticks. Al llegar a la cola máxima, compite en igualdad de condiciones, resultando matemáticamente imposible superar los 150 ticks continuos en espera.
  - **RP3 (Utilización de CPU $\ge 85\%$):** Cumplido. El planificador mantiene ocupada la CPU siempre que existan procesos listos; el despacho en $O(1)$ mediante `collections.deque` no introduce retardos simulados vacíos.
  - **RM3 (Protección de memoria ante accesos inválidos):** Cumplido en el Prototipo 2. Al ejecutar la instrucción `("MEM", dir)`, si la dirección excede `memoria_bytes` o es negativa, el núcleo captura `ErrorMemoria`, aborta limpiamente al proceso infractor mediante `terminar_proceso(pid)` (liberando marcos, swap y cancelando E/S pendientes) y cede la CPU sin detener el reloj ni alterar la cola de los demás procesos sanos.

- **Limitaciones:**
  - El envejecimiento no degrada automáticamente a los procesos una vez atendidos (vuelven a su prioridad original tras completar su ciclo de E/S o culminar su quantum).
  - La sincronización mediante primitivas `WAIT` y `SIGNAL` sobre semáforos/mutex se integra en el Prototipo 3.

### 2.2 Gestión de memoria virtual (`memoria.py`)
> Estado: Prototipo 2 (completo). Responsable: Integrante 2.
- **Algoritmo elegido:** paginación por demanda con **reemplazo local** y política del **Reloj (segunda oportunidad)**, el plan del equipo de la guía conceptual (sección 5.7). Un proceso nunca tiene más de `cuota_marcos` páginas residentes y solo saca páginas **suyas**.
- **Cómo funciona:**
  - Traducción con las herramientas de la guía: `ceil(memoria_bytes / tam_pagina)` páginas por proceso y `pagina, desplazamiento = divmod(direccion, tam_pagina)`.
  - **Fallo de página:** (1) si el proceso tiene cuota libre y hay un marco libre, lo usa; (2) si no, la víctima es una de sus propias páginas, elegida por el Reloj: la manecilla recorre las páginas residentes del proceso; si `referenciada` es `True` la pone en `False` y sigue; si es `False`, la reemplaza; (3) única excepción: si el proceso no tiene ninguna página residente y no hay marcos libres, no podría avanzar, y toma un marco del proceso con más marcos. Solo ocurre cuando la suma de las cuotas supera los marcos físicos.
  - Una página `modificada` que sale de memoria cuenta como escritura al swap (`escrituras_a_swap`).
  - **RM3:** la dirección se valida (`0 <= dir < memoria_bytes`) **antes** de tocar cualquier estado. Si está fuera, lanza `ErrorMemoria` y no cambian ni las tablas, ni los marcos, ni las métricas. `procesos` captura la excepción y termina solo al proceso infractor.
  - **Fragmentación interna** (guía 5.4): por proceso, `ceil(bytes / tam_pagina) * tam_pagina - bytes`, sumada para todos los procesos con memoria registrada.
  - **Hiperpaginación:** se diagnostica cuando más de la mitad de los últimos 32 accesos fueron fallos (mínimo 16 accesos). La reacción (RM2) llega en el Prototipo 3.
- **Integración con los otros módulos:**
  - `memoria` no importa `kernel`. Si le preguntan por un PID que nadie registró, lee su `memoria_bytes` y su `cuota_marcos` de `procesos` (import diferido), así que no depende de que `crear_proceso` la llame. Esto resuelve el pendiente de la guía 5.11 ("hay que acordar cómo le llegan el tamaño y la cuota"). También existe `registrar_proceso(pid, memoria_bytes, cuota_marcos)` para registrarlo de forma explícita.
  - Cada registro recuerda de qué proceso de `procesos` salió. Si el kernel se reinicia y los PID vuelven a empezar, el nuevo PID 1 no hereda la memoria del anterior: se registra de nuevo. Un acceso de un proceso TERMINADO lanza `ErrorNoExiste` sin tocar las métricas.
  - `estado_memoria` cuenta a todos los procesos vivos, aunque todavía no hayan accedido a memoria.
  - El bloqueo de 5 ticks por fallo de página lo aplica `procesos`; `memoria` solo informa `fallo_pagina`.
  - Cumple "un proceso que termina libera su memoria" aunque el proceso termine solo: antes de asignar marcos y al reportar su estado, libera los procesos que `procesos` ya marcó como TERMINADO.
  - Funciones adicionales: `reiniciar(config)` (la llama `kernel.iniciar_sistema`), `registrar_proceso` y `_fijar_politica` (solo para experimentos).
- **Alternativas evaluadas (mínimo 2):**
  1. **LRU, local.** Sale la página usada hace más tiempo.
  2. **FIFO, local.** Sale la página cargada hace más tiempo, aunque se esté usando mucho.
  3. **Reparto de marcos (decisión de diseño).** Se probaron dos variantes que quitan marcos a otros procesos: "el que no encuentra marco libre se lo quita al que tiene más" (41–48 % de fallos en sobrecarga, fallos en cadena) y una asignación proporcional `marcos × cuota / Σcuotas` (33–38 %). Se descartaron porque rompen el reemplazo local que el equipo eligió (guía 5.8 y 5.12: un proceso no debe sacar páginas de otro). Con cuotas que caben en memoria no hay diferencia.
- **Experimento y métricas comparativas:**
  - **Validación con la guía (5.7):** las tres políticas reproducen exactamente los números de la guía: secuencia clásica de 20 accesos con 3 marcos → LRU 12, Reloj 14 y FIFO 15 fallos; anomalía de Belady → FIFO y Reloj pasan de 9 a 10 fallos con 4 marcos y LRU baja de 10 a 8; y el ejemplo del Reloj paso a paso.
  - **Carga del proyecto:** `python informe/experimentos/experimento_memoria.py`. 5 semillas fijas y la misma carga para las tres políticas. Cada servicio accede con localidad: en cada fase, el 85 % de los accesos va a un conjunto "caliente" de `cuota − 1` páginas y el 15 % a cualquier página; el 30 % son escrituras. Los procesos se intercalan (un acceso de cada uno por turno). Se miden `tasa_fallos`, `reemplazos` y `escrituras_a_swap`.

  | Carga | Reloj | LRU | FIFO |
  |---|---|---|---|
  | Nominal (Σcuotas = 15 ≤ 16 marcos), tasa de fallos promedio | 0,189 | **0,171** | 0,202 |
  | Nominal, rango en las 5 semillas | 0,165–0,203 | 0,141–0,182 | 0,179–0,215 |
  | Sobrecarga (Σcuotas = 22 > 16 marcos), promedio | 0,362 | **0,342** | 0,369 |

  - **Con el kernel completo** (rama `feature/nucleo-prototipo2` del Integrante 1 + este módulo): el escenario `tests/escenarios/memoria.json` termina con **16,5 % de fallos** y los 16 marcos libres al final.
- **Justificación frente a los requisitos (RM1–RM3):**
  - **RM1:** 16,5 % con el kernel completo y como máximo 20,3 % en las 5 semillas: por debajo del 25 %.
  - **RM3:** la validación previa garantiza que un acceso inválido no modifica nada, y el reemplazo local impide que un proceso le saque páginas a otro. Lo comprueban `test_acceso_invalido_no_cambia_ningun_estado`, `test_reemplazo_local_no_quita_marcos_a_otro_proceso` y `test_rm3_proceso_real_fuera_de_su_espacio_no_afecta_a_otros`.
  - **Por qué el Reloj y no LRU:** LRU tuvo 1,8 puntos menos de fallos, pero ambos cumplen RM1 con margen. El Reloj es el plan del equipo y usa el bit `referenciada` de la tabla de páginas del enunciado; LRU exacto requiere guardar el instante de cada acceso, algo que el hardware real no hace. LRU queda implementado: cambiarlo es una línea (`_POLITICA`).
- **Limitaciones:**
  - Con memoria sobrecomprometida la tasa sube a ~36 % y no cumple RM1: es el caso de hiperpaginación que el Prototipo 3 debe atender (RM2).
  - El Reloj, igual que FIFO, puede sufrir la anomalía de Belady (lo muestra la prueba `test_anomalia_de_belady`).
  - La excepción de "sin páginas propias" quita un marco a otro proceso; solo ocurre si Σcuotas > marcos.
  - El swap no se modela como dispositivo: las escrituras al swap solo se cuentan, no consumen ticks de disco (duda abierta de la guía 7.5).
  - La carga del experimento tiene localidad diseñada (85 % de accesos a `cuota − 1` páginas calientes); el resultado depende de esa localidad. El experimento intercala un acceso por proceso y no modela el bloqueo de 5 ticks; con reemplazo local y cuotas que caben no cambia la tasa (el kernel completo da el mismo 16,5 %).
  - El escenario `memoria.json` usa `("MEM", dir)` de dos elementos, como define el enunciado, sin indicar escritura; por eso con el kernel `escrituras_a_swap` es 0, aunque el experimento sí mide escrituras.

### 2.3 Planificación de disco y caché (`disco.py`)
> Estado: Prototipo 2 (completo). Responsable: Integrante 2.
- **Algoritmo elegido:** **C-LOOK**, el plan del equipo (guía 6.5), más una **caché LRU de bloques**.
  - C-LOOK (guía 6.8): `_elegir_siguiente(cola, cabezal)` devuelve la solicitud de menor bloque **mayor o igual** al cabezal; si no hay ninguna, la de menor bloque de todas (el salto de regreso). A igual bloque, la más antigua.
  - Detalle anti-inanición: en el mismo bloque donde está el cabezal solo se atienden en esta pasada las solicitudes que ya existían cuando el cabezal llegó; las que llegan después esperan a la siguiente pasada. Sin esto, un flujo constante de solicitudes a ese bloque dejaría esperando para siempre a las demás (lo encontró la revisión independiente). `_elegir_siguiente` recibe para eso un tercer parámetro opcional, `id_limite`.
  - Caché: guarda los últimos `cache_bloques` bloques leídos o escritos (LRU con `OrderedDict`). Las decisiones que la guía 6.7 deja abiertas: una lectura de un bloque en caché es un **acierto**, no usa el cabezal (no suma desplazamiento) y termina en el siguiente tick, en paralelo con la solicitud en servicio; las escrituras siempre van al disco (escritura directa) y dejan el bloque en caché; `info_cache` cuenta solo lecturas.
- **Decisiones que se mantienen del Prototipo 1:** tiempo de servicio `1 + abs(cabezal - bloque) // 10`; `disco` no importa `procesos` ni `kernel` (el kernel llama a `avanzar_tick()` en el paso 2 del tick y recibe los PID cuya E/S terminó); iniciar y descontar el servicio en la misma llamada para no perder ticks; un bloque u operación inválidos lanzan `ErrorSistema`; `procesar_disco()` atiende todo de una vez sin consumir ticks ni liberar procesos (sirve para medir). El salto de C-LOOK cuenta como desplazamiento, porque el cabezal sí se mueve (guía 6.5).
- **Funciones adicionales:** `reiniciar`, `avanzar_tick`, `cancelar_solicitudes`, `estadisticas_espera()` (espera máxima y promedio, desde que se encola hasta que termina, guía 6.6) y `_fijar_politica` (solo experimentos). `metricas_disco()` conserva exactamente las 3 claves del enunciado.
- **Alternativas evaluadas (mínimo 2):**
  1. **FCFS** (línea base de RD1; era la política del Prototipo 1).
  2. **SSTF** (la más cercana al cabezal, hacia cualquier lado).
  3. **C-LOOK con límite de espera (descartada).** Se probó atender primero a la solicitud que llevara 100 ticks o más en cola. En la prueba de carga (experimento D) empeoró mucho el sistema: con 0,75 solicitudes por tick la espera máxima pasó de 108 a 1880 ticks, porque al atender por antigüedad el disco vuelve a recorridos largos (como FCFS) y la cola se desborda. C-LOOK no la necesita: en cada pasada el cabezal llega hasta la última solicitud y vuelve, así que ninguna espera más de una vuelta.
- **Experimento y métricas comparativas:** `python informe/experimentos/experimento_disco.py`, con 5 semillas fijas.
  - **Validación con la guía (6.5):** con el cabezal en 53 y los bloques `98, 183, 37, 122, 14, 124, 65, 67`, el módulo da el mismo orden y desplazamiento que la tabla de la guía: FCFS 640, SSTF 236 y C-LOOK 322.
  - **A) Lote** (cabezal inicial al azar y 40 solicitudes con `procesar_disco`): ahorro frente a FCFS de 84,4–87,8 % con C-LOOK y de 89,5–92,6 % con SSTF. Con todas las solicitudes presentes desde el principio no hay llegadas nuevas, así que este caso favorece a SSTF y no mide la espera; por eso el experimento principal es el B.
  - **B) Dinámico** (escenario de respaldo, 10 procesos × 8 E/S, con el kernel real):

    | Semilla | Ahorro C-LOOK | Ahorro SSTF | Espera máx. C-LOOK | Espera máx. SSTF | Espera máx. FCFS |
    |---|---|---|---|---|---|
    | 1 | 62,2 % | 66,1 % | 62 | 81 | 110 |
    | 2 | 55,0 % | 58,5 % | 50 | 84 | 98 |
    | 3 | 55,4 % | 65,1 % | 64 | 44 | 109 |
    | 4 | 58,4 % | 61,7 % | 51 | 53 | 85 |
    | 5 | 61,6 % | 70,5 % | 57 | 69 | 95 |

  - **C) Inanición:** una solicitud al bloque 190 mientras llega una solicitud cercana (bloques 0–30) por tick. **SSTF nunca la atiende**; FCFS tarda 21 ticks y **C-LOOK 22 ticks**.
  - **D) Carga creciente** (llegadas al azar durante 2000 ticks; espera máxima, peor de 5 semillas):

    | Solicitudes por tick | 0,1 | 0,2 | 0,4 | 0,6 | 0,7 | 0,8 | 0,9 |
    |---|---|---|---|---|---|---|---|
    | FCFS | 112 | 1104 | 4106 | 6871 | 8250 | 9849 | 11234 |
    | SSTF | 53 | 76 | 117 | 161 | 186 | 186 | 222 |
    | C-LOOK | 56 | 63 | 65 | 93 | 104 | 126 | 211 |
- **Justificación frente a los requisitos (RD1):**
  - Ahorro del 55–62 % frente a FCFS en el escenario dinámico (se pide ≥ 30 %) y espera máxima de 50–64 ticks (se pide ≤ 200).
  - SSTF mueve un poco menos el cabezal, pero puede dejar una solicitud esperando para siempre (experimento C) y su espera máxima crece más rápido con la carga (experimento D). C-LOOK mantiene la espera más baja hasta 0,8 solicitudes por tick.
  - El escenario `tests/escenarios/disco.json` lo comprueba con el kernel completo (`test_rd1_escenario_de_disco_con_el_kernel`).
- **Limitaciones:**
  - RD1 se cumple hasta unas 0,8 solicitudes por tick. Con 0,9 o más el disco está sobrecargado (la cola crece sin parar) y ningún planificador garantiza las 200 ticks.
  - `estadisticas_espera` solo mide solicitudes terminadas; por eso el experimento B se detiene con error si un escenario no termina, en vez de reportar números parciales.
  - Un acierto de caché termina en 1 tick en vez de seguir la fórmula de servicio. Es la razón de ser de la caché, pero hay que tenerlo en cuenta al comparar tiempos.
  - La caché solo atiende la E/S de procesos (`("ES", bloque)`); `archivos.py` no pasa por ella.
  - El tiempo de servicio no distingue lectura de escritura.

### 2.4 Asignación de bloques de archivos (`archivos.py`)
> Estado: Prototipo 2 (completo).
- **Algoritmo elegido:** asignación indexada. Cada archivo guarda en su nodo la lista de bloques que ocupa, que hace de índice, como los punteros de un inodo en Unix. Un archivo de N bytes ocupa N / `tam_bloque` bloques, redondeado hacia arriba. Al crecer se le agregan los primeros bloques libres del disco, estén seguidos o no, y al achicarse devuelve los que le sobran desde el final del índice. Todo esto está en una sola función, `_ajustar_bloques`.
- **Decisiones de diseño:**
  - **Estructura:** el árbol de archivos son diccionarios anidados y cada directorio guarda a sus hijos por nombre. `archivos` no importa `kernel`, `procesos` ni `disco`, y lleva su propio mapa de bloques (una lista de ocupado/libre). `kernel.iniciar_sistema` llama a `reiniciar(config)`, que toma `bloques_disco` y `tam_bloque`.
  - **Permisos:** como en Unix (propietario, grupo y otros); `admin` los ignora. Crear un archivo o directorio pide escribir y entrar en la carpeta; sobrescribir pide escribir en el archivo; leer pide leer. `fs_chmod` solo lo puede hacer el dueño o `admin`, con tres dígitos del 0 al 7.
  - **Borrado:** pide escribir y entrar en la carpeta y, además, ser el dueño o `admin`. La raíz es `777` (el enunciado no tiene una función para cambiar el propietario), así que sin esta regla cualquier cliente podría borrar los archivos de otro; es lo que hace `/tmp` en Unix con el bit *sticky*. Un directorio vacío se borra sin `recursivo`; con contenido lo necesita, y antes de borrar se revisan los permisos de todo lo que hay adentro para no dejar el borrado a medias.
  - **Enlaces simbólicos:** guardan la ruta destino, que debe existir al crearlos. Se siguen en las rutas intermedias y al leer, escribir, listar y en `chmod`; `fs_info` y `fs_eliminar` actúan sobre el enlace mismo, como en Unix. Hay un límite de 40 saltos, como en Linux, para que un ciclo no se quede dando vueltas.
  - **Espacio:** si no hay bloques suficientes, `fs_escribir` lanza `ErrorSistema` antes de tocar nada. Los directorios y los enlaces no ocupan bloques; el tamaño de un enlace es el de su ruta destino.
  - **Formatos:** `formatear_disco` borra también los usuarios, salvo `admin`. En `fs_info`, `bloques` es la lista de bloques del archivo *(por confirmar con el docente si se espera un número)*. En `fs_estado_disco`, `huecos_libres` es la cantidad de grupos de bloques libres seguidos.
- **Alternativas evaluadas (mínimo 2):**
  1. Asignación contigua: cada archivo ocupa bloques seguidos; para crecer necesita que lo de al lado esté libre o hay que moverlo entero a otro hueco.
  2. Asignación enlazada: cada bloque apunta al siguiente; usa cualquier bloque libre, pero para llegar al bloque k hay que recorrer la cadena desde el primero.
- **Experimento y métricas comparativas:** `informe/experimentos/experimento_asignacion.py` (se ejecuta con `python informe/experimentos/experimento_asignacion.py`). Las tres políticas atienden la misma carga sobre un disco de 200 bloques: 400 operaciones de crear (35 %, de 1 a 12 bloques), crecer (30 %, de 1 a 6 bloques) y borrar (35 %), generadas con `random.Random(semilla)` y promediadas sobre 5 semillas.

  | Métrica (promedio de 5 semillas) | Contigua | Enlazada | Indexada |
  |---|---|---|---|
  | Escrituras que fallaron | 18.2 | 12.0 | 12.0 |
  | Fallaron habiendo espacio libre suficiente | 17.6 | 0.0 | 0.0 |
  | Huecos libres promedio | 4.9 | 4.2 | 4.2 |
  | Bloques que hubo que mover para crecer | 410.2 | 0.0 | 0.0 |
  | Accesos para llegar a un bloque cualquiera | 1.0 | 4.8 | 1.0 |

  Casi todas las fallas de la contigua (17.6 de 18.2) pasan con espacio libre de sobra, por la fragmentación externa, y además tiene que mover 410 bloques para que los archivos crezcan. Enlazada e indexada solo fallan cuando el disco está lleno de verdad, pero la enlazada necesita en promedio 4.8 accesos para llegar a un bloque, contra 1 de la indexada.
- **Justificación frente a los requisitos (RF1):**
  - **Permisos:** toda función que recibe usuario revisa sus permisos antes de cambiar algo. `tests/test_archivos.py` recorre 12 operaciones distintas sin permiso (leer, escribir, agregar, listar, entrar, crear, borrar, `chmod` y enlaces) y comprueba que todas lanzan `ErrorPermiso` sin tocar el disco, y que `admin` sí puede hacerlas.
  - **Bloques:** usados más libres siempre da el total, porque los dos se cuentan sobre el mismo mapa y `_ajustar_bloques` revisa el espacio antes de reservar. Una prueba hace 300 operaciones al azar con semilla fija en un disco de 40 bloques que se llena varias veces, y después de cada una suma los bloques de todos los archivos y verifica que dé el total sin bloques repetidos.
- **Limitaciones:**
  - **Índice:** vive en el nodo y no se modela como un bloque de índice en el disco, que en un disco real costaría un bloque más por archivo y un acceso extra.
  - **Rutas:** solo se aceptan absolutas (la consola arma las relativas) y no se interpretan `.` ni `..`.
  - **Asignación:** siempre se toman los primeros bloques libres, sin intentar dejar juntos los de un mismo archivo.
  - **Disco:** `archivos` no genera solicitudes en `disco.py`, así que leer y escribir archivos no mueve el cabezal ni usa la caché.

### 2.5 Sincronización e interbloqueos (`sincronizacion.py`)
- **Mecanismo y estrategia elegidos:**
- **Alternativas evaluadas (mínimo 2):**
  1. 
  2. 
- **Experimento y métricas comparativas:**
- **Justificación frente a los requisitos (RS1–RS2):**
- **Limitaciones:**

---

## 3. Lista de pruebas propias

- `tests/test_disco.py` (41 pruebas): fórmula de servicio, cancelar, reiniciar, validaciones y métricas (Prototipo 1); orden C-LOOK con salto, desempate por antigüedad, ahorro ≥ 30 % frente a FCFS en 5 semillas, que C-LOOK no deje esperando a una solicitud lejana, `estadisticas_espera`, el ejemplo de la guía con el cabezal en 53 (FCFS, SSTF y C-LOOK), que un flujo al bloque del cabezal no deje esperando a otra, validación de la configuración, y caché LRU: aciertos sin mover el cabezal, expulsión LRU, escritura directa, capacidad 0, cancelación y reinicio (Prototipo 2).
- `tests/test_memoria.py` (36 pruebas): traducción y formato de `tabla_paginas`, copias, `ErrorMemoria` fuera del espacio (RM3) sin cambiar ningún estado, cuota de marcos, víctima del Reloj, LRU y FIFO, reemplazo local estricto y su única excepción, escrituras al swap, `liberar_memoria`, `estado_memoria` (fragmentación interna sumada), `metricas_memoria`, reinicio, hiperpaginación y los ejemplos de la guía (Reloj paso a paso, secuencia clásica de 20 accesos y anomalía de Belady).
- `tests/test_requisitos_memoria_disco.py` (12 pruebas): formato de los escenarios `memoria.json` y `disco.json`; RM1 con los accesos del escenario y con el kernel completo (se omite mientras `procesos` no ejecute `MEM`); RM3 con procesos reales; liberación de memoria al terminar (por `terminar_proceso` y al terminar solo); RD1 con el kernel completo (C-LOOK ≤ 70 % del desplazamiento de FCFS y espera ≤ 200); y regresiones de la revisión independiente (PID reutilizado tras reiniciar el kernel, acceso de un proceso TERMINADO y fragmentación de procesos que aún no acceden).
- `tests/test_disco_kernel_simulado.py` (6 pruebas): con un kernel simulado, `("ES", 40)` bloquea al proceso 5 ticks.
- `tests/test_archivos.py` (83 pruebas): formateo, usuarios, directorios, escribir y leer (bytes, bloques por tamaño, disco lleno), eliminar (normal, recursivo y sin dejarlo a medias), `chmod`, enlaces simbólicos, permisos por propietario, grupo y otros, y RF1: 12 operaciones sin permiso que deben lanzar `ErrorPermiso` y 300 operaciones al azar verificando que usados más libres dé el total.
- `tests/test_escenarios.py` (24 pruebas): valida el formato de los escenarios y mide RP1, RP2 y RP3 sobre ellos usando solo funciones del enunciado. Todas pasando tras la integración del catálogo y usuarios en `kernel.cargar_escenario`.
- `tests/test_prototipo1.py` (17 pruebas): pruebas unitarias y de integración para `kernel.py` y `procesos.py`, verificando el ciclo de 4 pasos, el planificador MLFQ con aging, preempción y el cumplimiento formal de RP1, RP2 y RP3.
- `tests/test_prototipo2.py` (19 pruebas): pruebas unitarias y de integración para `kernel.py` y `procesos.py` en el Prototipo 2. Valida la asignación incremental de TIDs independientes por proceso, despacho concurrente desacoplado de hilos, el bloqueo exacto y determinista de 5 ticks ante fallo de página en la instrucción `("MEM", dir)`, el cumplimiento del requisito RM3 (proceso infractor termina limpiamente ante `ErrorMemoria` sin afectar a procesos concurrentes) e integración multiprocesador (`num_cpus=2`).
- `tests/test_consola.py` (35 pruebas): pruebas para `consola.py`, verificando comandos de procesos (`ps`, `kill`, `run` con catálogo del escenario, `tick`, `top`), comandos de archivos (`pwd`, `cd`, `ls` con `-l`, `mkdir`, `touch`, `cat`, `echo` con `>` y `>>`, `rm` con `-r`, `chmod`, `ln -s`, `tree`), comandos de recursos (`free` y `df`), el aislamiento de `historial` y `directorio_actual` por usuario, las variantes de Windows (`tasklist`, `taskkill`, `dir`, `md`, `type`, `del`, `mklink`), el formato obligatorio de errores (`Error:...`), control de permisos entre usuarios sobre el sistema de archivos y soporte de rutas con espacios en `load`.
- `tests/test_estructura.py` (9 pruebas): verificación de importaciones públicas, jerarquía de excepciones en `errores.py` y coincidencia exacta de firmas obligatorias.
- Escenarios en `tests/escenarios/` (formato del enunciado): `ejemplo_enunciado.json` (el ejemplo del enunciado), `base.json` (mezcla de web, respaldo y analítica; RP1), `inanicion.json` (un servicio web cada 4 ticks frente a una analítica de baja prioridad; RP2) y `carga_cpu.json` (tres analíticas y cinco web; RP3). En los escenarios propios la prioridad 0 es la más alta, como en el planificador del equipo. Prototipo 2: `memoria.json` (analítica, dos web y respaldo con accesos `("MEM", dir)` con localidad; Σcuotas = 15 ≤ 16 marcos; RM1) y `disco.json` (10 procesos de respaldo con 8 E/S a bloques al azar; RD1). Ambos se regeneran con `--guardar` desde los scripts de `informe/experimentos/`.

---

## 4. Declaración de uso de herramientas de IA e integridad académica

- **Integrante 1:** `procesos.py`, `kernel.py` y las suites de pruebas `test_prototipo1.py` y `test_prototipo2.py` se desarrollaron con asistencia de modelos de lenguaje (Gemini). El integrante las revisó, ejecutó y adaptó, y puede explicar cada línea.
- **Integrante 2:** `disco.py`, `memoria.py`, sus pruebas, los escenarios `memoria.json` y `disco.json` y los scripts de `informe/experimentos/` se desarrollaron con asistencia de Claude (Anthropic). El integrante los revisó, ejecutó y adaptó, y puede explicar cada línea.
- **Integrante 3:** `archivos.py`, los escenarios JSON, el experimento de asignación y sus pruebas se desarrollaron con asistencia de Claude (Anthropic). El integrante los revisó y ejecutó, y puede explicar cada línea.
- **Integrante 4:** `consola.py`, comandos de archivos y recursos, infraestructura de pruebas y validación de los Prototipos 1 y 2 se desarrollaron con asistencia de herramientas de IA. El integrante las revisó, ejecutó y adaptó, y puede explicar cada línea.

---

## 5. Bitácora del proyecto

> Registro cronológico de lo que hizo cada integrante, las decisiones tomadas y su evidencia (commits, pruebas, experimentos). Sirve de base para redactar el informe final de forma coherente con el proceso.

### Prototipo 1 (entrega: 17 de noviembre)
- **Integrante 2 — disco simple (PR #1):** `disco.py` con FCFS, tiempo de servicio `1 + distancia // 10` y avance por tick (`avanzar_tick`), sin importar `procesos` ni `kernel`. Pruebas unitarias (18) y prueba de contrato con un kernel simulado (6).
- **Integrante 3 — base de archivos y escenarios (PR #3):** `archivos.py` con usuarios, directorios, permisos tipo Unix y mapa de bloques propio. Cuatro escenarios con el formato del enunciado (`ejemplo_enunciado`, `base`, `inanicion` y `carga_cpu`) y pruebas que miden RP1, RP2 y RP3 solo con funciones del enunciado (24), más pruebas de archivos (23).

### Prototipo 2 (entrega: 23 de noviembre)

#### 22 de noviembre (1) — Integrante 2: primera implementación de memoria y disco (rama `feature/memoria-disco-completo`)
- **Análisis inicial:**
  - `memoria.py` tenía solo las 7 firmas, sin implementar.
  - `disco.py` seguía en FCFS y sin caché.
  - La instrucción `("MEM", dir)` la integra el Integrante 1 en `feature/nucleo-prototipo2`, que todavía no estaba fusionada a `main`.
  - Se decidió trabajar sobre `main` para que el PR contenga solo los archivos del Integrante 2, y que `memoria` funcione con o sin esa rama (registro automático leyendo `procesos`).
- **Primera versión de `memoria.py`:**
  - Paginación por demanda, `ErrorMemoria` validado antes de modificar el estado (RM3), `reiniciar`, `registrar_proceso`, liberación automática de los procesos TERMINADO e hiperpaginación por ventana.
  - Decisiones iniciales según el experimento:
    1. Se descartó quitarle marcos al proceso con más marcos (fallos en cadena: 41–48 %).
    2. Se agregó asignación proporcional.
    3. Se eligió LRU (menos fallos que el Reloj y FIFO en las 10 corridas).
- **Primera versión de `disco.py`:**
  - C-LOOK con límite de espera de 100 ticks, caché LRU de lectura con escritura directa y `estadisticas_espera()`.
  - El experimento de inanición mostró que SSTF puede no atender nunca una solicitud lejana: argumento para C-LOOK.
- **Escenarios y experimentos:** `tests/escenarios/memoria.json` y `disco.json`; `informe/experimentos/experimento_memoria.py` y `experimento_disco.py`, con 5 semillas.

#### 22 de noviembre (2) — Integrante 2: revisión contra el enunciado y la guía, y pruebas de robustez
- **Revisión contra la guía conceptual y el cuaderno de herramientas.** Se encontraron y corrigieron estas incoherencias:
  1. **Reemplazo local.** La asignación proporcional le quitaba páginas a otros procesos, lo que la guía (5.6, 5.8, 5.12) marca como error en una política local. Se pasó a reemplazo local estricto; la única excepción es un proceso sin ninguna página residente cuando no hay marcos libres. En el escenario nominal no cambia la tasa de fallos.
  2. **Política del Reloj.** La guía fija el plan del equipo: Reloj local, comparado contra FIFO y LRU. LRU fue 1,8 puntos mejor, pero ambos cumplen RM1 con margen; se adoptó el Reloj (coherencia con el plan, uso del bit `referenciada` y realismo) y LRU queda como alternativa evaluada.
  3. **Fragmentación interna.** Se contaba solo si la última página estaba en memoria; la guía (5.4, pregunta 15) la define sumada para todos los procesos. Corregido.
  4. **Herramientas del cuaderno.** La traducción usa `math.ceil` y `divmod`, como en la sección 6 del cuaderno.
  5. **Contrato del disco.** `_elegir_siguiente(cola, cabezal)` recuperó su firma de la guía (6.8), que es la que se modifica en vivo en la sustentación.
- **Prueba de carga del disco (experimento D) y decisión:** el límite de espera de 100 ticks colapsaba el disco con carga alta (con 0,75 solicitudes por tick la espera máxima pasó de 108 a 1880 ticks), porque al atender por antigüedad el disco vuelve a recorridos largos. **Se eliminó**: C-LOOK puro tiene la menor espera máxima hasta 0,8 solicitudes por tick y no deja solicitudes sin atender.
- **Pruebas que validan contra la guía:** secuencia clásica de 20 accesos (LRU 12, Reloj 14, FIFO 15 fallos), anomalía de Belady, ejemplo del Reloj paso a paso y ejemplo de disco con el cabezal en 53 (FCFS 640, SSTF 236, C-LOOK 322). Los resultados coinciden exactamente con la guía.
- **Pruebas de robustez (fuera del repositorio):**
  - 300 corridas aleatorias de 400 operaciones sobre `memoria`: después de cada operación se cumplen las invariantes (marcos libres + ocupados = totales, ningún marco repetido, nadie supera su cuota, un acceso inválido no cambia nada).
  - 100 corridas aleatorias de 600 ticks sobre `disco`, con cancelaciones y caché: todas las solicitudes terminan y la espera máxima fue de 71 ticks.
  - Cada archivo de pruebas pasa solo (`-W error`); los módulos usan solo la biblioteca estándar y no usan la hora real; los escenarios se regeneran idénticos byte a byte.

#### 22 de noviembre (3) — Integrante 2: revisión independiente y correcciones finales
- **Revisión independiente** (un revisor sin acceso a las conclusiones previas, contra el enunciado y la guía). Confirmó que la lógica central es correcta: 900 corridas aleatorias por módulo sin romper invariantes, los ejemplos de la guía reproducidos y las firmas y claves exactas. Encontró casos borde que se corrigieron, cada uno con su prueba de regresión:
  1. **PID reutilizado tras reiniciar el kernel.** Como el kernel de `main` aún no llama a `memoria.reiniciar`, el nuevo PID 1 heredaba el tamaño y los marcos del anterior (rompía RM3). Ahora cada registro recuerda de qué proceso salió y se registra de nuevo si cambió.
  2. **Inanición en C-LOOK con un flujo al mismo bloque del cabezal.** Se probó primero "estrictamente mayor que el cabezal", pero con varias solicitudes pendientes al mismo bloque atendía una por pasada y la espera máxima con carga 0,6 subió de 93 a 244 ticks. Se adoptó la regla correcta: en el bloque del cabezal se atienden las que ya existían al llegar, y las nuevas esperan a la siguiente pasada.
  3. **Proceso TERMINADO que accede a memoria directamente:** lanzaba `KeyError`. Ahora lanza `ErrorNoExiste` sin tocar las métricas.
  4. **`estado_memoria` no contaba los procesos que aún no accedían.** Ahora cuenta a todos los procesos vivos (fragmentación de todos, guía 5.4).
  5. **Validaciones menores:** `encolar_solicitud_disco` rechaza bloques `bool` y `reiniciar` valida la configuración del disco.
  6. **Experimentos más honestos:**
     - El experimento A arranca con el cabezal al azar (antes, con el cabezal en 0, inflaba el ahorro de C-LOOK).
     - El experimento B se detiene con error si un escenario no termina.
     - Los scripts siempre restauran la política elegida (`try`/`finally`).
- **Limitaciones agregadas al informe** a partir de la revisión: la carga de memoria tiene localidad diseñada; el escenario de memoria no tiene escrituras (el enunciado define `("MEM", dir)` sin ese dato); RD1 se cumple hasta unas 0,8 solicitudes por tick.
- **Resultados finales:**
  - RM1: 16,5 % de fallos con el kernel completo (Reloj); como máximo 20,3 % en las 5 semillas.
  - RD1: 55–62 % menos desplazamiento que FCFS y espera máxima de 50–64 ticks en el escenario de disco; con carga creciente, C-LOOK se mantiene por debajo de 200 ticks hasta 0,8 solicitudes por tick.
  - RM3: comprobado con procesos reales, también tras reiniciar el kernel.
- **Pruebas del repositorio:**
  - En `main`: pasan 189, se omite 1 (RM1 con el kernel, hasta que se fusione la rama del Integrante 1) y falla 1 ajena (`test_consola_comando_load`, por los espacios en la ruta).
  - Con `feature/nucleo-prototipo2` + estos módulos: pasan las 210, incluida RM1 de punta a punta.
  - Pruebas aleatorias: memoria 300 × 400 operaciones; disco 100 × 600 ticks con espera máxima de 75 ticks.
- **Pendientes de otros integrantes detectados (sin modificar su código):**
  - **Integrante 1:**
    - Fusionar `feature/nucleo-prototipo2`.
    - Llamar a `memoria.liberar_memoria` cuando un proceso termina solo. `memoria` ya lo cubre, pero conviene hacerlo explícito.
    - Capturar el `ErrorSistema` de `disco.encolar_solicitud_disco` ante un bloque inválido en `("ES", bloque)`.
    - Que `resumen_sistema()["bloques_libres"]` consulte `archivos.fs_estado_disco()`.
    - Acordar en qué tick vuelve a LISTO un proceso tras un fallo de página (pendiente de la guía 3.3).
  - **Integrante 3:** las funciones `fs_*` pendientes y la reserva y liberación de bloques (RF1).
  - **Integrante 4:** los comandos `free`, `df` y los de archivos; `load` falla con rutas que contienen espacios (`test_consola_comando_load`).

#### 22 de noviembre (4) — Integrante 3: archivos completo (rama `feature/archivos-prototipo2`)
- **Implementación:** `fs_escribir`, `fs_leer`, `fs_eliminar`, `fs_chmod` y `fs_enlace_simbolico`, con asignación indexada: cada archivo guarda su lista de bloques y toma los primeros libres del disco. `tam_bloque` sale de la configuración.
- **Decisiones:**
  - Borrar exige ser el dueño o `admin`, porque la raíz es `777` (como `/tmp` con el bit *sticky*).
  - El borrado recursivo revisa los permisos de todo lo de adentro antes de borrar, para no dejarlo a medias.
  - Sin espacio se lanza `ErrorSistema` sin cambiar nada.
  - Los enlaces se siguen, salvo en `fs_info` y `fs_eliminar`, con un límite de 40 saltos.
- **Experimento:** `informe/experimentos/experimento_asignacion.py` compara contigua, enlazada e indexada (sección 2.4). La contigua falla 17.6 veces habiendo espacio libre y mueve 410 bloques; la enlazada necesita 4.8 accesos para llegar a un bloque; la indexada, 1.
- **Pruebas:** `tests/test_archivos.py` pasa de 23 a 83 pruebas, incluida RF1: 12 operaciones sin permiso y 300 operaciones al azar en un disco que se llena.
- **Integración:** `kernel.resumen_sistema()["bloques_libres"]` ahora consulta `archivos.fs_estado_disco()`, el pendiente que había anotado el Integrante 2. Se hizo después de fusionar la rama del Integrante 1, que tocaba esa misma función. Con `main` actualizado pasan las 270 pruebas.

#### 22 de noviembre (5) — Integrante 4: comandos de archivos, recursos y pruebas de consola (rama `feature/consola-prototipo2`)
- **Implementación de comandos de archivos:**
  - `mkdir` y `md`: creación de directorios en el sistema de archivos virtual.
  - `touch`: creación de archivos vacíos o actualización sin alterar contenido existente.
  - `cat` y `type`: lectura e impresión del contenido de archivos de texto.
  - `echo` con redirección: soporte para `echo "texto" > archivo` (sobrescritura) y `echo "texto" >> archivo` (anexar), así como sintaxis con operadores contiguos (`>archivo` / `>>archivo`).
  - `ls` y `dir`: listado de entradas; soporte para `-l` mostrando modo octal, propietario, grupo, tamaño en bytes y nombre.
  - `rm` y `del`: borrado de archivos y enlaces; soporte de `-r` / `-R` para borrado recursivo de árboles de directorios.
  - `chmod`: modificación de permisos octales sobre archivos y directorios.
  - `ln -s` y `mklink`: creación de enlaces simbólicos resolviendo rutas de destino y enlace.
  - `tree`: visualización recursiva del árbol de directorios con conectores estándar (`├──`, `└──`, `│   `).
- **Implementación de comandos de recursos:**
  - `free`: consulta `memoria.estado_memoria()` y `memoria.metricas_memoria()` para presentar marcos totales, usados, libres, fragmentación interna, accesos, fallos de página (con porcentaje), reemplazos y escrituras a swap.
  - `df`: consulta `archivos.fs_estado_disco()` para reportar bloques totales, usados, libres, porcentaje de ocupación, grupos de huecos libres y política de asignación (`indexada`).
- **Resolución canónica de rutas (`_resolver_ruta`):**
  - Permite que todos los comandos de consola operen con rutas relativas, absolutas o con segmentos `.` y `..`, traduciéndolas a rutas canónicas absolutas que el módulo `archivos` exige.
  - `cd` valida existencia y permisos antes de cambiar el directorio de trabajo del usuario.
- **Robustez y pruebas:**
  - `load`: soporta rutas con espacios y comillas (solución al pendiente de la bitácora).
  - La suite `tests/test_consola.py` se amplía de 21 a 35 pruebas exhaustivas.
  - Con esta entrega, el total de pruebas del repositorio pasa a **282 pruebas automáticas**, todas pasando exitosamente.
