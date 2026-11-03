"""Atualização automática: verificação ao abrir e pelo menu, e a janela das notas, do download e da instalação.

O núcleo (consulta, SHA-256, script de instalação) está em ``updater.py``; aqui fica a interface.

- ``Verificador.verificar_ao_abrir()``: consulta em segundo plano, no máximo uma vez por dia, e só se a preferência
  ``atualizacao/automatica`` estiver ligada. Erro de rede é silencioso; versão pulada (``atualizacao/pulada``) não
  é oferecida de novo.
- ``Verificador.verificar_manual()`` (Ajuda → "Verificar atualizações…"): sempre responde, inclusive com "você já
  está na versão mais recente" e com o erro.
- ``DialogoAtualizacao``: não modal (o app segue usável). Download numa thread, com progresso e cancelamento; antes
  de fechar o app para instalar, avisa se o trabalho tem alterações não salvas. Sem instalação automática (código-
  fonte, sistema sem suporte, release sem o pacote), mostra só a página da versão.

A requisição leva só o User-Agent do app (``updater``): nenhum dado do usuário sai.
"""

from __future__ import annotations

import threading
import time

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QLabel, QMessageBox, QProgressBar, QPushButton,
                               QTextBrowser, QVBoxLayout)

from .. import __version__, updater
from ..i18n import N_, _
from . import icones, prefs, tema

CHAVE_AUTOMATICA = "atualizacao/automatica"
CHAVE_ULTIMA = "atualizacao/ultima_verificacao"   # epoch (s) da última consulta, boa ou ruim
CHAVE_PULADA = "atualizacao/pulada"               # tag da versão que o usuário mandou pular
INTERVALO = 24 * 3600
ATRASO_AO_ABRIR_MS = 2000                         # a janela aparece antes da consulta

ERROS = {
    "no-public-release": N_("Não há versão publicada que o app consiga ver. O repositório precisa ser público "
                            "para as atualizações automáticas funcionarem."),
    "offline": N_("Não foi possível falar com o GitHub. Confira a sua conexão com a internet."),
    "no-checksums": N_("A versão publicada não tem o arquivo de conferência (SHA256SUMS.txt); por segurança, a "
                       "atualização automática foi cancelada. Baixe pela página da versão."),
    "checksum-mismatch": N_("O arquivo baixado não confere com o original publicado. Nada foi instalado."),
    "bad-archive": N_("O pacote baixado não tem o formato esperado. Nada foi instalado."),
    "unsupported": N_("Este tipo de instalação não pode ser atualizado automaticamente. Baixe pela página da versão."),
    "cancelled": N_("Download cancelado."),
}


def texto_erro(codigo: str) -> str:
    """Mensagem para um código de erro do ``updater`` (ou um texto cru, para código desconhecido)."""
    if codigo in ERROS:
        return _(ERROS[codigo])
    return _("Não foi possível verificar ou instalar a atualização ({codigo}).").format(codigo=codigo)


def automatica_ligada() -> bool:
    return bool(prefs.settings().value(CHAVE_AUTOMATICA, True, bool))


# Funções de caixa e de sistema, em nível de módulo: os testes as trocam sem abrir diálogo nem navegador.
def informar(janela, titulo: str, texto: str) -> None:
    QMessageBox.information(janela, titulo, texto)


def perguntar(janela, titulo: str, texto: str, confirmar: str) -> bool:
    """Pergunta com dois botões ("Voltar", padrão, e ``confirmar``). Devolve True só se confirmar."""
    caixa = QMessageBox(QMessageBox.Icon.Question, titulo, texto, QMessageBox.StandardButton.NoButton, janela)
    voltar = caixa.addButton(_("Voltar"), QMessageBox.ButtonRole.RejectRole)
    sim = caixa.addButton(confirmar, QMessageBox.ButtonRole.AcceptRole)
    caixa.setDefaultButton(voltar)
    caixa.exec()
    return caixa.clickedButton() is sim


def abrir_pagina(url: str) -> None:
    QDesktopServices.openUrl(QUrl(url))


def _encerrar() -> None:
    QApplication.instance().quit()


class _Ponte(QObject):
    """Sinais das threads de trabalho para a thread principal (entrega enfileirada)."""

    resultado = Signal(object)   # (release | None, código de erro, manual)
    progresso = Signal(int, int)  # bytes baixados, total
    terminou = Signal(str, str)  # caminho do pacote, código de erro


class Verificador(QObject):
    """Consulta a release em segundo plano e mostra o resultado na thread principal (aviso, mensagem ou diálogo)."""

    def __init__(self, janela) -> None:
        super().__init__(janela)
        self.janela = janela
        self.consultando = False
        self.dialogo: DialogoAtualizacao | None = None
        self._ponte = _Ponte(self)
        self._ponte.resultado.connect(self._ao_resultado)

    def verificar_manual(self) -> None:
        self._consultar(manual=True)

    def verificar_ao_abrir(self) -> None:
        if self.consultando or not automatica_ligada():
            return
        ultima = float(prefs.settings().value(CHAVE_ULTIMA, 0) or 0)
        if time.time() - ultima < INTERVALO:
            return
        self._consultar(manual=False)

    def _consultar(self, manual: bool) -> None:
        self.consultando = True
        threading.Thread(target=self._rodar, args=(manual,), daemon=True).start()

    def _rodar(self, manual: bool) -> None:
        try:
            payload = (updater.check(), "", manual)
        except updater.UpdateError as exc:
            payload = (None, str(exc), manual)
        except Exception as exc:  # noqa: BLE001 - a verificação nunca derruba o app
            payload = (None, str(exc) or exc.__class__.__name__, manual)
        self._ponte.resultado.emit(payload)

    def _ao_resultado(self, payload) -> None:
        rel, erro, manual = payload
        self.consultando = False
        prefs.settings().setValue(CHAVE_ULTIMA, time.time())
        if rel is None:
            if manual:
                informar(self.janela, _("Atualizações"), texto_erro(erro))
            return
        if not updater.is_newer(rel):
            if manual:
                informar(self.janela, _("Atualizações"),
                         _("Você já está na versão mais recente ({versao}).").format(versao=__version__))
            return
        if not manual and str(prefs.settings().value(CHAVE_PULADA, "")) == rel.tag:
            return
        self.dialogo = DialogoAtualizacao(self.janela, rel, self.janela.estado)
        self.dialogo.show()
        self.dialogo.raise_()


class DialogoAtualizacao(QDialog):
    """Notas da versão, download com progresso e instalação (ou só a página da versão, sem instalação automática)."""

    def __init__(self, janela, release: updater.Release, estado=None) -> None:
        super().__init__(janela)
        self.release = release
        self.estado = estado
        self.tipo = updater.install_info()["kind"]
        self.pacote = updater.pick_asset(release, self.tipo)  # (nome, url, tamanho) ou None
        self.automatica = updater.can_auto_install(self.tipo) and self.pacote is not None
        self._cancelar = threading.Event()
        self._ocupado = False
        self._baixado = ""  # pacote já baixado e conferido: "Atualizar agora" de novo não baixa outra vez
        self._ponte = _Ponte(self)
        self._ponte.progresso.connect(self._progresso)
        self._ponte.terminou.connect(self._terminou)

        versao = release.tag.lstrip("v")
        self.setWindowTitle(_("Atualização disponível"))
        self.resize(620, 520)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 16)
        lay.setSpacing(10)
        kicker = QLabel(_("ATUALIZAÇÃO"))
        kicker.setObjectName("Kicker")
        lay.addWidget(kicker)
        titulo = QLabel(_("Revelador {versao} está disponível").format(versao=versao))
        titulo.setObjectName("PanelTitle")
        lay.addWidget(titulo)
        atual = QLabel(_("Você está usando a versão {atual}.").format(atual=__version__))
        atual.setObjectName("Muted")
        lay.addWidget(atual)
        self.notas = QTextBrowser()
        self.notas.setOpenExternalLinks(True)
        self.notas.setMarkdown(release.body or _("Sem notas para esta versão."))
        lay.addWidget(self.notas, 1)
        self.barra = QProgressBar()
        self.barra.setRange(0, 1000)
        self.barra.setVisible(False)
        lay.addWidget(self.barra)
        self.situacao = QLabel()
        self.situacao.setObjectName("Muted")
        self.situacao.setWordWrap(True)
        lay.addWidget(self.situacao)

        linha = QHBoxLayout()
        self.pular = QPushButton(_("Pular esta versão"))
        self.pular.setObjectName("Flat")
        self.pular.clicked.connect(self._pular)
        linha.addWidget(self.pular)
        self.pagina = QPushButton(_("Abrir página da versão"))
        self.pagina.setObjectName("Flat" if self.automatica else "Primary")
        self.pagina.clicked.connect(lambda: abrir_pagina(release.url))
        linha.addWidget(self.pagina)
        linha.addStretch(1)
        self.cancelar = QPushButton(_("Cancelar download"))
        self.cancelar.clicked.connect(self._cancelar.set)
        self.cancelar.setVisible(False)
        linha.addWidget(self.cancelar)
        self.depois = QPushButton(_("Mais tarde"))
        self.depois.clicked.connect(self.reject)
        linha.addWidget(self.depois)
        self.atualizar = QPushButton("  " + _("Atualizar agora"))
        self.atualizar.setObjectName("Primary")
        self.atualizar.setIcon(icones.icone("exportar", tema.TEXTO_SOBRE_DESTAQUE, 16))
        self.atualizar.clicked.connect(self._iniciar)
        self.atualizar.setVisible(self.automatica)
        linha.addWidget(self.atualizar)
        lay.addLayout(linha)

        if not self.automatica:
            if self.tipo == "source":
                self.situacao.setText(_("Você está rodando pelo código-fonte: atualize com \"git pull\" ou baixe a "
                                        "versão nova pela página."))
            else:
                self.situacao.setText(_("Não há instalação automática para este tipo de instalação. Baixe pela "
                                        "página da versão."))

    @property
    def ocupado(self) -> bool:
        """True enquanto o pacote está sendo baixado."""
        return self._ocupado

    def _pular(self) -> None:
        prefs.settings().setValue(CHAVE_PULADA, self.release.tag)
        self.reject()

    def _iniciar(self) -> None:
        if self._baixado:
            self._pedir_instalacao()
            return
        self._ocupado = True
        self._cancelar.clear()
        self.atualizar.setEnabled(False)
        self.depois.setEnabled(False)
        self.pular.setEnabled(False)
        self.cancelar.setVisible(True)
        self.barra.setValue(0)
        self.barra.setVisible(True)
        self.situacao.setText(_("Baixando {arquivo}…").format(arquivo=self.pacote[0]))
        threading.Thread(target=self._baixar, daemon=True).start()

    def _baixar(self) -> None:
        try:
            caminho = updater.download(self.release, self.pacote,
                                       lambda feito, total: self._ponte.progresso.emit(feito, total), self._cancelar)
            self._ponte.terminou.emit(caminho, "")
        except updater.UpdateError as exc:
            self._ponte.terminou.emit("", str(exc))
        except Exception as exc:  # noqa: BLE001
            self._ponte.terminou.emit("", str(exc) or exc.__class__.__name__)

    def _progresso(self, feito: int, total: int) -> None:
        if total > 0:
            self.barra.setValue(int(feito / total * 1000))
            self.situacao.setText(_("Baixando… {feito} de {total} MB").format(
                feito=f"{feito / 1e6:.0f}", total=f"{total / 1e6:.0f}"))

    def _terminou(self, caminho: str, erro: str) -> None:
        self._ocupado = False
        self.barra.setVisible(False)
        self.cancelar.setVisible(False)
        self.depois.setEnabled(True)
        self.pular.setEnabled(True)
        if erro:
            self.atualizar.setEnabled(True)
            self.situacao.setText(texto_erro(erro))
            return
        self._baixado = caminho
        self.situacao.setText(_("Pacote baixado e conferido com o SHA-256 publicado."))
        self._pedir_instalacao()

    def _pedir_instalacao(self) -> None:
        versao = self.release.tag.lstrip("v")
        texto = _("Fechar o Revelador para instalar a versão {versao}? Ele abre de novo sozinho quando a instalação "
                  "terminar.").format(versao=versao)
        if self.estado is not None and self.estado.modificado:
            aviso = _("O trabalho tem alterações não salvas. Salve o trabalho antes de atualizar: fechar o Revelador "
                      "agora perde essas alterações.")
            texto = aviso + "\n\n" + texto
        self.atualizar.setEnabled(True)
        if not perguntar(self, _("Instalar atualização"), texto, _("Instalar e fechar")):
            self.situacao.setText(_("A instalação ficou para depois. O pacote já baixado continua pronto: clique em "
                                    "\"Atualizar agora\" quando quiser."))
            return
        self.atualizar.setEnabled(False)
        janela = self.parent()
        if janela is not None and not janela.close():
            # O usuário cancelou o fechamento (trabalho não salvo, exportação em andamento): nada é instalado.
            self.atualizar.setEnabled(True)
            self.situacao.setText(_("A instalação ficou para depois e o app continua aberto. Clique em "
                                    "\"Atualizar agora\" quando quiser instalar."))
            return
        try:
            updater.install(self._baixado, self.tipo)
        except updater.UpdateError as exc:
            if janela is not None:
                janela.show()
            self.show()
            self.atualizar.setEnabled(True)
            self.situacao.setText(texto_erro(str(exc)))
            return
        self.accept()
        _encerrar()

    def reject(self) -> None:
        if self._ocupado:
            self._cancelar.set()
        super().reject()
