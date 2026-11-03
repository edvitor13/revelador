"""Pastas de tamanho (#32), interface (subprocesso offscreen): seção Pastas, filtro, arrastar, menus, chip, painel e
o passo de importar pasta."""

from __future__ import annotations

from conftest import rodar_python

PREAMBULO = """
import sys, time, warnings
warnings.simplefilter("ignore", DeprecationWarning)
from pathlib import Path
from tempfile import mkdtemp
from PIL import Image
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QApplication, QDialog, QMenu
app = QApplication(sys.argv[:1])
from revelador.ui import prefs, tema
from revelador.ui.grade import area_chips, celula, largura_duas_colunas, layout_chips
from revelador.ui.main_window import MainWindow
from revelador.ui.painel_impressoes import escolher_no_combo
from revelador.ui.pastas import (ALTURA_LINHA, CHAVE_RECOLHIDA, MAX_LINHAS, MIME_FOTOS, PassoImportarPasta,
                                 ids_do_mime)

def esperar(cond, ms=30000):
    fim = time.time() + ms / 1000
    while time.time() < fim:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False

def pasta_com(n, nome=None):
    d = Path(mkdtemp(prefix="fotos_"))
    if nome:
        d = d / nome
        d.mkdir()
    for i in range(n):
        Image.new("RGB", (600 + i, 400), (i * 20 % 255, 90, 150)).save(d / f"f{i:02d}.jpg")
    return d

def acoes(menu):
    saida = {}
    for a in menu.actions():
        if a.objectName():
            saida[a.objectName()] = a
        if a.menu() is not None:
            saida.update(acoes(a.menu()))
    return saida

prefs.settings().remove(CHAVE_RECOLHIDA)
j = MainWindow(); j.resize(1400, 900); j.show()
e = j.estado
s = j.secao_pastas
g = j.grade
"""

COM_FOTOS = """
fotos = j.importar([pasta_com(5)], marcar=False)
assert esperar(lambda: len(e.info) == 5)
app.processEvents()
a, b, c, d, f = fotos
"""


def rodar(corpo: str) -> None:
    p = rodar_python(PREAMBULO + corpo, timeout=180)
    assert p.returncode == 0, p.stderr + p.stdout
    assert p.stdout.strip().endswith("ok"), p.stdout + p.stderr


def test_secao_e_criar_pasta_pelo_dialogo():
    rodar(COM_FOTOS + """
assert s.parent() is g and g.layout().indexOf(s) == 0          # no topo da grade, acima da lista
assert not s.rolagem.isVisible() and len(s.linhas) == 1        # sem pastas: só o cabeçalho
n = e.pilha.count()
dl = s.criar_dialogo_nova_pasta()
assert dl.tamanho() == e.trabalho.tamanho_padrao and dl.seletor_cor.cor() == "azul"
dl.accept()                                                    # nome vazio: mostra o erro e não cria
assert dl.result() != QDialog.DialogCode.Accepted and not e.trabalho.pastas and not dl.erro.isHidden()
dl.campo_nome.setText("  Família ")
escolher_no_combo(dl.combo_tamanho, "13x18")
dl.seletor_cor.botoes["verde"].click()
dl.accept()
assert dl.result() == QDialog.DialogCode.Accepted
p = dl.pasta_criada
assert (p.nome, p.tamanho, p.cor, p.copias) == ("Família", "13x18", "verde", 1)
assert e.trabalho.pastas == [p] and e.pilha.count() == n + 1
app.processEvents()
assert s.rolagem.isVisible() and [l.pasta for l in s.linhas] == [None, p]
assert s.linha_da_pasta(p).n_fotos == 0 and s.linha_da_pasta(None).n_fotos == 5
# personalizado: as medidas e o preço aparecem só nele
dl = s.criar_dialogo_nova_pasta()
assert dl.seletor_cor.cor() == "azul"                          # a próxima livre da paleta
assert not dl.form.isRowVisible(2)
escolher_no_combo(dl.combo_tamanho, "personalizado")
assert dl.form.isRowVisible(2) and dl.form.isRowVisible(3)
dl.campo_nome.setText("Polaroide"); dl.largura.setValue(88); dl.altura.setValue(107); dl.preco.setText("3,50")
dl.accept()
q = dl.pasta_criada
assert (q.tamanho, q.papel_mm, q.preco_centavos) == ("personalizado", (88.0, 107.0), 350)
app.processEvents()
nome, tam, n_fotos = s.linha_da_pasta(q).textos(400)
assert (nome, tam, n_fotos) == ("Polaroide", "88x107 mm", "0")
# estreita (duas colunas de 80 px): a seção não alarga a grade e corta o nome
g.definir_miniatura(80)
app.processEvents()
assert j.area_grade.minimumWidth() == largura_duas_colunas(80)
assert g.layout().itemAt(0).minimumSize().width() <= largura_duas_colunas(80)   # a seção não impõe largura
q2 = e.criar_pasta("Um nome de pasta bem comprido para caber numa coluna estreita", "15x21")
app.processEvents()
nome, tam, n_fotos = s.linha_da_pasta(q2).textos(largura_duas_colunas(80) - 12)
assert nome.endswith("…") and n_fotos == "0"
# muitas pastas: a lista rola em vez de comer a grade; recolher é lembrado
for i in range(8):
    e.criar_pasta(f"P{i}")
app.processEvents()
assert s.rolagem.height() <= (MAX_LINHAS + 1) * (ALTURA_LINHA + 1) + 2 and len(s.linhas) == 12
s.recolher(True)
assert not s.rolagem.isVisible() and prefs.settings().value(CHAVE_RECOLHIDA) in (True, "true")
s.recolher(False)
assert s.rolagem.isVisible()
print("ok")
""")


def test_filtro_pela_pasta_e_volta_a_todas():
    rodar(COM_FOTOS + """
p = e.criar_pasta("Natal", "15x21")
q = e.criar_pasta("Praia")
e.adicionar_a_pasta([a, c, d], p)
e.adicionar_a_pasta([b], q)
app.processEvents()
assert s.linha_da_pasta(p).n_fotos == 3 and s.linha_da_pasta(q).n_fotos == 1
s.clicar(p)
assert s.pasta_filtrada == p.id and g.pasta_filtrada == p.id
assert g.fotos_visiveis() == [a, c, d] and e.visiveis == [a.id, c.id, d.id]
assert s.linha_da_pasta(p).ativa and not s.linha_da_pasta(None).ativa
# a pasta + "Selecionadas": as duas condições (só as marcadas da pasta)
e.selecionar(c, False)
assert g.fotos_visiveis() == [a, c, d]                         # desmarcada continua na pasta
j.filtro_mostrar.botoes["selecionadas"].click()
assert g.fotos_visiveis() == [a, d]
j.filtro_mostrar.botoes["todas"].click()
# tirar da pasta some do filtro na hora; entrar aparece
e.tirar_da_pasta([d], p)
assert g.fotos_visiveis() == [a, c]
e.adicionar_a_pasta([f], p)
assert g.fotos_visiveis() == [a, c, f]
# clicar de novo na pasta escolhida (ou em "Todas") volta a todas
s.clicar(p)
assert s.pasta_filtrada is None and g.pasta_filtrada is None and g.total() == 5
s.clicar(q); assert g.fotos_visiveis() == [b]
s.clicar(None); assert g.total() == 5
# apagar a pasta filtrada (com a confirmação trocada) volta a todas; o desfazer devolve a pasta, sem filtro
s.clicar(q)
perguntas = []
s.confirmar_apagar = lambda pasta, n: perguntas.append((pasta.nome, n)) or False
s.apagar(q)
assert perguntas == [("Praia", 1)] and q in e.trabalho.pastas   # recusou: nada muda
s.confirmar_apagar = lambda pasta, n: True
s.apagar(q)
app.processEvents()
assert q not in e.trabalho.pastas and s.pasta_filtrada is None and g.pasta_filtrada is None and g.total() == 5
assert not b.selecionada
e.desfazer(); app.processEvents()
assert [x.nome for x in e.trabalho.pastas] == ["Natal", "Praia"] and b.selecionada
assert [l.pasta.nome if l.pasta else None for l in s.linhas] == [None, "Natal", "Praia"]
print("ok")
""")


def test_arrastar_fotos_e_adicionar_pelo_menu():
    rodar(COM_FOTOS + """
p = e.criar_pasta("Natal", "15x21", "vermelho", copias=2)
app.processEvents()
# arrastar: a grade põe os ids das escolhidas no mime próprio (sem URLs: nada vai para o Explorer)
mime = g.modelo.mimeData([g.modelo.index(3), g.modelo.index(1)])
assert ids_do_mime(mime) == [b.id, d.id] and not mime.hasUrls() and g.modelo.mimeTypes() == [MIME_FOTOS]
assert not g.pixmap_arrasto([b, d]).isNull() and not g.pixmap_arrasto([b]).isNull()
assert g.modelo.flags(g.modelo.index(0)) & Qt.ItemFlag.ItemIsDragEnabled
linha = s.linha_da_pasta(p)
n = e.pilha.count()
entrar = QDragEnterEvent(QPoint(20, 10), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier)
QApplication.sendEvent(linha, entrar)
assert entrar.isAccepted() and linha.alvo
soltar = QDropEvent(QPointF(20, 10), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton,
                    Qt.KeyboardModifier.NoModifier)
QApplication.sendEvent(linha, soltar)
app.processEvents()
assert not linha.alvo
assert [x.id for x in e.fotos_da_pasta(p)] == [b.id, d.id] and b.selecionada and d.selecionada
imp = e.impressao_da_pasta(b, p)
assert (imp.tamanho, imp.copias) == ("15x21", 2)
assert e.pilha.count() == n + 1                                # várias fotos, um passo do desfazer
app.processEvents()
assert s.linha_da_pasta(p).n_fotos == 2
# "Todas" e arrastos de fora (sem o mime) não aceitam
from PySide6.QtCore import QMimeData
outro = QMimeData(); outro.setText("x")
ev = QDragEnterEvent(QPoint(5, 5), Qt.DropAction.CopyAction, outro, Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier)
linha.dragEnterEvent(ev)
assert not ev.isAccepted() and not linha.alvo
todas = s.linha_da_pasta(None)
ev = QDragEnterEvent(QPoint(5, 5), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier)
todas.dragEnterEvent(ev)
assert not ev.isAccepted() and not todas.alvo and not todas.acceptDrops()

# menu de contexto: "Adicionar à pasta ▸" logo depois de "Cópias ▸"; "Tirar da pasta ▸" se alguma está nela
menu = g.menu_contexto([a, c])
nomes = [x.objectName() for x in menu.actions() if x.objectName()]
assert nomes.index("adicionar_pasta") == nomes.index("copias") + 1 and "tirar_pasta" not in nomes
assert nomes.index("adicionar_pasta") < nomes.index("remover")
itens = acoes(menu)
assert {f"adicionar:{p.id}", "nova_pasta"} <= set(itens) and itens[f"adicionar:{p.id}"].isEnabled()
n = e.pilha.count()
itens[f"adicionar:{p.id}"].trigger()
assert {x.id for x in e.fotos_da_pasta(p)} == {a.id, b.id, c.id, d.id} and e.pilha.count() == n + 1
itens = acoes(g.menu_contexto([a, c]))
assert not itens[f"adicionar:{p.id}"].isEnabled() and itens[f"adicionar:{p.id}"].isChecked()   # já estão
assert f"tirar:{p.id}" in itens
itens[f"tirar:{p.id}"].trigger()
assert {x.id for x in e.fotos_da_pasta(p)} == {b.id, d.id} and not a.selecionada and not c.selecionada
# "Nova pasta…" do menu: cria a pasta e põe as fotos nela, num passo só
n = e.pilha.count()
dl = g.criar_dialogo_nova_pasta([a, f])
dl.campo_nome.setText("Escola")
dl.accept()
nova = dl.pasta_criada
assert nova.nome == "Escola" and [x.id for x in e.fotos_da_pasta(nova)] == [a.id, f.id]
assert e.pilha.count() == n + 1
e.desfazer()
assert [x.nome for x in e.trabalho.pastas] == ["Natal"] and not a.selecionada and not f.selecionada
print("ok")
""")


def test_chip_ganha_a_cor_da_pasta():
    rodar(COM_FOTOS + """
p = e.criar_pasta("Natal", "15x21", "verde")
e.selecionar(a)                                                # avulsa 10x15
e.adicionar_a_pasta([a, b], p)
from PySide6.QtCore import QRect
area = QRect(0, 0, 600, 18)                                    # largura de sobra (a fonte do offscreen é larga)
chips = layout_chips(area, a, pastas=e.trabalho.pastas)
assert [(ch[1], ch.cor) for ch in chips if ch[1] is not None] == [(0, None), (1, tema.cor_pasta("verde"))]
assert layout_chips(area, a)[1].cor is None                   # sem as pastas, nenhuma cor
r, indice, texto, apagado = chips[0]                          # continua uma tupla de 4
# compacto: o chip único leva a cor da primeira impressão de pasta
chip = layout_chips(area, b, True, e.trabalho.pastas)[0]
assert chip[2] == "×1" and chip.cor == tema.cor_pasta("verde")
assert layout_chips(area, a, True, e.trabalho.pastas)[0].cor == tema.cor_pasta("verde")
e.alterar_pasta(p, cor="rosa")
assert layout_chips(area, b, True, e.trabalho.pastas)[0].cor == tema.cor_pasta("rosa")
# o delegado desenha sem erro com as cores (miniatura normal e compacta)
g.lista.viewport().repaint()
g.definir_miniatura(80); app.processEvents(); g.lista.viewport().repaint()
print("ok")
""")


def test_painel_mostra_a_pasta_e_remover_tira_dela():
    rodar(COM_FOTOS + """
p = e.criar_pasta("Natal", "15x21", "roxo")
e.selecionar(a)
e.adicionar_a_pasta([a], p)
e.definir_atual(a)
app.processEvents()
painel = j.painel_impressoes
assert len(painel.linhas) == 2
avulsa, de_pasta = painel.linhas
assert de_pasta.pasta is p and not de_pasta.caixa_pasta.isHidden() and "Natal" in de_pasta.rotulo_pasta.text()
assert avulsa.pasta is None and avulsa.caixa_pasta.isHidden()
assert not de_pasta.combo_tamanho.isEnabled() and avulsa.combo_tamanho.isEnabled()
painel.trocar_tamanho(1, "20x30")                              # o tamanho da impressão de pasta não muda aqui
assert a.impressoes[1].tamanho == "15x21"
e.alterar_pasta(p, nome="Natal 2025")
app.processEvents()
assert "Natal 2025" in painel.linhas[1].rotulo_pasta.text()
# remover a impressão de pasta = tirar da pasta (mesmo sendo a última)
painel.remover_impressao(1)
assert e.fotos_da_pasta(p) == [] and [i.pasta for i in a.impressoes] == [None]
e.adicionar_a_pasta([b], p)
e.definir_atual(b)
app.processEvents()
assert painel.linhas[0].botao_remover.isEnabled()
painel.linhas[0].botao_remover.click()
assert not b.selecionada and e.fotos_da_pasta(p) == []
print("ok")
""")


def test_menu_da_pasta():
    rodar(COM_FOTOS + """
p = e.criar_pasta("Natal", "15x21", "azul")
q = e.criar_pasta("Praia")
e.adicionar_a_pasta([a, b], p)
menu = s.menu_pasta(p)
itens = acoes(menu)
assert {"renomear", "cor", "tamanho_pasta", "copias_pasta", "subir", "descer", "apagar", "cor_verde", "20x30",
        "personalizado", "copias_pasta_3"} <= set(itens)
assert itens["cor_azul"].isChecked() and itens["15x21"].isChecked() and itens["copias_pasta_1"].isChecked()
assert not itens["subir"].isEnabled() and itens["descer"].isEnabled()
s.pedir_nome = lambda pasta: "Natal da família"
itens["renomear"].trigger()
assert p.nome == "Natal da família"
s.pedir_nome = lambda pasta: None                              # cancelou
acoes(s.menu_pasta(p))["renomear"].trigger()
assert p.nome == "Natal da família"
acoes(s.menu_pasta(p))["cor_verde"].trigger()
assert p.cor == "verde"
acoes(s.menu_pasta(p))["20x30"].trigger()
assert p.tamanho == "20x30" and all(e.impressao_da_pasta(x, p).tamanho == "20x30" for x in (a, b))
acoes(s.menu_pasta(p))["copias_pasta_3"].trigger()
assert p.copias == 3 and all(e.impressao_da_pasta(x, p).copias == 3 for x in (a, b))
s.pedir_personalizado = lambda pasta: (90.0, 120.0, 400)
acoes(s.menu_pasta(p))["personalizado"].trigger()
assert (p.tamanho, p.papel_mm, p.preco_centavos) == ("personalizado", (90.0, 120.0), 400)
assert e.impressao_da_pasta(a, p).papel_mm == (90.0, 120.0)
acoes(s.menu_pasta(p))["descer"].trigger()
assert [x.nome for x in e.trabalho.pastas] == ["Praia", "Natal da família"]
app.processEvents()
assert [l.pasta.id if l.pasta else None for l in s.linhas] == [None, q.id, p.id]
s.confirmar_apagar = lambda pasta, n: True
acoes(s.menu_pasta(p))["apagar"].trigger()
assert [x.nome for x in e.trabalho.pastas] == ["Praia"] and not a.selecionada and len(e.trabalho.fotos) == 5
print("ok")
""")


def test_importar_pasta_cria_a_pasta_de_tamanho():
    rodar("""
d = pasta_com(3, "Casamento da Ana")
n = e.pilha.count()
passo = j.criar_passo_importar_pasta(d)
assert isinstance(passo, PassoImportarPasta) and passo.n_fotos == 3
assert passo.criar() and passo.campo_nome.text() == "Casamento da Ana"
assert passo.tamanho() == e.trabalho.tamanho_padrao and passo.seletor_cor.cor() == tema.proxima_cor_pasta([])
passo.accept()
assert len(e.trabalho.fotos) == 3 and len(e.trabalho.pastas) == 1
p = e.trabalho.pastas[0]
assert p.nome == "Casamento da Ana" and p.tamanho == e.trabalho.tamanho_padrao
assert all(f.selecionada and [i.pasta for i in f.impressoes] == [p.id] for f in e.trabalho.fotos)
assert e.pilha.count() == n + 1                                # criar a pasta e marcar as fotos: um passo
assert "Casamento da Ana" in j.acao_desfazer.text()
app.processEvents()
assert s.linha_da_pasta(p).n_fotos == 3
e.desfazer()
assert e.trabalho.pastas == [] and len(e.trabalho.fotos) == 3   # as fotos ficam; só a pasta e a marcação voltam
assert not any(f.selecionada for f in e.trabalho.fotos)
e.refazer()
assert len(e.trabalho.pastas) == 1 and all(f.selecionada for f in e.trabalho.fotos)

# desmarcado: só importa; cancelar não importa nada
d2 = pasta_com(2, "Viagem")
passo = j.criar_passo_importar_pasta(d2)
passo.chave_criar.setChecked(False)
assert not passo.campo_nome.isEnabled()
passo.campo_nome.setText("")                                   # nome vazio não importa quando não vai criar
passo.accept()
assert passo.result() == QDialog.DialogCode.Accepted
assert len(e.trabalho.fotos) == 5 and len(e.trabalho.pastas) == 1
passo = j.criar_passo_importar_pasta(pasta_com(2, "Outra"))
passo.reject()
assert len(e.trabalho.fotos) == 5
# importar de novo uma pasta já importada: as fotos que já estavam entram na pasta nova
passo = j.criar_passo_importar_pasta(d2)
passo.campo_nome.setText("Viagem 10x15")
passo.seletor_cor.botoes["marrom"].click()
passo.accept()
q = e.trabalho.pastas[-1]
assert (q.nome, q.cor) == ("Viagem 10x15", "marrom") and len(e.fotos_da_pasta(q)) == 2 and len(e.trabalho.fotos) == 5
# o trabalho novo ganha o nome da primeira pasta importada (salvamento automático) e a importação continua normal
assert j.autosalvar.nome_automatico() == "Casamento da Ana"
print("ok")
""")
