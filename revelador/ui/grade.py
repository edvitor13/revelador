"""Grade de miniaturas: ``QListView`` em modo ícone com modelo próprio (aguenta ~1000 fotos).

Fala só com o ``Estado``: lê ``trabalho.fotos``, ``miniaturas`` e ``erros`` e reage a ``fotos_mudaram`` e
``foto_mudou``. Clique escolhe a foto atual; Espaço ou clique na marca liga/desliga a seleção para revelação;
Delete tira do trabalho (nunca do disco, sem confirmação); setas navegam. A miniatura é lida do cache em disco
sob demanda, só das células visíveis, com um cache pequeno de ``QPixmap``.
"""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import QAbstractListModel, QModelIndex, QPoint, QRect, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QListView, QStyle, QStyledItemDelegate, QStyleOptionViewItem,
                               QVBoxLayout, QWidget)

from .. import tamanhos
from ..i18n import _
from ..projeto import Foto
from .estado import Estado

CELULA = QSize(168, 176)
LADO_MINIATURA_VISTA = 152
TAMANHO_MARCA = 22
LIMITE_PIXMAPS = 400
PAPEL_FOTO = Qt.ItemDataRole.UserRole


def rotulo_impressao(tamanho: str, copias: int) -> str:
    """Texto do chip de uma impressão: ``10x15 ×2``."""
    try:
        nome = _(tamanhos.obter(tamanho).nome)
    except KeyError:
        nome = _("Personalizado")
    return f"{nome} ×{copias}"


def rect_marca(celula: QRect) -> QRect:
    """Retângulo da marca de seleção (canto superior esquerdo da célula)."""
    return QRect(celula.left() + 8, celula.top() + 8, TAMANHO_MARCA, TAMANHO_MARCA)


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
    def __init__(self, modelo: ModeloGrade, parent=None) -> None:
        super().__init__(parent)
        self.modelo = modelo

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        return CELULA

    def paint(self, p: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        foto: Foto | None = index.data(PAPEL_FOTO)
        if foto is None:
            return
        paleta = option.palette
        r = option.rect.adjusted(3, 3, -3, -3)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        estados = option.state
        if estados & QStyle.StateFlag.State_Selected:
            p.fillRect(r, paleta.highlight())
        elif estados & QStyle.StateFlag.State_MouseOver:
            cor = QColor(paleta.highlight().color())
            cor.setAlpha(60)
            p.fillRect(r, cor)

        area = QRect(r.left() + 4, r.top() + 4, r.width() - 8, LADO_MINIATURA_VISTA - 24)
        erro = foto.id in self.modelo.estado.erros
        pm = self.modelo.pixmap(foto)
        if pm is not None and not erro:
            alvo = pm.size().scaled(area.size(), Qt.AspectRatioMode.KeepAspectRatio)
            alvo_r = QRect(QPoint(area.center().x() - alvo.width() // 2, area.center().y() - alvo.height() // 2),
                           alvo)
            p.drawPixmap(alvo_r, pm)
        else:
            p.fillRect(area, QColor(128, 128, 128, 50))
            p.setPen(paleta.windowText().color())
            p.drawText(area, Qt.AlignmentFlag.AlignCenter, "⚠" if erro else "…")
        if erro:
            p.setPen(QColor("#d9822b"))
            p.drawText(area.adjusted(0, 0, -4, -2), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom,
                       "⚠ " + _("Não abriu"))

        # marca de seleção
        marca = rect_marca(option.rect)
        p.setPen(QColor("#ffffff"))
        p.setBrush(QColor("#2d7ff9") if foto.selecionada else QColor(0, 0, 0, 120))
        p.drawEllipse(marca)
        if foto.selecionada:
            p.drawText(marca, Qt.AlignmentFlag.AlignCenter, "✓")

        # nome e chips das impressões
        texto_cor = paleta.highlightedText().color() if estados & QStyle.StateFlag.State_Selected \
            else paleta.text().color()
        p.setPen(texto_cor)
        nome_r = QRect(r.left() + 4, r.top() + LADO_MINIATURA_VISTA - 18, r.width() - 8, 16)
        p.drawText(nome_r, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   p.fontMetrics().elidedText(foto.caminho.name, Qt.TextElideMode.ElideMiddle, nome_r.width()))
        chips = "  ".join(rotulo_impressao(i.tamanho, i.copias) for i in foto.impressoes)
        if chips:
            chip_r = QRect(r.left() + 4, r.top() + LADO_MINIATURA_VISTA, r.width() - 8, 16)
            p.setPen(texto_cor)
            p.drawText(chip_r, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       p.fontMetrics().elidedText(chips, Qt.TextElideMode.ElideRight, chip_r.width()))
        p.restore()


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
        self.lista.setSpacing(2)
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
