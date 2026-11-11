"""Pruebas estructurales iniciales para validar módulos, excepciones y firmas de ``minidc``."""

import inspect
import unittest


class TestEstructuraPaquete(unittest.TestCase):
    """Verifica la estructura obligatoria del paquete ``minidc``."""

    def test_importaciones_obligatorias(self) -> None:
        from minidc import (  # noqa: F401
            archivos,
            consola,
            disco,
            errores,
            kernel,
            memoria,
            procesos,
            sincronizacion,
        )

    def test_jerarquia_excepciones(self) -> None:
        from minidc.errores import (
            ErrorMemoria,
            ErrorNoExiste,
            ErrorPermiso,
            ErrorSincronizacion,
            ErrorSistema,
            ErrorYaExiste,
        )

        self.assertTrue(issubclass(ErrorSistema, Exception))
        for exc in (
            ErrorPermiso,
            ErrorNoExiste,
            ErrorYaExiste,
            ErrorMemoria,
            ErrorSincronizacion,
        ):
            self.assertTrue(
                issubclass(exc, ErrorSistema),
                f"{exc.__name__} debe heredar de ErrorSistema",
            )


class TestFirmasObligatorias(unittest.TestCase):
    """Verifica que las funciones obligatorias coincidan en nombre, parámetros y valores por defecto."""

    def _verificar_firma(
        self,
        modulo,
        nombre_fn: str,
        params_esperados: list[tuple[str, object]],
    ) -> None:
        self.assertTrue(
            hasattr(modulo, nombre_fn),
            f"Falta la función {modulo.__name__}.{nombre_fn}",
        )
        fn = getattr(modulo, nombre_fn)
        self.assertTrue(callable(fn), f"{nombre_fn} debe ser invocable")
        sig = inspect.signature(fn)
        params_reales = [
            (
                p.name,
                inspect._empty if p.default is inspect.Parameter.empty else p.default,
            )
            for p in sig.parameters.values()
        ]
        self.assertEqual(
            params_reales,
            params_esperados,
            f"Firma inesperada en {modulo.__name__}.{nombre_fn}",
        )

    def test_firmas_kernel(self) -> None:
        from minidc import kernel

        vacío = inspect._empty
        esperadas = {
            "iniciar_sistema": [("config", vacío)],
            "apagar_sistema": [],
            "tick": [],
            "ejecutar_ticks": [("n", vacío)],
            "reloj_actual": [],
            "cargar_escenario": [("ruta_json", vacío)],
            "resumen_sistema": [],
        }
        for nombre, params in esperadas.items():
            self._verificar_firma(kernel, nombre, params)

    def test_firmas_procesos(self) -> None:
        from minidc import procesos

        vacío = inspect._empty
        esperadas = {
            "crear_proceso": [
                ("nombre", vacío),
                ("usuario", vacío),
                ("programa", vacío),
                ("memoria_bytes", 4096),
                ("cuota_marcos", 4),
                ("prioridad", 0),
            ],
            "crear_hilo": [("pid", vacío), ("programa", vacío)],
            "terminar_proceso": [("pid", vacío)],
            "estado_proceso": [("pid", vacío)],
            "listar_procesos": [],
            "cola_listos": [],
            "proceso_en_ejecucion": [("cpu", 0)],
            "metricas_planificacion": [],
            "politica_planificacion": [],
        }
        for nombre, params in esperadas.items():
            self._verificar_firma(procesos, nombre, params)

    def test_firmas_memoria(self) -> None:
        from minidc import memoria

        vacío = inspect._empty
        esperadas = {
            "acceder_memoria": [
                ("pid", vacío),
                ("direccion_virtual", vacío),
                ("escritura", False),
            ],
            "tabla_paginas": [("pid", vacío)],
            "liberar_memoria": [("pid", vacío)],
            "estado_memoria": [],
            "metricas_memoria": [],
            "detectar_hiperpaginacion": [],
            "politica_reemplazo": [],
        }
        for nombre, params in esperadas.items():
            self._verificar_firma(memoria, nombre, params)

    def test_firmas_disco(self) -> None:
        from minidc import disco

        vacío = inspect._empty
        esperadas = {
            "encolar_solicitud_disco": [
                ("pid", vacío),
                ("bloque", vacío),
                ("operacion", vacío),
            ],
            "procesar_disco": [],
            "cola_disco": [],
            "metricas_disco": [],
            "info_cache": [],
            "politica_disco": [],
        }
        for nombre, params in esperadas.items():
            self._verificar_firma(disco, nombre, params)

    def test_firmas_archivos(self) -> None:
        from minidc import archivos

        vacío = inspect._empty
        esperadas = {
            "formatear_disco": [],
            "crear_usuario": [("nombre", vacío), ("grupo", "usuarios")],
            "fs_mkdir": [("ruta", vacío), ("usuario", vacío)],
            "fs_escribir": [
                ("ruta", vacío),
                ("contenido", vacío),
                ("usuario", vacío),
                ("agregar", False),
            ],
            "fs_leer": [("ruta", vacío), ("usuario", vacío)],
            "fs_listar": [("ruta", vacío), ("usuario", vacío)],
            "fs_eliminar": [
                ("ruta", vacío),
                ("usuario", vacío),
                ("recursivo", False),
            ],
            "fs_chmod": [("ruta", vacío), ("modo", vacío), ("usuario", vacío)],
            "fs_enlace_simbolico": [
                ("destino", vacío),
                ("ruta_enlace", vacío),
                ("usuario", vacío),
            ],
            "fs_info": [("ruta", vacío)],
            "fs_estado_disco": [],
            "politica_asignacion_archivos": [],
        }
        for nombre, params in esperadas.items():
            self._verificar_firma(archivos, nombre, params)

    def test_firmas_sincronizacion(self) -> None:
        from minidc import sincronizacion

        vacío = inspect._empty
        esperadas = {
            "crear_semaforo": [("nombre", vacío), ("valor_inicial", vacío)],
            "semaforo_wait": [("nombre", vacío), ("pid", vacío)],
            "semaforo_signal": [("nombre", vacío), ("pid", vacío)],
            "estado_semaforo": [("nombre", vacío)],
            "crear_mutex": [("nombre", vacío)],
            "mutex_lock": [("nombre", vacío), ("pid", vacío)],
            "mutex_unlock": [("nombre", vacío), ("pid", vacío)],
            "detectar_interbloqueo": [],
            "resolver_interbloqueo": [],
            "demo_condicion_carrera": [
                ("usar_sincronizacion", vacío),
                ("num_hilos", vacío),
                ("iteraciones", vacío),
            ],
        }
        for nombre, params in esperadas.items():
            self._verificar_firma(sincronizacion, nombre, params)

    def test_firmas_consola(self) -> None:
        from minidc import consola

        vacío = inspect._empty
        esperadas = {
            "ejecutar_comando": [("linea", vacío), ("usuario", "admin")],
            "directorio_actual": [("usuario", "admin")],
            "historial": [("usuario", "admin")],
        }
        for nombre, params in esperadas.items():
            self._verificar_firma(consola, nombre, params)


if __name__ == "__main__":
    unittest.main()
