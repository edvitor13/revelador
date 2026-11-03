"""Receita única: da foto (já orientada e em sRGB) à imagem do tamanho de destino (docs/ARQUITETURA.md, seção 6).

Puro (sem Qt, sem ``random``/``time``): a mesma entrada dá sempre a mesma saída. O editor mostra a prévia e a
exportação grava o arquivo pelo MESMO caminho, ``renderizar()``; quem chama só muda o tamanho de destino e a fonte
(o proxy ou o original: as coordenadas do ``Recorte`` são normalizadas, então os dois dão o mesmo recorte).

Passos de ``renderizar(fonte, impressao, ajustes, destino_px)``
---------------------------------------------------------------
1. **Giro de 90°** (``recorte.giro``, sentido horário): ``np.rot90``, sem perda.
2. **Recorte + endireitar + redimensionar numa transformação afim só** (modo *preencher*): ``enquadramento.retangulo``
   dá o retângulo (centro, tamanho, ângulo) na imagem girada e ``cv2.warpAffine`` amostra, do destino para a fonte,
   com ``INTER_LANCZOS4``. Quando a redução é grande, a região que interessa é reduzida antes com ``INTER_AREA``
   (sem serrilhado) até ficar com até ~1 px de fonte por px de destino.
3. **Ajustes** (``ajustes.aplicar``) já no tamanho de destino, com a escala em px por mm de papel (a nitidez).
4. **Modo *caber***: a foto inteira (só o giro; o ângulo não vale) centralizada sobre papel branco nos px exatos do
   destino; os ajustes valem só para a foto, não para a borda.

Convenção do ângulo: ``angulo > 0`` gira a FOTO no sentido horário no resultado (o retângulo do recorte gira no
sentido anti-horário sobre a imagem). ``matriz_destino_fonte()`` e ``poligono()`` são a única definição dessa
geometria: o editor desenha com elas o que a receita vai amostrar.

Quem chama (tamanhos de destino)
--------------------------------
- Editor: ``destino_na_caixa(impressao, largura, altura, caixa_w, caixa_h)`` (maior imagem com a proporção do papel
  dentro do visor) e ``renderizar(proxy, ...)``.
- Exportação: ``tamanho_exportacao(impressao, largura, altura, dpi)`` (px exatos do papel) e
  ``renderizar(carregar_fonte(caminho, "original"), ...)``.
``largura``/``altura`` são sempre as da imagem orientada SEM giro (``imagem.InfoFoto`` ou ``fonte.shape``).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from pathlib import Path

import cv2
import numpy as np

from . import ajustes as _ajustes
from . import enquadramento, imagem, tamanhos
from .enquadramento import Retangulo
from .projeto import Impressao

FONTES = ("proxy", "original")
MODO_CABER = "caber"
REDUCAO_MAXIMA = 1.0     # px de fonte por px de destino acima dos quais a região é reduzida antes (INTER_AREA)
RAIO_LANCZOS = 4         # px de folga ao redor da região amostrada (Lanczos de 4 lóbulos)


# ------------------------------------------------------------------------------------------------ fonte

def carregar_fonte(caminho: str | Path, fonte: str = "proxy") -> np.ndarray:
    """A imagem de partida: ``"proxy"`` (cópia reduzida, com cache, para a prévia) ou ``"original"`` (exportação).

    Ambas saem orientadas (EXIF) e em sRGB, float32 0..1, H×W×3. Não modifique o array devolvido.
    """
    if fonte == "proxy":
        return imagem.proxy(caminho)
    if fonte == "original":
        return imagem.carregar(caminho)
    raise ValueError(f"fonte desconhecida: {fonte!r} (use {FONTES})")


# ------------------------------------------------------------------------------------- papel e destino

def dimensoes_giradas(impressao: Impressao, largura: int, altura: int) -> tuple[int, int]:
    """``(W, H)`` da imagem depois do giro de 90° da impressão."""
    return (altura, largura) if int(impressao.recorte.giro) % 2 else (largura, altura)


def orientacao(impressao: Impressao, largura: int, altura: int) -> str:
    """``"retrato"`` ou ``"paisagem"`` da impressão ("auto" segue a imagem JÁ girada)."""
    W, H = dimensoes_giradas(impressao, largura, altura)
    return tamanhos.orientacao_efetiva(impressao.orientacao, W, H)


def proporcao(impressao: Impressao, largura: int, altura: int) -> float:
    """Largura ÷ altura do papel da impressão, na orientação dela."""
    return tamanhos.proporcao(impressao.tamanho, orientacao(impressao, largura, altura), impressao.papel_mm)


def papel_orientado_mm(impressao: Impressao, largura: int, altura: int) -> tuple[float, float]:
    """``(largura, altura)`` do papel em mm, na orientação da impressão."""
    menor, maior = tamanhos.papel_mm(impressao.tamanho, impressao.papel_mm)
    return (menor, maior) if orientacao(impressao, largura, altura) == "retrato" else (maior, menor)


def tamanho_exportacao(impressao: Impressao, largura: int, altura: int, dpi: int = 300) -> tuple[int, int]:
    """Pixels exatos do papel (``round(mm / 25,4 × dpi)``) na orientação da impressão: o destino da exportação."""
    return tamanhos.px(impressao.tamanho, orientacao(impressao, largura, altura), dpi, impressao.papel_mm)


def destino_na_caixa(impressao: Impressao, largura: int, altura: int, caixa_w: int, caixa_h: int) -> tuple[int, int]:
    """Maior ``(w, h)`` com a proporção do papel que cabe na caixa (o visor da prévia). Pelo menos 1×1."""
    prop = proporcao(impressao, largura, altura)
    caixa_w, caixa_h = max(1, int(caixa_w)), max(1, int(caixa_h))
    w = min(float(caixa_w), caixa_h * prop)
    return max(1, round(w)), max(1, min(caixa_h, round(w / prop)))


def escala_mm_px(impressao: Impressao, largura: int, altura: int, destino_w: int) -> float:
    """Pixels por mm de papel de uma imagem de destino com ``destino_w`` px de largura (para ``ajustes.aplicar``)."""
    return destino_w / papel_orientado_mm(impressao, largura, altura)[0]


def retangulo_da_impressao(impressao: Impressao, largura: int, altura: int) -> Retangulo:
    """O recorte da impressão em px da imagem girada ``W × H`` (sempre dentro dela e na proporção do papel)."""
    W, H = dimensoes_giradas(impressao, largura, altura)
    return enquadramento.retangulo(impressao.recorte, W, H, proporcao(impressao, largura, altura))


# ------------------------------------------------------------------------------------------- geometria

def _afim(a: float, b: float, c: float, d: float, tx: float, ty: float) -> np.ndarray:
    return np.array([[a, b, tx], [c, d, ty], [0.0, 0.0, 1.0]], dtype=np.float64)


def matriz_destino_fonte(ret: Retangulo, dw: float, dh: float) -> np.ndarray:
    """Matriz 3×3 (coordenadas contínuas: o px ``i`` ocupa ``[i, i+1]``) do destino ``dw × dh`` para a imagem girada.

    Leva o destino inteiro ao retângulo ``ret``: escala ``w/dw`` e ``h/dh``, giro de ``-angulo`` (a foto aparece
    girada ``+angulo`` no sentido horário) em torno do centro do recorte.
    """
    t = math.radians(-ret.angulo)
    c, s = math.cos(t), math.sin(t)
    sx, sy = ret.w / dw, ret.h / dh
    return _afim(1, 0, 0, 1, ret.cx, ret.cy) @ _afim(c, -s, s, c, 0, 0) @ _afim(sx, 0, 0, sy, 0, 0) \
        @ _afim(1, 0, 0, 1, -dw / 2, -dh / 2)


def poligono(ret: Retangulo) -> list[tuple[float, float]]:
    """Os 4 cantos do recorte na imagem girada (sentido horário a partir do canto superior esquerdo do papel)."""
    m = matriz_destino_fonte(ret, ret.w, ret.h)
    return [tuple(float(v) for v in (m @ np.array([x, y, 1.0]))[:2])
            for x, y in ((0, 0), (ret.w, 0), (ret.w, ret.h), (0, ret.h))]


def encolher(ret: Retangulo, margem: float) -> Retangulo:
    """O mesmo recorte menos ``margem`` px em cada lado (a margem de corte tracejada do editor)."""
    margem = max(0.0, min(margem, ret.w / 2 - 1e-6, ret.h / 2 - 1e-6))
    return Retangulo(ret.cx, ret.cy, ret.w - 2 * margem, ret.h - 2 * margem, ret.angulo)


# ------------------------------------------------------------------------------------------ renderizar

def girar(fonte: np.ndarray, giro: int) -> np.ndarray:
    """``giro`` × 90° no sentido horário, sem perda (visão do array, sem cópia)."""
    return np.rot90(fonte, -(int(giro) % 4))


def _redimensionar(img: np.ndarray, w: int, h: int) -> np.ndarray:
    if (img.shape[1], img.shape[0]) == (w, h):
        return np.ascontiguousarray(img)
    reduz = w < img.shape[1] or h < img.shape[0]
    return cv2.resize(np.ascontiguousarray(img), (w, h),
                      interpolation=cv2.INTER_AREA if reduz else cv2.INTER_LANCZOS4)


def _recortar(img: np.ndarray, ret: Retangulo, dw: int, dh: int) -> np.ndarray:
    """Amostra o retângulo ``ret`` da imagem girada ``img`` num destino ``dw × dh`` (passo 2 da receita)."""
    H, W = img.shape[:2]
    a = matriz_destino_fonte(ret, dw, dh)
    cantos = a @ np.array([(0, 0, 1), (dw, 0, 1), (dw, dh, 1), (0, dh, 1)], dtype=np.float64).T
    passo = max(ret.w / dw, ret.h / dh)                    # px de fonte por px de destino
    folga = RAIO_LANCZOS * max(1.0, passo) + 2
    x0 = max(0, math.floor(cantos[0].min() - folga))
    x1 = min(W, math.ceil(cantos[0].max() + folga))
    y0 = max(0, math.floor(cantos[1].min() - folga))
    y1 = min(H, math.ceil(cantos[1].max() + folga))
    regiao = np.ascontiguousarray(img[y0:y1, x0:x1])
    qx = qy = 1.0
    if passo > REDUCAO_MAXIMA:                             # reduz antes (INTER_AREA) para não serrilhar
        q = REDUCAO_MAXIMA / passo
        nw, nh = max(1, round(regiao.shape[1] * q)), max(1, round(regiao.shape[0] * q))
        regiao = cv2.resize(regiao, (nw, nh), interpolation=cv2.INTER_AREA)
        qx, qy = nw / (x1 - x0), nh / (y1 - y0)
    b = _afim(qx, 0, 0, qy, 0, 0) @ _afim(1, 0, 0, 1, -x0, -y0) @ a
    m = _afim(1, 0, 0, 1, -0.5, -0.5) @ b @ _afim(1, 0, 0, 1, 0.5, 0.5)    # centros dos px: índice = contínuo - 0,5
    saida = cv2.warpAffine(regiao, m[:2], (dw, dh), flags=cv2.INTER_LANCZOS4 | cv2.WARP_INVERSE_MAP,
                           borderMode=cv2.BORDER_REPLICATE)
    return np.clip(saida, 0.0, 1.0, out=saida)


def renderizar(fonte: np.ndarray, impressao: Impressao, ajustes: dict | None,
               destino_px: tuple[int, int]) -> np.ndarray:
    """A receita única: ``fonte`` (float32 0..1, H×W×3, sRGB, orientada, SEM giro) → float32 0..1 ``destino_px``.

    ``destino_px = (largura, altura)`` exatos da saída: o visor (prévia, ver ``destino_na_caixa``) ou o papel
    (exportação, ver ``tamanho_exportacao``). No modo *preencher* a proporção do destino deve ser a do papel (o
    recorte é esticado para preenchê-lo, então uma diferença de 1 px de arredondamento é invisível). ``ajustes`` são
    os da foto (``{}``/``None`` = nenhum). Determinística; não modifica ``fonte``.
    """
    dw, dh = int(destino_px[0]), int(destino_px[1])
    if dw < 1 or dh < 1:
        raise ValueError(f"destino inválido: {destino_px}")
    fonte = np.asarray(fonte, dtype=np.float32)
    if fonte.ndim != 3 or fonte.shape[2] != 3 or fonte.shape[0] < 1 or fonte.shape[1] < 1:
        raise ValueError(f"a fonte precisa ser H×W×3, veio {fonte.shape}")
    altura, largura = fonte.shape[:2]
    img = girar(fonte, impressao.recorte.giro)
    escala = escala_mm_px(impressao, largura, altura, dw)

    if impressao.modo == MODO_CABER:
        return _caber(img, ajustes, dw, dh, escala)
    ret = retangulo_da_impressao(impressao, largura, altura)
    saida = _recortar(img, ret, dw, dh)
    return _ajustes.aplicar(saida, ajustes, escala) if _ajustes.sanitizar(ajustes) else saida


def _caber(img: np.ndarray, ajustes: dict | None, dw: int, dh: int, escala: float) -> np.ndarray:
    """Modo *caber*: a foto inteira, centralizada sobre branco, nos px exatos do destino."""
    H, W = img.shape[:2]
    k = min(dw / W, dh / H)
    pw, ph = min(dw, max(1, round(W * k))), min(dh, max(1, round(H * k)))
    foto = _redimensionar(img, pw, ph)
    if _ajustes.sanitizar(ajustes):
        foto = _ajustes.aplicar(foto, ajustes, escala)
    saida = np.ones((dh, dw, 3), dtype=np.float32)
    x, y = (dw - pw) // 2, (dh - ph) // 2
    saida[y:y + ph, x:x + pw] = np.clip(foto, 0.0, 1.0)
    return saida


def para_uint8(img: np.ndarray) -> np.ndarray:
    """float32 0..1 → ``uint8`` por arredondamento simples (determinístico): tela e JPEG da exportação."""
    return np.clip(np.floor(np.asarray(img, dtype=np.float32) * 255.0 + 0.5), 0, 255).astype(np.uint8)


def ponto_da_fonte(ret: Retangulo, destino: Sequence[float], u: float, v: float) -> tuple[float, float]:
    """Onde o ponto ``(u, v)`` (contínuo) do destino cai na imagem girada: o inverso do que o editor mostra."""
    x, y, _ = matriz_destino_fonte(ret, destino[0], destino[1]) @ np.array([u, v, 1.0])
    return float(x), float(y)
