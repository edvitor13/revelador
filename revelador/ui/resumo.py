"""Resumo do pedido: texto da barra de status e a janela com a tabela por tamanho e o total estimado.

O valor é sempre uma **estimativa** (``docs/ARQUITETURA.md``, seção 13). O cálculo vem de ``precos.orcamento``.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QHBoxLayout, QLabel, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from .. import precos
from ..i18n import _
from ..precos import Orcamento
from ..projeto import Trabalho
from .estado import Estado
from .precos_dialog import PrecosDialog, tabela_precos


def _plural(n: int, singular: str, plural: str) -> str:
    return (singular if n == 1 else plural).format(n=n)


def nomes_sem_preco(orc: Orcamento) -> list[str]:
    return [linha.nome for linha in orc.linhas if linha.unitario is None]


def texto_barra(trabalho: Trabalho, orc: Orcamento) -> str:
    """"12 fotos · 18 cópias · R$ 45,60"; parcial: "… · R$ 30,00 (sem preço: 15x21)"; nada marcado: aviso curto."""
    if not orc.linhas:
        return _("Nenhuma foto selecionada para revelação")
    fotos = len([f for f in trabalho.selecionadas() if f.impressoes])
    copias = sum(linha.copias for linha in orc.linhas)
    partes = [_plural(fotos, _("{n} foto"), _("{n} fotos")), _plural(copias, _("{n} cópia"), _("{n} cópias"))]
    faltam = nomes_sem_preco(orc)
    aviso = _("sem preço: {tamanhos}").format(tamanhos=", ".join(faltam))
    if not faltam:
        partes.append(precos.formatar(orc.total))
    elif len(faltam) == len(orc.linhas):
        partes.append(aviso)
    else:
        partes.append(f"{precos.formatar(orc.total)} ({aviso})")
    return " · ".join(partes)


class ResumoDialog(QDialog):
    """"Resumo do pedido": tabela por tamanho (fotos, cópias, valor por cópia, subtotal), total e atalho aos preços."""

    def __init__(self, estado: Estado, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.estado = estado
        self.setWindowTitle(_("Resumo do pedido"))
        self.setMinimumSize(520, 340)
        raiz = QVBoxLayout(self)
        self.tabela = QTableWidget(0, 5)
        self.tabela.setHorizontalHeaderLabels(
            [_("Tamanho"), _("Fotos"), _("Cópias"), _("Valor por cópia"), _("Subtotal")])
        self.tabela.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabela.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.tabela.verticalHeader().hide()
        self.tabela.horizontalHeader().setStretchLastSection(True)
        raiz.addWidget(self.tabela, 1)
        self.rotulo_total = QLabel()
        fonte = self.rotulo_total.font()
        fonte.setBold(True)
        self.rotulo_total.setFont(fonte)
        raiz.addWidget(self.rotulo_total)
        self.rotulo_aviso = QLabel(_("Estimativa — confirme com o seu laboratório."))
        self.rotulo_aviso.setWordWrap(True)
        raiz.addWidget(self.rotulo_aviso)
        linha = QHBoxLayout()
        self.botao_precos = QPushButton(_("Editar preços…"))
        self.botao_precos.clicked.connect(self.editar_precos)
        linha.addWidget(self.botao_precos)
        linha.addStretch(1)
        fechar = QPushButton(_("Fechar"))
        fechar.clicked.connect(self.accept)
        linha.addWidget(fechar)
        raiz.addLayout(linha)
        estado.pedido_mudou.connect(self.atualizar)
        self.atualizar()

    def atualizar(self) -> None:
        orc = precos.orcamento(self.estado.trabalho, tabela_precos())
        self.tabela.setRowCount(len(orc.linhas))
        for i, linha in enumerate(orc.linhas):
            valores = [linha.nome, str(linha.fotos), str(linha.copias),
                       precos.formatar(linha.unitario) if linha.unitario is not None else _("sem preço"),
                       precos.formatar(linha.subtotal) if linha.subtotal is not None else "—"]
            for j, texto in enumerate(valores):
                item = QTableWidgetItem(texto)
                if j:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.tabela.setItem(i, j, item)
        if not orc.linhas:
            self.rotulo_total.setText(_("Nenhuma foto selecionada para revelação"))
        elif orc.completo:
            self.rotulo_total.setText(_("Total estimado: {valor}").format(valor=precos.formatar(orc.total)))
        else:
            self.rotulo_total.setText(_("Total estimado: {valor} + sem preço: {tamanhos}").format(
                valor=precos.formatar(orc.total), tamanhos=", ".join(nomes_sem_preco(orc))))

    def editar_precos(self) -> None:
        PrecosDialog(self.estado, self).exec()
