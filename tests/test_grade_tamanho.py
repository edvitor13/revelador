"""Tamanho das miniaturas da grade (subprocesso offscreen): muda as células, é lembrado, duas colunas ao abrir."""

from __future__ import annotations

from conftest import rodar_python

PREAMBULO = """
import sys
from PySide6.QtCore import Qt, QPoint, QPointF, QRect
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv[:1])
from revelador.ui import prefs
from revelador.ui.grade import (celula, largura_duas_colunas, rect_marca, tamanho_miniatura_salvo,
                                MINIATURA_PADRAO)
from revelador.ui.main_window import MainWindow

def limpar_prefs():
    s = prefs.settings()
    for chave in ("grade/miniatura", "janela/geometria", "janela/divisores"):
        s.remove(chave)
    s.sync()

def com_fotos(j, n=3):
    # a grade só aparece com fotos (sem elas, a orientação de "arraste fotos" ocupa a área)
    from pathlib import Path
    from tempfile import mkdtemp
    from PIL import Image
    d = Path(mkdtemp())
    for i in range(n):
        Image.new("RGB", (300, 200), (90, 120, 150 + i)).save(d / f"f{i}.jpg")
    j.importar([d])
    app.processEvents()
"""


def rodar(corpo: str) -> None:
    p = rodar_python(PREAMBULO + corpo, timeout=120)
    assert p.returncode == 0, p.stderr
    assert p.stdout.strip().endswith("ok"), p.stdout


def test_tamanho_muda_celulas_e_e_lembrado():
    rodar("""
limpar_prefs()
j = MainWindow(); j.show(); app.processEvents()
g = j.grade
assert g.lado == MINIATURA_PADRAO == 150
assert g.lista.gridSize() == celula(150)
g.definir_miniatura(200)
assert g.lado == 200 and g.lista.gridSize() == celula(200)
assert g.delegado.lado == 200 and g.controle.valor() == 200
assert tamanho_miniatura_salvo() == 200
# limites: abaixo de 80 e acima de 320 não passam
g.definir_miniatura(10); assert g.lado == 80
g.definir_miniatura(1000); assert g.lado == 320
g.definir_miniatura(200)
# o controle deslizante também muda o tamanho
g.controle.definir_valor(120, emitir=True); assert g.lado == 120
j.close()
k = MainWindow(); k.show(); app.processEvents()
assert k.grade.lado == 120, k.grade.lado
print("ok")
""")


def test_duas_colunas_no_tamanho_inicial_e_nos_extremos():
    rodar("""
limpar_prefs()
j = MainWindow(); j.show(); app.processEvents()
com_fotos(j)
g = j.grade
assert g.isVisible()
for lado in (80, 150, 320):
    g.definir_miniatura(lado)
    app.processEvents()
    assert g.lista.viewport().width() >= 2 * celula(lado).width(), (lado, g.lista.viewport().width())
    # de fato duas colunas: a segunda foto começa à direita da primeira
    assert g.lista.visualRect(g.modelo.index(1)).left() > g.lista.visualRect(g.modelo.index(0)).left(), lado
    assert j.area_grade.minimumWidth() == largura_duas_colunas(lado)
    assert j.area_grade.width() >= largura_duas_colunas(lado), (lado, j.area_grade.width())
print("ok")
""")


def test_largura_antiga_salva_e_corrigida_ao_abrir():
    rodar("""
limpar_prefs()
j = MainWindow(); j.show(); app.processEvents()
j.divisor.setSizes([260, 700, 320]); app.processEvents()
j.close()
k = MainWindow(); k.show(); app.processEvents()
com_fotos(k)
minimo = largura_duas_colunas(150)
assert k.divisor.sizes()[0] >= minimo, k.divisor.sizes()
assert k.area_grade.width() >= minimo and k.grade.lista.viewport().width() >= 2 * celula(150).width()
print("ok")
""")


def test_ctrl_roda_muda_tamanho_e_roda_sem_ctrl_nao():
    rodar("""
limpar_prefs()
j = MainWindow(); j.show(); app.processEvents()
g = j.grade
def roda(dy, mod):
    ev = QWheelEvent(QPointF(10, 10), QPointF(10, 10), QPoint(0, 0), QPoint(0, dy), Qt.MouseButton.NoButton,
                     mod, Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(g.lista.viewport(), ev)   # o mouse chega no viewport, que repassa à lista
roda(120, Qt.KeyboardModifier.ControlModifier)
assert g.lado == 160, g.lado
roda(-120, Qt.KeyboardModifier.ControlModifier)
assert g.lado == 150, g.lado
roda(120, Qt.KeyboardModifier.NoModifier)
assert g.lado == 150
print("ok")
""")


def test_miniaturas_pequenas_e_marca_encolhe():
    rodar("""
limpar_prefs()
from pathlib import Path
from tempfile import mkdtemp
from PIL import Image
d = Path(mkdtemp())
for i in range(3):
    Image.new("RGB", (300, 200), (90, 120, 150)).save(d / f"f{i}.jpg")
j = MainWindow(); j.resize(900, 600); j.show(); app.processEvents()
j.importar([d])
import time
fim = time.time() + 30
while time.time() < fim and (j.importacao.ocupado or j.importacao._total):
    app.processEvents(); time.sleep(0.01)
g = j.grade
j.estado.selecionar(g.modelo.foto(0), True)   # uma impressão, para os chips
app.processEvents()
g.definir_miniatura(80)
app.processEvents()
g.grab()   # miniaturas pequenas: sem nome, chip compacto com a contagem
assert rect_marca(QRect(0, 0, celula(80).width(), celula(80).height())).width() == 14
assert rect_marca(QRect(0, 0, celula(150).width(), celula(150).height())).width() == 24
g.definir_miniatura(320)
app.processEvents()
g.grab()
assert g.modelo.foto(0).impressoes
print("ok")
""")
