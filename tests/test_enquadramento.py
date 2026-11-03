"""Enquadramento: geometria do recorte (seção 5.1) e política do recorte automático pelos rostos (seção 5.2).

Os rostos são sintéticos, em coordenadas normalizadas, como o YuNet devolve: a caixa vai das sobrancelhas ao queixo
e os olhos ficam a ~40% da altura dela. A "cabeça inteira" é a caixa com +30% da altura para cima (cabelo).
"""

from __future__ import annotations

import math

import pytest

from revelador.enquadramento import (
    Retangulo,
    caixa_envolvente,
    girar_rostos,
    recorte_automatico,
    reencaixar,
    retangulo,
    tamanho_maximo,
    zoom_efetivo,
)
from revelador.projeto import Recorte, Rosto

RETRATO = 2 / 3     # 10x15 em pé
PAISAGEM = 3 / 2    # 10x15 deitado
TOL = 1e-6


def rosto(cx: float, cy: float, w: float, h: float | None = None, confianca: float = 0.9,
          proporcao_imagem: float = 1.0) -> Rosto:
    """Rosto centrado em (cx, cy), normalizado. ``h`` padrão: rosto 1:1,2 em px na imagem dada."""
    if h is None:
        h = w * 1.2 * proporcao_imagem
    x, y = cx - w / 2, cy - h / 2
    olho_y = y + 0.4 * h
    return Rosto(x=x, y=y, w=w, h=h, olhos=((x + 0.3 * w, olho_y), (x + 0.7 * w, olho_y)), confianca=confianca)


def caixa_px(rec: Recorte, W: float, H: float, r: float) -> tuple[float, float, float, float]:
    ret = retangulo(rec, W, H, r)
    assert ret.angulo == 0
    return ret.cx - ret.w / 2, ret.cy - ret.h / 2, ret.cx + ret.w / 2, ret.cy + ret.h / 2


def cabeca_px(r: Rosto, W: float, H: float) -> tuple[float, float, float, float]:
    """Cabeça inteira em px (cabelo incluído), limitada à imagem."""
    x0, y0 = r.x * W, (r.y - 0.3 * r.h) * H
    x1, y1 = (r.x + r.w) * W, (r.y + r.h) * H
    return max(0.0, x0), max(0.0, y0), min(W, x1), min(H, y1)


def dentro(interna, externa, tol: float = 1e-6) -> bool:
    return (interna[0] >= externa[0] - tol and interna[1] >= externa[1] - tol
            and interna[2] <= externa[2] + tol and interna[3] <= externa[3] + tol)


def confere_recorte(rec: Recorte, W: float, H: float, r: float) -> tuple[float, float, float, float]:
    """Asserções comuns: proporção exata, zoom 1, dentro da imagem e do maior tamanho possível."""
    assert rec.zoom == 1.0 and rec.angulo == 0.0 and rec.giro == 0
    c = caixa_px(rec, W, H, r)
    w, h = c[2] - c[0], c[3] - c[1]
    assert w / h == pytest.approx(r, rel=1e-12)
    assert dentro(c, (0, 0, W, H))
    assert w == pytest.approx(W, rel=1e-9) or h == pytest.approx(H, rel=1e-9)
    # o centro gravado já é o centro limitado: reabrir não move o recorte
    ret = retangulo(rec, W, H, r)
    assert (ret.cx / W, ret.cy / H) == pytest.approx((rec.cx, rec.cy), abs=1e-12)
    return c


# --- sem rosto ------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("rostos", [None, [], [Rosto(0.5, 0.5, 0.0, 0.0)]])
def test_sem_rosto_centraliza(rostos):
    rec = recorte_automatico(4000, 3000, RETRATO, rostos)
    assert rec == Recorte(cx=0.5, cy=0.5, zoom=1.0, angulo=0.0, giro=0, origem="centro")
    c = confere_recorte(rec, 4000, 3000, RETRATO)
    assert c == pytest.approx((1000, 0, 3000, 3000))


# --- um rosto -------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("cx", [0.2, 0.35, 0.5, 0.65, 0.8, 0.95])
def test_retrato_4x3_deitado_para_10x15_em_pe(cx):
    """Foto 4:3 deitada, uma pessoa: o 10x15 em pé usa a altura toda e fica centrado no rosto (se couber)."""
    W, H = 4000, 3000
    r = rosto(cx, 0.3, 0.1, proporcao_imagem=W / H)
    rec = recorte_automatico(W, H, RETRATO, [r])
    assert rec.origem == "auto"
    c = confere_recorte(rec, W, H, RETRATO)
    assert c[2] - c[0] == pytest.approx(2000) and c[3] - c[1] == pytest.approx(3000)
    assert dentro(cabeca_px(r, W, H), c)
    centro_rosto = cx * W
    # rosto principal no centro do recorte, a não ser que a borda da foto impeça
    esperado = min(max(centro_rosto, 1000), 3000)
    assert (c[0] + c[2]) / 2 == pytest.approx(esperado, abs=1e-6)


def test_linha_dos_olhos_a_um_terco_do_topo():
    """Foto em pé para papel deitado: há folga vertical, e os olhos vão a 1/3 do topo."""
    W, H = 3000, 4000
    r = rosto(0.5, 0.45, 0.1, proporcao_imagem=W / H)
    rec = recorte_automatico(W, H, PAISAGEM, [r])
    c = confere_recorte(rec, W, H, PAISAGEM)
    olhos_y = r.olhos[0][1] * H
    assert (olhos_y - c[1]) / (c[3] - c[1]) == pytest.approx(1 / 3, abs=1e-9)
    assert dentro(cabeca_px(r, W, H), c)


def test_cabeca_tem_prioridade_sobre_a_linha_dos_olhos():
    """Rosto grande: os olhos a 1/3 cortariam o cabelo; o topo da cabeça manda e o queixo continua dentro."""
    W, H = 3000, 4000
    r = rosto(0.5, 0.5, 0.25, h=0.2)    # 800 px de altura num recorte de 2000
    rec = recorte_automatico(W, H, PAISAGEM, [r])
    c = confere_recorte(rec, W, H, PAISAGEM)
    olhos_y = r.olhos[0][1] * H
    assert (olhos_y - c[1]) / (c[3] - c[1]) > 1 / 3   # os olhos descem para caber o cabelo
    topo_folgado = (r.y - 0.6 * r.h) * H
    assert c[1] <= topo_folgado + TOL
    assert dentro(cabeca_px(r, W, H), c)


@pytest.mark.parametrize("lado", ["esquerda", "direita", "topo", "base"])
def test_rosto_encostado_na_borda(lado):
    """Rosto cortado pela borda da foto: o recorte encosta na mesma borda e não corta mais nada da cabeça."""
    W, H = 3000, 3000
    r = {
        "esquerda": Rosto(0.0, 0.4, 0.08, 0.1, None, 0.9),
        "direita": Rosto(0.92, 0.4, 0.08, 0.1, None, 0.9),
        "topo": Rosto(0.45, 0.0, 0.1, 0.08, None, 0.9),
        "base": Rosto(0.45, 0.9, 0.1, 0.1, None, 0.9),
    }[lado]
    proporcao = PAISAGEM if lado in ("topo", "base") else RETRATO
    rec = recorte_automatico(W, H, proporcao, [r])
    c = confere_recorte(rec, W, H, proporcao)
    assert dentro(cabeca_px(r, W, H), c)
    if lado == "esquerda":
        assert c[0] == pytest.approx(0)
    elif lado == "direita":
        assert c[2] == pytest.approx(W)
    elif lado == "topo":
        assert c[1] == pytest.approx(0)
    else:
        assert c[3] == pytest.approx(H)


def test_selfie_com_rosto_grande():
    """Selfie em pé com o rosto ocupando 60% da largura: rosto inteiro e centrado no 10x15 em pé."""
    W, H = 3000, 4000
    r = rosto(0.5, 0.42, 0.6, h=0.5)
    rec = recorte_automatico(W, H, RETRATO, [r])
    c = confere_recorte(rec, W, H, RETRATO)
    assert dentro(cabeca_px(r, W, H), c)
    assert (c[0] + c[2]) / 2 == pytest.approx(0.5 * W, abs=1e-6)


def test_selfie_rosto_maior_que_o_papel_prioriza_o_topo_da_cabeca():
    """Rosto mais alto que o recorte deitado: perde-se o queixo, nunca o topo da cabeça."""
    W, H = 4000, 3000
    r = rosto(0.45, 0.55, 0.4, h=0.75)      # 2250 px de altura; o recorte deitado tem 2667
    rec = recorte_automatico(W, H, PAISAGEM, [r])
    c = confere_recorte(rec, W, H, PAISAGEM)
    cab = cabeca_px(r, W, H)
    assert c[1] <= cab[1] + TOL                         # topo da cabeça dentro
    assert c[0] <= r.x * W and c[2] >= (r.x + r.w) * W  # laterais do rosto dentro
    assert c[3] - c[1] < (r.h * 1.35) * H              # não coube mesmo: algo do queixo/pescoço sai


def test_selfie_rosto_largo_demais_fica_centrado_no_rosto():
    """Rosto mais largo que o recorte em pé: centro no rosto (nariz no meio), topo da cabeça dentro."""
    W, H = 4000, 3000
    r = rosto(0.4, 0.5, 0.55, h=0.6)        # 2200 px de largura; o recorte em pé tem 2000
    rec = recorte_automatico(W, H, RETRATO, [r])
    c = confere_recorte(rec, W, H, RETRATO)
    assert (c[0] + c[2]) / 2 == pytest.approx(0.4 * W, abs=1e-6)
    assert c[1] <= cabeca_px(r, W, H)[1] + TOL


# --- vários rostos --------------------------------------------------------------------------------------------------

def test_grupo_em_linha_16x9_para_10x15_deitado():
    """Cinco pessoas em linha numa foto 16:9: todas as cabeças inteiras no 10x15 deitado (ninguém da ponta cortado)."""
    W, H = 1920, 1080
    rostos = [rosto(cx, 0.35, 0.08, proporcao_imagem=W / H) for cx in (0.14, 0.32, 0.5, 0.68, 0.86)]
    rec = recorte_automatico(W, H, PAISAGEM, rostos)
    c = confere_recorte(rec, W, H, PAISAGEM)
    for r in rostos:
        assert dentro(cabeca_px(r, W, H), c)


def test_grupo_largo_demais_descarta_as_pontas_e_nao_corta_ninguem_do_meio():
    """Sete pessoas de ponta a ponta: não cabem todas; saem as das pontas, e quem fica tem a cabeça inteira."""
    W, H = 1920, 1080
    centros = [0.05 + i * 0.15 for i in range(7)]   # 0.05 .. 0.95
    rostos = [rosto(cx, 0.35, 0.07, proporcao_imagem=W / H) for cx in centros]
    rec = recorte_automatico(W, H, PAISAGEM, rostos)
    c = confere_recorte(rec, W, H, PAISAGEM)
    inteiros = [dentro(cabeca_px(r, W, H), c) for r in rostos]
    assert all(inteiros[1:6])              # as cinco do meio inteiras
    assert (c[0] + c[2]) / 2 == pytest.approx(W / 2, abs=0.2 * W)


def test_crianca_pequena_e_adulto_grande():
    """Adulto perto e criança menor ao lado: os dois inteiros e o centro no meio dos dois (média simples, #36)."""
    W, H = 4000, 3000
    adulto = rosto(0.42, 0.3, 0.12, proporcao_imagem=W / H)
    crianca = rosto(0.58, 0.55, 0.05, proporcao_imagem=W / H)
    assert crianca.w * crianca.h / (adulto.w * adulto.h) >= 0.15   # é rosto principal
    rec = recorte_automatico(W, H, RETRATO, [crianca, adulto])
    c = confere_recorte(rec, W, H, RETRATO)
    assert dentro(cabeca_px(adulto, W, H), c)
    assert dentro(cabeca_px(crianca, W, H), c)
    assert (c[0] + c[2]) / 2 == pytest.approx(0.5 * W, abs=1e-6)   # o maior não puxa o recorte para si


def _centro_rosto(r: Rosto) -> float:
    return r.x + r.w / 2


def _media_ponderada(rostos: list[Rosto]) -> float:
    pesos = [r.w * r.h * r.confianca for r in rostos]
    return sum(_centro_rosto(r) * p for r, p in zip(rostos, pesos)) / sum(pesos)


def test_dois_rostos_de_tamanhos_diferentes_centram_na_media_simples():
    """Dois rostos principais de tamanhos bem diferentes: o centro horizontal é a média simples dos centros."""
    W, H = 4000, 3000
    rostos = [rosto(0.38, 0.32, 0.13, proporcao_imagem=W / H), rosto(0.60, 0.40, 0.06, proporcao_imagem=W / H)]
    rec = recorte_automatico(W, H, RETRATO, rostos)
    c = confere_recorte(rec, W, H, RETRATO)
    media = sum(_centro_rosto(r) for r in rostos) / 2
    assert (c[0] + c[2]) / 2 == pytest.approx(media * W, abs=1e-6)
    assert abs(media - _media_ponderada(rostos)) * W > 50     # a ponderação daria outro centro
    for r in rostos:
        assert dentro(cabeca_px(r, W, H), c)


def test_tres_rostos_de_tamanhos_diferentes_centram_na_media_simples():
    """Três rostos principais (grande, médio, pequeno): média simples dos três centros, cabeças inteiras."""
    W, H = 4000, 3000
    rostos = [rosto(0.40, 0.30, 0.10, proporcao_imagem=W / H),
              rosto(0.50, 0.36, 0.06, proporcao_imagem=W / H),
              rosto(0.62, 0.33, 0.08, proporcao_imagem=W / H)]
    rec = recorte_automatico(W, H, RETRATO, rostos)
    c = confere_recorte(rec, W, H, RETRATO)
    media = sum(_centro_rosto(r) for r in rostos) / 3
    assert (c[0] + c[2]) / 2 == pytest.approx(media * W, abs=1e-6)
    assert abs(media - _media_ponderada(rostos)) * W > 20
    for r in rostos:
        assert dentro(cabeca_px(r, W, H), c)


def test_media_simples_respeita_as_cabecas_inteiras():
    """Três rostos com a média puxada para um lado: o recorte sai da média só o necessário para caber as cabeças."""
    W, H = 1920, 1080
    rostos = [rosto(0.15, 0.35, 0.08, proporcao_imagem=W / H),
              rosto(0.30, 0.35, 0.08, proporcao_imagem=W / H),
              rosto(0.88, 0.35, 0.05, proporcao_imagem=W / H)]
    rec = recorte_automatico(W, H, PAISAGEM, rostos)
    c = confere_recorte(rec, W, H, PAISAGEM)
    for r in rostos:
        assert dentro(cabeca_px(r, W, H), c)
    media = sum(_centro_rosto(r) for r in rostos) / 3 * W
    assert (c[0] + c[2]) / 2 > media + 50                     # empurrado para a direita pela cabeça da ponta


def test_rosto_pequeno_ao_fundo_e_ignorado():
    """Gente pequena ao fundo (< 15% da importância do maior) não puxa o recorte: o adulto fica no centro."""
    W, H = 4000, 3000
    adulto = rosto(0.4, 0.3, 0.12, proporcao_imagem=W / H)
    fundo = rosto(0.9, 0.3, 0.03, proporcao_imagem=W / H)
    rec = recorte_automatico(W, H, RETRATO, [adulto, fundo])
    c = confere_recorte(rec, W, H, RETRATO)
    assert (c[0] + c[2]) / 2 == pytest.approx(0.4 * W, abs=1e-6)


@pytest.mark.parametrize("confianca,principal", [(0.98, True), (0.61, False)])
def test_confianca_pesa_na_importancia(confianca, principal):
    """A importância é área × confiança: um rosto pequeno e duvidoso fica abaixo do limite e não puxa o recorte;
    com confiança alta, o mesmo rosto é principal e entra na média."""
    W, H = 4000, 3000
    certo = rosto(0.40, 0.3, 0.1, confianca=0.98, proporcao_imagem=W / H)
    outro = rosto(0.62, 0.3, 0.045, confianca=confianca, proporcao_imagem=W / H)
    rec = recorte_automatico(W, H, RETRATO, [outro, certo])
    c = confere_recorte(rec, W, H, RETRATO)
    esperado = (0.40 + 0.62) / 2 if principal else 0.40
    assert (c[0] + c[2]) / 2 == pytest.approx(esperado * W, abs=1e-6)
    assert dentro(cabeca_px(certo, W, H), c)


def test_dois_rostos_que_nao_cabem_fica_o_mais_importante():
    """Duas pessoas nas pontas de uma foto deitada para papel em pé: fica a mais importante, inteira e centrada."""
    W, H = 4000, 3000
    maior = rosto(0.15, 0.3, 0.1, proporcao_imagem=W / H)
    menor = rosto(0.85, 0.3, 0.08, proporcao_imagem=W / H)
    rec = recorte_automatico(W, H, RETRATO, [menor, maior])
    c = confere_recorte(rec, W, H, RETRATO)
    assert dentro(cabeca_px(maior, W, H), c)
    assert c[0] == pytest.approx(0)   # 0.15 × 4000 = 600 < 1000: o mais centrado possível é encostar na borda


@pytest.mark.parametrize("cx", [0.1, 0.4, 0.75])
@pytest.mark.parametrize("proporcao", [PAISAGEM, RETRATO])
def test_panoramica_3x1(cx, proporcao):
    W, H = 6000, 2000
    r = rosto(cx, 0.35, 0.03, proporcao_imagem=W / H)
    rec = recorte_automatico(W, H, proporcao, [r])
    c = confere_recorte(rec, W, H, proporcao)
    assert c[3] - c[1] == pytest.approx(H)
    assert dentro(cabeca_px(r, W, H), c)
    w = c[2] - c[0]
    assert (c[0] + c[2]) / 2 == pytest.approx(min(max(cx * W, w / 2), W - w / 2), abs=1e-6)


@pytest.mark.parametrize("cx,cy", [(0.2, 0.3), (0.5, 0.5), (0.8, 0.7)])
@pytest.mark.parametrize("proporcao", [PAISAGEM, RETRATO, 1.0])
def test_foto_quadrada(cx, cy, proporcao):
    W = H = 3000
    r = rosto(cx, cy, 0.1)
    rec = recorte_automatico(W, H, proporcao, [r])
    c = confere_recorte(rec, W, H, proporcao)
    assert dentro(cabeca_px(r, W, H), c)


# --- margem de corte ------------------------------------------------------------------------------------------------

def test_margem_de_corte_afasta_os_rostos_da_borda_quando_ha_folga():
    """Dois rostos à esquerda puxam a média para lá e a criança encosta na borda direita; com a margem de corte da
    gráfica, ela sai de dentro da faixa que a guilhotina come."""
    W, H = 1920, 1080
    crianca = rosto(0.88, 0.35, 0.05, proporcao_imagem=W / H)
    rostos = [rosto(0.15, 0.35, 0.08, proporcao_imagem=W / H), rosto(0.30, 0.35, 0.08, proporcao_imagem=W / H),
              crianca]
    margem = 0.04
    margem_px = margem * H              # lado menor do recorte deitado = altura da foto
    sem = confere_recorte(recorte_automatico(W, H, PAISAGEM, rostos), W, H, PAISAGEM)
    com = confere_recorte(recorte_automatico(W, H, PAISAGEM, rostos, margem=margem), W, H, PAISAGEM)
    for c in (sem, com):
        for r in rostos:
            assert dentro(cabeca_px(r, W, H), c)
    assert sem[2] - (crianca.x + crianca.w) * W < margem_px          # sem margem, a criança fica na faixa
    for r in rostos:
        assert r.x * W - com[0] >= margem_px - TOL
        assert com[2] - (r.x + r.w) * W >= margem_px - TOL


def test_margem_sem_folga_nao_tira_ninguem():
    """Margem enorme que não cabe: ignorada, sem descartar rosto nem cortar cabeça."""
    W, H = 1920, 1080
    rostos = [rosto(cx, 0.35, 0.08, proporcao_imagem=W / H) for cx in (0.14, 0.5, 0.86)]
    c = confere_recorte(recorte_automatico(W, H, PAISAGEM, rostos, margem=0.3), W, H, PAISAGEM)
    for r in rostos:
        assert dentro(cabeca_px(r, W, H), c)


# --- giros ----------------------------------------------------------------------------------------------------------

def test_girar_rostos_ida_e_volta():
    r = rosto(0.3, 0.2, 0.1, h=0.15)
    for giro in range(4):
        g = girar_rostos(girar_rostos([r], giro), 4 - giro)[0]
        assert (g.x, g.y, g.w, g.h) == pytest.approx((r.x, r.y, r.w, r.h))
        assert sum(g.olhos, ()) == pytest.approx(sum(r.olhos, ()))
        assert g.confianca == r.confianca


def test_girar_rostos_90_horario():
    """Giro de 90° horário: o canto superior esquerdo vai para o superior direito; largura e altura trocam."""
    r = Rosto(0.1, 0.2, 0.3, 0.4, ((0.15, 0.3), (0.35, 0.3)), 0.8)
    g = girar_rostos([r], 1)[0]
    assert (g.x, g.y, g.w, g.h) == pytest.approx((1 - 0.2 - 0.4, 0.1, 0.4, 0.3))
    assert sum(g.olhos, ()) == pytest.approx((0.7, 0.15, 0.7, 0.35))
    g2 = girar_rostos([r], 2)[0]
    assert (g2.x, g2.y, g2.w, g2.h) == pytest.approx((0.6, 0.4, 0.3, 0.4))
    assert girar_rostos([r], 5)[0] == g


@pytest.mark.parametrize("giro", [0, 1, 2, 3])
def test_recorte_automatico_no_espaco_girado(giro):
    """Foto deitada girada: os rostos vão junto e a cabeça continua inteira no recorte da imagem girada."""
    W0, H0 = 4000, 3000
    r0 = rosto(0.7, 0.4, 0.1, proporcao_imagem=W0 / H0)
    W, H = (H0, W0) if giro % 2 else (W0, H0)
    r = girar_rostos([r0], giro)[0]
    rec = recorte_automatico(W, H, RETRATO, [r])
    c = confere_recorte(rec, W, H, RETRATO)
    assert dentro((r.x * W, r.y * H, (r.x + r.w) * W, (r.y + r.h) * H), c)


# --- geometria ------------------------------------------------------------------------------------------------------

def cantos(ret: Retangulo) -> list[tuple[float, float]]:
    t = math.radians(ret.angulo)
    c, s = math.cos(t), math.sin(t)
    pts = []
    for dx, dy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
        x, y = dx * ret.w / 2, dy * ret.h / 2
        pts.append((ret.cx + x * c - y * s, ret.cy + x * s + y * c))
    return pts


@pytest.mark.parametrize("W,H", [(4000, 3000), (3000, 4000), (6000, 2000), (2000, 2000), (101, 37)])
@pytest.mark.parametrize("proporcao", [RETRATO, PAISAGEM, 1.0, 0.8, 1.25, 3.0])
@pytest.mark.parametrize("angulo", [0.0, 1.0, -1.0, 15.0, -15.0, 45.0, -45.0])
@pytest.mark.parametrize("zoom", [1.0, 1.7, 4.0])
@pytest.mark.parametrize("cx,cy", [(0.5, 0.5), (0.0, 0.0), (1.0, 1.0), (-3.0, 0.2), (0.9, 7.0)])
def test_retangulo_sempre_dentro_e_na_proporcao(W, H, proporcao, angulo, zoom, cx, cy):
    ret = retangulo(Recorte(cx=cx, cy=cy, zoom=zoom, angulo=angulo, origem="manual"), W, H, proporcao)
    assert ret.w / ret.h == pytest.approx(proporcao, rel=1e-12)
    assert ret.angulo == angulo
    eps = 1e-6 * max(W, H)
    for x, y in cantos(ret):
        assert -eps <= x <= W + eps and -eps <= y <= H + eps
    bw, bh = caixa_envolvente(ret.w, ret.h, angulo)
    assert bw <= W + eps and bh <= H + eps
    # o zoom efetivo nunca é menor que o pedido
    assert zoom_efetivo(Recorte(cx=cx, cy=cy, zoom=zoom, angulo=angulo), W, H, proporcao) >= zoom - 1e-9


@pytest.mark.parametrize("angulo", [1.0, -15.0, 45.0])
def test_endireitar_usa_o_maior_recorte_que_cabe(angulo):
    """Com zoom 1, o recorte girado encosta na imagem (é o maior possível nesse ângulo)."""
    W, H = 4000, 3000
    ret = retangulo(Recorte(angulo=angulo), W, H, PAISAGEM)
    bw, bh = caixa_envolvente(ret.w, ret.h, angulo)
    assert bw == pytest.approx(W) or bh == pytest.approx(H)
    assert ret.w == pytest.approx(tamanho_maximo(W, H, PAISAGEM, angulo)[0])


def test_endireitar_pouco_nao_muda_a_escala_com_zoom():
    """Com zoom 3, girar 1° ainda cabe: a escala fica a mesma (sem pulos ao arrastar o endireitar)."""
    W, H = 4000, 3000
    reto = retangulo(Recorte(zoom=3.0), W, H, PAISAGEM)
    torto = retangulo(Recorte(zoom=3.0, angulo=1.0), W, H, PAISAGEM)
    assert torto.w == pytest.approx(reto.w)


def test_angulo_fora_da_faixa_e_limitado():
    assert retangulo(Recorte(angulo=80.0), 4000, 3000, PAISAGEM).angulo == 45.0
    assert retangulo(Recorte(angulo=-90.0), 4000, 3000, PAISAGEM).angulo == -45.0


def test_zoom_menor_que_um_vira_um():
    assert retangulo(Recorte(zoom=0.3), 4000, 3000, PAISAGEM) == retangulo(Recorte(), 4000, 3000, PAISAGEM)


def test_maior_recorte_sem_rotacao():
    assert tamanho_maximo(4000, 3000, RETRATO) == pytest.approx((2000, 3000))
    assert tamanho_maximo(4000, 3000, PAISAGEM) == pytest.approx((4000, 4000 / 1.5))
    assert tamanho_maximo(3000, 3000, 1.0) == pytest.approx((3000, 3000))
    with pytest.raises(ValueError):
        tamanho_maximo(0, 3000, 1.0)


# --- reencaixar -----------------------------------------------------------------------------------------------------

def test_reencaixar_mantem_centro_zoom_e_angulo_quando_cabe():
    rec = Recorte(cx=0.55, cy=0.45, zoom=2.0, angulo=3.0, giro=1, origem="manual")
    novo = reencaixar(rec, 3000, 4000, PAISAGEM)
    assert (novo.cx, novo.cy, novo.zoom, novo.angulo, novo.giro, novo.origem) == pytest.approx(
        (0.55, 0.45, 2.0, 3.0, 1, "manual"))


def test_reencaixar_limita_o_centro_na_nova_proporcao():
    """Recorte em pé encostado na direita; trocando para papel deitado (mais largo) o centro volta para dentro."""
    W, H = 4000, 3000
    rec = Recorte(cx=0.75, cy=0.5, zoom=1.0, origem="manual")
    assert retangulo(rec, W, H, RETRATO).cx == pytest.approx(3000)
    novo = reencaixar(rec, W, H, PAISAGEM)
    assert novo.cx == pytest.approx(0.5) and novo.origem == "manual"
    ret = retangulo(novo, W, H, PAISAGEM)
    assert ret.w / ret.h == pytest.approx(PAISAGEM)
    # reencaixar de novo não muda nada (idempotente)
    assert reencaixar(novo, W, H, PAISAGEM) == novo
