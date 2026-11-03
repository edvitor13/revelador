"""Painel de ajustes (subprocesso offscreen): gravação só das chaves fora do padrão, grupos, troca de foto,
copiar/colar e a imagem que o editor mostra (com ajustes e no antes/depois)."""

from __future__ import annotations

from conftest import rodar_python

PREAMBULO = """
import sys, tempfile, time
from pathlib import Path
import numpy as np
from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv[:1])
from revelador import ajustes, imagem
from revelador.ui.main_window import MainWindow, aplicar_tema
aplicar_tema(app)

PASTA = Path(tempfile.mkdtemp(prefix="revelador_painel_"))


def esperar(condicao, timeout=15.0):
    fim = time.monotonic() + timeout
    while not condicao():
        app.processEvents()
        assert time.monotonic() < fim, "tempo esgotado"
        time.sleep(0.01)
    app.processEvents()


def gerar_foto(nome, base=110, largura=640, altura=480):
    y, x = np.mgrid[0:altura, 0:largura]
    a = np.stack([x * 120 // largura + base // 2, y * 100 // altura + base // 2, np.full_like(x, base)], axis=-1)
    caminho = PASTA / nome
    Image.fromarray(a.astype(np.uint8)).save(caminho)
    return caminho


def abrir(nomes=("a.png", "b.png")):
    j = MainWindow()
    j.resize(1300, 800)
    j.show()
    fotos = []
    for n in nomes:
        c = gerar_foto(n)
        f = j.estado.adicionar([c])[0]
        j.estado.definir_info(f.id, imagem.abrir_info(c))
        fotos.append(f)
    j.estado.definir_atual(None)      # a grade pode ter escolhido a primeira foto
    app.processEvents()
    return j, fotos


def escolher(estado, foto):
    \"\"\"Torna a foto atual (relendo os ajustes dela mesmo que a grade já a tenha escolhido).\"\"\"
    if estado.atual is foto:
        estado.definir_atual(None)
    estado.definir_atual(foto)


def media(img):
    # média dos canais da QImage mostrada
    ptr = img.constBits()
    a = np.frombuffer(ptr, dtype=np.uint8)
    return float(a.reshape(img.height(), img.bytesPerLine())[:, : img.width() * 3].mean())
"""


def rodar(corpo: str) -> None:
    p = rodar_python(PREAMBULO + corpo, timeout=180)
    assert p.returncode == 0, p.stderr + p.stdout
    assert p.stdout.strip().endswith("ok"), p.stdout + p.stderr


def test_slider_grava_so_o_que_sai_do_padrao():
    rodar("""
j, (a, b) = abrir()
e = j.estado
pa = j.painel_ajustes
e.definir_atual(None)
assert not pa.isEnabled()                         # sem foto atual
assert set(pa.sliders) == {p.chave for p in ajustes.PARAMS} and len(pa.cards) == 3
escolher(e, a)
assert pa.isEnabled()
avisos = []
e.foto_mudou.connect(avisos.append)
pa.sliders["exposicao"].definir_valor(40, emitir=True)
assert a.ajustes == {"exposicao": 40.0} and avisos == ["%s" % a.id] and e.modificado
pa.sliders["contraste"].definir_valor(-10, emitir=True)
assert a.ajustes == {"exposicao": 40.0, "contraste": -10.0}
pa.sliders["exposicao"].restaurar()               # o que o duplo clique faz
assert a.ajustes == {"contraste": -10.0}
pa.sliders["contraste"].definir_valor(0, emitir=True)
assert a.ajustes == {}
# faixa, passo e padrão vêm de PARAMS
for p in ajustes.PARAMS:
    t = pa.sliders[p.chave].trilho
    assert (t.minimo, t.maximo, t.padrao) == (p.minimo, p.maximo, p.padrao)
print("ok")
""")


def test_restaurar_grupo_trocar_de_foto_e_restaurar_todos():
    rodar("""
j, (a, b) = abrir()
e = j.estado
pa = j.painel_ajustes
a.ajustes.update({"exposicao": 30.0, "sombras": 20.0, "saturacao": 25.0, "nitidez": 40.0})
b.ajustes.update({"matiz": -15.0})
escolher(e, a)
assert pa.sliders["exposicao"].valor() == 30 and pa.sliders["matiz"].valor() == 0
pa.cards["Luz"].restaurar_pedido.emit()
assert a.ajustes == {"saturacao": 25.0, "nitidez": 40.0}
assert pa.sliders["exposicao"].valor() == 0 and pa.sliders["saturacao"].valor() == 25
escolher(e, b)                                 # troca de foto: carrega os valores dela
assert pa.sliders["matiz"].valor() == -15 and pa.sliders["saturacao"].valor() == 0
assert b.ajustes == {"matiz": -15.0}               # carregar não grava nada
escolher(e, a)
pa.botao_restaurar_todos.click()
assert a.ajustes == {} and b.ajustes == {"matiz": -15.0}
assert all(s.valor() == 0 for s in pa.sliders.values())
e.definir_atual(None)
assert not pa.isEnabled()
print("ok")
""")


def test_copiar_e_colar_na_atual_e_em_varias():
    rodar("""
j, (a, b, c) = abrir(("a.png", "b.png", "c.png"))
e = j.estado
pa = j.painel_ajustes
a.ajustes.update({"exposicao": 30.0, "vibracao": 12.0})
b.ajustes.update({"contraste": 5.0})
escolher(e, a)
assert pa.copiar()
escolher(e, b)
assert pa.colar() == 1
assert b.ajustes == {"exposicao": 30.0, "vibracao": 12.0} and c.ajustes == {}
assert pa.sliders["exposicao"].valor() == 30
# várias escolhidas na grade: cola em todas
pa._fotos_escolhidas = lambda: [b, c]
b.ajustes.clear()
assert pa.colar() == 2
assert b.ajustes == c.ajustes == {"exposicao": 30.0, "vibracao": 12.0}
b.ajustes["exposicao"] = 99.0                       # copiado é cópia: não acompanha a foto de origem
assert pa._copiado == {"exposicao": 30.0, "vibracao": 12.0}
# atalhos
pa._fotos_escolhidas = None
c.ajustes.clear()
escolher(e, c)
QTest.keyClick(j, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
app.processEvents()
assert c.ajustes == {"exposicao": 30.0, "vibracao": 12.0}, c.ajustes
print("ok")
""")


def test_editor_mostra_os_ajustes_e_o_antes_depois():
    rodar("""
j, (a, b) = abrir()
e = j.estado
ed = j.editor
e.selecionar(a)
escolher(e, a)
esperar(lambda: ed.proxy is not None and ed.tela.imagem is not None)
original = media(ed.tela.imagem)
pa = j.painel_ajustes
pa.sliders["exposicao"].definir_valor(60, emitir=True)
esperar(lambda: ed._ajustada is not None and ed._ajustada_final)
claro = media(ed.tela.imagem)
assert claro > original + 10, (original, claro)
assert ed.tela.largura_ref == ed.proxy.shape[1]
# antes/depois: segurar a tecla mostra a foto sem ajustes; soltar volta
e.definir_comparando(True)
app.processEvents()
assert abs(media(ed.tela.imagem) - original) < 1e-6
e.definir_comparando(False)
app.processEvents()
assert abs(media(ed.tela.imagem) - claro) < 1e-6
# o botão faz o mesmo (pressed/released)
pa.botao_comparar.pressed.emit()
assert e.comparando and abs(media(ed.tela.imagem) - original) < 1e-6
pa.botao_comparar.released.emit()
assert not e.comparando
# a tecla "\\\\" (segurar)
j.activateWindow(); app.processEvents()
if j.isActiveWindow():
    QTest.keyPress(j, Qt.Key.Key_Backslash)
    assert e.comparando
    QTest.keyRelease(j, Qt.Key.Key_Backslash)
    assert not e.comparando
# voltar ao padrão: de novo a original
pa.restaurar_todos()
esperar(lambda: abs(media(ed.tela.imagem) - original) < 1e-6)
# a prévia ("Ver como sai") também recebe os ajustes e respeita o antes/depois
pa.sliders["exposicao"].definir_valor(60, emitir=True)
ed.definir_previa(True)
n = [0]
ed.previa_atualizada.connect(lambda: n.__setitem__(0, n[0] + 1))
esperar(lambda: ed.previa is not None)
esperar(lambda: n[0] >= 0 and ed.previa is not None and media(ed.previa) > 0)
com = media(ed.previa)
e.definir_comparando(True)
antes = n[0]
esperar(lambda: n[0] > antes)
sem = media(ed.previa)
assert com > sem + 10, (com, sem)
print("ok")
""")
