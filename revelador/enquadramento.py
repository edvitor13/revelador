"""Geometria do recorte e enquadramento automático pelos rostos (funções puras).

Contrato em ``docs/ARQUITETURA.md``, seções 5.1 e 5.2. Tudo aqui trabalha na imagem ORIENTADA E GIRADA (giros de
90° já aplicados), com ``W × H`` px, e com a proporção do papel ``proporcao = largura / altura`` já na orientação da
impressão. Os rostos ficam gravados no espaço sem giro: ``girar_rostos()`` leva-os para o espaço girado na hora de
usar.

- ``retangulo(recorte, W, H, proporcao)`` é a ÚNICA função que transforma um ``Recorte`` em geometria (px); o
  editor, a receita e os testes usam ela. O retângulo devolvido tem exatamente a proporção pedida e nunca sai da
  imagem, com ou sem endireitar.
- ``recorte_automatico(W, H, proporcao, rostos)`` é a política do recorte inicial (seção 5.2).
- ``reencaixar(recorte, W, H, proporcao)`` adapta um recorte à troca de tamanho/orientação do papel mantendo o
  centro, a escala e o ângulo possíveis.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Iterable, NamedTuple

from . import tamanhos
from .projeto import Impressao, Recorte, Rosto

# --- política (seção 5.2) -------------------------------------------------------------------------------------------

PRINCIPAL = 0.15            # rosto principal: importância (área × confiança) >= 15% da maior
EMPATE = 1.25               # ao descartar, rostos até 1,25× a menor importância contam como "empatados"
LINHA_DOS_OLHOS = 1 / 3     # linha dos olhos a 1/3 do topo do recorte
OLHOS_SEM_PONTOS = 0.4      # sem pontos dos olhos, a linha fica a 40% da altura da caixa (como no YuNet)

# Expansão da caixa do rosto até a cabeça e os ombros, em frações da altura (cima/baixo) e da largura (lados) do
# rosto. A primeira é a região de interesse (ROI) folgada da seção 5.2; quando ela não cabe, tenta-se as seguintes,
# mais justas, antes de descartar um rosto. A última ainda contém o topo da cabeça (o YuNet marca das sobrancelhas
# ao queixo; o cabelo fica uns 25-30% da altura acima).
EXPANSOES: tuple[tuple[float, float, float], ...] = (
    # (cima, baixo, lados)
    (0.60, 0.35, 0.30),
    (0.45, 0.20, 0.15),
    (0.35, 0.10, 0.05),
)


class Retangulo(NamedTuple):
    """Recorte em px na imagem girada: centro, largura, altura e ângulo de endireitar (graus)."""

    cx: float
    cy: float
    w: float
    h: float
    angulo: float


# --- geometria (seção 5.1) ------------------------------------------------------------------------------------------

def tamanho_maximo(W: float, H: float, proporcao: float, angulo: float = 0.0) -> tuple[float, float]:
    """Maior ``(w, h)`` com ``w / h = proporcao`` que, girado de ``angulo`` graus, cabe em ``W × H``.

    O recorte girado cabe se a caixa envolvente cabe: ``w·|cos θ| + h·|sin θ| ≤ W`` e ``w·|sin θ| + h·|cos θ| ≤ H``.
    """
    if W <= 0 or H <= 0 or proporcao <= 0:
        raise ValueError(f"dimensões inválidas: {W}x{H}, proporção {proporcao}")
    t = math.radians(angulo)
    c, s = abs(math.cos(t)), abs(math.sin(t))
    w = min(W / (c + s / proporcao), H / (s + c / proporcao))
    return w, w / proporcao


def caixa_envolvente(w: float, h: float, angulo: float) -> tuple[float, float]:
    """Largura e altura da caixa alinhada aos eixos que contém o retângulo ``w × h`` girado de ``angulo`` graus."""
    t = math.radians(angulo)
    c, s = abs(math.cos(t)), abs(math.sin(t))
    return w * c + h * s, w * s + h * c


def _limitar(v: float, minimo: float, maximo: float) -> float:
    if minimo > maximo:  # só por arredondamento: o retângulo já cabe por construção
        return (minimo + maximo) / 2
    return min(max(v, minimo), maximo)


def retangulo(recorte: Recorte, W: float, H: float, proporcao: float) -> Retangulo:
    """Transforma o ``Recorte`` em px na imagem girada ``W × H``, sempre dentro dela e na proporção exata.

    ``zoom = 1`` é o maior recorte sem endireitar; o zoom efetivo cresce o necessário para o recorte girado caber
    (endireitar não muda a escala enquanto ainda couber). O centro é limitado para a caixa envolvente ficar dentro da
    imagem: nunca há cantos vazios.
    """
    angulo = max(-45.0, min(45.0, float(recorte.angulo)))
    w0, _ = tamanho_maximo(W, H, proporcao)
    w_ang, _ = tamanho_maximo(W, H, proporcao, angulo)
    w = min(w0 / max(1.0, float(recorte.zoom)), w_ang)
    h = w / proporcao
    bw, bh = caixa_envolvente(w, h, angulo)
    cx = _limitar(float(recorte.cx) * W, bw / 2, W - bw / 2)
    cy = _limitar(float(recorte.cy) * H, bh / 2, H - bh / 2)
    return Retangulo(cx, cy, w, h, angulo)


def zoom_efetivo(recorte: Recorte, W: float, H: float, proporcao: float) -> float:
    """Zoom de fato aplicado (``>= recorte.zoom`` quando o endireitar obriga a aproximar)."""
    w0, _ = tamanho_maximo(W, H, proporcao)
    return w0 / retangulo(recorte, W, H, proporcao).w


def reencaixar(recorte: Recorte, W: float, H: float, proporcao: float) -> Recorte:
    """Adapta o recorte a outra proporção (troca de tamanho ou orientação do papel).

    Mantém o centro, o zoom e o ângulo e só limita o centro para o novo retângulo caber; ``giro`` e ``origem`` ficam
    como estão (um recorte ``"auto"`` deve ser refeito por ``recorte_automatico()`` por quem chama).
    """
    r = retangulo(recorte, W, H, proporcao)
    return replace(recorte, cx=r.cx / W, cy=r.cy / H, zoom=max(1.0, float(recorte.zoom)), angulo=r.angulo)


def girar_rostos(rostos: Iterable[Rosto], giro: int) -> list[Rosto]:
    """Leva rostos do espaço sem giro para o espaço girado ``giro`` × 90° no sentido horário (normalizado)."""
    k = int(giro) % 4

    def ponto(x: float, y: float) -> tuple[float, float]:
        if k == 1:
            return 1.0 - y, x
        if k == 2:
            return 1.0 - x, 1.0 - y
        if k == 3:
            return y, 1.0 - x
        return x, y

    saida: list[Rosto] = []
    for r in rostos:
        (ax, ay), (bx, by) = ponto(r.x, r.y), ponto(r.x + r.w, r.y + r.h)
        olhos = None
        if r.olhos is not None:
            olhos = (ponto(*r.olhos[0]), ponto(*r.olhos[1]))
        saida.append(Rosto(x=min(ax, bx), y=min(ay, by), w=abs(bx - ax), h=abs(by - ay),
                           olhos=olhos, confianca=r.confianca))
    return saida


# --- recorte automático (seção 5.2) ---------------------------------------------------------------------------------

@dataclass(frozen=True)
class _Caixa:
    """Rosto em px, com a importância e a altura da linha dos olhos."""

    x0: float
    y0: float
    x1: float
    y1: float
    olhos_y: float
    importancia: float

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    def expandida(self, cima: float, baixo: float, lados: float) -> tuple[float, float, float, float]:
        w, h = self.x1 - self.x0, self.y1 - self.y0
        return self.x0 - lados * w, self.y0 - cima * h, self.x1 + lados * w, self.y1 + baixo * h


def _caixas(rostos: Iterable[Rosto], W: float, H: float) -> list[_Caixa]:
    caixas = []
    for r in rostos:
        if not (r.w > 0 and r.h > 0):
            continue
        x0, y0, x1, y1 = r.x * W, r.y * H, (r.x + r.w) * W, (r.y + r.h) * H
        if r.olhos is not None:
            olhos_y = (r.olhos[0][1] + r.olhos[1][1]) / 2 * H
            if not (y0 <= olhos_y <= y1):
                olhos_y = y0 + OLHOS_SEM_PONTOS * (y1 - y0)
        else:
            olhos_y = y0 + OLHOS_SEM_PONTOS * (y1 - y0)
        caixas.append(_Caixa(x0, y0, x1, y1, olhos_y, (x1 - x0) * (y1 - y0) * max(0.0, r.confianca)))
    return caixas


def _intervalo(desejado: float, lado: float, total: float, a: float | None = None, b: float | None = None) -> float:
    """Centro (1D) de um segmento ``lado`` dentro de ``[0, total]`` o mais perto de ``desejado`` contendo ``[a, b]``."""
    minimo, maximo = lado / 2, total - lado / 2
    if a is not None and b is not None and b - a <= lado:
        minimo, maximo = max(minimo, b - lado / 2), min(maximo, a + lado / 2)
    return _limitar(desejado, minimo, maximo)


def _uniao(caixas: list[_Caixa], expansao: tuple[float, float, float], margem: float,
           W: float, H: float) -> tuple[float, float, float, float]:
    """União das caixas expandidas, limitada à imagem. Cada rosto fica a pelo menos ``margem`` px da borda dela."""
    partes = []
    for c in caixas:
        x0, y0, x1, y1 = c.expandida(*expansao)
        partes.append((min(x0, c.x0 - margem), min(y0, c.y0 - margem), max(x1, c.x1 + margem), max(y1, c.y1 + margem)))
    x0 = max(0.0, min(p[0] for p in partes))
    y0 = max(0.0, min(p[1] for p in partes))
    x1 = min(float(W), max(p[2] for p in partes))
    y1 = min(float(H), max(p[3] for p in partes))
    return x0, y0, x1, y1


def _descartar(caixas: list[_Caixa]) -> list[_Caixa]:
    """Tira o rosto menos importante; entre os empatados, o mais longe do centro de importância (as pontas)."""
    total = sum(c.importancia for c in caixas) or 1.0
    centro_x = sum(c.cx * c.importancia for c in caixas) / total
    menor = min(c.importancia for c in caixas)
    empatados = [c for c in caixas if c.importancia <= menor * EMPATE]
    sai = max(empatados, key=lambda c: (abs(c.cx - centro_x), -c.importancia))
    return [c for c in caixas if c is not sai]


def recorte_automatico(W: float, H: float, proporcao: float, rostos: Iterable[Rosto] | None,
                       margem: float = 0.0) -> Recorte:
    """Recorte inicial pelos rostos (seção 5.2), com ``zoom = 1`` e sem ângulo.

    ``W × H`` e ``rostos`` estão no espaço girado (use ``girar_rostos()``); ``proporcao`` = largura/altura do papel
    na orientação da impressão. ``margem`` é a margem de corte da gráfica como fração do lado menor do papel (ex.:
    2 mm num 10x15 → 2/102): quando houver folga, nenhum rosto fica dentro dela. O ``giro`` do resultado é 0; quem
    chama põe o giro da impressão.

    1. Sem rostos → centro (``origem = "centro"``).
    2. Importância = área × confiança; principais = importância ≥ 15% da maior.
    3. Região de interesse = união das caixas principais expandidas (cabelo, queixo, laterais).
    4. Recorte com ``zoom = 1`` na proporção do papel.
    5. Horizontal: centróide dos rostos ponderado pela importância (o rosto principal fica mais ao centro), com a
       região inteira dentro do recorte.
    6. Vertical: linha dos olhos a 1/3 do topo; depois o topo da região dentro do recorte (cabeça inteira) e, se
       couber, a base também.
    7. Se a região não couber nem com as expansões mais justas, descarta o rosto principal menos importante (entre
       empatados, o da ponta) e repete; com um rosto só, prioriza a cabeça inteira.
    8. Limita à imagem; ``origem = "auto"``.
    """
    w, h = tamanho_maximo(W, H, proporcao)
    caixas = _caixas(rostos or (), W, H)
    if not caixas:
        return Recorte(cx=0.5, cy=0.5, zoom=1.0, angulo=0.0, giro=0, origem="centro")

    maior = max(c.importancia for c in caixas)
    principais = [c for c in caixas if c.importancia >= PRINCIPAL * maior] or caixas
    margem_px = max(0.0, float(margem)) * min(w, h)

    # Passos 3 e 7: a região mais folgada que couber, com o maior número de rostos possível.
    escolha: tuple[list[_Caixa], tuple[float, float, float, float]] | None = None
    while escolha is None:
        for exp in EXPANSOES:
            for margem_atual in ((margem_px, 0.0) if margem_px > 0 else (0.0,)):
                roi = _uniao(principais, exp, margem_atual, W, H)
                if roi[2] - roi[0] <= w + 1e-6 and roi[3] - roi[1] <= h + 1e-6:
                    escolha = (principais, roi)
                    break
            if escolha is not None:
                break
        if escolha is None:
            if len(principais) == 1:
                break
            principais = _descartar(principais)

    total = sum(c.importancia for c in principais) or 1.0
    olhos_y = sum(c.olhos_y * c.importancia for c in principais) / total
    centro_x = sum(c.cx * c.importancia for c in principais) / total
    if escolha is not None:
        _, (x0, y0, x1, y1) = escolha
        cx = _intervalo(centro_x, w, W, x0, x1)
        cy = _intervalo(olhos_y - h * LINHA_DOS_OLHOS + h / 2, h, H, y0, y1)
    else:
        # Um rosto só e maior que o papel (selfie muito de perto): centro no rosto e topo da cabeça dentro.
        unico = principais[0]
        x0, y0, x1, y1 = _uniao(principais, EXPANSOES[-1], 0.0, W, H)
        cx = _intervalo(unico.cx, w, W, x0, x1)
        cy = olhos_y - h * LINHA_DOS_OLHOS + h / 2
        if y1 - y0 > h:
            cy = min(cy, y0 + h / 2)       # a cabeça (topo) tem prioridade sobre o queixo
        cy = _intervalo(cy, h, H, y0, y1)
    return Recorte(cx=cx / W, cy=cy / H, zoom=1.0, angulo=0.0, giro=0, origem="auto")


def recorte_sugerido(impressao: Impressao, largura: int, altura: int, rostos: Iterable[Rosto] | None,
                     margem_corte_mm: float = 0.0) -> Recorte:
    """Recorte automático de UMA impressão: o caminho único usado pela interface (ao selecionar, ao trocar o tamanho
    ou a orientação de uma impressão não manual e quando os rostos chegam).

    ``largura × altura`` e ``rostos`` são da imagem orientada SEM giro (como ``imagem.InfoFoto`` e ``Foto.rostos``).
    Aplica o giro da impressão, resolve a orientação ("auto" segue a imagem girada) e a proporção do papel, converte a
    margem de corte (mm) em fração do lado menor do papel e chama ``recorte_automatico``. O giro da impressão é
    mantido. Quem chama só substitui o recorte quando ``origem != "manual"``.
    """
    giro = int(impressao.recorte.giro) % 4
    W, H = (altura, largura) if giro % 2 else (largura, altura)
    orientacao = tamanhos.orientacao_efetiva(impressao.orientacao, W, H)
    prop = tamanhos.proporcao(impressao.tamanho, orientacao, impressao.papel_mm)
    menor, _maior = tamanhos.papel_mm(impressao.tamanho, impressao.papel_mm)
    margem = margem_corte_mm / menor if menor > 0 else 0.0
    recorte = recorte_automatico(W, H, prop, girar_rostos(rostos or (), giro), margem)
    return replace(recorte, giro=giro)
