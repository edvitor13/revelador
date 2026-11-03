"""Contratos da fase B: recorte sugerido por impressão (puro) e o Estado compartilhado da interface."""

from __future__ import annotations

import pytest
from conftest import rodar_python

from revelador import tamanhos
from revelador.enquadramento import recorte_sugerido, retangulo
from revelador.projeto import Impressao, Recorte, Rosto


def test_sem_rostos_vai_ao_centro_e_mantem_o_giro():
    imp = Impressao(tamanho="10x15", recorte=Recorte(giro=1))
    r = recorte_sugerido(imp, 4000, 3000, None)
    assert (r.cx, r.cy, r.origem, r.giro) == (0.5, 0.5, "centro", 1)


@pytest.mark.parametrize("giro", [0, 1, 2, 3])
def test_proporcao_segue_a_imagem_girada(giro):
    imp = Impressao(tamanho="10x15", recorte=Recorte(giro=giro))
    W, H = (3000, 4000) if giro % 2 else (4000, 3000)   # 4000x3000 girado 90° fica em pé
    r = recorte_sugerido(imp, 4000, 3000, [Rosto(0.45, 0.3, 0.1, 0.13)])
    orient = tamanhos.orientacao_efetiva("auto", W, H)
    prop = tamanhos.proporcao("10x15", orient)
    ret = retangulo(r, W, H, prop)
    assert ret.w / ret.h == pytest.approx(prop, rel=1e-6)
    assert r.giro == giro and r.origem == "auto"


def test_rosto_na_ponta_continua_dentro():
    imp = Impressao(tamanho="10x15", orientacao="retrato")
    rosto = Rosto(0.85, 0.2, 0.08, 0.11)
    r = recorte_sugerido(imp, 4000, 3000, [rosto], margem_corte_mm=2.0)
    ret = retangulo(r, 4000, 3000, tamanhos.proporcao("10x15", "retrato"))
    esquerda, direita = ret.cx - ret.w / 2, ret.cx + ret.w / 2
    assert esquerda <= rosto.x * 4000 and (rosto.x + rosto.w) * 4000 <= direita


def test_estado_selecao_rostos_e_sinais():
    p = rodar_python("""
from datetime import datetime
from pathlib import Path
from revelador.imagem import InfoFoto
from revelador.projeto import Recorte, Rosto
from revelador.ui.estado import Estado

e = Estado()
ev = []
e.fotos_mudaram.connect(lambda: ev.append("fotos"))
e.foto_mudou.connect(lambda i: ev.append("foto"))
e.pedido_mudou.connect(lambda: ev.append("pedido"))
e.modificado_mudou.connect(lambda s: ev.append(f"mod={s}"))

novas = e.adicionar([Path("a.jpg"), Path("b.jpg"), Path("a.jpg")])
assert len(novas) == 2 and len(e.trabalho.fotos) == 2
assert e.adicionar([Path("A.JPG")]) == []          # mesmo arquivo (Windows não diferencia maiúsculas)
f = novas[0]

e.selecionar(f)                                    # sem metadados ainda: impressão criada, recorte padrão
assert f.selecionada and len(f.impressoes) == 1 and f.impressoes[0].tamanho == "10x15"
assert f.impressoes[0].recorte == Recorte()
e.definir_atual(f)
assert e.impressao_atual is f.impressoes[0] and e.indice_impressao == 0

e.definir_info(f.id, InfoFoto(4000, 3000, None, None, None, 123, 5_000_000_000))
assert f.bytes == 123 and f.mtime == 5.0
assert f.impressoes[0].recorte.origem == "centro"  # metadados chegaram, sem rostos: centro

e.definir_rostos(f.id, [Rosto(0.8, 0.2, 0.08, 0.11)])
assert f.impressoes[0].recorte.origem == "auto"   # paisagem 3:2 ocupa a largura toda: só o cy se move

f.impressoes[0].recorte = Recorte(cx=0.3, origem="manual")
e.definir_rostos(f.id, [Rosto(0.1, 0.2, 0.08, 0.11)])
assert f.impressoes[0].recorte.cx == 0.3           # manual nunca é refeito sozinho

e.selecionar(f, False)
assert not f.selecionada and len(f.impressoes) == 1  # desmarcar guarda as impressões
e.remover([f])
assert [x.id for x in e.trabalho.fotos] == [novas[1].id] and f.id not in e.info
assert "fotos" in ev and "pedido" in ev and "mod=True" in ev
print("ok")
""")
    assert p.returncode == 0, p.stderr
    assert p.stdout.strip().endswith("ok"), p.stdout


def test_vizinha_segue_a_ordem_publicada_pela_grade_e_lote_executa():
    p = rodar_python("""
from pathlib import Path
from revelador.projeto import Pasta, Trabalho
from revelador.ui.estado import Estado

e = Estado()
a, b, c = e.adicionar([Path("a.jpg"), Path("b.jpg"), Path("c.jpg")])
assert e.vizinha(1) is None                       # nada publicado ainda
e.definir_visiveis([a.id, c.id])                  # filtro: b escondida
assert e.vizinha(1) is a and e.vizinha(-1) is c   # sem atual: primeira / última
e.definir_atual(a)
assert e.vizinha(1) is c and e.vizinha(-1) is None and e.vizinha(2) is None
e.definir_atual(b)                                # atual fora do filtro
assert e.vizinha(1) is a
with e.lote("teste"):
    e.selecionar(a)
assert a.selecionada
assert Trabalho().pastas == [] and Pasta("p1", "Festa", "laranja").tamanho == "10x15"
print("ok")
""")
    assert p.returncode == 0, p.stderr
    assert p.stdout.strip().endswith("ok"), p.stdout
