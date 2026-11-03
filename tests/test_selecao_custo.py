"""Seleção, impressões, preços e custo do pedido na interface (subprocesso offscreen, Estado preenchido à mão)."""

from __future__ import annotations

from conftest import rodar_python

PREAMBULO = """
import os, sys, tempfile
os.environ["REVELADOR_SETTINGS_DIR"] = tempfile.mkdtemp()   # prefs próprias de cada caso
from pathlib import Path
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv[:1])
from revelador.imagem import InfoFoto
from revelador.projeto import Foto
from revelador.ui.main_window import MainWindow
from revelador.ui.precos_dialog import PrecosDialog, salvar_tabela_precos, tabela_precos

def nova(j, nome, larg=4000, alt=3000, info=True):
    f = Foto(id=nome, caminho=Path(nome + ".jpg"))
    j.estado.trabalho.fotos.append(f)
    if info:
        j.estado.definir_info(f.id, InfoFoto(larg, alt, None, None, None, 1, 1))
    return f

j = MainWindow()
e = j.estado
p = j.painel_impressoes
"""


def rodar(corpo: str) -> None:
    proc = rodar_python(PREAMBULO + corpo)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip().endswith("ok"), proc.stdout


def test_selecionar_cria_impressao_no_tamanho_padrao_e_painel():
    rodar("""
assert j.orientacao_painel.isHidden() and j.coluna_painel.itemAt(0).widget() is p
f = nova(j, "a")
e.definir_atual(f)
p.caixa_selecao.setChecked(True)
assert f.selecionada and len(f.impressoes) == 1 and f.impressoes[0].tamanho == "10x15"
assert len(p.linhas) == 1 and p.linhas[0].combo_tamanho.currentData() == "10x15"
# tamanho padrão da barra
j.seletor_tamanho.definir("13x18")
assert e.trabalho.tamanho_padrao == "13x18" and e.modificado
g = nova(j, "b"); e.definir_atual(g); p.caixa_selecao.setChecked(True)
assert g.impressoes[0].tamanho == "13x18"
print("ok")
""")


def test_troca_de_tamanho_refaz_auto_e_reencaixa_manual():
    rodar("""
f = nova(j, "a"); e.definir_atual(f); e.selecionar(f)
imp = f.impressoes[0]
assert imp.recorte.origem == "centro"
p.linhas[0].combo_tamanho.setCurrentIndex(p.linhas[0].combo_tamanho.findData("a4"))
assert imp.tamanho == "a4" and imp.recorte.origem == "centro"
from dataclasses import replace
from revelador.enquadramento import retangulo
from revelador import tamanhos
imp.recorte = replace(imp.recorte, origem="manual", cx=0.1, cy=0.9, zoom=2.0)
p.trocar_tamanho(0, "10x10")
assert imp.recorte.origem == "manual" and imp.recorte.zoom == 2.0
r = retangulo(imp.recorte, 4000, 3000, 1.0)
assert abs(r.w / r.h - 1.0) < 1e-9 and r.cx - r.w / 2 >= -1e-6
p.definir_orientacao(0, "retrato")
assert imp.orientacao == "retrato" and imp.recorte.origem == "manual"
# giro de 90: largura e altura trocam
imp.recorte = replace(imp.recorte, giro=1)
p.trocar_tamanho(0, "10x15")
r = retangulo(imp.recorte, 3000, 4000, tamanhos.proporcao("10x15", "retrato"))
assert abs(r.cx / 3000 - imp.recorte.cx) < 1e-9
# sem metadados só troca o tamanho
h = nova(j, "h", info=False); e.definir_atual(h); e.selecionar(h)
p.trocar_tamanho(0, "20x30")
assert h.impressoes[0].tamanho == "20x30"
print("ok")
""")


def test_segunda_impressao_remover_e_copias():
    rodar("""
f = nova(j, "a"); e.definir_atual(f); e.selecionar(f)
p.botao_adicionar.click()
assert len(p.linhas) == 2 and e.indice_impressao == 1
assert f.impressoes[1].tamanho != f.impressoes[0].tamanho
e.definir_impressao(0)
p.linhas[0].spin_copias.setValue(3)
assert f.impressoes[0].copias == 3
p.linhas[1].botao_remover.click()
assert len(f.impressoes) == 1 and len(p.linhas) == 1 and not p.linhas[0].botao_remover.isEnabled()
p.remover_impressao(0)
assert len(f.impressoes) == 1
print("ok")
""")


def test_qualidade_baixa_em_foto_pequena():
    rodar("""
f = nova(j, "pequena", 1200, 900); e.definir_atual(f); e.selecionar(f)
p.trocar_tamanho(0, "30x45")
linha = p.linhas[0]
assert linha.qualidade == "baixa", linha.qualidade
assert "Baixa (" in linha.rotulo_qualidade.text() and "dpi" in linha.rotulo_qualidade.text()
assert "color" in linha.rotulo_qualidade.styleSheet()
p.trocar_tamanho(0, "9x13")
assert p.linhas[0].qualidade == "boa" and p.linhas[0].rotulo_qualidade.text() == "Boa"
print("ok")
""")


def test_precos_salvos_relidos_e_erro_inline():
    rodar("""
assert tabela_precos() == {}
salvar_tabela_precos({"10x15": 150, "20x30": 1234})
assert tabela_precos() == {"10x15": 150, "20x30": 1234}
d = PrecosDialog(e)
assert len(d.campos) == 14 and d.campos["10x15"].text() == "1,50" and d.campos["20x30"].text() == "12,34"
d.campos["10x15"].setText("abc")
avisos = []
e.pedido_mudou.connect(lambda: avisos.append(1))
assert not d.salvar() and not d.erros["10x15"].isHidden() and not avisos
assert tabela_precos()["10x15"] == 150
d.campos["10x15"].setText("2")
d.campos["20x30"].clear()
d.campos["a4"].setText("R$ 1.000,5")
assert d.salvar() and avisos
assert tabela_precos() == {"10x15": 200, "a4": 100050}
d.limpar(); assert d.salvar() and tabela_precos() == {}
print("ok")
""")


def test_custo_na_barra_resumo_parcial_e_personalizado():
    rodar("""
assert j.botao_custo.text() == "Nenhuma foto selecionada para revelação"
salvar_tabela_precos({"10x15": 150})
a = nova(j, "a"); e.definir_atual(a); e.selecionar(a)
assert j.botao_custo.text() == "1 foto · 1 cópia · R$ 1,50", j.botao_custo.text()
p.definir_copias(0, 4)
assert j.botao_custo.text() == "1 foto · 4 cópias · R$ 6,00"
b = nova(j, "b"); e.definir_atual(b); e.selecionar(b)
p.trocar_tamanho(0, "15x21")
assert j.botao_custo.text() == "2 fotos · 5 cópias · R$ 6,00 (sem preço: 15x21)", j.botao_custo.text()
# foto não selecionada fica fora
e.selecionar(b, False)
assert j.botao_custo.text() == "1 foto · 4 cópias · R$ 6,00"
e.selecionar(b)
# personalizado com preço próprio
p.definir_personalizado(0, 100, 250, 300)
assert b.impressoes[0].preco_centavos == 300 and b.impressoes[0].papel_mm == (100, 250)
try:
    p.definir_personalizado(0, 5, 250); raise SystemExit("deveria recusar")
except ValueError:
    pass
j.abrir_resumo()
t = j.resumo.tabela
nomes = [t.item(i, 0).text() for i in range(t.rowCount())]
assert nomes == ["10x15", "Personalizado 100x250 mm"], nomes
assert t.item(1, 4).text() == "R$ 3,00" and t.item(0, 4).text() == "R$ 6,00"
assert "R$ 9,00" in j.resumo.rotulo_total.text() and "Estimativa" in j.resumo.rotulo_aviso.text()
assert j.botao_custo.text() == "2 fotos · 5 cópias · R$ 9,00"
# tudo sem preço
salvar_tabela_precos({}); e.pedido_mudou.emit()
assert j.botao_custo.text() == "2 fotos · 5 cópias · R$ 3,00 (sem preço: 10x15)"
print("ok")
""")
