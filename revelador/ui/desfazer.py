"""Desfazer/refazer do trabalho (#5): passos de antes/depois sobre "fotografias" do estado editável.

O ``Estado`` guarda uma fotografia do que a pessoa edita em cada foto (``selecionada``, cópia profunda de
``impressoes`` e de ``ajustes``) e de ``trabalho.pastas``. Quando alguém avisa uma mudança (``alterar``,
``alterar_pastas``, ``remover``), o ``Estado`` compara com a fotografia anterior e, se mudou, empilha um ``Passo``
com o antes e o depois. Desfazer/refazer só recoloca fotografias (e refaz os recortes automáticos, que dependem dos
metadados e dos rostos do momento); nada aqui conhece widget.

Este módulo tem só os dados e o comando do ``QUndoStack``; a pilha, os lotes e a junção de passos ficam no
``Estado``. ``ligar_gestos`` liga o começo/fim de um gesto (apertar/soltar o mouse) a ``comecar_gesto``/``fim_gesto``.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QUndoCommand

from ..i18n import _
from ..imagem import InfoFoto
from ..projeto import Foto, Impressao, Pasta

if TYPE_CHECKING:
    from pathlib import Path

    from .estado import Estado


@dataclass
class Fotografia:
    """O que a pessoa edita numa foto: marca de revelação, impressões (com recortes) e ajustes."""

    selecionada: bool
    impressoes: list[Impressao]
    ajustes: dict[str, float]


def fotografar(foto: Foto) -> Fotografia:
    return Fotografia(foto.selecionada, copy.deepcopy(foto.impressoes), dict(foto.ajustes))


def restaurar(foto: Foto, f: Fotografia) -> None:
    """Põe a fotografia na foto (cópias novas: o passo guardado nunca é alterado por quem mexer na foto depois)."""
    foto.selecionada = f.selecionada
    foto.impressoes = copy.deepcopy(f.impressoes)
    foto.ajustes = dict(f.ajustes)


@dataclass
class MudancaFoto:
    foto_id: str
    antes: Fotografia
    depois: Fotografia


@dataclass
class MudancaPastas:
    antes: list[Pasta]
    depois: list[Pasta]


@dataclass
class MudancaRemocao:
    """Fotos tiradas do trabalho: posição original e o que o ``Estado`` sabia delas (para pôr de volta igual)."""

    itens: list[tuple[int, Foto]]                       # (posição em trabalho.fotos, foto), posições crescentes
    info: dict[str, InfoFoto] = field(default_factory=dict)
    miniaturas: dict[str, Path] = field(default_factory=dict)
    erros: dict[str, str] = field(default_factory=dict)


Mudanca = MudancaFoto | MudancaPastas | MudancaRemocao


def _descrever_foto(m: MudancaFoto) -> str:
    a, d = m.antes, m.depois
    if a.selecionada != d.selecionada:
        return _("marcação") if d.selecionada else _("desmarcação")
    if a.ajustes != d.ajustes:
        return _("ajustes")
    if len(a.impressoes) != len(d.impressoes):
        return _("novo tamanho") if len(d.impressoes) > len(a.impressoes) else _("remoção de tamanho")
    for ia, idp in zip(a.impressoes, d.impressoes):
        if (ia.tamanho, ia.papel_mm, ia.preco_centavos) != (idp.tamanho, idp.papel_mm, idp.preco_centavos):
            return _("tamanho")
        if ia.copias != idp.copias:
            return _("cópias")
        if ia.orientacao != idp.orientacao:
            return _("orientação")
        if ia.modo != idp.modo:
            return _("modo de impressão")
    for ia, idp in zip(a.impressoes, d.impressoes):
        if ia.recorte != idp.recorte:
            return _("enquadramento")
    return _("impressões")


def descrever(mudancas: list[Mudanca]) -> str:
    """Texto curto do passo para "Desfazer {texto}" (ex.: "cópias", "tamanho em 3 fotos")."""
    textos: list[str] = []
    for m in mudancas:
        if isinstance(m, MudancaFoto):
            textos.append(_descrever_foto(m))
        elif isinstance(m, MudancaPastas):
            textos.append(_("pastas"))
        else:
            n = len(m.itens)
            textos.append(_("remoção da foto") if n == 1 else _("remoção de {n} fotos").format(n=n))
    unicos = list(dict.fromkeys(textos))
    texto = unicos[0] if len(unicos) == 1 else _("várias mudanças")
    n = len({m.foto_id for m in mudancas if isinstance(m, MudancaFoto)})
    if n > 1 and not any(isinstance(m, MudancaRemocao) for m in mudancas):
        texto = _("{acao} em {n} fotos").format(acao=texto, n=n)
    return texto


class Passo(QUndoCommand):
    """Um passo da pilha: uma lista de mudanças (várias num lote). O ``Estado`` aplica antes/depois."""

    def __init__(self, estado: Estado, texto: str, mudancas: list[Mudanca]) -> None:
        super().__init__(texto)
        self.estado = estado
        self.mudancas = mudancas
        self._primeiro = True   # o push chama redo(), mas a mudança já está no modelo

    def redo(self) -> None:
        if self._primeiro:
            self._primeiro = False
            return
        self.estado._aplicar_mudancas(self.mudancas, depois=True)   # noqa: SLF001

    def undo(self) -> None:
        self.estado._aplicar_mudancas(list(reversed(self.mudancas)), depois=False)   # noqa: SLF001

    def juntar(self, m: MudancaFoto) -> None:
        """Mais uma chamada do mesmo gesto: fica o antes do começo e o depois mais recente."""
        self.mudancas[0].depois = m.depois


class FiltroGesto(QObject):
    """Apertar o botão esquerdo começa um gesto e soltar termina (as mudanças no meio viram um passo só)."""

    def __init__(self, estado: Estado, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.estado = estado

    def eventFilter(self, _obj: QObject, evento: QEvent) -> bool:  # noqa: N802 - nome do Qt
        tipo = evento.type()
        if tipo in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease) \
                and evento.button() == Qt.MouseButton.LeftButton:
            if tipo == QEvent.Type.MouseButtonPress:
                self.estado.comecar_gesto()
            else:
                self.estado.fim_gesto()
        return False


def ligar_gestos(estado: Estado, *widgets: QObject) -> FiltroGesto:
    """Instala o ``FiltroGesto`` nos widgets (visor do editor, trilhos dos sliders...). Devolve o filtro."""
    filtro = FiltroGesto(estado, widgets[0] if widgets else None)
    for w in widgets:
        w.installEventFilter(filtro)
    return filtro
