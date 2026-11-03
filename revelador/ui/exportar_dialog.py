"""Diálogo "Exportar para revelação" (docs/ARQUITETURA.md, seção 8).

Escolhe a pasta de destino (lembrada nas preferências), o modo das cópias e o dpi, mostra o resumo (fotos, cópias,
custo estimado), os avisos de conferência e a estrutura que será criada. A exportação roda num ``QThreadPool``
próprio (até 4 em paralelo); o progresso e o fim chegam por sinal na thread principal.

Testável sem diálogo modal: ``definir_destino()``, ``iniciar()`` (devolve False se não puder), ``aguardar()``,
``cancelar()``; o resultado fica em ``resultado``.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QCoreApplication, QObject, QRunnable, Qt, QThread, QThreadPool, QTimer, Signal
from PySide6.QtWidgets import (QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QProgressBar, QPushButton, QSpinBox, QVBoxLayout, QWidget)

from .. import exportar, precos, system
from ..i18n import N_, _
from . import prefs
from .estado import Estado
from .precos_dialog import tabela_precos

MODOS_TEXTO = {
    exportar.MODO_PASTAS: N_("Pastas por quantidade (1 cópia, 2 cópias...)"),
    exportar.MODO_NOME: N_("Quantidade no nome do arquivo"),
    exportar.MODO_REPETIR: N_("Repetir o arquivo, uma vez por cópia"),
}
CHAVE_PASTA = "exportar/pasta"
CHAVE_MODO = "exportar/copias"
CHAVE_DPI = "exportar/dpi"
LINHAS_ESTRUTURA = 8


class _Sinais(QObject):
    item_pronto = Signal(int, object, str)    # índice, arquivos gravados (lista), mensagem de erro ("" = ok)


class _TarefaItem(QRunnable):
    def __init__(self, indice: int, item: exportar.Item, dpi: int, sinais: _Sinais, exportacao: Exportacao) -> None:
        super().__init__()
        self.indice, self.item, self.dpi, self.sinais, self.exportacao = indice, item, dpi, sinais, exportacao
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            gravados = exportar.exportar_item(self.item, self.dpi, self.exportacao.foi_cancelada)
            self.sinais.item_pronto.emit(self.indice, gravados, "")
        except Exception as e:  # noqa: BLE001 - um item ruim não derruba os outros
            self.sinais.item_pronto.emit(self.indice, [], exportar.mensagem_erro(self.item, e))


class Exportacao(QObject):
    """Executa um ``Plano`` num ``QThreadPool`` e avisa o progresso e o fim (na thread principal)."""

    progresso = Signal(int, int)
    terminou = Signal(object)    # exportar.Resultado

    def __init__(self, plano: exportar.Plano, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.plano = plano
        self.resultado = exportar.Resultado()
        self.concluida = False
        self._cancelado = False
        self._feitos = 0
        self._sinais = _Sinais(self)
        self._sinais.item_pronto.connect(self._ao_terminar_item)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(exportar.trabalhadores_padrao())

    def foi_cancelada(self) -> bool:
        return self._cancelado

    def iniciar(self) -> None:
        exportar.preparar(self.plano)
        if not self.plano.itens:
            QTimer.singleShot(0, self._concluir)
            return
        for i, item in enumerate(self.plano.itens):
            self._pool.start(_TarefaItem(i, item, self.plano.dpi, self._sinais, self))

    def cancelar(self) -> None:
        self._cancelado = True

    def _ao_terminar_item(self, indice: int, gravados: list, erro: str) -> None:
        item = self.plano.itens[indice]
        if erro:
            self.resultado.erros.append((item, erro))
        elif gravados:
            self.resultado.feitos.append(item)
            self.resultado.arquivos.extend(gravados)
        self._feitos += 1
        self.progresso.emit(self._feitos, len(self.plano.itens))
        if self._feitos >= len(self.plano.itens):
            self._concluir()

    def _concluir(self) -> None:
        if self.concluida:
            return
        self.concluida = True
        self.resultado.cancelado = self._cancelado
        try:
            exportar.finalizar(self.plano, self.resultado)
        except OSError as e:
            self.resultado.erros.append((self.plano.itens[0], _("Não foi possível gravar o pedido.txt ({erro}).")
                                         .format(erro=e)) if self.plano.itens else (None, str(e)))
        self.terminou.emit(self.resultado)


class ExportarDialog(QDialog):
    """Escolhas da exportação, resumo, avisos, progresso e resultado."""

    def __init__(self, estado: Estado, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.estado = estado
        self.setWindowTitle(_("Exportar para revelação"))
        self.setMinimumWidth(560)
        self.exportacao: Exportacao | None = None
        self.resultado: exportar.Resultado | None = None
        self.plano: exportar.Plano | None = None

        raiz = QVBoxLayout(self)
        form = QFormLayout()
        s = prefs.settings()
        pasta = str(s.value(CHAVE_PASTA, "", str) or "")
        if not pasta or not Path(pasta).is_dir():
            pasta = str(system.pasta_imagens())
        self.campo_pasta = QLineEdit(pasta)
        self.campo_pasta.setObjectName("exportar_pasta")
        self.botao_pasta = QPushButton(_("Escolher…"))
        self.botao_pasta.setObjectName("Flat")
        self.botao_pasta.clicked.connect(self.escolher_pasta)
        linha = QHBoxLayout()
        linha.addWidget(self.campo_pasta, 1)
        linha.addWidget(self.botao_pasta)
        form.addRow(_("Pasta de destino"), linha)

        self.combo_copias = QComboBox()
        for modo in exportar.MODOS:
            self.combo_copias.addItem(_(MODOS_TEXTO[modo]), modo)
        modo_salvo = str(s.value(CHAVE_MODO, exportar.MODO_PASTAS, str))
        self.combo_copias.setCurrentIndex(max(0, self.combo_copias.findData(modo_salvo)))
        form.addRow(_("Cópias"), self.combo_copias)

        self.spin_dpi = QSpinBox()
        self.spin_dpi.setRange(72, 1200)
        self.spin_dpi.setSuffix(" dpi")
        self.spin_dpi.setValue(self.estado.trabalho.dpi or 300)
        form.addRow(_("Resolução"), self.spin_dpi)
        raiz.addLayout(form)

        self.rotulo_resumo = QLabel()
        self.rotulo_resumo.setWordWrap(True)
        raiz.addWidget(self.rotulo_resumo)
        self.lista_avisos = QListWidget()
        self.lista_avisos.setMaximumHeight(110)
        raiz.addWidget(self.lista_avisos)
        self.rotulo_estrutura = QLabel()
        self.rotulo_estrutura.setObjectName("Muted")
        self.rotulo_estrutura.setWordWrap(True)
        self.rotulo_estrutura.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        raiz.addWidget(self.rotulo_estrutura)

        self.barra = QProgressBar()
        self.barra.hide()
        raiz.addWidget(self.barra)
        self.rotulo_fim = QLabel()
        self.rotulo_fim.setWordWrap(True)
        self.rotulo_fim.hide()
        raiz.addWidget(self.rotulo_fim)
        self.lista_erros = QListWidget()
        self.lista_erros.setMaximumHeight(110)
        self.lista_erros.hide()
        raiz.addWidget(self.lista_erros)

        botoes = QHBoxLayout()
        botoes.addStretch(1)
        self.botao_abrir = QPushButton(_("Abrir a pasta"))
        self.botao_abrir.setObjectName("Flat")
        self.botao_abrir.clicked.connect(self.abrir_pasta)
        self.botao_abrir.hide()
        self.botao_fechar = QPushButton(_("Fechar"))
        self.botao_fechar.setObjectName("Flat")
        self.botao_fechar.clicked.connect(self.reject)
        self.botao_exportar = QPushButton(_("Exportar"))
        self.botao_exportar.setObjectName("Primary")
        self.botao_exportar.setDefault(True)
        self.botao_exportar.clicked.connect(self.iniciar)
        self.botao_cancelar = QPushButton(_("Cancelar exportação"))
        self.botao_cancelar.setObjectName("Danger")
        self.botao_cancelar.clicked.connect(self.cancelar)
        self.botao_cancelar.hide()
        for b in (self.botao_abrir, self.botao_fechar, self.botao_cancelar, self.botao_exportar):
            botoes.addWidget(b)
        raiz.addLayout(botoes)

        self.campo_pasta.textChanged.connect(self.atualizar)
        self.combo_copias.currentIndexChanged.connect(self.atualizar)
        self.spin_dpi.valueChanged.connect(self.atualizar)
        self.atualizar()

    # ------------------------------------------------------------ escolhas e resumo
    @property
    def modo_copias(self) -> str:
        return str(self.combo_copias.currentData())

    def definir_destino(self, pasta: str | Path) -> None:
        self.campo_pasta.setText(str(pasta))

    def escolher_pasta(self) -> None:
        pasta = QFileDialog.getExistingDirectory(self, _("Pasta de destino"), self.campo_pasta.text())
        if pasta:
            self.definir_destino(pasta)

    def montar_plano(self) -> exportar.Plano:
        return exportar.planejar(self.estado.trabalho, self.campo_pasta.text().strip(), self.modo_copias,
                                 self.spin_dpi.value(), tabela_precos())

    def atualizar(self) -> None:
        """Refaz resumo, avisos e a prévia da estrutura (instantâneo: não toca no disco além de ver o que existe)."""
        if self.exportacao is not None:
            return
        destino = self.campo_pasta.text().strip()
        plano = self.montar_plano() if destino else None
        self.plano = plano
        n_fotos = plano.fotos if plano else len(self.estado.trabalho.selecionadas())
        n_copias = plano.copias if plano else 0
        orc = precos.orcamento(self.estado.trabalho, tabela_precos())
        if not any(ln.unitario is not None for ln in orc.linhas):
            custo = _("sem preços cadastrados")
        elif orc.completo:
            custo = precos.formatar(orc.total)
        else:
            custo = _("{total} + sem preço").format(total=precos.formatar(orc.total))
        self.rotulo_resumo.setText(_("{fotos} foto(s), {copias} cópia(s). Custo estimado: {custo} (estimativa).")
                                   .format(fotos=n_fotos, copias=n_copias, custo=custo))
        self.lista_avisos.clear()
        for aviso in exportar.conferir(self.estado.trabalho, self.estado.info):
            self.lista_avisos.addItem(aviso.texto)
        self.lista_avisos.setVisible(self.lista_avisos.count() > 0)
        if plano and plano.itens:
            nomes = [d.relative_to(plano.pasta.parent).as_posix() for i in plano.itens for d in i.destinos]
            texto = "\n".join(nomes[:LINHAS_ESTRUTURA])
            if len(nomes) > LINHAS_ESTRUTURA:
                texto += "\n" + _("… e mais {n} arquivo(s)").format(n=len(nomes) - LINHAS_ESTRUTURA)
            self.rotulo_estrutura.setText(texto)
        else:
            self.rotulo_estrutura.setText("")
        self.botao_exportar.setEnabled(bool(plano and plano.itens))

    # ------------------------------------------------------------ execução
    def iniciar(self) -> bool:
        """Começa a exportar (sem bloquear). Falso se não houver o que exportar, destino ou se já estiver rodando."""
        if self.exportacao is not None:
            return False
        self.atualizar()
        plano = self.plano
        if plano is None or not plano.itens:
            return False
        try:
            plano.pasta.parent.mkdir(parents=True, exist_ok=True)
            exportacao = Exportacao(plano, self)
            exportacao.iniciar()
        except OSError as e:
            self.rotulo_fim.setText(_("Não foi possível criar a pasta de destino: {erro}").format(erro=e))
            self.rotulo_fim.show()
            return False
        s = prefs.settings()
        s.setValue(CHAVE_PASTA, self.campo_pasta.text().strip())
        s.setValue(CHAVE_MODO, self.modo_copias)
        s.sync()
        self.exportacao = exportacao
        self.resultado = None
        for w in (self.campo_pasta, self.botao_pasta, self.combo_copias, self.spin_dpi):
            w.setEnabled(False)
        self.botao_exportar.hide()
        self.botao_cancelar.show()
        self.barra.setRange(0, len(plano.itens))
        self.barra.setValue(0)
        self.barra.show()
        exportacao.progresso.connect(lambda feitos, total: self.barra.setValue(feitos))
        exportacao.terminou.connect(self._ao_terminar)
        return True

    def cancelar(self) -> None:
        if self.exportacao is not None and not self.exportacao.concluida:
            self.exportacao.cancelar()
            self.botao_cancelar.setEnabled(False)

    def aguardar(self, ms: int = 60000) -> bool:
        """Espera o fim da exportação processando eventos (para testes e para fechar com segurança)."""
        espera = 0
        while self.exportacao is not None and not self.exportacao.concluida and espera < ms:
            QCoreApplication.processEvents()
            QThread.msleep(5)
            espera += 5
        QCoreApplication.processEvents()
        return self.exportacao is None or self.exportacao.concluida

    def _ao_terminar(self, resultado: exportar.Resultado) -> None:
        self.resultado = resultado
        self.botao_cancelar.hide()
        self.botao_fechar.show()
        self.botao_abrir.show()
        n = len(resultado.arquivos)
        if resultado.cancelado:
            texto = _("Exportação cancelada. {n} arquivo(s) ficaram prontos em {pasta}.")
        elif resultado.erros:
            texto = _("Exportação concluída com erros: {n} arquivo(s) gravados em {pasta}.")
        else:
            texto = _("Exportação concluída: {n} arquivo(s) em {pasta}.")
        self.rotulo_fim.setText(texto.format(n=n, pasta=self.plano.pasta if self.plano else ""))
        self.rotulo_fim.show()
        self.lista_erros.clear()
        for _item, msg in resultado.erros:
            self.lista_erros.addItem(msg)
        self.lista_erros.setVisible(self.lista_erros.count() > 0)

    def abrir_pasta(self) -> None:
        if self.plano is not None:
            system.reveal(self.plano.pasta)

    def reject(self) -> None:
        """Fechar durante a exportação cancela e espera o arquivo atual terminar."""
        if self.exportacao is not None and not self.exportacao.concluida:
            self.cancelar()
            self.aguardar()
        super().reject()

