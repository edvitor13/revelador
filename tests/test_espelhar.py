"""Espelhar a foto na horizontal e na vertical: receita, formato do arquivo, rostos e editor (em subprocesso)."""

from __future__ import annotations

import json

import numpy as np
import pytest
from conftest import rodar_python

from revelador import enquadramento, projeto, receita
from revelador.projeto import Foto, Impressao, Recorte, Rosto, Trabalho


def textura(largura: int = 90, altura: int = 60) -> np.ndarray:
    y, x = np.mgrid[0:altura, 0:largura]
    return np.stack([x / largura, y / altura, (x * y) % 7 / 7], axis=-1).astype(np.float32)


@pytest.mark.parametrize("giro", range(4))
def test_girar_espelha_antes_do_giro(giro):
    img = textura()
    assert np.array_equal(receita.girar(img, giro, True, False), np.rot90(img[:, ::-1], -giro))
    assert np.array_equal(receita.girar(img, giro, False, True), np.rot90(img[::-1], -giro))
    assert np.array_equal(receita.girar(img, giro), np.rot90(img, -giro))


def test_renderizar_espelhado_e_o_espelho_do_original():
    img = textura(120, 80)
    base = Impressao(tamanho="10x15", orientacao="paisagem", modo="caber")
    normal = receita.renderizar(img, base, None, (150, 100))
    h = receita.renderizar(img, Impressao(tamanho="10x15", orientacao="paisagem", modo="caber",
                                          recorte=Recorte(espelho_h=True)), None, (150, 100))
    v = receita.renderizar(img, Impressao(tamanho="10x15", orientacao="paisagem", modo="caber",
                                          recorte=Recorte(espelho_v=True)), None, (150, 100))
    assert np.abs(h - normal[:, ::-1]).max() < 1e-4
    assert np.abs(v - normal[::-1]).max() < 1e-4


def test_arquivo_grava_so_quando_espelhado_e_le_de_volta(tmp_path):
    foto = Foto(id="f1", caminho=tmp_path / "a.jpg", selecionada=True,
                impressoes=[Impressao(recorte=Recorte(espelho_h=True, giro=1)), Impressao(tamanho="13x18")])
    d = projeto.para_dict(Trabalho(fotos=[foto]), tmp_path / "t.revelador")
    imps = d["fotos"][0]["impressoes"]
    assert imps[0]["recorte"]["espelho_h"] is True and "espelho_v" not in imps[0]["recorte"]
    assert "recorte" not in imps[1]          # sem espelhar, nada novo no arquivo (compatível com as versões antigas)
    assert d["formato"] == projeto.FORMATO == 1
    trabalho, _avisos = projeto.de_dict(json.loads(json.dumps(d)), tmp_path / "t.revelador")
    r = trabalho.fotos[0].impressoes[0].recorte
    assert (r.espelho_h, r.espelho_v, r.giro) == (True, False, 1)


def test_arquivo_antigo_e_valores_estranhos_nao_espelham(tmp_path):
    d = {"app": "Revelador", "formato": 1, "fotos": [
        {"id": "f1", "caminho": "a.jpg", "selecionada": True,
         "impressoes": [{"tamanho": "10x15", "recorte": {"giro": 1}},
                        {"tamanho": "10x15", "recorte": {"espelho_h": "sim", "espelho_v": 1}}]}]}
    trabalho, _avisos = projeto.de_dict(d, tmp_path / "t.revelador")
    for imp in trabalho.fotos[0].impressoes:
        assert (imp.recorte.espelho_h, imp.recorte.espelho_v) == (False, False)


def test_rostos_espelhados_acompanham_a_imagem():
    rosto = Rosto(x=0.1, y=0.2, w=0.2, h=0.3, olhos=((0.15, 0.3), (0.25, 0.3)), confianca=0.9)
    (h,) = enquadramento.girar_rostos([rosto], 0, True, False)
    assert (round(h.x, 6), round(h.y, 6), round(h.w, 6), round(h.h, 6)) == (0.7, 0.2, 0.2, 0.3)
    (v,) = enquadramento.girar_rostos([rosto], 0, False, True)
    assert (round(v.x, 6), round(v.y, 6)) == (0.1, 0.5)
    (g,) = enquadramento.girar_rostos([rosto], 1, True, False)   # espelha e depois gira
    (ref,) = enquadramento.girar_rostos([h], 1)
    assert (g.x, g.y, g.w, g.h) == pytest.approx((ref.x, ref.y, ref.w, ref.h))


def test_recorte_sugerido_mantem_o_espelho_e_segue_o_rosto():
    rosto = Rosto(x=0.05, y=0.3, w=0.1, h=0.15, olhos=None, confianca=0.9)   # rosto à esquerda
    imp = Impressao(tamanho="10x15", orientacao="retrato", recorte=Recorte(espelho_h=True))
    r = enquadramento.recorte_sugerido(imp, 3000, 2000, [rosto])
    assert r.espelho_h and not r.espelho_v
    assert r.cx > 0.5                      # espelhado, o rosto fica à direita e o recorte vai atrás dele


def test_editor_espelha_o_resultado_e_desfaz():
    r = rodar_python(r"""
import sys, tempfile, time
from dataclasses import replace
from pathlib import Path
import numpy as np
from PIL import Image
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv[:1])
from revelador import imagem, receita
from revelador.projeto import Foto, Impressao, Trabalho
from revelador.ui.estado import Estado
from revelador.ui.editor import Editor

pasta = Path(tempfile.mkdtemp(prefix="revelador_espelhar_"))
y, x = np.mgrid[0:600, 0:800]
a = np.stack([x * 255 // 800, y * 255 // 600, (x * y) % 251], axis=-1).astype(np.uint8)
caminho = pasta / "a.png"
Image.fromarray(a).save(caminho)

def esperar(cond, timeout=15.0):
    fim = time.monotonic() + timeout
    while not cond():
        app.processEvents()
        assert time.monotonic() < fim
        time.sleep(0.01)

estado = Estado()
foto = Foto(id="f1", caminho=caminho, selecionada=True, impressoes=[Impressao(tamanho="10x15"),
                                                                    Impressao(tamanho="13x18")])
estado.trabalho = Trabalho(fotos=[foto])
estado.definir_info("f1", imagem.abrir_info(caminho))
foto.rostos = []
estado.refazer_recortes_auto(foto)
ed = Editor(estado)
ed.resize(900, 650)
ed.show()
estado.definir_atual(foto)
esperar(lambda: ed.proxy is not None)
fonte = ed.proxy

for giro_passos in (0, 1):
    for horizontal in (True, False):
        if giro_passos:
            ed.girar(+1)
        ed.aproximar(1.6)
        ed.mover(0.07, -0.05)
        ed.endireitar(4.5)
        imp = estado.impressao_atual
        antes = receita.renderizar(fonte, imp, None, (200, 300))
        recorte_antes = imp.recorte
        assert ed.espelhar(horizontal)
        imp = estado.impressao_atual
        depois = receita.renderizar(fonte, imp, None, (200, 300))
        esperado = antes[:, ::-1] if horizontal else antes[::-1]
        dif = float(np.abs(depois - esperado).mean())
        assert dif < 0.01, (giro_passos, horizontal, dif)
        assert imp.recorte.origem == recorte_antes.origem
        outra = foto.impressoes[1].recorte                     # vale para todas as impressões da foto
        assert (outra.espelho_h, outra.espelho_v) == (imp.recorte.espelho_h, imp.recorte.espelho_v)
        assert estado.pilha.undoText().endswith("espelhar")
        estado.pilha.undo()
        r = estado.impressao_atual.recorte
        assert (r.espelho_h, r.espelho_v, r.cx, r.angulo) == (recorte_antes.espelho_h, recorte_antes.espelho_v,
                                                                recorte_antes.cx, recorte_antes.angulo)

ed.espelhar(True)
ed.espelhar(True)              # duas vezes volta ao original
r = estado.impressao_atual.recorte
assert not r.espelho_h and not r.espelho_v
assert ed.botao_espelhar.isEnabled()
ed.acao_espelhar_v.trigger()
r = estado.impressao_atual.recorte
assert r.espelho_v and not r.espelho_h
print("OK")
""", timeout=180)
    assert r.returncode == 0 and "OK" in r.stdout, r.stdout + r.stderr
