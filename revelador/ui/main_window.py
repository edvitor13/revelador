"""Janela principal: barra de ferramentas, três áreas (grade, editor, painel lateral) e barra de status.

As áreas começam vazias, só com um texto de orientação; as próximas issues encaixam os widgets de verdade nos
layouts ``area_grade.layout()``, ``area_editor.layout()`` e ``area_painel.layout()`` (e escondem o texto de
orientação correspondente, ``orientacao_grade`` etc.). Geometria da janela e das divisórias ficam em ``prefs``.
"""

from __future__ import annotations

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QAction, QColor, QPalette
from PySide6.QtWidgets import (QApplication, QLabel, QMainWindow, QMessageBox, QSplitter, QToolBar, QVBoxLayout,
                               QWidget)

from .. import APP_NAME, __version__
from ..i18n import _
from . import prefs
from .estado import Estado

CINZA_EDITOR = "#6b6b6b"  # cinza neutro: um fundo colorido enganaria a percepção de cor da foto
TAMANHO_INICIAL = (1280, 800)
PROPORCAO_INICIAL = [260, 700, 300]


def aplicar_tema(app: QApplication) -> None:
    """Estilo Fusion com a paleta do sistema, que segue o claro/escuro do Windows (inclusive ao vivo)."""
    app.setStyle("Fusion")

    def atualizar(*_args) -> None:
        app.setPalette(app.style().standardPalette())

    atualizar()
    try:
        app.styleHints().colorSchemeChanged.connect(atualizar)
    except AttributeError:  # Qt antigo, sem o sinal
        pass


def _area(nome: str, texto: str, fundo: str | None = None) -> tuple[QWidget, QLabel]:
    """Área vazia: um widget com layout vertical e o texto de orientação centralizado."""
    widget = QWidget()
    widget.setObjectName(nome)
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(6, 6, 6, 6)
    orientacao = QLabel(texto)
    orientacao.setAlignment(Qt.AlignmentFlag.AlignCenter)
    orientacao.setWordWrap(True)
    orientacao.setEnabled(False)
    layout.addWidget(orientacao)
    if fundo:
        paleta = widget.palette()
        paleta.setColor(QPalette.ColorRole.Window, QColor(fundo))
        paleta.setColor(QPalette.ColorRole.WindowText, QColor("#e6e6e6"))
        paleta.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor("#c8c8c8"))
        widget.setPalette(paleta)
        widget.setAutoFillBackground(True)
    return widget, orientacao


class MainWindow(QMainWindow):
    """Janela principal do Revelador."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.arquivos_iniciais: list[str] = []
        self.estado = Estado(self)   # trabalho aberto e foto atual; os widgets conversam por ele

        self._criar_acoes()
        self._criar_barra_de_ferramentas()
        self._criar_menus()
        self._criar_areas()
        self.statusBar().showMessage(_("Pronto."))
        self.restaurar_estado()
        self._ligar_editor()

    # ------------------------------------------------------------ montagem
    def _criar_acoes(self) -> None:
        self.acao_importar = QAction(_("Importar…"), self)
        self.acao_importar.setShortcut("Ctrl+I")
        self.acao_exportar = QAction(_("Exportar para revelação…"), self)
        self.acao_exportar.setShortcut("Ctrl+E")
        self.acao_exportar.setEnabled(False)  # liga quando houver fotos para exportar
        self.acao_sair = QAction(_("Sair"), self)
        self.acao_sair.setShortcut("Ctrl+Q")
        self.acao_sair.triggered.connect(self.close)
        self.acao_sobre = QAction(_("Sobre o {app}").format(app=APP_NAME), self)
        self.acao_sobre.triggered.connect(self.mostrar_sobre)

    def _criar_barra_de_ferramentas(self) -> None:
        barra = QToolBar(_("Ferramentas"), self)
        barra.setObjectName("barra_ferramentas")
        barra.setMovable(False)
        barra.addAction(self.acao_importar)
        barra.addAction(self.acao_exportar)
        barra.addSeparator()
        # Lugar do seletor de tamanho padrão (outra issue coloca o widget aqui).
        self.espaco_tamanho = QWidget()
        self.espaco_tamanho.setLayout(QVBoxLayout())
        self.espaco_tamanho.layout().setContentsMargins(0, 0, 0, 0)
        barra.addWidget(self.espaco_tamanho)
        self.barra = barra
        self.addToolBar(barra)

    def _criar_menus(self) -> None:
        arquivo = self.menuBar().addMenu(_("&Arquivo"))
        arquivo.addAction(self.acao_importar)
        arquivo.addAction(self.acao_exportar)
        arquivo.addSeparator()
        arquivo.addAction(self.acao_sair)
        ajuda = self.menuBar().addMenu(_("A&juda"))
        ajuda.addAction(self.acao_sobre)
        self.menu_arquivo, self.menu_ajuda = arquivo, ajuda

    def _criar_areas(self) -> None:
        self.area_grade, self.orientacao_grade = _area("area_grade", _("Arraste fotos ou pastas para cá"))
        self.area_editor, self.orientacao_editor = _area(
            "area_editor", _("Escolha uma foto na grade para enquadrar"), CINZA_EDITOR)
        self.area_painel, self.orientacao_painel = _area(
            "area_painel", _("Os tamanhos e ajustes da foto escolhida aparecem aqui"))
        self.divisor = QSplitter(Qt.Orientation.Horizontal)
        for area in (self.area_grade, self.area_editor, self.area_painel):
            self.divisor.addWidget(area)
        self.divisor.setChildrenCollapsible(False)
        self.divisor.setStretchFactor(0, 0)
        self.divisor.setStretchFactor(1, 1)
        self.divisor.setStretchFactor(2, 0)
        self.divisor.setSizes(PROPORCAO_INICIAL)
        self.setCentralWidget(self.divisor)
        self.setAcceptDrops(True)

    # ------------------------------------------------------------ editor
    def _ligar_editor(self) -> None:
        """Encaixa o editor de enquadramento na área central (esconde o texto de orientação)."""
        from .editor import Editor   # importação tardia: o editor puxa a receita (numpy/cv2), que a janela não precisa antes

        self.editor = Editor(self.estado, self.area_editor)
        self.area_editor.layout().addWidget(self.editor)
        self.orientacao_editor.hide()
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.editor.encerrar)

    # ------------------------------------------------------------ preferências
    def salvar_estado(self) -> None:
        s = prefs.settings()
        s.setValue("janela/geometria", self.saveGeometry())
        s.setValue("janela/divisores", self.divisor.saveState())
        s.sync()

    def restaurar_estado(self) -> None:
        s = prefs.settings()
        geometria = s.value("janela/geometria")
        if isinstance(geometria, QByteArray) and self.restoreGeometry(geometria):
            pass
        else:
            self.resize(*TAMANHO_INICIAL)
        divisores = s.value("janela/divisores")
        if isinstance(divisores, QByteArray):
            self.divisor.restoreState(divisores)

    def closeEvent(self, evento) -> None:  # noqa: N802 - nome do Qt
        self.salvar_estado()
        super().closeEvent(evento)

    # ------------------------------------------------------------ Ajuda
    def texto_sobre(self) -> str:
        return (
            "<h3>{app} {versao}</h3>"
            "<p>{descricao}</p>"
            "<p><b>{lic_t}</b> {lic}</p>"
            "<p><b>{mod_t}</b> {mod}</p>"
            "<p><b>{priv_t}</b> {priv}</p>"
        ).format(
            app=APP_NAME, versao=__version__,
            descricao=_("Prepara suas fotos para revelação no tamanho certo do papel."),
            lic_t=_("Licença:"), lic=_("MIT. Software livre."),
            mod_t=_("Detecção de rostos:"),
            mod=_("modelo YuNet (licença MIT), do OpenCV Zoo."),
            priv_t=_("Privacidade:"),
            priv=_("nenhuma foto sai do seu computador. O tratamento das fotos é todo feito aqui."))

    def mostrar_sobre(self) -> None:
        QMessageBox.about(self, _("Sobre o {app}").format(app=APP_NAME), self.texto_sobre())
