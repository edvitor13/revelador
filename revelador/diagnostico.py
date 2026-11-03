"""Confere se as dependências nativas funcionam de verdade (numpy, Pillow, pillow-heif, OpenCV, rostos e Qt).

Usado pelo CI no executável empacotado (``Revelador.exe --diagnostico saida.json``): o PyInstaller pode deixar
uma DLL de fora sem erro nenhum na hora de gerar, e o problema só apareceria quando a pessoa abrisse uma foto HEIC
ou a detecção de rostos rodasse. Por isso cada item faz uma operação real (codificar e decodificar, redimensionar),
não só ``import``.

Resultado (JSON)::

    {"app": "Revelador", "versao": "0.1.0", "python": "3.15.0", "empacotado": true, "ok": true,
     "itens": {"numpy": {"ok": true, "versao": "2.5.4"}, "pillow-heif": {"ok": false, "erro": "..."}, ...}}
"""

from __future__ import annotations

import io
import json
import platform
import sys
import traceback
from pathlib import Path
from typing import Callable

from . import APP_NAME, __version__

LARGURA, ALTURA = 64, 48


def _numpy() -> str:
    import numpy as np

    a = np.linspace(0.0, 1.0, LARGURA * ALTURA, dtype=np.float32).reshape(ALTURA, LARGURA)
    if abs(float(a.mean()) - 0.5) > 1e-5:
        raise RuntimeError("o numpy calculou a média errada")
    return np.__version__


def _pillow() -> str:
    import PIL
    from PIL import Image, ImageCms

    srgb = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    buf = io.BytesIO()
    Image.new("RGB", (LARGURA, ALTURA), (200, 120, 40)).save(
        buf, "JPEG", quality=95, subsampling=0, dpi=(300, 300), icc_profile=srgb)
    volta = Image.open(io.BytesIO(buf.getvalue()))
    volta.load()
    if volta.size != (LARGURA, ALTURA):
        raise RuntimeError(f"JPEG decodificado com tamanho errado: {volta.size}")
    if not volta.info.get("icc_profile"):
        raise RuntimeError("o JPEG saiu sem o perfil sRGB")
    if round(float(volta.info.get("dpi", (0, 0))[0])) != 300:
        raise RuntimeError(f"o JPEG saiu sem os 300 dpi: {volta.info.get('dpi')}")
    # Conversão de cor pelo LittleCMS (a mesma da importação de fotos com perfil).
    lab = ImageCms.createProfile("LAB")
    ImageCms.profileToProfile(volta, ImageCms.ImageCmsProfile(io.BytesIO(srgb)), lab, outputMode="LAB")
    return PIL.__version__


def _pillow_heif() -> str:
    import pillow_heif
    from PIL import Image

    pillow_heif.register_heif_opener()
    buf = io.BytesIO()
    Image.new("RGB", (LARGURA, ALTURA), (40, 120, 200)).save(buf, "HEIF", quality=90)
    volta = Image.open(io.BytesIO(buf.getvalue()))
    volta.load()
    if volta.size != (LARGURA, ALTURA):
        raise RuntimeError(f"HEIF decodificado com tamanho errado: {volta.size}")
    return pillow_heif.__version__


def _opencv() -> str:
    import cv2
    import numpy as np

    a = np.zeros((ALTURA, LARGURA, 3), np.uint8)
    b = cv2.resize(a, (LARGURA // 2, ALTURA // 2), interpolation=cv2.INTER_AREA)
    if b.shape != (ALTURA // 2, LARGURA // 2, 3):
        raise RuntimeError(f"cv2.resize devolveu outro tamanho: {b.shape}")
    if not hasattr(cv2, "FaceDetectorYN"):
        raise RuntimeError("o OpenCV não tem cv2.FaceDetectorYN (detecção de rostos)")
    return cv2.__version__


def _rostos() -> str:
    """Carrega o YuNet empacotado e roda o ``cv2.FaceDetectorYN`` (prova que o modelo e o DNN do OpenCV estão no
    executável). A imagem é sintética: não precisa achar rosto, só não pode falhar."""
    import numpy as np

    from . import rostos

    if not rostos.MODELO.is_file():
        raise RuntimeError(f"modelo de rostos ausente: {rostos.MODELO}")
    if rostos.sha256_modelo() != rostos.SHA256_MODELO:
        raise RuntimeError("modelo de rostos com SHA-256 diferente do esperado")
    a = np.zeros((ALTURA * 2, LARGURA * 2, 3), np.uint8)
    a[ALTURA // 2:ALTURA * 3 // 2, LARGURA // 2:LARGURA * 3 // 2] = (200, 170, 150)
    _, faces = rostos.criar_detector(LARGURA * 2, ALTURA * 2).detect(a)
    return f"{rostos.MODELO.name} ({0 if faces is None else len(faces)} rostos na imagem de teste)"


def _qt() -> str:
    import PySide6
    from PySide6.QtGui import QColor, QImage

    img = QImage(LARGURA, ALTURA, QImage.Format.Format_RGB32)
    img.fill(QColor(51, 102, 153))
    if img.pixelColor(0, 0).blue() != 153:
        raise RuntimeError("QImage com a cor errada")
    return PySide6.__version__


ITENS: dict[str, Callable[[], str]] = {
    "numpy": _numpy,
    "pillow": _pillow,
    "pillow-heif": _pillow_heif,
    "opencv": _opencv,
    "rostos": _rostos,
    "qt": _qt,
}


def executar() -> dict:
    """Roda todas as conferências e devolve o resultado (nunca lança exceção)."""
    itens: dict[str, dict] = {}
    for nome, func in ITENS.items():
        try:
            itens[nome] = {"ok": True, "versao": func()}
        except BaseException as exc:  # noqa: BLE001 - uma DLL ausente pode virar qualquer erro
            itens[nome] = {"ok": False, "erro": f"{type(exc).__name__}: {exc}",
                           "detalhes": traceback.format_exc(limit=6)}
    return {
        "app": APP_NAME,
        "versao": __version__,
        "python": platform.python_version(),
        "empacotado": bool(getattr(sys, "frozen", False)),
        "ok": all(i["ok"] for i in itens.values()),
        "itens": itens,
    }


def main(destino: Path | None = None) -> int:
    """Grava o resultado em ``destino`` (ou mostra no terminal) e devolve 0 se tudo funcionou."""
    resultado = executar()
    texto = json.dumps(resultado, ensure_ascii=False, indent=2) + "\n"
    if destino is not None:
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(texto, encoding="utf-8")
    elif sys.stdout is not None:  # o executável sem console não tem stdout
        sys.stdout.write(texto)
    return 0 if resultado["ok"] else 1
