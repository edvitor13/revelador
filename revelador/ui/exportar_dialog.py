"""Diálogo "Exportar para revelação" (docs/ARQUITETURA.md, seção 8).

Escolhe a pasta de destino (lembrada nas preferências), como organizar (por tamanho ou por pasta de tamanho, #32;
lembrado; a linha só aparece quando o trabalho tem pastas), o modo das cópias e o dpi, mostra o resumo (fotos, cópias,
custo estimado), os avisos de conferência e a estrutura que será criada. A exportação roda num ``QThreadPool``
próprio (até 4 em paralelo); o progresso e o fim chegam por sinal na thread principal.

Testável sem diálogo modal: ``definir_destino()``, ``iniciar()`` (devolve False se não puder), ``aguardar()``,
``cancelar()``; o resultado fica em ``resultado``.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from PySide6.QtGui import QColor
from PySide6.QtCore import QCoreApplication, QObject, QRunnable, Qt, QThread, QThreadPool, QTimer, Signal
from PySide6.QtWidgets import (QComboBox, QDialog, QFileDialog, QFormLayout, QGridLayout, QHBoxLayout, QLabel,
                               QMessageBox,
                               QLineEdit, QListWidget, QProgressBar, QPushButton, QSpinBox, QVBoxLayout, QWidget)

from .. import exportar, precos, system
from ..i18n import N_, _
from . import prefs, tema
from .componentes import Segmented
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
CHAVE_ORGANIZAR = "exportar/organizar"
CHAVE_ACABAMENTO = "exportar/acabamento/"   # + nome do tamanho ("10x15") → "borda|papel", lembrado por tamanho
ORGANIZAR_TEXTO = (
    (exportar.ORGANIZAR_TAMANHO, N_("Tamanho"), N_("Uma subpasta por tamanho (10x15, 15x21...)")),
    (exportar.ORGANIZAR_PASTA, N_("Pasta"), N_("Uma subpasta por pasta de tamanho; as fotos avulsas, por tamanho")),
)
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
        raiz.setContentsMargins(22, 20, 22, 18)
        raiz.setSpacing(12)
        form = QFormLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)
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

        self.campo_nome = QLineEdit(exportar.nome_pasta(date.today()))
        self.campo_nome.setObjectName("exportar_nome")
        self.campo_nome.setPlaceholderText(exportar.nome_pasta(date.today()))
        self.campo_nome.setToolTip(_("A pasta principal, com uma pasta por tamanho dentro. Se já existir, é substituída (a antiga vai para a "
                                         "Lixeira)."))
        form.addRow(_("Nome da pasta"), self.campo_nome)

        self.combo_copias = QComboBox()
        for modo in exportar.MODOS:
            self.combo_copias.addItem(_(MODOS_TEXTO[modo]), modo)
        modo_salvo = str(s.value(CHAVE_MODO, exportar.MODO_REPETIR, str))   # padrão: repetir o arquivo
        self.combo_copias.setCurrentIndex(max(0, self.combo_copias.findData(modo_salvo)))
        form.addRow(_("Cópias"), self.combo_copias)

        self.seg_organizar = Segmented([(k, _(t), _(d)) for k, t, d in ORGANIZAR_TEXTO])
        organizar_salvo = str(s.value(CHAVE_ORGANIZAR, exportar.ORGANIZAR_TAMANHO, str))
        if organizar_salvo not in exportar.ORGANIZACOES:
            organizar_salvo = exportar.ORGANIZAR_TAMANHO
        self.seg_organizar.definir_atual(organizar_salvo)
        linha_org = QHBoxLayout()
        linha_org.addWidget(self.seg_organizar)
        linha_org.addStretch(1)
        form.addRow(_("Organizar por"), linha_org)
        form.setRowVisible(linha_org, bool(self.estado.trabalho.pastas))

        self.spin_dpi = QSpinBox()
        self.spin_dpi.setRange(72, 1200)
        self.spin_dpi.setSuffix(" dpi")
        self.spin_dpi.setValue(self.estado.trabalho.dpi or 300)
        form.addRow(_("Resolução"), self.spin_dpi)
        raiz.addLayout(form)
        raiz.addWidget(self._montar_acabamentos())

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
        self.campo_nome.textChanged.connect(self.atualizar)
        self.combo_copias.currentIndexChanged.connect(self.atualizar)
        self.seg_organizar.mudou.connect(lambda _k: self.atualizar())
        self.spin_dpi.valueChanged.connect(self.atualizar)
        self.atualizar()

    # ------------------------------------------------------------ acabamento por tamanho
    def tamanhos_exportados(self) -> list[str]:
        """Nomes dos tamanhos que vão sair ("10x15", "15x21"...), na ordem em que aparecem no trabalho."""
        return list(dict.fromkeys(exportar.nome_tamanho(imp) for foto in self.estado.trabalho.selecionadas()
                                  for imp in foto.impressoes))

    def _montar_acabamentos(self) -> QWidget:
        """Uma linha por tamanho: borda e papel, só para o nome da pasta e o pedido.txt (a foto sai sem borda)."""
        caixa = QWidget()
        grade = QGridLayout(caixa)
        grade.setContentsMargins(0, 0, 0, 0)
        grade.setHorizontalSpacing(10)
        grade.setVerticalSpacing(6)
        titulo = QLabel(_("Acabamento"))
        titulo.setObjectName("PanelTitle")
        dica = QLabel(_("Vai no nome de cada pasta de tamanho, para o laboratório (a foto sai sem borda)."))
        dica.setObjectName("Muted")
        dica.setWordWrap(True)
        grade.addWidget(titulo, 0, 0, 1, 3)
        grade.addWidget(dica, 1, 0, 1, 3)
        for coluna, texto in ((1, _("Borda")), (2, _("Papel"))):
            cabecalho = QLabel(texto)
            cabecalho.setObjectName("Faint")
            grade.addWidget(cabecalho, 2, coluna)
        self.combos_acabamento: dict[str, tuple[QComboBox, QComboBox]] = {}
        s = prefs.settings()
        for linha, tam in enumerate(self.tamanhos_exportados(), start=3):
            borda, papel = QComboBox(), QComboBox()
            for chave in exportar.BORDAS:
                borda.addItem(_maiuscula(_(exportar.TEXTO_BORDA[chave])), chave)
            for chave in exportar.PAPEIS:
                papel.addItem(_maiuscula(_(exportar.TEXTO_PAPEL[chave])), chave)
            salvo = str(s.value(CHAVE_ACABAMENTO + tam, "", str) or "").split("|")
            borda.setCurrentIndex(max(0, borda.findData(salvo[0])))
            papel.setCurrentIndex(max(0, papel.findData(salvo[1] if len(salvo) > 1 else "")))
            borda.setToolTip(_("Borda branca que o laboratório deve fazer em {t}").format(t=tam))
            papel.setToolTip(_("Papel da revelação em {t}").format(t=tam))
            borda.currentIndexChanged.connect(self.atualizar)
            papel.currentIndexChanged.connect(self.atualizar)
            rotulo = QLabel(tam)
            rotulo.setObjectName("Value")
            grade.addWidget(rotulo, linha, 0)
            grade.addWidget(borda, linha, 1)
            grade.addWidget(papel, linha, 2)
            self.combos_acabamento[tam] = (borda, papel)
        grade.setColumnStretch(1, 1)
        grade.setColumnStretch(2, 1)
        caixa.setVisible(bool(self.combos_acabamento))
        return caixa

    def acabamentos(self) -> dict[str, exportar.Acabamento]:
        return {tam: exportar.Acabamento(str(b.currentData()), str(p.currentData()))
                for tam, (b, p) in self.combos_acabamento.items()}

    def definir_acabamento(self, tamanho: str, borda: str = "", papel: str = "") -> None:
        """Escolhe borda e papel de um tamanho (testes e atalhos)."""
        b, p = self.combos_acabamento[tamanho]
        b.setCurrentIndex(b.findData(borda))
        p.setCurrentIndex(p.findData(papel))

    def definir_nome(self, nome: str) -> None:
        self.campo_nome.setText(nome)

    def _lembrar_acabamentos(self) -> None:
        s = prefs.settings()
        for tam, a in self.acabamentos().items():
            s.setValue(CHAVE_ACABAMENTO + tam, f"{a.borda}|{a.papel}")

    # ------------------------------------------------------------ escolhas e resumo
    @property
    def modo_copias(self) -> str:
        return str(self.combo_copias.currentData())

    @property
    def organizar(self) -> str:
        """``exportar.ORGANIZAR_TAMANHO`` ou ``ORGANIZAR_PASTA`` (sem pastas no trabalho, sempre por tamanho)."""
        if not self.estado.trabalho.pastas:
            return exportar.ORGANIZAR_TAMANHO
        return self.seg_organizar.chave_atual() or exportar.ORGANIZAR_TAMANHO

    def definir_organizar(self, chave: str) -> None:
        self.seg_organizar.definir_atual(chave)
        self.atualizar()

    def definir_destino(self, pasta: str | Path) -> None:
        self.campo_pasta.setText(str(pasta))

    def escolher_pasta(self) -> None:
        pasta = QFileDialog.getExistingDirectory(self, _("Pasta de destino"), self.campo_pasta.text())
        if pasta:
            self.definir_destino(pasta)

    def montar_plano(self) -> exportar.Plano:
        return exportar.planejar(self.estado.trabalho, self.campo_pasta.text().strip(), self.modo_copias,
                                 self.spin_dpi.value(), tabela_precos(), organizar=self.organizar,
                                 nome=self.campo_nome.text(), acabamentos=self.acabamentos())

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
            self.lista_avisos.item(self.lista_avisos.count() - 1).setForeground(QColor(tema.AVISO))
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
        if not self._liberar_pasta():
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
        self._lembrar_acabamentos()
        if self.estado.trabalho.pastas:
            s.setValue(CHAVE_ORGANIZAR, self.organizar)
        s.sync()
        self.exportacao = exportacao
        self.estado.definir_exportando(True)   # a fila de rostos pausa (#36)
        self.resultado = None
        for w in (self.campo_pasta, self.botao_pasta, self.combo_copias, self.spin_dpi, self.seg_organizar):
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

    def pasta_principal(self) -> Path | None:
        """``destino/nome`` da pasta principal, como a pessoa escreveu (antes do `` (2)`` automático)."""
        destino = self.campo_pasta.text().strip()
        if not destino:
            return None
        return Path(destino) / exportar.nome_principal(self.campo_nome.text(), date.today())

    def perguntar_substituir(self, pasta: Path) -> bool:
        """Pergunta se a pasta que já existe pode ser substituída (testes trocam este método)."""
        caixa = QMessageBox(QMessageBox.Icon.Warning, _("A pasta já existe"),
                            _("Já existe a pasta “{nome}” em {lugar}.\n\nEla será substituída completamente: a "
                              "pasta antiga vai para a Lixeira (dá para recuperar de lá) e a revelação nova fica "
                              "sozinha, sem misturar fotos de outra revelação.").format(nome=pasta.name,
                                                                                       lugar=pasta.parent),
                            parent=self)
        substituir = caixa.addButton(_("Substituir"), QMessageBox.ButtonRole.AcceptRole)
        caixa.addButton(_("Cancelar"), QMessageBox.ButtonRole.RejectRole)
        caixa.exec()
        return caixa.clickedButton() is substituir

    def _liberar_pasta(self) -> bool:
        """Se a pasta principal já existe: pergunta e, com "Substituir", manda a antiga para a Lixeira."""
        pasta = self.pasta_principal()
        if pasta is None or not pasta.exists():
            return True
        if not self.perguntar_substituir(pasta):
            return False
        try:
            system.para_lixeira(pasta)
        except OSError as e:
            self.rotulo_fim.setText(_("Não foi possível substituir a pasta: {erro}").format(erro=e))
            self.rotulo_fim.show()
            return False
        return True

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
        self.estado.definir_exportando(False)  # concluída ou cancelada: os rostos seguem (#36)
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
            self.lista_erros.item(self.lista_erros.count() - 1).setForeground(QColor(tema.PERIGO))
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


def _maiuscula(texto: str) -> str:
    return texto[:1].upper() + texto[1:]
