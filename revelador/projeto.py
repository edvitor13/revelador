"""Modelo do trabalho: fotos, impressões (tamanho, cópias, recorte) e ajustes.

Dados puros, sem Qt e sem acesso a disco: o mesmo modelo serve à interface, à receita de imagem, à exportação, ao
orçamento e ao arquivo ``.revelador``. Contrato em ``docs/ARQUITETURA.md`` (seção 2; JSON na seção 9).

Regras: nomes de campos em português sem acento e **nunca renomeados** (são as chaves do ``.revelador``); campo novo
com padrão neutro; coordenadas normalizadas (0..1). A gravação e a leitura do ``.revelador`` chegam com a #9.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

TAMANHO_PADRAO = "10x15"
DPI_PADRAO = 300
MARGEM_CORTE_MM_PADRAO = 2.0

ORIGENS_RECORTE = ("auto", "centro", "manual")
ORIENTACOES = ("auto", "retrato", "paisagem")
MODOS = ("preencher", "caber")


@dataclass
class Rosto:
    """Rosto detectado, em coordenadas normalizadas da imagem ORIENTADA (EXIF aplicado, sem giro de 90°)."""

    x: float
    y: float
    w: float
    h: float
    olhos: tuple[tuple[float, float], tuple[float, float]] | None = None
    confianca: float = 1.0


@dataclass
class Recorte:
    """Recorte de uma impressão. A proporção não fica aqui: vem do papel e da orientação da impressão."""

    cx: float = 0.5          # centro, normalizado à imagem orientada E girada (giro aplicado)
    cy: float = 0.5
    zoom: float = 1.0        # 1 = maior recorte possível na proporção do papel; 2 = metade da largura...
    angulo: float = 0.0      # endireitar, graus (-45..45), em torno do centro do recorte
    giro: int = 0            # giros de 90° no sentido horário (0..3), sem perda
    origem: str = "auto"     # "auto" (rostos) | "centro" (sem rosto) | "manual" (a pessoa mexeu)


@dataclass
class Impressao:
    """Uma foto num tamanho de papel, com a quantidade de cópias e o recorte próprio."""

    tamanho: str = TAMANHO_PADRAO   # id de tamanhos.TAMANHOS, ou "personalizado"
    copias: int = 1
    orientacao: str = "auto"        # "auto" (segue a foto) | "retrato" | "paisagem"
    modo: str = "preencher"         # "preencher" (corta na proporção) | "caber" (foto inteira com borda branca)
    recorte: Recorte = field(default_factory=Recorte)
    papel_mm: tuple[float, float] | None = None  # só no "personalizado": (lado menor, lado maior) em mm
    preco_centavos: int | None = None            # só no "personalizado": valor por cópia (seção 13)


@dataclass
class Foto:
    """Uma foto importada. Os ajustes valem para todas as impressões dela; o recorte é de cada impressão."""

    id: str
    caminho: Path
    bytes: int = 0
    mtime: float = 0.0
    selecionada: bool = False
    ajustes: dict[str, float] = field(default_factory=dict)     # só as chaves fora do padrão
    rostos: list[Rosto] | None = None                           # None = ainda não detectado; [] = nenhum
    impressoes: list[Impressao] = field(default_factory=list)   # vazia até a foto ser selecionada


@dataclass
class Trabalho:
    """O conjunto de fotos de um pedido de revelação."""

    fotos: list[Foto] = field(default_factory=list)
    tamanho_padrao: str = TAMANHO_PADRAO
    dpi: int = DPI_PADRAO
    margem_corte_mm: float = MARGEM_CORTE_MM_PADRAO
    caminho: Path | None = None     # o .revelador, quando salvo

    def selecionadas(self) -> list[Foto]:
        return [f for f in self.fotos if f.selecionada]
