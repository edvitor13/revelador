"""Orientação explícita (Retrato | Paisagem), "Girar papel" (botão e O) e cópias rápidas (− +, atalhos e chip da grade).

Subprocesso offscreen, Estado preenchido à mão (sem fotos pessoais: imagens geradas no código).
"""

from __future__ import annotations

from conftest import rodar_python

PREAMBULO = """
import sys, tempfile, time
from pathlib import Path
from PySide6.QtCore import Qt, QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv[:1])
from revelador import enquadramento, imagem, receita, tamanhos
from revelador.imagem import InfoFoto
from revelador.projeto import Foto, Impressao, Recorte, Trabalho
from revelador.ui.editor import Editor
from revelador.ui.estado import Estado
from revelador.ui.grade import Grade, area_chips, layout_chips
from revelador.ui.painel_impressoes import PainelImpressoes

PASTA = Path(tempfile.mkdtemp(prefix="revelador_oc_"))


def esperar(condicao, timeout=10.0):
    fim = time.monotonic() + timeout
    while not condicao():
        app.processEvents()
        assert time.monotonic() < fim, "tempo esgotado"
        time.sleep(0.01)
    app.processEvents()


def nova_foto(estado, nome, largura, altura, selecionada=True, tamanho="10x15"):
    f = Foto(id=nome, caminho=PASTA / (nome + ".jpg"))
    estado.trabalho.fotos.append(f)
    estado.definir_info(nome, InfoFoto(largura, altura, None, None, None, 1, 1))
    if selecionada:
        f.selecionada = True
        f.impressoes.append(Impressao(tamanho=tamanho))
        estado.refazer_recortes_auto(f)
    return f


def painel_com(largura, altura):
    estado = Estado()
    estado.trabalho = Trabalho()
    f = nova_foto(estado, "a", largura, altura)
    painel = PainelImpressoes(estado)
    painel.resize(320, 700)
    painel.show()
    estado.definir_atual(f)
    app.processEvents()
    return estado, f, painel


def linha(painel):
    return painel.linhas[0]


def gerar_arquivo(foto, largura, altura):
    import numpy as np
    from PIL import Image
    y, x = np.mgrid[0:altura, 0:largura]
    a = np.stack([x * 255 // largura, y * 255 // altura, np.full_like(x, 120)], axis=-1).astype(np.uint8)
    Image.fromarray(a).save(foto.caminho)
"""


def rodar(corpo: str) -> None:
    p = rodar_python(PREAMBULO + corpo, timeout=120)
    assert p.returncode == 0, p.stderr + p.stdout
    assert p.stdout.strip().endswith("ok"), p.stdout + p.stderr


def test_orientacao_automatica_mostra_a_escolhida_pela_forma_da_foto():
    rodar("""
_e, deitada, p1 = painel_com(4000, 3000)
l = linha(p1)
assert l.seg_orientacao.chave_atual() == "paisagem"
assert not l.rotulo_auto.isHidden() and l.rotulo_auto.text() == "auto"
assert l.botao_voltar.isHidden()
assert deitada.impressoes[0].orientacao == "auto"
_e2, em_pe, p2 = painel_com(3000, 4000)
assert linha(p2).seg_orientacao.chave_atual() == "retrato"
print("ok")
""")


def test_trocar_orientacao_fixa_e_voltar_ao_automatico():
    rodar("""
estado, f, p = painel_com(4000, 3000)
l = linha(p)
imp = f.impressoes[0]
l.seg_orientacao.botoes["retrato"].click()
assert imp.orientacao == "retrato" and imp.recorte.origem != "manual"
assert l.seg_orientacao.chave_atual() == "retrato"
assert l.rotulo_auto.isHidden() and not l.botao_voltar.isHidden()
l.botao_voltar.click()
assert imp.orientacao == "auto"
assert l.seg_orientacao.chave_atual() == "paisagem" and not l.rotulo_auto.isHidden()
assert l.botao_voltar.isHidden()
print("ok")
""")


def test_girar_papel_refaz_auto_e_mantem_manual_com_origem():
    rodar("""
estado, f, p = painel_com(4000, 3000)
imp = f.impressoes[0]
l = linha(p)
l.botao_girar.click()
assert imp.orientacao == "retrato" and l.seg_orientacao.chave_atual() == "retrato"
r = enquadramento.retangulo(imp.recorte, 4000, 3000, tamanhos.proporcao(imp.tamanho, "retrato"))
assert abs(r.w / r.h - 2 / 3) < 1e-6 and imp.recorte.origem != "manual"
# manual: a origem continua manual e o recorte cabe na nova proporção
imp.recorte = Recorte(cx=0.5, cy=0.5, zoom=1.4, origem="manual")
p.girar_papel(0)
assert imp.orientacao == "paisagem" and imp.recorte.origem == "manual"
assert 0 <= imp.recorte.cx <= 1 and 0 <= imp.recorte.cy <= 1 and imp.recorte.zoom == 1.4
print("ok")
""")


def test_editor_girar_papel_e_atalho_o():
    rodar("""
estado, f, p = painel_com(4000, 3000)
gerar_arquivo(f, 800, 600)
imp = f.impressoes[0]
ed = Editor(estado); ed.resize(900, 650); ed.show()
estado.definir_atual(None); estado.definir_atual(f)   # a foto já era a atual: o editor precisa do sinal para carregar
esperar(lambda: ed.proxy is not None)
assert ed.botao_papel.isEnabled()
ed.botao_papel.click()
assert imp.orientacao == "retrato" and receita.orientacao(imp, *ed._dims()) == "retrato"
ed.activateWindow(); app.processEvents()
QTest.keyClick(ed.tela, Qt.Key.Key_O)
app.processEvents()
assert imp.orientacao == "paisagem", imp.orientacao
print("ok")
""")


def test_botoes_de_copias_limites_e_custo():
    rodar("""
estado, f, p = painel_com(4000, 3000)
imp = f.impressoes[0]
l = linha(p)
avisos = []
estado.pedido_mudou.connect(lambda: avisos.append(1))
l.botao_mais.click(); l.botao_mais.click()
assert imp.copias == 3 and l.spin_copias.value() == 3 and avisos
l.botao_menos.click()
assert imp.copias == 2
imp.copias = 999; p.sincronizar()
l.botao_mais.click(); assert imp.copias == 999
imp.copias = 1; p.sincronizar()
l.botao_menos.click(); assert imp.copias == 1
assert l.spin_copias.minimum() == 1 and l.spin_copias.maximum() == 999
print("ok")
""")


def test_atalhos_mais_e_menos_na_impressao_atual():
    rodar("""
estado, f, p = painel_com(4000, 3000)
imp = f.impressoes[0]
app.processEvents()
p.activateWindow(); app.processEvents()
QTest.keyClick(p, Qt.Key.Key_Plus)
app.processEvents()
assert imp.copias == 2, imp.copias
QTest.keyClick(p, Qt.Key.Key_Minus)
app.processEvents()
assert imp.copias == 1, imp.copias
p.mudar_copias_atual(+1)
assert imp.copias == 2
p.mudar_copias_atual(-5)
assert imp.copias == 1
print("ok")
""")


def test_chip_da_grade_tem_mais_e_menos():
    rodar("""
estado = Estado()
estado.trabalho = Trabalho()
f = nova_foto(estado, "a", 4000, 3000)
f.impressoes = [Impressao(tamanho="9x13")]   # um chip cabe folgado na célula; dois viram "+1" (não clicável)
estado.refazer_recortes_auto(f)
g = Grade(estado); g.resize(400, 300); g.show()
esperar(lambda: g.total() == 1)
idx = g.modelo.index(0)
area = area_chips(g.lista.visualRect(idx))
chips = layout_chips(area, f)
assert len(chips) == 1 and chips[0][1] == 0
r = chips[0][0]
mais, menos = QPoint(r.right() - 4, r.center().y()), QPoint(r.left() + 4, r.center().y())
QTest.mouseClick(g.lista.viewport(), Qt.MouseButton.LeftButton, pos=r.center())   # o texto só escolhe
app.processEvents()
assert f.impressoes[0].copias == 1 and estado.atual is f
QTest.mouseClick(g.lista.viewport(), Qt.MouseButton.LeftButton, pos=mais)
app.processEvents()
assert f.impressoes[0].copias == 2
QTest.mouseClick(g.lista.viewport(), Qt.MouseButton.LeftButton, pos=menos)
app.processEvents()
assert f.impressoes[0].copias == 1
# uma cópia a menos não passa de 1
QTest.mouseClick(g.lista.viewport(), Qt.MouseButton.LeftButton, pos=menos)
app.processEvents()
assert f.impressoes[0].copias == 1
print("ok")
""")


def test_chip_compacto_mostra_total_e_clique_funciona():
    rodar("""
estado = Estado()
estado.trabalho = Trabalho()
f = nova_foto(estado, "a", 4000, 3000)
f.impressoes = [Impressao(tamanho="9x13", copias=2)]
estado.refazer_recortes_auto(f)
g = Grade(estado); g.resize(400, 300); g.show()
esperar(lambda: g.total() == 1)
g.definir_miniatura(100)
app.processEvents()
idx = g.modelo.index(0)
chips = layout_chips(area_chips(g.lista.visualRect(idx)), f, True)
assert len(chips) == 1 and chips[0][2] == "×2", chips
r = chips[0][0]
QTest.mouseClick(g.lista.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(r.right() - 4, r.center().y()))
app.processEvents()
assert f.impressoes[0].copias == 3
print("ok")
""")


def test_recorte_comum_duplicar_unificar_e_filtro_por_tamanho():
    rodar("""
from dataclasses import replace
estado = Estado()
estado.trabalho = Trabalho()
f = nova_foto(estado, "a", 4000, 3000)
f.impressoes[0].recorte = replace(f.impressoes[0].recorte, cx=0.3, zoom=2.0, origem="manual")
f.impressoes.append(Impressao(tamanho="15x21"))
estado.refazer_recortes_auto(f)          # a impressão nova herda o recorte escolhido
r = f.impressoes[1].recorte
assert r.origem == "manual" and r.zoom == 2.0 and abs(r.cx - 0.3) < 0.05, r
f.impressoes[0].recorte = replace(f.impressoes[0].recorte, cx=0.6)
estado.compartilhar_recorte(f, f.impressoes[0])
assert abs(f.impressoes[1].recorte.cx - 0.6) < 0.05
# duplicar: mesmo arquivo, id novo, logo depois
d = estado.duplicar(f)
assert d.id != f.id and d.caminho == f.caminho and estado.trabalho.fotos.index(d) == 1
d.impressoes[1].recorte = replace(d.impressoes[1].recorte, cx=0.4)
assert abs(f.impressoes[1].recorte.cx - 0.6) < 0.05      # cópia independente
# unificar: tamanhos iguais somam cópias, a outra sai do trabalho
g = nova_foto(estado, "b", 4000, 3000, tamanho="10x15")
g.impressoes.append(Impressao(tamanho="20x30", copias=2))
estado.absorver(f); estado.absorver(g)
estado.unificar(f, [g])
assert estado.por_id("b") is None
assert [(i.tamanho, i.copias) for i in f.impressoes] == [("10x15", 2), ("15x21", 1), ("20x30", 2)]
estado.desfazer()
assert estado.por_id("b") is not None and [i.copias for i in f.impressoes] == [1, 1]
# filtro por tamanho na grade
gr = Grade(estado); gr.resize(400, 300); gr.show()
esperar(lambda: gr.total() == 3)
gr.definir_tamanho("20x30")
assert [x.id for x in gr.fotos_visiveis()] == ["b"]
assert gr.combo_tamanho.currentData() == "20x30"
gr.definir_tamanho(None)
assert gr.total() == 3
print("ok")
""")


def test_repetidas_e_ima_do_trilho():
    from PIL import Image, ImageDraw

    from revelador import repetidas
    from revelador.ui.componentes import imantar

    def foto(cor, deslocar=0):
        im = Image.new("RGB", (300, 200), cor)
        ImageDraw.Draw(im).ellipse((60 + deslocar, 40, 180 + deslocar, 160), fill=(250, 240, 220))
        return im

    a = repetidas.assinatura(foto((40, 60, 90)))
    b = repetidas.assinatura(foto((40, 60, 90)).resize((150, 100)))    # a mesma em outra resolução
    c = repetidas.assinatura(foto((200, 30, 30), deslocar=100))          # outra foto
    assert repetidas.distancia(a, b) <= repetidas.LIMITE_PADRAO < repetidas.distancia(a, c)
    assert repetidas.agrupar([("a", a), ("b", b), ("c", c)]) == [["a", "b"]]
    # ímã: perto do zero gruda no zero; perto de múltiplo de 5 gruda nele; longe, fica
    assert imantar(1.5, 0.0, 200, 1.2) == 0.0
    assert imantar(24.2, 0.0, 200, 1.2) == 25.0
    assert imantar(22.5, 0.0, 200, 1.2) == 22.5
    assert imantar(0.4, 0.0, 10, 0.06) == 0.4 and imantar(0.48, 0.0, 10, 0.06) == 0.5
