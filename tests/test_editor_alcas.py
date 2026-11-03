"""Alças nos cantos da moldura, ←/→ entre as fotos no editor e soltar um ``.revelador`` na janela (#6, #9).

Tudo em subprocesso *offscreen*, com imagens geradas no código.
"""

from __future__ import annotations

from conftest import rodar_python

PREAMBULO = """
import math, os, sys, tempfile, time
from pathlib import Path
import numpy as np
from PIL import Image
from PySide6.QtCore import QEvent, QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDropEvent, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv[:1])
from revelador import imagem, projeto, receita
from revelador.projeto import Foto, Impressao, Recorte, Trabalho
from revelador.ui.editor import Editor, ZOOM_MAXIMO
from revelador.ui.estado import Estado

PASTA = Path(tempfile.mkdtemp(prefix="revelador_alcas_"))


def esperar(condicao, timeout=20.0):
    fim = time.monotonic() + timeout
    while not condicao():
        app.processEvents()
        assert time.monotonic() < fim, "tempo esgotado"
        time.sleep(0.01)
    app.processEvents()


def gerar_foto(nome="a.png", largura=800, altura=600, cor=120):
    y, x = np.mgrid[0:altura, 0:largura]
    a = np.stack([x * 255 // largura, y * 255 // altura, np.full_like(x, cor)], axis=-1).astype(np.uint8)
    caminho = PASTA / nome
    Image.fromarray(a).save(caminho)
    return caminho


def montar(**kw_imp):
    estado = Estado()
    caminho = gerar_foto()
    foto = Foto(id="f1", caminho=caminho, selecionada=True)
    estado.trabalho = Trabalho(fotos=[foto])
    estado.definir_info("f1", imagem.abrir_info(caminho))
    foto.rostos = []
    foto.impressoes.append(Impressao(tamanho="10x15", **kw_imp))
    estado.refazer_recortes_auto(foto)
    editor = Editor(estado)
    editor.resize(900, 650)
    editor.show()
    estado.definir_atual(foto)
    esperar(lambda: editor.proxy is not None)
    return estado, foto, editor


def dentro(editor, imp):
    W, H = receita.dimensoes_giradas(imp, *editor._dims())
    ret = receita.retangulo_da_impressao(imp, *editor._dims())
    assert abs(ret.w / ret.h - receita.proporcao(imp, *editor._dims())) < 1e-9
    for x, y in receita.poligono(ret):
        assert -1e-6 <= x <= W + 1e-6 and -1e-6 <= y <= H + 1e-6, (x, y, W, H)
    assert 1.0 <= imp.recorte.zoom <= ZOOM_MAXIMO
    return ret


def cantos(editor, imp):
    return receita.poligono(receita.retangulo_da_impressao(imp, *editor._dims()))


def mouse(widget, tipo, pos, botoes=Qt.MouseButton.LeftButton):
    botao = Qt.MouseButton.NoButton if tipo == QEvent.Type.MouseMove else Qt.MouseButton.LeftButton
    ev = QMouseEvent(tipo, QPointF(pos), widget.mapToGlobal(QPointF(pos)), botao, botoes,
                     Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(widget, ev)
"""


def rodar(corpo: str) -> None:
    p = rodar_python(PREAMBULO + corpo, timeout=180)
    assert p.returncode == 0, p.stderr + p.stdout
    assert p.stdout.strip().endswith("ok"), p.stdout + p.stderr


def test_puxar_canto_muda_o_zoom_com_o_canto_oposto_parado():
    rodar("""
estado, foto, ed = montar()
imp = estado.impressao_atual
assert imp.recorte.origem != "manual" and imp.recorte.zoom == 1.0
W, H = receita.dimensoes_giradas(imp, *ed._dims())
avisos = []
estado.foto_mudou.connect(avisos.append)

# canto inferior direito até o meio da diagonal: metade do tamanho (zoom 2), o superior esquerdo parado
c0 = cantos(ed, imp)
alvo = ((c0[0][0] + c0[2][0]) / 2 / W, (c0[0][1] + c0[2][1]) / 2 / H)
assert ed.puxar_canto(2, alvo)
assert imp.recorte.origem == "manual" and avisos == ["f1"] and estado.modificado
assert abs(imp.recorte.zoom - 2.0) < 1e-9
c1 = cantos(ed, imp)
assert math.dist(c1[0], c0[0]) < 1e-6
dentro(ed, imp)

# cada canto, para dentro: o oposto fica parado e a proporção é exata
for canto in range(4):
    antes = cantos(ed, imp)
    op = antes[(canto + 2) % 4]
    alvo = ((op[0] + (antes[canto][0] - op[0]) * 0.8) / W, (op[1] + (antes[canto][1] - op[1]) * 0.8) / H)
    zoom = imp.recorte.zoom
    assert ed.puxar_canto(canto, alvo)
    assert abs(imp.recorte.zoom - zoom / 0.8) < 1e-6
    assert math.dist(cantos(ed, imp)[(canto + 2) % 4], op) < 1e-6
    dentro(ed, imp)

# para fora da imagem: zoom 1 (o maior papel), empurrado para dentro
assert ed.puxar_canto(2, (5.0, 5.0))
assert imp.recorte.zoom == 1.0
dentro(ed, imp)
# por cima do canto oposto: o menor papel (ZOOM_MAXIMO), nunca invertido
ed.puxar_canto(0, (5.0, 5.0))
assert imp.recorte.zoom == ZOOM_MAXIMO
dentro(ed, imp)

# endireitado: continua na proporção e dentro da imagem, o canto oposto parado quando cabe
imp.recorte = Recorte(cx=0.5, cy=0.5, zoom=2.0, angulo=0.0, origem="manual")
assert ed.endireitar(12.0)
antes = cantos(ed, imp)
op = antes[3]
alvo = ((op[0] + (antes[1][0] - op[0]) * 0.9) / W, (op[1] + (antes[1][1] - op[1]) * 0.9) / H)
assert ed.puxar_canto(1, alvo)
assert math.dist(cantos(ed, imp)[3], op) < 1e-6 and imp.recorte.angulo == 12.0
for alvo in ((0.0, 0.0), (1.0, 1.0), (0.5, 0.5), (-3.0, 2.0)):
    for canto in range(4):
        ed.puxar_canto(canto, alvo)
        dentro(ed, imp)

# sem mudança real: nada acontece
n = len(avisos)
c = cantos(ed, imp)
assert not ed.puxar_canto(2, (c[2][0] / W, c[2][1] / H)) and len(avisos) == n
assert not ed.puxar_canto(7, (0.5, 0.5))
print("ok")
""")


def test_alcas_com_o_mouse_cursor_e_onde_nao_aparecem():
    rodar("""
estado, foto, ed = montar()
imp = estado.impressao_atual
t = ed.tela
assert t.alcas and len(t.cantos_tela()) == 4
canto = t.cantos_tela()[2]
oposto = t.cantos_tela()[0]

# passar o mouse sobre a alça: cursor de redimensionar; longe dela: a mão
mouse(t, QEvent.Type.MouseMove, canto + QPointF(-3, -2), Qt.MouseButton.NoButton)
assert t.alca_em(canto + QPointF(-3, -2)) == 2
assert t.cursor().shape() in (Qt.CursorShape.SizeFDiagCursor, Qt.CursorShape.SizeBDiagCursor)
centro = (canto + oposto) / 2
mouse(t, QEvent.Type.MouseMove, centro, Qt.MouseButton.NoButton)
assert t.alca_em(centro) is None and t.cursor().shape() == Qt.CursorShape.OpenHandCursor

# arrastar a alça para dentro: o zoom muda; o ponto onde pegou não faz o canto saltar
pegou = canto + QPointF(-4, -4)
mouse(t, QEvent.Type.MouseButtonPress, pegou)
mouse(t, QEvent.Type.MouseMove, pegou)
assert imp.recorte.zoom == 1.0 or abs(imp.recorte.zoom - 1.0) < 1e-6
destino = oposto + (canto - oposto) * 0.5 + (pegou - canto)
mouse(t, QEvent.Type.MouseMove, destino)
assert t.cursor().shape() in (Qt.CursorShape.SizeFDiagCursor, Qt.CursorShape.SizeBDiagCursor)
mouse(t, QEvent.Type.MouseButtonRelease, destino, Qt.MouseButton.NoButton)
assert abs(imp.recorte.zoom - 2.0) < 0.05, imp.recorte.zoom
assert imp.recorte.origem == "manual"
assert (t.cantos_tela()[0] - oposto).manhattanLength() < 1.0
dentro(ed, imp)

# arrastar longe das alças continua movendo (sem mudar o zoom)
zoom = imp.recorte.zoom
centro = (t.cantos_tela()[0] + t.cantos_tela()[2]) / 2
mouse(t, QEvent.Type.MouseButtonPress, centro)
mouse(t, QEvent.Type.MouseMove, centro + QPointF(30, 10))
mouse(t, QEvent.Type.MouseButtonRelease, centro + QPointF(30, 10), Qt.MouseButton.NoButton)
assert imp.recorte.zoom == zoom

# "Resultado": sem alças
ed.definir_previa(True)
assert not t.alcas and t.cantos_tela() is None and t.alca_em(canto) is None
ed.definir_previa(False)
assert t.alcas

# modo caber: sem alças e o gesto não faz nada
imp.modo = receita.MODO_CABER
estado.alterar(foto)
assert not t.alcas and t.cantos_tela() is None
assert not ed.puxar_canto(2, (0.5, 0.5))
t.grab()        # desenha sem erro
imp.modo = "preencher"
estado.alterar(foto)
assert t.alcas
t.grab()

# o slider de endireitar continua usando as setas; no visor elas trocam de foto
estado.trabalho.fotos.append(Foto(id="f2", caminho=gerar_foto("b.png")))
estado.definir_visiveis(["f1", "f2"])
QTest.keyClick(ed.slider_angulo.trilho, Qt.Key.Key_Right)
assert estado.atual is foto and imp.recorte.angulo == 0.1
QTest.keyClick(t, Qt.Key.Key_Right)
assert estado.atual.id == "f2"
print("ok")
""")


def test_setas_no_editor_navegam_entre_as_visiveis():
    rodar("""
from revelador.ui.grade import Grade
estado = Estado()
fotos = []
for i in range(5):
    caminho = gerar_foto(f"n{i}.png", 320, 240, cor=40 * i)
    fotos.append(Foto(id=f"f{i}", caminho=caminho, selecionada=i != 2))
estado.trabalho = Trabalho(fotos=fotos)
grade = Grade(estado)
grade.resize(400, 600)
grade.show()
estado.fotos_mudaram.emit()
ed = Editor(estado)
ed.resize(700, 500)
ed.show()
app.processEvents()
assert estado.visiveis == [f.id for f in fotos]

estado.definir_atual(fotos[0])
QTest.keyClick(ed.tela, Qt.Key.Key_Right)
assert estado.atual is fotos[1]
QTest.keyClick(ed, Qt.Key.Key_Right)       # no rodapé / no editor também vale
assert estado.atual is fotos[2]
QTest.keyClick(ed.tela, Qt.Key.Key_Left)
assert estado.atual is fotos[1]
# para nas pontas
QTest.keyClick(ed.tela, Qt.Key.Key_Left)
QTest.keyClick(ed.tela, Qt.Key.Key_Left)
assert estado.atual is fotos[0]
assert not ed.navegar(-1)
QTest.keyClick(ed.tela, Qt.Key.Key_End)
assert estado.atual is fotos[4]
QTest.keyClick(ed.tela, Qt.Key.Key_Right)
assert estado.atual is fotos[4]
QTest.keyClick(ed.tela, Qt.Key.Key_Home)
assert estado.atual is fotos[0]
# com modificador não navega (Ctrl+→ etc. ficam livres)
QTest.keyClick(ed.tela, Qt.Key.Key_Right, Qt.KeyboardModifier.ControlModifier)
assert estado.atual is fotos[0]

# o filtro vale: só as selecionadas (a f2 some)
grade.definir_filtro(True)
app.processEvents()
assert estado.visiveis == ["f0", "f1", "f3", "f4"]
estado.definir_atual(fotos[1])
QTest.keyClick(ed.tela, Qt.Key.Key_Right)
assert estado.atual is fotos[3]
QTest.keyClick(ed.tela, Qt.Key.Key_Left)
assert estado.atual is fotos[1]
QTest.keyClick(ed.tela, Qt.Key.Key_End)
assert estado.atual is fotos[4]
print("ok")
""")


def test_grade_continua_navegando_com_as_setas():
    rodar("""
from revelador.ui.main_window import MainWindow
j = MainWindow(); j.show()
caminhos = [gerar_foto(f"g{i}.png", 320, 240, cor=50 * i) for i in range(3)]
j.importar([str(c) for c in caminhos])
esperar(lambda: not j.importacao.ocupado and len(j.estado.info) == 3)
fotos = j.estado.trabalho.fotos
j.estado.definir_atual(fotos[0])
app.processEvents()
lista = j.grade.lista
lista.setFocus()
QTest.keyClick(lista, Qt.Key.Key_Right)
app.processEvents()
assert j.estado.atual is fotos[1], j.estado.atual        # um passo só (a grade trata, o editor não repete)
QTest.keyClick(j.editor.tela, Qt.Key.Key_Right)
assert j.estado.atual is fotos[2]
QTest.keyClick(j.editor.tela, Qt.Key.Key_Left)
assert j.estado.atual is fotos[1]
for f in fotos:
    f.rostos = []
j.estado.marcar_modificado(False)
print("ok")
""")


def test_soltar_revelador_abre_o_trabalho_e_fotos_continuam_importando():
    rodar("""
from revelador.ui.main_window import MainWindow
from revelador.ui import projeto_ui as pu


def soltar(janela, caminhos):
    dados = QMimeData()
    dados.setUrls([QUrl.fromLocalFile(str(c)) for c in caminhos])
    ev = QDropEvent(QPointF(10, 10), Qt.DropAction.CopyAction, dados, Qt.MouseButton.LeftButton,
                    Qt.KeyboardModifier.NoModifier)
    janela.dropEvent(ev)
    assert ev.isAccepted()
    app.processEvents()


def pronto(j):
    esperar(lambda: not j.importacao.ocupado and len(j.estado.info) + len(j.estado.erros) >= len(j.estado.trabalho.fotos))


j = MainWindow(); j.show()
foto_a = gerar_foto("a.png", 320, 240)
foto_b = gerar_foto("b.png", 300, 200)
foto_c = gerar_foto("c.png", 200, 300)

# só fotos: importam como antes
soltar(j, [foto_a])
assert [f.caminho.name for f in j.estado.trabalho.fotos] == ["a.png"]
pronto(j)

# um trabalho salvo com a foto b
trab = PASTA / "festa.revelador"
projeto.salvar(Trabalho(fotos=[Foto(id="b1", caminho=foto_b)]), trab)

# há alterações: a pessoa cancela -> nada muda (nem o trabalho, nem as fotos soltas junto)
for f in j.estado.trabalho.fotos:
    f.rostos = []
j.estado.marcar_modificado(True)
j.projeto_ui.perguntar_salvar = lambda: pu.CANCELAR
soltar(j, [trab, foto_c])
esperar(lambda: True)
assert [f.caminho.name for f in j.estado.trabalho.fotos] == ["a.png"]
assert j.estado.trabalho.caminho is None

# descarta -> abre o trabalho (o primeiro .revelador) e as fotos soltas entram nele
j.projeto_ui.perguntar_salvar = lambda: pu.DESCARTAR
outro = PASTA / "outro.revelador"
projeto.salvar(Trabalho(), outro)
soltar(j, [foto_c, trab, outro])
esperar(lambda: j.estado.trabalho.caminho is not None and len(j.estado.trabalho.fotos) == 2)
assert Path(j.estado.trabalho.caminho).name == "festa.revelador"
assert sorted(f.caminho.name for f in j.estado.trabalho.fotos) == ["b.png", "c.png"]
pronto(j)

# só o .revelador, sem alterações pendentes: abre direto
for f in j.estado.trabalho.fotos:
    f.rostos = []
j.estado.marcar_modificado(False)
j.projeto_ui.perguntar_salvar = lambda: (_ for _ in ()).throw(AssertionError("não devia perguntar"))
soltar(j, [outro])
esperar(lambda: j.estado.trabalho.caminho is not None and Path(j.estado.trabalho.caminho).name == "outro.revelador")
assert j.estado.trabalho.fotos == []
j.estado.marcar_modificado(False)
print("ok")
""")
