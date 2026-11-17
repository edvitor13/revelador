"""Cada impressão com o próprio enquadramento, 0 cópias, confirmação ao remover, repetidas juntas no filtro e o
Visualizar com o tamanho e o recorte de cada impressão — e os ``.revelador`` antigos abrindo como antes."""

from __future__ import annotations

import json
from datetime import date

from conftest import rodar_python
from PIL import Image

from revelador import exportar, precos, projeto
from revelador.projeto import Foto, Impressao, Recorte, Trabalho, nova_impressao

# ------------------------------------------------------------------------------------------------ modelo e arquivo


def test_nova_impressao_herda_so_o_giro_e_o_espelho():
    foto = Foto(id="f", caminho=__import__("pathlib").Path("a.jpg"), impressoes=[
        Impressao(recorte=Recorte(cx=0.2, cy=0.7, zoom=3.0, angulo=5.0, giro=3, espelho_v=True, origem="manual"))])
    nova = nova_impressao(foto, "15x21", copias=2)
    assert (nova.tamanho, nova.copias) == ("15x21", 2)
    r = nova.recorte
    assert (r.giro, r.espelho_h, r.espelho_v) == (3, False, True)
    assert (r.cx, r.cy, r.zoom, r.angulo, r.origem) == (0.5, 0.5, 1.0, 0.0, "auto")   # enquadramento próprio
    sozinha = nova_impressao(Foto(id="g", caminho=foto.caminho))
    assert sozinha.recorte == Recorte()


def test_zero_copias_grava_e_le_de_volta(tmp_path):
    foto = Foto(id="f1", caminho=tmp_path / "a.jpg", selecionada=True,
                impressoes=[Impressao(copias=0), Impressao(tamanho="15x21")])
    d = projeto.para_dict(Trabalho(fotos=[foto]), tmp_path / "t.revelador")
    imps = d["fotos"][0]["impressoes"]
    assert imps[0]["copias"] == 0 and "copias" not in imps[1]
    assert d["formato"] == projeto.FORMATO == 1           # sem formato novo: as versões antigas continuam abrindo
    trabalho, avisos = projeto.de_dict(json.loads(json.dumps(d)), tmp_path / "t.revelador")
    assert [i.copias for i in trabalho.fotos[0].impressoes] == [0, 1] and avisos == []


def test_copias_negativas_viram_zero_e_pasta_continua_com_pelo_menos_uma(tmp_path):
    d = {"app": "Revelador", "formato": 1,
         "pastas": [{"id": "p1", "nome": "Natal", "cor": "azul", "copias": 0}],
         "fotos": [{"id": "f1", "caminho": "a.jpg", "selecionada": True,
                    "impressoes": [{"tamanho": "10x15", "copias": -3}]}]}
    trabalho, avisos = projeto.de_dict(d, tmp_path / "t.revelador")
    assert trabalho.fotos[0].impressoes[0].copias == 0
    assert trabalho.pastas[0].copias == 1
    assert avisos                                     # avisa que ajustou


def test_arquivos_antigos_abrem_iguais(raiz):
    """Os exemplos das versões anteriores leem igual: mesmas cópias, recortes e campos."""
    for nome in ("exemplo_formato_1.revelador", "exemplo_pastas.revelador"):
        caminho = raiz / "tests" / "data" / nome
        trabalho, _avisos = projeto.abrir(caminho)
        bruto = json.loads(caminho.read_text(encoding="utf-8"))
        for foto, d in zip(trabalho.fotos, bruto["fotos"]):
            for imp, di in zip(foto.impressoes, d.get("impressoes", [])):
                assert imp.copias == di.get("copias", 1)
                for chave, valor in di.get("recorte", {}).items():
                    assert getattr(imp.recorte, chave) == valor, (nome, chave)


def test_exportacao_e_custo_ignoram_zero_copias(tmp_path):
    img = tmp_path / "a.png"
    Image.new("RGB", (300, 200), (120, 80, 40)).save(img)
    foto = Foto(id="f1", caminho=img, selecionada=True,
                impressoes=[Impressao(tamanho="10x15", copias=0), Impressao(tamanho="15x21", copias=2)])
    so_zero = Foto(id="f2", caminho=img, selecionada=True, impressoes=[Impressao(copias=0)])
    trabalho = Trabalho(fotos=[foto, so_zero])
    plano = exportar.planejar(trabalho, tmp_path / "saida", hoje=date(2026, 11, 17))
    assert [(i.foto.id, i.impressao.tamanho, i.copias) for i in plano.itens] == [("f1", "15x21", 2)]
    assert plano.fotos == 1
    orc = precos.orcamento(trabalho, {"10x15": 150, "15x21": 300})
    assert [(linha.tamanho, linha.fotos, linha.copias) for linha in orc.linhas] == [("15x21", 1, 2)]
    assert orc.total == 600 and orc.completo


# ------------------------------------------------------------------------------------------------ interface

PREAMBULO = r"""
import sys, tempfile, time
from dataclasses import replace
from pathlib import Path
import numpy as np
from PIL import Image
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv[:1])
from revelador import imagem, receita
from revelador.projeto import Foto, Impressao, Recorte, Trabalho
from revelador.ui.estado import Estado

pasta = Path(tempfile.mkdtemp(prefix="revelador_recorte_imp_"))
y, x = np.mgrid[0:600, 0:900]
a = np.stack([x * 255 // 900, y * 255 // 600, (x * y) % 251], axis=-1).astype(np.uint8)
caminho = pasta / "a.png"
Image.fromarray(a).save(caminho)

def esperar(cond, timeout=15.0):
    fim = time.monotonic() + timeout
    while not cond():
        app.processEvents()
        assert time.monotonic() < fim
        time.sleep(0.01)
"""


def rodar(corpo: str, timeout: float = 120.0) -> None:
    r = rodar_python(PREAMBULO + corpo, timeout=timeout)
    assert r.returncode == 0 and "OK" in r.stdout, r.stdout + r.stderr


def test_mexer_na_moldura_de_um_tamanho_nao_muda_o_outro():
    rodar(r"""
from revelador.ui.editor import Editor
estado = Estado()
foto = Foto(id="f1", caminho=caminho, selecionada=True,
            impressoes=[Impressao(tamanho="10x15"), Impressao(tamanho="15x21")])
estado.trabalho = Trabalho(fotos=[foto])
estado.definir_info("f1", imagem.abrir_info(caminho))
foto.rostos = []
estado.refazer_recortes_auto(foto)
ed = Editor(estado); ed.resize(900, 650); ed.show()
estado.definir_atual(foto)
esperar(lambda: ed.proxy is not None)
dez, quinze = foto.impressoes

def igual(r1, r2):
    return (r1.cx, r1.cy, r1.zoom, r1.angulo, r1.giro, r1.espelho_h, r1.espelho_v, r1.origem) == \
           (r2.cx, r2.cy, r2.zoom, r2.angulo, r2.giro, r2.espelho_h, r2.espelho_v, r2.origem)

# no 10x15: mover, aproximar, alça, endireitar, centralizar e foto inteira — o 15x21 fica como estava
estado.definir_impressao(0)
antes = replace(quinze.recorte)
assert ed.aproximar(1.8) and ed.mover(0.08, -0.04) and ed.endireitar(3.0)
assert ed.puxar_canto(2, (0.9, 0.9))
assert dez.recorte.origem == "manual" and igual(quinze.recorte, antes), (quinze.recorte, antes)
assert ed.foto_inteira() and dez.recorte.zoom < 1 and igual(quinze.recorte, antes)
assert ed.centralizar() and igual(quinze.recorte, antes)

# no 15x21: a moldura muda e o 10x15 não
estado.definir_impressao(1)
ed.aproximar(1.5); ed.mover(-0.1, 0.05)
dez_antes = replace(dez.recorte)
ed.mover(0.03, 0.03)
assert igual(dez.recorte, dez_antes) and quinze.recorte.origem == "manual"

# enquadrar pelos rostos: só a impressão mostrada volta ao automático
assert ed.enquadrar_pelos_rostos()
assert quinze.recorte.origem != "manual" and dez.recorte.origem == "manual" and igual(dez.recorte, dez_antes)

# metadados que chegam de novo (abrir o trabalho) não copiam um recorte para o outro
estado.definir_impressao(0)
ed.mover(0.05, 0.0)
salvo = replace(dez.recorte)
estado.definir_info("f1", imagem.abrir_info(caminho))
assert igual(dez.recorte, salvo)

# girar 90° e espelhar são da foto: valem para as duas, cada uma com o próprio enquadramento
ed.aproximar(2.0); ed.mover(0.12, 0.1)
assert abs(dez.recorte.cx - quinze.recorte.cx) > 0.05
assert ed.girar(+1)
assert dez.recorte.giro == quinze.recorte.giro == 1
assert ed.espelhar(True)
assert dez.recorte.espelho_v == quinze.recorte.espelho_v == True     # giro ímpar: espelho visto = eixo v
assert abs(dez.recorte.cx - quinze.recorte.cx) > 1e-6 or abs(dez.recorte.cy - quinze.recorte.cy) > 1e-6

# desfazer volta tudo, passo a passo, e a impressão nova herda o giro e o espelho da foto
estado.pilha.undo(); estado.pilha.undo()
dez, quinze = foto.impressoes              # o desfazer recoloca cópias das impressões
assert dez.recorte.giro == quinze.recorte.giro == 0
ed.girar(+1)
from revelador.ui.painel_impressoes import PainelImpressoes
p = PainelImpressoes(estado)
p.adicionar_impressao("20x30")
nova = foto.impressoes[2].recorte
assert nova.giro == 1 and nova.origem != "manual"
print("OK")
""", timeout=180)


def test_lixeira_pergunta_antes_de_remover_e_o_painel_aceita_zero():
    rodar(r"""
from revelador.ui.painel_impressoes import PainelImpressoes
estado = Estado()
foto = Foto(id="f1", caminho=caminho, selecionada=True,
            impressoes=[Impressao(tamanho="10x15"), Impressao(tamanho="15x21", copias=2)])
estado.trabalho = Trabalho(fotos=[foto])
estado.definir_info("f1", imagem.abrir_info(caminho))
estado.definir_atual(foto)
p = PainelImpressoes(estado)
perguntas = []
p.confirmar_remover = lambda f, imp: perguntas.append((f.id, imp.tamanho)) or False
assert not p.pedir_remover(1) and len(foto.impressoes) == 2 and perguntas == [("f1", "15x21")]
p.confirmar_remover = lambda f, imp: True
assert p.pedir_remover(1) and [i.tamanho for i in foto.impressoes] == ["10x15"]
assert not p.pedir_remover(0)              # a última avulsa não sai (nem pergunta)
estado.pilha.undo()
assert [i.tamanho for i in foto.impressoes] == ["10x15", "15x21"]
p.definir_copias(1, 0)
assert foto.impressoes[1].copias == 0 and not p.linhas[1].rotulo_zero.isHidden()
assert p.linhas[0].rotulo_zero.isHidden()
# a pergunta de verdade: Cancelar é o padrão
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox
def responder():
    caixa = next(w for w in QApplication.topLevelWidgets() if isinstance(w, QMessageBox) and w.isVisible())
    assert "15x21" in caixa.text() and caixa.defaultButton().text() == "Cancelar"
    caixa.defaultButton().click()
QTimer.singleShot(200, responder)
assert p._confirmar_remover(foto, foto.impressoes[1]) is False
print("OK")
""")


def test_filtro_repetidas_poe_as_parecidas_lado_a_lado():
    rodar(r"""
from revelador.ui.grade import REPETIDAS, Grade
estado = Estado()
fotos = [Foto(id=n, caminho=pasta / f"{n}.jpg") for n in ("a", "b", "c", "d", "e", "f")]
estado.trabalho = Trabalho(fotos=fotos)
g = Grade(estado); g.resize(500, 400); g.show()
esperar(lambda: g.total() == 6)
grupos = [["a", "d"], ["b", "f"]]          # a ~ d e b ~ f, espalhadas na ordem de importação
g.modelo.repetidas = {i for gr in grupos for i in gr}
g.modelo.grupo_repetida = {i: n for n, gr in enumerate(grupos) for i in gr}
g.modelo.tamanho = REPETIDAS
g.modelo.recarregar()
assert [f.id for f in g.fotos_visiveis()] == ["a", "d", "b", "f"], [f.id for f in g.fotos_visiveis()]
assert [f.id for f in estado.trabalho.fotos] == ["a", "b", "c", "d", "e", "f"]   # o trabalho não muda de ordem
g.definir_tamanho(None)
assert [f.id for f in g.fotos_visiveis()] == ["a", "b", "c", "d", "e", "f"]     # sem o filtro, a ordem de sempre
print("OK")
""")


def test_visualizar_mostra_cada_impressao_com_tamanho_copias_e_recorte():
    rodar(r"""
from PySide6.QtWidgets import QLabel
from revelador.ui.visualizar import VisualizarDialog, descrever_impressao
estado = Estado()
foto = Foto(id="f1", caminho=caminho, selecionada=True, impressoes=[
    Impressao(tamanho="10x15", copias=2, recorte=Recorte(cx=0.3, zoom=1.5, origem="manual")),
    Impressao(tamanho="15x21", orientacao="retrato"), Impressao(tamanho="20x30", copias=0)])
estado.trabalho = Trabalho(fotos=[foto])
estado.definir_info("f1", imagem.abrir_info(caminho))
estado.refazer_recortes_auto(foto)
t, d = descrever_impressao(estado, foto, foto.impressoes[0])
assert t == "10x15 · 2 cópias" and d == "Paisagem · enquadramento manual · 1800 × 1200 px", (t, d)
t, d = descrever_impressao(estado, foto, foto.impressoes[1])
assert t == "15x21 · 1 cópia" and d.startswith("Retrato · enquadrada") and "1800 × 2480 px" in d, (t, d)
t, _d = descrever_impressao(estado, foto, foto.impressoes[2])
assert "0 cópias" in t and "não vai" in t
v = VisualizarDialog(estado, [foto]); v.show()
esperar(lambda: all(not im.pixmap().isNull() for im in v._imagens.values()))
textos = [l.text() for l in v.findChildren(QLabel)]
assert "10x15 · 2 cópias" in textos and "15x21 · 1 cópia" in textos
tamanhos_px = {n: (im.pixmap().width(), im.pixmap().height()) for n, im in v._imagens.items()}
assert tamanhos_px[0][0] > tamanhos_px[0][1] and tamanhos_px[1][0] < tamanhos_px[1][1]   # cada uma no seu papel
print("OK")
""")
