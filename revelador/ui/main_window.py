"""Janela principal: barra de ferramentas, três áreas (grade, editor, painel lateral) e barra de status.

As áreas começam vazias, só com um texto de orientação; as próximas issues encaixam os widgets de verdade nos
layouts ``area_grade.layout()``, ``area_editor.layout()`` e ``area_painel.layout()`` (e escondem o texto de
orientação correspondente, ``orientacao_grade`` etc.). Geometria da janela e das divisórias ficam em ``prefs``.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QPalette
from PySide6.QtWidgets import (QApplication, QComboBox, QFileDialog, QLabel, QMainWindow, QMenu, QMessageBox,
                               QPushButton, QScrollArea, QSplitter, QToolBar, QVBoxLayout, QWidget)

from .. import APP_NAME, __version__, imagem, precos
from ..i18n import _
from . import prefs
from .estado import Estado
from .grade import Grade
from .painel_impressoes import PainelImpressoes, SeletorTamanhoPadrao, tamanho_padrao_salvo
from .precos_dialog import PrecosDialog, tabela_precos
from .resumo import ResumoDialog, texto_barra
from .tarefas import Importacao

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
        self._ligar_grade()
        self._ligar_selecao()
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
        # Contrato: ações criadas aqui, desligadas; cada issue só as conecta e liga no seu _ligar_<parte>() e a barra
        # superior (visual) só as posiciona. Ninguém mais cria menu próprio para elas.
        self.acao_novo = QAction(_("Novo trabalho"), self)                    # #9
        self.acao_novo.setShortcut("Ctrl+N")
        self.acao_abrir = QAction(_("Abrir trabalho…"), self)                 # #9
        self.acao_abrir.setShortcut("Ctrl+O")
        self.acao_salvar = QAction(_("Salvar"), self)                         # #9
        self.acao_salvar.setShortcut("Ctrl+S")
        self.acao_salvar_como = QAction(_("Salvar como…"), self)              # #9
        self.acao_salvar_como.setShortcut("Ctrl+Shift+S")
        self.menu_recentes = QMenu(_("Abrir recente"), self)                  # #9 (preenchido por ela)
        self.acao_verificar_atualizacoes = QAction(_("Verificar atualizações…"), self)  # #10
        for acao in (self.acao_novo, self.acao_abrir, self.acao_salvar, self.acao_salvar_como,
                     self.acao_verificar_atualizacoes):
            acao.setEnabled(False)
        self.menu_recentes.setEnabled(False)

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
        for acao in (self.acao_novo, self.acao_abrir):
            arquivo.addAction(acao)
        arquivo.addMenu(self.menu_recentes)
        for acao in (self.acao_salvar, self.acao_salvar_como):
            arquivo.addAction(acao)
        arquivo.addSeparator()
        arquivo.addAction(self.acao_importar)
        arquivo.addAction(self.acao_exportar)
        arquivo.addSeparator()
        arquivo.addAction(self.acao_sair)
        ajuda = self.menuBar().addMenu(_("A&juda"))
        ajuda.addAction(self.acao_verificar_atualizacoes)
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

    # ------------------------------------------------------------ importação e grade (#2, #4)
    def _ligar_grade(self) -> None:
        """Grade de miniaturas, importação (botão, arrastar e soltar, linha de comando) e filtro "Mostrar"."""
        self.grade = Grade(self.estado)
        self.area_grade.layout().addWidget(self.grade)
        self.importacao = Importacao(self.estado, self)
        self.importacao.mensagem.connect(self.statusBar().showMessage)
        self.estado.fotos_mudaram.connect(self._atualizar_orientacao_grade)

        self.acao_importar_pasta = QAction(_("Importar pasta…"), self)
        self.acao_importar_pasta.setShortcut("Ctrl+Shift+I")
        self.acao_importar.triggered.connect(self.escolher_arquivos)
        self.acao_importar_pasta.triggered.connect(self.escolher_pasta)
        self.barra.insertAction(self.acao_exportar, self.acao_importar_pasta)
        self.menu_arquivo.insertAction(self.acao_exportar, self.acao_importar_pasta)

        self.filtro_mostrar = QComboBox()
        self.filtro_mostrar.setObjectName("filtro_mostrar")
        self.filtro_mostrar.addItem(_("Todas"), False)
        self.filtro_mostrar.addItem(_("Selecionadas"), True)
        self.filtro_mostrar.currentIndexChanged.connect(
            lambda _i: self.grade.definir_filtro(bool(self.filtro_mostrar.currentData())))
        self.barra.addSeparator()
        self.barra.addWidget(QLabel(_("Mostrar:") + " "))
        self.barra.addWidget(self.filtro_mostrar)

    def _atualizar_orientacao_grade(self) -> None:
        self.orientacao_grade.setVisible(not self.estado.trabalho.fotos)

    def importar(self, caminhos) -> list:
        """Importa arquivos e pastas (recursivo, só formatos aceitos); devolve as fotos novas."""
        return self.estado.adicionar(imagem.listar_fotos(caminhos))

    def escolher_arquivos(self) -> None:
        s = prefs.settings()
        formatos = " ".join(f"*{e}" for e in sorted(imagem.FORMATOS))
        nomes, _filtro = QFileDialog.getOpenFileNames(
            self, _("Importar fotos"), str(s.value("importar/ultima_pasta", "", str)),
            _("Fotos") + f" ({formatos})")
        if nomes:
            s.setValue("importar/ultima_pasta", str(Path(nomes[0]).parent))
            self.importar(nomes)

    def escolher_pasta(self) -> None:
        s = prefs.settings()
        inicio = str(s.value("importar/ultima_pasta", "", str))
        pasta = QFileDialog.getExistingDirectory(self, _("Importar pasta"), inicio)
        if pasta:
            s.setValue("importar/ultima_pasta", pasta)
            self.importar([pasta])

    def showEvent(self, evento) -> None:  # noqa: N802 - nome do Qt
        super().showEvent(evento)
        if self.arquivos_iniciais:
            QTimer.singleShot(0, self._importar_iniciais)

    def _importar_iniciais(self) -> None:
        iniciais, self.arquivos_iniciais = self.arquivos_iniciais, []
        self.importar(iniciais)

    def dragEnterEvent(self, evento) -> None:  # noqa: N802 - nome do Qt
        if evento.mimeData().hasUrls():
            evento.acceptProposedAction()

    def dropEvent(self, evento) -> None:  # noqa: N802 - nome do Qt
        caminhos = [u.toLocalFile() for u in evento.mimeData().urls() if u.isLocalFile()]
        if caminhos:
            self.importar(caminhos)
            evento.acceptProposedAction()

    # ------------------------------------------------------------ seleção, tamanhos e custo (#5, #13)
    def _ligar_selecao(self) -> None:
        """Painel de impressões, tamanho padrão, menu/ação de preços e o custo na barra de status.

        O painel lateral é uma coluna rolável (``coluna_painel``): a seção de impressões fica no topo e há um
        espaçador no fim; quem acrescentar seções insere antes dele (``insertWidget(count() - 1, ...)``).
        """
        padrao = tamanho_padrao_salvo()
        if padrao:
            self.estado.trabalho.tamanho_padrao = padrao
        self.orientacao_painel.hide()
        rolagem = QScrollArea()
        rolagem.setWidgetResizable(True)
        rolagem.setFrameShape(QScrollArea.Shape.NoFrame)
        conteudo = QWidget()
        self.coluna_painel = QVBoxLayout(conteudo)
        self.coluna_painel.setContentsMargins(0, 0, 0, 0)
        self.painel_impressoes = PainelImpressoes(self.estado)
        self.coluna_painel.addWidget(self.painel_impressoes)
        self.coluna_painel.addStretch(1)
        rolagem.setWidget(conteudo)
        self.rolagem_painel = rolagem
        self.area_painel.layout().addWidget(rolagem)

        self.seletor_tamanho = SeletorTamanhoPadrao(self.estado)
        self.espaco_tamanho.layout().addWidget(self.seletor_tamanho)

        self.acao_precos = QAction(_("Preços do laboratório…"), self)
        self.acao_precos.triggered.connect(self.abrir_precos)
        self.acao_resumo = QAction(_("Resumo do pedido…"), self)
        self.acao_resumo.triggered.connect(self.abrir_resumo)
        self.menu_pedido = QMenu(_("&Pedido"), self)
        self.menu_pedido.addAction(self.acao_resumo)
        self.menu_pedido.addAction(self.acao_precos)
        self.menuBar().insertMenu(self.menu_ajuda.menuAction(), self.menu_pedido)
        self.barra.addAction(self.acao_precos)

        self.botao_custo = QPushButton()
        self.botao_custo.setFlat(True)
        self.botao_custo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.botao_custo.setToolTip(_("Estimativa — clique para ver o resumo do pedido"))
        self.botao_custo.clicked.connect(self.abrir_resumo)
        self.statusBar().addPermanentWidget(self.botao_custo)
        self.resumo: ResumoDialog | None = None
        self.estado.pedido_mudou.connect(self.atualizar_custo)
        self.atualizar_custo()

    def atualizar_custo(self) -> None:
        orc = precos.orcamento(self.estado.trabalho, tabela_precos())
        self.botao_custo.setText(texto_barra(self.estado.trabalho, orc))

    def abrir_resumo(self) -> None:
        if self.resumo is None:
            self.resumo = ResumoDialog(self.estado, self)
        self.resumo.atualizar()
        self.resumo.show()
        self.resumo.raise_()

    def abrir_precos(self) -> None:
        PrecosDialog(self.estado, self).exec()

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
