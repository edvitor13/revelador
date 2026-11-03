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
- ``comparando_mudou(bool)``: antes/depois (``comparando``): enquanto verdadeiro, o editor mostra a foto sem ajustes.
- ``pastas_mudaram()``: a lista de pastas de tamanho (``trabalho.pastas``) ou algo de uma pasta mudou (#32).

Pastas de tamanho (#32): grupos virtuais do trabalho (nada muda no disco). Estar numa pasta = ter UMA impressão com
``pasta=<id>``, no tamanho da pasta; a foto pode estar em várias pastas e ainda ter impressões avulsas. Use só a API
da seção "pastas de tamanho" (``criar_pasta``, ``alterar_pasta``, ``apagar_pasta``, ``mover_pasta``,
``adicionar_a_pasta``, ``tirar_da_pasta``, ``fotos_da_pasta``, ``pastas_da_foto``, ``impressao_da_pasta``): ela
mantém o tamanho das impressões igual ao da pasta, refaz/reencaixa os recortes e agrupa tudo num passo do desfazer.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from .. import enquadramento, tamanhos
from ..enquadramento import recorte_sugerido
from ..i18n import _
from ..imagem import InfoFoto
from ..projeto import COPIAS_MAX, COPIAS_MIN, Foto, Impressao, Pasta, Rosto, Trabalho
from . import tema

_MANTER = object()   # valor padrão de ``alterar_pasta``: "não mexer neste campo"


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
    comparando_mudou = Signal(bool)
    pastas_mudaram = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.trabalho = Trabalho()
        self.atual: Foto | None = None
        self.indice_impressao = 0             # impressão da foto atual mostrada no editor
        self.info: dict[str, InfoFoto] = {}   # metadados lidos em segundo plano (largura/altura orientadas etc.)
        self.miniaturas: dict[str, Path] = {}  # JPEG de miniatura no cache, por id de foto (preenchido em segundo plano)
        self.erros: dict[str, str] = {}        # mensagem amigável das fotos que não abriram, por id de foto
        self._modificado = False
        self.comparando = False               # antes/depois: mostrar a foto sem ajustes (não vai para o arquivo)
        self.visiveis: list[str] = []          # ids das fotos visíveis na grade, na ordem dela (a grade publica)

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
        self.miniaturas.clear()
        self.erros.clear()
        self.atual = None
        self.fotos_mudaram.emit()
        self.pastas_mudaram.emit()
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
            self.miniaturas.pop(foto_id, None)
            self.erros.pop(foto_id, None)
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

    def definir_visiveis(self, ids: list[str]) -> None:
        """A grade publica as fotos visíveis (filtro aplicado), na ordem da tela; quem navega usa ``vizinha``."""
        self.visiveis = list(ids)

    def vizinha(self, passo: int) -> Foto | None:
        """A foto ``passo`` posições depois (negativo: antes) da atual entre as visíveis; None fora da lista.

        Sem foto atual (ou atual fora do filtro), ``passo > 0`` dá a primeira visível e ``passo < 0`` a última.
        """
        if not self.visiveis or passo == 0:
            return None
        try:
            i = self.visiveis.index(self.atual.id) if self.atual is not None else -1
        except ValueError:
            i = -1
        j = (0 if passo > 0 else len(self.visiveis) - 1) if i < 0 else i + passo
        return self.por_id(self.visiveis[j]) if 0 <= j < len(self.visiveis) else None

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

    def definir_miniatura(self, foto_id: str, caminho: Path) -> None:
        """Miniatura pronta no cache (a grade mostra)."""
        if self.por_id(foto_id) is None:
            return
        self.miniaturas[foto_id] = Path(caminho)
        self.foto_mudou.emit(foto_id)

    def definir_erro(self, foto_id: str, mensagem: str) -> None:
        """A foto não abriu: a grade a marca com aviso e mostra a mensagem no balão."""
        if self.por_id(foto_id) is None:
            return
        self.erros[foto_id] = mensagem
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

    def alterar_pastas(self) -> None:
        """Avisa que ``trabalho.pastas`` mudou (criar, renomear, cor, tamanho, cópias, apagar uma pasta).

        Quem mexe nas pastas chama isto (as impressões das fotos afetadas avisam por ``alterar``, de preferência
        tudo dentro de um ``lote``). Entra no desfazer/refazer (#5).
        """
        self.pastas_mudaram.emit()
        self.pedido_mudou.emit()
        self.marcar_modificado()

    @contextmanager
    def lote(self, texto: str = "") -> Iterator[None]:
        """Agrupa várias mudanças (em uma ou várias fotos) num passo só do desfazer/refazer.

        ``with estado.lote(_("Aplicar 15x21")): ...`` — quem mexe em várias fotos de uma vez usa isto. Os lotes podem
        ser aninhados (vale o de fora). O desfazer/refazer (#5) é ligado aqui; sem ele, só executa o bloco.
        """
        yield

    def definir_comparando(self, sim: bool) -> None:
        """Liga/desliga o antes/depois (o editor mostra a foto sem ajustes, com o mesmo recorte)."""
        if sim != self.comparando:
            self.comparando = sim
            self.comparando_mudou.emit(sim)

    def marcar_modificado(self, sim: bool = True) -> None:
        if sim != self._modificado:
            self._modificado = sim
            self.modificado_mudou.emit(sim)

    # ---- pastas de tamanho (#32)
    # Invariantes: o id de uma pasta nunca muda; cada foto tem no máximo UMA impressão por pasta; a impressão de pasta
    # tem sempre o tamanho (e o papel/preço do personalizado) da pasta. Cópias, orientação, modo e recorte continuam
    # por foto. Toda operação roda num ``lote`` (um passo do desfazer), avisa as fotos afetadas com
    # ``alterar(foto, pedido=True)`` e, se a pasta mudou, ``alterar_pastas()``.
    # Impressões de uma foto desmarcada ficam guardadas (como em ``selecionar``): a foto continua "na pasta"
    # (``fotos_da_pasta`` a inclui), mas não vai para o orçamento nem para a exportação até ser marcada de novo.

    def pasta_por_id(self, pasta_id: str | None) -> Pasta | None:
        """A pasta com esse id (None para None, para um id desconhecido ou para uma impressão avulsa)."""
        if pasta_id is None:
            return None
        return next((p for p in self.trabalho.pastas if p.id == pasta_id), None)

    def impressao_da_pasta(self, foto: Foto, pasta: Pasta) -> Impressao | None:
        """A impressão da foto que pertence à pasta (None se a foto não está nela)."""
        return next((i for i in foto.impressoes if i.pasta == pasta.id), None)

    def fotos_da_pasta(self, pasta: Pasta) -> list[Foto]:
        """Fotos que estão na pasta (têm uma impressão dela), na ordem do trabalho; inclui as desmarcadas."""
        return [f for f in self.trabalho.fotos if any(i.pasta == pasta.id for i in f.impressoes)]

    def pastas_da_foto(self, foto: Foto) -> list[Pasta]:
        """Pastas em que a foto está, na ordem de ``trabalho.pastas`` (a da tela)."""
        ids = {i.pasta for i in foto.impressoes if i.pasta is not None}
        return [p for p in self.trabalho.pastas if p.id in ids]

    def criar_pasta(self, nome: str, tamanho: str | None = None, cor: str | None = None, copias: int = 1,
                    papel_mm: tuple[float, float] | None = None, preco_centavos: int | None = None) -> Pasta:
        """Cria uma pasta de tamanho no fim da lista e a devolve (ainda vazia).

        ``tamanho``: id de ``tamanhos.TAMANHOS`` (padrão: o tamanho padrão do trabalho) ou ``"personalizado"`` com
        ``papel_mm`` (e, opcional, ``preco_centavos``). ``cor``: chave de ``tema.CORES_PASTA`` (padrão: a próxima
        livre da paleta). ``copias``: cópias das impressões novas da pasta (1..999). O id é novo, único e nunca muda.
        Nome vazio levanta ``ValueError``; tamanho desconhecido, ``KeyError``; medida inválida, ``ValueError``.
        """
        nome = _nome_valido(nome)
        tamanho = self.trabalho.tamanho_padrao if tamanho is None else tamanho
        papel, preco = _papel_valido(tamanho, papel_mm, preco_centavos)
        if cor is None:
            cor = tema.proxima_cor_pasta(p.cor for p in self.trabalho.pastas)
        pasta = Pasta(id=self._novo_id_pasta(), nome=nome, cor=_cor_valida(cor), tamanho=tamanho,
                      copias=_copias_validas(copias), papel_mm=papel, preco_centavos=preco)
        with self.lote(_("Nova pasta")):
            self.trabalho.pastas.append(pasta)
            self.alterar_pastas()
        return pasta

    def alterar_pasta(self, pasta: Pasta, *, nome: object = _MANTER, cor: object = _MANTER,
                      tamanho: object = _MANTER, copias: object = _MANTER, papel_mm: object = _MANTER,
                      preco_centavos: object = _MANTER) -> None:
        """Muda um ou mais campos da pasta (os que não forem passados ficam como estão).

        - ``tamanho`` (e ``papel_mm``/``preco_centavos`` do personalizado): todas as impressões da pasta passam ao
          tamanho novo; o recorte automático é refeito e o manual é reencaixado na proporção nova (continua manual).
          Trocar para um tamanho da tabela zera papel e preço; para ``"personalizado"`` precisa de ``papel_mm``
          (ou do que a pasta já tinha).
        - ``copias``: é o padrão das impressões NOVAS; as impressões da pasta que ainda tinham as cópias antigas da
          pasta (ninguém mexeu nelas) passam às novas, as que a pessoa mudou ficam como estão.
        - ``nome`` e ``cor`` só mudam a pasta.
        Valida como ``criar_pasta``. Sem mudança de fato, não faz nada (nem sinal).
        """
        if pasta not in self.trabalho.pastas:
            raise ValueError("pasta fora do trabalho")
        novo_nome = pasta.nome if nome is _MANTER else _nome_valido(nome)  # type: ignore[arg-type]
        nova_cor = pasta.cor if cor is _MANTER else _cor_valida(cor)  # type: ignore[arg-type]
        novas_copias = pasta.copias if copias is _MANTER else _copias_validas(copias)  # type: ignore[arg-type]
        novo_tam = pasta.tamanho if tamanho is _MANTER else tamanho
        if novo_tam == tamanhos.PERSONALIZADO:
            papel_pedido = pasta.papel_mm if papel_mm is _MANTER else papel_mm
            preco_pedido = pasta.preco_centavos if preco_centavos is _MANTER else preco_centavos
        else:
            papel_pedido, preco_pedido = None, None
        novo_papel, novo_preco = _papel_valido(novo_tam, papel_pedido, preco_pedido)  # type: ignore[arg-type]
        mudou_papel = (novo_tam, novo_papel) != (pasta.tamanho, pasta.papel_mm)
        antes = (pasta.nome, pasta.cor, pasta.copias, pasta.tamanho, pasta.papel_mm, pasta.preco_centavos)
        depois = (novo_nome, nova_cor, novas_copias, novo_tam, novo_papel, novo_preco)
        if antes == depois:
            return
        with self.lote(_("Alterar a pasta")):
            copias_antigas = pasta.copias
            pasta.nome, pasta.cor, pasta.copias = novo_nome, nova_cor, novas_copias
            pasta.tamanho, pasta.papel_mm, pasta.preco_centavos = novo_tam, novo_papel, novo_preco
            for foto in self.fotos_da_pasta(pasta):
                imp = self.impressao_da_pasta(foto, pasta)
                assert imp is not None
                mexeu = imp.copias == copias_antigas and novas_copias != copias_antigas
                if mexeu:
                    imp.copias = novas_copias
                if (imp.tamanho, imp.papel_mm, imp.preco_centavos) != (novo_tam, novo_papel, novo_preco):
                    imp.tamanho, imp.papel_mm, imp.preco_centavos = novo_tam, novo_papel, novo_preco
                    mexeu = True
                if mudou_papel:
                    self._reenquadrar(foto, imp)
                if mexeu:
                    self.alterar(foto, pedido=True)
            self.alterar_pastas()

    def mover_pasta(self, pasta: Pasta, indice: int) -> None:
        """Muda a posição da pasta na lista (a ordem da tela); ``indice`` é limitado à lista."""
        if pasta not in self.trabalho.pastas:
            raise ValueError("pasta fora do trabalho")
        lista = self.trabalho.pastas
        indice = max(0, min(len(lista) - 1, int(indice)))
        if lista.index(pasta) == indice:
            return
        with self.lote(_("Mover a pasta")):
            lista.remove(pasta)
            lista.insert(indice, pasta)
            self.alterar_pastas()

    def apagar_pasta(self, pasta: Pasta) -> None:
        """Apaga a pasta: tira das fotos só as impressões dela (as fotos e as outras impressões ficam no trabalho).

        A foto que fica sem nenhuma impressão deixa de estar marcada.
        """
        if pasta not in self.trabalho.pastas:
            return
        with self.lote(_("Apagar a pasta")):
            for foto in self.fotos_da_pasta(pasta):
                self._tirar_impressao(foto, pasta)
                self.alterar(foto, pedido=True)
            self.trabalho.pastas.remove(pasta)
            self.alterar_pastas()

    def adicionar_a_pasta(self, fotos: list[Foto], pasta: Pasta) -> list[Foto]:
        """Põe as fotos na pasta e as marca para revelação. Devolve as fotos que mudaram.

        Cada foto ganha uma impressão com ``pasta=<id>`` no tamanho e nas cópias da pasta, com o recorte sugerido
        (refeito quando os metadados chegarem, se ainda não chegaram). Casos:
        - a foto já está na pasta: não ganha outra impressão (só volta a ficar marcada, se estava desmarcada);
        - a foto estava desmarcada: as impressões avulsas guardadas dela são descartadas (ela entra marcada SÓ no
          tamanho da pasta; as de outras pastas voltam com ela);
        - a foto marcada já tem uma impressão avulsa no mesmo tamanho (e papel) da pasta: essa impressão passa a ser
          a da pasta (mantém cópias e recorte), para não revelar a mesma foto duas vezes sem querer.
        """
        if pasta not in self.trabalho.pastas:
            raise ValueError("pasta fora do trabalho")
        mudaram: list[Foto] = []
        with self.lote(_("Adicionar à pasta")):
            for foto in _sem_repetir(fotos):
                mudou = False
                if not foto.selecionada:
                    avulsas = [i for i in foto.impressoes if i.pasta is None]
                    if avulsas:
                        foto.impressoes = [i for i in foto.impressoes if i.pasta is not None]
                        mudou = True
                    foto.selecionada = True
                    mudou = True
                if self.impressao_da_pasta(foto, pasta) is None:
                    igual = next((i for i in foto.impressoes if i.pasta is None and _mesmo_papel(i, pasta)), None)
                    if igual is not None:
                        igual.pasta, igual.papel_mm = pasta.id, pasta.papel_mm
                        igual.preco_centavos = pasta.preco_centavos
                    else:
                        foto.impressoes.append(Impressao(tamanho=pasta.tamanho, copias=pasta.copias,
                                                         papel_mm=pasta.papel_mm,
                                                         preco_centavos=pasta.preco_centavos, pasta=pasta.id))
                        self.refazer_recortes_auto(foto)
                    mudou = True
                if mudou:
                    self._ajustar_indice(foto)
                    self.alterar(foto, pedido=True)
                    mudaram.append(foto)
            if mudaram:
                self.pastas_mudaram.emit()   # contagem de fotos da pasta
        return mudaram

    def tirar_da_pasta(self, fotos: list[Foto], pasta: Pasta) -> list[Foto]:
        """Tira as fotos da pasta (remove a impressão dela). Devolve as fotos que mudaram.

        As outras impressões ficam; a foto que fica sem nenhuma impressão deixa de estar marcada.
        """
        mudaram: list[Foto] = []
        with self.lote(_("Tirar da pasta")):
            for foto in _sem_repetir(fotos):
                if self._tirar_impressao(foto, pasta):
                    self.alterar(foto, pedido=True)
                    mudaram.append(foto)
            if mudaram:
                self.pastas_mudaram.emit()   # contagem de fotos da pasta
        return mudaram

    # -- auxiliares das pastas
    def _novo_id_pasta(self) -> str:
        usados = {p.id for p in self.trabalho.pastas}
        while True:
            pid = "p" + uuid.uuid4().hex[:11]
            if pid not in usados:
                return pid

    def _tirar_impressao(self, foto: Foto, pasta: Pasta) -> bool:
        """Remove a impressão da pasta (sem sinais); sem impressão sobrando, desmarca. Verdadeiro se mudou algo."""
        antes = len(foto.impressoes)
        foto.impressoes = [i for i in foto.impressoes if i.pasta != pasta.id]
        if len(foto.impressoes) == antes:
            return False
        if not foto.impressoes:
            foto.selecionada = False
        self._ajustar_indice(foto)
        return True

    def _ajustar_indice(self, foto: Foto) -> None:
        """Mantém ``indice_impressao`` dentro da lista quando as impressões da foto atual mudam."""
        if foto is self.atual:
            indice = max(0, min(self.indice_impressao, len(foto.impressoes) - 1))
            self.indice_impressao = indice
            self.impressao_mudou.emit(indice)

    def _reenquadrar(self, foto: Foto, imp: Impressao) -> None:
        """Depois de trocar o papel de ``imp``: refaz o recorte automático ou reencaixa o manual (sem sinais).

        Mesmo comportamento de ``painel_impressoes.refazer_enquadramento``; sem metadados, o automático é refeito
        quando eles chegarem (``definir_info``) e o manual fica como está.
        """
        if imp.recorte.origem != "manual":
            self.refazer_recortes_auto(foto)
            return
        info = self.info.get(foto.id)
        if info is None:
            return
        w, h = (info.altura, info.largura) if int(imp.recorte.giro) % 2 else (info.largura, info.altura)
        orient = tamanhos.orientacao_efetiva(imp.orientacao, w, h)
        imp.recorte = enquadramento.reencaixar(imp.recorte, w, h, tamanhos.proporcao(imp.tamanho, orient, imp.papel_mm))


def _sem_repetir(fotos: list[Foto]) -> list[Foto]:
    vistos: set[int] = set()
    return [f for f in fotos if not (id(f) in vistos or vistos.add(id(f)))]


def _mesmo_papel(imp: Impressao, pasta: Pasta) -> bool:
    """A impressão tem o mesmo papel da pasta (mesmo tamanho; no personalizado, as mesmas medidas)?"""
    if imp.tamanho != pasta.tamanho:
        return False
    if pasta.tamanho != tamanhos.PERSONALIZADO:
        return True
    return imp.papel_mm is not None and pasta.papel_mm is not None and sorted(imp.papel_mm) == sorted(pasta.papel_mm)


def _nome_valido(nome: str) -> str:
    nome = str(nome).strip()
    if not nome:
        raise ValueError(_("A pasta precisa de um nome."))
    return nome


def _cor_valida(cor: str) -> str:
    if not isinstance(cor, str) or not cor:
        raise ValueError("cor de pasta vazia")
    return cor


def _copias_validas(copias: int) -> int:
    return max(COPIAS_MIN, min(COPIAS_MAX, int(copias)))


def _papel_valido(tamanho: str, papel_mm: tuple[float, float] | None,
                  preco_centavos: int | None) -> tuple[tuple[float, float] | None, int | None]:
    """(papel_mm, preco_centavos) da pasta: só no personalizado (validados); num tamanho da tabela, (None, None)."""
    if tamanho != tamanhos.PERSONALIZADO:
        tamanhos.obter(tamanho)   # KeyError em id desconhecido
        return None, None
    menor, maior = tamanhos.papel_mm(tamanho, papel_mm)   # ValueError sem medida ou fora dos limites
    if preco_centavos is not None and (isinstance(preco_centavos, bool) or not isinstance(preco_centavos, int)
                                       or preco_centavos < 0):
        raise ValueError("preço em centavos inválido")
    return (menor, maior), preco_centavos


def _chave_caminho(caminho: Path) -> str:
    try:
        return str(Path(caminho).resolve()).casefold()
    except OSError:
        return str(caminho).casefold()
