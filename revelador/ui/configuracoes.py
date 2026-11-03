"""Diálogo "Configurações" (engrenagem → Configurações…): preferências do app, em seções.

Cada seção é um ``Secao`` (um ``Card`` do tema) que sabe ``carregar()`` das preferências, ``validar()`` e
``aplicar()`` (gravar). O diálogo monta as seções de ``SECOES`` na ordem; para uma preferência nova, crie outra
subclasse de ``Secao`` (com ``id_secao`` único) e acrescente-a em ``SECOES``. Nada é gravado até "Salvar"
(``salvar()``, que os testes chamam sem ``exec()``); depois de gravar, o sinal ``aplicado`` avisa quem relê as
preferências (o salvamento automático reinicia o temporizador).

Seções de hoje: **Salvamento automático** (#34): ligado/desligado, intervalo em minutos e a pasta dos trabalhos novos.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QScrollArea, QSpinBox, QVBoxLayout, QWidget)

from ..i18n import _
from . import autosalvar, tema
from .componentes import Card, ToggleSwitch


class Secao(Card):
    """Uma seção do diálogo: subclasses definem ``id_secao`` (o ``Card`` já usa ``chave``), montam os controles
    e implementam ``carregar``, ``validar`` e ``aplicar``."""

    id_secao = ""

    def carregar(self) -> None:
        """Põe nos controles os valores salvos."""

    def validar(self) -> str | None:
        """Mensagem de erro (mostrada na seção) ou ``None`` se está tudo certo."""
        return None

    def aplicar(self) -> None:
        """Grava os valores dos controles nas preferências."""

    @staticmethod
    def linha(rotulo: str, *widgets: QWidget, dica: str = "") -> QWidget:
        """Linha "rótulo ............ controles" do corpo da seção."""
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        texto = QLabel(rotulo)
        if dica:
            texto.setToolTip(dica)
        lay.addWidget(texto, 1)
        for widget in widgets:
            lay.addWidget(widget)
        return w


class SecaoSalvamento(Secao):
    """Salvamento automático: chave liga/desliga, intervalo (minutos) e a pasta dos trabalhos novos."""

    id_secao = "salvamento"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(_("Salvamento automático"),
                         _("Grava o trabalho sozinho enquanto você mexe. As fotos originais nunca são alteradas."),
                         restaurar=True, dica_restaurar=_("Voltar ao padrão"), parent=parent)
        self.ligado = ToggleSwitch()
        self.ligado.setAccessibleName(_("Salvar automaticamente"))
        self.adicionar(self.linha(_("Salvar automaticamente"), self.ligado,
                                  dica=_("Ao fechar, o trabalho é salvo sem perguntar.")))

        self.intervalo = QSpinBox()
        self.intervalo.setRange(autosalvar.INTERVALO_MIN, autosalvar.INTERVALO_MAX)
        self.intervalo.setSuffix(" " + _("min"))
        self.intervalo.setAccessibleName(_("Intervalo do salvamento automático, em minutos"))
        self.intervalo.setMinimumWidth(90)
        self.linha_intervalo = self.linha(_("Salvar a cada"), self.intervalo)
        self.adicionar(self.linha_intervalo)

        rotulo_pasta = QLabel(_("Pasta dos trabalhos novos"))
        ajuda = QLabel(_("Trabalhos que ainda não têm arquivo são salvos aqui, com um nome automático. "
                         "Use “Salvar como…” para dar outro nome ou lugar."))
        ajuda.setObjectName("Faint")
        ajuda.setWordWrap(True)
        self.campo_pasta = QLineEdit()
        self.campo_pasta.setReadOnly(True)
        self.campo_pasta.setAccessibleName(_("Pasta dos trabalhos novos"))
        self.botao_pasta = QPushButton(_("Escolher…"))
        self.botao_pasta.setCursor(Qt.CursorShape.PointingHandCursor)
        self.botao_pasta.clicked.connect(lambda _c=False: self.trocar_pasta())
        linha_campo = QWidget()
        lay = QHBoxLayout(linha_campo)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        lay.addWidget(self.campo_pasta, 1)
        lay.addWidget(self.botao_pasta)
        self.bloco_pasta = QWidget()
        bloco = QVBoxLayout(self.bloco_pasta)
        bloco.setContentsMargins(0, 6, 0, 0)
        bloco.setSpacing(4)
        bloco.addWidget(rotulo_pasta)
        bloco.addWidget(linha_campo)
        bloco.addWidget(ajuda)
        self.adicionar(self.bloco_pasta)

        self.ligado.toggled.connect(self._sincronizar)
        self.restaurar_pedido.connect(self.restaurar_padrao)
        self.carregar()

    # ------------------------------------------------------------ valores
    @property
    def pasta(self) -> Path:
        return Path(self.campo_pasta.text())

    def definir_pasta(self, pasta: Path | str) -> None:
        self.campo_pasta.setText(str(pasta))
        self.campo_pasta.setToolTip(str(pasta))
        self.campo_pasta.setCursorPosition(0)

    def escolher_pasta(self) -> Path | None:
        """Diálogo de pasta (os testes substituem)."""
        nome = QFileDialog.getExistingDirectory(self, _("Pasta dos trabalhos novos"), str(self.pasta))
        return Path(nome) if nome else None

    def trocar_pasta(self) -> None:
        escolhida = self.escolher_pasta()
        if escolhida is not None:
            self.definir_pasta(escolhida)

    def _sincronizar(self, ligado: bool) -> None:
        self.linha_intervalo.setEnabled(ligado)
        self.bloco_pasta.setEnabled(ligado)

    def restaurar_padrao(self) -> None:
        self.ligado.setChecked(True)
        self.intervalo.setValue(autosalvar.INTERVALO_PADRAO_MIN)
        self.definir_pasta(autosalvar.pasta_padrao())

    # ------------------------------------------------------------ Secao
    def carregar(self) -> None:
        self.ligado.setChecked(autosalvar.ligado())
        self.intervalo.setValue(autosalvar.intervalo_min())
        self.definir_pasta(autosalvar.pasta_trabalhos())
        self._sincronizar(self.ligado.isChecked())

    def validar(self) -> str | None:
        if not self.campo_pasta.text().strip():
            return _("Escolha a pasta dos trabalhos novos.")
        return None

    def aplicar(self) -> None:
        autosalvar.gravar_preferencias(ligar=self.ligado.isChecked(), minutos=self.intervalo.value(),
                                       pasta=self.pasta)


SECOES: list[type[Secao]] = [SecaoSalvamento]


class ConfiguracoesDialog(QDialog):
    """As seções de ``SECOES`` numa coluna rolável, com Salvar/Cancelar. ``secoes``: {id_secao: Secao}."""

    aplicado = Signal()

    def __init__(self, parent: QWidget | None = None, secoes: list[type[Secao]] | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("Configurações"))
        self.setMinimumWidth(520)
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(22, 20, 22, 18)
        raiz.setSpacing(14)

        corpo = QWidget()
        coluna = QVBoxLayout(corpo)
        coluna.setContentsMargins(0, 0, 0, 0)
        coluna.setSpacing(12)
        self.secoes: dict[str, Secao] = {}
        for classe in (secoes if secoes is not None else SECOES):
            secao = classe()
            self.secoes[secao.id_secao] = secao
            coluna.addWidget(secao)
        coluna.addStretch(1)
        rolagem = QScrollArea()
        rolagem.setWidgetResizable(True)
        rolagem.setFrameShape(QScrollArea.Shape.NoFrame)
        rolagem.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        rolagem.setWidget(corpo)
        raiz.addWidget(rolagem, 1)

        self.erro = QLabel()
        self.erro.setStyleSheet(f"color: {tema.PERIGO};")
        self.erro.setWordWrap(True)
        self.erro.hide()
        raiz.addWidget(self.erro)

        botoes = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        botoes.button(QDialogButtonBox.StandardButton.Ok).setText(_("Salvar"))
        botoes.button(QDialogButtonBox.StandardButton.Cancel).setText(_("Cancelar"))
        botoes.accepted.connect(self.accept)
        botoes.rejected.connect(self.reject)
        raiz.addWidget(botoes)

    def salvar(self) -> bool:
        """Valida todas as seções e grava; com erro, mostra a mensagem e devolve ``False`` (nada é gravado)."""
        for secao in self.secoes.values():
            erro = secao.validar()
            if erro:
                self.erro.setText(erro)
                self.erro.show()
                return False
        self.erro.hide()
        for secao in self.secoes.values():
            secao.aplicar()
        self.aplicado.emit()
        return True

    def accept(self) -> None:
        if self.salvar():
            super().accept()
