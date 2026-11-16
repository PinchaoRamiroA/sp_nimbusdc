# Informe de decisiones de diseño — NimbusDC (`minidc`)

> **Curso:** Sistemas Operativos 1 (IS734) — Universidad Tecnológica de Pereira  
> **Periodo:** Noviembre–diciembre de 2026  
> **Equipo:** Santiago Ardila - Ramiro Pinchao - Santiago Ramirez - Kenneth Rodriguez

---

## 1. Diagrama y descripción de la arquitectura

*(Incluir diagrama de arquitectura que muestre la interacción entre `kernel`, `procesos`, `memoria`, `disco`, `archivos`, `sincronizacion`, `consola` y `errores`.)*

---

## 2. Decisiones de diseño por subsistema

### 2.1 Gestión de CPU y procesos (`procesos.py`)
- **Algoritmo elegido:**
- **Alternativas evaluadas (mínimo 2):**
  1. 
  2. 
- **Experimento y métricas comparativas:**
- **Justificación frente a los requisitos (RP1–RP3):**
- **Limitaciones:**

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

*(Documentar las pruebas implementadas en `tests/`, escenarios probados y cómo verifican los requisitos RP1–RP3, RM1–RM3, RD1, RF1, RS1–RS2.)*

- `tests/test_disco.py` (18 pruebas): fórmula de servicio, orden FCFS, cancelar, reiniciar, validaciones y métricas.
- `tests/test_disco_kernel_simulado.py` (6 pruebas): con un kernel simulado, `("ES", 40)` bloquea al proceso 5 ticks.
- `tests/test_archivos.py` (23 pruebas): formateo, usuarios, directorios, permisos por propietario, grupo y otros, y conteo de bloques y huecos.
- `tests/test_escenarios.py` (24 pruebas): valida el formato de los escenarios y mide RP1, RP2 y RP3 sobre ellos usando solo funciones del enunciado. 4 están marcadas como fallo esperado hasta que `kernel.cargar_escenario` lea el formato del enunciado.
- Escenarios en `tests/escenarios/` (formato del enunciado): `ejemplo_enunciado.json` (el ejemplo del enunciado), `base.json` (mezcla de web, respaldo y analítica; RP1), `inanicion.json` (un servicio web cada 4 ticks frente a una analítica de baja prioridad; RP2) y `carga_cpu.json` (tres analíticas y cinco web; RP3). En los escenarios propios la prioridad 0 es la más alta, como en el planificador del equipo.

---

## 4. Declaración de uso de herramientas de IA e integridad académica

*(Declarar explícitamente si se utilizaron herramientas de IA durante el proyecto, en qué partes y confirmar que todo el equipo comprende y puede explicar cada línea del código.)*

- **Integrante 2:** `disco.py` y sus pruebas se desarrollaron con asistencia de Claude (Anthropic). El integrante las revisó, ejecutó y adaptó, y puede explicar cada línea.
- **Integrante 3:** `archivos.py`, los escenarios JSON y sus pruebas se desarrollaron con asistencia de Claude (Anthropic). El integrante los revisó y ejecutó, y puede explicar cada línea.
