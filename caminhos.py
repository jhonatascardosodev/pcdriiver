"""Caminhos de dados e comando de relançamento, válidos rodando do código ou como .exe."""
import os
import sys

EMPACOTADO = bool(getattr(sys, "frozen", False))

# Dados ficam ao lado do .exe (ou do código). No modo onefile, __file__ aponta para uma
# pasta temporária apagada ao sair, por isso não serve para guardar nada.
PASTA = os.path.dirname(sys.executable) if EMPACOTADO else os.path.dirname(os.path.abspath(__file__))


def dado(nome):
    return os.path.join(PASTA, nome)


def comando_app(*extra):
    """(executável, argumentos) para abrir este programa de novo."""
    if EMPACOTADO:
        return sys.executable, list(extra)
    py = sys.executable
    pyw = os.path.join(os.path.dirname(py), "pythonw.exe")
    return (pyw if os.path.exists(pyw) else py), [os.path.join(PASTA, "app.py"), *extra]
