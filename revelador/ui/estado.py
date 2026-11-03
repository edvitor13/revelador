"""Estado compartilhado da interface: o trabalho aberto, a foto atual e os avisos de mudança.

Grade, editor, painel lateral e barra de status leem e alteram o modelo (``projeto.py``) **por aqui** e reagem aos
sinais; nenhum widget conversa direto com outro. Só a thread principal mexe no ``Estado``: workers (miniaturas,
metadados, rostos, prévia, exportação) devolvem resultados por sinal e quem recebe chama os métodos daqui.

Sinais:
- ``fotos_mudaram()``: a lista de fotos mudou (importação, remoção, trabalho aberto).
- ``atual_mudou(foto | None)``: outra foto passou a ser a atual (a do editor e do painel).
- ``impressao_mudou(indice)``: outra impressão da foto atual passou a ser a do editor (o painel escolhe).
- ``foto_mudou(id)``: algo de uma foto mudou (seleção, impressões, recorte, ajustes, rostos, metadados).
- ``pedido_mudou()``: algo que muda o orçamento ou a exportação (seleção, tamanhos, cópias, preços).
- ``modificado_mudou(bool)``: o trabalho passou a ter (ou deixou de ter) alterações não salvas.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from ..enquadramento import recorte_sugerido
from ..imagem import InfoFoto
from ..projeto import Foto, Impressao, Rosto, Trabalho


def novo_id() -> str:
    """Id de foto: curto, único e estável (vai para o ``.revelador``; nunca muda depois de criado)."""
    return uuid.uuid4().hex[:12]


class Estado(QObject):
    """O trabalho aberto e a foto atual, com sinais para a interface reagir."""

    fotos_mudaram = Signal()
    atual_mudou = Signal(object)
    impressao_mudou = Signal(int)
    foto_mudou = Signal(str)
    pedido_mudou = Signal()
    modificado_mudou = Signal(bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.trabalho = Trabalho()
        self.atual: Foto | None = None
        self.indice_impressao = 0             # impressão da foto atual mostrada no editor
        self.info: dict[str, InfoFoto] = {}   # metadados lidos em segundo plano (largura/altura orientadas etc.)
        self._modificado = False

    # ------------------------------------------------------------ consulta
    @property
    def modificado(self) -> bool:
        return self._modificado

    @property
    def impressao_atual(self) -> Impressao | None:
        """A impressão da foto atual que o editor mostra (None sem foto ou sem impressões)."""
        if self.atual is None or not self.atual.impressoes:
            return None
        return self.atual.impressoes[min(self.indice_impressao, len(self.atual.impressoes) - 1)]

    def por_id(self, foto_id: str) -> Foto | None:
        return next((f for f in self.trabalho.fotos if f.id == foto_id), None)

    # ------------------------------------------------------------ trabalho e lista de fotos
    def definir_trabalho(self, trabalho: Trabalho) -> None:
        """Troca o trabalho inteiro (novo ou aberto de um ``.revelador``)."""
        self.trabalho = trabalho
        self.info.clear()
        self.atual = None
        self.fotos_mudaram.emit()
        self.atual_mudou.emit(None)
        self.pedido_mudou.emit()
        self.marcar_modificado(False)

    def adicionar(self, caminhos: list[Path]) -> list[Foto]:
        """Cria fotos para os caminhos ainda não presentes (mesmo arquivo não entra duas vezes) e devolve as novas."""
        existentes = {_chave_caminho(f.caminho) for f in self.trabalho.fotos}
        novas: list[Foto] = []
        for caminho in caminhos:
            chave = _chave_caminho(caminho)
            if chave in existentes:
                continue
            existentes.add(chave)
            novas.append(Foto(id=novo_id(), caminho=Path(caminho)))
        if novas:
            self.trabalho.fotos.extend(novas)
            self.fotos_mudaram.emit()
            self.marcar_modificado()
        return novas

    def remover(self, fotos: list[Foto]) -> None:
        """Tira fotos do trabalho (o arquivo original não é tocado)."""
        ids = {f.id for f in fotos}
        if not ids:
            return
        self.trabalho.fotos = [f for f in self.trabalho.fotos if f.id not in ids]
        for foto_id in ids:
            self.info.pop(foto_id, None)
        if self.atual is not None and self.atual.id in ids:
            self.definir_atual(None)
        self.fotos_mudaram.emit()
        self.pedido_mudou.emit()
        self.marcar_modificado()

    def definir_atual(self, foto: Foto | None) -> None:
        if foto is self.atual:
            return
        self.atual = foto
        self.indice_impressao = 0
        self.atual_mudou.emit(foto)

    def definir_impressao(self, indice: int) -> None:
        """Escolhe qual impressão da foto atual o editor mostra."""
        if indice != self.indice_impressao:
            self.indice_impressao = indice
            self.impressao_mudou.emit(indice)

    # ------------------------------------------------------------ resultados dos workers
    def definir_info(self, foto_id: str, info: InfoFoto) -> None:
        """Metadados lidos em segundo plano. Preenche bytes/mtime da foto e refaz os recortes automáticos."""
        foto = self.por_id(foto_id)
        if foto is None:
            return
        self.info[foto_id] = info
        foto.bytes = info.bytes
        foto.mtime = info.mtime / 1e9   # Foto.mtime em segundos; InfoFoto.mtime em ns
        self.refazer_recortes_auto(foto)
        self.foto_mudou.emit(foto_id)

    def definir_rostos(self, foto_id: str, rostos: list[Rosto]) -> None:
        """Rostos detectados em segundo plano ([] = nenhum). Refaz os recortes que não são manuais."""
        foto = self.por_id(foto_id)
        if foto is None:
            return
        foto.rostos = list(rostos)
        self.refazer_recortes_auto(foto)
        self.foto_mudou.emit(foto_id)
        self.marcar_modificado()

    # ------------------------------------------------------------ seleção e impressões
    def selecionar(self, foto: Foto, sim: bool = True) -> None:
        """Marca/desmarca a foto para revelação. A primeira seleção cria uma impressão no tamanho padrão."""
        if foto.selecionada == sim and (not sim or foto.impressoes):
            return
        foto.selecionada = sim
        if sim and not foto.impressoes:
            foto.impressoes.append(Impressao(tamanho=self.trabalho.tamanho_padrao))
            self.refazer_recortes_auto(foto)
        self.alterar(foto, pedido=True)

    def refazer_recortes_auto(self, foto: Foto) -> None:
        """Recalcula o recorte das impressões não manuais (precisa dos metadados; sem eles, não faz nada).

        Chame depois de mudar tamanho, orientação ou giro de uma impressão não manual.
        """
        info = self.info.get(foto.id)
        if info is None:
            return
        for imp in foto.impressoes:
            if imp.recorte.origem != "manual":
                imp.recorte = recorte_sugerido(imp, info.largura, info.altura, foto.rostos,
                                               self.trabalho.margem_corte_mm)

    def alterar(self, foto: Foto, *, pedido: bool = False) -> None:
        """Avisa que a foto mudou (quem mexeu no modelo chama isto). ``pedido=True`` se afeta orçamento/exportação."""
        self.foto_mudou.emit(foto.id)
        if pedido:
            self.pedido_mudou.emit()
        self.marcar_modificado()

    def marcar_modificado(self, sim: bool = True) -> None:
        if sim != self._modificado:
            self._modificado = sim
            self.modificado_mudou.emit(sim)


def _chave_caminho(caminho: Path) -> str:
    try:
        return str(Path(caminho).resolve()).casefold()
    except OSError:
        return str(caminho).casefold()
