"""Receita única (``receita.py``): tamanho exato, proporção, geometria, prévia ≈ exportação, modo caber."""

from __future__ import annotations

import math

import cv2
import numpy as np
import pytest

from revelador import ajustes, enquadramento, receita, tamanhos
from revelador.projeto import Impressao, Recorte

MARCA = np.array([1.0, 0.0, 1.0], dtype=np.float32)   # magenta: não existe no fundo cinza


def fundo(largura: int, altura: int, valor: float = 0.5) -> np.ndarray:
    return np.full((altura, largura, 3), valor, dtype=np.float32)


def com_marca(img: np.ndarray, fx: float, fy: float, lado: int = 6) -> np.ndarray:
    """Cópia com um quadrado magenta centrado na posição normalizada (fx, fy)."""
    img = img.copy()
    h, w = img.shape[:2]
    x, y = round(fx * w), round(fy * h)
    img[max(0, y - lado // 2):y + lado // 2, max(0, x - lado // 2):x + lado // 2] = MARCA
    return img


def centro_da_marca(img: np.ndarray) -> tuple[float, float]:
    """Centro (px, contínuo) dos pixels magenta."""
    m = (img[..., 0] > 0.8) & (img[..., 1] < 0.3) & (img[..., 2] > 0.8)
    assert m.sum() > 0, "marca não encontrada"
    ys, xs = np.nonzero(m)
    return float(xs.mean() + 0.5), float(ys.mean() + 0.5)


def imp(tamanho: str = "10x15", **kw) -> Impressao:
    recorte = kw.pop("recorte", Recorte())
    return Impressao(tamanho=tamanho, recorte=recorte, **kw)


def textura(largura: int, altura: int) -> np.ndarray:
    """Imagem determinística com gradiente, círculos e ruído fino (para comparar prévia e exportação)."""
    rng = np.random.default_rng(7)
    y, x = np.mgrid[0:altura, 0:largura].astype(np.float32)
    img = np.stack([x / largura, y / altura, 0.5 + 0.4 * np.sin((x + y) / 90.0)], axis=-1)
    for cx, cy, r, cor in ((0.3, 0.4, 0.15, (0.9, 0.2, 0.1)), (0.7, 0.6, 0.2, (0.1, 0.7, 0.3))):
        d = np.hypot(x - cx * largura, y - cy * altura)
        img[d < r * altura] = cor
    img += rng.normal(0, 0.03, img.shape).astype(np.float32)
    return np.clip(img, 0, 1).astype(np.float32)


# ------------------------------------------------------------------------------------- tamanho e proporção

@pytest.mark.parametrize("tamanho", ["9x13", "10x15", "a4", "20x30", "10x10", "15x15"])
@pytest.mark.parametrize("orient", ["retrato", "paisagem", "auto"])
@pytest.mark.parametrize("dpi", [72, 150])
@pytest.mark.parametrize("modo", ["preencher", "caber"])
def test_saida_tem_os_px_exatos_do_papel(tamanho, orient, dpi, modo):
    fonte = textura(300, 200)
    i = imp(tamanho, orientacao=orient, modo=modo)
    destino = receita.tamanho_exportacao(i, 300, 200, dpi)
    esperado = tamanhos.px(tamanho, receita.orientacao(i, 300, 200), dpi)
    assert destino == esperado
    saida = receita.renderizar(fonte, i, {}, destino)
    assert saida.shape == (destino[1], destino[0], 3)
    assert saida.dtype == np.float32
    assert 0.0 <= saida.min() and saida.max() <= 1.0


def test_tamanho_exportacao_a_300_dpi_e_personalizado():
    i = imp("10x15", orientacao="paisagem")
    assert receita.tamanho_exportacao(i, 300, 200, 300) == (1800, 1200)
    saida = receita.renderizar(textura(300, 200), i, None, (1800, 1200))
    assert saida.shape == (1200, 1800, 3)
    p = imp("personalizado", papel_mm=(100.0, 250.0))
    assert receita.tamanho_exportacao(p, 200, 300, 254) == (1000, 2500)


@pytest.mark.parametrize("giro", [0, 1, 2, 3])
@pytest.mark.parametrize("tamanho", ["10x15", "a4", "10x10"])
def test_retangulo_tem_a_proporcao_do_papel_e_fica_dentro(giro, tamanho):
    for zoom in (1.0, 1.7, 4.0):
        for angulo in (-45.0, -12.5, 0.0, 3.3, 45.0):
            for cx, cy in ((0.0, 0.0), (0.5, 0.5), (1.0, 0.2), (0.9, 1.0)):
                i = imp(tamanho, recorte=Recorte(cx=cx, cy=cy, zoom=zoom, angulo=angulo, giro=giro))
                W, H = receita.dimensoes_giradas(i, 4000, 3000)
                ret = receita.retangulo_da_impressao(i, 4000, 3000)
                assert ret.w / ret.h == pytest.approx(receita.proporcao(i, 4000, 3000), rel=1e-9)
                for x, y in receita.poligono(ret):
                    assert -1e-6 <= x <= W + 1e-6 and -1e-6 <= y <= H + 1e-6


# ----------------------------------------------------------------------------------------- geometria

@pytest.mark.parametrize("giro", [0, 1, 2, 3])
def test_marcador_no_lugar_certo_com_giro(giro):
    # 300×200 num papel 100×150 mm (paisagem 3:2; com giro ímpar, a imagem é retrato 2:3 e o papel acompanha).
    fonte = com_marca(fundo(300, 200), 0.2, 0.3)
    i = imp("personalizado", papel_mm=(100.0, 150.0), recorte=Recorte(giro=giro))
    destino = receita.tamanho_exportacao(i, 300, 200, 50.8)        # 200×300 ou 300×200
    saida = receita.renderizar(fonte, i, None, destino)
    # Onde a marca deve cair: a mesma posição normalizada depois de girar o ponto no sentido horário.
    fx, fy = 0.2, 0.3
    for _ in range(giro):
        fx, fy = 1.0 - fy, fx
    x, y = centro_da_marca(saida)
    assert x / destino[0] == pytest.approx(fx, abs=0.01)
    assert y / destino[1] == pytest.approx(fy, abs=0.01)


def test_giro_horario_leva_o_canto_superior_esquerdo_para_o_superior_direito():
    fonte = com_marca(fundo(300, 200), 0.1, 0.1)
    i = imp("personalizado", papel_mm=(100.0, 150.0), recorte=Recorte(giro=1))
    x, y = centro_da_marca(receita.renderizar(fonte, i, None, (200, 300)))
    assert x > 150 and y < 50


@pytest.mark.parametrize("cx,cy,zoom", [(0.5, 0.5, 1.0), (0.3, 0.6, 2.0), (0.8, 0.25, 3.0), (0.05, 0.95, 1.5)])
def test_marcador_com_zoom_e_centro(cx, cy, zoom):
    fonte = com_marca(fundo(800, 600), cx, cy, lado=8)
    i = imp("10x15", orientacao="paisagem", recorte=Recorte(cx=cx, cy=cy, zoom=zoom))
    destino = (600, 400)
    ret = receita.retangulo_da_impressao(i, 800, 600)
    saida = receita.renderizar(fonte, i, None, destino)
    # A posição esperada da marca no destino vem direto da geometria do recorte (ponto da fonte -> destino).
    esperado = (destino[0] * (cx * 800 - (ret.cx - ret.w / 2)) / ret.w,
                destino[1] * (cy * 600 - (ret.cy - ret.h / 2)) / ret.h)
    if 0 < esperado[0] < destino[0] and 0 < esperado[1] < destino[1]:
        x, y = centro_da_marca(saida)
        assert x == pytest.approx(esperado[0], abs=1.5)
        assert y == pytest.approx(esperado[1], abs=1.5)
    if (cx, cy) == (0.3, 0.6):       # recorte centrado na marca: ela fica no meio do destino
        x, y = centro_da_marca(saida)
        assert (x, y) == (pytest.approx(300, abs=1.5), pytest.approx(200, abs=1.5))


@pytest.mark.parametrize("angulo", [-30.0, 10.0, 25.0])
def test_convencao_do_angulo_foto_gira_no_sentido_horario(angulo):
    # Marca 60 px à direita do centro da imagem; o recorte é centrado nela.
    fonte = com_marca(fundo(800, 600), 0.5 + 60 / 800, 0.5, lado=8)
    i = imp("10x15", orientacao="paisagem", recorte=Recorte(zoom=1.5, angulo=angulo))
    ret = receita.retangulo_da_impressao(i, 800, 600)
    destino = (600, 400)
    escala = destino[0] / ret.w
    x, y = centro_da_marca(receita.renderizar(fonte, i, None, destino))
    t = math.radians(angulo)
    assert x == pytest.approx(destino[0] / 2 + 60 * math.cos(t) * escala, abs=2.0)
    assert y == pytest.approx(destino[1] / 2 + 60 * math.sin(t) * escala, abs=2.0)


@pytest.mark.parametrize("angulo", [-45.0, -20.0, 7.5, 33.0, 45.0])
@pytest.mark.parametrize("zoom", [1.0, 2.5])
def test_com_angulo_nenhum_pixel_de_fora_da_imagem(angulo, zoom):
    # Imagem toda cinza (0,6): preto/borda replicada de fora apareceria como outro valor (e o polígono sai dos limites).
    fonte = fundo(500, 350, 0.6)
    for cx, cy in ((0.5, 0.5), (0.0, 0.0), (1.0, 1.0)):
        i = imp("10x15", recorte=Recorte(cx=cx, cy=cy, zoom=zoom, angulo=angulo))
        saida = receita.renderizar(fonte, i, None, receita.tamanho_exportacao(i, 500, 350, 60))
        assert saida.min() > 0.599 and saida.max() < 0.601
        W, H = receita.dimensoes_giradas(i, 500, 350)
        for x, y in receita.poligono(receita.retangulo_da_impressao(i, 500, 350)):
            assert -1e-6 <= x <= W + 1e-6 and -1e-6 <= y <= H + 1e-6


# ------------------------------------------------------------------------- prévia ≈ exportação, proxy ≈ original

def _diferenca_media(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.abs(a - b).mean())


@pytest.mark.parametrize("recorte", [
    Recorte(),
    Recorte(cx=0.4, cy=0.55, zoom=1.8),
    Recorte(cx=0.5, cy=0.5, zoom=1.3, angulo=12.0),
    Recorte(cx=0.6, cy=0.4, zoom=1.0, angulo=-25.0, giro=1),
])
def test_previa_pequena_e_parecida_com_a_exportacao_reduzida(recorte, capsys):
    fonte = textura(2400, 1600)
    i = imp("10x15", recorte=recorte)
    grande = receita.tamanho_exportacao(i, 2400, 1600, 300)
    pequeno = (grande[0] // 6, grande[1] // 6)
    a = receita.renderizar(fonte, i, None, grande)
    reduzida = cv2.resize(a, pequeno, interpolation=cv2.INTER_AREA)
    b = receita.renderizar(fonte, i, None, pequeno)
    dif = _diferenca_media(reduzida, b)
    with capsys.disabled():
        print(f"\n[previa x exportacao] giro={recorte.giro} angulo={recorte.angulo} zoom={recorte.zoom}: "
              f"diferenca media {dif:.5f}")
    assert dif < 0.02


def test_previa_com_ajustes_parecida_com_exportacao():
    fonte = textura(2400, 1600)
    aj = {"exposicao": 20, "contraste": 25, "saturacao": 30, "sombras": 40, "nitidez": 50}
    i = imp("10x15", orientacao="paisagem", recorte=Recorte(cx=0.45, zoom=1.4, angulo=5.0))
    grande = receita.tamanho_exportacao(i, 2400, 1600, 300)
    pequeno = (grande[0] // 5, grande[1] // 5)
    reduzida = cv2.resize(receita.renderizar(fonte, i, aj, grande), pequeno, interpolation=cv2.INTER_AREA)
    assert _diferenca_media(reduzida, receita.renderizar(fonte, i, aj, pequeno)) < 0.03


def test_proxy_e_original_dao_o_mesmo_recorte():
    fonte = textura(2400, 1600)
    proxy = cv2.resize(fonte, (600, 400), interpolation=cv2.INTER_AREA)
    i = imp("10x15", recorte=Recorte(cx=0.4, cy=0.55, zoom=1.5, angulo=10.0, giro=3))
    destino = (200, 300)
    dif = _diferenca_media(receita.renderizar(fonte, i, None, destino), receita.renderizar(proxy, i, None, destino))
    assert dif < 0.02


# --------------------------------------------------------------------------------------------- caber

def test_modo_caber_foto_inteira_com_borda_branca():
    fonte = com_marca(fundo(300, 200, 0.4), 0.0, 0.0, lado=8)
    fonte[-1, -1] = MARCA
    i = imp("10x15", orientacao="retrato", modo="caber")
    destino = receita.tamanho_exportacao(i, 300, 200, 50)     # 200×300
    saida = receita.renderizar(fonte, i, None, destino)
    assert saida.shape == (300, 200, 3)
    # Foto 3:2 em papel 2:3: ocupa a largura toda (200×133) no meio; o resto é branco puro.
    topo = (300 - 133) // 2
    assert np.all(saida[:topo - 1] == 1.0) and np.all(saida[topo + 134:] == 1.0)
    miolo = saida[topo + 2:topo + 130, 4:-4]
    assert abs(float(miolo[40:80, 40:120].mean()) - 0.4) < 0.01       # a foto, sem corte
    esperada = cv2.resize(fonte, (200, 133), interpolation=cv2.INTER_AREA)
    assert _diferenca_media(saida[topo:topo + 133], esperada) < 0.03


def test_modo_caber_ajustes_nao_mexem_na_borda():
    fonte = fundo(300, 200, 0.4)
    i = imp("10x15", orientacao="retrato", modo="caber")
    saida = receita.renderizar(fonte, i, {"exposicao": -60, "contraste": 50}, (200, 300))
    assert np.all(saida[:10] == 1.0)
    assert saida[150, 100, 0] < 0.4


def test_modo_caber_respeita_o_giro():
    fonte = com_marca(fundo(300, 200), 0.1, 0.1)
    i = imp("10x15", orientacao="paisagem", modo="caber", recorte=Recorte(giro=1))
    destino = (300, 200)         # foto girada (200×300) cabe pela altura: 133×200 centrada
    saida = receita.renderizar(fonte, i, None, destino)
    x, y = centro_da_marca(saida)
    assert x > 150 + 33 and y < 40
    assert np.all(saida[:, :80] == 1.0)


# ------------------------------------------------------------------------------ neutro e determinismo

def test_ajustes_neutros_nao_alteram_nada():
    fonte = textura(600, 400)
    i = imp("10x15", orientacao="paisagem", recorte=Recorte(zoom=1.2, angulo=4.0))
    base = receita.renderizar(fonte, i, None, (300, 200))
    for neutro in ({}, {"exposicao": 0, "contraste": 0.0, "nitidez": 0}, {"desconhecido": 50}):
        assert np.array_equal(base, receita.renderizar(fonte, i, neutro, (300, 200)))
    assert not np.array_equal(base, receita.renderizar(fonte, i, {"exposicao": 30}, (300, 200)))


def test_ajustes_aplicados_no_tamanho_de_destino():
    fonte = textura(600, 400)
    i = imp("10x15", orientacao="paisagem")
    sem = receita.renderizar(fonte, i, None, (300, 200))
    esperado = ajustes.aplicar(sem, {"exposicao": 30}, receita.escala_mm_px(i, 600, 400, 300))
    assert np.array_equal(receita.renderizar(fonte, i, {"exposicao": 30}, (300, 200)), esperado)


def test_deterministico_e_nao_modifica_a_fonte():
    fonte = textura(800, 600)
    copia = fonte.copy()
    i = imp("10x15", recorte=Recorte(cx=0.3, zoom=2.0, angulo=-8.0, giro=2))
    a = receita.renderizar(fonte, i, {"contraste": 20}, (300, 450))
    b = receita.renderizar(fonte, i, {"contraste": 20}, (300, 450))
    assert np.array_equal(a, b) and np.array_equal(fonte, copia)


def test_fonte_somente_leitura_funciona():
    fonte = textura(400, 300)
    fonte.flags.writeable = False
    receita.renderizar(fonte, imp("10x15"), None, (100, 150))


def test_destino_na_caixa_mantem_a_proporcao():
    i = imp("10x15", orientacao="paisagem")
    for caixa in ((800, 600), (300, 900), (1, 1), (1000, 100)):
        w, h = receita.destino_na_caixa(i, 300, 200, *caixa)
        assert 1 <= w <= max(1, caixa[0]) and 1 <= h <= max(1, caixa[1])
        if min(caixa) > 50:
            assert w / h == pytest.approx(1.5, rel=0.02)
    assert receita.destino_na_caixa(i, 300, 200, 800, 600) == (800, 533)


def test_destino_invalido_e_fonte_invalida():
    with pytest.raises(ValueError):
        receita.renderizar(fundo(10, 10), imp(), None, (0, 10))
    with pytest.raises(ValueError):
        receita.renderizar(np.zeros((10, 10), dtype=np.float32), imp(), None, (10, 10))
    with pytest.raises(ValueError):
        receita.carregar_fonte("x.jpg", "outra")


def test_carregar_fonte_proxy_e_original(tmp_path):
    from PIL import Image
    Image.new("RGB", (400, 300), (10, 200, 30)).save(tmp_path / "a.png")
    original = receita.carregar_fonte(tmp_path / "a.png", "original")
    proxy = receita.carregar_fonte(tmp_path / "a.png", "proxy")
    assert original.shape == (300, 400, 3) and proxy.dtype == np.float32
    i = imp("10x15", orientacao="paisagem")
    assert receita.tamanho_exportacao(i, 400, 300, 300) == (1800, 1200)


def test_retangulo_e_o_do_enquadramento():
    i = imp("10x15", recorte=Recorte(cx=0.3, cy=0.7, zoom=1.9, angulo=14.0, giro=1))
    W, H = receita.dimensoes_giradas(i, 4000, 3000)
    assert (W, H) == (3000, 4000)
    esperado = enquadramento.retangulo(i.recorte, W, H, receita.proporcao(i, 4000, 3000))
    assert receita.retangulo_da_impressao(i, 4000, 3000) == esperado
