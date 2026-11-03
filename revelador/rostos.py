"""Detecção de rostos com o YuNet (``cv2.FaceDetectorYN``), só para sugerir o enquadramento inicial.

O modelo ``face_detection_yunet_2023mar.onnx`` (opencv_zoo, licença MIT, ~230 KB) vai dentro do pacote, em
``revelador/data/modelos/`` com a licença ao lado; o SHA-256 dele é conferido por teste. Nada é baixado e nada sai do
computador: a detecção devolve só retângulos, pontos dos olhos e confiança (regra 15 do ``AGENTS.md``).

``detectar(rgb)`` recebe a imagem ORIENTADA (EXIF aplicado, sem giro de 90°) e devolve ``projeto.Rosto`` em
coordenadas normalizadas (0..1). Nunca lança exceção para quem chama: qualquer falha vira lista vazia e um registro
no ``logging`` (a detecção é só uma sugestão; nunca pode impedir importar ou exportar).

O ``cv2.FaceDetectorYN`` não é seguro entre threads: cada thread tem o seu (``threading.local``). O modelo é lido
para a memória uma vez e passado como buffer, o que também evita o problema do OpenCV com caminhos não ASCII no
Windows (pasta de usuário com acento).
"""

from __future__ import annotations

import hashlib
import logging
import threading
from pathlib import Path

import numpy as np

from .projeto import Rosto

log = logging.getLogger(__name__)

PASTA_MODELOS = Path(__file__).parent / "data" / "modelos"
MODELO = PASTA_MODELOS / "face_detection_yunet_2023mar.onnx"
SHA256_MODELO = "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"

LADO_MAXIMO = 1280          # a detecção roda sobre a imagem reduzida a este lado maior (px)
LIMIAR = 0.6                # confiança mínima (score_threshold)
NMS = 0.3                   # supressão de caixas sobrepostas (nms_threshold)
TOP_K = 100
LARGURA_MINIMA = 0.015      # descarta rostos mais estreitos que 1,5% do lado menor da imagem

_bytes_modelo: np.ndarray | None = None
_trava_modelo = threading.Lock()
_local = threading.local()


def sha256_modelo(caminho: Path = MODELO) -> str:
    """SHA-256 (hex, minúsculo) do arquivo do modelo."""
    return hashlib.sha256(caminho.read_bytes()).hexdigest()


def _modelo() -> np.ndarray:
    """Conteúdo do modelo em memória (lido uma vez; o buffer é só lido depois, então pode ser compartilhado)."""
    global _bytes_modelo
    with _trava_modelo:
        if _bytes_modelo is None:
            _bytes_modelo = np.frombuffer(MODELO.read_bytes(), np.uint8)
        return _bytes_modelo


def criar_detector(largura: int, altura: int):
    """Cria um ``cv2.FaceDetectorYN`` com o modelo empacotado (também usado pelo diagnóstico)."""
    import cv2

    return cv2.FaceDetectorYN.create("onnx", _modelo(), np.zeros(0, np.uint8), (int(largura), int(altura)),
                                     LIMIAR, NMS, TOP_K)


def _detector_da_thread(largura: int, altura: int):
    det = getattr(_local, "detector", None)
    if det is None:
        det = criar_detector(largura, altura)
        _local.detector = det
    else:
        det.setInputSize((int(largura), int(altura)))
    return det


def _para_bgr_uint8(rgb: np.ndarray) -> np.ndarray:
    """Converte RGB (uint8 ou float 0..1; aceita cinza e RGBA) para BGR uint8 contíguo, como o OpenCV quer."""
    a = np.asarray(rgb)
    if a.ndim == 2:
        a = np.repeat(a[:, :, None], 3, axis=2)
    if a.ndim != 3 or a.shape[2] < 3:
        raise ValueError(f"imagem com formato inesperado: {a.shape}")
    a = a[:, :, :3]
    if a.dtype != np.uint8:
        a = np.clip(np.rint(a.astype(np.float32) * 255.0), 0, 255).astype(np.uint8)
    return np.ascontiguousarray(a[:, :, ::-1])


def detectar(rgb: np.ndarray) -> list[Rosto]:
    """Rostos da imagem, do mais importante (área × confiança) para o menos. Falha = lista vazia."""
    try:
        return _detectar(rgb)
    except Exception:  # noqa: BLE001 - a detecção é só sugestão; nunca derruba quem chama
        log.exception("falha ao detectar rostos")
        return []


def _detectar(rgb: np.ndarray) -> list[Rosto]:
    import cv2

    bgr = _para_bgr_uint8(rgb)
    alt, larg = bgr.shape[:2]
    if alt < 2 or larg < 2:
        return []
    escala = min(1.0, LADO_MAXIMO / max(alt, larg))
    if escala < 1.0:
        larg, alt = max(1, round(larg * escala)), max(1, round(alt * escala))
        bgr = cv2.resize(bgr, (larg, alt), interpolation=cv2.INTER_AREA)

    _, faces = _detector_da_thread(larg, alt).detect(bgr)
    if faces is None:
        return []

    minimo = LARGURA_MINIMA * min(larg, alt)
    rostos: list[Rosto] = []
    for f in faces:
        x, y, w, h = (float(v) for v in f[:4])
        x0, y0 = max(0.0, x), max(0.0, y)
        x1, y1 = min(float(larg), x + w), min(float(alt), y + h)
        if x1 - x0 < minimo or y1 <= y0:
            continue
        olhos = ((float(f[4]) / larg, float(f[5]) / alt), (float(f[6]) / larg, float(f[7]) / alt))
        rostos.append(Rosto(x=x0 / larg, y=y0 / alt, w=(x1 - x0) / larg, h=(y1 - y0) / alt,
                            olhos=olhos, confianca=float(f[14])))
    rostos.sort(key=lambda r: r.w * r.h * r.confianca, reverse=True)
    return rostos
