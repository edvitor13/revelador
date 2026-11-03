"""Fotos repetidas: procura em segundo plano e janela para decidir, grupo a grupo, se mantém todas ou unifica.

Unificar junta numa foto só as impressões (tamanhos e cópias) das outras e tira as outras do trabalho; o arquivo
original nunca é tocado. Fotos duplicadas de propósito (mesmo arquivo, "Duplicar foto") não contam como repetidas.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel, QScrollArea,
                               QVBoxLayout, QWidget)

from .. import repetidas
from ..i18n import _
from ..projeto import Foto
from .estado import Estado

LADO_MINIATURA = 96


class _Sinais(QObject):
    pronto = Signal(object)   # list[list[str]]: grupos de ids de fotos


class _Procurar(QRunnable):
    def __init__(self, sinais: _Sinais, itens: list[tuple[str, Path]]) -> None:
        super().__init__()
        self.sinais, self.itens = sinais, itens

    def run(self) -> None:
        pares = [(i, a) for i, c in self.itens if (a := repetidas.assinatura_do_arquivo(c)) is not None]
        self.sinais.pronto.emit(repetidas.agrupar(pares))


def procurar(estado: Estado, ao_terminar) -> _Sinais:
    """Procura as repetidas fora da thread da interface (pelas miniaturas do cache); ``ao_terminar(grupos)`` recebe os
    grupos de ids. Uma foto por arquivo (as duplicadas de propósito ficam de fora)."""
    vistos: set[str] = set()
    itens: list[tuple[str, Path]] = []
    for foto in estado.trabalho.fotos:
        chave = str(foto.caminho).casefold()
        mini = estado.miniaturas.get(foto.id)
        if mini is not None and chave not in vistos:
            vistos.add(chave)
            itens.append((foto.id, mini))
    sinais = _Sinais()
    sinais.pronto.connect(ao_terminar)
    QThreadPool.globalInstance().start(_Procurar(sinais, itens))
    return sinais


class RepetidasDialog(QDialog):
    """Um cartão por grupo de fotos parecidas, com as miniaturas e a escolha: "Manter todas" ou "Unificar em …"."""

    def __init__(self, estado: Estado, grupos: list[list[str]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.estado = estado
        self.setWindowTitle(_("Fotos repetidas"))
        self.resize(720, 560)
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(20, 18, 20, 16)
        raiz.setSpacing(12)
        aviso = QLabel(_("Estas fotos são arquivos diferentes, mas parecem a mesma imagem. Escolha, em cada grupo, "
                         "se continua com todas ou se unifica numa só (os tamanhos e cópias passam para ela e as "
                         "outras saem do trabalho; nenhum arquivo é apagado)."))
        aviso.setWordWrap(True)
        aviso.setObjectName("Muted")
        raiz.addWidget(aviso)
        conteudo = QWidget()
        coluna = QVBoxLayout(conteudo)
        coluna.setContentsMargins(0, 0, 0, 0)
        coluna.setSpacing(10)
        self.grupos: list[tuple[list[Foto], QComboBox]] = []
        for ids in grupos:
            fotos = [f for f in (estado.por_id(i) for i in ids) if f is not None]
            if len(fotos) > 1:
                coluna.addWidget(self._cartao(fotos))
        coluna.addStretch(1)
        rolagem = QScrollArea()
        rolagem.setWidgetResizable(True)
        rolagem.setFrameShape(QScrollArea.Shape.NoFrame)
        rolagem.setWidget(conteudo)
        raiz.addWidget(rolagem, 1)
        botoes = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        botoes.button(QDialogButtonBox.StandardButton.Ok).setText(_("Aplicar"))
        botoes.button(QDialogButtonBox.StandardButton.Ok).setObjectName("Primary")
        botoes.button(QDialogButtonBox.StandardButton.Cancel).setText(_("Fechar"))
        botoes.accepted.connect(self.accept)
        botoes.rejected.connect(self.reject)
        raiz.addWidget(botoes)

    def _cartao(self, fotos: list[Foto]) -> QFrame:
        cartao = QFrame()
        cartao.setObjectName("Card")
        coluna = QVBoxLayout(cartao)
        coluna.setContentsMargins(12, 10, 12, 10)
        linha = QHBoxLayout()
        linha.setSpacing(10)
        for foto in fotos:
            linha.addWidget(self._miniatura(foto))
        linha.addStretch(1)
        coluna.addLayout(linha)
        escolha = QComboBox()
        escolha.addItem(_("Manter todas"), None)
        for foto in fotos:
            escolha.addItem(_("Unificar em “{nome}”").format(nome=foto.caminho.name), foto.id)
        coluna.addWidget(escolha)
        self.grupos.append((fotos, escolha))
        return cartao

    def _miniatura(self, foto: Foto) -> QWidget:
        caixa = QWidget()
        coluna = QVBoxLayout(caixa)
        coluna.setContentsMargins(0, 0, 0, 0)
        coluna.setSpacing(4)
        imagem = QLabel()
        imagem.setFixedSize(QSize(LADO_MINIATURA, LADO_MINIATURA))
        imagem.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mini = self.estado.miniaturas.get(foto.id)
        if mini is not None:
            pm = QPixmap(str(mini))
            if not pm.isNull():
                imagem.setPixmap(pm.scaled(LADO_MINIATURA, LADO_MINIATURA, Qt.AspectRatioMode.KeepAspectRatio,
                                           Qt.TransformationMode.SmoothTransformation))
        nome = QLabel(foto.caminho.name)
        nome.setObjectName("Muted")
        nome.setToolTip(str(foto.caminho))
        nome.setMaximumWidth(LADO_MINIATURA + 30)
        coluna.addWidget(imagem)
        coluna.addWidget(nome)
        return caixa

    def aplicar(self) -> int:
        """Unifica os grupos escolhidos; devolve quantas fotos saíram do trabalho."""
        tiradas = 0
        with self.estado.lote(_("unificar fotos repetidas")):
            for fotos, escolha in self.grupos:
                alvo = self.estado.por_id(escolha.currentData()) if escolha.currentData() else None
                if alvo is not None:
                    outras = [f for f in fotos if f is not alvo]
                    self.estado.unificar(alvo, outras)
                    tiradas += len(outras)
        return tiradas

    def accept(self) -> None:
        self.aplicar()
        super().accept()
