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

Como é calculado (desempenho, #7)
---------------------------------
As fórmulas acima são as de ``tests/ajustes_referencia.py`` (cópia lenta e direta, usada nos testes); aqui o
cálculo é reorganizado, sem mudar a ordem nem a matemática, para custar uma fração do tempo (diferença máxima
medida contra a referência < 1/1024 e média < 1/4096):

- Tudo o que é pontual e por canal (temperatura, matiz, exposição, brancos, pretos, contraste e as conversões sRGB
  ↔ luz linear entre eles) vira **uma tabela de consulta** por canal, calculada em float64 sobre uma grade de 8192
  pontos e aplicada com interpolação linear (``cv2.remap``). Realces e sombras (espaciais) separam a tabela em duas:
  a anterior a eles e a posterior (contraste e decodificação).
- A máscara de realces/sombras é uma tabela sobre o guia ``G``; sombras usam ``exp(log(x)·expoente)`` com ``cv2``.
- Saturação, vibração e nitidez trabalham nas raízes cúbicas LMS (``c``), sem passar por um array OKLab inteiro:
  como ``L`` não muda com a saturação e ``a``, ``b`` só são multiplicados, ``c' = c + (F-1)·Q·c + ΔL`` (``Q`` fixa).
  A saturação sozinha é uma só matriz 3×3. A volta (cubo, matriz, luz linear → sRGB) acaba numa tabela de 16384
  pontos que já limita o resultado a 0..1.
- Nada de threads aqui; o ``cv2`` já paraleliza o que vale a pena.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

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

# Parâmetros da implementação rápida (ver "Como é calculado" na docstring do módulo).
_N_TABELA = 16384              # pontos por canal das tabelas de tons
_N_MASCARA = 4096              # pontos das tabelas de realces/sombras (função do guia G, 0..1)
_N_CODIFICAR = 16384           # pontos da tabela final luz linear → sRGB (0..1)
_DOMINIO_MIN, _DOMINIO_MAX = -2.0, 8.0   # a tabela cobre os valores da imagem, limitados a esta faixa
_LIMITE_MAPA = 6_000_000       # acima disto (elementos) o mapa de canais não fica em cache

_F_RGB_LMS = _M_RGB_LMS.astype(np.float32)
_LINHA_LUMA = _LUMA[None, :]
_LINHA_L, _LINHA_A, _LINHA_B = (_M_LMS_LAB[i:i + 1].astype(np.float32) for i in range(3))
# Q·c = parte de c que vem de a e b (c' = c + (F-1)·Q·c escala a e b por F e deixa L como está).
_Q = _M_LAB_LMS @ np.diag([0.0, 1.0, 1.0]) @ _M_LMS_LAB
_F_Q = _Q.astype(np.float32)
# Volta ao RGB já em coordenadas da tabela de codificação (0 .. _N_CODIFICAR-1).
_F_LMS_RGB_INDICE = (_M_LMS_RGB * (_N_CODIFICAR - 1)).astype(np.float32)


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
    """sRGB → luz linear (valores negativos viram 0; acima de 1 segue a mesma curva). Exata, em qualquer ``float``."""
    x = np.maximum(x, 0.0)
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4).astype(x.dtype, copy=False)


def _codificar(lin: np.ndarray) -> np.ndarray:
    """Luz linear → sRGB (valores negativos viram 0). Exata, em qualquer ``float``."""
    lin = np.maximum(lin, 0.0)
    return np.where(lin <= 0.0031308, lin * 12.92, 1.055 * lin ** (1.0 / 2.4) - 0.055).astype(lin.dtype, copy=False)


def _transformar(x: np.ndarray, matriz: np.ndarray) -> np.ndarray:
    """Aplica uma matriz 3×3 a cada pixel (``saida = matriz @ pixel``)."""
    return cv2.transform(np.ascontiguousarray(x), matriz.astype(np.float32))


def _linear_para_oklab(lin: np.ndarray) -> np.ndarray:
    """Luz linear → OKLab (usado pelos testes; ``aplicar`` trabalha direto nas raízes LMS)."""
    lms = _transformar(lin, _M_RGB_LMS)
    return _transformar(cv2.pow(np.maximum(lms, 0.0), 1.0 / 3.0), _M_LMS_LAB)


def _passo_suave(x: np.ndarray, a: float, b: float) -> np.ndarray:
    t = np.clip((x - a) / (b - a), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _desfocar_relativo(canal: np.ndarray, sigma: float, destino: np.ndarray | None = None) -> np.ndarray:
    """Gaussiana de sigma ``sigma`` px; sigma grande é calculado numa cópia reduzida (rápido, igual em qualquer escala)."""
    h, w = canal.shape
    if sigma <= _SIGMA_MASCARA_PX:
        return cv2.GaussianBlur(canal, (0, 0), sigma, dst=destino, borderType=cv2.BORDER_REFLECT)
    escala = _SIGMA_MASCARA_PX / sigma
    w2, h2 = max(1, round(w * escala)), max(1, round(h * escala))
    pequena = cv2.resize(canal, (w2, h2), interpolation=cv2.INTER_AREA)
    pequena = cv2.GaussianBlur(pequena, (0, 0), sigma * w2 / w, borderType=cv2.BORDER_REFLECT)
    return cv2.resize(pequena, (w, h), dst=destino, interpolation=cv2.INTER_LINEAR)


# ----------------------------------------------------------------------------------- memória de trabalho

class _Memoria:
    """Arrays de trabalho de UMA chamada de ``aplicar``, reaproveitados entre os passos.

    Alocar e tocar 20 MB novos custa ~3 ms; operar sobre um array que já existe, ~1 ms. Nada fica entre chamadas
    (``aplicar`` continua sem estado) e o resultado devolvido nunca é um destes arrays. Os passos usam sempre o
    valor devolvido pelo ``cv2``, então um array de tamanho inesperado só perde o reaproveitamento.
    """

    def __init__(self) -> None:
        self._arrays: dict[str, np.ndarray] = {}

    def pegar(self, nome: str, forma: tuple[int, ...]) -> np.ndarray:
        a = self._arrays.get(nome)
        if a is None or a.shape != forma:
            a = self._arrays[nome] = np.empty(forma, np.float32)
        return a


# ---------------------------------------------------------------------------------- tabelas de consulta

def _construir_mapa(h: int, largura: int, canais: int) -> np.ndarray:
    """Mapa de linhas para ``cv2.remap``: o canal (0, 1, 2) de cada coluna, ou só zeros (tabela de uma linha)."""
    if canais == 1:
        return np.zeros((h, largura), np.float32)
    linha = np.tile(np.arange(canais, dtype=np.float32), largura // canais)
    return np.ascontiguousarray(np.broadcast_to(linha, (h, largura)))


@lru_cache(maxsize=3)
def _mapa_em_cache(h: int, largura: int, canais: int) -> np.ndarray:
    mapa = _construir_mapa(h, largura, canais)
    mapa.flags.writeable = False
    return mapa


def _mapa_linhas(h: int, largura: int, canais: int) -> np.ndarray:
    """O mapa de linhas guarda-se em cache para o tamanho da prévia (que se repete); imagens enormes não."""
    if h * largura > _LIMITE_MAPA:
        return _construir_mapa(h, largura, canais)
    return _mapa_em_cache(h, largura, canais)


def _consultar(tabela: np.ndarray, coordenadas: np.ndarray, canais: int,
               destino: np.ndarray | None = None) -> np.ndarray:
    """``tabela[canal][coordenada]`` com interpolação linear; ``coordenadas`` (H × W·canais) em unidades de índice.

    Fora da tabela vale o primeiro/último ponto. ``tabela`` tem ``canais`` linhas (1 = plano, 3 = RGB intercalado).
    ``destino`` pode ser as próprias ``coordenadas`` (a consulta é elemento a elemento).
    """
    mapa = _mapa_linhas(coordenadas.shape[0], coordenadas.shape[1], canais)
    return cv2.remap(tabela, coordenadas, mapa, cv2.INTER_LINEAR, dst=destino, borderMode=cv2.BORDER_REPLICATE)


def _dominio(plano: np.ndarray) -> tuple[float, float]:
    """Faixa que a tabela cobre: a da imagem, sempre incluindo 0..1 e dentro de [-2, 8]."""
    menor, maior = cv2.minMaxLoc(plano)[:2]
    if not (np.isfinite(menor) and np.isfinite(maior)):
        return 0.0, 1.0
    return min(0.0, max(menor, _DOMINIO_MIN)), max(1.0, min(maior, _DOMINIO_MAX))


def _por_tabela(x: np.ndarray, tabela: np.ndarray, lo: float, hi: float, trabalho: np.ndarray,
                destino: np.ndarray | None = None) -> np.ndarray:
    """Aplica a ``x`` (H×W×3 float32) a tabela de 3 linhas (uma por canal) que cobre ``lo..hi``.

    Usa ``trabalho`` (mesma forma de ``x``; pode ser o próprio ``x``) para as coordenadas; o resultado fica em
    ``destino`` (ou em ``trabalho``).
    """
    h, w = x.shape[:2]
    plano = x.reshape(h, w * 3)
    escala = (tabela.shape[1] - 1) / (hi - lo)
    coord = trabalho.reshape(h, w * 3)
    coord = cv2.addWeighted(plano, escala, plano, 0.0, -lo * escala, dst=coord)
    saida = coord if destino is None else destino.reshape(h, w * 3)
    return _consultar(tabela, coord, 3, saida).reshape(h, w, 3)


def _grade(lo: float, hi: float, n: int) -> np.ndarray:
    """A grade de entradas da tabela, repetida para os 3 canais (float64, 3 × n)."""
    return np.tile(np.linspace(lo, hi, n), (3, 1))


def _ganhos_linear(v: dict[str, float]) -> np.ndarray:
    """Ganhos R/G/B de temperatura, matiz e exposição (luminância do branco preservada nos dois primeiros)."""
    g = np.array([2.0 ** (0.4 * v.get("temperatura", 0.0) / 100.0),
                  2.0 ** (-0.3 * v.get("matiz", 0.0) / 100.0),
                  2.0 ** (-0.4 * v.get("temperatura", 0.0) / 100.0)], dtype=np.float64)
    g /= float(np.dot(g, _LUMA.astype(np.float64)))
    g *= 2.0 ** (v.get("exposicao", 0.0) / 50.0)
    return g.astype(np.float32)


def _curva_brancos_pretos(t: np.ndarray, brancos: float, pretos: float) -> np.ndarray:
    """Soma uma curva suave nas luzes (brancos) e nos pretos (``t`` em sRGB)."""
    if brancos:
        x = np.clip(t, 0.0, 1.0)
        t = t + (0.2 * brancos / 100.0) * (x * x)
    if pretos:
        x = 1.0 - np.clip(t, 0.0, 1.0)
        t = t + (0.15 * pretos / 100.0) * (x * x)
    return t


def _curva_contraste(t: np.ndarray, valor: float) -> np.ndarray:
    x = np.clip(t, 0.0, 1.0)
    return t + (valor / 100.0) * (x * (1.0 - x) * (2.0 * x - 1.0))


def _tabela_antes(lo: float, hi: float, v: dict[str, float], espacial: bool, cor: bool) -> np.ndarray:
    """Tudo o que é pontual antes de realces/sombras (ou até o fim, se não há): passos 1, 2, 3 e, sem eles, o 5.

    Sai em sRGB sem limitar (se há realces/sombras), em luz linear (se há cor) ou em sRGB limitado a 0..1.
    """
    t = _grade(lo, hi, _N_TABELA)
    linear = False
    if any(k in v for k in ("temperatura", "matiz", "exposicao")):
        t, linear = _decodificar(t) * _ganhos_linear(v).astype(np.float64)[:, None], True
    if any(k in v for k in ("brancos", "pretos", "realces", "sombras", "contraste")):
        if linear:
            t, linear = _codificar(t), False
        t = _curva_brancos_pretos(t, v.get("brancos", 0.0), v.get("pretos", 0.0))
        if not espacial and v.get("contraste"):
            t = _curva_contraste(t, v["contraste"])
    if espacial:
        return t.astype(np.float32)
    if cor:
        return (t if linear else _decodificar(t)).astype(np.float32)
    return np.clip(_codificar(t) if linear else t, 0.0, 1.0).astype(np.float32)


def _tabela_depois(lo: float, hi: float, contraste: float, cor: bool) -> np.ndarray:
    """O que é pontual depois de realces/sombras: contraste (5) e, havendo cor, a decodificação para luz linear."""
    t = _grade(lo, hi, _N_TABELA)
    if contraste:
        t = _curva_contraste(t, contraste)
    return (_decodificar(t) if cor else np.clip(t, 0.0, 1.0)).astype(np.float32)


def _tabela_codificacao() -> np.ndarray:
    """Luz linear 0..1 → sRGB, três linhas iguais (uma por canal)."""
    t = _codificar(_grade(0.0, 1.0, _N_CODIFICAR))
    return np.clip(t, 0.0, 1.0).astype(np.float32)


_TABELA_CODIFICAR = _tabela_codificacao()


def _tabela_mascara(funcao) -> np.ndarray:
    """Tabela 1 × N de ``funcao(G)`` para G em 0..1."""
    return funcao(np.linspace(0.0, 1.0, _N_MASCARA))[None, :].astype(np.float32)


# ------------------------------------------------------------------------------------------------ passos

def _realces_sombras(s: np.ndarray, realces: float, sombras: float, m: _Memoria) -> np.ndarray:
    """Realces e sombras com máscara da luminância suavizada misturada à nítida (sem halos).

    Devolve o array ``"W"`` da memória de trabalho (``s`` pode ser o próprio ``"W"`` ou a entrada, que não muda).
    """
    h, w = s.shape[:2]
    forma, plano = (h, w, 3), (h, w)
    saida, extra = m.pegar("W", forma), m.pegar("H1", forma)
    menor, maior = cv2.minMaxLoc(s.reshape(h, w * 3))[:2]
    limitado = s if (menor >= 0.0 and maior <= 1.0) else np.clip(s, 0.0, 1.0, out=extra)
    y = cv2.transform(limitado, _LINHA_LUMA, dst=m.pegar("y", plano))
    guia = _desfocar_relativo(y, _SIGMA_MASCARA * min(h, w), m.pegar("guia", plano))
    # guia = 0,75·desfoque(Y) + 0,25·Y, já em unidades de índice das tabelas de máscara
    guia = cv2.addWeighted(guia, 0.75 * (_N_MASCARA - 1), y, 0.25 * (_N_MASCARA - 1), 0.0, dst=guia)
    if realces:
        t = realces / 100.0
        tabela = _tabela_mascara(lambda g: 1.0 + (0.4 * t) * _passo_suave(g, 0.45, 1.0))
        ganho = _consultar(tabela, guia, 1, y)
        s = cv2.multiply(s, cv2.cvtColor(ganho, cv2.COLOR_GRAY2RGB, dst=extra), dst=saida)
    if sombras:
        t = sombras / 100.0
        tabela = _tabela_mascara(lambda g: 1.0 - (0.6 * t) * (1.0 - _passo_suave(g, 0.0, 0.55)))
        expoente = _consultar(tabela, guia, 1, y)
        # s^e = exp(e·ln s); fora da máscara e = 1 e o valor fica como está
        s = np.maximum(s, np.float32(1e-6), out=saida)
        s = cv2.log(s, dst=s)
        s = cv2.multiply(s, cv2.cvtColor(expoente, cv2.COLOR_GRAY2RGB, dst=extra), dst=s)
        s = cv2.exp(s, dst=s)
    return s


def _fator_croma(a: np.ndarray, b: np.ndarray, saturacao: float, vibracao: float, m: _Memoria) -> np.ndarray:
    """Plano do fator que multiplica ``a`` e ``b`` (saturação × vibração protegendo tons de pele).

    Consome ``a`` e ``b`` (usa os dois como espaço de trabalho) e devolve um array da memória.
    """
    fs = 1.0 + saturacao / 100.0
    t = vibracao / 100.0
    c = cv2.magnitude(a, b, m.pegar("croma", a.shape))
    # pele = ((1 + cos(h - 55°))/2)^8, com cos = (a·cos55 + b·sen55)/C
    pele = cv2.addWeighted(a, _PELE_COS, b, _PELE_SEN, 0.0, dst=a)
    pele = cv2.divide(pele, cv2.max(c, 1e-6, dst=b), dst=pele)
    pele = cv2.addWeighted(pele, 0.5, pele, 0.0, 0.5, dst=pele)
    for _ in range(3):
        pele = cv2.multiply(pele, pele, dst=pele)
    # peso = (1 - min(C/0,3; 1))² = min(C/0,3 - 1; 0)²
    peso = cv2.addWeighted(c, 1.0 / _C_VIBRACAO, c, 0.0, -1.0, dst=b)
    peso = cv2.multiply(cv2.min(peso, 0.0, dst=peso), peso, dst=peso)
    if t <= 0:  # negativo: 0,3 + 0,7·(1 - peso)
        peso = cv2.addWeighted(peso, -0.7, peso, 0.0, 1.0, dst=peso)
    pele = cv2.addWeighted(pele, -0.75, pele, 0.0, 1.0, dst=pele)
    peso = cv2.multiply(peso, pele, dst=peso)
    return cv2.addWeighted(peso, fs * t, peso, 0.0, fs - 1.0, dst=peso)  # já menos 1: é o (F-1) de c' = c + (F-1)·Q·c


def _cor_e_nitidez(lin: np.ndarray, v: dict[str, float], escala_mm_px: float | None, m: _Memoria,
                   destino: np.ndarray) -> np.ndarray:
    """Saturação, vibração e nitidez (passos 6 e 7). Entra em luz linear (≥ 0) e sai em sRGB limitado a 0..1.

    ``lin`` é o array ``"W"`` da memória de trabalho e é consumido. Trabalha nas raízes cúbicas LMS ``c``: ``L`` é
    uma combinação de ``c``; escalar ``a`` e ``b`` por ``F`` é somar ``(F-1)·Q·c``; a nitidez soma ``ΔL`` aos três
    canais (a primeira coluna de LAB→LMS é 1, 1, 1).
    """
    saturacao, vibracao, nitidez = v.get("saturacao", 0.0), v.get("vibracao", 0.0), v.get("nitidez", 0.0)
    h, w = lin.shape[:2]
    forma, plano = (h, w, 3), (h, w)
    extra = m.pegar("H1", forma)
    c = cv2.transform(lin, _F_RGB_LMS, dst=lin)
    c = cv2.pow(c, 1.0 / 3.0, dst=c)
    if vibracao:
        fator = _fator_croma(cv2.transform(c, _LINHA_A, dst=m.pegar("a", plano)),
                             cv2.transform(c, _LINHA_B, dst=m.pegar("b", plano)), saturacao, vibracao, m)
        novo = cv2.transform(c, _F_Q, dst=m.pegar("H2", forma))
        novo = cv2.multiply(novo, cv2.cvtColor(fator, cv2.COLOR_GRAY2RGB, dst=extra), dst=novo)
        novo = cv2.add(novo, c, dst=novo)
    elif saturacao:
        novo = cv2.transform(c, np.eye(3, dtype=np.float32) + np.float32(saturacao / 100.0) * _F_Q,
                             dst=m.pegar("H2", forma))
    else:
        novo = c
    if nitidez:
        if escala_mm_px is None or not escala_mm_px > 0:
            escala_mm_px = min(h, w) / _MM_LADO_MENOR_PADRAO
        luz = cv2.transform(c, _LINHA_L, dst=m.pegar("y", plano))
        d = cv2.GaussianBlur(luz, (0, 0), _MM_NITIDEZ * escala_mm_px, dst=m.pegar("guia", plano),
                             borderType=cv2.BORDER_REFLECT)
        d = cv2.subtract(luz, d, dst=d)
        d2 = cv2.multiply(d, d, dst=luz)
        d2 = cv2.divide(d2, cv2.add(d2, _LIMIAR_NITIDEZ ** 2, dst=m.pegar("croma", plano)), dst=d2)
        d2 = cv2.multiply(d2, d, scale=_QUANTIDADE_NITIDEZ * nitidez / 100.0, dst=d2)
        novo = cv2.add(novo, cv2.cvtColor(d2, cv2.COLOR_GRAY2RGB, dst=extra), dst=novo)
    cubo = cv2.pow(novo, 3.0, dst=novo)
    indice = cv2.transform(cubo, _F_LMS_RGB_INDICE, dst=cubo)  # luz linear já em coordenadas da tabela
    return _consultar(_TABELA_CODIFICAR, indice.reshape(h, w * 3), 3, destino.reshape(h, w * 3)).reshape(h, w, 3)


# ------------------------------------------------------------------------------------------------- principal

def aplicar(rgb: np.ndarray, valores: dict | None, escala_mm_px: float | None = None) -> np.ndarray:
    """Aplica os ajustes na ordem fixa (ver a docstring do módulo). Não modifica ``rgb``.

    ``escala_mm_px``: px por mm de papel da imagem de destino (só a nitidez usa). Sem ela, vale o equivalente a
    300 dpi de um 10×15 relativo ao lado menor.
    """
    v = sanitizar(valores)
    if not v:
        return np.array(rgb, dtype=np.float32, order="C", copy=True)
    x = np.ascontiguousarray(rgb, dtype=np.float32)  # só lido: todo passo escreve na memória de trabalho
    h, w = x.shape[:2]
    m = _Memoria()
    trabalho = m.pegar("W", x.shape)
    resultado = np.empty(x.shape, np.float32)  # o que o chamador recebe; nunca é memória de trabalho

    espacial = "realces" in v or "sombras" in v
    cor = any(k in v for k in ("saturacao", "vibracao", "nitidez"))
    contraste = v.get("contraste", 0.0)

    if any(k in v for k in ("temperatura", "matiz", "exposicao", "brancos", "pretos")) or (
            not espacial and (contraste or cor)):
        lo, hi = _dominio(x.reshape(h, w * 3))
        ultimo = not espacial and not cor
        x = _por_tabela(x, _tabela_antes(lo, hi, v, espacial, cor), lo, hi, trabalho, resultado if ultimo else None)
    if espacial:
        x = _realces_sombras(x, v.get("realces", 0.0), v.get("sombras", 0.0), m)
        if contraste or cor:
            lo, hi = _dominio(x.reshape(h, w * 3))
            x = _por_tabela(x, _tabela_depois(lo, hi, contraste, cor), lo, hi, trabalho,
                            None if cor else resultado)
        else:
            x = np.clip(x, 0.0, 1.0, out=resultado)
    if cor:
        x = _cor_e_nitidez(x, v, escala_mm_px, m, resultado)
    return x
