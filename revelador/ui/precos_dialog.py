"""Tabela de preços do laboratório: leitura/gravação nas preferências e o diálogo "Preços da revelação".

A tabela vale para todos os trabalhos e fica no grupo ``precos`` das preferências (``prefs.settings()``): uma chave
por id de tamanho, valor em **centavos inteiros** (regra 16 do ``AGENTS.md``); tamanho sem preço = sem chave.
O tamanho personalizado não entra aqui: leva o valor na própria impressão (``Impressao.preco_centavos``).
"""

from __future__ import annotations

from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)

from .. import precos, tamanhos
from ..i18n import _
from . import prefs, tema
from .estado import Estado

GRUPO = "precos"


def tabela_precos() -> dict[str, int]:
    """Preços por cópia salvos (id do tamanho -> centavos). Valores inválidos são ignorados."""
    s = prefs.settings()
    s.beginGroup(GRUPO)
    tabela: dict[str, int] = {}
    for chave in s.childKeys():
        try:
            centavos = int(s.value(chave))
        except (TypeError, ValueError):
            continue
        if centavos >= 0:
            tabela[chave] = centavos
    s.endGroup()
    return tabela


def salvar_tabela_precos(tabela: dict[str, int]) -> None:
    """Grava a tabela inteira no grupo ``precos`` (o que não está em ``tabela`` deixa de ter preço)."""
    for centavos in tabela.values():
        if isinstance(centavos, bool) or not isinstance(centavos, int) or centavos < 0:
            raise ValueError(_("O preço precisa ser um inteiro em centavos."))
    s = prefs.settings()
    s.remove(GRUPO)
    for tamanho_id, centavos in tabela.items():
        s.setValue(f"{GRUPO}/{tamanho_id}", centavos)
    s.sync()


class PrecosDialog(QDialog):
    """Um campo em reais por tamanho da tabela; vazio = sem preço. Erro de texto aparece na própria linha."""

    def __init__(self, estado: Estado | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.estado = estado
        self.setWindowTitle(_("Preços da revelação"))
        self.setMinimumWidth(420)
        self.campos: dict[str, QLineEdit] = {}
        self.erros: dict[str, QLabel] = {}

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(22, 20, 22, 18)
        raiz.setSpacing(14)
        aviso = QLabel(_("Valor cobrado por cópia em cada tamanho. Deixe vazio para tamanho sem preço. "
                         "O total do pedido é sempre uma estimativa."))
        aviso.setObjectName("Muted")
        aviso.setWordWrap(True)
        raiz.addWidget(aviso)

        corpo = QWidget()
        form = QFormLayout(corpo)
        form.setContentsMargins(0, 0, 12, 0)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)
        atual = tabela_precos()
        for t in tamanhos.TAMANHOS:
            campo = QLineEdit()
            campo.setPlaceholderText(_("sem preço"))
            campo.setObjectName(f"preco_{t.id}")
            if t.id in atual:
                campo.setText(precos.formatar(atual[t.id]).removeprefix("R$ "))
            erro = QLabel()
            erro.setStyleSheet(f"color: {tema.PERIGO};")
            erro.hide()
            campo.textChanged.connect(lambda _t, i=t.id: self.erros[i].hide())
            caixa = QVBoxLayout()
            caixa.setSpacing(0)
            caixa.addWidget(campo)
            caixa.addWidget(erro)
            form.addRow(_(t.nome) + " (R$)", caixa)
            self.campos[t.id] = campo
            self.erros[t.id] = erro
        rolagem = QScrollArea()
        rolagem.setWidgetResizable(True)
        rolagem.setWidget(corpo)
        raiz.addWidget(rolagem, 1)
        ajuda = QLabel(_(tamanhos.AJUDA))
        ajuda.setWordWrap(True)
        ajuda.setObjectName("Faint")
        raiz.addWidget(ajuda)

        self.botao_limpar = QPushButton(_("Limpar"))
        self.botao_limpar.clicked.connect(self.limpar)
        botoes = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        botoes.addButton(self.botao_limpar, QDialogButtonBox.ButtonRole.ResetRole)
        botoes.button(QDialogButtonBox.StandardButton.Ok).setText(_("Salvar"))
        botoes.button(QDialogButtonBox.StandardButton.Cancel).setText(_("Cancelar"))
        botoes.accepted.connect(self.accept)
        botoes.rejected.connect(self.reject)
        raiz.addWidget(botoes)

    def limpar(self) -> None:
        """Esvazia todos os campos (só grava ao confirmar)."""
        for campo in self.campos.values():
            campo.clear()

    def salvar(self) -> bool:
        """Valida, grava nas preferências e avisa o ``Estado``. Com erro, mostra-o na linha e devolve False."""
        tabela: dict[str, int] = {}
        ok = True
        for tamanho_id, campo in self.campos.items():
            try:
                centavos = precos.ler(campo.text())
            except ValueError as e:
                self.erros[tamanho_id].setText(str(e))
                self.erros[tamanho_id].show()
                ok = False
                continue
            if centavos is not None:
                tabela[tamanho_id] = centavos
        if not ok:
            return False
        salvar_tabela_precos(tabela)
        if self.estado is not None:
            self.estado.pedido_mudou.emit()
        return True

    def accept(self) -> None:
        if self.salvar():
            super().accept()
