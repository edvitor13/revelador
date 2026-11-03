"""Painel lateral de ajustes de luz e cor: um cartão por grupo de ``ajustes.GRUPOS``, gerado de ``ajustes.PARAMS``.

Lê e grava só pelo ``Estado`` (``docs/ARQUITETURA.md``, seções 7 e 10): os valores são os de ``estado.atual.ajustes``
(só as chaves fora do padrão; voltar ao padrão remove a chave). Mexer num controle muda o modelo e chama
``estado.alterar(foto)``; quem mostra o resultado é o editor, que reage ao sinal. Sem foto atual, o painel fica
desabilitado.

- Duplo clique no controle volta ao padrão; o botão do cartão restaura o grupo; "Restaurar todos" zera tudo.
- Antes/depois: segurar ``\\`` (ou o botão) liga ``estado.comparando``; o editor mostra a foto sem ajustes.
- Copiar/colar (Ctrl+Shift+C / Ctrl+Shift+V): colar vale para a foto atual ou, havendo várias fotos escolhidas na
  grade (``fotos_escolhidas``, opcional), para todas elas.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QGridLayout, QLineEdit, QSizePolicy, QVBoxLayout, QWidget

from .. import ajustes
from ..i18n import _
from ..projeto import Foto
from . import tema
from .componentes import Card, Slider, botao_plano
from .estado import Estado


class PainelAjustes(QWidget):
    """Os cartões Luz, Cor e Detalhe e os botões de antes/depois, copiar, colar e restaurar."""

    def __init__(self, estado: Estado, fotos_escolhidas: Callable[[], list[Foto]] | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("painel_ajustes")
        self.estado = estado
        self._fotos_escolhidas = fotos_escolhidas
        self._copiado: dict[str, float] | None = None   # área de transferência dos ajustes (só chaves fora do padrão)
        self._carregando = False
        self.sliders: dict[str, Slider] = {}
        self.cards: dict[str, Card] = {}

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(8)
        for grupo in ajustes.GRUPOS:
            card = Card(_(grupo), restaurar=True, dica_restaurar=_("Restaurar este grupo"))
            card.restaurar_pedido.connect(lambda g=grupo: self.restaurar_grupo(g))
            for p in (q for q in ajustes.PARAMS if q.grupo == grupo):
                s = Slider(_(p.nome), p.minimo, p.maximo, p.passo, p.padrao)
                s.valor_mudou.connect(lambda v, c=p.chave: self._mudou(c, v))
                card.adicionar(s)
                self.sliders[p.chave] = s
            raiz.addWidget(card)
            self.cards[grupo] = card

        # Quatro ações em grade 2x2, botões comuns com ícone (largura igual).
        grade = QGridLayout()
        grade.setHorizontalSpacing(8)
        grade.setVerticalSpacing(8)
        self.botao_comparar = botao_plano("comparar", _("Segure para ver a foto sem ajustes (\)"), _("Antes/depois"),
                                          tamanho=16, cor=tema.APAGADO, plano=False)
        self.botao_comparar.pressed.connect(lambda: self.estado.definir_comparando(True))
        self.botao_comparar.released.connect(lambda: self.estado.definir_comparando(False))
        self.botao_restaurar_todos = botao_plano("reset", _("Volta todos os ajustes ao padrão"), _("Restaurar todos"),
                                                 tamanho=16, cor=tema.APAGADO, plano=False)
        self.botao_restaurar_todos.clicked.connect(self.restaurar_todos)
        self.botao_copiar = botao_plano("copiar", _("Copia os ajustes desta foto (Ctrl+Shift+C)"), _("Copiar"),
                                        tamanho=16, cor=tema.APAGADO, plano=False)
        self.botao_copiar.clicked.connect(self.copiar)
        self.botao_colar = botao_plano("colar", _("Cola os ajustes copiados (Ctrl+Shift+V)"), _("Colar"),
                                       tamanho=16, cor=tema.APAGADO, plano=False)
        self.botao_colar.clicked.connect(self.colar)
        for i, b in enumerate((self.botao_comparar, self.botao_restaurar_todos, self.botao_copiar, self.botao_colar)):
            b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            b.setMinimumWidth(10)
            posicoes = ((0, 0, 1, 2), (2, 0, 1, 2), (1, 0, 1, 1), (1, 1, 1, 1))   # comparar, restaurar, copiar, colar
            grade.addWidget(b, *posicoes[i])
        raiz.addLayout(grade)

        for chave, slot in (("Ctrl+Shift+C", self.copiar), ("Ctrl+Shift+V", self.colar)):
            QShortcut(QKeySequence(chave), self, activated=slot, context=Qt.ShortcutContext.WindowShortcut)
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)   # segurar "\" para o antes/depois

        estado.atual_mudou.connect(lambda _foto: self.recarregar())
        estado.foto_mudou.connect(self._foto_mudou)
        self.recarregar()

    # ------------------------------------------------------------ do modelo para os controles
    def _foto_mudou(self, foto_id: str) -> None:
        if self.estado.atual is not None and self.estado.atual.id == foto_id:
            self.recarregar()

    def recarregar(self) -> None:
        """Mostra nos controles os ajustes da foto atual (padrão onde não há chave) e habilita/desabilita."""
        foto = self.estado.atual
        valores = ajustes.sanitizar(foto.ajustes) if foto is not None else {}
        self._carregando = True
        try:
            for p in ajustes.PARAMS:
                self.sliders[p.chave].definir_valor(valores.get(p.chave, p.padrao))
        finally:
            self._carregando = False
        self.setEnabled(foto is not None)
        self.botao_colar.setEnabled(foto is not None and self._copiado is not None)

    # ------------------------------------------------------------ dos controles para o modelo
    def _mudou(self, chave: str, valor: float) -> None:
        foto = self.estado.atual
        if foto is None or self._carregando:
            return
        param = next(p for p in ajustes.PARAMS if p.chave == chave)
        if float(valor) == param.padrao:
            foto.ajustes.pop(chave, None)
        else:
            foto.ajustes[chave] = float(valor)
        self.estado.alterar(foto)

    def restaurar_grupo(self, grupo: str) -> None:
        """Volta ao padrão todos os ajustes do grupo na foto atual."""
        foto = self.estado.atual
        if foto is None:
            return
        chaves = [p.chave for p in ajustes.PARAMS if p.grupo == grupo]
        if any(c in foto.ajustes for c in chaves):
            for c in chaves:
                foto.ajustes.pop(c, None)
            self.estado.alterar(foto)
        self.recarregar()

    def restaurar_todos(self) -> None:
        foto = self.estado.atual
        if foto is None:
            return
        if foto.ajustes:
            foto.ajustes.clear()
            self.estado.alterar(foto)
        self.recarregar()

    # ------------------------------------------------------------ copiar e colar
    def copiar(self) -> bool:
        """Guarda os ajustes da foto atual (só as chaves fora do padrão)."""
        if self._foco_em_campo() or self.estado.atual is None:
            return False
        self._copiado = ajustes.sanitizar(self.estado.atual.ajustes)
        self.botao_colar.setEnabled(True)
        return True

    def alvos_da_colagem(self) -> list[Foto]:
        """Várias fotos escolhidas na grade, se houver; senão só a atual."""
        escolhidas = self._fotos_escolhidas() if self._fotos_escolhidas is not None else []
        if len(escolhidas) > 1:
            return list(escolhidas)
        return [self.estado.atual] if self.estado.atual is not None else []

    def colar(self) -> int:
        """Aplica os ajustes copiados às fotos-alvo. Devolve quantas fotos mudaram."""
        if self._copiado is None or self._foco_em_campo():
            return 0
        n = 0
        for foto in self.alvos_da_colagem():
            novo = dict(self._copiado)
            if ajustes.sanitizar(foto.ajustes) != novo:
                foto.ajustes = novo
                self.estado.alterar(foto)
                n += 1
        self.recarregar()
        return n

    @staticmethod
    def _foco_em_campo() -> bool:
        """Num campo de texto, Ctrl+Shift+C/V é do campo, não dos ajustes."""
        return isinstance(QApplication.focusWidget(), QLineEdit)

    # ------------------------------------------------------------ antes/depois com a tecla "\"
    def eventFilter(self, obj: QObject, evento: QEvent) -> bool:  # noqa: N802 - nome do Qt
        tipo = evento.type()
        if tipo in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease) and not evento.isAutoRepeat() \
                and evento.key() == Qt.Key.Key_Backslash and not self._foco_em_campo():
            if tipo == QEvent.Type.KeyPress:
                if self.estado.atual is not None and self.window().isActiveWindow():
                    self.estado.definir_comparando(True)
            else:
                self.estado.definir_comparando(False)
        return False
