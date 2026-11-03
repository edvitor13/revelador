"""Visualizar: passa pelas fotos e mostra como cada uma vai sair no papel, em cada tamanho que vai ser revelado.

Cada impressão é desenhada pela receita única (``RenderizarPrevia``, a mesma da prévia do editor), lado a lado,
com o rótulo "10x15 ×2" embaixo. ←/→ (ou os botões) passam as fotos; Esc fecha. Nada é alterado no trabalho.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QThreadPool, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from .. import receita
from ..i18n import _
from ..projeto import Foto
from .editor import rotulo_impressao
from .estado import Estado
from .previa import CarregarProxy, RenderizarPrevia, Sinais

ESPACO = 16   # px entre as impressões lado a lado


class VisualizarDialog(QDialog):
    """Tela de visualização: ``fotos`` na ordem dada, começando em ``inicio``."""

    def __init__(self, estado: Estado, fotos: list[Foto], inicio: int = 0, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.estado = estado
        self.fotos = fotos
        self.indice = max(0, min(inicio, len(fotos) - 1))
        self.setWindowTitle(_("Visualizar a revelação"))
        self.setObjectName("Panel")
        self.resize(1200, 820)
        self.sinais = Sinais(self)
        self.sinais.proxy_pronto.connect(self._proxy_pronto)
        self.sinais.proxy_erro.connect(lambda _g, _c, msg: self._aviso(msg))
        self.sinais.previa_pronta.connect(self._previa_pronta)
        self.sinais.previa_erro.connect(lambda _g, msg: self._aviso(msg))
        self._geracao = 0
        self._proxy = None
        self._imagens: dict[int, QLabel] = {}

        self.titulo = QLabel()
        self.titulo.setObjectName("PanelTitle")
        self.contador = QLabel()
        self.contador.setObjectName("Muted")
        self.area = QWidget()
        self.linha = QHBoxLayout(self.area)
        self.linha.setContentsMargins(0, 0, 0, 0)
        self.linha.setSpacing(ESPACO)
        self.botao_ant = QPushButton("‹  " + _("Anterior"))
        self.botao_prox = QPushButton(_("Próxima") + "  ›")
        self.botao_prox.setObjectName("Primary")
        for b in (self.botao_ant, self.botao_prox):
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
        self.botao_ant.clicked.connect(lambda: self.passar(-1))
        self.botao_prox.clicked.connect(lambda: self.passar(+1))
        topo = QHBoxLayout()
        topo.addWidget(self.titulo, 1)
        topo.addWidget(self.contador)
        base = QHBoxLayout()
        base.addWidget(self.botao_ant)
        dica = QLabel(_("← → passam as fotos · Esc fecha"))
        dica.setObjectName("Faint")
        base.addStretch(1)
        base.addWidget(dica)
        base.addStretch(1)
        base.addWidget(self.botao_prox)
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(20, 16, 20, 16)
        raiz.setSpacing(12)
        raiz.addLayout(topo)
        raiz.addWidget(self.area, 1)
        raiz.addLayout(base)
        self._timer = QTimer(self, singleShot=True, interval=80)
        self._timer.timeout.connect(self._renderizar)
        self.mostrar()

    # ------------------------------------------------------------ navegação
    @property
    def foto(self) -> Foto | None:
        return self.fotos[self.indice] if self.fotos else None

    def passar(self, passo: int) -> None:
        novo = max(0, min(len(self.fotos) - 1, self.indice + passo))
        if novo != self.indice:
            self.indice = novo
            self.mostrar()

    def keyPressEvent(self, e) -> None:  # noqa: N802 - nome do Qt
        if e.key() in (Qt.Key.Key_Left, Qt.Key.Key_Up, Qt.Key.Key_PageUp):
            self.passar(-1)
        elif e.key() in (Qt.Key.Key_Right, Qt.Key.Key_Down, Qt.Key.Key_PageDown, Qt.Key.Key_Space):
            self.passar(+1)
        else:
            super().keyPressEvent(e)

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        self._timer.start()

    # ------------------------------------------------------------ montagem
    def mostrar(self) -> None:
        """Monta a foto atual: título, uma coluna por impressão (imagem + rótulo) e pede o proxy."""
        self._geracao += 1
        self._proxy = None
        self._imagens.clear()
        while self.linha.count():
            item = self.linha.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        foto = self.foto
        self.botao_ant.setEnabled(self.indice > 0)
        self.botao_prox.setEnabled(self.indice < len(self.fotos) - 1)
        if foto is None:
            self.titulo.setText(_("Nenhuma foto marcada para revelação"))
            self.contador.clear()
            return
        self.titulo.setText(foto.caminho.name)
        self.contador.setText(_("{n} de {total}").format(n=self.indice + 1, total=len(self.fotos)))
        imps = foto.impressoes if foto.selecionada else []
        if not imps:
            self._aviso(_("Esta foto não está marcada para revelação."))
            return
        for n, imp in enumerate(imps):
            coluna = QVBoxLayout()
            imagem = QLabel(_("Carregando…"))
            imagem.setObjectName("Muted")
            imagem.setAlignment(Qt.AlignmentFlag.AlignCenter)
            imagem.setMinimumSize(80, 80)
            rotulo = QLabel(rotulo_impressao(imp))
            rotulo.setObjectName("PanelTitle")
            rotulo.setAlignment(Qt.AlignmentFlag.AlignCenter)
            caixa = QWidget()
            caixa.setLayout(coluna)
            coluna.setContentsMargins(0, 0, 0, 0)
            coluna.addWidget(imagem, 1)
            coluna.addWidget(rotulo)
            self.linha.addWidget(caixa, 1)
            self._imagens[n] = imagem
        QThreadPool.globalInstance().start(CarregarProxy(self.sinais, self._geracao, foto.caminho))

    def _aviso(self, texto: str) -> None:
        if not self._imagens:
            rotulo = QLabel(texto)
            rotulo.setObjectName("Muted")
            rotulo.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.linha.addWidget(rotulo, 1)
        else:
            for imagem in self._imagens.values():
                imagem.setText(texto)

    def _proxy_pronto(self, geracao: int, _caminho: str, proxy) -> None:
        if geracao != self._geracao:
            return
        self._proxy = proxy
        self._renderizar()

    def _renderizar(self) -> None:
        foto = self.foto
        if foto is None or self._proxy is None:
            return
        altura, largura = self._proxy.shape[:2]
        for n, imagem in self._imagens.items():
            imp = foto.impressoes[n]
            w, h = receita.destino_na_caixa(imp, largura, altura, imagem.width() - 8, imagem.height() - 8)
            ger = self._geracao * 1000 + n
            QThreadPool.globalInstance().start(RenderizarPrevia(self.sinais, ger, self._proxy, imp,
                                                                foto.ajustes, (w, h)))

    def _previa_pronta(self, geracao: int, imagem) -> None:
        if geracao // 1000 != self._geracao:
            return
        alvo = self._imagens.get(geracao % 1000)
        if alvo is not None:
            alvo.setPixmap(QPixmap.fromImage(imagem))


def fotos_para_visualizar(estado: Estado, visiveis: list[Foto]) -> list[Foto]:
    """As fotos marcadas para revelação, na ordem da grade (as visíveis primeiro, depois o resto do trabalho)."""
    ids = {f.id for f in visiveis}
    ordem = list(visiveis) + [f for f in estado.trabalho.fotos if f.id not in ids]
    return [f for f in ordem if f.selecionada and f.impressoes]
