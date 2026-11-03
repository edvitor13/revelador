"""Salvar e abrir o trabalho na interface: Novo/Abrir/Salvar, recentes, título, recuperação e fotos não encontradas.

``ProjetoUi`` liga as ações do contrato da janela (``acao_novo``, ``acao_abrir``, ``acao_salvar``,
``acao_salvar_como`` e ``menu_recentes``) ao formato ``.revelador`` (``projeto.py``) e fala com o resto da
interface só pelo ``Estado``. Avisos, a oferta de recuperação e o "Procurar…" aparecem em **faixas não modais**
(``PilhaFaixas``) no alto da janela; nenhum diálogo é aberto por conta própria fora dos métodos ``perguntar_salvar``,
``escolher_arquivo_abrir``, ``escolher_arquivo_salvar`` e ``escolher_pasta_busca`` (os testes os substituem).

Recuperação: com o trabalho modificado, a cada ``INTERVALO_RECUPERACAO_MS`` grava uma cópia em
``%LOCALAPPDATA%\\Revelador\\recuperacao`` (``projeto.salvar_recuperacao``); salvar (inclusive o salvamento
automático), trocar de trabalho ou fechar apaga essas cópias. Depois de uma falha, a próxima abertura oferece
restaurar. Com o salvamento automático (``ui/autosalvar.py``, #34) ela fica só como rede de segurança para o que
mudou depois da última gravação.

Salvamento automático: a janela põe o ``AutoSalvar`` em ``autosalvar``. Ligado, trocar de trabalho ou fechar com
alterações grava sem perguntar (se a gravação falhar, a pergunta volta); "Salvar" num arquivo automático pergunta
onde salvar e "Salvar como…" apaga o arquivo automático antigo. ``salvo(Path)`` sai a cada "Salvar"/"Salvar como…".
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (QFileDialog, QFrame, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton,
                               QVBoxLayout, QWidget)

from .. import ajustes, projeto
from ..i18n import _
from ..projeto import ErroFormato, Foto, Trabalho
from ..tamanhos import TAMANHOS
from . import autosalvar as auto
from . import prefs, tema
from .estado import Estado

log = logging.getLogger(__name__)

EXTENSAO = ".revelador"
MAX_RECENTES = 10
INTERVALO_RECUPERACAO_MS = 2 * 60 * 1000
MAX_AVISOS_VISIVEIS = 3
MAX_ARQUIVOS_BUSCA = 300_000   # teto de arquivos olhados ao procurar fotos movidas

# Respostas de ``perguntar_salvar``
SALVAR, DESCARTAR, CANCELAR = "salvar", "descartar", "cancelar"


# --------------------------------------------------------------------------------------------------------------------
# Funções puras
# --------------------------------------------------------------------------------------------------------------------
def localizar_fotos(nomes: set[str], pasta: Path) -> dict[str, Path]:
    """Procura em ``pasta`` (e subpastas) arquivos com estes nomes (sem diferenciar maiúsculas).

    Devolve ``{nome em minúsculas: caminho}``; o primeiro achado, de cima para baixo, vence.
    """
    achados: dict[str, Path] = {}
    pendentes = {n.casefold() for n in nomes}
    vistos = 0
    for raiz, _pastas, arquivos in os.walk(pasta):
        for nome in arquivos:
            vistos += 1
            chave = nome.casefold()
            if chave in pendentes:
                achados[chave] = Path(raiz) / nome
                pendentes.discard(chave)
        if not pendentes or vistos > MAX_ARQUIVOS_BUSCA:
            break
    return achados


def com_extensao(caminho: Path) -> Path:
    return caminho if caminho.suffix.lower() == EXTENSAO else caminho.with_name(caminho.name + EXTENSAO)


# --------------------------------------------------------------------------------------------------------------------
# Faixas não modais
# --------------------------------------------------------------------------------------------------------------------
class Faixa(QFrame):
    """Uma linha de aviso com texto, botões de ação e "×" para fechar."""

    def __init__(self, chave: str, texto: str, cor: str, botoes: list[tuple[str, Callable[[], None]]],
                 ao_fechar: Callable[[], None], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.chave = chave
        self.setObjectName("Faixa")
        self.setStyleSheet(f"QFrame#Faixa {{ background: {tema.PAINEL2}; border: none; "
                           f"border-bottom: 1px solid {tema.BORDA}; border-left: 4px solid {cor}; }}")
        caixa = QHBoxLayout(self)
        caixa.setContentsMargins(12, 6, 8, 6)
        self.rotulo = QLabel(texto)
        self.rotulo.setWordWrap(True)
        self.rotulo.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        caixa.addWidget(self.rotulo, 1)
        self.botoes: dict[str, QPushButton] = {}
        for rotulo, acao in botoes:
            b = QPushButton(rotulo)
            b.setObjectName("Flat")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _checked=False, f=acao: f())
            caixa.addWidget(b)
            self.botoes[rotulo] = b
        fechar = QPushButton("×")
        fechar.setObjectName("Flat")
        fechar.setToolTip(_("Fechar este aviso"))
        fechar.setAccessibleName(_("Fechar este aviso"))
        fechar.clicked.connect(ao_fechar)
        caixa.addWidget(fechar)


class PilhaFaixas(QWidget):
    """Coluna de faixas no alto da janela; uma por chave (mostrar de novo troca a anterior)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._caixa = QVBoxLayout(self)
        self._caixa.setContentsMargins(0, 0, 0, 0)
        self._caixa.setSpacing(0)
        self.faixas: dict[str, Faixa] = {}
        self.hide()

    def mostrar(self, chave: str, texto: str, cor: str, botoes: list[tuple[str, Callable[[], None]]] | None = None
                ) -> Faixa:
        self.fechar(chave)
        faixa = Faixa(chave, texto, cor, botoes or [], lambda: self.fechar(chave), self)
        self.faixas[chave] = faixa
        self._caixa.addWidget(faixa)
        self.show()
        return faixa

    def fechar(self, chave: str) -> None:
        faixa = self.faixas.pop(chave, None)
        if faixa is not None:
            self._caixa.removeWidget(faixa)
            faixa.hide()
            faixa.deleteLater()
        if not self.faixas:
            self.hide()

    def textos(self) -> dict[str, str]:
        return {k: f.rotulo.text() for k, f in self.faixas.items()}


# --------------------------------------------------------------------------------------------------------------------
# Controlador
# --------------------------------------------------------------------------------------------------------------------
class ProjetoUi(QObject):
    """Cuida do ciclo de vida do trabalho (novo, abrir, salvar, fechar) para a ``MainWindow``."""

    salvo = Signal(object)   # Path gravado por "Salvar"/"Salvar como…" (o automático tem o sinal dele)

    def __init__(self, janela: QMainWindow, estado: Estado, importacao, faixas: PilhaFaixas) -> None:
        super().__init__(janela)
        self.janela = janela
        self.estado = estado
        self.importacao = importacao
        self.faixas = faixas
        self.titulo_padrao = janela.windowTitle()
        self.nome_sugerido: str | None = None            # nome de um trabalho restaurado, para o "Salvar como"
        self._recuperacoes: set[Path] = set()            # arquivos de recuperação gravados nesta sessão
        self.autosalvar = None                           # ``AutoSalvar`` (#34), posto pela janela

        a = janela
        a.acao_novo.triggered.connect(self.novo)
        a.acao_abrir.triggered.connect(lambda _c=False: self.abrir())
        a.acao_salvar.triggered.connect(lambda _c=False: self.salvar())
        a.acao_salvar_como.triggered.connect(lambda _c=False: self.salvar_como())
        for acao in (a.acao_novo, a.acao_abrir, a.acao_salvar, a.acao_salvar_como):
            acao.setEnabled(True)
        a.menu_recentes.aboutToShow.connect(self.reconstruir_menu)
        self.reconstruir_menu()

        estado.modificado_mudou.connect(lambda _m: self.atualizar_titulo())
        self.atualizar_titulo()

        self.timer = QTimer(self)
        self.timer.setInterval(INTERVALO_RECUPERACAO_MS)
        self.timer.timeout.connect(self.autossalvar)
        self.timer.start()
        janela.installEventFilter(self)

    # ------------------------------------------------------------ diálogos (os testes substituem)
    def perguntar_salvar(self) -> str:
        """Pergunta o que fazer com as alterações: ``SALVAR``, ``DESCARTAR`` ou ``CANCELAR``."""
        caixa = QMessageBox(QMessageBox.Icon.Question, _("Salvar alterações?"),
                            _("O trabalho tem alterações que não foram salvas. Quer salvar antes de continuar?"),
                            QMessageBox.StandardButton.NoButton, self.janela)
        salvar = caixa.addButton(_("Salvar"), QMessageBox.ButtonRole.AcceptRole)
        descartar = caixa.addButton(_("Não salvar"), QMessageBox.ButtonRole.DestructiveRole)
        cancelar = caixa.addButton(_("Cancelar"), QMessageBox.ButtonRole.RejectRole)
        caixa.setDefaultButton(salvar)
        caixa.setEscapeButton(cancelar)
        caixa.exec()
        clicado = caixa.clickedButton()
        if clicado is salvar:
            return SALVAR
        if clicado is descartar:
            return DESCARTAR
        return CANCELAR

    def escolher_arquivo_abrir(self) -> Path | None:
        s = prefs.settings()
        nome, _filtro = QFileDialog.getOpenFileName(
            self.janela, _("Abrir trabalho"), str(s.value("projeto/ultima_pasta", "", str)),
            _("Trabalho do Revelador") + f" (*{EXTENSAO})")
        return Path(nome) if nome else None

    def escolher_arquivo_salvar(self) -> Path | None:
        s = prefs.settings()
        atual = self.estado.trabalho.caminho
        if atual is not None and auto.e_automatico(atual):   # nome automático: começa na última pasta da pessoa
            pasta = str(s.value("projeto/ultima_pasta", "", str)) or str(atual.parent)
            inicio = str(Path(pasta) / atual.name)
        elif atual is not None:
            inicio = str(atual)
        else:
            pasta = str(s.value("projeto/ultima_pasta", "", str)) or str(Path.home())
            inicio = str(Path(pasta) / ((self.nome_sugerido or _("Trabalho")) + EXTENSAO))
        nome, _filtro = QFileDialog.getSaveFileName(
            self.janela, _("Salvar trabalho"), inicio, _("Trabalho do Revelador") + f" (*{EXTENSAO})")
        return Path(nome) if nome else None

    def escolher_pasta_busca(self) -> Path | None:
        s = prefs.settings()
        pasta = QFileDialog.getExistingDirectory(self.janela, _("Procurar as fotos que faltam"),
                                                 str(s.value("importar/ultima_pasta", "", str)))
        return Path(pasta) if pasta else None

    # ------------------------------------------------------------ título
    def titulo_janela(self) -> str:
        t = self.estado.trabalho
        if t.caminho is None and not self.estado.modificado:
            return self.titulo_padrao
        nome = t.caminho.stem if t.caminho is not None else (self.nome_sugerido or _("Sem título"))
        return f"{'• ' if self.estado.modificado else ''}{nome} — {_('Revelador')}"

    def atualizar_titulo(self) -> None:
        self.janela.setWindowTitle(self.titulo_janela())

    # ------------------------------------------------------------ perguntar e fechar
    def confirmar_descartar(self) -> bool:
        """Sem alterações, ``True``. Com alterações pergunta; ``True`` = pode seguir (salvou ou descartou).

        Com o salvamento automático ligado, grava sem perguntar; só se a gravação falhar a pergunta aparece.
        """
        if not self.estado.modificado:
            return True
        if self.autosalvar is not None and self.autosalvar.ligado and self.autosalvar.salvar_agora(sincrono=True):
            return True
        resposta = self.perguntar_salvar()
        if resposta == SALVAR:
            return self.salvar()
        return resposta == DESCARTAR

    def eventFilter(self, obj, evento) -> bool:  # noqa: N802 - nome do Qt
        if obj is self.janela and evento.type() == QEvent.Type.Close:
            if not self.confirmar_descartar():
                evento.ignore()
                return True
            self.timer.stop()
            self.apagar_recuperacoes()
        return False

    # ------------------------------------------------------------ novo, abrir, salvar
    def novo(self) -> bool:
        if not self.confirmar_descartar():
            return False
        antigo = self.estado.trabalho
        self._trocar_trabalho(Trabalho(tamanho_padrao=antigo.tamanho_padrao, dpi=antigo.dpi,
                                       margem_corte_mm=antigo.margem_corte_mm))
        return True

    def abrir(self, caminho: Path | str | None = None) -> bool:
        """Abre um ``.revelador`` (pergunta qual se ``caminho`` for ``None``). ``True`` se abriu."""
        if caminho is None:
            caminho = self.escolher_arquivo_abrir()
            if caminho is None:
                return False
        if not self.confirmar_descartar():
            return False
        return self._abrir_arquivo(Path(caminho))

    def _abrir_arquivo(self, caminho: Path, *, restaurando: bool = False) -> bool:
        try:
            trabalho, avisos = projeto.abrir(caminho, tamanhos_validos={t.id for t in TAMANHOS},
                                             limitar_ajustes=ajustes.sanitizar)
        except ErroFormato as e:
            self._erro(str(e))
            self._esquecer_recente(caminho)
            return False
        except OSError:
            self._erro(_("Não consegui abrir “{nome}”. O arquivo ainda existe?").format(nome=caminho.name))
            self._esquecer_recente(caminho)
            return False
        for foto in trabalho.fotos:   # "pasta/../fotos/a.jpg" (caminho relativo resolvido) vira o caminho limpo
            foto.caminho = Path(os.path.normpath(foto.caminho))
        if restaurando:
            trabalho.caminho = None
        self._trocar_trabalho(trabalho, avisos)
        if restaurando:
            self.estado.marcar_modificado(True)
            self.atualizar_titulo()
        else:
            self.adicionar_recente(caminho)
            self._lembrar_pasta(caminho)
        return True

    def salvar(self) -> bool:
        """Salva no arquivo do trabalho (pergunta onde, se ainda não tem ou se o arquivo é automático)."""
        caminho = self.estado.trabalho.caminho
        if caminho is None or auto.e_automatico(caminho):
            return self.salvar_como()
        return self._gravar(caminho)

    def salvar_como(self) -> bool:
        """Pergunta onde salvar e grava. Se o trabalho estava num arquivo automático, ele é apagado (foi movido)."""
        antigo = self.estado.trabalho.caminho
        destino = self.escolher_arquivo_salvar()
        if destino is None:
            return False
        destino = com_extensao(destino)
        if not self._gravar(destino):
            return False
        if antigo is not None and auto.e_automatico(antigo):
            if os.path.normcase(str(Path(antigo).absolute())) == os.path.normcase(str(Path(destino).absolute())):
                auto.esquecer_automatico(antigo)       # a pessoa adotou o próprio arquivo automático
            elif auto.apagar_automatico(antigo):
                self._esquecer_recente(antigo)
        return True

    def _gravar(self, destino: Path) -> bool:
        if self.autosalvar is not None:
            self.autosalvar.esperar()   # nunca duas gravações ao mesmo tempo no mesmo arquivo
        try:
            projeto.salvar(self.estado.trabalho, destino)
        except OSError as e:
            self._erro(_("Não consegui salvar em “{nome}”: {erro}").format(nome=destino.name, erro=e.strerror or e))
            return False
        self.nome_sugerido = None
        self.faixas.fechar("erro")
        self.apagar_recuperacoes()
        self.estado.marcar_modificado(False)
        self.adicionar_recente(destino)
        self._lembrar_pasta(destino)
        self.atualizar_titulo()
        self.salvo.emit(Path(destino))
        return True

    def _trocar_trabalho(self, trabalho: Trabalho, avisos: list[str] | None = None) -> None:
        """Instala um trabalho novo ou aberto: a grade se repovoa e a leitura das fotos recomeça."""
        self.apagar_recuperacoes()
        for chave in ("erro", "avisos", "faltando"):
            self.faixas.fechar(chave)
        self.nome_sugerido = None
        # Mesmos ids de um trabalho aberto antes não podem ser tomados por "já pedidos" pela importação.
        self.importacao._pedidas.clear()   # noqa: SLF001 - reinício da fila (a #2 não expõe método público)
        self.estado.definir_trabalho(trabalho)
        for foto in self.fotos_faltando():
            self.estado.definir_erro(foto.id, _("Foto não encontrada. Use “Procurar…” para religá-la."))
        self._mostrar_faltando()
        if avisos:
            visiveis = avisos[:MAX_AVISOS_VISIVEIS]
            if len(avisos) > len(visiveis):
                visiveis.append(_("(e mais {n})").format(n=len(avisos) - len(visiveis)))
            self.faixas.mostrar("avisos", _("Trabalho aberto com ajustes:") + " " + " ".join(visiveis), tema.AVISO)
        self.atualizar_titulo()

    # ------------------------------------------------------------ mensagens
    def _erro(self, texto: str) -> None:
        self.faixas.mostrar("erro", texto, tema.PERIGO)

    # ------------------------------------------------------------ fotos não encontradas
    def fotos_faltando(self) -> list[Foto]:
        return [f for f in self.estado.trabalho.fotos if not f.caminho.exists()]

    def _mostrar_faltando(self) -> None:
        n = len(self.fotos_faltando())
        if n == 0:
            self.faixas.fechar("faltando")
            return
        texto = (_("1 foto não foi encontrada. Ela pode ter sido movida ou apagada.") if n == 1 else
                 _("{n} fotos não foram encontradas. Elas podem ter sido movidas ou apagadas.").format(n=n))
        self.faixas.mostrar("faltando", texto, tema.AVISO, [(_("Procurar…"), lambda: self.procurar_faltando())])

    def procurar_faltando(self, pasta: Path | str | None = None) -> int:
        """Procura as fotos que faltam em ``pasta`` e religa todas as que achar. Devolve quantas religou."""
        faltando = self.fotos_faltando()
        if not faltando:
            self._mostrar_faltando()
            return 0
        if pasta is None:
            pasta = self.escolher_pasta_busca()
            if pasta is None:
                return 0
        achados = localizar_fotos({f.caminho.name for f in faltando}, Path(pasta))
        religadas: list[Foto] = []
        for foto in faltando:
            novo = achados.get(foto.caminho.name.casefold())
            if novo is not None:
                foto.caminho = novo
                religadas.append(foto)
        for foto in religadas:
            self.estado.erros.pop(foto.id, None)
            self.importacao._pedidas.discard(foto.id)   # noqa: SLF001 - volta para a fila de leitura
            self.estado.foto_mudou.emit(foto.id)
        if religadas:
            self.importacao.verificar()
            self.estado.marcar_modificado(True)
        self._mostrar_faltando()
        return len(religadas)

    # ------------------------------------------------------------ recentes
    def recentes(self) -> list[Path]:
        """Trabalhos recentes que ainda existem (mais novo primeiro, até ``MAX_RECENTES``)."""
        s = prefs.settings()
        try:
            bruto = json.loads(str(s.value("projeto/recentes", "[]", str)))
        except ValueError:
            bruto = []
        todos = [str(x) for x in bruto] if isinstance(bruto, list) else []
        vivos = [p for p in todos if Path(p).is_file()][:MAX_RECENTES]
        if vivos != todos:
            self._gravar_recentes(vivos)
        return [Path(p) for p in vivos]

    def _gravar_recentes(self, lista: list[str]) -> None:
        s = prefs.settings()
        s.setValue("projeto/recentes", json.dumps(lista, ensure_ascii=False))
        s.sync()

    def adicionar_recente(self, caminho: Path) -> None:
        novo = str(Path(caminho).absolute())
        chave = os.path.normcase(novo)
        resto = [str(p) for p in self.recentes() if os.path.normcase(str(p)) != chave]
        self._gravar_recentes(([novo] + resto)[:MAX_RECENTES])
        self.reconstruir_menu()

    def _esquecer_recente(self, caminho: Path) -> None:
        chave = os.path.normcase(str(Path(caminho).absolute()))
        self._gravar_recentes([str(p) for p in self.recentes() if os.path.normcase(str(p)) != chave])
        self.reconstruir_menu()

    def limpar_recentes(self) -> None:
        self._gravar_recentes([])
        self.reconstruir_menu()

    def reconstruir_menu(self) -> None:
        menu = self.janela.menu_recentes
        menu.clear()
        lista = self.recentes()
        for p in lista:
            acao = menu.addAction(p.name)
            acao.setData(str(p))
            acao.setToolTip(str(p))
            acao.setStatusTip(str(p))
            acao.triggered.connect(lambda _c=False, caminho=p: self.abrir(caminho))
        if lista:
            menu.addSeparator()
            menu.addAction(_("Limpar lista")).triggered.connect(lambda _c=False: self.limpar_recentes())
        menu.setEnabled(bool(lista))

    def _lembrar_pasta(self, caminho: Path) -> None:
        s = prefs.settings()
        s.setValue("projeto/ultima_pasta", str(Path(caminho).absolute().parent))
        s.sync()

    # ------------------------------------------------------------ recuperação
    def autossalvar(self) -> Path | None:
        """Grava a cópia de recuperação se o trabalho tem alterações (chamado pelo temporizador)."""
        if not self.estado.modificado:
            return None
        try:
            destino = projeto.salvar_recuperacao(self.estado.trabalho)
        except OSError:
            log.exception("falha ao gravar a recuperação")
            return None
        self._recuperacoes.add(destino)
        return destino

    def apagar_recuperacoes(self) -> None:
        for destino in list(self._recuperacoes):
            projeto.apagar_recuperacao(destino)
        self._recuperacoes.clear()

    def oferecer_recuperacao(self) -> Path | None:
        """Depois de uma falha: se sobrou cópia de recuperação, mostra a faixa "Restaurar / Descartar"."""
        achados = [p for p in projeto.listar_recuperacao() if p not in self._recuperacoes]
        if not achados:
            return None
        arquivo = achados[0]
        quando = time.strftime("%d/%m/%Y %H:%M", time.localtime(arquivo.stat().st_mtime))
        nome = arquivo.stem if arquivo.stem != "sem-nome" else _("Sem título")
        self.faixas.mostrar(
            "recuperacao",
            _("O Revelador foi fechado sem salvar “{nome}” ({quando}). Quer restaurar esse trabalho?").format(
                nome=nome, quando=quando),
            tema.DESTAQUE,
            [(_("Restaurar"), lambda: self.restaurar_recuperacao(arquivo)),
             (_("Descartar"), lambda: self.descartar_recuperacao(achados))])
        return arquivo

    def restaurar_recuperacao(self, arquivo: Path) -> bool:
        if not self.confirmar_descartar():
            return False
        self.faixas.fechar("recuperacao")
        if not self._abrir_arquivo(arquivo, restaurando=True):
            return False
        self.nome_sugerido = arquivo.stem if arquivo.stem != "sem-nome" else None
        projeto.apagar_recuperacao(arquivo)
        self.atualizar_titulo()
        return True

    def descartar_recuperacao(self, arquivos: list[Path]) -> None:
        for arquivo in arquivos:
            projeto.apagar_recuperacao(arquivo)
        self.faixas.fechar("recuperacao")
