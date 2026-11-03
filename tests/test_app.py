"""A janela abre (provisória até a #1). Widgets do Qt só num subprocesso offscreen com QApplication própria."""

from __future__ import annotations

from conftest import rodar_python

CODIGO = """
import sys
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv[:1])
from revelador import __version__
from revelador.app import criar_janela, pasta_assets
janela = criar_janela()
janela.show()
app.processEvents()
assert janela.windowTitle() == f"Revelador {__version__}", janela.windowTitle()
assert (pasta_assets() / "logo-256.png").is_file()
assert (pasta_assets() / "logo.ico").is_file()
print("ok")
app.exit(0)
"""


def test_janela_abre_offscreen():
    p = rodar_python(CODIGO)
    assert p.returncode == 0, p.stderr
    assert p.stdout.strip().endswith("ok"), p.stdout
