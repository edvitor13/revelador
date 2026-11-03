"""Desfazer/refazer (#5) e o menu de contexto da grade (subprocesso offscreen)."""

from __future__ import annotations

from conftest import rodar_python

MODELO = """
from pathlib import Path
from revelador.imagem import InfoFoto
from revelador.projeto import Pasta, Recorte, Trabalho
from revelador.ui.estado import Estado

e = Estado()
a, b, c = e.adicionar([Path("a.jpg"), Path("b.jpg"), Path("c.jpg")])
for f in (a, b, c):
    e.definir_info(f.id, InfoFoto(4000, 3000, None, None, None, 1, 1))
assert e.pilha.count() == 0                     # importar e metadados não entram no desfazer
"""

JANELA = """
import sys, time
from pathlib import Path
from tempfile import mkdtemp
from PIL import Image
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv[:1])
from revelador.ui import estado as estado_mod
estado_mod.JUNTAR_MS = 150
from revelador.ui.main_window import MainWindow

def esperar(cond, ms=30000):
    fim = time.time() + ms / 1000
    while time.time() < fim:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False

def pasta_com(n):
    d = Path(mkdtemp(prefix="fotos_"))
    for i in range(n):
        Image.new("RGB", (600 + i, 400), (i * 20 % 255, 90, 150)).save(d / f"f{i:02d}.jpg")
    return d

j = MainWindow(); j.resize(1400, 900); j.show()
e = j.estado
fotos = j.importar([pasta_com(4)])
assert esperar(lambda: not j.importacao.ocupado and j.importacao._total == 0 and len(e.info) == 4)
app.processEvents()
assert e.pilha.count() == 0
"""


def rodar(codigo: str) -> None:
    p = rodar_python(codigo, timeout=120)
    assert p.returncode == 0, p.stderr + p.stdout
    assert p.stdout.strip().endswith("ok"), p.stdout + p.stderr


def test_desfazer_e_refazer_marcar_copias_recorte_e_ajuste():
    rodar(MODELO + """
ev = []
e.foto_mudou.connect(lambda i: ev.append(i))
e.selecionar(a)
assert e.pilha.undoText() == "marcação" and a.selecionada and len(a.impressoes) == 1
auto = a.impressoes[0].recorte
a.impressoes[0].copias = 4
e.alterar(a, pedido=True)
assert e.pilha.undoText() == "cópias"
a.impressoes[0].tamanho = "15x21"
e.refazer_recortes_auto(a)
e.alterar(a, pedido=True)
assert e.pilha.undoText() == "tamanho"
a.impressoes[0].recorte = Recorte(cx=0.4, cy=0.5, zoom=1.5, origem="manual")
e.alterar(a)
assert e.pilha.undoText() == "enquadramento"
a.ajustes["exposicao"] = 30.0
e.alterar(a)
assert e.pilha.undoText() == "ajustes" and e.pilha.count() == 5

e.desfazer(); assert a.ajustes == {}
e.desfazer(); assert a.impressoes[0].recorte.origem != "manual" and a.impressoes[0].tamanho == "15x21"
e.desfazer(); assert a.impressoes[0].tamanho == "10x15" and a.impressoes[0].recorte == auto
e.desfazer(); assert a.impressoes[0].copias == 1
e.desfazer(); assert not a.selecionada and a.impressoes == []
assert not e.pilha.canUndo() and e.pilha.redoText() == "marcação"
assert e.atual is a and ev[-1] == a.id           # o passo de uma foto só mostra a foto
for _ in range(5):
    e.refazer()
assert a.selecionada and a.impressoes[0].copias == 4 and a.impressoes[0].tamanho == "15x21"
assert a.impressoes[0].recorte.zoom == 1.5 and a.ajustes == {"exposicao": 30.0}
assert not e.pilha.canRedo()

# o que o sistema muda (rostos, metadados) não vira passo; o refazer usa o recorte automático de agora
n = e.pilha.count()
e.selecionar(b)
e.definir_rostos(b.id, [])
assert e.pilha.count() == n + 1
e.desfazer(); e.refazer()
assert b.impressoes[0].recorte.origem == "centro"
assert e.modificado
print("ok")
""")


def test_lote_remover_pastas_juntar_e_trocar_de_trabalho():
    rodar(MODELO + """
with e.lote("tamanho 15x21"):
    for f in (a, b, c):
        e.selecionar(f)
        with e.lote("de dentro"):                     # aninhado: vale o de fora
            f.impressoes[0].tamanho = "15x21"
            e.alterar(f, pedido=True)
assert e.pilha.count() == 1 and e.pilha.undoText() == "tamanho 15x21"
e.desfazer()
assert not any(f.selecionada or f.impressoes for f in (a, b, c))
e.refazer()
assert all(f.impressoes[0].tamanho == "15x21" for f in (a, b, c))
with e.lote("nada"):
    pass
assert e.pilha.count() == 1                       # lote vazio não empilha

# remover entra no desfazer e volta no mesmo lugar, com os metadados
e.definir_atual(b)
e.remover([a, b])
assert [f.id for f in e.trabalho.fotos] == [c.id] and e.atual is None and b.id not in e.info
assert e.pilha.undoText() == "remoção de 2 fotos"
e.desfazer()
assert [f.id for f in e.trabalho.fotos] == [a.id, b.id, c.id] and b.id in e.info
e.refazer(); e.desfazer()

# pastas de tamanho
e.trabalho.pastas.append(Pasta("p1", "Festa", "laranja"))
e.alterar_pastas()
assert e.pilha.undoText() == "pastas"
e.desfazer(); assert e.trabalho.pastas == []
e.refazer(); assert e.trabalho.pastas[0].nome == "Festa"

# juntar: mesma foto + mesma chave + nada no meio = um passo, até o fim do gesto
n = e.pilha.count()
for v in (10.0, 20.0, 30.0):
    a.ajustes["exposicao"] = v
    e.alterar(a, juntar="ajuste:exposicao")
assert e.pilha.count() == n + 1
a.ajustes["contraste"] = 5.0
e.alterar(a, juntar="ajuste:contraste")          # outra chave: passo novo
a.ajustes["contraste"] = 8.0
e.alterar(a, juntar="ajuste:contraste")
assert e.pilha.count() == n + 2
e.fim_gesto()
a.ajustes["contraste"] = 9.0
e.alterar(a, juntar="ajuste:contraste")          # depois do fim do gesto: passo novo
assert e.pilha.count() == n + 3
e.desfazer(); assert a.ajustes["contraste"] == 8.0
a.ajustes["contraste"] = 12.0
e.alterar(a, juntar="ajuste:contraste")          # depois de desfazer não junta com o passo desfeito
assert e.pilha.count() == n + 3 and not e.pilha.canRedo()
e.desfazer(); e.desfazer(); assert "contraste" not in a.ajustes and a.ajustes["exposicao"] == 30.0
e.desfazer(); assert "exposicao" not in a.ajustes

# trocar de trabalho limpa a pilha (e não marca modificado)
e.definir_trabalho(Trabalho())
assert e.pilha.count() == 0 and not e.pilha.canUndo() and not e.modificado
print("ok")
""")


def test_acoes_da_janela_e_gestos_do_editor_e_dos_ajustes():
    rodar(JANELA + """
assert not j.acao_desfazer.isEnabled() and not j.acao_refazer.isEnabled()
assert j.acao_desfazer.text() == "Desfazer"
f = fotos[0]
e.definir_atual(f)
j.painel_impressoes.alternar_selecao(True)
assert j.acao_desfazer.isEnabled() and j.acao_desfazer.text() == "Desfazer marcação"
j.acao_desfazer.trigger()
assert not f.selecionada and not j.acao_desfazer.isEnabled()
assert j.acao_refazer.isEnabled() and j.acao_refazer.text() == "Refazer marcação"
j.acao_refazer.trigger()
assert f.selecionada and not j.acao_refazer.isEnabled()
j.painel_impressoes.trocar_tamanho(0, "13x18")
assert j.acao_desfazer.text() == "Desfazer tamanho"

# arrastar no visor do editor = um passo só
ed = j.editor
assert esperar(lambda: ed.proxy is not None)
app.processEvents()
ed.aproximar(2.0)
n = e.pilha.count()
assert esperar(lambda: e._aberto is None, 3000)  # o zoom (sem fim explícito) fecha sozinho
centro = ed.tela.quadro().center().toPoint()
QTest.mousePress(ed.tela, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, centro)
for i in range(1, 8):
    QTest.mouseMove(ed.tela, centro + QPoint(6 * i, 3 * i))
    time.sleep(0.05)
    app.processEvents()
time.sleep(0.25); app.processEvents()           # pausa no meio do arrasto (mais que o JUNTAR_MS) não divide
QTest.mouseMove(ed.tela, centro + QPoint(60, 30))
QTest.mouseRelease(ed.tela, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, centro + QPoint(60, 30))
assert e.pilha.count() == n + 1 and j.acao_desfazer.text() == "Desfazer enquadramento"
cx = f.impressoes[0].recorte.cx
QTest.mousePress(ed.tela, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, centro)
QTest.mouseMove(ed.tela, centro + QPoint(-20, 0))
QTest.mouseRelease(ed.tela, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, centro + QPoint(-20, 0))
assert e.pilha.count() == n + 2                   # outro arrasto: outro passo
e.desfazer()
assert abs(f.impressoes[0].recorte.cx - cx) < 1e-12
e.desfazer()
assert e.pilha.count() == n + 2 and e.pilha.index() == n

# slider de endireitar: arrastar o trilho = um passo
trilho = ed.slider_angulo.trilho
m = e.pilha.index()
y = trilho.height() // 2
QTest.mousePress(trilho, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(trilho.width() // 2 + 10, y))
for dx in (20, 30, 40, 50):
    QTest.mouseMove(trilho, QPoint(trilho.width() // 2 + dx, y))
QTest.mouseRelease(trilho, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                   QPoint(trilho.width() // 2 + 50, y))
assert f.impressoes[0].recorte.angulo != 0.0
assert e.pilha.index() == m + 1 and e.pilha.count() == m + 1

# slider de ajuste: arrastar = um passo; o painel volta junto no desfazer
s = j.painel_ajustes.sliders["exposicao"]
t = s.trilho
y = t.height() // 2
QTest.mousePress(t, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(t.width() // 2 + 5, y))
for dx in (10, 20, 30):
    QTest.mouseMove(t, QPoint(t.width() // 2 + dx, y))
QTest.mouseRelease(t, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(t.width() // 2 + 30, y))
assert f.ajustes.get("exposicao", 0) > 0
assert e.pilha.count() == m + 2 and j.acao_desfazer.text() == "Desfazer ajustes"
j.acao_desfazer.trigger()
assert "exposicao" not in f.ajustes and s.valor() == 0.0

# colar ajustes em várias fotos = um passo
f.ajustes = {"contraste": 10.0}; e.alterar(f)
j.painel_ajustes.copiar()
j.grade.lista.selectAll()
app.processEvents()
k = e.pilha.count()
assert j.painel_ajustes.colar() == 3
assert e.pilha.count() == k + 1 and j.acao_desfazer.text() == "Desfazer colar ajustes"
j.acao_desfazer.trigger()
assert all(x.ajustes == {} for x in fotos[1:])

# trocar de trabalho limpa a pilha e desliga as ações
from revelador.projeto import Trabalho
e.definir_trabalho(Trabalho())
assert not j.acao_desfazer.isEnabled() and not j.acao_refazer.isEnabled() and j.acao_desfazer.text() == "Desfazer"
j.editor.encerrar(); e.marcar_modificado(False)
print("ok")
""")


def test_menu_de_contexto_da_grade_aplica_tamanho_copias_e_procurar():
    rodar(JANELA + """
from PySide6.QtWidgets import QMenu

def acoes(menu):
    saida = {}
    for a in menu.actions():
        if a.objectName():
            saida[a.objectName()] = a
        if a.menu() is not None:
            for b in a.menu().actions():
                if b.objectName():
                    saida[b.objectName()] = b
    return saida

a, b, c, d = fotos
e.selecionar(a)
a.impressoes[0].copias = 2
e.alterar(a, pedido=True)
n = e.pilha.count()
menu = j.grade.menu_contexto([a, b, c])
assert isinstance(menu, QMenu)
itens = acoes(menu)
assert {"marcar", "desmarcar", "tamanho", "copias", "remover", "15x21", "copias_3", "copias_mais"} <= set(itens)
assert "procurar" not in itens                     # nenhuma falta no disco
assert itens["marcar"].text() == "Marcar 3 fotos para revelação"
itens["15x21"].trigger()
assert all(f.selecionada and [i.tamanho for i in f.impressoes] == ["15x21"] for f in (a, b, c))
assert not d.selecionada and a.impressoes[0].copias == 2
assert all(i.recorte.origem != "manual" for f in (a, b, c) for i in f.impressoes)
assert e.pilha.count() == n + 1 and j.acao_desfazer.text() == "Desfazer tamanho 15x21"
assert acoes(j.grade.menu_contexto([a, b, c]))["15x21"].isChecked()

acoes(j.grade.menu_contexto([a, b, c]))["copias_3"].trigger()
assert all(i.copias == 3 for f in (a, b, c) for i in f.impressoes) and e.pilha.count() == n + 2
acoes(j.grade.menu_contexto([a, b]))["copias_mais"].trigger()
assert a.impressoes[0].copias == 4 and b.impressoes[0].copias == 4 and c.impressoes[0].copias == 3
acoes(j.grade.menu_contexto([c]))["copias_1"].trigger()
acoes(j.grade.menu_contexto([c]))["copias_menos"].trigger()
assert c.impressoes[0].copias == 1                 # nunca abaixo de 1
assert e.pilha.count() == n + 4                    # o "−1" sem efeito não vira passo

for _ in range(4):
    e.desfazer()
assert a.impressoes[0].tamanho == "10x15" and a.impressoes[0].copias == 2
assert not b.selecionada and not c.selecionada and not b.impressoes

# impressão de pasta não muda de tamanho; a foto ganha uma avulsa
d.selecionada = True
from revelador.projeto import Impressao
d.impressoes = [Impressao(tamanho="20x30", pasta="p1")]
e.alterar(d, pedido=True)
acoes(j.grade.menu_contexto([d]))["13x18"].trigger()
assert [(i.tamanho, i.pasta) for i in d.impressoes] == [("20x30", "p1"), ("13x18", None)]

# marcar/desmarcar e remover pelo menu (um passo cada)
acoes(j.grade.menu_contexto([a, d]))["desmarcar"].trigger()
assert not a.selecionada and not d.selecionada
j.acao_desfazer.trigger()
assert a.selecionada and d.selecionada
acoes(j.grade.menu_contexto([b, c]))["remover"].trigger()
assert [f.id for f in e.trabalho.fotos] == [a.id, d.id] and j.grade.total() == 2
j.acao_desfazer.trigger()
assert [f.id for f in e.trabalho.fotos] == [a.id, b.id, c.id, d.id] and j.grade.total() == 4

# "Procurar…": só com foto faltando; liga na busca do projeto
chamadas = []
j.projeto_ui.procurar_faltando = lambda *x: chamadas.append(x) or 0
b.caminho.unlink()
itens = acoes(j.grade.menu_contexto([a, b]))
assert "procurar" in itens and "procurar" not in acoes(j.grade.menu_contexto([a]))
itens["procurar"].trigger()
assert chamadas == [()]

# o clique direito escolhe a foto sob o mouse (sem abrir o menu de verdade no teste)
j.grade.menu_contexto = lambda fs: (chamadas.append([f.id for f in fs]), QMenu())[1]
lista = j.grade.lista
lista.clearSelection()
r = lista.visualRect(j.grade.modelo.indice_da_foto(c))
from PySide6.QtGui import QContextMenuEvent
evento = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, r.center(), lista.viewport().mapToGlobal(r.center()))
lista.contextMenuEvent(evento)
assert chamadas[-1] == [c.id]
j.editor.encerrar(); e.marcar_modificado(False)
print("ok")
""")
