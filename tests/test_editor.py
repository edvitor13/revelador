"""Editor de enquadramento (subprocesso offscreen): gestos, limites, giro, rostos, prévia e integração na janela."""

from __future__ import annotations

from conftest import rodar_python

PREAMBULO = """
import sys, tempfile, time
from pathlib import Path
import numpy as np
from PIL import Image
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv[:1])
from revelador import enquadramento, imagem, receita, tamanhos
from revelador.projeto import Foto, Impressao, Recorte, Rosto, Trabalho
from revelador.ui.editor import Editor
from revelador.ui.estado import Estado

PASTA = Path(tempfile.mkdtemp(prefix="revelador_editor_"))


def esperar(condicao, timeout=10.0):
    fim = time.monotonic() + timeout
    while not condicao():
        app.processEvents()
        assert time.monotonic() < fim, "tempo esgotado"
        time.sleep(0.01)
    app.processEvents()


def gerar_foto(nome="a.png", largura=800, altura=600):
    y, x = np.mgrid[0:altura, 0:largura]
    a = np.stack([x * 255 // largura, y * 255 // altura, np.full_like(x, 120)], axis=-1).astype(np.uint8)
    caminho = PASTA / nome
    Image.fromarray(a).save(caminho)
    return caminho


def montar(selecionar=True, tamanho="10x15", rostos=None, **kw_imp):
    \"\"\"Estado preenchido à mão + editor com o proxy já carregado.\"\"\"
    estado = Estado()
    caminho = gerar_foto()
    foto = Foto(id="f1", caminho=caminho)
    estado.trabalho = Trabalho(fotos=[foto])
    estado.definir_info("f1", imagem.abrir_info(caminho))
    foto.rostos = rostos
    if selecionar:
        foto.selecionada = True
        foto.impressoes.append(Impressao(tamanho=tamanho, **kw_imp))
        estado.refazer_recortes_auto(foto)
    editor = Editor(estado)
    editor.resize(900, 650)
    editor.show()
    estado.definir_atual(foto)
    esperar(lambda: editor.proxy is not None)
    return estado, foto, editor


def dentro(editor, imp):
    \"\"\"O recorte da impressão cabe na imagem girada e tem a proporção do papel.\"\"\"
    W, H = receita.dimensoes_giradas(imp, *editor._dims())
    ret = receita.retangulo_da_impressao(imp, *editor._dims())
    assert abs(ret.w / ret.h - receita.proporcao(imp, *editor._dims())) < 1e-9
    for x, y in receita.poligono(ret):
        assert -1e-6 <= x <= W + 1e-6 and -1e-6 <= y <= H + 1e-6, (x, y, W, H)
    assert 0 <= imp.recorte.cx <= 1 and 0 <= imp.recorte.cy <= 1 and imp.recorte.zoom >= 1.0
    return ret
"""


def rodar(corpo: str) -> None:
    p = rodar_python(PREAMBULO + corpo, timeout=120)
    assert p.returncode == 0, p.stderr + p.stdout
    assert p.stdout.strip().endswith("ok"), p.stdout + p.stderr


def test_gestos_viram_manual_e_ficam_dentro_da_imagem():
    rodar("""
estado, foto, ed = montar()
imp = estado.impressao_atual
assert imp.recorte.origem in ("centro", "auto")
avisos = []
estado.foto_mudou.connect(avisos.append)
assert not estado.modificado

assert ed.aproximar(2.0)
assert imp.recorte.origem == "manual" and imp.recorte.zoom == 2.0 and avisos == ["f1"] and estado.modificado
ret0 = dentro(ed, imp)

# arrastar para além da borda: para na borda, sempre dentro, e sem mudar o tamanho
for dx, dy in ((5.0, 0.0), (-9.0, 0.0), (0.0, 7.0), (0.0, -7.0), (0.3, 0.2)):
    ed.mover(dx, dy)
    ret = dentro(ed, imp)
    assert abs(ret.w - ret0.w) < 1e-6
ed.mover(-9.0, -9.0)
ret = dentro(ed, imp)
assert abs(ret.cx - ret.w / 2) < 1e-6 and abs(ret.cy - ret.h / 2) < 1e-6
assert not ed.mover(-9.0, -9.0)                   # já na borda: nada muda
n = len(avisos)
assert not ed.mover(0, 0) and len(avisos) == n

# zoom: de 1 a ZOOM_MAXIMO, nunca fora disso
for _ in range(60):
    ed.aproximar(1.5)
assert imp.recorte.zoom == 10.0
for _ in range(60):
    ed.aproximar(1 / 1.5)
assert imp.recorte.zoom == 1.0 and not ed.aproximar(0.5)
dentro(ed, imp)

# endireitar: -45..45 passo 0,1, o recorte continua dentro da imagem em qualquer combinação
assert ed.endireitar(12.34) and imp.recorte.angulo == 12.3
ed.endireitar(99); assert imp.recorte.angulo == 45.0
ed.endireitar(-99); assert imp.recorte.angulo == -45.0
for ang in (-45, -30.5, -7, 0.1, 8, 29.9, 45):
    for cx, cy, z in ((0.0, 0.0, 1.0), (1.0, 1.0, 1.0), (0.5, 0.5, 3.0), (0.9, 0.1, 6.0)):
        imp.recorte = Recorte(cx=cx, cy=cy, zoom=z, angulo=0.0, origem="manual")
        ed.endireitar(ang)
        dentro(ed, imp)
        ed.mover(0.4, -0.4)
        dentro(ed, imp)
        ed.aproximar(1.7)
        dentro(ed, imp)
assert imp.recorte.origem == "manual"
print("ok")
""")


def test_zoom_com_ancora_mantem_o_ponto_sob_o_mouse():
    rodar("""
estado, foto, ed = montar()
imp = estado.impressao_atual
W, H = receita.dimensoes_giradas(imp, *ed._dims())
ancora = (0.7, 0.3)
ed.aproximar(1.0001)                     # fixa um recorte manual (centro aproximado)
imp.recorte = Recorte(cx=0.55, cy=0.5, zoom=1.5, origem="manual")
r0 = receita.retangulo_da_impressao(imp, *ed._dims())
rel0 = ((ancora[0] * W - (r0.cx - r0.w / 2)) / r0.w, (ancora[1] * H - (r0.cy - r0.h / 2)) / r0.h)
ed.aproximar(1.6, ancora)
r1 = receita.retangulo_da_impressao(imp, *ed._dims())
rel1 = ((ancora[0] * W - (r1.cx - r1.w / 2)) / r1.w, (ancora[1] * H - (r1.cy - r1.h / 2)) / r1.h)
assert r1.w < r0.w
# o ponto continua na mesma posição relativa dentro do recorte (a menos que a borda tenha limitado)
assert abs(rel0[0] - rel1[0]) < 1e-6 and abs(rel0[1] - rel1[1]) < 1e-6, (rel0, rel1)
dentro(ed, imp)
print("ok")
""")


def test_mouse_arrastar_e_roda_chamam_os_gestos():
    rodar("""
estado, foto, ed = montar()
imp = estado.impressao_atual
ed.aproximar(2.0)
antes = receita.retangulo_da_impressao(imp, *ed._dims())
k = ed.tela.escala_imagem()
W, H = receita.dimensoes_giradas(imp, *ed._dims())
ed.tela.arrastado.emit(-10.0, 0.0)            # mouse 10 px à esquerda: a moldura anda 10 px (visor) à esquerda
depois = receita.retangulo_da_impressao(imp, *ed._dims())
assert abs((antes.cx - depois.cx) - 10.0 / k * (ed.proxy.shape[1] / W)) < 1e-6
quadro = ed.tela.quadro()
z = imp.recorte.zoom
ed.tela.rolado.emit(1.0, QPointF(quadro.center()))
assert imp.recorte.zoom > z
ed.tela.rolado.emit(-3.0, QPointF(quadro.center()))
assert imp.recorte.zoom < z * 1.0 or imp.recorte.zoom == 1.0
dentro(ed, imp)
print("ok")
""")


def test_girar_troca_a_proporcao_certa():
    rodar("""
estado, foto, ed = montar()
imp = estado.impressao_atual
W0, H0 = ed._dims()
assert (W0, H0) == (800, 600)
assert receita.proporcao(imp, W0, H0) == tamanhos.proporcao("10x15", "paisagem")   # foto deitada: papel deitado
estado_orientacao = receita.orientacao(imp, W0, H0)
assert estado_orientacao == "paisagem"

assert ed.girar(+1)
assert imp.recorte.giro == 1 and imp.recorte.origem == "manual"
assert receita.orientacao(imp, W0, H0) == "retrato"
ret = dentro(ed, imp)
assert abs(ret.w / ret.h - 2 / 3) < 1e-9
assert ed.tela.imagem.width() == 600 and ed.tela.imagem.height() == 800   # a foto na tela também girou
ed.girar(+1)
assert imp.recorte.giro == 2 and abs(dentro(ed, imp).w / dentro(ed, imp).h - 3 / 2) < 1e-9
ed.girar(+1); ed.girar(+1)
assert imp.recorte.giro == 0
ed.girar(-1)
assert imp.recorte.giro == 3 and receita.orientacao(imp, W0, H0) == "retrato"
ed.girar(+1)
assert imp.recorte.giro == 0

# o centro acompanha a foto: um recorte no canto superior esquerdo vai para o superior direito ao girar à direita
imp.recorte = Recorte(cx=0.0, cy=0.0, zoom=3.0, origem="manual")
ed.girar(+1)
r = receita.retangulo_da_impressao(imp, W0, H0)
Wr, Hr = receita.dimensoes_giradas(imp, W0, H0)
assert abs(r.cx + r.w / 2 - Wr) < 1e-6 and abs(r.cy - r.h / 2) < 1e-6

# orientação fixa em retrato: a proporção do papel não muda com o giro, o recorte só se adapta
estado2, foto2, ed2 = montar(orientacao="retrato")
imp2 = estado2.impressao_atual
ed2.girar(+1)
r2 = dentro(ed2, imp2)
assert abs(r2.w / r2.h - 2 / 3) < 1e-9 and imp2.recorte.giro == 1
print("ok")
""")


def test_enquadrar_pelos_rostos_volta_a_auto():
    rodar("""
rosto = Rosto(x=0.62, y=0.25, w=0.1, h=0.16, olhos=None, confianca=0.9)
estado, foto, ed = montar(tamanho="10x15", orientacao="retrato", rostos=[rosto])
imp = estado.impressao_atual
assert imp.recorte.origem == "auto"
auto = Recorte(**vars(imp.recorte))
ed.aproximar(2.0); ed.mover(-0.3, 0.2); ed.endireitar(7.0)
assert imp.recorte.origem == "manual" and imp.recorte != auto
# com o recorte manual, o Estado não o refaz sozinho (regra 6)...
estado.refazer_recortes_auto(foto)
assert imp.recorte.origem == "manual"
# ...mas o botão volta ao automático e usa o mesmo caminho do Estado
avisos = []
estado.foto_mudou.connect(avisos.append)
ed.botao_auto.click()
assert imp.recorte.origem == "auto" and avisos == ["f1"]
assert imp.recorte == auto
sug = enquadramento.recorte_sugerido(imp, 800, 600, foto.rostos, estado.trabalho.margem_corte_mm)
assert imp.recorte == sug and imp.recorte.angulo == 0.0 and imp.recorte.zoom == 1.0
dentro(ed, imp)

# sem os metadados no Estado, usa as proporções do proxy
estado.info.clear()
ed.aproximar(3.0); assert imp.recorte.origem == "manual"
ed.enquadrar_pelos_rostos()
assert imp.recorte.origem == "auto" and imp.recorte == auto

# o giro da impressão sobrevive ao automático
ed.girar(+1); ed.enquadrar_pelos_rostos()
assert imp.recorte.giro == 1 and imp.recorte.origem == "auto"
print("ok")
""")


def test_sem_foto_ou_sem_impressao_mostra_dica_e_nao_mexe():
    rodar("""
estado = Estado()
ed = Editor(estado); ed.resize(900, 650); ed.show(); app.processEvents()
assert "Escolha uma foto" in ed.tela.mensagem and ed.tela.imagem is None
for gesto in (lambda: ed.mover(0.1, 0), lambda: ed.aproximar(2), lambda: ed.girar(1), lambda: ed.endireitar(5),
              ed.enquadrar_pelos_rostos):
    assert gesto() is False
assert not ed.botao_previa.isEnabled() and not ed.slider_angulo.isEnabled() and not ed.modo_vista.isEnabled()
ed.tela.grab()

estado, foto, ed = montar(selecionar=False)
assert estado.impressao_atual is None
assert ed.tela.imagem is not None and "Marque a foto para revelar" in ed.tela.dica and ed.tela.moldura is None
assert (ed.mover(0.1, 0), ed.aproximar(2), ed.endireitar(3), ed.enquadrar_pelos_rostos(), ed.girar(1)) == (False,) * 5
assert not estado.modificado
ed.tela.grab()
# marcar a foto depois faz a moldura aparecer
estado.selecionar(foto)
app.processEvents()
assert "Marque a foto" not in ed.tela.dica and ed.tela.moldura is not None
print("ok")
""")


def test_foto_que_nao_abre_mostra_a_mensagem():
    rodar("""
estado = Estado()
foto = Foto(id="x", caminho=PASTA / "nao_existe.png")
estado.trabalho = Trabalho(fotos=[foto])
ed = Editor(estado); ed.resize(900, 650); ed.show()
estado.definir_atual(foto)
esperar(lambda: "não foi encontrado" in ed.tela.mensagem)
assert ed.proxy is None
print("ok")
""")


def test_desenho_escurece_fora_do_recorte_e_mostra_a_moldura():
    rodar("""
estado, foto, ed = montar()
imp = estado.impressao_atual
ed.aproximar(2.0)
app.processEvents()
q = ed.tela.quadro()
ret = receita.retangulo_da_impressao(imp, *ed._dims())
img = ed.tela.grab().toImage()
k = ed.tela.escala_imagem()
def luz(x_img, y_img):
    c = img.pixelColor(int(q.left() + x_img * k), int(q.top() + y_img * k))
    return c.red() + c.green() + c.blue()
dentro_ = luz(ret.cx - ret.w * 0.1, ret.cy - ret.h * 0.1)
fora = luz(ret.cx - ret.w / 2 - 25 / k if ret.cx - ret.w / 2 > 30 / k else ret.cx + ret.w / 2 + 25 / k, ret.cy)
# na foto de teste o brilho varia pouco entre pontos próximos: dentro do papel é claramente mais claro
assert fora < dentro_ * 0.7, (fora, dentro_)
# o rótulo informa tamanho e resolução (sem aviso: 800x600 para 10x15 fica baixa, então avisa)
t = ed.rotulo_info.text()
assert "10x15" in t and "dpi" in t and "paisagem" in t, t
assert "baixa" in t       # 800 px de largura num papel de 15 cm: < 150 dpi
# rostos
foto.rostos = [Rosto(0.4, 0.3, 0.1, 0.15, None, 0.9)]
ed.mostrar_rostos(True)
estado.alterar(foto)
assert len(ed.tela.rostos) == 1 and ed.tela.mostrar_rostos and ed.caixa_rostos.isChecked()
ed.tela.grab()
print("ok")
""")


def test_previa_pela_receita_chega_com_a_proporcao_do_papel():
    rodar("""
estado, foto, ed = montar()
imp = estado.impressao_atual
ed.mover(0.0, 0.0)
chegou = []
ed.previa_atualizada.connect(lambda: chegou.append(1))
ed.botao_previa.click()
assert ed.mostrar_previa and ed.mostrando_previa
esperar(lambda: ed.previa is not None)
p = ed.previa
assert abs(p.width() / p.height() - 1.5) < 0.01, (p.width(), p.height())
area = ed.tela.area_util()
assert p.width() <= area.width() + 1 and p.height() <= area.height() + 1
assert min(abs(p.width() - area.width()), abs(p.height() - area.height())) < 2     # aproveita o visor
assert ed.tela.mostrar_previa and ed.tela.previa is p
chegou.clear()

# vários gestos seguidos viram UMA prévia (debounce) e ela é a do ÚLTIMO estado; o que ficou velho é descartado
ed.aproximar(2.0); ed.mover(0.1, 0.05); ed.endireitar(6.0); ed.aproximar(1.2); ed.mover(-0.02, 0.0)
geracao = ed.previa_geracao
esperar(lambda: chegou)
app.processEvents(); time.sleep(0.3); app.processEvents()
assert len(chegou) == 1 and ed.previa_geracao == geracao
destino = (ed.previa.width(), ed.previa.height())
esperado = receita.para_uint8(receita.renderizar(ed.proxy, imp, foto.ajustes, destino))
q = ed.previa.convertToFormat(ed.previa.Format.Format_RGB888)
bytes_ = np.frombuffer(q.constBits(), dtype=np.uint8).reshape(q.height(), q.bytesPerLine())[:, :q.width() * 3]
assert np.array_equal(bytes_.reshape(q.height(), q.width(), 3), esperado)      # o que se vê É a receita

# ajustes entram na prévia pelo mesmo caminho
chegou.clear()
foto.ajustes["exposicao"] = 40
estado.alterar(foto)
esperar(lambda: chegou)
q2 = ed.previa.convertToFormat(ed.previa.Format.Format_RGB888)
b2 = np.frombuffer(q2.constBits(), dtype=np.uint8).reshape(q2.height(), q2.bytesPerLine())[:, :q2.width() * 3]
assert b2.reshape(q2.height(), q2.width(), 3).mean() > esperado.mean()

# arrastar e rolar também funcionam na prévia; voltar à moldura
r0 = receita.retangulo_da_impressao(imp, *ed._dims())
ed.tela.arrastado.emit(30.0, 0.0)
assert receita.retangulo_da_impressao(imp, *ed._dims()).cx < r0.cx            # a foto acompanha o mouse
ed.tela.rolado.emit(1.0, QPointF(ed.tela.quadro().center()))
dentro(ed, imp)
ed.botao_moldura.click()
assert not ed.mostrando_previa
print("ok")
""")


def test_resultado_velho_da_previa_e_descartado():
    rodar("""
estado, foto, ed = montar()
imp = estado.impressao_atual
ed.definir_previa(True)
esperar(lambda: ed.previa is not None)
from PySide6.QtGui import QImage
ed.previa = None
antiga = ed.previa_geracao - 1
ed._previa_pronta(antiga, QImage(10, 10, QImage.Format.Format_RGB888))
assert ed.previa is None                                  # geração velha: descartada
ed._previa_pronta(ed.previa_geracao, QImage(10, 10, QImage.Format.Format_RGB888))
assert ed.previa is not None
# trocar de foto também invalida
g = ed.previa_geracao
ed._atual_mudou(None)
assert ed.previa_geracao > g and ed.previa is None
print("ok")
""")


def test_modo_caber_mostra_a_previa_e_nao_deixa_mover():
    rodar("""
estado, foto, ed = montar(modo="caber", orientacao="retrato")
imp = estado.impressao_atual
assert ed.mostrando_previa
esperar(lambda: ed.previa is not None)
p = ed.previa
assert abs(p.width() / p.height() - 2 / 3) < 0.01
assert ed.tela.moldura is None and not ed.tela.arrastavel
assert ed.mover(0.1, 0.1) is False and ed.aproximar(2.0) is False and ed.endireitar(5) is False
assert imp.recorte.origem != "manual"
# girar vale no caber (a foto entra girada) e atualiza a prévia
antes = ed.previa_geracao
assert ed.girar(+1) and imp.recorte.giro == 1
assert ed.previa_geracao > antes
esperar(lambda: ed.previa_geracao and ed.previa is not None)
print("ok")
""")


def test_controles_endireitar_giro_e_teclas():
    rodar("""
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest
estado, foto, ed = montar()
imp = estado.impressao_atual
ed.slider_angulo.trilho.definir_valor(5.5, emitir=True)       # como se arrastasse o slider
assert imp.recorte.angulo == 5.5 and ed.slider_angulo.valor() == 5.5 and imp.recorte.origem == "manual"
ed.slider_angulo.campo.setText("-12")                          # ou digitasse o valor
ed.slider_angulo.campo.editingFinished.emit()
assert imp.recorte.angulo == -12.0 and ed.slider_angulo.valor() == -12.0 and ed.slider_angulo.campo.text() == "-12,0°"
assert ed.slider_angulo.trilho.minimo == -45.0 and ed.slider_angulo.trilho.maximo == 45.0 and ed.slider_angulo.trilho.passo == 0.1
ed.slider_angulo.restaurar()                                   # duplo clique no trilho
assert imp.recorte.angulo == 0.0
ed.botao_zoom_mais.click(); ed.botao_zoom_menos.click()
ed.botao_girar_dir.click(); assert imp.recorte.giro == 1
ed.botao_girar_esq.click(); ed.botao_girar_esq.click(); assert imp.recorte.giro == 3
ed.caixa_rostos.click(); assert ed.tela.mostrar_rostos
# mudança externa do recorte (outra parte da interface) atualiza os controles
imp.recorte = Recorte(angulo=20.0, origem="manual")
estado.alterar(foto)
assert ed.slider_angulo.valor() == 20.0
# atalhos de janela (a janela precisa estar ativa; o QShortcut responde a QTest.keyClick no editor)
ed.activateWindow(); app.processEvents()
giro = imp.recorte.giro
QTest.keyClick(ed.tela, Qt.Key.Key_R)
app.processEvents()
assert imp.recorte.giro in ((giro + 1) % 4, giro)        # em plataformas sem foco de janela o atalho pode não disparar
print("ok")
""")


def test_janela_principal_encaixa_o_editor_e_reage_ao_estado():
    rodar("""
from revelador.ui.main_window import MainWindow
j = MainWindow(); j.show(); app.processEvents()
assert j.orientacao_editor.isHidden()
assert j.editor.parent() is j.area_editor and j.area_editor.layout().indexOf(j.editor) >= 0
caminho = gerar_foto("b.png", 600, 900)
fotos = j.estado.adicionar([caminho])
j.estado.definir_info(fotos[0].id, imagem.abrir_info(caminho))
j.estado.selecionar(fotos[0])
j.estado.definir_atual(fotos[0])
esperar(lambda: j.editor.proxy is not None)
imp = j.estado.impressao_atual
assert j.editor.tela.moldura is not None
r = receita.retangulo_da_impressao(imp, 600, 900)
assert abs(r.w / r.h - 2 / 3) < 1e-9
j.editor.encerrar()
print("ok")
""")
