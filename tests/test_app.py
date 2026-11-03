"""O app: janela principal abre, ``--diagnostico`` segue funcionando. Qt só em subprocesso offscreen."""

from __future__ import annotations

import json

from conftest import rodar_python

CODIGO = """
import sys
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv[:1])
from revelador import __version__
from revelador.app import pasta_assets
from revelador.ui.main_window import MainWindow, aplicar_tema
aplicar_tema(app)
janela = MainWindow()
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


def test_diagnostico_nao_abre_janela(tmp_path):
    destino = tmp_path / "d.json"
    p = rodar_python(f"import sys; from revelador.app import main; sys.exit(main(['--diagnostico', r'{destino}']))")
    assert p.returncode == 0, p.stderr
    assert json.loads(destino.read_text(encoding="utf-8"))["ok"] is True
