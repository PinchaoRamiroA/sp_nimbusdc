# NimbusDC (`minidc`) — Mini centro de datos con sistema operativo propio

Proyecto final de **Sistemas Operativos 1 (IS734)** · Universidad Tecnológica de Pereira · Noviembre–diciembre de 2026.

## Descripción

**NimbusDC** simula un servidor único de centro de datos que atiende concurrentemente cargas heterogéneas mediante un sistema operativo simulado en Python (`minidc`) y una consola administrativa de comandos.

### Cargas de trabajo y usuarios

| Tipo de servicio | Comportamiento principal |
| --- | --- |
| `web` | Muchas ráfagas cortas de CPU y E/S frecuente; requiere baja latencia de respuesta |
| `analítica` | Ráfagas largas de CPU, poca E/S y alto consumo de memoria |
| `respaldo` | E/S intensiva sobre el disco |
| `base de datos` | Recurso compartido con lecturas y escrituras concurrentes |

Usuarios base del sistema: `admin` (administrador, ignora restricciones de permisos), `cliente_a` y `cliente_b`.

---

## Estructura del proyecto

```text
so_nimbusdc/
├── minidc/
│   ├── __init__.py         # Expone los módulos públicos del paquete
│   ├── errores.py          # Jerarquía de excepciones (ErrorSistema y derivadas)
│   ├── kernel.py           # Reloj discreto, inicialización, escenarios y resumen
│   ├── procesos.py         # Gestión de procesos, hilos y planificación de CPU
│   ├── memoria.py          # Memoria virtual paginada, reemplazo e hiperpaginación
│   ├── disco.py            # Cola de E/S de disco, planificación de cabezal y caché
│   ├── archivos.py         # Sistema de archivos virtual, bloques y permisos Unix
│   ├── sincronizacion.py   # Semáforos, mutex, interbloqueos y demo de carrera
│   └── consola.py          # Intérprete de comandos de administración
├── tests/
│   └── test_estructura.py  # Pruebas iniciales de importaciones, errores y firmas
├── informe/
│   └── informe_diseno.md   # Plantilla del informe de decisiones de diseño
├── .gitignore
├── requirements.txt
└── README.md
```

---

## Requisitos del entorno

- **Python 3.11 o superior** (implementación basada únicamente en la biblioteca estándar).
- **`rich`** *(opcional)*: permitido únicamente para presentación visual en pantalla.
- **`pytest`**: requerido para ejecutar la suite de pruebas automáticas.

### Configuración recomendada

```bash
# Crear y activar entorno virtual (Windows PowerShell)
python -m venv .venv
.venv\Scripts\Activate.ps1

# Instalar dependencias de pruebas
pip install -r requirements.txt
```

En Linux/macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

## Consola interactiva (tiempo real)

Puedes iniciar la consola interactiva en vivo de NimbusDC para ejecutar comandos y monitorear la simulación en tiempo real:

```bash
# Iniciar la consola interactiva
python main.py
# o mediante el módulo
python -m minidc

# Iniciar cargando un escenario directamente
python main.py tests/escenarios/base.json
```

Dentro de la consola puedes escribir `help` para ver la lista de comandos disponibles (`ps`, `run`, `tick`, `top`, `kill`, `load`, etc.) o `salir` para cerrar la sesión.

---

## Ejecución de pruebas

Para ejecutar toda la suite de pruebas desde la raíz del repositorio:

```bash
python -m pytest
```

Para ver salida detallada por prueba:

```bash
python -m pytest -v
```

> **Nota inicial:** Si aún no has instalado `pytest`, puedes validar las pruebas estructurales iniciales con la biblioteca estándar usando:
>
> ```bash
> python -m unittest discover -s tests -v
> ```

---

## Reglas clave de diseño y simulación

- **Tiempo discreto:** el único reloj de la simulación es `kernel.tick()`. No se utiliza tiempo real para tomar decisiones (salvo `time.sleep(0)` en `demo_condicion_carrera`).
- **Procesos simulados:** se modelan con estructuras de datos propias; `threading` se utiliza únicamente en `sincronizacion.demo_condicion_carrera`.
- **Implementación propia:** toda la lógica de planificación, paginación, disco, sistema de archivos y sincronización debe ser desarrollada por el equipo usando solo la biblioteca estándar de Python.
- **Manejo de errores:** las funciones del núcleo lanzan excepciones heredadas de `ErrorSistema` (`ErrorPermiso`, `ErrorNoExiste`, `ErrorYaExiste`, `ErrorMemoria`, `ErrorSincronizacion`); `consola.py` captura los errores y devuelve texto que inicia por `Error:`.

---

## Hoja de ruta de prototipos

| Prototipo | Fecha límite | Alcance principal | Requisitos |
| --- | --- | --- | --- |
| **Prototipo 1** | Mar 17 nov | `kernel` y `procesos` (sin `crear_hilo` obligatorio); consola: `ps`, `run`, `kill`, `tick`, `top` | RP1 a RP3 |
| **Prototipo 2** | Lun 23 nov | `memoria`, `disco` y `archivos` completos; consola: comandos de archivos, `free`, `df`; `crear_hilo` | RM1, RM3, RD1, RF1 |
| **Prototipo 3** | Lun 30 nov | `sincronizacion` completo, instrucciones `WAIT`/`SIGNAL`, integración total y consola completa | RM2, RS1, RS2 y anteriores |
| **Entrega final** | Jue 3 dic | Sustentación, repositorio final e `informe/informe_diseno.md` | Todos |

---

## Equipo

- Santiago Ardila — Integrante 1 (Núcleo y Procesos)
- Ramiro Pinchao — Integrante 2 (Memoria y Disco)
- Santiago Ramirez — Integrante 3 (Sistema de Archivos y Escenarios)
- Kenneth Rodriguez — Integrante 4 (Consola, Infraestructura y Pruebas)