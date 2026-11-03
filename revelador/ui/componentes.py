"""Componentes próprios da interface: chave liga/desliga, seletor segmentado, cartão recolhível e slider.

Todos usam só as cores e os nomes de objeto de ``tema.py`` e o texto vem de quem os cria (já traduzido por ``_()``).

- ``ToggleSwitch``: chave liga/desliga animada (um ``QAbstractButton`` marcável: ``toggled``, ``isChecked``).
- ``Segmented``: botões lado a lado, um só marcado; sinal ``mudou(chave)``.
- ``Card``: cartão com título, subtítulo e botão de restaurar opcionais; o corpo recolhe ao clicar no cabeçalho.
- ``Slider``: rótulo, valor editável e trilho; duplo clique volta ao padrão; sinal ``valor_mudou(float)``.
- ``Pilula``: botão arredondado cujo texto encurta no meio (com "…") quando falta lugar.
- ``BarraAdaptavel``: barra de uma linha que encolhe em etapas (só ícones, depois some o que é opcional).
- ``botao_plano``: botão ``Flat`` com ícone (e texto opcional).
"""

from __future__ import annotations

from PySide6.QtCore import (Property, QEasingCurve, QEvent, QPointF, QPropertyAnimation, QRectF, QSize, Qt, QTimer,
                            Signal)
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen, QTransform
from PySide6.QtWidgets import (QAbstractButton, QButtonGroup, QFrame, QHBoxLayout, QLabel, QLayout, QLineEdit,
                               QPushButton, QSizePolicy, QToolButton, QVBoxLayout, QWidget)

from . import icones, tema


def botao_plano(icone: str, dica: str = "", texto: str = "", marcavel: bool = False, tamanho: int = 18,
                cor: str = tema.TEXTO, cor_marcado: str | None = None, plano: bool = True) -> QToolButton:
    """Botão ``Flat`` com o ícone `icone` (de ``icones.py``) e, se `texto`, o texto ao lado.

    Com `marcavel`, o ícone muda para `cor_marcado` (se dado) quando o botão está marcado. Com ``plano=False`` o
    botão mantém a borda (botão comum)."""
    b = QToolButton()
    if plano:
        b.setObjectName("Flat")
    if cor_marcado:
        b.setIcon(icones.icone_dois_estados(icone, cor, cor_marcado, tamanho))
    else:
        b.setIcon(icones.icone(icone, cor, tamanho))
    b.setIconSize(QSize(tamanho, tamanho))
    b.setToolTip(dica)
    b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setCheckable(marcavel)
    if texto:
        b.setText(texto)
        b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    return b


def com_menu(botao: QToolButton, menu) -> QToolButton:
    """Liga `menu` ao botão (abre ao clicar) e liga a setinha de menu do tema."""
    botao.setMenu(menu)
    botao.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    botao.setProperty("menu", True)
    return botao


def _mistura(a: str, b: str, t: float) -> QColor:
    ca, cb = QColor(a), QColor(b)
    return QColor(int(ca.red() + (cb.red() - ca.red()) * t), int(ca.green() + (cb.green() - ca.green()) * t),
                  int(ca.blue() + (cb.blue() - ca.blue()) * t))


# ------------------------------------------------------------------ chave liga/desliga
class ToggleSwitch(QAbstractButton):
    """Chave liga/desliga (38x22): trilho cinza que vira laranja e botão que desliza."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self._p = 0.0
        self._anim = QPropertyAnimation(self, b"posicao", self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._animar)

    def sizeHint(self) -> QSize:
        return QSize(38, 22)

    def _ler(self) -> float:
        return self._p

    def _gravar(self, v: float) -> None:
        self._p = v
        self.update()

    posicao = Property(float, _ler, _gravar)

    def _animar(self, ligado: bool) -> None:
        self._anim.stop()
        if not self.isVisible():   # ainda não aparece: vai direto ao estado final
            self._p = 1.0 if ligado else 0.0
            self.update()
            return
        self._anim.setStartValue(self._p)
        self._anim.setEndValue(1.0 if ligado else 0.0)
        self._anim.start()

    def paintEvent(self, _evento) -> None:
        if self._anim.state() != QPropertyAnimation.State.Running:
            self._p = 1.0 if self.isChecked() else 0.0
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        ativo = self.isEnabled()
        trilho = _mistura(tema.PAINEL3, tema.DESTAQUE if ativo else tema.DESTAQUE_DIM, self._p)
        borda = _mistura(tema.BORDA_FORTE, trilho.name(), self._p)
        r = QRectF(1, 2, self.width() - 2, self.height() - 4)
        p.setPen(QPen(borda, 1))
        p.setBrush(trilho)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        d = r.height() - 6
        x = r.left() + 3 + self._p * (r.width() - d - 6)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_mistura(tema.APAGADO, tema.TEXTO_SOBRE_DESTAQUE, self._p))
        p.drawEllipse(QRectF(x, r.top() + 3, d, d))
        if self.hasFocus():
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(tema.DESTAQUE_DIM), 1.5))
            p.drawRoundedRect(r.adjusted(-1, -1, 1, 1), r.height() / 2 + 1, r.height() / 2 + 1)
        p.end()


# ------------------------------------------------------------------ seletor segmentado
class Segmented(QFrame):
    """Seletor segmentado: ``itens`` = [(chave, texto, dica)]; ``icones`` = {chave: nome de ``icones.py``}."""

    mudou = Signal(str)

    def __init__(self, itens: list[tuple[str, str, str]], parent: QWidget | None = None,
                 icones_itens: dict[str, str] | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SegBox")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(2)
        self.grupo = QButtonGroup(self)
        self.grupo.setExclusive(True)
        self.botoes: dict[str, QToolButton] = {}
        for chave, texto, dica in itens:
            b = QToolButton()
            b.setObjectName("Seg")
            b.setText(texto)
            b.setToolTip(dica)
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            if icones_itens and chave in icones_itens:
                b.setIcon(icones.icone_dois_estados(icones_itens[chave], tema.APAGADO, tema.TEXTO_SOBRE_DESTAQUE, 16))
                b.setIconSize(QSize(16, 16))
                b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            self.grupo.addButton(b)
            lay.addWidget(b)
            self.botoes[chave] = b
            b.clicked.connect(lambda _marcado=False, k=chave: self.mudou.emit(k))

    def definir_atual(self, chave: str) -> None:
        """Marca `chave` sem emitir ``mudou``."""
        if chave in self.botoes:
            self.botoes[chave].setChecked(True)

    def chave_atual(self) -> str | None:
        return next((k for k, b in self.botoes.items() if b.isChecked()), None)


# ------------------------------------------------------------------ cartão recolhível
class Card(QFrame):
    """Cartão recolhível. Cabeçalho: seta, título (e subtítulo), restaurar e chave opcionais. Corpo em ``corpo``.

    Sinais: ``alternado(bool)`` (expandido?), ``restaurar_pedido()`` (botão de restaurar), ``chave_mudou(bool)``.
    Coloque os controles com ``card.adicionar(widget)`` (ou ``card.corpo_layout``).
    """

    alternado = Signal(bool)
    restaurar_pedido = Signal()
    chave_mudou = Signal(bool)

    def __init__(self, titulo: str, subtitulo: str = "", restaurar: bool = False, com_chave: bool = False,
                 expandido: bool = True, dica_restaurar: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(14, 11, 14, 13)
        raiz.setSpacing(4)
        self.cabecalho = QWidget()
        self.cabecalho.setCursor(Qt.CursorShape.PointingHandCursor)
        cab = QHBoxLayout(self.cabecalho)
        cab.setContentsMargins(0, 0, 0, 0)
        cab.setSpacing(8)
        self._seta = QLabel()
        self._seta.setContentsMargins(0, 3, 0, 0)
        self._seta.setFixedSize(16, 16)
        cab.addWidget(self._seta, 0, Qt.AlignmentFlag.AlignTop)
        textos = QVBoxLayout()
        textos.setSpacing(0)
        self.titulo = QLabel(titulo)
        self.titulo.setObjectName("PanelTitle")
        self.titulo.setMinimumWidth(60)
        textos.addWidget(self.titulo)
        self.subtitulo: QLabel | None = None
        if subtitulo:
            self.subtitulo = QLabel(subtitulo)
            self.subtitulo.setObjectName("Faint")
            self.subtitulo.setWordWrap(True)
            self.subtitulo.setMinimumWidth(60)
            textos.addWidget(self.subtitulo)
        cab.addLayout(textos, 1)
        self.botao_restaurar: QToolButton | None = None
        if restaurar:
            b = QToolButton()
            b.setObjectName("Flat")
            b.setIcon(icones.icone("reset", tema.APAGADO, 16))
            b.setToolTip(dica_restaurar)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(self.restaurar_pedido)
            cab.addWidget(b)
            self.botao_restaurar = b
        self.chave: ToggleSwitch | None = None
        if com_chave:
            self.chave = ToggleSwitch()
            self.chave.toggled.connect(self.chave_mudou)
            cab.addWidget(self.chave)
        self.cabecalho.mousePressEvent = lambda e: self.expandir(not self.expandido)
        raiz.addWidget(self.cabecalho)
        self.corpo = QWidget()
        self.corpo_layout = QVBoxLayout(self.corpo)
        self.corpo_layout.setContentsMargins(0, 8, 0, 0)
        self.corpo_layout.setSpacing(8)
        raiz.addWidget(self.corpo)
        self.expandido = True
        self.expandir(expandido, emitir=False)

    def adicionar(self, widget: QWidget) -> None:
        self.corpo_layout.addWidget(widget)

    def expandir(self, sim: bool, emitir: bool = True) -> None:
        mudou = sim != self.expandido
        self.expandido = sim
        self.corpo.setVisible(sim)
        pm = icones.icone("chevron", tema.APAGADO, 16).pixmap(16, 16)
        if not sim:
            pm = pm.transformed(QTransform().rotate(-90), Qt.TransformationMode.SmoothTransformation)
        self._seta.setPixmap(pm)
        if emitir and mudou:
            self.alternado.emit(sim)


# ------------------------------------------------------------------ slider
class Trilho(QWidget):
    """Só o trilho do slider: arrasta (Shift = ajuste fino), setas do teclado, duplo clique pede o padrão."""

    valor_mudou = Signal(float)
    soltou = Signal()
    padrao_pedido = Signal()

    MARGEM = 8

    def __init__(self, minimo: float, maximo: float, passo: float, padrao: float,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.minimo, self.maximo, self.passo, self.padrao = float(minimo), float(maximo), float(passo), float(padrao)
        self._v = float(padrao)
        self._arrasto = False
        self._sobre = False
        self._ancora_fina: tuple[float, float] | None = None
        self.origem = 0.0 if self.minimo < 0 < self.maximo else self.minimo
        self.setFixedHeight(24)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def valor(self) -> float:
        return self._v

    def definir_valor(self, v: float, emitir: bool = False) -> None:
        v = self._ajustar(float(v))
        if v != self._v:
            self._v = v
            self.update()
            if emitir:
                self.valor_mudou.emit(v)

    def _x(self, v: float) -> float:
        faixa = self.maximo - self.minimo or 1.0
        return self.MARGEM + (self.width() - 2 * self.MARGEM) * (v - self.minimo) / faixa

    def _de_x(self, x: float) -> float:
        faixa = self.maximo - self.minimo
        return self._ajustar(self.minimo + (x - self.MARGEM) / max(1.0, self.width() - 2 * self.MARGEM) * faixa)

    def _ajustar(self, v: float) -> float:
        if self.passo > 0:
            v = round((v - self.minimo) / self.passo) * self.passo + self.minimo
        return min(max(v, self.minimo), self.maximo)

    def paintEvent(self, _evento) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cy = self.height() / 2
        x0, x1 = self.MARGEM, self.width() - self.MARGEM
        ativo = self.isEnabled()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(tema.PAINEL3))
        p.drawRoundedRect(QRectF(x0, cy - 2, x1 - x0, 4), 2, 2)
        xv, xo = self._x(self._v), self._x(self.origem)
        a, b = sorted((xo, xv))
        p.setBrush(QColor(tema.DESTAQUE if ativo else tema.DESTAQUE_DIM))
        p.drawRoundedRect(QRectF(a, cy - 2, max(b - a, 0.5), 4), 2, 2)
        # marca do valor padrão (pontinho abaixo do trilho)
        p.setBrush(QColor(tema.FRACO))
        p.drawEllipse(QPointF(self._x(self.padrao), cy + 8), 1.3, 1.3)
        raio = 7.0 if (self._arrasto or self._sobre) else 6.0
        if self._arrasto or self.hasFocus():
            halo = QColor(tema.DESTAQUE)
            halo.setAlpha(60)
            p.setBrush(halo)
            p.drawEllipse(QPointF(xv, cy), raio + 4, raio + 4)
        p.setBrush(QColor(tema.TEXTO) if ativo else QColor(tema.FRACO))
        p.setPen(QPen(QColor(tema.DESTAQUE if ativo else tema.DESTAQUE_DIM), 2))
        p.drawEllipse(QPointF(xv, cy), raio - 1, raio - 1)
        p.end()

    def mousePressEvent(self, e) -> None:
        if e.button() != Qt.MouseButton.LeftButton:
            return
        self._arrasto = True
        if e.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self._ancora_fina = (e.position().x(), self._v)
        else:
            self._ancora_fina = None
            self.definir_valor(self._de_x(e.position().x()), emitir=True)
        self.update()

    def mouseMoveEvent(self, e) -> None:
        if self._arrasto:
            if self._ancora_fina:
                x0, v0 = self._ancora_fina
                por_px = (self.maximo - self.minimo) / max(1.0, self.width() - 2 * self.MARGEM)
                self.definir_valor(v0 + (e.position().x() - x0) * por_px * 0.1, emitir=True)
            else:
                self.definir_valor(self._de_x(e.position().x()), emitir=True)
        else:
            sobre = abs(e.position().x() - self._x(self._v)) < 12
            if sobre != self._sobre:
                self._sobre = sobre
                self.update()

    def mouseReleaseEvent(self, _e) -> None:
        if self._arrasto:
            self._arrasto = False
            self.update()
            self.soltou.emit()

    def leaveEvent(self, _e) -> None:
        self._sobre = False
        self.update()

    def mouseDoubleClickEvent(self, _e) -> None:
        self.padrao_pedido.emit()

    def wheelEvent(self, e) -> None:
        e.ignore()

    def keyPressEvent(self, e) -> None:
        mult = 10 if e.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
        passo = self.passo or (self.maximo - self.minimo) / 100
        if e.key() in (Qt.Key.Key_Right, Qt.Key.Key_Up):
            self.definir_valor(self._v + passo * mult, emitir=True)
            self.soltou.emit()
        elif e.key() in (Qt.Key.Key_Left, Qt.Key.Key_Down):
            self.definir_valor(self._v - passo * mult, emitir=True)
            self.soltou.emit()
        else:
            super().keyPressEvent(e)


class Slider(QWidget):
    """Linha de ajuste: rótulo à esquerda, valor editável à direita e o trilho embaixo.

    Duplo clique no trilho volta ao padrão (emitindo ``valor_mudou``); digitar um valor e dar Enter também emite.
    Sinais: ``valor_mudou(float)`` (a cada movimento), ``soltou()`` (soltou o mouse/tecla: hora de gravar o histórico).
    """

    valor_mudou = Signal(float)
    soltou = Signal()

    def __init__(self, rotulo: str, minimo: float, maximo: float, passo: float, padrao: float, unidade: str = "",
                 casas: int | None = None, escala: float = 1.0, dica: str = "", horizontal: bool = False,
                 parent: QWidget | None = None) -> None:
        """`escala`: o valor mostrado é ``valor * escala`` (ex.: 100 para exibir 0..1 como porcentagem).
        `horizontal`: tudo numa linha só (rótulo, trilho, valor), para barras; senão o trilho fica sob o rótulo."""
        super().__init__(parent)
        self.unidade = unidade
        self.escala = escala
        self.casas = casas if casas is not None else self._casas(passo * escala)
        if dica:
            self.setToolTip(dica)
        self.rotulo = QLabel(rotulo)
        self.rotulo.setObjectName("Muted")
        self.campo = QLineEdit()
        self.campo.setObjectName("Value")
        self.campo.setFixedWidth(72)
        self.campo.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.campo.editingFinished.connect(self._editado)
        self.trilho = Trilho(minimo, maximo, passo, padrao)
        self.trilho.valor_mudou.connect(self._moveu)
        self.trilho.padrao_pedido.connect(self.restaurar)
        self.trilho.soltou.connect(self.soltou)
        if horizontal:
            lay = QHBoxLayout(self)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(10)
            lay.addWidget(self.rotulo)
            lay.addWidget(self.trilho, 1)
            lay.addWidget(self.campo)
        else:
            lay = QVBoxLayout(self)
            lay.setContentsMargins(0, 2, 0, 2)
            lay.setSpacing(0)
            topo = QHBoxLayout()
            topo.setSpacing(4)
            topo.addWidget(self.rotulo)
            topo.addStretch(1)
            topo.addWidget(self.campo)
            lay.addLayout(topo)
            lay.addWidget(self.trilho)
        self._mostrar()

    @staticmethod
    def _casas(passo: float) -> int:
        n = 0
        while n < 4 and abs(passo * 10 ** n - round(passo * 10 ** n)) > 1e-9:
            n += 1
        return n

    def valor(self) -> float:
        return self.trilho.valor()

    def definir_valor(self, v: float, emitir: bool = False) -> None:
        self.trilho.definir_valor(v, emitir=False)
        self._mostrar()
        if emitir:
            self.valor_mudou.emit(self.trilho.valor())

    def restaurar(self) -> None:
        """Volta ao valor padrão e avisa (``valor_mudou`` + ``soltou``)."""
        antes = self.trilho.valor()
        self.definir_valor(self.trilho.padrao)
        if self.trilho.valor() != antes:
            self.valor_mudou.emit(self.trilho.valor())
        self.soltou.emit()

    def texto(self, v: float) -> str:
        return f"{v * self.escala:.{self.casas}f}".replace(".", ",") + self.unidade

    def _mostrar(self) -> None:
        if not self.campo.hasFocus():
            self.campo.setText(self.texto(self.trilho.valor()))

    def _moveu(self, v: float) -> None:
        self._mostrar()
        self.valor_mudou.emit(v)

    def _editado(self) -> None:
        txt = self.campo.text().strip().replace(self.unidade.strip(), "").replace(",", ".").strip()
        try:
            v = float(txt) / self.escala
        except ValueError:
            self._mostrar()
            return
        antes = self.trilho.valor()
        self.trilho.definir_valor(v)
        self.campo.clearFocus()
        self._mostrar()
        if self.trilho.valor() != antes:
            self.valor_mudou.emit(self.trilho.valor())
            self.soltou.emit()


# ------------------------------------------------------------------ pílula
class Pilula(QPushButton):
    """Botão em pílula (``objectName`` "Pilula") que mostra o texto inteiro se couber e, senão, o encurta no meio.

    ``text()`` devolve sempre o texto completo; o tamanho ideal é o do texto inteiro, mas ela aceita encolher."""

    FOLGA = 2 * 16 + 2 + 24      # padding lateral + borda + ícone (com respiro)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Pilula")
        self._completo = ""
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

    def setText(self, texto: str) -> None:  # noqa: N802 - nome do Qt
        self._completo = texto
        self._encurtar()
        self.updateGeometry()

    def text(self) -> str:
        return self._completo

    def sizeHint(self) -> QSize:  # noqa: N802
        base = super().sizeHint()
        largura = QFontMetrics(self.font()).horizontalAdvance(self._completo) + self.FOLGA
        return QSize(max(largura, 120), base.height())

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(120, super().minimumSizeHint().height())

    def _encurtar(self) -> None:
        disponivel = max(20, self.width() - self.FOLGA)
        elidido = QFontMetrics(self.font()).elidedText(self._completo, Qt.TextElideMode.ElideMiddle, disponivel)
        super().setText(elidido)

    def resizeEvent(self, evento) -> None:  # noqa: N802
        super().resizeEvent(evento)
        self._encurtar()


# ------------------------------------------------------------------ barra adaptável
class BarraAdaptavel(QWidget):
    """Barra de uma linha que encolhe em etapas para caber na largura (como a barra superior do Pelicula).

    Etapa 0: tudo como foi montado. Etapa 1: somem os ``rotulos`` (textos de apoio). Etapa 2: os botões de
    ``compactos`` ficam só com o ícone (o texto vira dica). Etapa 3: somem os ``opcionais``.
    O layout da barra tem de ser um ``QHBoxLayout``.
    """

    ETAPAS = 4

    def __init__(self, nome: str = "TopBar", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName(nome)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.rotulos: list[QWidget] = []
        self.compactos: list[QToolButton] = []
        self.opcionais: list[QWidget] = []
        self.nivel = 0
        self._ocupado = False
        self._ultimo_hint = -1
        self.setMinimumWidth(1)   # o mínimo vem da etapa mais compacta, não do layout inteiro

    def definir_adaptacao(self, compactos: list[QToolButton] = (), opcionais: list[QWidget] = (),
                          rotulos: list[QWidget] = ()) -> None:
        self.rotulos = [w for w in rotulos if w is not None]
        self.compactos = [b for b in compactos if b is not None]
        self.opcionais = [w for w in opcionais if w is not None]
        for b in self.compactos:
            if b.text() and not b.toolTip():
                b.setToolTip(b.text())
        lay = self.layout()
        if lay is not None:
            lay.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self._adaptar()

    @staticmethod
    def _mostrar(w: QWidget, mostrar: bool) -> None:
        if bool(w.property("adaptativo_oculto")) == mostrar:
            w.setProperty("adaptativo_oculto", not mostrar)
            w.setVisible(mostrar)

    def _aplicar(self, nivel: int) -> None:
        estilo = Qt.ToolButtonStyle.ToolButtonIconOnly if nivel >= 2 else Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        for b in self.compactos:
            if b.text() and b.toolButtonStyle() != estilo:
                b.setToolButtonStyle(estilo)
        for w in self.rotulos:
            self._mostrar(w, nivel < 1)
        for w in self.opcionais:
            self._mostrar(w, nivel < 3)

    def _adaptar(self) -> None:
        lay = self.layout()
        if self._ocupado or lay is None:
            return
        self._ocupado = True
        try:
            for nivel in range(self.ETAPAS):
                self._aplicar(nivel)
                lay.invalidate()
                if lay.sizeHint().width() <= self.width():
                    break
            self.nivel = nivel
            self._ultimo_hint = lay.sizeHint().width()
        finally:
            self._ocupado = False

    def resizeEvent(self, evento) -> None:  # noqa: N802 - nome do Qt
        super().resizeEvent(evento)
        self._adaptar()

    def event(self, evento) -> bool:
        if evento.type() == QEvent.Type.LayoutRequest and not self._ocupado:
            lay = self.layout()   # um filho mudou de tamanho (ex.: o texto do custo): adapta de novo
            if lay is not None and lay.sizeHint().width() != self._ultimo_hint:
                QTimer.singleShot(0, self._adaptar)
        return super().event(evento)
