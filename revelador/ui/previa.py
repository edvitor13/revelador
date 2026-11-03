"""Trabalhadores do editor: carregar o proxy e calcular a prévia pela receita, fora da thread principal.

Cada trabalho é um ``QRunnable`` que devolve o resultado por sinal do objeto ``Sinais`` (que mora na thread
principal); quem recebe confere o número da geração e descarta o que ficou velho. Nada daqui toca em widgets.
"""

from __future__ import annotations

import copy
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import QObject, QRunnable, Signal
from PySide6.QtGui import QImage

from .. import ajustes as _ajustes
from .. import receita
from ..projeto import Impressao


def para_qimage(rgb8: np.ndarray) -> QImage:
    """``uint8`` H×W×3 → ``QImage`` (cópia independente do array). Seguro fora da thread principal."""
    rgb8 = np.ascontiguousarray(rgb8)
    h, w = rgb8.shape[:2]
    return QImage(rgb8.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()


class Sinais(QObject):
    """Canal de resultados dos trabalhadores (criado na thread principal)."""

    proxy_pronto = Signal(int, str, object)    # geração, caminho, array float32 do proxy (somente leitura)
    proxy_erro = Signal(int, str, str)         # geração, caminho, mensagem para a pessoa
    previa_pronta = Signal(int, object)        # geração, QImage
    previa_erro = Signal(int, str)             # geração, mensagem
    ajustada_pronta = Signal(int, bool, object)  # geração, versão final (não reduzida)?, QImage


class CarregarProxy(QRunnable):
    """Lê o proxy da foto (``imagem.proxy``, com cache) sem travar a interface."""

    def __init__(self, sinais: Sinais, geracao: int, caminho: Path) -> None:
        super().__init__()
        self.sinais, self.geracao, self.caminho = sinais, geracao, Path(caminho)

    def run(self) -> None:
        try:
            proxy = receita.carregar_fonte(self.caminho, "proxy")
        except Exception as e:  # noqa: BLE001 - ErroImagem já traz a mensagem amigável; o resto vira texto genérico
            self.sinais.proxy_erro.emit(self.geracao, str(self.caminho), str(e))
            return
        self.sinais.proxy_pronto.emit(self.geracao, str(self.caminho), proxy)


class RenderizarPrevia(QRunnable):
    """Prévia pela receita única, no tamanho do visor. Recebe cópias do modelo: a thread principal pode seguir mexendo."""

    def __init__(self, sinais: Sinais, geracao: int, fonte: np.ndarray, impressao: Impressao,
                 ajustes: dict | None, destino: tuple[int, int]) -> None:
        super().__init__()
        self.sinais, self.geracao, self.fonte = sinais, geracao, fonte
        self.impressao = copy.deepcopy(impressao)
        self.ajustes = dict(ajustes or {})
        self.destino = (int(destino[0]), int(destino[1]))

    def run(self) -> None:
        try:
            saida = receita.renderizar(self.fonte, self.impressao, self.ajustes, self.destino)
            imagem = para_qimage(receita.para_uint8(saida))
        except Exception as e:  # noqa: BLE001 - a prévia falhar não pode derrubar o app
            self.sinais.previa_erro.emit(self.geracao, str(e))
            return
        self.sinais.previa_pronta.emit(self.geracao, imagem)


class AjustarImagem(QRunnable):
    """A foto inteira (já girada) com os ajustes, para a moldura do editor. ``max_lado`` reduz (arrasto de controle).

    ``escala_mm_px`` é a do papel para a imagem inteira na largura de ``fonte`` girada (a nitidez é em mm de papel);
    o trabalhador a reescala se reduzir a imagem.
    """

    def __init__(self, sinais: Sinais, geracao: int, fonte: np.ndarray, giro: int, valores: dict,
                 escala_mm_px: float | None, max_lado: int | None, final: bool) -> None:
        super().__init__()
        self.sinais, self.geracao, self.fonte, self.giro = sinais, geracao, fonte, giro
        self.valores = dict(valores)
        self.escala, self.max_lado, self.final = escala_mm_px, max_lado, final

    def run(self) -> None:
        try:
            img = receita.girar(self.fonte, self.giro)
            escala = self.escala
            maior = max(img.shape[:2])
            if self.max_lado and maior > self.max_lado:
                k = self.max_lado / maior
                w, h = max(1, round(img.shape[1] * k)), max(1, round(img.shape[0] * k))
                img = cv2.resize(np.ascontiguousarray(img), (w, h), interpolation=cv2.INTER_AREA)
                escala = None if escala is None else escala * k
            saida = _ajustes.aplicar(img, self.valores, escala)
            imagem = para_qimage(receita.para_uint8(saida))
        except Exception:  # noqa: BLE001 - a moldura segue mostrando a foto sem ajustes
            return
        self.sinais.ajustada_pronta.emit(self.geracao, self.final, imagem)
