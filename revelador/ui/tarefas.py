"""Trabalhadores da importação: metadados e miniatura (prioridade alta), depois os rostos (prioridade baixa).

Tudo pesado roda num ``QThreadPool``; os resultados voltam por sinal e são entregues ao ``Estado`` na thread
principal. Nenhum widget é tocado fora dela. Foto removida do trabalho no meio do caminho tem o resultado ignorado
(e, se ainda não começou, nem é processada). Não usa ``imagem.proxy``: o cache em memória é do editor.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from .. import imagem, miniaturas, rostos
from ..i18n import _
from .estado import Estado

log = logging.getLogger(__name__)

PRIORIDADE_MINIATURA = 10
PRIORIDADE_ROSTOS = 0
LADO_MINIATURA = 320
LADO_ROSTOS = 1280


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


class Importacao(QObject):
    """Cuida das fotos novas do ``Estado``: lê metadados/miniatura e depois detecta rostos, em segundo plano.

    ``mensagem(str)`` traz o progresso para a barra de status; ``ocioso()`` é emitido quando tudo termina.
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
        self._sinais.rostos_prontos.connect(self._ao_ter_rostos)
        self._vivas: set[str] = set()      # ids presentes no trabalho (lido pelas threads)
        self._pedidas: set[str] = set()    # ids já enfileirados
        self._total = 0                    # miniaturas pedidas / concluídas desde que ficou ocioso
        self._feitas = 0
        self._rostos_pendentes = 0
        estado.fotos_mudaram.connect(self.verificar)

    @property
    def ocupado(self) -> bool:
        return self._feitas < self._total or self._rostos_pendentes > 0

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
            self.estado.definir_info(foto_id, info)
            self.estado.definir_miniatura(foto_id, mini)
            if foto.rostos is None:
                self._rostos_pendentes += 1
                self.pool.start(_TarefaRostos(foto_id, foto.caminho, self._vivas, self._sinais), PRIORIDADE_ROSTOS)
        self._concluir_miniatura()

    def _ao_dar_erro(self, foto_id: str, mensagem: str) -> None:
        if mensagem:
            self.estado.definir_erro(foto_id, mensagem)
        self._concluir_miniatura()

    def _ao_ter_rostos(self, foto_id: str, achados) -> None:
        self._rostos_pendentes -= 1
        if achados is not None and self.estado.por_id(foto_id) is not None:
            self.estado.definir_rostos(foto_id, achados)
        self._mostrar_progresso()
        self._se_ocioso()

    def _concluir_miniatura(self) -> None:
        self._feitas += 1
        self._mostrar_progresso()
        self._se_ocioso()

    def _mostrar_progresso(self) -> None:
        if self._feitas < self._total:
            self.mensagem.emit(_("Importando {n} de {total}…").format(n=self._feitas, total=self._total))
        elif self._rostos_pendentes > 0:
            self.mensagem.emit(_("Procurando rostos para enquadrar ({n} restantes)…").format(n=self._rostos_pendentes))

    def _se_ocioso(self) -> None:
        if not self.ocupado:
            self._total = self._feitas = 0
            self.mensagem.emit(_("Pronto."))
            self.ocioso.emit()

    def aguardar(self, ms: int = 30000) -> bool:
        """Espera o pool esvaziar (encerramento). Não processa sinais."""
        return self.pool.waitForDone(ms)
