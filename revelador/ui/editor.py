"""Editor de enquadramento: a foto com a moldura do papel, mover, zoom, girar, endireitar e "Ver como sai".

Conversa só pelo ``Estado`` (``docs/ARQUITETURA.md``, seções 5.1, 6 e 10): lê a foto atual e a impressão atual
(``estado.impressao_atual``), altera o ``Recorte`` dela e avisa com ``estado.alterar(foto)``. Qualquer gesto da
pessoa marca o recorte como ``"manual"`` (nunca mais refeito sozinho); "Enquadrar pelos rostos" volta a ``"auto"``.

Geometria: tudo vem de ``enquadramento.retangulo`` e de ``receita.poligono`` (a moldura desenhada é exatamente o que
a receita vai amostrar). O recorte só entra no modelo depois de passar por ``enquadramento.reencaixar``, então fica
sempre dentro da imagem. Os gestos têm métodos públicos (``mover``, ``aproximar``, ``puxar_canto``, ``girar``,
``endireitar``, ``enquadrar_pelos_rostos``) que o mouse e os atalhos só chamam; os testes chamam direto. As alças nos
cantos do papel (só na moldura, no modo *preencher*) mudam o zoom com o canto oposto parado.

Com o foco no editor, ← / → (e Home / End) vão para a foto anterior / seguinte entre as visíveis na grade
(``Estado.vizinha``; o filtro "Mostrar" vale): ``navegar`` e ``ir_para_ponta``.

Dois modos de ver (``definir_previa``, seletor "Moldura | Resultado"): a foto inteira com a moldura do papel (padrão)
e o resultado, a prévia pela receita no tamanho do visor, calculada num trabalhador com *debounce* de ~60 ms e contador de geração
(resultado velho é descartado). Impressão no modo *caber* mostra sempre a prévia (a moldura não faz sentido).
"""

from __future__ import annotations

import math
from dataclasses import replace

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QKeySequence, QPainter, QPainterPath, QPen, QPolygonF, QShortcut
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from .. import ajustes as ajustes_mod
from .. import enquadramento, receita, tamanhos
from ..i18n import N_, _
from ..projeto import Foto, Impressao, Recorte
from . import tema
from .componentes import BarraAdaptavel, Segmented, Slider, botao_plano
from .estado import Estado
from .previa import AjustarImagem, CarregarProxy, RenderizarPrevia, Sinais, para_qimage

FUNDO = tema.CANVAS_EDITOR   # cinza escuro neutro: um fundo colorido enganaria a percepção de cor da foto
ESCURECER_FORA = 166         # ~65% de preto sobre a parte da foto que fica fora do papel
ZOOM_MAXIMO = 10.0
PASSO_ZOOM = 1.1             # fator por clique da roda (e por atalho)
DEBOUNCE_MS = 60
DEBOUNCE_FINO_MS = 350      # parou de mexer nos ajustes: refaz a moldura na resolução do proxy
LADO_RAPIDO = 640           # lado maior da versão reduzida da moldura (enquanto o controle é arrastado)
ANGULO_MAX = 45.0
MARGEM_TELA = 14             # px lógicos entre a moldura e a borda do visor
TOQUE_ALCA = 12              # px lógicos ao redor do canto do papel que pegam a alça
COMPRIMENTO_ALCA = 20        # px lógicos de cada perna do "L" da alça
LARGURA_ALCA = 4.0           # espessura do "L" (o contorno escuro tem 2,5 px a mais)
# Sinal (x, y), no referencial do papel, do canto i (horário a partir do superior esquerdo) visto do canto oposto.
SINAIS_CANTO = ((-1, -1), (1, -1), (1, 1), (-1, 1))
# Teclas de navegação entre as fotos visíveis na grade, com o foco no editor.
TECLAS_NAVEGAR = {Qt.Key.Key_Left: -1, Qt.Key.Key_Right: +1}

QUALIDADES = {
    "boa": N_("qualidade boa"),
    "aceitavel": N_("qualidade aceitável"),
    "baixa": N_("resolução baixa para este tamanho"),
}


class Tela(QWidget):
    """O visor: desenha a foto (ou a prévia) e a moldura; traduz mouse em sinais. Não conhece o modelo."""

    arrastado = Signal(float, float)       # deslocamento do mouse (px lógicos) desde o último evento
    rolado = Signal(float, QPointF)        # passos da roda (1 = um clique) e a posição do mouse
    alca_arrastada = Signal(int, QPointF)  # canto do papel (0..3) e onde ele deve ficar (px lógicos do visor)
    redimensionada = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("tela_editor")
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setMouseTracking(True)                        # cursor de redimensionar ao passar sobre uma alça
        self.setMinimumSize(240, 180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.imagem: QImage | None = None                  # a foto inteira, já girada (e ajustada)
        self.largura_ref = 0                               # largura do proxy girado em px (a imagem pode estar reduzida)
        self.moldura: enquadramento.Retangulo | None = None  # recorte em px da imagem girada
        self.margem_rel = 0.0                              # margem de corte ÷ largura do papel
        self.rostos: list[tuple[float, float, float, float]] = []   # caixas em px da imagem girada
        self.mostrar_rostos = False
        self.previa: QImage | None = None
        self.mostrar_previa = False
        self.mensagem = ""                                 # texto no centro (carregando, erro, nada escolhido)
        self.dica = ""                                     # faixa de texto embaixo
        self.arrastavel = False
        self.alcas = False                                 # alças nos cantos do papel (moldura editável)
        self._ultimo: QPointF | None = None
        self._alca: int | None = None                      # alça sendo arrastada
        self._desvio = QPointF()                           # canto − ponto onde o mouse pegou a alça
        self._alca_sob_mouse: int | None = None

    # ------------------------------------------------------------ geometria do visor
    def area_util(self) -> QRectF:
        return QRectF(self.rect()).adjusted(MARGEM_TELA, MARGEM_TELA, -MARGEM_TELA, -MARGEM_TELA)

    def quadro(self) -> QRectF | None:
        """Onde a foto (ou a prévia) é desenhada, em px lógicos do visor."""
        area = self.area_util()
        if self.mostrar_previa and self.previa is not None:
            dpr = self.previa.devicePixelRatio() or 1.0
            w, h = self.previa.width() / dpr, self.previa.height() / dpr
        elif self.imagem is not None and not self.mostrar_previa:
            k = min(area.width() / self.imagem.width(), area.height() / self.imagem.height())
            w, h = self.imagem.width() * k, self.imagem.height() * k
        else:
            return None
        return QRectF(area.center().x() - w / 2, area.center().y() - h / 2, w, h)

    def escala_imagem(self) -> float:
        """Px lógicos do visor por px da imagem girada (modo moldura)."""
        q = self.quadro()
        if q is None or self.imagem is None:
            return 1.0
        return q.width() / (self.largura_ref or self.imagem.width())

    def cantos_tela(self) -> list[QPointF] | None:
        """Os cantos do papel em px lógicos do visor (horário a partir do superior esquerdo), quando há alças."""
        if not self.alcas or self.moldura is None or self.mostrar_previa or self.imagem is None:
            return None
        quadro = self.quadro()
        return None if quadro is None else self._para_tela(quadro, receita.poligono(self.moldura))

    def alca_em(self, pos: QPointF) -> int | None:
        """O canto (0..3) cuja alça está sob ``pos`` (o mais perto, até ``TOQUE_ALCA`` px), ou None."""
        cantos = self.cantos_tela()
        if not cantos:
            return None
        dist = [math.hypot(c.x() - pos.x(), c.y() - pos.y()) for c in cantos]
        i = min(range(4), key=dist.__getitem__)
        return i if dist[i] <= TOQUE_ALCA else None

    def _cursor_alca(self, canto: int) -> Qt.CursorShape:
        """Seta diagonal que acompanha o canto na tela (o papel pode estar endireitado)."""
        cantos = self.cantos_tela()
        if not cantos:
            return Qt.CursorShape.SizeFDiagCursor
        oposto = cantos[(canto + 2) % 4]
        d = cantos[canto] - oposto
        return Qt.CursorShape.SizeFDiagCursor if d.x() * d.y() > 0 else Qt.CursorShape.SizeBDiagCursor

    def _cursor_parado(self) -> Qt.CursorShape:
        if self._alca_sob_mouse is not None:
            return self._cursor_alca(self._alca_sob_mouse)
        return Qt.CursorShape.OpenHandCursor if self.arrastavel else Qt.CursorShape.ArrowCursor

    # ------------------------------------------------------------ desenho
    def paintEvent(self, _evento) -> None:  # noqa: N802 - nome do Qt
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor(FUNDO))
        quadro = self.quadro()
        if quadro is None:
            self._texto(p, self.rect(), self.mensagem)
        elif self.mostrar_previa and self.previa is not None:
            p.drawImage(quadro, self.previa)
            if self.margem_rel > 0:
                m = self.margem_rel * quadro.width()
                self._tracejado(p, [QPointF(quadro.left() + m, quadro.top() + m),
                                    QPointF(quadro.right() - m, quadro.top() + m),
                                    QPointF(quadro.right() - m, quadro.bottom() - m),
                                    QPointF(quadro.left() + m, quadro.bottom() - m)])
        else:
            p.drawImage(quadro, self.imagem)
            if self.moldura is not None:
                self._moldura(p, quadro)
        if self.dica and quadro is not None:
            faixa = QRectF(0, self.height() - 30, self.width(), 30)
            p.fillRect(faixa, QColor(0, 0, 0, 150))
            self._texto(p, faixa, self.dica, QColor(tema.TEXTO))
        p.end()

    @staticmethod
    def _texto(p: QPainter, area: QRectF, texto: str, cor: QColor | None = None) -> None:
        if not texto:
            return
        p.setPen(cor or QColor(tema.APAGADO))
        p.drawText(QRectF(area), int(Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap), texto)

    def _para_tela(self, quadro: QRectF, pontos) -> list[QPointF]:
        k = quadro.width() / (self.largura_ref or self.imagem.width())
        return [QPointF(quadro.left() + x * k, quadro.top() + y * k) for x, y in pontos]

    @staticmethod
    def _tracejado(p: QPainter, pontos: list[QPointF]) -> None:
        poligono = QPolygonF(pontos + [pontos[0]])
        claro = QPen(QColor(255, 255, 255, 230), 1.2, Qt.PenStyle.DashLine)
        escuro = QPen(QColor(0, 0, 0, 200), 1.2, Qt.PenStyle.DashLine)
        escuro.setDashOffset(3)
        for caneta in (claro, escuro):
            p.setPen(caneta)
            p.drawPolyline(poligono)

    def _moldura(self, p: QPainter, quadro: QRectF) -> None:
        ret = self.moldura
        cantos = self._para_tela(quadro, receita.poligono(ret))
        # Fora do papel escurecido.
        fora = QPainterPath()
        fora.addRect(quadro)
        dentro = QPainterPath()
        dentro.addPolygon(QPolygonF(cantos + [cantos[0]]))
        p.fillPath(fora.subtracted(dentro), QColor(0, 0, 0, ESCURECER_FORA))
        # Regra dos terços.
        tl, tr, br, bl = cantos
        p.setPen(QPen(QColor(255, 255, 255, 110), 1.0))
        for f in (1 / 3, 2 / 3):
            p.drawLine(tl + (tr - tl) * f, bl + (br - bl) * f)
            p.drawLine(tl + (bl - tl) * f, tr + (br - tr) * f)
        # Rostos detectados.
        if self.mostrar_rostos:
            p.setPen(QPen(QColor(tema.OK), 1.5))
            k = quadro.width() / (self.largura_ref or self.imagem.width())
            for x, y, w, h in self.rostos:
                p.drawRect(QRectF(quadro.left() + x * k, quadro.top() + y * k, w * k, h * k))
        # Borda do papel e margem de corte tracejada.
        p.setPen(QPen(QColor("#ffffff"), 1.6))
        p.drawPolyline(QPolygonF(cantos + [cantos[0]]))
        if self.margem_rel > 0:
            interno = receita.encolher(ret, self.margem_rel * ret.w)
            self._tracejado(p, self._para_tela(quadro, receita.poligono(interno)))
        if self.alcas:
            self._alcas(p, cantos)

    def _alcas(self, p: QPainter, cantos: list[QPointF]) -> None:
        """Um "L" em cada canto do papel, ao longo das bordas; a alça ativa (mouse em cima ou arrastando) em destaque."""
        sombra = QColor(tema.CANVAS_EDITOR)
        sombra.setAlpha(200)
        ativa = self._alca if self._alca is not None else self._alca_sob_mouse
        for i, c in enumerate(cantos):
            pernas = []
            for vizinho in (cantos[(i - 1) % 4], cantos[(i + 1) % 4]):
                d = vizinho - c
                n = math.hypot(d.x(), d.y()) or 1.0
                pernas.append(c + d * (min(COMPRIMENTO_ALCA, n / 3) / n))
            linha = QPolygonF([pernas[0], c, pernas[1]])
            for cor, largura in ((sombra, LARGURA_ALCA + 2.5),
                                 (QColor(tema.DESTAQUE if i == ativa else tema.TEXTO), LARGURA_ALCA)):
                caneta = QPen(cor, largura)
                caneta.setCapStyle(Qt.PenCapStyle.SquareCap)
                caneta.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
                p.setPen(caneta)
                p.drawPolyline(linha)

    # ------------------------------------------------------------ mouse
    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton and self.arrastavel:
            alca = self.alca_em(e.position())
            if alca is not None:      # pegou uma alça: muda o zoom pelo canto (sem saltar para o ponto exato)
                self._alca = alca
                self._desvio = self.cantos_tela()[alca] - e.position()
                self.setCursor(self._cursor_alca(alca))
                self.update()
            else:
                self._ultimo = e.position()
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
            self.setFocus()

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        if self._alca is not None:
            self.alca_arrastada.emit(self._alca, e.position() + self._desvio)
        elif self._ultimo is not None:
            d = e.position() - self._ultimo
            self._ultimo = e.position()
            if d.x() or d.y():
                self.arrastado.emit(d.x(), d.y())
        else:
            alca = self.alca_em(e.position()) if self.arrastavel else None
            if alca != self._alca_sob_mouse:
                self._alca_sob_mouse = alca
                self.setCursor(self._cursor_parado())
                self.update()

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        if e.button() != Qt.MouseButton.LeftButton or (self._ultimo is None and self._alca is None):
            return
        self._ultimo, self._alca = None, None
        self._alca_sob_mouse = self.alca_em(e.position()) if self.arrastavel else None
        self.setCursor(self._cursor_parado())
        self.update()

    def leaveEvent(self, e) -> None:  # noqa: N802
        super().leaveEvent(e)
        if self._alca_sob_mouse is not None and self._alca is None:
            self._alca_sob_mouse = None
            self.update()

    def wheelEvent(self, e) -> None:  # noqa: N802
        passos = e.angleDelta().y() / 120.0
        if passos and self.arrastavel:
            self.rolado.emit(passos, e.position())
            e.accept()

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        self.redimensionada.emit()

    def definir_arrastavel(self, sim: bool) -> None:
        self.arrastavel = sim
        if not sim:
            self._ultimo = None
        if not sim or not self.alcas:     # chame depois de definir ``alcas``
            self._alca, self._alca_sob_mouse = None, None
        if self._ultimo is None and self._alca is None:   # no meio de um gesto o cursor do gesto continua
            self.setCursor(self._cursor_parado())


class Editor(QWidget):
    """Área central: o visor e os controles do enquadramento da impressão atual."""

    proxy_carregado = Signal()      # o proxy da foto atual chegou
    previa_atualizada = Signal()    # chegou uma prévia nova (não descartada)
    ajustada_atualizada = Signal()  # chegou a foto inteira ajustada da moldura (reduzida ou final)

    def __init__(self, estado: Estado, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("editor")
        self.estado = estado
        self.proxy: np.ndarray | None = None        # proxy da foto atual (float32, sem giro); somente leitura
        self.previa: QImage | None = None           # a última prévia recebida
        self.previa_geracao = 0
        self.mostrar_previa = False
        self._caminho: str | None = None
        self._imagens: dict[int, QImage] = {}       # foto inteira girada, por giro
        self._ger_proxy = 0
        self._erro = ""
        self._dpr_previa = 1.0
        self._ajustada: QImage | None = None        # a foto inteira girada com os ajustes (moldura)
        self._ajustada_giro = 0
        self._ajustada_final = False
        self._chave_ajustada: tuple | None = None   # (giro, ajustes) da última versão pedida
        self._ger_ajuste = 0
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(2)
        self._sinais = Sinais(self)
        self._sinais.proxy_pronto.connect(self._proxy_pronto)
        self._sinais.proxy_erro.connect(self._proxy_erro)
        self._sinais.previa_pronta.connect(self._previa_pronta)
        self._sinais.previa_erro.connect(self._previa_erro)
        self._sinais.ajustada_pronta.connect(self._ajustada_pronta)
        self._timer_ajuste = QTimer(self)
        self._timer_ajuste.setSingleShot(True)
        self._timer_ajuste.setInterval(DEBOUNCE_MS)
        self._timer_ajuste.timeout.connect(lambda: self._disparar_ajustada(LADO_RAPIDO, False))
        self._timer_fino = QTimer(self)
        self._timer_fino.setSingleShot(True)
        self._timer_fino.setInterval(DEBOUNCE_FINO_MS)
        self._timer_fino.timeout.connect(lambda: self._disparar_ajustada(None, True))
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(DEBOUNCE_MS)
        self._timer.timeout.connect(self._disparar_previa)
        self._montar()
        self._atalhos()
        for sinal, slot in ((estado.atual_mudou, self._atual_mudou), (estado.foto_mudou, self._foto_mudou),
                            (estado.impressao_mudou, self._impressao_mudou),
                            (estado.comparando_mudou, self._comparando_mudou)):
            sinal.connect(slot)
        self._atualizar()

    # ------------------------------------------------------------ montagem
    def _montar(self) -> None:
        self.tela = Tela(self)
        self.tela.arrastado.connect(self._ao_arrastar)
        self.tela.rolado.connect(self._ao_rolar)
        self.tela.alca_arrastada.connect(self._ao_arrastar_alca)
        self.tela.redimensionada.connect(self._agendar_previa)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)   # clicar no rodapé também dá o foco (←/→ entre as fotos)

        self.botao_girar_esq = botao_plano("girar_esquerda", _("Girar 90° para a esquerda (Shift+R)"))
        self.botao_girar_dir = botao_plano("girar_direita", _("Girar 90° para a direita (R)"))
        self.botao_girar_esq.clicked.connect(lambda: self.girar(-1))
        self.botao_girar_dir.clicked.connect(lambda: self.girar(+1))
        self.botao_papel = botao_plano("foto", _("Girar o papel: retrato ↔ paisagem (O)"), _("Girar papel"))
        self.botao_papel.clicked.connect(self.girar_papel)
        self.botao_zoom_menos = botao_plano("zoom_menos", _("Afastar a foto (Ctrl+−)"))
        self.botao_zoom_mais = botao_plano("zoom_mais", _("Aproximar a foto (Ctrl++)"))
        self.botao_zoom_menos.clicked.connect(lambda: self.aproximar(1 / PASSO_ZOOM))
        self.botao_zoom_mais.clicked.connect(lambda: self.aproximar(PASSO_ZOOM))

        self.slider_angulo = Slider(_("Endireitar"), -ANGULO_MAX, ANGULO_MAX, 0.1, 0.0, "°", horizontal=True,
                                    dica=_("Endireitar a foto (duplo clique volta a 0°)"))
        self.slider_angulo.valor_mudou.connect(self.endireitar)

        self.botao_auto = botao_plano("recorte", _("Volta ao enquadramento automático (A)"),
                                      _("Enquadrar pelos rostos"))
        self.botao_auto.clicked.connect(self.enquadrar_pelos_rostos)
        self.caixa_rostos = botao_plano("rosto", _("Mostrar os rostos detectados"), _("Rostos"), marcavel=True,
                                        cor=tema.APAGADO, cor_marcado=tema.DESTAQUE_HI)
        self.caixa_rostos.toggled.connect(self.mostrar_rostos)
        self.modo_vista = Segmented([
            ("moldura", _("Moldura"), _("A foto inteira com a moldura do papel")),
            ("resultado", _("Resultado"), _("Mostra o resultado como será revelado")),
        ])
        self.modo_vista.definir_atual("moldura")
        self.modo_vista.mudou.connect(lambda chave: self.definir_previa(chave == "resultado"))
        self.botao_previa = self.modo_vista.botoes["resultado"]   # os botões do seletor "Moldura | Resultado"
        self.botao_moldura = self.modo_vista.botoes["moldura"]

        self.rotulo_info = QLabel()
        self.rotulo_info.setObjectName("info_editor")
        self.rotulo_info.setWordWrap(True)

        controles = BarraAdaptavel("Controles")
        barra = QHBoxLayout(controles)
        barra.setContentsMargins(0, 0, 0, 0)
        barra.setSpacing(6)
        for w in (self.botao_girar_esq, self.botao_girar_dir, self.botao_papel):
            barra.addWidget(w)
        for w in (self.botao_zoom_menos, self.botao_zoom_mais):
            barra.addWidget(w)
        barra.addWidget(self.caixa_rostos)
        barra.addWidget(self.botao_auto)
        barra.addStretch(1)
        barra.addWidget(self.modo_vista)
        controles.definir_adaptacao(compactos=[self.caixa_rostos, self.botao_auto],
                                    opcionais=[self.botao_zoom_menos, self.botao_zoom_mais])

        self.rodape = QWidget()
        self.rodape.setObjectName("Rodape")
        self.rodape.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        coluna = QVBoxLayout(self.rodape)
        coluna.setContentsMargins(14, 10, 14, 12)
        coluna.setSpacing(8)
        coluna.addWidget(self.rotulo_info)
        coluna.addWidget(controles)
        coluna.addWidget(self.slider_angulo)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.tela, 1)
        layout.addWidget(self.rodape)

    def _atalhos(self) -> None:
        def atalho(chave, slot) -> None:
            QShortcut(QKeySequence(chave), self, activated=slot, context=Qt.ShortcutContext.WindowShortcut)

        atalho("R", lambda: self.girar(+1))
        atalho("Shift+R", lambda: self.girar(-1))
        atalho("A", self.enquadrar_pelos_rostos)
        atalho("O", self.girar_papel)
        atalho(QKeySequence.StandardKey.ZoomIn, lambda: self.aproximar(PASSO_ZOOM))
        atalho(QKeySequence.StandardKey.ZoomOut, lambda: self.aproximar(1 / PASSO_ZOOM))

    def keyPressEvent(self, e) -> None:  # noqa: N802 - nome do Qt
        """← / → (e Home / End) com o foco no editor: foto anterior / seguinte entre as visíveis na grade.

        As teclas que um filho trata (o slider de endireitar usa as setas) não chegam aqui; a grade navega sozinha
        quando o foco está nela.
        """
        modificadores = e.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
        if modificadores == Qt.KeyboardModifier.NoModifier:
            if e.key() in TECLAS_NAVEGAR:
                self.navegar(TECLAS_NAVEGAR[e.key()])
                e.accept()
                return
            if e.key() in (Qt.Key.Key_Home, Qt.Key.Key_End):
                self.ir_para_ponta(e.key() == Qt.Key.Key_End)
                e.accept()
                return
        super().keyPressEvent(e)

    # ------------------------------------------------------------ consulta
    def _contexto(self) -> tuple[Foto, Impressao] | None:
        """(foto, impressão) editáveis agora: com proxy pronto e a moldura fazendo sentido (modo preencher)."""
        foto, imp = self.estado.atual, self.estado.impressao_atual
        if foto is None or imp is None or self.proxy is None:
            return None
        return foto, imp

    def _editavel(self) -> tuple[Foto, Impressao] | None:
        ctx = self._contexto()
        return None if ctx is None or ctx[1].modo == receita.MODO_CABER else ctx

    def _dims(self) -> tuple[int, int]:
        """(largura, altura) do proxy, sem giro."""
        return self.proxy.shape[1], self.proxy.shape[0]

    def _retangulo(self, imp: Impressao) -> enquadramento.Retangulo:
        return receita.retangulo_da_impressao(imp, *self._dims())

    @property
    def recorte_atual(self) -> Recorte | None:
        imp = self.estado.impressao_atual
        return None if imp is None else imp.recorte

    @property
    def mostrando_previa(self) -> bool:
        """Verdadeiro se o visor está mostrando a prévia (pedida pela pessoa ou imposta pelo modo *caber*)."""
        ctx = self._contexto()
        return self.mostrar_previa or (ctx is not None and ctx[1].modo == receita.MODO_CABER)

    # ------------------------------------------------------------ gestos (públicos)
    def _aplicar(self, foto: Foto, imp: Impressao, novo: Recorte) -> bool:
        """Grava o recorte como manual e avisa. Sem mudança real, não faz nada (e não vira manual).

        Desfazer: arrastar, rolar o zoom e o slider de endireitar juntam as chamadas seguidas num passo só (até
        soltar o mouse ou parar de mexer); o giro de 90° é sempre um passo próprio.
        """
        a = imp.recorte
        if (novo.cx, novo.cy, novo.zoom, novo.angulo, novo.giro) == (a.cx, a.cy, a.zoom, a.angulo, a.giro):
            return False
        if novo.giro != a.giro:
            juntar = None
        elif (novo.cx, novo.cy, novo.zoom) == (a.cx, a.cy, a.zoom):
            juntar = f"endireitar:{self.estado.indice_impressao}"
        else:
            juntar = f"recorte:{self.estado.indice_impressao}"
        imp.recorte = replace(novo, origem="manual")
        self.estado.alterar(foto, juntar=juntar)
        return True

    def _limitado(self, imp: Impressao, recorte: Recorte) -> Recorte:
        """O recorte reencaixado na proporção da impressão (centro e ângulo limitados à imagem)."""
        temp = replace(imp, recorte=recorte)
        W, H = receita.dimensoes_giradas(temp, *self._dims())
        return enquadramento.reencaixar(recorte, W, H, receita.proporcao(temp, *self._dims()))

    def mover(self, dx: float, dy: float) -> bool:
        """Desloca o recorte ``(dx, dy)`` em frações da imagem girada (+x direita, +y baixo). Limitado à imagem."""
        ctx = self._editavel()
        if ctx is None or not (dx or dy):
            return False
        foto, imp = ctx
        W, H = receita.dimensoes_giradas(imp, *self._dims())
        r = self._retangulo(imp)
        novo = replace(imp.recorte, cx=r.cx / W + dx, cy=r.cy / H + dy)
        return self._aplicar(foto, imp, self._limitado(imp, novo))

    def aproximar(self, fator: float, ancora: tuple[float, float] | None = None) -> bool:
        """Multiplica o zoom por ``fator`` (> 1 aproxima, < 1 afasta), de 1 a ``ZOOM_MAXIMO``.

        ``ancora`` = ponto da imagem girada (frações) que fica parado; sem ela, o centro do recorte.
        """
        if fator <= 0:
            raise ValueError("o fator de zoom precisa ser positivo")
        ctx = self._editavel()
        if ctx is None:
            return False
        foto, imp = ctx
        W, H = receita.dimensoes_giradas(imp, *self._dims())
        prop = receita.proporcao(imp, *self._dims())
        r = self._retangulo(imp)
        zoom = min(ZOOM_MAXIMO, max(1.0, enquadramento.zoom_efetivo(imp.recorte, W, H, prop) * fator))
        rec = replace(imp.recorte, zoom=zoom)
        novo_w = enquadramento.retangulo(rec, W, H, prop).w
        cx, cy = r.cx / W, r.cy / H
        if ancora is not None:
            k = novo_w / r.w
            cx, cy = ancora[0] + (cx - ancora[0]) * k, ancora[1] + (cy - ancora[1]) * k
        return self._aplicar(foto, imp, self._limitado(imp, replace(rec, cx=cx, cy=cy)))

    def puxar_canto(self, canto: int, ponto: tuple[float, float]) -> bool:
        """A alça: leva o canto ``canto`` do papel (0..3, horário a partir do superior esquerdo) para ``ponto``
        (frações da imagem girada) com o **canto oposto parado**. Muda só o zoom: a proporção do papel não muda.

        O tamanho novo é a projeção do ponto na diagonal do papel (o canto fica o mais perto possível do mouse), de
        zoom 1 a ``ZOOM_MAXIMO``. Se o papel maior não cabe com o canto oposto onde está, ele é empurrado para dentro
        da imagem (``reencaixar``), como nos outros gestos.
        """
        ctx = self._editavel()
        if ctx is None or canto not in range(4):
            return False
        foto, imp = ctx
        W, H = receita.dimensoes_giradas(imp, *self._dims())
        prop = receita.proporcao(imp, *self._dims())
        r = self._retangulo(imp)
        ox, oy = receita.poligono(r)[(canto + 2) % 4]
        t = math.radians(-r.angulo)              # o mesmo giro de receita.matriz_destino_fonte (papel -> imagem)
        c, s = math.cos(t), math.sin(t)
        vx, vy = ponto[0] * W - ox, ponto[1] * H - oy
        lx, ly = c * vx + s * vy, -s * vx + c * vy           # o vetor no referencial do papel
        sx, sy = SINAIS_CANTO[canto]
        k = (sx * lx * r.w + sy * ly * r.h) / (r.w ** 2 + r.h ** 2)   # tamanho novo ÷ tamanho atual
        w0, _h0 = enquadramento.tamanho_maximo(W, H, prop)
        zoom = min(ZOOM_MAXIMO, max(1.0, w0 / max(k * r.w, 1e-9)))
        if abs(zoom - enquadramento.zoom_efetivo(imp.recorte, W, H, prop)) < 1e-9:
            return False          # o canto não saiu do lugar (só arredondamento): não vira manual
        rec = replace(imp.recorte, zoom=zoom)
        novo = enquadramento.retangulo(rec, W, H, prop)
        hx, hy = sx * novo.w / 2, sy * novo.h / 2            # do canto oposto ao centro, no referencial do papel
        cx, cy = ox + c * hx - s * hy, oy + s * hx + c * hy
        return self._aplicar(foto, imp, self._limitado(imp, replace(rec, cx=cx / W, cy=cy / H)))

    def girar(self, sentido: int) -> bool:
        """Gira 90° (``+1`` horário, ``-1`` anti-horário), sem perda. A proporção acompanha a imagem girada."""
        ctx = self._contexto()
        if ctx is None or sentido == 0:
            return False
        foto, imp = ctx
        W, H = receita.dimensoes_giradas(imp, *self._dims())
        r = self._retangulo(imp) if imp.modo != receita.MODO_CABER else None
        cx, cy = (r.cx / W, r.cy / H) if r else (imp.recorte.cx, imp.recorte.cy)
        if sentido > 0:
            cx, cy = 1.0 - cy, cx
        else:
            cx, cy = cy, 1.0 - cx
        giro = (imp.recorte.giro + (1 if sentido > 0 else -1)) % 4
        novo = replace(imp.recorte, cx=cx, cy=cy, giro=giro)
        return self._aplicar(foto, imp, self._limitado(imp, novo))

    def endireitar(self, graus: float) -> bool:
        """Define o ângulo de endireitar (−45 a 45, passo 0,1). Mantém o centro e o zoom escolhidos."""
        ctx = self._editavel()
        if ctx is None:
            return False
        foto, imp = ctx
        graus = round(max(-ANGULO_MAX, min(ANGULO_MAX, float(graus))), 1)
        return self._aplicar(foto, imp, replace(imp.recorte, angulo=graus))

    def enquadrar_pelos_rostos(self) -> bool:
        """Volta ao recorte automático (``origem = "auto"``): o mesmo caminho de ``Estado.refazer_recortes_auto``.

        Foto ainda sem detecção: pede os rostos já (``Estado.pedir_rostos``); o recorte, que deixa de ser manual, é
        refeito quando eles chegam (``definir_rostos`` refaz os recortes não manuais).
        """
        ctx = self._contexto()
        if ctx is None:
            return False
        foto, imp = ctx
        if foto.rostos is None:
            self.estado.pedir_rostos(foto)
        imp.recorte = replace(imp.recorte, origem="auto")
        if foto.id in self.estado.info:
            self.estado.refazer_recortes_auto(foto)
        else:    # metadados ainda não chegaram: as proporções do proxy bastam (o recorte é normalizado)
            largura, altura = self._dims()
            imp.recorte = enquadramento.recorte_sugerido(imp, largura, altura, foto.rostos,
                                                         self.estado.trabalho.margem_corte_mm)
        self.estado.alterar(foto)
        return True

    def girar_papel(self) -> bool:
        """Troca retrato ↔ paisagem da impressão atual (fixa a escolha). Automático refeito; manual reencaixado."""
        ctx = self._contexto()
        if ctx is None:
            return False
        foto, imp = ctx
        imp.orientacao = "paisagem" if receita.orientacao(imp, *self._dims()) == "retrato" else "retrato"
        if imp.recorte.origem == "manual":
            imp.recorte = self._limitado(imp, imp.recorte)
        elif foto.id in self.estado.info:
            self.estado.refazer_recortes_auto(foto)
        else:    # metadados ainda não chegaram: o recorte sai das proporções do proxy (como em enquadrar_pelos_rostos)
            imp.recorte = enquadramento.recorte_sugerido(imp, *self._dims(), foto.rostos,
                                                         self.estado.trabalho.margem_corte_mm)
        self.estado.alterar(foto, pedido=True)
        return True

    def mostrar_rostos(self, sim: bool) -> None:
        if self.caixa_rostos.isChecked() != sim:
            self.caixa_rostos.setChecked(sim)
            return
        self.tela.mostrar_rostos = sim
        self.tela.update()

    def definir_previa(self, sim: bool) -> None:
        """Liga/desliga o "Resultado" (a prévia pela receita no tamanho do visor); desligado, volta à "Moldura"."""
        self.modo_vista.definir_atual("resultado" if sim else "moldura")
        self.mostrar_previa = sim
        self._atualizar()
        self._agendar_previa()

    # ------------------------------------------------------------ navegação entre as fotos (←/→, Home/End)
    def navegar(self, passo: int) -> bool:
        """Vai para a foto ``passo`` posições adiante (negativo: para trás) entre as visíveis na grade (o filtro vale).

        Para nas pontas (sem dar a volta). ``True`` se a foto atual mudou.
        """
        foto = self.estado.vizinha(passo)
        if foto is None or foto is self.estado.atual:
            return False
        self.estado.definir_atual(foto)
        return True

    def ir_para_ponta(self, ultima: bool) -> bool:
        """Vai para a primeira (Home) ou a última (End) foto visível na grade."""
        ids = self.estado.visiveis
        foto = self.estado.por_id(ids[-1 if ultima else 0]) if ids else None
        if foto is None or foto is self.estado.atual:
            return False
        self.estado.definir_atual(foto)
        return True

    # ------------------------------------------------------------ mouse -> gestos
    def _ponto_da_tela(self, pos: QPointF) -> tuple[float, float] | None:
        """A posição do visor como fração da imagem girada (nos dois modos de ver)."""
        quadro = self.tela.quadro()
        ctx = self._contexto()
        if quadro is None or ctx is None:
            return None
        imp = ctx[1]
        W, H = receita.dimensoes_giradas(imp, *self._dims())
        if not self.mostrando_previa:
            k = self.tela.escala_imagem()
            return (pos.x() - quadro.left()) / k / W, (pos.y() - quadro.top()) / k / H
        if imp.modo == receita.MODO_CABER:
            return None
        k = quadro.width()
        u, v = (pos.x() - quadro.left()) / k, (pos.y() - quadro.top()) / quadro.height()
        x, y = receita.ponto_da_fonte(self._retangulo(imp), (1.0, 1.0), u, v)
        return x / W, y / H

    def _ao_arrastar(self, dx: float, dy: float) -> None:
        ctx = self._editavel()
        quadro = self.tela.quadro()
        if ctx is None or quadro is None:
            return
        imp = ctx[1]
        W, H = receita.dimensoes_giradas(imp, *self._dims())
        if not self.mostrando_previa:
            k = self.tela.escala_imagem()
            self.mover(dx / k / W, dy / k / H)
            return
        # Na prévia a foto acompanha o mouse: o recorte anda no sentido contrário, girado pelo ângulo.
        r = self._retangulo(imp)
        s = r.w / quadro.width()
        t = math.radians(-r.angulo)
        vx, vy = dx * math.cos(t) - dy * math.sin(t), dx * math.sin(t) + dy * math.cos(t)
        self.mover(-vx * s / W, -vy * s / H)

    def _ao_rolar(self, passos: float, pos: QPointF) -> None:
        self.aproximar(PASSO_ZOOM ** passos, self._ponto_da_tela(pos))

    def _ao_arrastar_alca(self, canto: int, pos: QPointF) -> None:
        if self.mostrando_previa:      # as alças só existem na moldura
            return
        ponto = self._ponto_da_tela(pos)
        if ponto is not None:
            self.puxar_canto(canto, ponto)

    # ------------------------------------------------------------ reação ao Estado
    def _atual_mudou(self, foto: Foto | None) -> None:
        self._ger_proxy += 1
        self.proxy, self.previa, self._erro = None, None, ""
        self._imagens.clear()
        self._caminho = None
        self._timer.stop()
        self._limpar_ajustada()
        self.previa_geracao += 1
        if foto is not None:
            self._caminho = str(foto.caminho)
            self._pool.start(CarregarProxy(self._sinais, self._ger_proxy, foto.caminho))
        self._atualizar()

    def _foto_mudou(self, foto_id: str) -> None:
        if self.estado.atual is not None and self.estado.atual.id == foto_id:
            self._agendar_ajustada()
            self._atualizar()
            self._agendar_previa()

    def _impressao_mudou(self, _indice: int) -> None:
        self._agendar_ajustada()
        self._atualizar()
        self._agendar_previa()

    def _proxy_pronto(self, geracao: int, caminho: str, proxy: object) -> None:
        if geracao != self._ger_proxy:
            return
        self.proxy = proxy
        self._imagens.clear()
        self._agendar_ajustada()
        self._atualizar()
        self._agendar_previa()
        self.proxy_carregado.emit()

    def _proxy_erro(self, geracao: int, _caminho: str, mensagem: str) -> None:
        if geracao != self._ger_proxy:
            return
        self._erro = mensagem
        self._atualizar()

    def _comparando_mudou(self, _sim: bool) -> None:
        self._atualizar()
        self._agendar_previa()

    def _ajustes_da_foto(self) -> dict:
        """Ajustes da foto atual (só os fora do padrão), ou ``{}`` no antes/depois."""
        foto = self.estado.atual
        if foto is None or self.estado.comparando:
            return {}
        return ajustes_mod.sanitizar(foto.ajustes)

    # ------------------------------------------------------------ moldura ajustada (foto inteira com os ajustes)
    def _limpar_ajustada(self) -> None:
        self._ger_ajuste += 1
        self._timer_ajuste.stop()
        self._timer_fino.stop()
        self._ajustada, self._chave_ajustada, self._ajustada_final = None, None, False

    def _agendar_ajustada(self) -> None:
        """Pede a foto inteira ajustada: primeiro reduzida (rápida), depois no tamanho do proxy quando parar de mexer.

        Só refaz se o giro ou os valores mudaram (mover o recorte não recalcula nada).
        """
        foto, imp = self.estado.atual, self.estado.impressao_atual
        if foto is None or self.proxy is None:
            return
        valores = ajustes_mod.sanitizar(foto.ajustes)
        if not valores:
            self._limpar_ajustada()
            return
        giro = imp.recorte.giro % 4 if imp is not None else 0
        chave = (giro, tuple(sorted(valores.items())))
        if chave == self._chave_ajustada:
            return
        self._chave_ajustada = chave
        self._ger_ajuste += 1
        self._timer_ajuste.start()
        self._timer_fino.start()

    def _escala_moldura(self, imp: Impressao | None, largura_img: int) -> float | None:
        """Px por mm de papel da foto inteira exibida em ``largura_img`` px (a nitidez é em mm de papel)."""
        if imp is None:
            return None
        try:
            w, h = self._dims()
            W, _H = receita.dimensoes_giradas(imp, w, h)
            ret = receita.retangulo_da_impressao(imp, w, h)
            papel_l = receita.papel_orientado_mm(imp, w, h)[0]
            return largura_img / W * ret.w / papel_l
        except (KeyError, ValueError, ZeroDivisionError):
            return None

    def _disparar_ajustada(self, max_lado: int | None, final: bool) -> None:
        imp = self.estado.impressao_atual
        if self.estado.atual is None or self.proxy is None or self._chave_ajustada is None:
            return
        giro = self._chave_ajustada[0]
        W = self.proxy.shape[1] if giro % 2 == 0 else self.proxy.shape[0]
        escala = self._escala_moldura(imp, W)
        self._pool.start(AjustarImagem(self._sinais, self._ger_ajuste, self.proxy, giro,
                                       dict(self._chave_ajustada[1]), escala, max_lado, final))

    def _ajustada_pronta(self, geracao: int, final: bool, imagem: object) -> None:
        if geracao != self._ger_ajuste:
            return
        if self._ajustada is not None and self._ajustada_final and not final:
            return          # a versão reduzida chegou depois da final da mesma geração
        self._ajustada, self._ajustada_final = imagem, final
        self._ajustada_giro = self._chave_ajustada[0] if self._chave_ajustada else 0
        self._atualizar()
        self.ajustada_atualizada.emit()

    # ------------------------------------------------------------ prévia (receita num trabalhador)
    def _agendar_previa(self) -> None:
        """Invalida a prévia em andamento e recalcula depois do *debounce*."""
        self.previa_geracao += 1
        if self.mostrando_previa and self._contexto() is not None:
            self._timer.start()
        else:
            self._timer.stop()

    def _disparar_previa(self) -> None:
        ctx = self._contexto()
        if ctx is None or not self.mostrando_previa:
            return
        foto, imp = ctx
        dpr = self.tela.devicePixelRatioF()
        area = self.tela.area_util()
        destino = receita.destino_na_caixa(imp, *self._dims(), int(area.width() * dpr), int(area.height() * dpr))
        self._dpr_previa = dpr
        self._pool.start(RenderizarPrevia(self._sinais, self.previa_geracao, self.proxy, imp, self._ajustes_da_foto(), destino))

    def _previa_pronta(self, geracao: int, imagem: object) -> None:
        if geracao != self.previa_geracao:
            return          # resultado velho: o recorte ou o visor mudou enquanto calculava
        imagem.setDevicePixelRatio(self._dpr_previa)
        self.previa = imagem
        self._atualizar()
        self.previa_atualizada.emit()

    def _previa_erro(self, geracao: int, mensagem: str) -> None:
        if geracao == self.previa_geracao:
            self._erro = mensagem
            self._atualizar()

    # ------------------------------------------------------------ atualizar o visor e os controles
    def _imagem_girada(self, giro: int) -> QImage:
        if giro not in self._imagens:
            self._imagens[giro] = para_qimage(receita.para_uint8(receita.girar(self.proxy, giro)))
        return self._imagens[giro]

    def _atualizar(self) -> None:
        t = self.tela
        foto, imp = self.estado.atual, self.estado.impressao_atual
        t.moldura, t.rostos, t.margem_rel, t.dica = None, [], 0.0, ""
        t.imagem, t.mostrar_rostos = None, self.caixa_rostos.isChecked()
        info = ""
        qualidade = None
        if foto is None:
            t.mensagem = _("Escolha uma foto na grade para enquadrar")
        elif self._erro:
            t.mensagem = self._erro
        elif self.proxy is None:
            t.mensagem = _("Carregando a foto…")
        else:
            t.mensagem = ""
            giro = imp.recorte.giro % 4 if imp is not None else 0
            bruta = self._imagem_girada(giro)
            t.largura_ref = bruta.width()
            usar = (self._ajustada is not None and self._ajustada_giro == giro and not self.estado.comparando
                    and self._chave_ajustada is not None)
            t.imagem = self._ajustada if usar else bruta
            if imp is None:
                t.dica = _("Marque a foto para revelar e escolha o tamanho")
            else:
                info, qualidade = self._preencher_moldura(foto, imp)
        t.mostrar_previa = self.mostrando_previa and self.previa is not None
        t.previa = self.previa
        editavel = self._editavel() is not None
        t.alcas = editavel and not self.mostrando_previa   # nem no modo caber nem no "Resultado"
        t.definir_arrastavel(editavel)
        self.rotulo_info.setText(info)
        cor = {"baixa": tema.PERIGO, "aceitavel": tema.AVISO}.get(qualidade or "")
        self.rotulo_info.setStyleSheet(f"color: {cor};" if cor else "")
        self._sincronizar_controles(imp)
        t.update()

    def _preencher_moldura(self, foto: Foto, imp: Impressao) -> tuple[str, str | None]:
        """Dá à tela a moldura, a margem e os rostos; devolve o texto de resolução e a qualidade ("boa" etc. ou None)."""
        t = self.tela
        largura, altura = self._dims()
        orient = receita.orientacao(imp, largura, altura)
        try:
            nome = _(tamanhos.obter(imp.tamanho).nome)
        except KeyError:
            nome = _("Personalizado")
        papel_l, _papel_a = receita.papel_orientado_mm(imp, largura, altura)
        t.margem_rel = max(0.0, self.estado.trabalho.margem_corte_mm) / papel_l
        texto = f"{nome} · {_(orient)}"
        if imp.modo == receita.MODO_CABER:
            return texto + " · " + _("foto inteira com borda branca"), None
        W, H = receita.dimensoes_giradas(imp, largura, altura)
        r = self._retangulo(imp)
        t.moldura = r
        if foto.rostos:
            t.rostos = [(c.x * W, c.y * H, c.w * W, c.h * H)
                        for c in enquadramento.girar_rostos(foto.rostos, imp.recorte.giro)]
        info = self.estado.info.get(foto.id)
        qualidade = None
        if info is not None:
            largura_orig = info.altura if imp.recorte.giro % 2 else info.largura   # largura da imagem girada
            px_recorte = r.w / W * largura_orig
            dpi = tamanhos.resolucao_efetiva(round(px_recorte), imp.tamanho, orient, imp.papel_mm)
            q = tamanhos.qualidade(dpi)
            qualidade = q
            texto += f" · {dpi:.0f} dpi ({_(QUALIDADES[q])})"
        return texto, qualidade

    def _sincronizar_controles(self, imp: Impressao | None) -> None:
        ativo = self._editavel() is not None
        com_foto = self._contexto() is not None
        for w in (self.slider_angulo, self.botao_zoom_menos, self.botao_zoom_mais):
            w.setEnabled(ativo)
        for w in (self.botao_girar_esq, self.botao_girar_dir, self.botao_papel, self.botao_auto, self.modo_vista):
            w.setEnabled(com_foto)
        angulo = imp.recorte.angulo if imp is not None else 0.0
        self.slider_angulo.definir_valor(round(angulo, 1))

    # ------------------------------------------------------------ encerramento
    def encerrar(self) -> None:
        """Espera os trabalhadores terminarem (chamado ao fechar o aplicativo)."""
        self._timer.stop()
        self._timer_ajuste.stop()
        self._timer_fino.stop()
        self._ger_ajuste += 1
        self._ger_proxy += 1
        self.previa_geracao += 1
        self._pool.waitForDone(3000)
