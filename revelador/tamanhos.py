"""Tamanhos de revelação: tabela única de papéis, orientação, proporção, pixels e qualidade.

Funções puras, sem Qt. O tamanho real do papel manda (muitos tamanhos "em cm" são polegadas); os pixels saem do
papel pelo dpi (``round(mm / 25,4 × dpi)``). IDs sem acento e **nunca renomeados**. Contrato em
``docs/ARQUITETURA.md`` (seção 4).
"""

from __future__ import annotations

from dataclasses import dataclass

from .i18n import N_, _

COMUM = "comum"
AMPLIACAO = "ampliacao"
QUADRADO = "quadrado"
GRUPOS = (COMUM, AMPLIACAO, QUADRADO)

PADRAO = "10x15"
PERSONALIZADO = "personalizado"
MM_POR_POLEGADA = 25.4
LIMITE_LADO_MIN_MM = 20.0
LIMITE_LADO_MAX_MM = 1000.0
ORIENTACOES_FIXAS = ("retrato", "paisagem")

AJUDA = N_(
    "Os tamanhos variam um pouco entre laboratórios (principalmente o 15x21). "
    "Confirme as medidas e o nome com o seu laboratório antes de encomendar."
)


@dataclass(frozen=True)
class Tamanho:
    """Um tamanho de papel. ``lado_menor_mm <= lado_maior_mm``; a orientação é da impressão, não daqui."""

    id: str
    nome: str
    lado_menor_mm: float
    lado_maior_mm: float
    grupo: str


TAMANHOS: tuple[Tamanho, ...] = (
    Tamanho("9x13", N_("9x13"), 88.9, 127.0, COMUM),
    Tamanho("10x15", N_("10x15"), 101.6, 152.4, COMUM),
    Tamanho("13x18", N_("13x18"), 127.0, 177.8, COMUM),
    Tamanho("15x20", N_("15x20"), 152.4, 203.2, COMUM),
    Tamanho("15x21", N_("15x21"), 152.4, 210.0, COMUM),
    Tamanho("20x25", N_("20x25"), 203.2, 254.0, AMPLIACAO),
    Tamanho("20x30", N_("20x30"), 203.2, 304.8, AMPLIACAO),
    Tamanho("a4", N_("A4 (21x29,7)"), 210.0, 297.0, AMPLIACAO),
    Tamanho("30x40", N_("30x40"), 304.8, 406.4, AMPLIACAO),
    Tamanho("30x45", N_("30x45"), 304.8, 457.2, AMPLIACAO),
    Tamanho("40x60", N_("40x60"), 406.4, 609.6, AMPLIACAO),
    Tamanho("10x10", N_("10x10"), 101.6, 101.6, QUADRADO),
    Tamanho("15x15", N_("15x15"), 152.4, 152.4, QUADRADO),
    Tamanho("20x20", N_("20x20"), 203.2, 203.2, QUADRADO),
)

_INDICE = {t.id: t for t in TAMANHOS}


def obter(tamanho_id: str) -> Tamanho:
    """O tamanho da tabela com esse id. O personalizado não está na tabela: use ``papel_mm()``."""
    try:
        return _INDICE[tamanho_id]
    except KeyError:
        raise KeyError(_("Tamanho desconhecido: {id}").format(id=tamanho_id)) from None


def _menor_maior(tamanho_id: str, medida: tuple[float, float] | None) -> tuple[float, float]:
    if tamanho_id != PERSONALIZADO:
        t = obter(tamanho_id)
        return t.lado_menor_mm, t.lado_maior_mm
    if medida is None:
        raise ValueError(_("O tamanho personalizado precisa de largura e altura."))
    a, b = (float(lado) for lado in medida)
    for lado in (a, b):
        if not LIMITE_LADO_MIN_MM <= lado <= LIMITE_LADO_MAX_MM:
            raise ValueError(
                _("Cada lado do tamanho personalizado deve ficar entre {minimo} e {maximo} mm.").format(
                    minimo=f"{LIMITE_LADO_MIN_MM:g}", maximo=f"{LIMITE_LADO_MAX_MM:g}")
            )
    return min(a, b), max(a, b)


def papel_mm(tamanho_id: str, papel_mm: tuple[float, float] | None = None) -> tuple[float, float]:
    """(lado menor, lado maior) do papel em mm. O personalizado usa ``papel_mm`` (em qualquer ordem, validado)."""
    return _menor_maior(tamanho_id, papel_mm)


def orientacao_auto(largura: int, altura: int) -> str:
    """Retrato se a imagem for mais alta que larga (ou quadrada); paisagem se for mais larga."""
    return "paisagem" if largura > altura else "retrato"


def orientacao_efetiva(orientacao: str, largura_img: int, altura_img: int) -> str:
    """Resolve ``"auto"`` pela imagem; ``"retrato"`` e ``"paisagem"`` passam como estão."""
    if orientacao == "auto":
        return orientacao_auto(largura_img, altura_img)
    if orientacao in ORIENTACOES_FIXAS:
        return orientacao
    raise ValueError(_("Orientação desconhecida: {valor}").format(valor=orientacao))


def _mm_na_orientacao(tamanho_id: str, orientacao: str, medida: tuple[float, float] | None) -> tuple[float, float]:
    """(largura, altura) do papel em mm, já na orientação. Exige orientação resolvida."""
    menor, maior = _menor_maior(tamanho_id, medida)
    if orientacao == "retrato":
        return menor, maior
    if orientacao == "paisagem":
        return maior, menor
    raise ValueError(_("A orientação precisa ser retrato ou paisagem: {valor}").format(valor=orientacao))


def proporcao(tamanho_id: str, orientacao: str, papel_mm: tuple[float, float] | None = None) -> float:
    """Largura ÷ altura do papel na orientação (retrato = menor/maior; paisagem = maior/menor)."""
    largura, altura = _mm_na_orientacao(tamanho_id, orientacao, papel_mm)
    return largura / altura


def px(tamanho_id: str, orientacao: str, dpi: int = 300, papel_mm: tuple[float, float] | None = None) -> tuple[int, int]:
    """(largura, altura) em pixels exatos do papel: ``round(mm / 25,4 × dpi)``."""
    if dpi <= 0:
        raise ValueError(_("O dpi precisa ser maior que zero."))
    largura, altura = _mm_na_orientacao(tamanho_id, orientacao, papel_mm)
    return round(largura / MM_POR_POLEGADA * dpi), round(altura / MM_POR_POLEGADA * dpi)


def resolucao_efetiva(largura_recorte_px: int, tamanho_id: str, orientacao: str,
                      papel_mm: tuple[float, float] | None = None) -> float:
    """DPI efetivo: pixels do recorte na foto original ÷ polegadas da largura do papel."""
    largura_mm, _altura_mm = _mm_na_orientacao(tamanho_id, orientacao, papel_mm)
    return largura_recorte_px / (largura_mm / MM_POR_POLEGADA)


def qualidade(dpi: float) -> str:
    """"boa" (>= 200 dpi), "aceitavel" (150 a 199) ou "baixa" (< 150)."""
    if dpi >= 200:
        return "boa"
    if dpi >= 150:
        return "aceitavel"
    return "baixa"
