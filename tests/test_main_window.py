"""Janela principal (subprocesso offscreen): áreas, ações, geometria salva e restaurada, "Sobre"."""

from __future__ import annotations

from conftest import rodar_python

PREAMBULO = """
import sys
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv[:1])
from revelador.ui.main_window import MainWindow
"""


def rodar(corpo: str) -> None:
    p = rodar_python(PREAMBULO + corpo)
    assert p.returncode == 0, p.stderr
    assert p.stdout.strip().endswith("ok"), p.stdout


def test_tres_areas_e_acoes():
    rodar("""
j = MainWindow()
j.show(); app.processEvents()
assert j.divisor.count() == 3
assert [j.divisor.widget(i) for i in range(3)] == [j.area_grade, j.area_editor, j.area_painel]
for area in (j.area_grade, j.area_editor, j.area_painel):
    assert area.layout() is not None
assert "Arraste fotos ou pastas" in j.orientacao_grade.text()
assert j.acao_importar.text() == "Importar…" and j.acao_importar.isEnabled()
assert j.acao_exportar.text() == "Exportar para revelação…" and not j.acao_exportar.isEnabled()
assert j.espaco_tamanho is not None and j.statusBar() is not None
assert [m.title() for m in (j.menu_arquivo, j.menu_ajuda)] == ["&Arquivo", "A&juda"]
assert j.arquivos_iniciais == []
print("ok")
""")


def test_sobre_menciona_licenca_modelo_e_privacidade():
    rodar("""
t = MainWindow().texto_sobre()
for parte in ("MIT", "YuNet", "OpenCV Zoo", "nenhuma foto sai do seu computador"):
    assert parte in t, parte
print("ok")
""")


def test_geometria_salva_e_restaurada_pelo_ini():
    rodar("""
import os
from pathlib import Path
j = MainWindow()
j.show(); app.processEvents()
j.resize(700, 500)
j.divisor.setSizes([150, 300, 200]); app.processEvents()
tamanho, divisores = j.size(), j.divisor.sizes()
j.close()
ini = Path(os.environ["REVELADOR_SETTINGS_DIR"]) / "Revelador.ini"
assert ini.is_file() and "geometria" in ini.read_text(encoding="utf-8", errors="replace")
k = MainWindow()
k.show(); app.processEvents()
assert k.size() == tamanho, (k.size(), tamanho)
assert k.divisor.sizes() == divisores, (k.divisor.sizes(), divisores)
print("ok")
""")
