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
- **Algoritmo elegido:**
- **Alternativas evaluadas (mínimo 2):**
  1. 
  2. 
- **Experimento y métricas comparativas:**
- **Justificación frente a los requisitos (RM1–RM3):**
- **Limitaciones:**

### 2.3 Planificación de disco y caché (`disco.py`)
> Estado: Prototipo 1. Se actualiza en el Prototipo 2.
- **Algoritmo elegido:** FCFS (provisional, línea base). Objetivo para el Prototipo 2: C-LOOK, según el experimento.
- **Decisiones del Prototipo 1:** el tiempo de servicio es `1 + abs(cabezal - bloque) // 10`. `disco` no importa `procesos` ni `kernel`: el kernel llama a `avanzar_tick()` y recibe los PID cuya E/S terminó. Funciones adicionales: `reiniciar`, `avanzar_tick` y `cancelar_solicitudes`. Un bloque u operación inválidos lanzan `ErrorSistema` *(por confirmar)*.
- **Alternativas evaluadas (mínimo 2):**
  1. SSTF *(por evaluar)*
  2. C-LOOK *(por evaluar)*
- **Experimento y métricas comparativas:** *(pendiente, Prototipo 2)* misma carga con semilla fija para cada política; métricas: `desplazamiento_total` y espera máxima.
- **Justificación frente a los requisitos (RD1):** *(pendiente)* FCFS es la línea base de RD1. En el Prototipo 1 no pierde ticks entre solicitudes, lo que protege RP3.
- **Limitaciones:** FCFS no reduce el desplazamiento; la caché aún no está implementada; `procesar_disco()` no libera procesos.

### 2.4 Asignación de bloques de archivos (`archivos.py`)
> Estado: Prototipo 1 (avance). Se completa en el Prototipo 2.
- **Algoritmo elegido:** asignación indexada (prevista). En el Prototipo 1 todavía no se reservan bloques: eso llega con `fs_escribir` en el Prototipo 2.
- **Decisiones del Prototipo 1:** el árbol de archivos son diccionarios anidados y cada directorio guarda a sus hijos por nombre. `archivos` no importa `kernel`, `procesos` ni `disco`, y lleva su propio mapa de bloques (una lista de ocupado/libre). Los permisos son los de Unix (propietario, grupo y otros) y `admin` los ignora. `formatear_disco` borra también los usuarios, salvo `admin`. La raíz se crea con modo `777`, porque el enunciado no tiene una función para cambiar el propietario *(por confirmar)*. En `fs_info`, `bloques` es la lista de bloques del archivo, y en `fs_estado_disco`, `huecos_libres` es la cantidad de grupos de bloques libres seguidos *(por confirmar)*. Función adicional: `reiniciar(config)`, que `kernel.iniciar_sistema` debe llamar *(pendiente de conectar en el kernel)*.
- **Alternativas evaluadas (mínimo 2):**
  1. Asignación contigua *(por evaluar)*
  2. Asignación enlazada *(por evaluar)*
- **Experimento y métricas comparativas:** *(pendiente, Prototipo 2)* misma secuencia de creación, crecimiento y borrado de archivos con semilla fija para cada política; métricas: `huecos_libres` y escrituras que fallan por falta de espacio.
- **Justificación frente a los requisitos (RF1):** *(pendiente)* En el Prototipo 1 ya se cumple para directorios: sin permiso se lanza `ErrorPermiso`, y bloques usados más bloques libres es igual a bloques totales porque ambos se cuentan sobre el mismo mapa.
- **Limitaciones:** faltan `fs_escribir`, `fs_leer`, `fs_eliminar`, `fs_chmod` y `fs_enlace_simbolico`; solo acepta rutas absolutas y no interpreta `.` ni `..`; los directorios no ocupan bloques.

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

- `tests/test_disco.py` (18 pruebas): fórmula de servicio, orden FCFS, cancelar, reiniciar, validaciones y métricas.
- `tests/test_disco_kernel_simulado.py` (6 pruebas): con un kernel simulado, `("ES", 40)` bloquea al proceso 5 ticks.
- `tests/test_archivos.py` (23 pruebas): formateo, usuarios, directorios, permisos por propietario, grupo y otros, y conteo de bloques y huecos.
- `tests/test_escenarios.py` (24 pruebas): valida el formato de los escenarios y mide RP1, RP2 y RP3 sobre ellos usando solo funciones del enunciado. Todas pasando tras la integración del catálogo y usuarios en `kernel.cargar_escenario`.
- `tests/test_prototipo1.py` (17 pruebas): pruebas unitarias y de integración para `kernel.py` y `procesos.py`, verificando el ciclo de 4 pasos, el planificador MLFQ con aging, preempción y el cumplimiento formal de RP1, RP2 y RP3.
- `tests/test_prototipo2.py` (19 pruebas): pruebas unitarias y de integración para `kernel.py` y `procesos.py` en el Prototipo 2. Valida la asignación incremental de TIDs independientes por proceso, despacho concurrente desacoplado de hilos, el bloqueo exacto y determinista de 5 ticks ante fallo de página en la instrucción `("MEM", dir)`, el cumplimiento del requisito RM3 (proceso infractor termina limpiamente ante `ErrorMemoria` sin afectar a procesos concurrentes) e integración multiprocesador (`num_cpus=2`).
- `tests/test_consola.py` (21 pruebas): pruebas para `consola.py`, verificando comandos `ps`, `kill`, `run` (usando el catálogo del escenario), `tick`, `top`, `whoami`, `pwd`, `cd`, el aislamiento de `historial` y `directorio_actual` por usuario, las variantes de Windows (`tasklist`, `taskkill`) y el formato obligatorio de errores (`Error:...`).
- `tests/test_estructura.py` (9 pruebas): verificación de importaciones públicas, jerarquía de excepciones en `errores.py` y coincidencia exacta de firmas obligatorias.
- Escenarios en `tests/escenarios/` (formato del enunciado): `ejemplo_enunciado.json` (el ejemplo del enunciado), `base.json` (mezcla de web, respaldo y analítica; RP1), `inanicion.json` (un servicio web cada 4 ticks frente a una analítica de baja prioridad; RP2) y `carga_cpu.json` (tres analíticas y cinco web; RP3). En los escenarios propios la prioridad 0 es la más alta, como en el planificador del equipo.

---

## 4. Declaración de uso de herramientas de IA e integridad académica

- **Integrante 1:** `procesos.py`, `kernel.py` y las suites de pruebas `test_prototipo1.py` y `test_prototipo2.py` se desarrollaron con asistencia de modelos de lenguaje (Gemini). El integrante las revisó, ejecutó y adaptó, y puede explicar cada línea.
- **Integrante 2:** `disco.py` y sus pruebas se desarrollaron con asistencia de Claude (Anthropic). El integrante las revisó, ejecutó y adaptó, y puede explicar cada línea.
- **Integrante 3:** `archivos.py`, los escenarios JSON y sus pruebas se desarrollaron con asistencia de Claude (Anthropic). El integrante los revisó y ejecutó, y puede explicar cada línea.
- **Integrante 4:** `consola.py`, infraestructura de pruebas y validación del Prototipo 1 se desarrollaron con asistencia de herramientas de IA. El integrante las revisó, ejecutó y adaptó, y puede explicar cada línea.
