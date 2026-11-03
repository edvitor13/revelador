"""Janela principal: barra superior, três áreas (grade, editor, painel lateral) e barra de status.

A barra superior (``BarraAdaptavel``) substitui menus e barra de ferramentas: logo, Importar, Projeto, "Mostrar"
(todas | selecionadas), tamanho padrão, o custo do pedido, Exportar e a engrenagem. As ações ficam todas em
``self.acao_*`` (com atalhos valendo na janela inteira) e a barra só as posiciona; quem implementa uma ação só a conecta.
As áreas começam vazias, só com um texto de orientação; os widgets de verdade entram nos layouts
``area_grade.layout()``, ``area_editor.layout()`` e ``area_painel.layout()``. O painel lateral é uma coluna rolável
(``coluna_painel``): cada seção é um ``Card`` inserido antes do espaçador final. Geometria e divisórias ficam em ``prefs``.
"""

from __future__ import annotations

import os

from pathlib import Path

from PySide6.QtCore import QByteArray, QSize, Qt, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QApplication, QFileDialog, QHBoxLayout, QLabel, QMainWindow, QMenu, QMessageBox,
                               QPushButton, QScrollArea, QSplitter, QToolButton, QVBoxLayout, QWidget)

from .. import APP_NAME, __version__, imagem, precos
from ..i18n import _
from . import icones, prefs, tema
from .componentes import BarraAdaptavel, Pilula, Segmented, botao_plano, com_menu
from .estado import Estado
from .grade import Grade
from .painel_impressoes import PainelImpressoes, SeletorTamanhoPadrao, tamanho_padrao_salvo
from .precos_dialog import PrecosDialog, tabela_precos
from .resumo import ResumoDialog, texto_barra
from .tarefas import Importacao

TAMANHO_INICIAL = (1280, 800)
PROPORCAO_INICIAL = [380, 580, 320]   # para a janela inicial de 1280 px
LARGURA_MINIMA = (200, 400, 300)   # grade, editor, painel
MARGEM_PAINEL = 14
ATRASO_ATUALIZACAO_MS = 2000  # a verificação ao abrir começa depois que a janela aparece


def _area(nome: str, texto: str, estilo: str | None = None) -> tuple[QWidget, QLabel]:
    """Área vazia: um widget com layout vertical e o texto de orientação centralizado. `estilo`: nome de objeto do tema."""
    widget = QWidget()
    widget.setObjectName(estilo or nome)
    widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    orientacao = QLabel(texto)
    orientacao.setObjectName("Muted")
    orientacao.setAlignment(Qt.AlignmentFlag.AlignCenter)
    orientacao.setWordWrap(True)
    layout.addWidget(orientacao)
    return widget, orientacao


class MainWindow(QMainWindow):
    """Janela principal do Revelador."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.arquivos_iniciais: list[str] = []
        self.estado = Estado(self)   # trabalho aberto e foto atual; os widgets conversam por ele
        padrao = tamanho_padrao_salvo()
        if padrao:
            self.estado.trabalho.tamanho_padrao = padrao

        self._criar_acoes()
        self._criar_barra_superior()
        self._criar_areas()
        self.statusBar().setSizeGripEnabled(False)
        self.statusBar().showMessage(_("Pronto."))
        self.restaurar_estado()
        self._ligar_grade()
        self._ligar_selecao()
        self._ligar_editor()
        self._ligar_exportacao()
        self._ligar_atualizacao()
        self._ligar_ajustes()
        self._ligar_projeto()

    # ------------------------------------------------------------ montagem
    def _criar_acoes(self) -> None:
        self.acao_importar = QAction(_("Importar…"), self)
        self.acao_importar.setShortcut("Ctrl+I")
        self.acao_importar_pasta = QAction(_("Importar pasta…"), self)
        self.acao_importar_pasta.setShortcut("Ctrl+Shift+I")
        self.acao_exportar = QAction(_("Exportar para revelação…"), self)
        self.acao_exportar.setShortcut("Ctrl+E")
        self.acao_exportar.setEnabled(False)  # liga quando houver fotos para exportar
        self.acao_sair = QAction(_("Sair"), self)
        self.acao_sair.setShortcut("Ctrl+Q")
        self.acao_sair.triggered.connect(self.close)
        self.acao_sobre = QAction(_("Sobre o {app}").format(app=APP_NAME), self)
        self.acao_sobre.triggered.connect(self.mostrar_sobre)
        # Contrato: ações criadas aqui, desligadas; cada issue só as conecta e liga no seu _ligar_<parte>() e a barra
        # superior só as posiciona. Ninguém mais cria menu próprio para elas.
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
        self.acao_precos = QAction(_("Preços do laboratório…"), self)
        self.acao_precos.triggered.connect(self.abrir_precos)
        self.acao_resumo = QAction(_("Resumo do pedido…"), self)
        self.acao_resumo.triggered.connect(self.abrir_resumo)
        self.acao_importar.setIcon(icones.icone("foto", tema.TEXTO, 16))
        self.acao_importar_pasta.setIcon(icones.icone("pasta", tema.TEXTO, 16))
        # Sem barra de menus, os atalhos precisam estar na própria janela.
        self.acoes_da_janela = [
            self.acao_importar, self.acao_importar_pasta, self.acao_exportar, self.acao_novo, self.acao_abrir,
            self.acao_salvar, self.acao_salvar_como, self.acao_verificar_atualizacoes, self.acao_sair,
        ]
        for acao in self.acoes_da_janela:
            self.addAction(acao)

    def _menu(self, *itens) -> QMenu:
        """Menu da barra superior. Itens: QAction, QMenu (submenu) ou None (separador)."""
        menu = QMenu(self)
        for item in itens:
            if item is None:
                menu.addSeparator()
            elif isinstance(item, QMenu):
                menu.addMenu(item)
            else:
                menu.addAction(item)
        return menu

    def _criar_barra_superior(self) -> None:
        """Barra superior: logo e nome, Importar, Projeto, Mostrar, tamanho padrão, custo, Exportar e engrenagem."""
        barra = BarraAdaptavel("TopBar")
        lay = QHBoxLayout(barra)
        lay.setContentsMargins(16, 9, 14, 9)
        lay.setSpacing(8)
        logo = QLabel()
        logo.setPixmap(icones.icone_app().pixmap(QSize(30, 30)))
        nome = QLabel(APP_NAME)
        nome.setObjectName("AppName")
        lay.addWidget(logo)
        lay.addWidget(nome)
        lay.addSpacing(16)

        self.botao_importar = com_menu(
            botao_plano("importar", _("Importar fotos ou uma pasta (Ctrl+I)"), _("Importar")),
            self._menu(self.acao_importar, self.acao_importar_pasta))
        self.botao_projeto = com_menu(
            botao_plano("salvar", _("Novo, abrir e salvar o trabalho"), _("Projeto")),
            self._menu(self.acao_novo, self.acao_abrir, self.menu_recentes, None, self.acao_salvar,
                       self.acao_salvar_como))
        lay.addWidget(self.botao_importar)
        lay.addWidget(self.botao_projeto)
        lay.addSpacing(10)

        self.filtro_mostrar = Segmented([("todas", _("Todas"), _("Mostrar todas as fotos")),
                                         ("selecionadas", _("Selecionadas"),
                                          _("Mostrar só as fotos marcadas para revelar"))])
        self.filtro_mostrar.definir_atual("todas")
        self.rotulo_mostrar = QLabel(_("Mostrar"))
        self.rotulo_mostrar.setObjectName("Muted")
        lay.addWidget(self.rotulo_mostrar)
        lay.addWidget(self.filtro_mostrar)
        lay.addSpacing(10)

        self.seletor_tamanho = SeletorTamanhoPadrao(self.estado)
        lay.addWidget(self.seletor_tamanho)
        lay.addStretch(1)

        self.botao_custo = Pilula()
        self.botao_custo.setIcon(icones.icone("dinheiro", tema.APAGADO, 16))
        self.botao_custo.setIconSize(QSize(16, 16))
        self.botao_custo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.botao_custo.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.botao_custo.setToolTip(_("Estimativa — clique para ver o resumo do pedido"))
        self.botao_custo.clicked.connect(self.abrir_resumo)
        lay.addWidget(self.botao_custo)

        self.botao_exportar = QToolButton()
        self.botao_exportar.setObjectName("Primary")
        self.botao_exportar.setIcon(icones.icone("exportar", tema.TEXTO_SOBRE_DESTAQUE, 18))
        self.botao_exportar.setIconSize(QSize(18, 18))
        self.botao_exportar.setText(_("Exportar para revelação"))
        self.botao_exportar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.botao_exportar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.botao_exportar.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.botao_exportar.clicked.connect(self.acao_exportar.trigger)
        self.acao_exportar.changed.connect(self._sincronizar_exportar)
        self._sincronizar_exportar()
        lay.addWidget(self.botao_exportar)

        self.botao_menu = com_menu(
            botao_plano("configuracoes", _("Preços, resumo, atualizações e sobre")),
            self._menu(self.acao_precos, self.acao_resumo, None, self.acao_verificar_atualizacoes, self.acao_sobre))
        self.botao_menu.setProperty("menu", False)   # só o ícone, sem a setinha
        lay.addWidget(self.botao_menu)

        barra.definir_adaptacao(
            rotulos=[self.rotulo_mostrar, self.seletor_tamanho.rotulo],
            compactos=[self.botao_importar, self.botao_projeto, self.botao_exportar],
            opcionais=[nome])
        self.barra_superior = barra

    def _sincronizar_exportar(self) -> None:
        acao = self.acao_exportar
        self.botao_exportar.setEnabled(acao.isEnabled())
        self.botao_exportar.setToolTip(f"{acao.text().rstrip('…')} ({acao.shortcut().toString()})")

    def _criar_areas(self) -> None:
        self.area_grade, self.orientacao_grade = _area("area_grade", _("Arraste fotos ou pastas para cá"))
        self.area_editor, self.orientacao_editor = _area(
            "area_editor", _("Escolha uma foto na grade para enquadrar"), "Canvas")
        self.area_painel, self.orientacao_painel = _area(
            "area_painel", _("Os tamanhos e ajustes da foto escolhida aparecem aqui"), "Panel")
        self.divisor = QSplitter(Qt.Orientation.Horizontal)
        for area, minimo in zip((self.area_grade, self.area_editor, self.area_painel), LARGURA_MINIMA):
            area.setMinimumWidth(minimo)
            self.divisor.addWidget(area)
        self.divisor.setChildrenCollapsible(False)
        self.divisor.setHandleWidth(4)
        self.divisor.setStretchFactor(0, 1)    # a grade e o editor dividem o que sobra ou falta; o painel é fixo
        self.divisor.setStretchFactor(1, 3)
        self.divisor.setStretchFactor(2, 0)
        self.divisor.setSizes(PROPORCAO_INICIAL)
        central = QWidget()
        coluna = QVBoxLayout(central)
        coluna.setContentsMargins(0, 0, 0, 0)
        coluna.setSpacing(0)
        coluna.addWidget(self.barra_superior)
        coluna.addWidget(self.divisor, 1)
        self.setCentralWidget(central)
        self.setAcceptDrops(True)

    # ------------------------------------------------------------ importação e grade (#2, #4)
    def _ligar_grade(self) -> None:
        """Grade de miniaturas, importação (botão, arrastar e soltar, linha de comando) e filtro "Mostrar"."""
        self.grade = Grade(self.estado)
        self.importacao = Importacao(self.estado, self)
        self.importacao.mensagem.connect(self.statusBar().showMessage)
        # Estado vazio: ícone, orientação e um botão; some quando entra a primeira foto.
        self.vazio_grade = QWidget()
        vazio = QVBoxLayout(self.vazio_grade)
        vazio.setContentsMargins(24, 24, 24, 24)
        vazio.setSpacing(12)
        vazio.addStretch(1)
        icone = QLabel()
        icone.setPixmap(icones.icone("foto", tema.FRACO, 44).pixmap(QSize(44, 44)))
        icone.setAlignment(Qt.AlignmentFlag.AlignCenter)
        vazio.addWidget(icone)
        self.area_grade.layout().removeWidget(self.orientacao_grade)
        vazio.addWidget(self.orientacao_grade)
        botao = QPushButton("  " + _("Importar fotos"))
        botao.setObjectName("Primary")
        botao.setIcon(icones.icone("importar", tema.TEXTO_SOBRE_DESTAQUE, 16))
        botao.setCursor(Qt.CursorShape.PointingHandCursor)
        botao.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        botao.clicked.connect(self.acao_importar.trigger)
        vazio.addWidget(botao, 0, Qt.AlignmentFlag.AlignHCenter)
        vazio.addStretch(1)
        self.area_grade.layout().addWidget(self.vazio_grade)
        self.area_grade.layout().addWidget(self.grade)
        self.estado.fotos_mudaram.connect(self._atualizar_orientacao_grade)
        self._atualizar_orientacao_grade()

        self.acao_importar.triggered.connect(self.escolher_arquivos)
        self.acao_importar_pasta.triggered.connect(self.escolher_pasta)
        self.filtro_mostrar.mudou.connect(lambda chave: self.grade.definir_filtro(chave == "selecionadas"))

    def _atualizar_orientacao_grade(self) -> None:
        tem_fotos = bool(self.estado.trabalho.fotos)
        self.vazio_grade.setVisible(not tem_fotos)
        self.grade.setVisible(tem_fotos)

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
        """Painel de impressões, preços e o custo do pedido na barra superior.

        O painel lateral é uma coluna rolável (``coluna_painel``): a seção de impressões fica no topo e há um
        espaçador no fim; quem acrescentar seções (``Card``) insere antes dele (``insertWidget(count() - 1, ...)``).
        """
        self.orientacao_painel.hide()
        rolagem = QScrollArea()
        rolagem.setWidgetResizable(True)
        rolagem.setFrameShape(QScrollArea.Shape.NoFrame)
        rolagem.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        conteudo = QWidget()
        conteudo.setObjectName("Panel")
        self.coluna_painel = QVBoxLayout(conteudo)
        self.coluna_painel.setContentsMargins(MARGEM_PAINEL, MARGEM_PAINEL, MARGEM_PAINEL, MARGEM_PAINEL)
        self.coluna_painel.setSpacing(12)
        self.painel_impressoes = PainelImpressoes(self.estado)
        self.coluna_painel.addWidget(self.painel_impressoes)
        self.coluna_painel.addStretch(1)
        rolagem.setWidget(conteudo)
        self.rolagem_painel = rolagem
        self.area_painel.layout().addWidget(rolagem)

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

    # ------------------------------------------------------------ exportação
    def _ligar_exportacao(self) -> None:
        """Liga ``acao_exportar``: habilitada quando há pelo menos uma foto selecionada com impressão."""
        self.acao_exportar.triggered.connect(self.abrir_exportacao)
        self.estado.pedido_mudou.connect(self.atualizar_acao_exportar)
        self.atualizar_acao_exportar()

    def atualizar_acao_exportar(self) -> None:
        self.acao_exportar.setEnabled(any(f.impressoes for f in self.estado.trabalho.selecionadas()))

    def criar_dialogo_exportacao(self):
        from .exportar_dialog import ExportarDialog   # importação tardia: puxa a receita (numpy/cv2)
        return ExportarDialog(self.estado, self)

    def abrir_exportacao(self) -> None:
        self.criar_dialogo_exportacao().exec()

    # ------------------------------------------------------------ atualização (#10)
    def _ligar_atualizacao(self) -> None:
        """Verificação ao abrir (em segundo plano, no máximo uma vez por dia) e "Verificar atualizações…" (Ajuda)."""
        from .atualizacao import Verificador

        self.verificador = Verificador(self)
        self.acao_verificar_atualizacoes.setEnabled(True)
        self.acao_verificar_atualizacoes.triggered.connect(self.verificador.verificar_manual)
        if not os.environ.get("REVELADOR_SEM_REDE"):   # testes e capturas de tela: nenhuma consulta à rede
            QTimer.singleShot(ATRASO_ATUALIZACAO_MS, self.verificador.verificar_ao_abrir)

    # ------------------------------------------------------------ ajustes de luz e cor (#7)
    def _ligar_ajustes(self) -> None:
        """Cartões Luz, Cor e Detalhe na coluna do painel lateral, abaixo das impressões, antes do espaçador."""
        from .painel_ajustes import PainelAjustes

        self.painel_ajustes = PainelAjustes(self.estado, self.grade.fotos_escolhidas)
        self.coluna_painel.insertWidget(self.coluna_painel.count() - 1, self.painel_ajustes)

    # ------------------------------------------------------------ salvar e abrir o trabalho (#9)
    def _ligar_projeto(self) -> None:
        """Novo/Abrir/Salvar, recentes, título, recuperação e fotos não encontradas (``ui/projeto_ui.py``).

        As faixas de aviso (não modais) ficam entre a barra superior e as três áreas.
        """
        from .projeto_ui import PilhaFaixas, ProjetoUi

        self.faixas = PilhaFaixas()
        self.centralWidget().layout().insertWidget(1, self.faixas)   # logo abaixo da barra superior
        self.projeto_ui = ProjetoUi(self, self.estado, self.importacao, self.faixas)
        self.projeto_ui.oferecer_recuperacao()

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
