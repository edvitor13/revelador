"""Salvamento automático do trabalho (#34): a cada intervalo, se houver alterações, grava sozinho, sem perguntar.

- **Trabalho com arquivo**: grava no próprio ``.revelador``.
- **Trabalho novo**: na primeira gravação ganha um nome ("Revelação AAAA-MM-DD HH-MM", o nome da primeira pasta
  importada ou o nome de um trabalho restaurado) e vai para a pasta dos trabalhos automáticos
  (``Imagens\\Revelador\\Trabalhos`` por padrão; trocável nas Configurações), com nome livre (`` (2)``...), e entra
  nos recentes. Esse arquivo fica marcado como **automático** (lista ``autosalvar/automaticos`` nas preferências,
  nunca dentro do arquivo); "Salvar" nele pergunta onde salvar e "Salvar como…" o move: o automático antigo é
  apagado (só ele, e só se ainda estiver na lista; um arquivo da pessoa nunca é apagado).
- **Sem travar a interface**: o texto do arquivo é montado na thread principal (é rápido) e gravado num
  ``QThreadPool`` próprio de uma thread por ``projeto.gravar_texto_seguro`` (``.tmp`` + ``os.replace``); o
  resultado volta por sinal. Depois de gravar, o trabalho só deixa de estar "modificado" se nada mudou no meio.
- **Indicador** na barra de status (``indicador``): "Salvando…" / "Salvo às 14:32". Falha: faixa de aviso não modal
  (chave ``"autosalvar"``) uma vez por sequência de falhas, e o trabalho continua modificado; nada se perde.
- **Ao fechar** (e ao trocar de trabalho) com o salvamento ligado, ``ProjetoUi.confirmar_descartar`` chama
  ``salvar_agora(sincrono=True)`` em vez de perguntar; se falhar, a pergunta volta.

Preferências: ``autosalvar/ligado`` (bool, padrão ligado), ``autosalvar/intervalo_min`` (minutos, padrão 1),
``autosalvar/pasta`` (vazio = padrão) e ``autosalvar/automaticos`` (JSON com os arquivos criados por aqui).
Com ``REVELADOR_SETTINGS_DIR`` (modo portátil e testes) a pasta padrão fica ao lado das preferências
(``<pasta>/Trabalhos``), para nada ser gravado fora dela. Só o ``.revelador`` é gravado; as fotos, nunca.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QThreadPool, QTimer, Signal
from PySide6.QtWidgets import QLabel, QMainWindow

from .. import projeto, system
from ..i18n import _
from ..projeto import Trabalho
from . import prefs, tema
from .estado import Estado

log = logging.getLogger(__name__)

EXTENSAO = ".revelador"
CHAVE_LIGADO = "autosalvar/ligado"
CHAVE_INTERVALO = "autosalvar/intervalo_min"
CHAVE_PASTA = "autosalvar/pasta"
CHAVE_AUTOMATICOS = "autosalvar/automaticos"
INTERVALO_PADRAO_MIN = 1
INTERVALO_MIN, INTERVALO_MAX = 1, 60
MAX_AUTOMATICOS = 200
_PROIBIDOS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


# --------------------------------------------------------------------------------------------------------------------
# Preferências
# --------------------------------------------------------------------------------------------------------------------
def ligado() -> bool:
    return bool(prefs.settings().value(CHAVE_LIGADO, True, bool))


def intervalo_min() -> int:
    try:
        n = int(prefs.settings().value(CHAVE_INTERVALO, INTERVALO_PADRAO_MIN))
    except (TypeError, ValueError):
        n = INTERVALO_PADRAO_MIN
    return min(max(n, INTERVALO_MIN), INTERVALO_MAX)


def pasta_padrao() -> Path:
    r"""``Imagens\Revelador\Trabalhos``; no modo portátil/testes (``REVELADOR_SETTINGS_DIR``), ao lado das prefs."""
    portatil = os.environ.get("REVELADOR_SETTINGS_DIR")
    if portatil:
        return Path(portatil) / "Trabalhos"
    return system.pasta_imagens() / "Revelador" / "Trabalhos"


def pasta_trabalhos() -> Path:
    """Pasta onde os trabalhos novos são salvos automaticamente (preferência ou padrão)."""
    escolhida = str(prefs.settings().value(CHAVE_PASTA, "", str) or "")
    return Path(escolhida) if escolhida else pasta_padrao()


def gravar_preferencias(*, ligar: bool, minutos: int, pasta: Path | str | None) -> None:
    """Grava as três preferências do salvamento automático (``pasta`` vazia/None = padrão)."""
    s = prefs.settings()
    s.setValue(CHAVE_LIGADO, bool(ligar))
    s.setValue(CHAVE_INTERVALO, min(max(int(minutos), INTERVALO_MIN), INTERVALO_MAX))
    texto = str(pasta) if pasta else ""
    s.setValue(CHAVE_PASTA, "" if texto and Path(texto) == pasta_padrao() else texto)
    s.sync()


# ------------------------------------------------------------ marca de "automático"
def _chave(caminho: Path | str) -> str:
    return os.path.normcase(str(Path(caminho).absolute()))


def _automaticos() -> list[str]:
    try:
        bruto = json.loads(str(prefs.settings().value(CHAVE_AUTOMATICOS, "[]", str)))
    except ValueError:
        bruto = []
    return [str(x) for x in bruto] if isinstance(bruto, list) else []


def _gravar_automaticos(lista: list[str]) -> None:
    s = prefs.settings()
    s.setValue(CHAVE_AUTOMATICOS, json.dumps(lista[-MAX_AUTOMATICOS:], ensure_ascii=False))
    s.sync()


def e_automatico(caminho: Path | str | None) -> bool:
    """O arquivo foi criado pelo salvamento automático e a pessoa ainda não o adotou ("Salvar como…")."""
    if caminho is None:
        return False
    chave = _chave(caminho)
    return any(_chave(p) == chave for p in _automaticos())


def marcar_automatico(caminho: Path | str) -> None:
    chave = _chave(caminho)
    _gravar_automaticos([p for p in _automaticos() if _chave(p) != chave] + [str(Path(caminho).absolute())])


def esquecer_automatico(caminho: Path | str) -> None:
    chave = _chave(caminho)
    lista = _automaticos()
    resto = [p for p in lista if _chave(p) != chave]
    if resto != lista:
        _gravar_automaticos(resto)


def apagar_automatico(caminho: Path | str) -> bool:
    """Apaga o arquivo automático (só se estiver na lista e for um ``.revelador``). ``True`` se apagou."""
    caminho = Path(caminho)
    if not e_automatico(caminho) or caminho.suffix.lower() != EXTENSAO:
        return False
    esquecer_automatico(caminho)
    try:
        caminho.unlink(missing_ok=True)
    except OSError:
        log.exception("não consegui apagar o trabalho automático antigo")
        return False
    return True


# --------------------------------------------------------------------------------------------------------------------
# Funções puras
# --------------------------------------------------------------------------------------------------------------------
def limpar_nome(nome: str) -> str:
    """Nome de arquivo válido no Windows (sem ``<>:"/\\|?*``, sem ponto ou espaço no fim); vazio se nada sobrar."""
    return _PROIBIDOS.sub(" ", nome).strip().rstrip(". ").strip()


def nome_por_data(quando: datetime) -> str:
    return _("Revelação {data}").format(data=quando.strftime("%Y-%m-%d %H-%M"))


def arquivo_livre(pasta: Path, nome: str) -> Path:
    """``pasta/nome.revelador``; se já existir, ``nome (2).revelador``, ``nome (3)``... (nunca sobrescreve)."""
    candidato = pasta / f"{nome}{EXTENSAO}"
    n = 2
    while candidato.exists() or candidato.with_name(candidato.name + ".tmp").exists():
        candidato = pasta / f"{nome} ({n}){EXTENSAO}"
        n += 1
    return candidato


def texto_do_trabalho(trabalho: Trabalho, base: Path) -> str:
    """O mesmo texto que ``projeto.salvar`` grava (caminhos das fotos relativos a ``base`` quando dá)."""
    return json.dumps(projeto.para_dict(trabalho, base), ensure_ascii=False, indent=2) + "\n"


# --------------------------------------------------------------------------------------------------------------------
# Controlador
# --------------------------------------------------------------------------------------------------------------------
@dataclass
class _Gravacao:
    trabalho: Trabalho
    destino: Path
    texto: str
    novo: bool          # arquivo criado agora (trabalho que não tinha caminho)


class AutoSalvar(QObject):
    """Temporizador, gravação em segundo plano, indicador da barra de status e a faixa de falha.

    Sinais: ``salvo(Path)`` depois de cada gravação automática bem-sucedida e ``falhou(str)`` com a mensagem.
    ``ms_por_minuto`` (60000) pode ser reduzido nos testes antes de ``aplicar_preferencias()``.
    """

    salvo = Signal(object)
    falhou = Signal(str)
    _terminou = Signal()

    def __init__(self, janela: QMainWindow, estado: Estado, projeto_ui, faixas) -> None:
        super().__init__(janela)
        self.janela = janela
        self.estado = estado
        self.projeto_ui = projeto_ui
        self.faixas = faixas
        self.ms_por_minuto = 60_000
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._andamento: _Gravacao | None = None
        self._resultado: str | None = None        # "" = gravou; texto = erro (escrito pela thread, lido aqui)
        self._falhando = False
        self._inicio: tuple[Trabalho, datetime] | None = None        # primeira alteração do trabalho sem arquivo
        self._pasta_importada: tuple[Trabalho, str] | None = None    # nome da primeira pasta importada nele
        self._terminou.connect(self._concluir)

        self.indicador = QLabel()
        self.indicador.setAccessibleName(_("Salvamento do trabalho"))
        self.indicador.hide()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tique)
        estado.modificado_mudou.connect(self._ao_modificar)
        projeto_ui.salvo.connect(self._ao_salvar_manual)
        self.aplicar_preferencias()

    # ------------------------------------------------------------ preferências
    @property
    def ligado(self) -> bool:
        return self.timer.isActive()

    def aplicar_preferencias(self) -> None:
        """Relê as preferências (ligado e intervalo) e reinicia o temporizador."""
        self.timer.setInterval(max(1, intervalo_min() * self.ms_por_minuto))
        if ligado():
            self.timer.start()
        else:
            self.timer.stop()

    # ------------------------------------------------------------ nome do trabalho novo
    def notar_importacao(self, caminhos) -> None:
        """Guarda o nome da primeira pasta importada num trabalho ainda sem arquivo (vira o nome automático)."""
        t = self.estado.trabalho
        if t.caminho is not None or (self._pasta_importada is not None and self._pasta_importada[0] is t):
            return
        for c in caminhos:
            p = Path(c)
            nome = limpar_nome(p.name)
            if nome and p.is_dir():
                self._pasta_importada = (t, nome)
                return

    def _ao_modificar(self, sim: bool) -> None:
        t = self.estado.trabalho
        if sim and t.caminho is None and (self._inicio is None or self._inicio[0] is not t):
            self._inicio = (t, datetime.now())

    def nome_automatico(self) -> str:
        """Nome do trabalho atual, sem arquivo: o do trabalho restaurado, a primeira pasta importada ou a data."""
        t = self.estado.trabalho
        sugerido = limpar_nome(self.projeto_ui.nome_sugerido or "")
        if sugerido:
            return sugerido
        if self._pasta_importada is not None and self._pasta_importada[0] is t:
            return self._pasta_importada[1]
        quando = self._inicio[1] if self._inicio is not None and self._inicio[0] is t else datetime.now()
        return nome_por_data(quando)

    # ------------------------------------------------------------ gravar
    @property
    def gravando(self) -> bool:
        return self._andamento is not None

    def tique(self) -> None:
        """Temporizador: grava em segundo plano se o trabalho tem alterações e nada está sendo gravado."""
        if self.estado.modificado and self._andamento is None:
            self.salvar_agora()

    def salvar_agora(self, sincrono: bool = False) -> bool:
        """Grava agora, se houver alterações. ``True``: gravou, começou a gravar ou não havia o que gravar.

        ``sincrono`` (ao fechar ou trocar de trabalho): espera a gravação em curso e grava nesta thread; devolve
        ``False`` se falhar. Trabalho novo e vazio (sem fotos) não vira arquivo.
        """
        if self._andamento is not None:
            if not sincrono:
                return True
            self.esperar()
        t = self.estado.trabalho
        if not self.estado.modificado:
            return True
        novo = t.caminho is None
        if novo and not t.fotos:
            return True
        destino = (arquivo_livre(pasta_trabalhos(), self.nome_automatico()) if novo else t.caminho).absolute()
        self._andamento = _Gravacao(t, destino, texto_do_trabalho(t, destino.parent), novo)
        self._mostrar(_("Salvando…"), str(destino))
        if sincrono:
            self._resultado = self._gravar(destino, self._andamento.texto)
            return self._concluir()
        g = self._andamento
        self._pool.start(lambda: self._em_fundo(g))
        return True

    @staticmethod
    def _gravar(destino: Path, texto: str) -> str:
        try:
            projeto.gravar_texto_seguro(destino, texto)
        except OSError as e:
            return str(e.strerror or e)
        except Exception as e:  # noqa: BLE001 - qualquer falha vira aviso; o trabalho continua aberto
            log.exception("falha no salvamento automático")
            return str(e) or type(e).__name__
        return ""

    def _em_fundo(self, g: _Gravacao) -> None:
        """Roda no ``QThreadPool``: só grava o texto (nada de Qt de interface aqui)."""
        self._resultado = self._gravar(g.destino, g.texto)
        self._terminou.emit()

    def esperar(self) -> None:
        """Espera a gravação em curso terminar e trata o resultado (antes de outra gravação no mesmo arquivo)."""
        if self._andamento is not None:
            self._pool.waitForDone()
            self._concluir()

    def encerrar(self) -> None:
        """Ao fechar a janela: para o temporizador e espera a gravação em curso."""
        self.timer.stop()
        self.esperar()

    def _concluir(self) -> bool:
        """Na thread principal: trata o resultado da gravação (o sinal em fila chega depois e não acha nada)."""
        g, erro = self._andamento, self._resultado
        if g is None or erro is None:
            return False
        self._andamento, self._resultado = None, None
        if erro:
            self._falha(g, erro)
            return False
        ui = self.projeto_ui
        if g.novo:
            g.trabalho.caminho = g.destino
            marcar_automatico(g.destino)
            ui.adicionar_recente(g.destino)
        if self.estado.trabalho is g.trabalho:
            ui.nome_sugerido = None
            ui.apagar_recuperacoes()
            if texto_do_trabalho(g.trabalho, g.destino.parent) == g.texto:   # nada mudou durante a gravação
                self.estado.marcar_modificado(False)
            ui.atualizar_titulo()
        self._sucesso(g.destino)
        self.salvo.emit(g.destino)
        return True

    # ------------------------------------------------------------ indicador e avisos
    def _mostrar(self, texto: str, dica: str = "") -> None:
        self.indicador.setText(texto)
        self.indicador.setToolTip(dica)
        self.indicador.show()

    def _sucesso(self, destino: Path) -> None:
        self._mostrar(_("Salvo às {hora}").format(hora=datetime.now().strftime("%H:%M")),
                      _("Salvo em {caminho}").format(caminho=destino))
        if self._falhando:
            self._falhando = False
            self.faixas.fechar("autosalvar")

    def _ao_salvar_manual(self, destino) -> None:
        """"Salvar"/"Salvar como…" da pessoa também atualiza o indicador e tira a faixa de falha."""
        self._sucesso(Path(destino))

    def _falha(self, g: _Gravacao, erro: str) -> None:
        self._mostrar(_("Não salvo"), _("O salvamento automático falhou: {erro}").format(erro=erro))
        self.falhou.emit(erro)
        if self._falhando:
            return   # um aviso por sequência de falhas; a próxima tentativa é no próximo intervalo
        self._falhando = True
        acao_config = getattr(self.janela, "acao_configuracoes", None)
        botoes = [(_("Salvar como…"), lambda: self.projeto_ui.salvar_como())]
        if acao_config is not None:
            botoes.append((_("Configurações…"), acao_config.trigger))
        self.faixas.mostrar(
            "autosalvar",
            _("Não consegui salvar automaticamente em “{nome}”: {erro}. As alterações continuam abertas; "
              "tento de novo em instantes, ou use “Salvar como…”.").format(nome=g.destino.name, erro=erro),
            tema.PERIGO, botoes)
