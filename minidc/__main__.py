"""Punto de entrada de línea de comandos para NimbusDC: `python -m minidc`."""
import sys

from minidc.consola import iniciar_consola_interactiva

if __name__ == "__main__":
    escenario_arg = sys.argv[1] if len(sys.argv) > 1 else None
    iniciar_consola_interactiva(escenario_arg)
