"""Importação e grade de fotos (subprocesso offscreen): miniaturas, rostos em segundo plano, seleção, filtro."""

from __future__ import annotations

from conftest import rodar_python

PREAMBULO = """
import sys, shutil, time
from pathlib import Path
from tempfile import mkdtemp
from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv[:1])
from revelador.ui.main_window import MainWindow

def esperar(cond, ms=30000):
    fim = time.time() + ms / 1000
    while time.time() < fim:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False

def pasta_com(n, rosto=False):
    d = Path(mkdtemp(prefix="fotos_"))
    for i in range(n):
        Image.new("RGB", (400 + i, 300), (i * 20 % 255, 90, 150)).save(d / f"f{i:02d}.jpg")
    if rosto:
        shutil.copy(Path("tests/data/rosto_neil_armstrong.jpg"), d / "rosto.jpg")
    return d

def pronto(j):
    return esperar(lambda: not j.importacao.ocupado and j.importacao._total == 0)
"""


def rodar(corpo: str) -> None:
    p = rodar_python(PREAMBULO + corpo, timeout=120)
    assert p.returncode == 0, p.stderr
    assert p.stdout.strip().endswith("ok"), p.stdout


def test_importar_pasta_gera_itens_info_e_miniaturas():
    rodar("""
d = pasta_com(5)
j = MainWindow(); j.show()
assert j.orientacao_grade.isVisible()
j.importar([d])
assert j.grade.total() == 5 and not j.orientacao_grade.isVisible()
assert pronto(j)
e = j.estado
assert len(e.info) == 5 and len(e.miniaturas) == 5 and not e.erros
assert all(Path(m).is_file() for m in e.miniaturas.values())
assert all(f.rostos is not None for f in e.trabalho.fotos)
assert j.statusBar().currentMessage() == "Pronto."
print("ok")
""")


def test_arquivo_corrompido_fica_marcado_e_nao_derruba():
    rodar("""
d = pasta_com(2)
(d / "ruim.jpg").write_bytes(b"isto nao e uma imagem")
j = MainWindow(); j.show()
j.importar([d])
assert pronto(j)
e = j.estado
ruim = next(f for f in e.trabalho.fotos if f.caminho.name == "ruim.jpg")
assert e.erros.get(ruim.id) and len(e.erros) == 1 and len(e.miniaturas) == 2
assert e.erros[ruim.id] in j.grade.modelo.data(j.grade.modelo.indice_da_foto(ruim), Qt.ItemDataRole.ToolTipRole)
print("ok")
""")


def test_selecao_teclado_delete_e_duplicadas():
    rodar("""
d = pasta_com(4)
j = MainWindow(); j.resize(900, 600); j.show()
j.importar([d]); j.importar([d, d / "f00.jpg"])
assert j.grade.total() == 4
assert pronto(j)
e, g = j.estado, j.grade
g.lista.setCurrentIndex(g.modelo.index(1))
assert e.atual is e.trabalho.fotos[1]
g.lista.setFocus()
QTest.keyClick(g.lista, Qt.Key.Key_Space)
assert e.trabalho.fotos[1].selecionada and e.trabalho.fotos[1].impressoes
QTest.keyClick(g.lista, Qt.Key.Key_Right)
assert e.atual is e.trabalho.fotos[2]
# filtro
j.filtro_mostrar.botoes["selecionadas"].click()
assert g.total() == 1
j.filtro_mostrar.botoes["todas"].click()
assert g.total() == 4
# delete
alvo = e.trabalho.fotos[2]
QTest.keyClick(g.lista, Qt.Key.Key_Delete)
assert g.total() == 3 and alvo not in e.trabalho.fotos and alvo.caminho.is_file()
print("ok")
""")


def test_clique_na_marca_e_argumentos_iniciais():
    rodar("""
d = pasta_com(2)
j = MainWindow(); j.resize(900, 600)
j.arquivos_iniciais = [str(d)]
j.show()
assert esperar(lambda: j.grade.total() == 2)
assert pronto(j)
from revelador.ui.grade import rect_marca
g = j.grade
idx = g.modelo.index(0)
QTest.mouseClick(g.lista.viewport(), Qt.MouseButton.LeftButton, pos=rect_marca(g.lista.visualRect(idx)).center())
assert j.estado.trabalho.fotos[0].selecionada
print("ok")
""")


def test_rostos_chegam_para_foto_de_rosto():
    rodar("""
d = pasta_com(0, rosto=True)
j = MainWindow(); j.show()
j.importar([d])
assert pronto(j)
f = j.estado.trabalho.fotos[0]
assert f.rostos and len(f.rostos) >= 1
print("ok")
""")


def test_foto_removida_durante_importacao_e_ignorada():
    rodar("""
d = pasta_com(6, rosto=True)
j = MainWindow(); j.show()
j.importar([d])
j.estado.remover(list(j.estado.trabalho.fotos))
assert pronto(j)
assert not j.estado.info and not j.estado.miniaturas and j.grade.total() == 0
print("ok")
""")
