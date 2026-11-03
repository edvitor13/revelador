"""Gera os ícones do app a partir de ``assets/logo.svg``.

Saída: ``assets/logo-256.png`` (ícone da janela), ``assets/logo-512.png`` (documentação) e ``assets/logo.ico``
(executável e instalador; 16 a 256 px, cada tamanho desenhado direto do SVG).

Uso:  python tools/gerar_icone.py
"""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
TAMANHOS_ICO = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def renderizar(svg: Path, lado: int):
    """SVG → imagem RGBA do Pillow com ``lado`` × ``lado`` px (pelo QtSvg)."""
    from PIL import Image
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    img = QImage(lado, lado, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    pintor = QPainter(img)
    pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
    QSvgRenderer(str(svg)).render(pintor)
    pintor.end()
    dados = QByteArray()
    buf = QBuffer(dados)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    buf.close()
    return Image.open(io.BytesIO(bytes(dados))).convert("RGBA")


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QGuiApplication

    app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])  # noqa: F841
    svg = ASSETS / "logo.svg"
    for lado in (256, 512):
        renderizar(svg, lado).save(ASSETS / f"logo-{lado}.png", optimize=True)
    imagens = [renderizar(svg, lado) for lado in TAMANHOS_ICO]
    imagens[-1].save(ASSETS / "logo.ico", format="ICO", sizes=[(t, t) for t in TAMANHOS_ICO],
                     append_images=imagens[:-1])
    for nome in ("logo-256.png", "logo-512.png", "logo.ico"):
        print(f"{ASSETS / nome} ({(ASSETS / nome).stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
