"""Ajustes de luz e cor: esquema (``PARAMS``) e ``aplicar()`` (puro, numpy).

``aplicar(rgb, valores, escala_mm_px=None)`` recebe float32 H×W×3, sRGB, 0..1, e devolve outro array (a entrada
nunca é modificada). Sem estado, sem ``random``/``time``: mesma entrada, mesma saída, bit a bit. Todos os valores no
padrão (ou ``{}``) devolvem uma cópia idêntica. Toda distância é relativa ao tamanho da imagem de destino (fração
do lado menor) ou em mm de papel convertidos por ``escala_mm_px``, então a prévia pequena e a exportação grande
ficam iguais (a receita aplica os ajustes no tamanho final).

Fórmulas (ordem fixa; ``v`` = valor do controle, ``t = v/100``)
---------------------------------------------------------------
Os valores não são cortados no meio do caminho (curvas suaves e definidas fora de 0..1); só o resultado final é
limitado a 0..1. Antes de entrar em luz linear ou OKLab, valores negativos viram 0.

1. **Temperatura e matiz** (luz linear). Ganhos ``gR = 2^(+0,4·t_temp)``, ``gB = 2^(-0,4·t_temp)``,
   ``gG = 2^(-0,3·t_matiz)`` (matiz positivo = magenta). Os três ganhos são divididos por
   ``0,2126·gR + 0,7152·gG + 0,0722·gB``, para o branco manter a luminância.
2. **Exposição** (luz linear). ``× 2^(v/50)`` (±2 EV). Junta-se ao passo 1 numa só multiplicação.
3. **Brancos e pretos** (sRGB, ``x`` = valor limitado a 0..1 só dentro do peso):
   ``y = y + 0,2·t_brancos·x²`` e ``y = y + 0,15·t_pretos·(1-x)²`` (positivo clareia as luzes/os pretos).
4. **Realces e sombras**. Luminância ``Y = 0,2126R + 0,7152G + 0,0722B`` (sRGB). Guia
   ``G = 0,75·desfoque(Y) + 0,25·Y``, com desfoque gaussiano de sigma = 2% do lado menor (calculado numa cópia
   reduzida a sigma ≈ 4 px e ampliada, igual em qualquer resolução). Máscaras
   ``Mr = smoothstep(0,45; 1; G)`` e ``Ms = 1 - smoothstep(0; 0,55; G)``.
   Realces: ``RGB × (1 + 0,4·t_realces·Mr)``. Sombras: ``RGB^(1 - 0,6·t_sombras·Ms)`` por canal (o expoente é 1
   fora da máscara, então não mexe nas luzes).
5. **Contraste**: ``y = x + t·x(1-x)(2x-1)`` com ``x`` limitado a 0..1 (S suave em torno de 0,5; preserva 0 e 1;
   monótona nos dois sentidos).
6. **Saturação e vibração** (OKLab, ``C = hypot(a, b)``; ``a`` e ``b`` multiplicados por ``F = Fs·Fv``).
   ``Fs = 1 + t_sat`` (−100 = tons de cinza). Vibração: ``p = (1 - min(C/0,3; 1))²`` (cores pouco saturadas pesam
   mais) e ``pele = ((1 + cos(h - 55°))/2)^8`` (cos do ângulo entre o matiz e o de pele, sem calcular ângulo);
   ``Fv = 1 + t_vib·p·(1 - 0,75·pele)`` se positivo; negativo: ``Fv = 1 + t_vib·(0,3 + 0,7·(1-p))·(1 - 0,75·pele)``.
7. **Nitidez** (OKLab ``L``): máscara de nitidez ``L' = L + 1,5·t_nit·d·d²/(d²+0,01²)`` com
   ``d = L - gaussiana(L)``; sigma = 0,1 mm × ``escala_mm_px`` (px por mm da imagem de destino). Sem
   ``escala_mm_px``, usa o equivalente a 300 dpi de um 10×15 relativo ao lado menor (lado menor = 100 mm →
   sigma = lado menor / 1000 px). O termo ``d²/(d²+0,01²)`` é o limiar suave contra ruído.

Luz linear = sRGB decodificado; os passos 6 e 7 compartilham uma só ida e volta a OKLab. O resultado volta a sRGB
e é limitado a 0..1.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .i18n import N_

GRUPO_LUZ = N_("Luz")
GRUPO_COR = N_("Cor")
GRUPO_DETALHE = N_("Detalhe")
GRUPOS = (GRUPO_LUZ, GRUPO_COR, GRUPO_DETALHE)


@dataclass(frozen=True)
class Param:
    """Um ajuste do painel lateral. A ``chave`` nunca muda (ela vai para o ``.revelador``)."""

    chave: str
    nome: str
    minimo: float
    maximo: float
    padrao: float
    grupo: str
    passo: float = 1.0


# Na ordem do painel (a ordem de aplicação é outra e fica fixa em aplicar()).
PARAMS: tuple[Param, ...] = (
    Param("exposicao", N_("Exposição"), -100, 100, 0, GRUPO_LUZ),
    Param("contraste", N_("Contraste"), -100, 100, 0, GRUPO_LUZ),
    Param("realces", N_("Realces"), -100, 100, 0, GRUPO_LUZ),
    Param("sombras", N_("Sombras"), -100, 100, 0, GRUPO_LUZ),
    Param("brancos", N_("Brancos"), -100, 100, 0, GRUPO_LUZ),
    Param("pretos", N_("Pretos"), -100, 100, 0, GRUPO_LUZ),
    Param("temperatura", N_("Temperatura"), -100, 100, 0, GRUPO_COR),
    Param("matiz", N_("Matiz"), -100, 100, 0, GRUPO_COR),
    Param("saturacao", N_("Saturação"), -100, 100, 0, GRUPO_COR),
    Param("vibracao", N_("Vibração"), -100, 100, 0, GRUPO_COR),
    Param("nitidez", N_("Nitidez"), 0, 100, 0, GRUPO_DETALHE),
)
POR_CHAVE: dict[str, Param] = {p.chave: p for p in PARAMS}

# Constantes do modelo (ver a docstring do módulo).
_LUMA = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
_SIGMA_MASCARA = 0.02          # fração do lado menor
_SIGMA_MASCARA_PX = 4.0        # sigma do desfoque na cópia reduzida
_MM_NITIDEZ = 0.1              # raio da nitidez em mm de papel
_MM_LADO_MENOR_PADRAO = 100.0  # 10×15 cm: lado menor em mm, quando não há escala
_LIMIAR_NITIDEZ = 0.01
_QUANTIDADE_NITIDEZ = 1.5
_C_VIBRACAO = 0.3
_PELE_COS = float(np.cos(np.radians(55.0)))
_PELE_SEN = float(np.sin(np.radians(55.0)))

_M_RGB_LMS = np.array([[0.4122214708, 0.5363325363, 0.0514459929],
                       [0.2119034982, 0.6806995451, 0.1073969566],
                       [0.0883024619, 0.2817188376, 0.6299787005]], dtype=np.float64)
_M_LMS_LAB = np.array([[0.2104542553, 0.7936177850, -0.0040720468],
                       [1.9779984951, -2.4285922050, 0.4505937099],
                       [0.0259040371, 0.7827717662, -0.8086757660]], dtype=np.float64)
_M_LAB_LMS = np.linalg.inv(_M_LMS_LAB)
_M_LMS_RGB = np.linalg.inv(_M_RGB_LMS)


# --------------------------------------------------------------------------------------------- esquema

def sanitizar(valores: dict | None) -> dict[str, float]:
    """Só chaves conhecidas, como float, dentro da faixa e fora do padrão (ordem de ``PARAMS``)."""
    saida: dict[str, float] = {}
    if not valores:
        return saida
    for p in PARAMS:
        if p.chave not in valores:
            continue
        try:
            v = float(valores[p.chave])
        except (TypeError, ValueError):
            continue
        if not np.isfinite(v):
            continue
        v = float(min(max(v, p.minimo), p.maximo))
        if v != p.padrao:
            saida[p.chave] = v
    return saida


def e_neutro(valores: dict | None) -> bool:
    """Verdadeiro se nenhum ajuste muda a imagem."""
    return not sanitizar(valores)


# ------------------------------------------------------------------------------------------ utilidades

def _decodificar(x: np.ndarray) -> np.ndarray:
    """sRGB → luz linear (valores negativos viram 0; acima de 1 segue a mesma curva)."""
    x = np.maximum(x, 0.0)
    alto = cv2.pow((x + 0.055) / 1.055, 2.4)
    return np.where(x <= 0.04045, x / 12.92, alto).astype(np.float32, copy=False)


def _codificar(lin: np.ndarray) -> np.ndarray:
    """Luz linear → sRGB (valores negativos viram 0)."""
    lin = np.maximum(lin, 0.0)
    alto = cv2.pow(lin, 1.0 / 2.4) * 1.055 - 0.055
    return np.where(lin <= 0.0031308, lin * 12.92, alto).astype(np.float32, copy=False)


def _transformar(x: np.ndarray, matriz: np.ndarray) -> np.ndarray:
    """Aplica uma matriz 3×3 a cada pixel (``saida = matriz @ pixel``)."""
    return cv2.transform(np.ascontiguousarray(x), matriz.astype(np.float32))


def _linear_para_oklab(lin: np.ndarray) -> np.ndarray:
    lms = _transformar(lin, _M_RGB_LMS)
    return _transformar(cv2.pow(np.maximum(lms, 0.0), 1.0 / 3.0), _M_LMS_LAB)


def _oklab_para_linear(lab: np.ndarray) -> np.ndarray:
    lms_c = _transformar(lab, _M_LAB_LMS)
    return _transformar(lms_c * lms_c * lms_c, _M_LMS_RGB)


def _passo_suave(x: np.ndarray, a: float, b: float) -> np.ndarray:
    t = np.clip((x - a) / (b - a), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _desfocar_relativo(canal: np.ndarray, sigma: float) -> np.ndarray:
    """Gaussiana de sigma ``sigma`` px; sigma grande é calculado numa cópia reduzida (rápido e igual em qualquer escala)."""
    h, w = canal.shape
    if sigma <= _SIGMA_MASCARA_PX:
        return cv2.GaussianBlur(canal, (0, 0), sigma, borderType=cv2.BORDER_REFLECT)
    escala = _SIGMA_MASCARA_PX / sigma
    w2, h2 = max(1, round(w * escala)), max(1, round(h * escala))
    pequena = cv2.resize(canal, (w2, h2), interpolation=cv2.INTER_AREA)
    pequena = cv2.GaussianBlur(pequena, (0, 0), sigma * w2 / w, borderType=cv2.BORDER_REFLECT)
    return cv2.resize(pequena, (w, h), interpolation=cv2.INTER_LINEAR)


# ------------------------------------------------------------------------------------------------ passos

def _ganhos_linear(v: dict[str, float]) -> np.ndarray:
    """Ganhos R/G/B de temperatura, matiz e exposição (luminância do branco preservada nos dois primeiros)."""
    g = np.array([2.0 ** (0.4 * v.get("temperatura", 0.0) / 100.0),
                  2.0 ** (-0.3 * v.get("matiz", 0.0) / 100.0),
                  2.0 ** (-0.4 * v.get("temperatura", 0.0) / 100.0)], dtype=np.float64)
    g /= float(np.dot(g, _LUMA.astype(np.float64)))
    g *= 2.0 ** (v.get("exposicao", 0.0) / 50.0)
    return g.astype(np.float32)


def _curvas_brancos_pretos(s: np.ndarray, brancos: float, pretos: float) -> None:
    """Soma, no lugar, uma curva suave nas luzes (brancos) e nos pretos."""
    if brancos:
        x = np.clip(s, 0.0, 1.0)
        s += (0.2 * brancos / 100.0) * (x * x)
    if pretos:
        x = 1.0 - np.clip(s, 0.0, 1.0)
        s += (0.15 * pretos / 100.0) * (x * x)


def _realces_sombras(s: np.ndarray, realces: float, sombras: float) -> np.ndarray:
    """Realces e sombras com máscara da luminância suavizada misturada à nítida (sem halos)."""
    h, w = s.shape[:2]
    y = np.clip(s, 0.0, 1.0) @ _LUMA
    guia = 0.75 * _desfocar_relativo(y, _SIGMA_MASCARA * min(h, w)) + 0.25 * y
    if realces:
        ganho = 1.0 + (0.4 * realces / 100.0) * _passo_suave(guia, 0.45, 1.0)
        s = s * ganho[..., None].astype(np.float32)
    if sombras:
        expoente = 1.0 - (0.6 * sombras / 100.0) * (1.0 - _passo_suave(guia, 0.0, 0.55))
        base = np.log(np.maximum(s, 1e-6))
        # só onde a máscara age; fora dela o expoente é 1 e o valor fica como está
        s = np.where(expoente[..., None] == 1.0, s, np.exp(base * expoente[..., None].astype(np.float32)))
        s = s.astype(np.float32, copy=False)
    return s


def _contraste(s: np.ndarray, valor: float) -> None:
    x = np.clip(s, 0.0, 1.0)
    s += (valor / 100.0) * (x * (1.0 - x) * (2.0 * x - 1.0))


def _fator_croma(a: np.ndarray, b: np.ndarray, saturacao: float, vibracao: float) -> np.ndarray:
    """Fator que multiplica ``a`` e ``b`` (saturação × vibração protegendo tons de pele)."""
    fator = np.float32(1.0 + saturacao / 100.0)
    if not vibracao:
        return np.full(a.shape, fator, dtype=np.float32)
    c = np.sqrt(a * a + b * b)
    peso = 1.0 - np.minimum(c / _C_VIBRACAO, 1.0)
    peso *= peso
    cos_pele = (a * _PELE_COS + b * _PELE_SEN) / np.maximum(c, 1e-6)
    pele = ((1.0 + cos_pele) * 0.5) ** 8
    t = vibracao / 100.0
    base = peso if t > 0 else 0.3 + 0.7 * (1.0 - peso)
    return (fator * (1.0 + t * base * (1.0 - 0.75 * pele))).astype(np.float32)


def _oklab_cor_e_nitidez(x_linear: np.ndarray, v: dict[str, float], escala_mm_px: float | None) -> np.ndarray:
    """Saturação, vibração e nitidez numa só ida e volta a OKLab. Entra e sai em luz linear."""
    lab = _linear_para_oklab(x_linear)
    if v.get("saturacao") or v.get("vibracao"):
        fator = _fator_croma(lab[..., 1], lab[..., 2], v.get("saturacao", 0.0), v.get("vibracao", 0.0))
        lab[..., 1] *= fator
        lab[..., 2] *= fator
    if v.get("nitidez"):
        h, w = lab.shape[:2]
        if escala_mm_px is None or not escala_mm_px > 0:
            escala_mm_px = min(h, w) / _MM_LADO_MENOR_PADRAO
        sigma = _MM_NITIDEZ * escala_mm_px
        luz = np.ascontiguousarray(lab[..., 0])
        d = luz - cv2.GaussianBlur(luz, (0, 0), sigma, borderType=cv2.BORDER_REFLECT)
        d2 = d * d
        lab[..., 0] = luz + (_QUANTIDADE_NITIDEZ * v["nitidez"] / 100.0) * d * (d2 / (d2 + _LIMIAR_NITIDEZ ** 2))
    return _oklab_para_linear(lab)


# ------------------------------------------------------------------------------------------------- principal

def aplicar(rgb: np.ndarray, valores: dict | None, escala_mm_px: float | None = None) -> np.ndarray:
    """Aplica os ajustes na ordem fixa (ver a docstring do módulo). Não modifica ``rgb``.

    ``escala_mm_px``: px por mm de papel da imagem de destino (só a nitidez usa). Sem ela, vale o equivalente a
    300 dpi de um 10×15 relativo ao lado menor.
    """
    v = sanitizar(valores)
    x = np.array(rgb, dtype=np.float32, order="C", copy=True)
    if not v:
        return x

    linear = False
    if any(k in v for k in ("temperatura", "matiz", "exposicao")):
        x = _decodificar(x) * _ganhos_linear(v)
        linear = True

    tom = any(k in v for k in ("brancos", "pretos", "realces", "sombras", "contraste"))
    if tom:
        if linear:
            x, linear = _codificar(x), False
        _curvas_brancos_pretos(x, v.get("brancos", 0.0), v.get("pretos", 0.0))
        if v.get("realces") or v.get("sombras"):
            x = _realces_sombras(x, v.get("realces", 0.0), v.get("sombras", 0.0))
        if v.get("contraste"):
            _contraste(x, v["contraste"])

    if any(k in v for k in ("saturacao", "vibracao", "nitidez")):
        if not linear:
            x, linear = _decodificar(x), True
        x = _oklab_cor_e_nitidez(x, v, escala_mm_px)

    if linear:
        x = _codificar(x)
    return np.clip(x, 0.0, 1.0, out=x)
