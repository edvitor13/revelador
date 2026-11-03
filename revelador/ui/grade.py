"""Grade de miniaturas: ``QListView`` em modo ícone com modelo próprio (aguenta ~1000 fotos).

Fala só com o ``Estado``: lê ``trabalho.fotos``, ``miniaturas`` e ``erros`` e reage a ``fotos_mudaram`` e
``foto_mudou``. Clique escolhe a foto atual; Espaço ou clique na marca liga/desliga a seleção para revelação;
Delete tira do trabalho (nunca do disco, sem confirmação); setas navegam. A miniatura é lida do cache em disco
sob demanda, só das células visíveis, com um cache pequeno de ``QPixmap``.

Clique direito abre o menu de contexto das fotos escolhidas (``Grade.menu_contexto``): marcar/desmarcar, tamanho e
cópias para todas de uma vez, "Adicionar à pasta ▸"/"Tirar da pasta ▸" (pastas de tamanho, #32), "Procurar…" (se
alguma falta no disco; sinal ``procurar_pedido``) e remover. Cada ação em várias fotos é um passo só do desfazer
(``estado.lote``).

Pastas de tamanho (#32): ``definir_pasta(id)`` filtra a grade pela pasta (junto com o filtro Todas | Selecionadas: a
grade mostra as fotos que passam nos DOIS); arrastar as fotos escolhidas leva os ids delas (``pastas.MIME_FOTOS``)
para uma linha da seção Pastas; o chip de uma impressão de pasta ganha a cor dela (``layout_chips(..., pastas=)``).
"""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import QAbstractListModel, QModelIndex, QPoint, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QDrag, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QHBoxLayout, QListView, QMenu, QPushButton, QStyle,
                               QStyledItemDelegate, QStyleOptionViewItem, QToolButton, QVBoxLayout, QWidget)

from .. import tamanhos
from ..i18n import _
from ..projeto import Foto, Impressao, Pasta
from . import icones, prefs, tema
from .componentes import Slider
from .estado import Estado
from .painel_impressoes import LIMITE_COPIAS, NOMES_GRUPOS, refazer_enquadramento
from .pastas import MIME_FOTOS, dialogo_nova_pasta, mime_das_fotos, nome_tamanho

MINIATURA_PADRAO = 150  # lado da miniatura (o tamanho com que a grade sempre abriu)
MINIATURA_MINIMA = 80
MINIATURA_MAXIMA = 320
PASSO_MINIATURA = 10
LADO_COMPACTO = 120     # abaixo disso o nome some e os chips viram só a contagem de cópias
MARGEM_CARTAO = 4       # entre a célula e o cartão
MARGEM_MINIATURA = 6    # entre o cartão e a miniatura
MARGEM_TOTAL = 2 * (MARGEM_CARTAO + MARGEM_MINIATURA)
ALTURA_TOPO = MARGEM_CARTAO + MARGEM_MINIATURA   # da borda da célula até a miniatura
ALTURA_RODAPE = 54          # da miniatura até a borda: nome, chips e margens
ALTURA_RODAPE_COMPACTO = 34
ESPACO_ROLAGEM = 40     # barra de rolagem e folga: a largura mínima da grade conta com ela
RAIO_CARTAO = 12
RAIO_MINIATURA = 8
TAMANHO_MARCA = 24
ALTURA_CHIP = 18
SEM_PASTA = "__sem_pasta__"   # valor do filtro da grade: fotos marcadas fora de qualquer pasta de tamanho
LARGURA_MAIS = 15       # zona do "−" (à esquerda) e do "+" (à direita) dentro de cada chip
LIMITE_PIXMAPS = 400
PAPEL_FOTO = Qt.ItemDataRole.UserRole
CHAVE_PREF = "grade/miniatura"
ATRASO_NA_TELA_MS = 150    # debounce da publicação das fotos na tela (rostos, #36)
COPIAS_MENU = (1, 2, 3, 5, 10)   # atalhos do submenu "Cópias" do menu de contexto
LADO_ARRASTO = 64                # miniatura que acompanha o mouse ao arrastar fotos para uma pasta


def limitar_miniatura(lado: int) -> int:
    """Lado da miniatura dentro da faixa permitida."""
    return min(max(int(lado), MINIATURA_MINIMA), MINIATURA_MAXIMA)


def tamanho_miniatura_salvo() -> int:
    """Lado da miniatura lembrado nas preferências (o padrão se não houver ou for inválido)."""
    try:
        return limitar_miniatura(prefs.settings().value(CHAVE_PREF))
    except (TypeError, ValueError):
        return MINIATURA_PADRAO


def celula(lado: int) -> QSize:
    """Tamanho de uma célula da grade para miniaturas de ``lado`` px."""
    altura = ALTURA_RODAPE_COMPACTO if lado < LADO_COMPACTO else ALTURA_RODAPE
    return QSize(lado + MARGEM_TOTAL, ALTURA_TOPO + lado + altura)


def largura_duas_colunas(lado: int) -> int:
    """Menor largura da grade que mostra duas colunas (com a barra de rolagem)."""
    return 2 * celula(lado).width() + ESPACO_ROLAGEM


def rotulo_impressao(tamanho: str, copias: int) -> str:
    """Texto do chip de uma impressão: ``10x15 ×2``."""
    try:
        nome = _(tamanhos.obter(tamanho).nome)
    except KeyError:
        nome = _("Personalizado")
    return f"{nome} ×{copias}"


def rect_miniatura(celula: QRect) -> QRect:
    """Quadrado da miniatura dentro da célula."""
    cartao = celula.adjusted(MARGEM_CARTAO, MARGEM_CARTAO, -MARGEM_CARTAO, -MARGEM_CARTAO)
    lado = cartao.width() - 2 * MARGEM_MINIATURA
    return QRect(cartao.left() + MARGEM_MINIATURA, cartao.top() + MARGEM_MINIATURA, lado, lado)


def rect_marca(celula: QRect) -> QRect:
    """Retângulo da marca de seleção (canto superior esquerdo da miniatura); encolhe com ela."""
    miniatura = rect_miniatura(celula)
    lado = max(14, min(TAMANHO_MARCA, round(miniatura.width() * 0.16)))
    return QRect(miniatura.left() + 8, miniatura.top() + 8, lado, lado)


def compacta(celula: QRect) -> bool:
    """Miniatura abaixo de ``LADO_COMPACTO``: sem nome, e o chip mostra só o total de cópias."""
    return rect_miniatura(celula).width() < LADO_COMPACTO


def area_chips(celula: QRect) -> QRect:
    """Faixa dos chips de impressão, abaixo do nome do arquivo (ou logo abaixo da miniatura, se compacta)."""
    miniatura = rect_miniatura(celula)
    if compacta(celula):
        topo = miniatura.bottom() + 8
    else:
        topo = miniatura.bottom() + 8 + 16 + 5     # mesma conta do nome em DelegadoGrade.paint
    return QRect(miniatura.left() + 2, topo, miniatura.width() - 4, ALTURA_CHIP)


def _fonte_chip() -> QFont:
    return tema.fonte(8, QFont.Weight.DemiBold)


class Chip(tuple):
    """Um chip: a tupla (retângulo, índice da impressão ou None no "+N", texto, apagado) e, em ``cor``, o hexadecimal
    da pasta de tamanho da impressão (None: impressão avulsa ou "+N", no laranja/cinza de sempre)."""

    cor: str | None

    def __new__(cls, retangulo: QRect, indice: int | None, texto: str, apagado: bool, cor: str | None = None):
        chip = super().__new__(cls, (retangulo, indice, texto, apagado))
        chip.cor = cor
        return chip


def _cor_da_impressao(imp: Impressao, pastas: dict[str, Pasta]) -> str | None:
    pasta = pastas.get(imp.pasta) if imp.pasta is not None else None
    return tema.cor_pasta(pasta.cor) if pasta is not None else None


def layout_chips(area: QRect, foto: Foto, compacto: bool = False,
                 pastas: list[Pasta] | dict[str, Pasta] | None = None) -> list[Chip]:
    """Chips da foto dentro de ``area``: ``Chip`` = (retângulo, índice da impressão ou None no "+N", texto, apagado),
    com ``cor`` = cor da pasta de tamanho da impressão (``pastas``: as do trabalho; sem elas, nenhuma cor).

    Compacto: um único chip "×N" com o total de cópias; o clique nele age sobre a primeira impressão. A cor dele é a
    da primeira impressão que está numa pasta (na ordem das impressões).
    """
    if not foto.impressoes:
        return []
    por_id = pastas if isinstance(pastas, dict) else {p.id: p for p in (pastas or ())}
    medidas = QFontMetrics(_fonte_chip())
    if compacto:
        texto = f"×{sum(i.copias for i in foto.impressoes)}"
        largura = min(medidas.horizontalAdvance(texto) + 16 + 2 * LARGURA_MAIS, area.width())
        cor = next((c for c in (_cor_da_impressao(i, por_id) for i in foto.impressoes) if c), None)
        return [Chip(QRect(area.left(), area.top(), largura, ALTURA_CHIP), 0, texto, False, cor)]
    textos = [rotulo_impressao(i.tamanho, i.copias) for i in foto.impressoes]
    saida: list[Chip] = []
    x = area.left()
    for n, texto in enumerate(textos):
        largura = medidas.horizontalAdvance(texto) + 16 + 2 * LARGURA_MAIS
        resto = len(textos) - n - 1
        reserva = medidas.horizontalAdvance(f"+{resto}") + 16 + 4 if resto else 0
        if x + largura + reserva > area.right() + 1 and n > 0:
            sobra = f"+{len(textos) - n}"
            saida.append(Chip(QRect(x, area.top(), medidas.horizontalAdvance(sobra) + 16, ALTURA_CHIP), None, sobra,
                              True))
            return saida
        retangulo = QRect(x, area.top(), min(largura, area.right() - x + 1), ALTURA_CHIP)
        saida.append(Chip(retangulo, n, medidas.elidedText(texto, Qt.TextElideMode.ElideRight,
                                                           area.right() - x - 14 - 2 * LARGURA_MAIS),
                          False, _cor_da_impressao(foto.impressoes[n], por_id)))
        x += largura + 4
    return saida


def chip_em(celula: QRect, foto: Foto, ponto: QPoint) -> int | None:
    """Índice da impressão cujo chip está sob ``ponto`` (None se nenhum, ou se for o "+N")."""
    achado = chip_e_zona(celula, foto, ponto)
    return None if achado is None else achado[0]


def zona_chip(retangulo: QRect, ponto: QPoint) -> int:
    """-1 no "−" (ponta esquerda do chip), +1 no "+" (ponta direita), 0 no meio (o texto)."""
    if ponto.x() < retangulo.left() + LARGURA_MAIS:
        return -1
    if ponto.x() > retangulo.right() - LARGURA_MAIS:
        return +1
    return 0


def chip_e_zona(celula: QRect, foto: Foto, ponto: QPoint) -> tuple[int, int] | None:
    """(índice da impressão, zona) do chip sob ``ponto`` (zona: -1 "−", 0 texto, +1 "+"), ou None."""
    for retangulo, indice, _texto, _apagado in layout_chips(area_chips(celula), foto, compacta(celula)):
        if indice is not None and retangulo.contains(ponto):
            return indice, zona_chip(retangulo, ponto)
    return None


class ModeloGrade(QAbstractListModel):
    """Fotos visíveis, na ordem de importação: todas ou só as selecionadas e, com ``pasta``, só as dessa pasta de
    tamanho (os dois filtros juntos). Arrastar leva os ids das fotos (``MIME_FOTOS``)."""

    def __init__(self, estado: Estado, parent=None) -> None:
        super().__init__(parent)
        self.estado = estado
        self.so_selecionadas = False
        self.pasta: str | None = None   # id da pasta de tamanho filtrada (None = sem filtro de pasta)
        self.tamanho: str | None = None  # id do tamanho filtrado (None = todos os tamanhos)
        self._fotos: list[Foto] = []
        self._linha: dict[str, int] = {}
        self._pixmaps: OrderedDict[str, QPixmap] = OrderedDict()
        self.recarregar()

    def filtrando(self) -> bool:
        return self.so_selecionadas or self.pasta is not None or self.tamanho is not None

    def passa(self, foto: Foto) -> bool:
        """A foto passa nos filtros (selecionadas e pasta)?"""
        if self.so_selecionadas and not foto.selecionada:
            return False
        if self.tamanho == SEM_PASTA:
            if any(i.pasta is not None for i in foto.impressoes):
                return False
        elif self.tamanho is not None and not (foto.selecionada and any(i.tamanho == self.tamanho
                                                                        for i in foto.impressoes)):
            return False
        return self.pasta is None or any(i.pasta == self.pasta for i in foto.impressoes)

    def _visiveis(self) -> list[Foto]:
        fotos = self.estado.trabalho.fotos
        return [f for f in fotos if self.passa(f)] if self.filtrando() else list(fotos)

    def recarregar(self) -> None:
        self.beginResetModel()
        self._fotos = self._visiveis()
        self._linha = {f.id: i for i, f in enumerate(self._fotos)}
        self._pixmaps.clear()
        self.endResetModel()
        self.estado.definir_visiveis([f.id for f in self._fotos])

    def foto_mudou(self, foto_id: str) -> None:
        if self.filtrando():
            linha = self._linha.get(foto_id)
            foto = self._fotos[linha] if linha is not None else self.estado.por_id(foto_id)
            if foto is not None and self.passa(foto) != (linha is not None):
                self.recarregar()
                return
        linha = self._linha.get(foto_id)
        if linha is not None:
            self._pixmaps.pop(foto_id, None)
            indice = self.index(linha)
            self.dataChanged.emit(indice, indice)

    def foto(self, linha: int) -> Foto | None:
        return self._fotos[linha] if 0 <= linha < len(self._fotos) else None

    def indice_da_foto(self, foto: Foto | None) -> QModelIndex:
        linha = self._linha.get(foto.id) if foto is not None else None
        return self.index(linha) if linha is not None else QModelIndex()

    def pixmap(self, foto: Foto) -> QPixmap | None:
        pm = self._pixmaps.get(foto.id)
        if pm is not None:
            self._pixmaps.move_to_end(foto.id)
            return pm
        caminho = self.estado.miniaturas.get(foto.id)
        if caminho is None:
            return None
        pm = QPixmap(str(caminho))
        if pm.isNull():
            return None
        self._pixmaps[foto.id] = pm
        while len(self._pixmaps) > LIMITE_PIXMAPS:
            self._pixmaps.popitem(last=False)
        return pm

    # ------------------------------------------------------------ interface do modelo
    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        flags = super().flags(index)
        return flags | Qt.ItemFlag.ItemIsDragEnabled if index.isValid() else flags

    def mimeTypes(self) -> list[str]:  # noqa: N802
        return [MIME_FOTOS]

    def mimeData(self, indices):  # noqa: N802
        fotos = [self.foto(i.row()) for i in sorted(indices, key=lambda i: i.row())]
        return mime_das_fotos(f for f in fotos if f is not None)

    def supportedDragActions(self) -> Qt.DropAction:  # noqa: N802
        return Qt.DropAction.CopyAction

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._fotos)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        foto = self.foto(index.row()) if index.isValid() else None
        if foto is None:
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return foto.caminho.name
        if role == Qt.ItemDataRole.ToolTipRole:
            erro = self.estado.erros.get(foto.id)
            return f"{foto.caminho.name}\n{erro}" if erro else str(foto.caminho)
        if role == PAPEL_FOTO:
            return foto
        return None


class DelegadoGrade(QStyledItemDelegate):
    """Desenha cada célula: miniatura de cantos suaves, marca de seleção, nome e chips dos tamanhos."""

    def __init__(self, modelo: ModeloGrade, parent=None) -> None:
        super().__init__(parent)
        self.modelo = modelo
        self.lado = MINIATURA_PADRAO

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        return celula(self.lado)

    def paint(self, p: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        foto: Foto | None = index.data(PAPEL_FOTO)
        if foto is None:
            return
        estados = option.state
        atual = bool(estados & QStyle.StateFlag.State_Selected)
        sobre = bool(estados & QStyle.StateFlag.State_MouseOver)
        cartao = option.rect.adjusted(MARGEM_CARTAO, MARGEM_CARTAO, -MARGEM_CARTAO, -MARGEM_CARTAO)
        miniatura = rect_miniatura(option.rect)
        compacto = miniatura.width() < LADO_COMPACTO
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setPen(Qt.PenStyle.NoPen)
        if atual:
            fundo = QColor(tema.DESTAQUE)
            fundo.setAlpha(34)
            p.setBrush(fundo)
            p.drawRoundedRect(cartao, RAIO_CARTAO, RAIO_CARTAO)
        elif sobre:
            p.setBrush(QColor(tema.PAINEL2))
            p.drawRoundedRect(cartao, RAIO_CARTAO, RAIO_CARTAO)

        # miniatura
        p.setBrush(QColor(tema.PAINEL2))
        p.drawRoundedRect(miniatura, RAIO_MINIATURA, RAIO_MINIATURA)
        erro = foto.id in self.modelo.estado.erros
        pm = self.modelo.pixmap(foto)
        if pm is not None and not erro:
            area = miniatura
            alvo = pm.size().scaled(area.size(), Qt.AspectRatioMode.KeepAspectRatio)
            alvo_r = QRect(QPoint(area.center().x() - alvo.width() // 2 + 1, area.center().y() - alvo.height() // 2 + 1),
                           alvo)
            recorte = QPainterPath()
            recorte.addRoundedRect(QRectF(alvo_r), RAIO_MINIATURA - 2, RAIO_MINIATURA - 2)
            p.setClipPath(recorte)
            p.drawPixmap(alvo_r, pm)
            p.setClipping(False)
        elif erro:
            icone = icones.icone("aviso", tema.PERIGO, 28).pixmap(28, 28)
            p.drawPixmap(miniatura.center().x() - 14, miniatura.center().y() - 22, icone)
            if not compacto:
                p.setPen(QColor(tema.PERIGO))
                p.setFont(tema.fonte(8.5))
                p.drawText(QRect(miniatura.left(), miniatura.center().y() + 12, miniatura.width(), 18),
                           Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, _("Não abriu"))
        else:
            icone = icones.icone("foto", tema.FRACO, 28).pixmap(28, 28)
            p.setOpacity(0.5)
            p.drawPixmap(miniatura.center().x() - 14, miniatura.center().y() - 14, icone)
            p.setOpacity(1.0)
        if atual:
            p.setPen(QPen(QColor(tema.DESTAQUE), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(miniatura).adjusted(1, 1, -1, -1), RAIO_MINIATURA, RAIO_MINIATURA)

        self._marca(p, option.rect, foto, atual or sobre)

        # nome do arquivo (apagado, cortado com "…"); nas miniaturas pequenas ele some
        if not compacto:
            p.setFont(tema.fonte(8.5))
            p.setPen(QColor(tema.TEXTO if atual else tema.APAGADO))
            nome_r = QRect(miniatura.left() + 2, miniatura.bottom() + 8, miniatura.width() - 4, 16)
            p.drawText(nome_r, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       p.fontMetrics().elidedText(foto.caminho.name, Qt.TextElideMode.ElideRight, nome_r.width()))
        self._chips(p, area_chips(option.rect), foto, compacto)
        p.restore()

    def _marca(self, p: QPainter, celula: QRect, foto: Foto, visivel: bool) -> None:
        """Marca de seleção para revelação: círculo vazio (só com o mouse em cima) ou laranja com visto."""
        marca = rect_marca(celula)
        if foto.selecionada:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(tema.DESTAQUE))
            p.drawEllipse(marca)
            p.save()
            p.translate(marca.left() + marca.width() * 0.17, marca.top() + marca.height() * 0.17)
            p.scale(marca.width() * 0.66 / 24.0, marca.height() * 0.66 / 24.0)
            icones.desenhar("check", p, QColor(tema.TEXTO_SOBRE_DESTAQUE))
            p.restore()
        elif visivel:
            p.setBrush(QColor(0, 0, 0, 120))
            p.setPen(QPen(QColor(255, 255, 255, 215), 1.6))
            p.drawEllipse(QRectF(marca).adjusted(1, 1, -1, -1))

    def _chips(self, p: QPainter, area: QRect, foto: Foto, compacto: bool = False) -> None:
        """Um chip em pílula por impressão ("10x15 ×2"); o que não couber vira "+N". Compacto: só o total de cópias."""
        if not foto.impressoes:
            return
        p.setFont(_fonte_chip())
        for chip in layout_chips(area, foto, compacto, self.modelo.estado.trabalho.pastas):
            retangulo, indice, texto, apagado = chip
            self._pilula(p, retangulo, texto, apagado=apagado, cor=chip.cor, botoes=indice is not None)

    @staticmethod
    def _pilula(p: QPainter, r: QRect, texto: str, apagado: bool = False, cor: str | None = None,
                botoes: bool = False) -> None:
        """Pílula do chip: laranja (impressão avulsa), a cor da pasta (impressão de pasta) ou cinza ("+N")."""
        fundo = QColor(tema.PAINEL3) if apagado else QColor(cor or tema.DESTAQUE)
        if not apagado:
            fundo.setAlpha(56 if cor else 46)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(fundo)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        if apagado:
            p.setPen(QColor(tema.APAGADO))
        else:
            p.setPen(QColor(cor).lighter(135) if cor else QColor(tema.DESTAQUE_HI))
        if not botoes:
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, texto)
            return
        p.drawText(r.adjusted(LARGURA_MAIS, 0, -LARGURA_MAIS, 0), Qt.AlignmentFlag.AlignCenter, texto)
        cor_mais = QColor(tema.TEXTO)
        cor_mais.setAlpha(170)
        p.setPen(cor_mais)
        p.drawText(QRect(r.left() + 2, r.top(), LARGURA_MAIS, r.height()), Qt.AlignmentFlag.AlignCenter, "−")
        p.drawText(QRect(r.right() - LARGURA_MAIS - 1, r.top(), LARGURA_MAIS, r.height()),
                   Qt.AlignmentFlag.AlignCenter, "+")


class _Lista(QListView):
    def __init__(self, grade: "Grade") -> None:
        super().__init__()
        self.grade = grade

    def wheelEvent(self, evento) -> None:  # noqa: N802
        """Ctrl + roda do mouse muda o tamanho das miniaturas; sem Ctrl, rola a grade."""
        dy = evento.angleDelta().y()
        if evento.modifiers() & Qt.KeyboardModifier.ControlModifier and dy:
            self.grade.ajustar_miniatura(PASSO_MINIATURA if dy > 0 else -PASSO_MINIATURA)
            evento.accept()
            return
        super().wheelEvent(evento)

    def mousePressEvent(self, evento) -> None:  # noqa: N802
        indice = self.indexAt(evento.position().toPoint())
        if indice.isValid() and evento.button() == Qt.MouseButton.LeftButton:
            ponto = evento.position().toPoint()
            if rect_marca(self.visualRect(indice)).contains(ponto):
                self.grade.alternar(indice)
                self.setCurrentIndex(indice)
                return
            foto = self.grade.modelo.foto(indice.row())
            achado = chip_e_zona(self.visualRect(indice), foto, ponto) if foto is not None else None
            if achado is not None:
                self.grade.clicar_chip(indice, achado[0], achado[1])
                return
        super().mousePressEvent(evento)

    def startDrag(self, _acoes) -> None:  # noqa: N802
        """Arrasta as fotos escolhidas (para uma pasta da seção Pastas), com uma miniatura e o número delas."""
        fotos = self.grade.fotos_escolhidas()
        if not fotos:
            return
        arrasto = QDrag(self)
        arrasto.setMimeData(mime_das_fotos(fotos))
        arrasto.setPixmap(self.grade.pixmap_arrasto(fotos))
        arrasto.setHotSpot(QPoint(LADO_ARRASTO // 2, LADO_ARRASTO // 2))
        arrasto.exec(Qt.DropAction.CopyAction, Qt.DropAction.CopyAction)

    def contextMenuEvent(self, evento) -> None:  # noqa: N802
        indice = self.indexAt(evento.pos())
        if indice.isValid() and not self.selectionModel().isSelected(indice):
            self.setCurrentIndex(indice)   # clique direito fora da seleção: escolhe só a foto clicada
        fotos = self.grade.fotos_escolhidas()
        menu = self.grade.menu_contexto(fotos) if fotos else None
        if menu is not None and menu.actions():
            menu.exec(evento.globalPos())
        if menu is not None:
            menu.deleteLater()

    def keyPressEvent(self, evento) -> None:  # noqa: N802
        if evento.key() == Qt.Key.Key_Space:
            self.grade.alternar_atual()
        elif evento.key() == Qt.Key.Key_Delete:
            self.grade.remover_selecionados()
        else:
            super().keyPressEvent(evento)


class Grade(QWidget):
    """A grade de miniaturas ligada ao ``Estado``. Rodapé com o tamanho das miniaturas (lembrado nas preferências)."""

    tamanho_mudou = Signal(int)
    repetidas_pedido = Signal()  # botão "Repetidas…" no topo da grade; a janela liga
    procurar_pedido = Signal()   # "Procurar…" no menu de contexto (fotos que faltam no disco); a janela liga

    def __init__(self, estado: Estado, parent=None) -> None:
        super().__init__(parent)
        self.estado = estado
        self.modelo = ModeloGrade(estado, self)
        self.lista = _Lista(self)
        self.lista.setObjectName("lista_grade")
        self.lista.setModel(self.modelo)
        self.delegado = DelegadoGrade(self.modelo, self.lista)
        self.lado = tamanho_miniatura_salvo()
        self.delegado.lado = self.lado
        self.lista.setItemDelegate(self.delegado)
        self.lista.setGridSize(celula(self.lado))
        self.lista.setViewMode(QListView.ViewMode.IconMode)
        self.lista.setMovement(QListView.Movement.Static)
        self.lista.setResizeMode(QListView.ResizeMode.Adjust)
        self.lista.setUniformItemSizes(True)
        self.lista.setSpacing(0)
        self.lista.setMouseTracking(True)
        self.lista.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.lista.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.lista.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.lista.setFrameShape(QListView.Shape.NoFrame)
        self.lista.setDragEnabled(True)        # arrastar fotos para uma pasta de tamanho (#32)
        self.lista.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.lista.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.controle = Slider(_("Miniaturas"), MINIATURA_MINIMA, MINIATURA_MAXIMA, PASSO_MINIATURA, self.lado, "px",
                               casas=0, horizontal=True, dica=_("Tamanho das miniaturas (Ctrl + roda do mouse também)"))
        self.controle.valor_mudou.connect(lambda v: self.definir_miniatura(int(round(v))))
        self.rodape = QWidget()
        self.rodape.setObjectName("Rodape")
        self.rodape.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        linha = QHBoxLayout(self.rodape)
        linha.setContentsMargins(12, 6, 12, 6)
        linha.addWidget(self.controle)
        self.combo_tamanho = QComboBox()
        self.combo_tamanho.setObjectName("filtro_tamanho")
        self.combo_tamanho.setToolTip(_("Mostrar só as fotos marcadas num tamanho, ou as que não estão em pasta"))
        self.combo_tamanho.currentIndexChanged.connect(self._ao_escolher_tamanho)
        self.botao_repetidas = QPushButton(_("Repetidas…"))
        self.botao_repetidas.setToolTip(_("Procurar fotos muito parecidas (arquivos diferentes) no trabalho"))
        self.botao_repetidas.clicked.connect(self.repetidas_pedido)
        self.topo = QWidget()
        topo = QHBoxLayout(self.topo)
        topo.setContentsMargins(12, 6, 12, 6)
        topo.setSpacing(8)
        self.botao_marcar = QToolButton()
        self.botao_marcar.setObjectName("Flat")
        self.botao_marcar.setText(_("Marcar"))
        self.botao_marcar.setToolTip(_("Marcar ou desmarcar para revelação todas as fotos mostradas"))
        self.botao_marcar.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu_marcar = QMenu(self.botao_marcar)
        menu_marcar.addAction(_("Marcar todas para revelação"), lambda: self.marcar_fotos(self.fotos_visiveis(), True))
        menu_marcar.addAction(_("Desmarcar todas"), lambda: self.marcar_fotos(self.fotos_visiveis(), False))
        self.botao_marcar.setMenu(menu_marcar)
        topo.addWidget(self.combo_tamanho, 1)
        topo.addWidget(self.botao_marcar)
        topo.addWidget(self.botao_repetidas)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.topo)
        layout.addWidget(self.lista, 1)
        layout.addWidget(self.rodape)

        self._sincronizando = False
        self._preenchendo = False
        self.lista.selectionModel().currentChanged.connect(self._ao_mudar_indice)
        estado.fotos_mudaram.connect(self._ao_mudar_fotos)
        estado.foto_mudou.connect(self.modelo.foto_mudou)
        estado.atual_mudou.connect(self._ao_mudar_atual)
        estado.pastas_mudaram.connect(self._ao_mudar_pastas)
        estado.pedido_mudou.connect(self._atualizar_tamanhos)
        estado.fotos_mudaram.connect(self._atualizar_tamanhos)
        self._atualizar_tamanhos()
        self._ligar_na_tela()

    # ------------------------------------------------------------ consulta
    def total(self) -> int:
        return self.modelo.rowCount()

    def fotos_visiveis(self) -> list[Foto]:
        return [self.modelo.foto(i) for i in range(self.modelo.rowCount())]

    def fotos_escolhidas(self) -> list[Foto]:
        """Fotos destacadas na grade (seleção da lista, não a marca de revelação)."""
        fotos = [self.modelo.foto(i.row()) for i in self.lista.selectionModel().selectedIndexes()]
        return [f for f in fotos if f is not None]

    def largura_minima(self) -> int:
        """Menor largura que mantém duas colunas no tamanho atual."""
        return largura_duas_colunas(self.lado)

    # ------------------------------------------------------------ ações
    def definir_miniatura(self, lado: int) -> None:
        """Muda o lado das miniaturas (limitado), relê o layout, lembra a escolha e avisa a janela."""
        lado = limitar_miniatura(lado)
        if lado == self.lado:
            return
        self.lado = lado
        self.delegado.lado = lado
        self.lista.setGridSize(celula(lado))
        self.lista.doItemsLayout()
        atual = self.lista.currentIndex()
        if atual.isValid():
            self.lista.scrollTo(atual)
        self.lista.viewport().update()
        prefs.settings().setValue(CHAVE_PREF, lado)
        self.controle.definir_valor(lado)
        self.tamanho_mudou.emit(lado)

    def ajustar_miniatura(self, passo: int) -> None:
        self.definir_miniatura(self.lado + passo)

    def definir_filtro(self, so_selecionadas: bool) -> None:
        self.modelo.so_selecionadas = so_selecionadas
        self._ao_mudar_fotos()

    def definir_tamanho(self, tamanho_id: str | None) -> None:
        """Mostra só as fotos marcadas com uma impressão em ``tamanho_id`` (None: todos os tamanhos)."""
        if tamanho_id == self.modelo.tamanho:
            return
        self.modelo.tamanho = tamanho_id
        self._ao_mudar_fotos()
        self._atualizar_tamanhos()

    def _ao_escolher_tamanho(self, _i: int) -> None:
        if not self._preenchendo:
            self.definir_tamanho(self.combo_tamanho.currentData())

    def _atualizar_tamanhos(self) -> None:
        """Opções do filtro: "Todos os tamanhos" e os tamanhos em uso no trabalho, com o número de fotos de cada."""
        contagem: dict[str, int] = {}
        for foto in self.estado.trabalho.fotos:
            if foto.selecionada:
                for t in {i.tamanho for i in foto.impressoes}:
                    contagem[t] = contagem.get(t, 0) + 1
        ordem = [t.id for t in tamanhos.TAMANHOS] + [tamanhos.PERSONALIZADO]
        filtro = self.modelo.tamanho
        if filtro is not None and filtro != SEM_PASTA and filtro not in contagem:
            contagem[filtro] = 0
        self._preenchendo = True
        try:
            self.combo_tamanho.clear()
            self.combo_tamanho.addItem(_("Todos os tamanhos"), None)
            for t in sorted(contagem, key=lambda t: ordem.index(t) if t in ordem else len(ordem)):
                nome = _("Personalizado") if t == tamanhos.PERSONALIZADO else nome_tamanho(t)
                self.combo_tamanho.addItem(_("{tamanho} ({n})").format(tamanho=nome, n=contagem[t]), t)
            sem = sum(1 for f in self.estado.trabalho.fotos if not any(i.pasta for i in f.impressoes))
            self.combo_tamanho.addItem(_("Sem pasta ({n})").format(n=sem), SEM_PASTA)
            self.combo_tamanho.setCurrentIndex(max(0, self.combo_tamanho.findData(filtro)) if filtro else 0)
        finally:
            self._preenchendo = False

    @property
    def pasta_filtrada(self) -> str | None:
        return self.modelo.pasta

    def definir_pasta(self, pasta_id: str | None) -> None:
        """Mostra só as fotos da pasta de tamanho ``pasta_id`` (None: sem filtro de pasta). Combina com o filtro
        Todas | Selecionadas: com os dois, só as fotos marcadas da pasta."""
        if pasta_id is not None and self.estado.pasta_por_id(pasta_id) is None:
            pasta_id = None
        if pasta_id == self.modelo.pasta:
            return
        self.modelo.pasta = pasta_id
        self._ao_mudar_fotos()

    def pixmap_arrasto(self, fotos: list[Foto]) -> QPixmap:
        """Imagem que acompanha o mouse ao arrastar: a miniatura da primeira foto e, com várias, o número delas."""
        pm = QPixmap(LADO_ARRASTO + 12, LADO_ARRASTO + 12)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        quadro = QRect(0, 8, LADO_ARRASTO, LADO_ARRASTO)
        p.setPen(QPen(QColor(tema.BORDA_FORTE), 1))
        p.setBrush(QColor(tema.PAINEL2))
        p.drawRoundedRect(QRectF(quadro).adjusted(0.5, 0.5, -0.5, -0.5), RAIO_MINIATURA, RAIO_MINIATURA)
        miniatura = self.modelo.pixmap(fotos[0]) if fotos else None
        if miniatura is not None:
            alvo = miniatura.size().scaled(quadro.size() - QSize(6, 6), Qt.AspectRatioMode.KeepAspectRatio)
            r = QRect(quadro.center().x() - alvo.width() // 2 + 1, quadro.center().y() - alvo.height() // 2 + 1,
                      alvo.width(), alvo.height())
            recorte = QPainterPath()
            recorte.addRoundedRect(QRectF(r), RAIO_MINIATURA - 3, RAIO_MINIATURA - 3)
            p.setClipPath(recorte)
            p.drawPixmap(r, miniatura)
            p.setClipping(False)
        if len(fotos) > 1:
            texto = str(len(fotos))
            p.setFont(tema.fonte(8.5, QFont.Weight.Bold))
            largura = max(22, p.fontMetrics().horizontalAdvance(texto) + 12)
            bolha = QRect(LADO_ARRASTO + 10 - largura, 0, largura, 22)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(tema.DESTAQUE))
            p.drawRoundedRect(bolha, 11, 11)
            p.setPen(QColor(tema.TEXTO_SOBRE_DESTAQUE))
            p.drawText(bolha, Qt.AlignmentFlag.AlignCenter, texto)
        p.end()
        return pm

    def alternar(self, indice: QModelIndex) -> None:
        foto = self.modelo.foto(indice.row())
        if foto is not None:
            self.estado.selecionar(foto, not foto.selecionada)

    def clicar_chip(self, indice: QModelIndex, n: int, zona: int = 0) -> None:
        """Clique no chip "− 10x15 ×2 +": o "+" soma uma cópia à impressão n, o "−" tira uma (de 1 a 999) e o texto
        só escolhe a foto e a impressão (a que o editor mostra)."""
        foto = self.modelo.foto(indice.row())
        if foto is None or not 0 <= n < len(foto.impressoes):
            return
        self.lista.setCurrentIndex(indice)   # a foto clicada vira a atual (e a impressão, a do editor)
        self.estado.definir_impressao(n)
        imp = foto.impressoes[n]
        copias = max(1, min(999, imp.copias + zona))
        if copias != imp.copias:
            imp.copias = copias
            self.estado.alterar(foto, pedido=True)

    def alternar_atual(self) -> None:
        escolhidas = self.fotos_escolhidas() or ([self.estado.atual] if self.estado.atual else [])
        if not escolhidas:
            return
        self.marcar_fotos(escolhidas, not escolhidas[0].selecionada)

    def remover_selecionados(self) -> None:
        self.remover_fotos(self.fotos_escolhidas())

    def remover_fotos(self, fotos: list[Foto]) -> None:
        """Tira as fotos do trabalho (nunca do disco) e escolhe a vizinha. Desfazer as põe de volta."""
        if not fotos:
            return
        proxima = self._vizinha(fotos)
        self.estado.remover(fotos)
        if proxima is not None:
            self.estado.definir_atual(proxima)

    # ------------------------------------------------------------ várias fotos de uma vez (menu de contexto)
    def menu_contexto(self, fotos: list[Foto]) -> QMenu:
        """Menu de contexto para ``fotos`` (as escolhidas), sem abrir: quem chama faz ``exec``/``popup``.

        Itens (``objectName`` entre parênteses, para testes e para quem acrescentar itens): "Marcar para revelação"
        (``marcar``), "Desmarcar" (``desmarcar``), "Tamanho ▸" (``tamanho``; ações com o id do tamanho),
        "Cópias ▸" (``copias``: ``copias_1``... ``copias_10``, ``copias_mais``, ``copias_menos``), "Procurar…"
        (``procurar``, só se alguma foto falta no disco) e "Remover do trabalho" (``remover``). Submenus novos entram
        depois de "Cópias ▸", antes do separador de "Procurar…"/"Remover".
        """
        menu = QMenu(self)
        menu.setObjectName("menu_grade")
        fotos = list(fotos)
        if not fotos:
            return menu
        n = len(fotos)
        if any(not f.selecionada for f in fotos):
            texto = _("Marcar para revelação") if n == 1 else _("Marcar {n} fotos para revelação").format(n=n)
            self._item(menu, "marcar", texto, lambda: self.marcar_fotos(fotos, True))
        if any(f.selecionada for f in fotos):
            texto = _("Desmarcar") if n == 1 else _("Desmarcar {n} fotos").format(n=n)
            self._item(menu, "desmarcar", texto, lambda: self.marcar_fotos(fotos, False))
        menu.addSeparator()

        marcadas = all(f.selecionada for f in fotos)
        tamanho = menu.addMenu(_("Tamanho"))
        tamanho.menuAction().setObjectName("tamanho")
        avulsos = {i.tamanho for f in fotos for i in f.impressoes if i.pasta is None}
        for grupo in tamanhos.GRUPOS:
            tamanho.addSection(_(NOMES_GRUPOS[grupo]))
            for t in tamanhos.TAMANHOS:
                if t.grupo == grupo:
                    acao = self._item(tamanho, t.id, _(t.nome), lambda _c=False, i=t.id: self.aplicar_tamanho(fotos, i))
                    acao.setCheckable(True)
                    acao.setChecked(marcadas and avulsos == {t.id})
                    acao.setData(t.id)

        copias = menu.addMenu(_("Cópias"))
        copias.menuAction().setObjectName("copias")
        todas = {i.copias for f in fotos for i in f.impressoes}
        for c in COPIAS_MENU:
            texto = _("1 cópia") if c == 1 else _("{n} cópias").format(n=c)
            acao = self._item(copias, f"copias_{c}", texto, lambda _c=False, c=c: self.aplicar_copias(fotos, c))
            acao.setCheckable(True)
            acao.setChecked(marcadas and todas == {c})
            acao.setData(c)
        copias.addSeparator()
        self._item(copias, "copias_mais", _("Uma cópia a mais"), lambda: self.somar_copias(fotos, +1))
        self._item(copias, "copias_menos", _("Uma cópia a menos"), lambda: self.somar_copias(fotos, -1))
        self._menu_pastas(menu, fotos)

        menu.addSeparator()
        texto = _("Duplicar foto (outro recorte)") if n == 1 else _("Duplicar {n} fotos").format(n=n)
        self._item(menu, "duplicar", texto, lambda: self.duplicar(fotos))
        if any(not f.caminho.exists() for f in fotos):
            self._item(menu, "procurar", _("Procurar…"), lambda: self.procurar_pedido.emit())
        texto = _("Remover do trabalho") if n == 1 else _("Remover {n} fotos do trabalho").format(n=n)
        self._item(menu, "remover", texto, lambda: self.remover_fotos(fotos))
        return menu

    def _menu_pastas(self, menu: QMenu, fotos: list[Foto]) -> None:
        """"Adicionar à pasta ▸" (``adicionar_pasta``: ``adicionar:<id>`` por pasta e ``nova_pasta``) e, se alguma das
        fotos está numa pasta, "Tirar da pasta ▸" (``tirar_pasta``: ``tirar:<id>``)."""
        pastas = self.estado.trabalho.pastas
        adicionar = menu.addMenu(_("Adicionar à pasta"))
        adicionar.menuAction().setObjectName("adicionar_pasta")
        for pasta in pastas:
            texto = f"{pasta.nome}  ·  {nome_tamanho(pasta.tamanho, pasta.papel_mm)}"
            acao = self._item(adicionar, f"adicionar:{pasta.id}", texto,
                              lambda _c=False, p=pasta.id: self.adicionar_a_pasta(fotos, p))
            ja_estao = all(f.selecionada and self.estado.impressao_da_pasta(f, pasta) for f in fotos)
            acao.setCheckable(True)
            acao.setChecked(ja_estao)
            acao.setEnabled(not ja_estao)        # nada a fazer: já estão (marcadas) nessa pasta
            acao.setIcon(icones.bolinha(tema.cor_pasta(pasta.cor), 14, anel=ja_estao))
            acao.setData(pasta.id)
        if pastas:
            adicionar.addSeparator()
        acao = self._item(adicionar, "nova_pasta", _("Nova pasta…"), lambda: self.nova_pasta_com(fotos))
        acao.setIcon(icones.icone("mais", tema.APAGADO, 16))
        presentes = [p for p in pastas if any(self.estado.impressao_da_pasta(f, p) for f in fotos)]
        if presentes:
            tirar = menu.addMenu(_("Tirar da pasta"))
            tirar.menuAction().setObjectName("tirar_pasta")
            for pasta in presentes:
                acao = self._item(tirar, f"tirar:{pasta.id}", pasta.nome,
                                  lambda _c=False, p=pasta.id: self.tirar_da_pasta(fotos, p))
                acao.setIcon(icones.bolinha(tema.cor_pasta(pasta.cor), 14))
                acao.setData(pasta.id)

    def adicionar_a_pasta(self, fotos: list[Foto], pasta_id: str) -> list[Foto]:
        """Põe as fotos na pasta de tamanho (marcadas), num passo só do desfazer."""
        pasta = self.estado.pasta_por_id(pasta_id)
        return self.estado.adicionar_a_pasta(list(fotos), pasta) if pasta is not None else []

    def tirar_da_pasta(self, fotos: list[Foto], pasta_id: str) -> list[Foto]:
        """Tira as fotos da pasta de tamanho, num passo só do desfazer."""
        pasta = self.estado.pasta_por_id(pasta_id)
        return self.estado.tirar_da_pasta(list(fotos), pasta) if pasta is not None else []

    def criar_dialogo_nova_pasta(self, fotos: list[Foto]):
        """Diálogo "Nova pasta" que, aceito, cria a pasta e põe nela as fotos (um passo só do desfazer)."""
        return dialogo_nova_pasta(self.estado, self.window(), list(fotos))

    def nova_pasta_com(self, fotos: list[Foto]) -> Pasta | None:
        """"Nova pasta…" do menu de contexto: pede nome, tamanho e cor (modal) e põe as fotos na pasta nova."""
        dialogo = self.criar_dialogo_nova_pasta(fotos)
        dialogo.exec()
        pasta = dialogo.pasta_criada
        dialogo.deleteLater()
        return pasta

    @staticmethod
    def _item(menu: QMenu, nome: str, texto: str, slot) -> QAction:
        acao = menu.addAction(texto)
        acao.setObjectName(nome)
        acao.triggered.connect(slot)
        return acao

    def duplicar(self, fotos: list[Foto]) -> list[Foto]:
        """Uma cópia de cada foto no trabalho (mesmo arquivo), para usar outro recorte; a primeira vira a atual."""
        novas = [self.estado.duplicar(f) for f in fotos]
        if novas:
            self.estado.definir_atual(novas[0])
        return novas

    def marcar_fotos(self, fotos: list[Foto], sim: bool = True) -> None:
        """Marca (ou desmarca) as fotos para revelação, num passo só do desfazer."""
        with self.estado.lote(_("marcação") if sim else _("desmarcação")):
            for foto in fotos:
                self.estado.selecionar(foto, sim)

    def aplicar_tamanho(self, fotos: list[Foto], tamanho_id: str) -> None:
        """Põe as fotos no tamanho ``tamanho_id``, num passo só do desfazer.

        Regra: a foto não marcada é marcada; a **primeira impressão avulsa** (``pasta is None``) troca de tamanho (o
        recorte automático é refeito e o manual, reencaixado, como no painel) — as outras avulsas ficam como estão, para
        uma foto em 10x15 e 20x30 não virar duas cópias do mesmo tamanho; se alguma avulsa já está nesse tamanho, nada
        muda. A foto sem avulsa (só com impressões de pastas) ganha uma nesse tamanho. Impressões de pastas de tamanho
        não mudam (o tamanho delas é o da pasta).
        """
        t = tamanhos.obter(tamanho_id)   # valida (KeyError em id desconhecido); "personalizado" não entra aqui
        with self.estado.lote(_("tamanho {t}").format(t=_(t.nome))):
            for foto in fotos:
                if not foto.selecionada:
                    self.estado.selecionar(foto)
                avulsas = [i for i in foto.impressoes if i.pasta is None]
                if not avulsas:
                    foto.impressoes.append(Impressao(tamanho=tamanho_id))
                    self.estado.refazer_recortes_auto(foto)
                elif all(i.tamanho != tamanho_id for i in avulsas):
                    imp = avulsas[0]
                    imp.tamanho, imp.papel_mm, imp.preco_centavos = tamanho_id, None, None
                    refazer_enquadramento(self.estado, foto, imp)
                self.estado.alterar(foto, pedido=True)

    def aplicar_copias(self, fotos: list[Foto], copias: int) -> None:
        """Todas as impressões das fotos com ``copias`` cópias (1 a 999); marca as não marcadas. Um passo só."""
        copias = max(LIMITE_COPIAS[0], min(LIMITE_COPIAS[1], int(copias)))
        self._mudar_copias(fotos, lambda _atual: copias)

    def somar_copias(self, fotos: list[Foto], delta: int) -> None:
        """Soma ``delta`` às cópias de todas as impressões das fotos (limitado a 1 e 999). Um passo só."""
        self._mudar_copias(fotos, lambda atual: max(LIMITE_COPIAS[0], min(LIMITE_COPIAS[1], atual + delta)))

    def _mudar_copias(self, fotos: list[Foto], nova) -> None:
        with self.estado.lote(_("cópias")):
            for foto in fotos:
                if not foto.selecionada:
                    self.estado.selecionar(foto)
                for imp in foto.impressoes:
                    imp.copias = nova(imp.copias)
                self.estado.alterar(foto, pedido=True)

    def _vizinha(self, removidas: list[Foto]) -> Foto | None:
        ids = {f.id for f in removidas}
        visiveis = self.fotos_visiveis()
        ultimo = max((i for i, f in enumerate(visiveis) if f.id in ids), default=-1)
        for f in visiveis[ultimo + 1:] + visiveis[:ultimo][::-1]:
            if f.id not in ids:
                return f
        return None

    # ------------------------------------------------------------ reações
    def _ao_mudar_fotos(self) -> None:
        self._sincronizando = True
        try:
            self.modelo.recarregar()
            self._marcar_atual(self.estado.atual)
        finally:
            self._sincronizando = False

    def _marcar_atual(self, foto: Foto | None) -> None:
        indice = self.modelo.indice_da_foto(foto)
        sm = self.lista.selectionModel()
        if indice.isValid():
            sm.setCurrentIndex(indice, sm.SelectionFlag.ClearAndSelect)
            self.lista.scrollTo(indice)
        else:
            sm.clear()

    def _ao_mudar_pastas(self) -> None:
        """Pastas mudaram (cor, nome, apagada, desfeita, outro trabalho): a pasta filtrada que sumiu solta o filtro, a
        lista filtrada é conferida e os chips são redesenhados com as cores novas."""
        if self.modelo.pasta is not None:
            if self.estado.pasta_por_id(self.modelo.pasta) is None:
                self.modelo.pasta = None
                self._ao_mudar_fotos()
            elif [f.id for f in self.modelo._visiveis()] != [f.id for f in self.fotos_visiveis()]:
                self._ao_mudar_fotos()
        self.lista.viewport().update()

    def _ao_mudar_atual(self, foto) -> None:
        if self._sincronizando:
            return
        self._sincronizando = True
        try:
            self._marcar_atual(foto)
        finally:
            self._sincronizando = False

    def _ao_mudar_indice(self, atual: QModelIndex, _anterior: QModelIndex) -> None:
        if self._sincronizando or not atual.isValid():
            return
        self._sincronizando = True
        try:
            self.estado.definir_atual(self.modelo.foto(atual.row()))
        finally:
            self._sincronizando = False

    # ---- rostos (#36): publica no Estado as fotos que aparecem no viewport (a fila de rostos as adianta)
    def _ligar_na_tela(self) -> None:
        self._timer_na_tela = QTimer(self)
        self._timer_na_tela.setSingleShot(True)
        self._timer_na_tela.setInterval(ATRASO_NA_TELA_MS)
        self._timer_na_tela.timeout.connect(self.publicar_na_tela)
        barra = self.lista.verticalScrollBar()
        barra.valueChanged.connect(lambda *_: self._timer_na_tela.start())    # rolar
        barra.rangeChanged.connect(lambda *_: self._timer_na_tela.start())    # redimensionar, miniatura, filtro
        self.modelo.modelReset.connect(lambda: self._timer_na_tela.start())

    def ids_na_tela(self) -> list[str]:
        """Ids das fotos cujo cartão aparece (mesmo em parte) no viewport, na ordem da grade."""
        area = self.lista.viewport().rect()
        ids: list[str] = []
        for linha in range(self.modelo.rowCount()):
            r = self.lista.visualRect(self.modelo.index(linha))
            if r.top() > area.bottom():
                break                      # modo ícone: as linhas seguem de cima para baixo
            foto = self.modelo.foto(linha)
            if foto is not None and r.intersects(area):
                ids.append(foto.id)
        return ids

    def publicar_na_tela(self) -> None:
        self.estado.definir_na_tela(self.ids_na_tela())
