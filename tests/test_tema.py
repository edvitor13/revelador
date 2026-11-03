"""Tema visual: folha de estilo, paleta neutra, ícones desenhados e componentes próprios (Qt só em subprocesso)."""

from __future__ import annotations

import re
import subprocess
import sys

from conftest import ROOT, rodar_python

from revelador.ui import tema


def _luminancia(cor: str) -> float:
    canais = [int(cor[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in canais]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _contraste(a: str, b: str) -> float:
    la, lb = sorted((_luminancia(a), _luminancia(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def test_cinzas_neutros_sem_matiz():
    for nome in ("BG", "PAINEL", "PAINEL2", "PAINEL3", "BORDA", "BORDA_FORTE", "TEXTO", "APAGADO", "FRACO",
                 "CANVAS_EDITOR"):
        cor = getattr(tema, nome)
        r, g, b = (int(cor[i:i + 2], 16) for i in (1, 3, 5))
        assert r == g == b, f"{nome} = {cor} não é cinza neutro"


def test_contraste_do_texto_aa():
    for fundo in (tema.BG, tema.PAINEL, tema.PAINEL2):
        for texto in (tema.TEXTO, tema.APAGADO, tema.FRACO, tema.DESTAQUE, tema.OK, tema.AVISO, tema.PERIGO):
            assert _contraste(texto, fundo) >= 4.5, (texto, fundo)
    assert _contraste(tema.TEXTO_SOBRE_DESTAQUE, tema.DESTAQUE) >= 4.5


def test_destaque_vem_do_logo():
    svg = (ROOT / "assets" / "logo.svg").read_text(encoding="utf-8")
    laranja = re.search(r'stroke="(#[0-9a-fA-F]{6})"', svg).group(1)
    ref = [int(laranja[i:i + 2], 16) for i in (1, 3, 5)]
    atual = [int(tema.DESTAQUE[i:i + 2], 16) for i in (1, 3, 5)]
    assert atual[0] >= 230 and atual[0] > atual[1] > atual[2]          # mesma família (laranja/coral)
    assert abs(atual[1] - ref[1]) <= 30 and abs(atual[2] - ref[2]) <= 30


def test_folha_de_estilo_tem_cores_e_nomes():
    p = rodar_python("""
from PySide6.QtWidgets import QApplication
import sys
app = QApplication(sys.argv[:1])
from PySide6.QtGui import QPalette
from revelador.ui import tema
css = tema.folha_de_estilo("C:/x/seta.png", "C:/x/marca.png")
for nome in ("TopBar", "Panel", "Primary", "Flat", "Seg", "SegBox", "Muted", "Faint", "PanelTitle", "Kicker", "Card",
             "Canvas", "Rodape", "Pilula", "LinhaImp", "AppName"):
    assert "#" + nome in css, nome
for ident in ("QListView", "QTableView", "QHeaderView", "QSlider", "QDialogButtonBox", "QComboBox", "QScrollBar"):
    assert ident in css, ident
for cor in (tema.BG, tema.PAINEL, tema.PAINEL2, tema.DESTAQUE, tema.DESTAQUE_HI, tema.TEXTO, tema.BORDA):
    assert cor in css, cor
assert "C:/x/seta.png" in css and "C:/x/marca.png" in css
assert css.count("{") == css.count("}")
assert tema.paleta().color(QPalette.ColorRole.Highlight).name() == tema.DESTAQUE
assert tema.fonte_ui() and tema.fonte_titulo()
assert tema.fonte(10).pointSizeF() == 10
print("ok")
""")
    assert p.returncode == 0, p.stderr
    assert p.stdout.strip().endswith("ok"), p.stdout


def test_instalar_aplica_tema_no_app():
    p = rodar_python("""
from PySide6.QtWidgets import QApplication
import sys
app = QApplication(sys.argv[:1])
from revelador.ui import tema
tema.instalar(app)
assert app.palette().color(app.palette().ColorRole.Window).name() == tema.BG
assert "QPushButton#Primary" in app.styleSheet()
assert not app.windowIcon().isNull()
print("ok")
""")
    assert p.returncode == 0, p.stderr
    assert p.stdout.strip().endswith("ok"), p.stdout


def test_icones_nao_vazios():
    p = rodar_python("""
from PySide6.QtWidgets import QApplication
import sys
app = QApplication(sys.argv[:1])
from revelador.ui import icones
pedidos = ["importar", "pasta", "exportar", "salvar", "abrir", "configuracoes", "check", "mais", "lixeira",
           "girar_esquerda", "girar_direita", "endireitar", "zoom_mais", "zoom_menos", "rosto", "recorte", "grade",
           "filtro", "dinheiro", "info", "aviso", "chevron", "reset"]
assert set(pedidos) <= set(icones.NOMES)
for nome in icones.NOMES:
    ic = icones.icone(nome, "#ffffff", 24)
    assert not ic.isNull(), nome
    img = ic.pixmap(24, 24).toImage()
    visiveis = sum(1 for y in range(img.height()) for x in range(img.width()) if img.pixelColor(x, y).alpha() > 0)
    assert visiveis > 20, (nome, visiveis)
assert not icones.icone_app().isNull()
try:
    icones.icone("nao_existe")
except KeyError:
    pass
else:
    raise AssertionError("nome inválido devia dar KeyError")
print("ok")
""")
    assert p.returncode == 0, p.stderr
    assert p.stdout.strip().endswith("ok"), p.stdout


def test_componentes_estado_e_sinais():
    p = rodar_python("""
from PySide6.QtWidgets import QApplication, QWidget
import sys
app = QApplication(sys.argv[:1])
from revelador.ui import tema
tema.instalar(app)
from revelador.ui.componentes import Card, Segmented, Slider, ToggleSwitch

# ToggleSwitch
t = ToggleSwitch()
vistos = []
t.toggled.connect(vistos.append)
assert not t.isChecked()
t.click()
assert t.isChecked() and vistos == [True]
t.setChecked(False)
assert vistos == [True, False]

# Segmented
s = Segmented([("a", "A", ""), ("b", "B", "")])
mudou = []
s.mudou.connect(mudou.append)
s.definir_atual("a")
assert s.chave_atual() == "a" and mudou == []
s.botoes["b"].click()
assert s.chave_atual() == "b" and mudou == ["b"]

# Card
c = Card("Luz", "sub", restaurar=True, com_chave=True)
alt, rest, chv = [], [], []
c.alternado.connect(alt.append)
c.restaurar_pedido.connect(lambda: rest.append(1))
c.chave_mudou.connect(chv.append)
c.show()
filho = QWidget()
c.adicionar(filho)
app.processEvents()
assert c.expandido and filho.isVisibleTo(c)
c.expandir(False)
assert not c.expandido and not filho.isVisibleTo(c) and alt == [False]
c.cabecalho.mousePressEvent(None)
assert c.expandido and alt == [False, True]
c.botao_restaurar.click()
assert rest == [1]
c.chave.click()
assert chv == [True]
assert Card("x", expandido=False).expandido is False

# Slider
sl = Slider("Exposição", -2.0, 2.0, 0.05, 0.0, " EV")
vals, soltou = [], []
sl.valor_mudou.connect(vals.append)
sl.soltou.connect(lambda: soltou.append(1))
assert sl.valor() == 0.0 and sl.campo.text() == "0,00 EV", sl.campo.text()
sl.definir_valor(1.0)                       # programático: não emite
assert vals == [] and sl.valor() == 1.0 and sl.campo.text() == "1,00 EV"
sl.trilho.definir_valor(0.5, emitir=True)   # como se arrastasse
assert vals == [0.5] and abs(sl.valor() - 0.5) < 1e-9
sl.restaurar()                              # equivale ao duplo clique
assert sl.valor() == 0.0 and vals[-1] == 0.0 and soltou
sl.campo.setText("1,5")
sl.campo.editingFinished.emit()
assert abs(sl.valor() - 1.5) < 1e-9 and vals[-1] == 1.5
sl.campo.setText("abc")
sl.campo.editingFinished.emit()
assert abs(sl.valor() - 1.5) < 1e-9 and sl.campo.text() == "1,50 EV"
sl.definir_valor(99)                        # limitado à faixa
assert sl.valor() == 2.0
pct = Slider("Opacidade", 0.0, 1.0, 0.01, 1.0, "%", escala=100)
assert pct.campo.text() == "100%", pct.campo.text()
print("ok")
""")
    assert p.returncode == 0, p.stderr
    assert p.stdout.strip().endswith("ok"), p.stdout


def test_captura_tela_gera_png(tmp_path):
    saida = tmp_path / "saida"
    p = subprocess.run([sys.executable, str(ROOT / "tools" / "captura_tela.py"), "--saida", str(saida),
                        "--plataforma", "offscreen"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=180)
    assert p.returncode == 0, p.stderr
    for nome in ("janela.png", "catalogo.png"):
        arq = saida / nome
        assert arq.is_file() and arq.stat().st_size > 2000, nome
        assert arq.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_pilula_barra_adaptavel_e_slider_horizontal():
    p = rodar_python("""
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QPushButton
import sys
app = QApplication(sys.argv[:1])
from revelador.ui import tema
tema.instalar(app)
from revelador.ui.componentes import BarraAdaptavel, Pilula, Slider, botao_plano, com_menu
from PySide6.QtWidgets import QMenu
from PySide6.QtCore import Qt

# Pilula: text() devolve o texto inteiro, a tela mostra uma versão encurtada no meio se faltar lugar
pi = Pilula()
pi.setText("12 fotos · 18 cópias · R$ 45,60 (sem preço: 15x21, 20x25, 30x40)")
assert pi.text().startswith("12 fotos") and pi.minimumSizeHint().width() < pi.sizeHint().width()
pi.resize(150, 32); app.processEvents()
assert "…" in QPushButton.text(pi)
pi.resize(pi.sizeHint().width() + 10, 32); app.processEvents()
assert pi.text() == "12 fotos · 18 cópias · R$ 45,60 (sem preço: 15x21, 20x25, 30x40)"

# BarraAdaptavel: com pouca largura, rótulos somem, botões ficam só com ícone e os opcionais somem
barra = BarraAdaptavel("TopBar")
lay = QHBoxLayout(barra)
rotulo, opcional = QLabel("rótulo de apoio longo longo"), QLabel("opcional opcional opcional opcional")
b1 = botao_plano("importar", "dica", "Importar fotos")
b2 = botao_plano("salvar", "dica", "Projeto")
for w in (rotulo, b1, b2, opcional):
    lay.addWidget(w)
barra.definir_adaptacao(compactos=[b1, b2], opcionais=[opcional], rotulos=[rotulo])
barra.resize(2000, 40); barra.show(); app.processEvents()
assert barra.nivel == 0 and not rotulo.isHidden() and not b1.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonIconOnly
barra.resize(300, 40); app.processEvents()
assert barra.nivel == 3 and rotulo.isHidden() and opcional.isHidden()
assert b1.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonIconOnly and b1.toolTip() == "dica"
barra.resize(2000, 40); app.processEvents()
assert barra.nivel == 0 and not rotulo.isHidden() and not opcional.isHidden()

# botão com menu liga a setinha do tema
com_menu(b1, QMenu())
assert b1.property("menu") is True

# Slider horizontal: tudo numa linha
sl = Slider("Endireitar", -45, 45, 0.1, 0.0, "°", horizontal=True)
sl.resize(400, 30); sl.show(); app.processEvents()
assert abs(sl.rotulo.geometry().center().y() - sl.trilho.geometry().center().y()) <= 3
assert sl.campo.text() == "0,0°"
print("ok")
""")
    assert p.returncode == 0, p.stderr
    assert p.stdout.strip().endswith("ok"), p.stdout
