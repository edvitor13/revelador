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
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QApplication, QFileDialog, QHBoxLayout, QLabel, QMainWindow, QMenu, QMessageBox,
                               QPushButton, QScrollArea, QSplitter, QToolButton, QVBoxLayout, QWidget)

from .. import APP_NAME, __version__, imagem, precos
from ..i18n import _
from . import icones, prefs, tema
from .componentes import BarraAdaptavel, Pilula, Segmented, botao_plano, com_menu
from .estado import Estado
from .grade import Grade, largura_duas_colunas, tamanho_miniatura_salvo
from .painel_impressoes import PainelImpressoes, SeletorTamanhoPadrao, tamanho_padrao_salvo
from .precos_dialog import PrecosDialog, tabela_precos
from .resumo import ResumoDialog, texto_barra
from .tarefas import Importacao

TAMANHO_INICIAL = (1280, 800)
PROPORCAO_INICIAL = [380, 580, 320]   # para a janela inicial de 1280 px
LARGURA_MINIMA = (400, 300)   # editor, painel; a grade tem o mínimo de duas colunas (ver _largura_minima_grade)
MARGEM_PAINEL = 14
ATRASO_ATUALIZACAO_MS = 2000  # a verificação ao abrir começa depois que a janela aparece


def _largura_minima_grade() -> int:
    """Menor largura da grade: duas colunas no tamanho de miniatura salvo (antes de a grade existir)."""
    return largura_duas_colunas(tamanho_miniatura_salvo())


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
        self._ligar_desfazer()
        self._ligar_menu_grade()
        self._ligar_autosalvar()
        self._ligar_boas_vindas()
        self._ligar_pastas()

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
        self.acao_desfazer = QAction(_("Desfazer"), self)                     # #5 (QUndoStack do Estado)
        self.acao_desfazer.setShortcut(QKeySequence.StandardKey.Undo)
        self.acao_refazer = QAction(_("Refazer"), self)                       # #5
        self.acao_refazer.setShortcuts([QKeySequence("Ctrl+Y"), QKeySequence("Ctrl+Shift+Z")])
        self.acao_configuracoes = QAction(_("Configurações…"), self)          # #34 (e outras preferências)
        self.acao_boas_vindas = QAction(_("Tela de boas-vindas"), self)       # #35
        for acao in (self.acao_novo, self.acao_abrir, self.acao_salvar, self.acao_salvar_como,
                     self.acao_verificar_atualizacoes, self.acao_desfazer, self.acao_refazer,
                     self.acao_configuracoes, self.acao_boas_vindas):
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
            self.acao_salvar, self.acao_salvar_como, self.acao_verificar_atualizacoes, self.acao_desfazer,
            self.acao_refazer, self.acao_sair,
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
                       self.acao_salvar_como, None, self.acao_desfazer, self.acao_refazer))
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
            botao_plano("configuracoes", _("Preços, resumo, configurações, atualizações e sobre")),
            self._menu(self.acao_precos, self.acao_resumo, None, self.acao_configuracoes, self.acao_boas_vindas,
                       None, self.acao_verificar_atualizacoes, self.acao_sobre))
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
        self.area_grade.setMinimumWidth(_largura_minima_grade())
        for area, minimo in zip((self.area_editor, self.area_painel), LARGURA_MINIMA):
            area.setMinimumWidth(minimo)
        for area in (self.area_grade, self.area_editor, self.area_painel):
            self.divisor.addWidget(area)
        self._atualizar_minimo_divisor()
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
        self.grade.tamanho_mudou.connect(self._ajustar_largura_grade)
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
        """"Importar pasta…": escolhe a pasta do disco e mostra o passo curto (criar ou não a pasta de tamanho, #32)."""
        s = prefs.settings()
        inicio = str(s.value("importar/ultima_pasta", "", str))
        pasta = QFileDialog.getExistingDirectory(self, _("Importar pasta"), inicio)
        if pasta:
            s.setValue("importar/ultima_pasta", pasta)
            passo = self.criar_passo_importar_pasta(Path(pasta))
            passo.exec()
            passo.deleteLater()

    def criar_passo_importar_pasta(self, pasta: Path):
        """Passo "Importar pasta" (``pastas.PassoImportarPasta``) já ligado: aceitar importa a pasta e, com "Criar pasta
        de tamanho" marcado, põe as fotos dela numa pasta de tamanho nova; cancelar não importa nada. Quem chama faz
        ``exec()`` (ou ``accept()`` num teste)."""
        from .pastas import PassoImportarPasta

        pasta = Path(pasta)
        caminhos = imagem.listar_fotos([pasta])
        dialogo = PassoImportarPasta(self.estado, pasta, len(caminhos), self)
        dialogo.accepted.connect(
            lambda: self.importar_pasta(pasta, dialogo.valores() if dialogo.criar() else None, caminhos))
        return dialogo

    def importar_pasta(self, pasta: Path, pasta_tamanho: dict | None = None,
                       caminhos: list[Path] | None = None) -> list:
        """Importa a pasta do disco (como ``importar``) e devolve as fotos novas.

        Com ``pasta_tamanho`` (os argumentos de ``Estado.criar_pasta``: nome, tamanho, cor...), cria essa pasta de
        tamanho e põe nela, marcadas para revelação, todas as fotos daquela pasta do disco (inclusive as que já
        estavam no trabalho). Criar a pasta e marcar as fotos é UM passo do desfazer (a importação em si não entra no
        desfazer). Sem nenhuma foto na pasta do disco, nenhuma pasta de tamanho é criada.
        """
        from .pastas import fotos_dos_caminhos

        if pasta_tamanho is None:
            return self.importar([pasta])
        caminhos = imagem.listar_fotos([pasta]) if caminhos is None else caminhos
        nome = pasta_tamanho.get("nome") or Path(pasta).name
        with self.estado.lote(_("importação da pasta “{nome}”").format(nome=nome)):
            novas = self.importar([pasta])
            fotos = fotos_dos_caminhos(self.estado, caminhos)
            if fotos:
                criada = self.estado.criar_pasta(**pasta_tamanho)
                self.estado.adicionar_a_pasta(fotos, criada)
                self.statusBar().showMessage(_("{fotos} na pasta “{nome}”, marcadas para revelação.").format(
                    fotos=_("1 foto") if len(fotos) == 1 else _("{n} fotos").format(n=len(fotos)), nome=criada.nome))
        return novas

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
        """Fotos e pastas soltas são importadas; o primeiro ``.revelador`` solto abre o trabalho (como na linha de
        comando: abre primeiro, as fotos entram depois no trabalho aberto; se a pessoa cancelar, nada entra).

        O trabalho é tratado depois do soltar (``QTimer``): a pergunta "Salvar/Descartar" não prende o Explorer."""
        from ..app import separar_argumentos

        caminhos = [u.toLocalFile() for u in evento.mimeData().urls() if u.isLocalFile()]
        if not caminhos:
            return
        trabalhos, resto = separar_argumentos(caminhos)
        evento.acceptProposedAction()
        if not trabalhos:
            self.importar(resto)
            return

        def abrir_e_importar() -> None:
            if self.projeto_ui.abrir(Path(trabalhos[0])) and resto:
                self.importar(resto)

        QTimer.singleShot(0, abrir_e_importar)

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

    # ------------------------------------------------------------ desfazer/refazer (#5)
    def _ligar_desfazer(self) -> None:
        """Ctrl+Z / Ctrl+Y pela pilha do ``Estado``: habilitadas por ``canUndo``/``canRedo``, texto "Desfazer {o quê}".

        Os gestos do editor (arrastar no visor, slider de endireitar) começam ao apertar e terminam ao soltar o mouse:
        tudo no meio vira um passo só.
        """
        from .desfazer import ligar_gestos

        pilha = self.estado.pilha
        self.acao_desfazer.triggered.connect(self.estado.desfazer)
        self.acao_refazer.triggered.connect(self.estado.refazer)
        pilha.canUndoChanged.connect(self.acao_desfazer.setEnabled)
        pilha.canRedoChanged.connect(self.acao_refazer.setEnabled)
        pilha.undoTextChanged.connect(self._texto_desfazer)
        pilha.redoTextChanged.connect(self._texto_refazer)
        self.acao_desfazer.setEnabled(pilha.canUndo())
        self.acao_refazer.setEnabled(pilha.canRedo())
        self._texto_desfazer(pilha.undoText())
        self._texto_refazer(pilha.redoText())
        self._filtro_gesto = ligar_gestos(self.estado, self.editor.tela, self.editor.slider_angulo.trilho)
        self.editor.slider_angulo.soltou.connect(self.estado.fim_gesto)

    def _texto_desfazer(self, texto: str) -> None:
        self.acao_desfazer.setText(_("Desfazer {acao}").format(acao=texto) if texto else _("Desfazer"))

    def _texto_refazer(self, texto: str) -> None:
        self.acao_refazer.setText(_("Refazer {acao}").format(acao=texto) if texto else _("Refazer"))

    # ------------------------------------------------------------ menu de contexto da grade (#5, #9)
    def _ligar_menu_grade(self) -> None:
        """O "Procurar…" do menu de contexto da grade usa a mesma busca da faixa de fotos não encontradas."""
        self.grade.procurar_pedido.connect(lambda: self.projeto_ui.procurar_faltando())

    # ------------------------------------------------------------ salvamento automático e configurações (#34)
    def _ligar_autosalvar(self) -> None:
        """Salvamento automático (``ui/autosalvar.py``), o indicador na barra de status e "Configurações…".

        Para dar ao trabalho novo o nome da primeira pasta importada, ``importar`` passa a avisar o ``AutoSalvar``
        antes de importar (a importação em si não muda).
        """
        from .autosalvar import AutoSalvar

        self.autosalvar = AutoSalvar(self, self.estado, self.projeto_ui, self.faixas)
        self.projeto_ui.autosalvar = self.autosalvar
        self.statusBar().addPermanentWidget(self.autosalvar.indicador)
        importar_original = self.importar

        def importar(caminhos) -> list:
            self.autosalvar.notar_importacao(caminhos)
            return importar_original(caminhos)

        self.importar = importar
        self.acao_configuracoes.triggered.connect(lambda _c=False: self.abrir_configuracoes())
        self.acao_configuracoes.setEnabled(True)

    def criar_dialogo_configuracoes(self):
        """Diálogo de Configurações já ligado: ao salvar, o salvamento automático relê as preferências."""
        from .configuracoes import ConfiguracoesDialog

        dialogo = ConfiguracoesDialog(self)
        dialogo.aplicado.connect(self.autosalvar.aplicar_preferencias)
        return dialogo

    def abrir_configuracoes(self) -> None:
        self.criar_dialogo_configuracoes().exec()

    # ------------------------------------------------------------ tela de boas-vindas (#35)
    def _ligar_boas_vindas(self) -> None:
        """Tela de boas-vindas (``ui/boas_vindas.py``): engrenagem → "Tela de boas-vindas" (``acao_boas_vindas``).

        Ao abrir o app, ``app.main`` chama ``boas_vindas.ao_abrir()`` depois de tratar a linha de comando (a tela só
        aparece sem arquivos nela). Precisa de ``projeto_ui``, ``faixas``, ``verificador`` e ``divisor``.
        """
        from .boas_vindas import BoasVindas

        self.boas_vindas = BoasVindas(self)

    # ------------------------------------------------------------ pastas de tamanho (#32)
    def _ligar_pastas(self) -> None:
        """Seção "Pastas" (``ui/pastas.py``) no topo da grade, acima da lista (aparece e some com ela).

        Clicar numa pasta filtra a grade (``Grade.definir_pasta``), junto com "Mostrar: Todas | Selecionadas": a grade
        mostra as fotos que passam nos dois (pasta "Natal" + Selecionadas = as fotos marcadas da pasta "Natal").
        "Importar pasta…" mostra o passo de criar a pasta de tamanho (``escolher_pasta``); arrastar uma pasta do
        Explorer para a janela continua só importando.
        """
        from .pastas import SecaoPastas

        self.secao_pastas = SecaoPastas(self.estado)
        self.grade.layout().insertWidget(0, self.secao_pastas)
        self.secao_pastas.filtro_mudou.connect(self.grade.definir_pasta)

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
        self._corrigir_largura_grade()

    def _ajustar_largura_grade(self, _lado: int) -> None:
        """Quando o tamanho das miniaturas muda, a grade acompanha o novo mínimo de duas colunas."""
        self.area_grade.setMinimumWidth(self.grade.largura_minima())
        self._atualizar_minimo_divisor()
        self._corrigir_largura_grade()

    def _atualizar_minimo_divisor(self) -> None:
        """A soma dos mínimos das três áreas vira o mínimo do divisor, e a janela cresce para caber."""
        areas = (self.area_grade, self.area_editor, self.area_painel)
        self.divisor.setMinimumWidth(sum(a.minimumWidth() for a in areas) + 2 * self.divisor.handleWidth())

    def _corrigir_largura_grade(self) -> None:
        """Grade com pelo menos duas colunas: uma largura salva menor (ex.: da primeira versão) é ignorada.

        A grade cresce até o mínimo e o editor cede o que falta (sem passar do próprio mínimo).
        """
        tamanhos = self.divisor.sizes()
        if len(tamanhos) != 3:
            return
        falta = self.area_grade.minimumWidth() - tamanhos[0]
        if falta <= 0:
            return
        tamanhos[0] += falta
        tamanhos[1] = max(tamanhos[1] - falta, self.area_editor.minimumWidth())
        self.divisor.setSizes(tamanhos)

    def closeEvent(self, evento) -> None:  # noqa: N802 - nome do Qt
        # Chega aqui só se o fechamento foi aceito (``ProjetoUi`` já salvou ou perguntou).
        self.salvar_estado()
        self.autosalvar.encerrar()   # para o temporizador e espera uma gravação em curso
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
