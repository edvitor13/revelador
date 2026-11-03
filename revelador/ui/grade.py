"""Grade de miniaturas: ``QListView`` em modo ícone com modelo próprio (aguenta ~1000 fotos).

Fala só com o ``Estado``: lê ``trabalho.fotos``, ``miniaturas`` e ``erros`` e reage a ``fotos_mudaram`` e
``foto_mudou``. Clique escolhe a foto atual; Espaço ou clique na marca liga/desliga a seleção para revelação;
Delete tira do trabalho (nunca do disco, sem confirmação); setas navegam. A miniatura é lida do cache em disco
sob demanda, só das células visíveis, com um cache pequeno de ``QPixmap``.
"""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import QAbstractListModel, QModelIndex, QPoint, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QListView, QStyle, QStyledItemDelegate, QStyleOptionViewItem,
                               QVBoxLayout, QWidget)

from .. import tamanhos
from ..i18n import _
from ..projeto import Foto
from . import icones, tema
from .estado import Estado

CELULA = QSize(170, 214)
MARGEM_CARTAO = 4       # entre a célula e o cartão
MARGEM_MINIATURA = 6    # entre o cartão e a miniatura
RAIO_CARTAO = 12
RAIO_MINIATURA = 8
TAMANHO_MARCA = 24
ALTURA_CHIP = 18
LIMITE_PIXMAPS = 400
PAPEL_FOTO = Qt.ItemDataRole.UserRole


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
    """Retângulo da marca de seleção (canto superior esquerdo da miniatura)."""
    miniatura = rect_miniatura(celula)
    return QRect(miniatura.left() + 8, miniatura.top() + 8, TAMANHO_MARCA, TAMANHO_MARCA)


class ModeloGrade(QAbstractListModel):
    """Fotos visíveis (todas ou só as selecionadas), na ordem de importação."""

    def __init__(self, estado: Estado, parent=None) -> None:
        super().__init__(parent)
        self.estado = estado
        self.so_selecionadas = False
        self._fotos: list[Foto] = []
        self._linha: dict[str, int] = {}
        self._pixmaps: OrderedDict[str, QPixmap] = OrderedDict()
        self.recarregar()

    def _visiveis(self) -> list[Foto]:
        fotos = self.estado.trabalho.fotos
        return [f for f in fotos if f.selecionada] if self.so_selecionadas else list(fotos)

    def recarregar(self) -> None:
        self.beginResetModel()
        self._fotos = self._visiveis()
        self._linha = {f.id: i for i, f in enumerate(self._fotos)}
        self._pixmaps.clear()
        self.endResetModel()

    def foto_mudou(self, foto_id: str) -> None:
        if self.so_selecionadas:
            novas = [f.id for f in self._visiveis()]
            if novas != [f.id for f in self._fotos]:
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

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        return CELULA

    def paint(self, p: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        foto: Foto | None = index.data(PAPEL_FOTO)
        if foto is None:
            return
        estados = option.state
        atual = bool(estados & QStyle.StateFlag.State_Selected)
        sobre = bool(estados & QStyle.StateFlag.State_MouseOver)
        cartao = option.rect.adjusted(MARGEM_CARTAO, MARGEM_CARTAO, -MARGEM_CARTAO, -MARGEM_CARTAO)
        miniatura = rect_miniatura(option.rect)
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

        # nome do arquivo (apagado, cortado com "…")
        p.setFont(tema.fonte(8.5))
        p.setPen(QColor(tema.TEXTO if atual else tema.APAGADO))
        nome_r = QRect(miniatura.left() + 2, miniatura.bottom() + 8, miniatura.width() - 4, 16)
        p.drawText(nome_r, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   p.fontMetrics().elidedText(foto.caminho.name, Qt.TextElideMode.ElideRight, nome_r.width()))
        self._chips(p, QRect(miniatura.left() + 2, nome_r.bottom() + 5, miniatura.width() - 4, ALTURA_CHIP), foto)
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

    def _chips(self, p: QPainter, area: QRect, foto: Foto) -> None:
        """Um chip em pílula por impressão ("10x15 ×2"); o que não couber vira "+N"."""
        if not foto.impressoes:
            return
        fonte = tema.fonte(8, QFont.Weight.DemiBold)
        medidas = QFontMetrics(fonte)
        p.setFont(fonte)
        x = area.left()
        textos = [rotulo_impressao(i.tamanho, i.copias) for i in foto.impressoes]
        for n, texto in enumerate(textos):
            largura = medidas.horizontalAdvance(texto) + 16
            resto = len(textos) - n - 1
            reserva = medidas.horizontalAdvance(f"+{resto}") + 16 + 4 if resto else 0
            if x + largura + reserva > area.right() + 1 and n > 0:
                self._pilula(p, QRect(x, area.top(), medidas.horizontalAdvance(f"+{len(textos) - n}") + 16,
                                      ALTURA_CHIP), f"+{len(textos) - n}", apagado=True)
                return
            self._pilula(p, QRect(x, area.top(), min(largura, area.right() - x + 1), ALTURA_CHIP),
                         medidas.elidedText(texto, Qt.TextElideMode.ElideRight, area.right() - x - 14))
            x += largura + 4

    @staticmethod
    def _pilula(p: QPainter, r: QRect, texto: str, apagado: bool = False) -> None:
        fundo = QColor(tema.PAINEL3) if apagado else QColor(tema.DESTAQUE)
        if not apagado:
            fundo.setAlpha(46)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(fundo)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        p.setPen(QColor(tema.APAGADO if apagado else tema.DESTAQUE_HI))
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, texto)


class _Lista(QListView):
    def __init__(self, grade: "Grade") -> None:
        super().__init__()
        self.grade = grade

    def mousePressEvent(self, evento) -> None:  # noqa: N802
        indice = self.indexAt(evento.position().toPoint())
        if indice.isValid() and evento.button() == Qt.MouseButton.LeftButton:
            if rect_marca(self.visualRect(indice)).contains(evento.position().toPoint()):
                self.grade.alternar(indice)
                self.setCurrentIndex(indice)
                return
        super().mousePressEvent(evento)

    def keyPressEvent(self, evento) -> None:  # noqa: N802
        if evento.key() == Qt.Key.Key_Space:
            self.grade.alternar_atual()
        elif evento.key() == Qt.Key.Key_Delete:
            self.grade.remover_selecionados()
        else:
            super().keyPressEvent(evento)


class Grade(QWidget):
    """A grade de miniaturas ligada ao ``Estado``."""

    def __init__(self, estado: Estado, parent=None) -> None:
        super().__init__(parent)
        self.estado = estado
        self.modelo = ModeloGrade(estado, self)
        self.lista = _Lista(self)
        self.lista.setObjectName("lista_grade")
        self.lista.setModel(self.modelo)
        self.lista.setItemDelegate(DelegadoGrade(self.modelo, self.lista))
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
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.lista)

        self._sincronizando = False
        self.lista.selectionModel().currentChanged.connect(self._ao_mudar_indice)
        estado.fotos_mudaram.connect(self._ao_mudar_fotos)
        estado.foto_mudou.connect(self.modelo.foto_mudou)
        estado.atual_mudou.connect(self._ao_mudar_atual)

    # ------------------------------------------------------------ consulta
    def total(self) -> int:
        return self.modelo.rowCount()

    def fotos_visiveis(self) -> list[Foto]:
        return [self.modelo.foto(i) for i in range(self.modelo.rowCount())]

    def fotos_escolhidas(self) -> list[Foto]:
        """Fotos destacadas na grade (seleção da lista, não a marca de revelação)."""
        fotos = [self.modelo.foto(i.row()) for i in self.lista.selectionModel().selectedIndexes()]
        return [f for f in fotos if f is not None]

    # ------------------------------------------------------------ ações
    def definir_filtro(self, so_selecionadas: bool) -> None:
        self.modelo.so_selecionadas = so_selecionadas
        self._ao_mudar_fotos()

    def alternar(self, indice: QModelIndex) -> None:
        foto = self.modelo.foto(indice.row())
        if foto is not None:
            self.estado.selecionar(foto, not foto.selecionada)

    def alternar_atual(self) -> None:
        escolhidas = self.fotos_escolhidas() or ([self.estado.atual] if self.estado.atual else [])
        if not escolhidas:
            return
        sim = not escolhidas[0].selecionada
        for foto in escolhidas:
            self.estado.selecionar(foto, sim)

    def remover_selecionados(self) -> None:
        escolhidas = self.fotos_escolhidas()
        if not escolhidas:
            return
        proxima = self._vizinha(escolhidas)
        self.estado.remover(escolhidas)
        if proxima is not None:
            self.estado.definir_atual(proxima)

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
