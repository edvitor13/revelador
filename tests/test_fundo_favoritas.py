"""Fundo ao afastar e "Foto inteira" (#53, #54), continuar de onde parou (#55), favoritas (#56) e o Visualizar em
tela cheia (#57). Interface só em subprocesso offscreen."""

from __future__ import annotations

from conftest import rodar_python

PREAMBULO = """
import sys, tempfile, time
from pathlib import Path
import numpy as np
from PIL import Image
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv[:1])
from revelador import enquadramento, imagem, receita
from revelador.projeto import ZOOM_MINIMO, Foto, Impressao, Recorte, Trabalho
from revelador.ui.estado import Estado

PASTA = Path(tempfile.mkdtemp(prefix="revelador_fundo_"))


def esperar(condicao, timeout=15.0):
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


def montar_editor():
    from revelador.ui.editor import Editor
    estado = Estado()
    caminho = gerar_foto()
    foto = Foto(id="f1", caminho=caminho, selecionada=True, impressoes=[Impressao(tamanho="10x15")])
    estado.trabalho = Trabalho(fotos=[foto])
    estado.definir_info("f1", imagem.abrir_info(caminho))
    foto.rostos = []
    estado.refazer_recortes_auto(foto)
    ed = Editor(estado)
    ed.resize(900, 650)
    ed.show()
    estado.definir_atual(foto)
    esperar(lambda: ed.proxy is not None)
    return estado, foto, ed
"""


def rodar(corpo: str, timeout: float = 180) -> None:
    p = rodar_python(PREAMBULO + corpo, timeout=timeout)
    assert p.returncode == 0, p.stderr + p.stdout
    assert p.stdout.strip().endswith("ok"), p.stdout + p.stderr


def test_editor_foto_inteira_fundo_e_desfazer():
    rodar("""
estado, foto, ed = montar_editor()
imp = estado.impressao_atual
W, H = receita.dimensoes_giradas(imp, *ed._dims())
prop = receita.proporcao(imp, *ed._dims())
assert ed.tela.extensao is None and ed.tela.cor_fundo is None and ed.botao_inteira.isEnabled()

# "Foto inteira": o papel contém a foto inteira, centralizada; o visor mostra tudo com o fundo branco
assert ed.foto_inteira()
r = receita.retangulo_da_impressao(imp, *ed._dims())
assert imp.recorte.origem == "manual" and imp.recorte.zoom == ZOOM_MINIMO
assert abs(r.w - enquadramento.tamanho_foto_inteira(W, H, prop)[0]) < 1e-6
assert ed.tela.extensao is not None and ed.tela.cor_fundo == QColor("#ffffff")
assert "com fundo" in ed.rotulo_info.text()
assert not ed.foto_inteira()                       # já está: nada muda
quadro = ed.tela.quadro()
area = ed.tela.area_util()
cantos = ed.tela._para_tela(quadro, receita.poligono(r))
assert all(area.adjusted(-1, -1, 1, 1).contains(c) for c in cantos)   # o papel inteiro cabe no visor

# cor de fundo: vale para a foto, aparece na moldura e na prévia, e entra no desfazer
assert ed.definir_fundo("#000000") and foto.fundo == "#000000" and ed.tela.cor_fundo == QColor("#000000")
assert not ed.definir_fundo("#000000") and not ed.definir_fundo("azul")
ed.definir_previa(True)
esperar(lambda: ed.previa is not None)
canto = ed.previa.pixelColor(1, ed.previa.height() // 2)
assert (canto.red(), canto.green(), canto.blue()) == (0, 0, 0), canto.name()
ed.definir_previa(False)
estado.desfazer()
assert foto.fundo == "#ffffff"
estado.desfazer()
imp = estado.impressao_atual            # o desfazer repõe cópias das impressões
assert imp.recorte.zoom != ZOOM_MINIMO and ed.tela.extensao is None

# atalho I
ed.setFocus()
QTest.keyClick(ed, Qt.Key.Key_I)
imp = estado.impressao_atual
assert imp.recorte.zoom == ZOOM_MINIMO
# aproximar a partir da foto inteira volta a fechar o papel
for _ in range(10):
    ed.aproximar(1.1)
assert imp.recorte.zoom > 1.0 and ed.tela.extensao is None
estado.marcar_modificado(False)
print("ok")
""")


def test_estado_favoritas_fundo_e_foto_inteira_em_varias_fotos():
    rodar("""
e = Estado()
fotos = [Foto(id=f"f{i}", caminho=Path(f"x{i}.jpg"), selecionada=True, impressoes=[Impressao(), Impressao("20x30")])
         for i in range(3)]
fotos.append(Foto(id="f9", caminho=Path("nao_marcada.jpg")))
e.trabalho = Trabalho(fotos=fotos)
for f in fotos:
    e.absorver(f)
avisos = []
e.favoritas_mudaram.connect(lambda: avisos.append(1))
e.favoritar(fotos[:2])
assert [f.favorita for f in fotos] == [True, True, False, False] and avisos == [1]
assert e.pilha.count() == 1 and "favorita" in e.pilha.undoText()
e.favoritar(fotos[:2])                       # já são: nada
assert e.pilha.count() == 1
e.desfazer()
assert not any(f.favorita for f in fotos)
e.refazer()
assert fotos[0].favorita and fotos[1].favorita

e.definir_fundo(fotos, "#FF0000")
assert all(f.fundo == "#ff0000" for f in fotos) and e.pilha.count() == 2
e.desfazer()
assert all(f.fundo == "#ffffff" for f in fotos)

e.foto_inteira(fotos)
assert e.pilha.index() == 2 and e.pilha.count() == 2     # um passo só para todas
for f in fotos[:3]:
    assert all(i.recorte.zoom == ZOOM_MINIMO and i.recorte.origem == "manual" for i in f.impressoes)
assert fotos[3].impressoes == []
e.desfazer()
assert all(i.recorte.zoom == 1.0 for f in fotos[:3] for i in f.impressoes)

# mudar de foto lembra a última, sem contar como alteração
e.marcar_modificado(False)
e.definir_atual(fotos[2])
assert e.trabalho.ultima_foto == "f2" and not e.modificado
print("ok")
""")


def test_grade_estrela_filtro_e_menu():
    rodar("""
from revelador.ui.grade import FAVORITAS, Grade, rect_estrela
e = Estado()
fotos = [Foto(id=f"f{i}", caminho=gerar_foto(f"g{i}.png", 120, 90)) for i in range(4)]
e.trabalho = Trabalho(fotos=fotos)
for f in fotos:
    e.absorver(f)
g = Grade(e)
g.resize(700, 600)
g.show()
app.processEvents()
indice = g.modelo.indice_da_foto(fotos[1])
r = g.lista.visualRect(indice)
QTest.mouseClick(g.lista.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                 rect_estrela(r).center())
assert fotos[1].favorita and not fotos[0].favorita
assert g.combo_tamanho.itemText(g.combo_tamanho.findData(FAVORITAS)) == "Favoritas (1)"
g.definir_tamanho(FAVORITAS)
assert [f.id for f in g.fotos_visiveis()] == ["f1"]
e.favoritar([fotos[3]])
assert [f.id for f in g.fotos_visiveis()] == ["f1", "f3"]
e.favoritar([fotos[1]], False)
assert [f.id for f in g.fotos_visiveis()] == ["f3"]
g.definir_tamanho(None)

menu = g.menu_contexto([fotos[0]])
nomes = [a.objectName() for a in menu.actions()]
assert "favoritar" in nomes and "foto_inteira" not in nomes       # sem impressão: nada para enquadrar
e.selecionar(fotos[0])
menu = g.menu_contexto([fotos[0], fotos[3]])
acoes = {a.objectName(): a for a in menu.actions()}
assert "foto_inteira" in acoes and "favoritar" in acoes
acoes["favoritar"].trigger()
assert fotos[0].favorita and fotos[3].favorita
menu = g.menu_contexto([fotos[0], fotos[3]])
assert "desfavoritar" in [a.objectName() for a in menu.actions()]
acoes["foto_inteira"].trigger()
assert fotos[0].impressoes[0].recorte.zoom == ZOOM_MINIMO
print("ok")
""")


def test_janela_atalho_f_e_continuar_de_onde_parou():
    rodar("""
from revelador.ui.main_window import MainWindow
from revelador.ui import prefs
from revelador import projeto

j = MainWindow(); j.show()
j.autosalvar.timer.stop()
caminhos = [gerar_foto(f"j{i}.png", 320, 240, cor=40 * i) for i in range(4)]
j.importar([str(c) for c in caminhos])
esperar(lambda: not j.importacao.ocupado and len(j.estado.info) == 4)
fotos = j.estado.trabalho.fotos

# F: favorita a foto atual (e tira de novo); o botão da faixa do editor também
j.estado.definir_atual(fotos[1])
app.processEvents()
j.acao_favoritar.trigger()
assert fotos[1].favorita
j.editor.faixa.botao_favorita.click()
assert not fotos[1].favorita

# salvar com a atual na foto 3: o arquivo guarda ultima_foto
j.estado.definir_atual(fotos[3])
arquivo = PASTA / "trabalho.revelador"
assert j.projeto_ui._gravar(arquivo)
dados = __import__("json").loads(arquivo.read_text(encoding="utf-8"))
assert dados["ultima_foto"] == fotos[3].id and dados["formato"] == 1

# navegar sem mudar nada não pede para salvar, mas fica lembrado (preferências)
j.estado.definir_atual(fotos[2])
assert not j.estado.modificado
assert j.projeto_ui.novo()
assert j.estado.atual is None
mensagens = []
j.statusBar().messageChanged.connect(mensagens.append)
assert j.projeto_ui.abrir(arquivo)
esperar(lambda: j.estado.atual is not None)
assert j.estado.atual.id == fotos[2].id, j.estado.atual
assert j.grade.lista.currentIndex().row() == 2
assert any("parou" in m for m in mensagens), mensagens

# sem a lembrança das preferências (outro computador): vale o que está no arquivo
prefs.settings().remove("projeto/ultimas_fotos")
assert j.projeto_ui.novo()
assert j.projeto_ui.abrir(arquivo)
assert j.estado.atual is not None and j.estado.atual.id == fotos[3].id
j.estado.marcar_modificado(False)
print("ok")
""", timeout=240)


def test_visualizar_tela_cheia_maximizar_e_favorita():
    rodar("""
from revelador.ui.visualizar import VisualizarDialog
e = Estado()
fotos = [Foto(id=f"v{i}", caminho=gerar_foto(f"v{i}.png", 200, 150), selecionada=True,
              impressoes=[Impressao()]) for i in range(2)]
e.trabalho = Trabalho(fotos=fotos)
for f in fotos:
    e.absorver(f)
d = VisualizarDialog(e, fotos, 0)
d.show()
app.processEvents()
assert d.windowFlags() & Qt.WindowType.WindowMaximizeButtonHint
assert not d.maximizada and not d.tela_cheia
d.botao_maximizar.click()
assert d.maximizada and d.botao_maximizar.text() == "Restaurar"
QTest.keyClick(d, Qt.Key.Key_F11)
assert d.tela_cheia and d.botao_tela_cheia.text() == "Sair da tela cheia"
QTest.keyClick(d, Qt.Key.Key_Escape)                  # Esc na tela cheia só sai dela (volta maximizada)
assert not d.tela_cheia and d.maximizada and d.isVisible()
d.botao_maximizar.click()
assert not d.maximizada
QTest.keyClick(d, Qt.Key.Key_F)
assert fotos[0].favorita
QTest.keyClick(d, Qt.Key.Key_Right)
d.botao_favorita.click()
assert fotos[1].favorita
QTest.keyClick(d, Qt.Key.Key_Escape)                  # fora da tela cheia, Esc fecha
assert not d.isVisible()

# a próxima abertura lembra a janela maximizada
d2 = VisualizarDialog(e, fotos, 0)
d2.botao_maximizar.click()
d2.close()
d3 = VisualizarDialog(e, fotos, 0)
assert d3.maximizada
print("ok")
""")
