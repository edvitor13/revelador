"""Preços da revelação: leitura e formatação de valores em reais, e a previsão do custo do pedido.

Dinheiro é sempre ``int`` em centavos (regra 16 do ``AGENTS.md``): nunca ``float``, nem para converter. O texto
("R$ 1.234,56") só existe em ``ler()`` e ``formatar()``. Funções puras, sem Qt. Contrato em
``docs/ARQUITETURA.md`` (seção 13). O valor é sempre uma **estimativa**.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field

from . import tamanhos
from .i18n import _
from .projeto import Impressao, Trabalho

_RE_VALOR = re.compile(r"(?P<reais>[0-9]{1,3}(?:\.[0-9]{3})+|[0-9]+)(?:,(?P<centavos>[0-9]{1,2}))?")
_POSICAO = {t.id: i for i, t in enumerate(tamanhos.TAMANHOS)}


def ler(texto: str) -> int | None:
    """Converte o texto digitado em reais para centavos. "" ou só espaços → None (sem preço).

    Aceita "1,5", "1,50", "2", "R$ 2", "1.234,56" e espaços. Recusa o resto, inclusive 3 casas decimais.
    """
    limpo = texto.strip()
    if limpo[:2].upper() == "R$":
        limpo = limpo[2:].strip()
    if not limpo:
        return None
    if limpo.startswith("-"):
        raise ValueError(_("O valor não pode ser negativo."))
    m = _RE_VALOR.fullmatch(limpo)
    if m is None:
        raise ValueError(_("Valor inválido: use algo como 1,50 ou 12,00."))
    reais = int(m["reais"].replace(".", ""))
    centavos = int((m["centavos"] or "0").ljust(2, "0"))
    return reais * 100 + centavos


def formatar(centavos: int) -> str:
    """Centavos para texto em reais: "R$ 1.234,56". Não depende da localidade do sistema."""
    if isinstance(centavos, bool) or not isinstance(centavos, int):
        raise TypeError(_("O valor precisa ser um inteiro em centavos."))
    sinal = "-" if centavos < 0 else ""
    reais, cent = divmod(abs(centavos), 100)
    return f"{sinal}R$ {reais:,}".replace(",", ".") + f",{cent:02d}"


def _sem_zeros(mm: float) -> str:
    return f"{mm:.6f}".rstrip("0").rstrip(".")


def chave_preco(impressao: Impressao) -> str:
    """Id do tamanho, ou ``personalizado-<menor>x<maior>`` em mm (lados ordenados, sem zeros inúteis)."""
    if impressao.tamanho != tamanhos.PERSONALIZADO:
        return impressao.tamanho
    menor, maior = tamanhos.papel_mm(tamanhos.PERSONALIZADO, impressao.papel_mm)
    return f"{tamanhos.PERSONALIZADO}-{_sem_zeros(menor)}x{_sem_zeros(maior)}"


@dataclass
class LinhaOrcamento:
    tamanho: str              # id (ou "personalizado-<w>x<h>")
    nome: str                 # "10x15"
    fotos: int                # fotos diferentes nesse tamanho
    copias: int               # soma das cópias
    unitario: int | None      # centavos por cópia; None = sem preço
    subtotal: int | None      # unitario × copias


@dataclass
class Orcamento:
    linhas: list[LinhaOrcamento]   # na ordem da tabela de tamanhos
    total: int                     # soma dos subtotais conhecidos
    completo: bool                 # False se algum tamanho usado está sem preço


@dataclass
class _Grupo:
    tamanho: str
    nome: str
    unitario: int | None
    ordem: tuple
    fotos: set[str] = field(default_factory=set)
    copias: int = 0


def orcamento(trabalho: Trabalho, tabela: Mapping[str, int]) -> Orcamento:
    """Previsão do pedido: só fotos selecionadas; cada impressão conta ``copias``.

    ``tabela`` mapeia id do tamanho para centavos por cópia. O personalizado usa o ``preco_centavos`` da própria
    impressão (a tabela não vale para ele) e agrupa por papel + preço. Tamanho sem preço deixa o total parcial.
    """
    grupos: dict[tuple[str, int | None], _Grupo] = {}
    for foto in trabalho.selecionadas():
        for imp in foto.impressoes:
            if imp.tamanho == tamanhos.PERSONALIZADO:
                menor, maior = tamanhos.papel_mm(imp.tamanho, imp.papel_mm)
                chave = (chave_preco(imp), imp.preco_centavos)
                grupo = grupos.get(chave) or _Grupo(
                    tamanho=chave[0],
                    nome=_("Personalizado {menor}x{maior} mm").format(menor=_sem_zeros(menor), maior=_sem_zeros(maior)),
                    unitario=imp.preco_centavos,
                    ordem=(1, menor, maior, imp.preco_centavos is None, imp.preco_centavos or 0),
                )
            else:
                t = tamanhos.obter(imp.tamanho)
                chave = (t.id, None)
                grupo = grupos.get(chave) or _Grupo(
                    tamanho=t.id,
                    nome=_(t.nome),
                    unitario=tabela.get(t.id),
                    ordem=(0, _POSICAO[t.id]),
                )
            grupos[chave] = grupo
            grupo.fotos.add(foto.id)
            grupo.copias += imp.copias

    linhas = [
        LinhaOrcamento(
            tamanho=g.tamanho,
            nome=g.nome,
            fotos=len(g.fotos),
            copias=g.copias,
            unitario=g.unitario,
            subtotal=None if g.unitario is None else g.unitario * g.copias,
        )
        for g in sorted(grupos.values(), key=lambda g: g.ordem)
    ]
    total = sum((linha.subtotal for linha in linhas if linha.subtotal is not None), 0)
    completo = all(linha.unitario is not None for linha in linhas)
    return Orcamento(linhas=linhas, total=total, completo=completo)
