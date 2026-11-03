"""Trabalhadores da importação: metadados e miniatura primeiro; depois os rostos, aos poucos, numa fila própria.

Tudo pesado roda em ``QThreadPool``; os resultados voltam por sinal e são entregues ao ``Estado`` na thread
principal. Nenhum widget é tocado fora dela. Foto removida do trabalho no meio do caminho tem o resultado ignorado
(e, se ainda não começou, nem é processada). Não usa ``imagem.proxy``: o cache em memória é do editor.

Rostos (``FilaRostos``, #36): um pool só deles com ``limite_rostos()`` trabalhadores (1; 2 com 8 núcleos ou mais).
A fila fica na thread principal e entrega ao pool uma foto por trabalhador livre, escolhida na hora (a prioridade
muda sem reenfileirar nada): (a) as pedidas (``Estado.pedir_rostos``), a foto atual e as recém-marcadas para
revelar, que furam a fila e não esperam as miniaturas; (b) depois que as miniaturas pendentes terminam, as fotos
visíveis na tela da grade (``Estado.na_tela``); (c) a ordem da grade (``Estado.visiveis``) e o resto. Fotos que já
têm rostos (``.revelador`` aberto) não são detectadas de novo. Pausa enquanto ``Estado.exportando``.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from itertools import chain
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal

from .. import imagem, miniaturas, rostos
from ..i18n import _
from ..projeto import Foto
from .estado import Estado

log = logging.getLogger(__name__)

PRIORIDADE_MINIATURA = 10
LADO_MINIATURA = 320
LADO_ROSTOS = 1280


def limite_rostos(nucleos: int | None = None) -> int:
    """Quantas detecções de rostos rodam ao mesmo tempo: 1, ou 2 em máquinas com 8 núcleos ou mais."""
    n = os.cpu_count() if nucleos is None else nucleos
    return 2 if (n or 1) >= 8 else 1


class _Sinais(QObject):
    """Sinais dos workers; vive na thread principal, então a entrega é sempre ali (conexão em fila)."""

    info_pronta = Signal(str, object, object)   # id, InfoFoto, caminho da miniatura
    erro = Signal(str, str)                     # id, mensagem ("" = foto removida, só fecha a contagem)
    rostos_prontos = Signal(str, object)        # id, list[Rosto] (None = não detectou: removida ou ilegível)


class _TarefaMiniatura(QRunnable):
    def __init__(self, foto_id: str, caminho: Path, vivas: set[str], sinais: _Sinais) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self.foto_id, self.caminho, self.vivas, self.sinais = foto_id, caminho, vivas, sinais

    def run(self) -> None:
        if self.foto_id not in self.vivas:
            self.sinais.erro.emit(self.foto_id, "")
            return
        try:
            info = imagem.abrir_info(self.caminho)
            mini = miniaturas.obter(self.caminho, LADO_MINIATURA)
        except imagem.ErroImagem as e:
            self.sinais.erro.emit(self.foto_id, str(e))
        except Exception as e:  # noqa: BLE001 - uma foto ruim nunca derruba a importação
            log.exception("falha ao ler %s", self.caminho.name)
            self.sinais.erro.emit(self.foto_id, _("Não foi possível abrir esta foto.") + f" ({e})")
        else:
            self.sinais.info_pronta.emit(self.foto_id, info, mini)


class _TarefaRostos(QRunnable):
    def __init__(self, foto_id: str, caminho: Path, vivas: set[str], sinais: _Sinais) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self.foto_id, self.caminho, self.vivas, self.sinais = foto_id, caminho, vivas, sinais

    def run(self) -> None:
        achados = None
        if self.foto_id in self.vivas:
            try:
                achados = rostos.detectar(imagem.carregar(self.caminho, lado_max=LADO_ROSTOS))
            except Exception:  # noqa: BLE001 - rostos são só sugestão; foto ilegível já foi marcada pela miniatura
                log.exception("falha ao carregar %s para os rostos", self.caminho.name)
        self.sinais.rostos_prontos.emit(self.foto_id, achados)


class FilaRostos(QObject):
    """Detecta os rostos das fotos sem detecção, aos poucos e na ordem de prioridade (veja o início do módulo).

    ``progresso()`` avisa (na thread principal) que algo começou ou terminou; ``ocupado`` diz se ainda há o que
    fazer; ``feitos``/``total`` contam desde a última vez que ficou ociosa. ``miniaturas_pendentes`` (chamável) diz
    se a importação ainda lê miniaturas: até lá, só as fotos que furam a fila são detectadas.
    """

    progresso = Signal()

    def __init__(self, estado: Estado, vivas: set[str], miniaturas_pendentes: Callable[[], bool] = lambda: False,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.estado = estado
        self.limite = limite_rostos()
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(self.limite)
        self.miniaturas_pendentes = miniaturas_pendentes
        self._vivas = vivas                     # o mesmo conjunto da importação (lido pelas threads)
        self._sinais = _Sinais(self)
        self._sinais.rostos_prontos.connect(self._ao_ter_rostos)
        self._indice: dict[str, Foto] = {}      # fotos do trabalho por id
        self._em_voo: dict[str, Path] = {}      # id -> caminho entregue ao pool
        self._urgentes: list[str] = []          # furam a fila (o pedido mais recente primeiro)
        self._falhas: set[str] = set()          # não abriram para os rostos: não tenta de novo sozinho
        self._selecionadas: set[str] = set()    # para notar a foto recém-marcada para revelar
        self.feitos = 0
        self._timer = QTimer(self)               # junta vários avisos seguidos num agendamento só
        self._timer.setSingleShot(True)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self.agendar)
        estado.fotos_mudaram.connect(self._ao_mudar_fotos)
        estado.atual_mudou.connect(self._ao_mudar_atual)
        estado.foto_mudou.connect(self._ao_mudar_foto)
        estado.rostos_pedidos.connect(self._ao_pedir)
        estado.exportando_mudou.connect(self._ao_mudar_exportando)
        self._ao_mudar_fotos()

    # ------------------------------------------------------------ consulta
    def _candidata(self, foto: Foto) -> bool:
        return (foto.rostos is None and foto.id not in self._em_voo and foto.id not in self._falhas
                and foto.id not in self.estado.erros)

    @property
    def pendentes(self) -> int:
        """Fotos que ainda vão ser detectadas (fora as que estão rodando agora)."""
        return sum(1 for f in self.estado.trabalho.fotos if self._candidata(f))

    @property
    def em_andamento(self) -> int:
        return len(self._em_voo)

    @property
    def total(self) -> int:
        return self.feitos + self.em_andamento + self.pendentes

    @property
    def ocupado(self) -> bool:
        return bool(self._em_voo) or self.pendentes > 0

    @property
    def pausada(self) -> bool:
        return self.estado.exportando

    def _proxima(self) -> Foto | None:
        while self._urgentes:
            foto = self._indice.get(self._urgentes.pop(0))
            if foto is not None and self._candidata(foto):
                return foto
        if self.miniaturas_pendentes():
            return None
        for foto_id in chain(self.estado.na_tela, self.estado.visiveis):
            foto = self._indice.get(foto_id)
            if foto is not None and self._candidata(foto):
                return foto
        return next((f for f in self.estado.trabalho.fotos if self._candidata(f)), None)

    # ------------------------------------------------------------ agendamento (thread principal)
    def logo(self) -> None:
        """Agenda uma rodada de entrega ao pool assim que o laço de eventos voltar (vários avisos viram um)."""
        if not self._timer.isActive():
            self._timer.start()

    def agendar(self) -> None:
        """Entrega ao pool uma foto por trabalhador livre, a de maior prioridade agora."""
        if self.pausada:
            return
        entregou = False
        while len(self._em_voo) < self.limite:
            foto = self._proxima()
            if foto is None:
                break
            self._em_voo[foto.id] = foto.caminho
            self.pool.start(_TarefaRostos(foto.id, foto.caminho, self._vivas, self._sinais))
            entregou = True
        if entregou:
            self.progresso.emit()

    def _urgente(self, foto_id: str) -> None:
        if foto_id in self._urgentes:
            self._urgentes.remove(foto_id)
        self._urgentes.insert(0, foto_id)
        self.logo()

    def esquecer_falha(self, foto_id: str) -> None:
        """A foto foi lida de novo (religada, por exemplo): pode voltar a ser detectada."""
        self._falhas.discard(foto_id)

    # ------------------------------------------------------------ reações
    def _ao_mudar_fotos(self) -> None:
        fotos = self.estado.trabalho.fotos
        self._indice = {f.id: f for f in fotos}
        self._selecionadas = {f.id for f in fotos if f.selecionada}
        self._urgentes = [i for i in self._urgentes if i in self._indice]
        self._falhas &= self._indice.keys()
        if self.estado.atual is not None and self.estado.atual.id in self._indice:
            self._ao_mudar_atual(self.estado.atual)
        self.logo()

    def _ao_mudar_atual(self, foto: Foto | None) -> None:
        if foto is not None and foto.rostos is None:
            self._urgente(foto.id)

    def _ao_pedir(self, foto_id: str) -> None:
        self._falhas.discard(foto_id)      # pedido explícito tenta de novo
        self._urgente(foto_id)

    def _ao_mudar_exportando(self, _sim: bool) -> None:
        self.logo()
        self.progresso.emit()

    def _ao_mudar_foto(self, foto_id: str) -> None:
        foto = self._indice.get(foto_id)
        if foto is None:
            return
        if foto.selecionada != (foto_id in self._selecionadas):
            if foto.selecionada:
                self._selecionadas.add(foto_id)
                if foto.rostos is None:
                    self._urgente(foto_id)     # recém-marcada para revelar
            else:
                self._selecionadas.discard(foto_id)
        if self._candidata(foto):              # chegou a miniatura, ou os rostos foram zerados (foto mudou no disco)
            self.logo()

    def _ao_ter_rostos(self, foto_id: str, achados) -> None:
        caminho = self._em_voo.pop(foto_id, None)
        self.feitos += 1
        foto = self._indice.get(foto_id)
        if foto is not None and foto.caminho == caminho and foto.rostos is None:
            if achados is None:
                self._falhas.add(foto_id)
            else:
                self.estado.definir_rostos(foto_id, achados)
        if not self.ocupado:
            self.feitos = 0
        self.agendar()
        self.progresso.emit()

    def aguardar(self, ms: int = 30000) -> bool:
        return self.pool.waitForDone(ms)


class Importacao(QObject):
    """Cuida das fotos novas do ``Estado``: lê metadados/miniatura e depois detecta rostos, em segundo plano.

    ``mensagem(str)`` traz o progresso para a barra de status ("Importando 3 de 10…", depois "Rostos: 12 de 80",
    e "Pronto." no fim); ``ocioso()`` é emitido quando tudo termina. Os rostos ficam na ``FilaRostos`` (``rostos``).
    Fotos que já têm rostos (trabalho aberto) não são detectadas de novo.
    """

    mensagem = Signal(str)
    ocioso = Signal()

    def __init__(self, estado: Estado, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.estado = estado
        self.pool = QThreadPool(self)
        self._sinais = _Sinais(self)
        self._sinais.info_pronta.connect(self._ao_ter_info)
        self._sinais.erro.connect(self._ao_dar_erro)
        self._vivas: set[str] = set()      # ids presentes no trabalho (lido pelas threads)
        self._pedidas: set[str] = set()    # ids já enfileirados
        self._total = 0                    # miniaturas pedidas / concluídas desde que ficou ocioso
        self._feitas = 0
        self._avisou_ocioso = True
        estado.fotos_mudaram.connect(self.verificar)
        self.rostos = FilaRostos(estado, self._vivas, lambda: self._feitas < self._total, self)
        self.rostos.progresso.connect(self._ao_progredir_rostos)

    @property
    def ocupado(self) -> bool:
        return self._feitas < self._total or self.rostos.ocupado

    def verificar(self) -> None:
        """Enfileira o que ainda não foi enfileirado e esquece as fotos removidas."""
        fotos = self.estado.trabalho.fotos
        self._vivas.clear()
        self._vivas.update(f.id for f in fotos)
        for foto in fotos:
            if foto.id in self._pedidas:
                continue
            self._pedidas.add(foto.id)
            self._total += 1
            self.pool.start(_TarefaMiniatura(foto.id, foto.caminho, self._vivas, self._sinais), PRIORIDADE_MINIATURA)
        self._mostrar_progresso()

    # ------------------------------------------------------------ resultados (thread principal)
    def _ao_ter_info(self, foto_id: str, info, mini) -> None:
        foto = self.estado.por_id(foto_id)
        if foto is not None:
            self.rostos.esquecer_falha(foto_id)
            self.estado.definir_info(foto_id, info)
            self.estado.definir_miniatura(foto_id, mini)
        self._concluir_miniatura()

    def _ao_dar_erro(self, foto_id: str, mensagem: str) -> None:
        if mensagem:
            self.estado.definir_erro(foto_id, mensagem)
        self._concluir_miniatura()

    def _ao_progredir_rostos(self) -> None:
        self._mostrar_progresso()
        self._se_ocioso()

    def _concluir_miniatura(self) -> None:
        self._feitas += 1
        if self._feitas >= self._total:
            self.rostos.logo()            # miniaturas prontas: a fila de rostos segue com o resto
        self._mostrar_progresso()
        self._se_ocioso()

    def _mostrar_progresso(self) -> None:
        if self._feitas < self._total:
            self._avisou_ocioso = False
            self.mensagem.emit(_("Importando {n} de {total}…").format(n=self._feitas, total=self._total))
        elif self.rostos.ocupado and not self.rostos.pausada:
            self._avisou_ocioso = False
            self.mensagem.emit(_("Rostos: {n} de {total}").format(n=self.rostos.feitos, total=self.rostos.total))

    def _se_ocioso(self) -> None:
        if not self.ocupado:
            self._total = self._feitas = 0
            if not self._avisou_ocioso:     # só na transição: rodadas vazias não repetem "Pronto."
                self._avisou_ocioso = True
                self.mensagem.emit(_("Pronto."))
            self.ocioso.emit()

    def aguardar(self, ms: int = 30000) -> bool:
        """Espera os pools esvaziarem (encerramento). Não processa sinais."""
        return self.pool.waitForDone(ms) and self.rostos.aguardar(ms)
