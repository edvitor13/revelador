"""Trabalhadores do editor: carregar o proxy e calcular a prévia pela receita, fora da thread principal.

Cada trabalho é um ``QRunnable`` que devolve o resultado por sinal do objeto ``Sinais`` (que mora na thread
principal); quem recebe confere o número da geração e descarta o que ficou velho. Nada daqui toca em widgets.
"""

from __future__ import annotations

import copy
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, QRunnable, Signal
from PySide6.QtGui import QImage

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
