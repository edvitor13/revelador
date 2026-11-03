"""Ícones vetoriais desenhados com QPainter (sem arquivos externos), numa grade de 24 unidades.

``icone(nome, cor, tamanho)`` devolve um ``QIcon`` nítido em telas comuns e em telas de alta densidade (1x e 2x).
Traço de 1,8 unidade com pontas e junções arredondadas; formas cheias só onde o ícone pede (pontos, setas).
``NOMES`` lista os ícones disponíveis; ``icone_app()`` devolve o ícone do programa (``assets/logo-*.png``) e
``bolinha(cor)`` um círculo cheio (a cor de uma pasta de tamanho, #32, em menus e rótulos).
"""

from __future__ import annotations

import math
from functools import lru_cache

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

from . import tema


def _pen(p: QPainter, cor: QColor, largura: float = 1.8) -> None:
    pen = QPen(cor, largura)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)


def _cheio(p: QPainter, cor: QColor) -> None:
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(cor))


def _poli(p: QPainter, pontos: list[tuple[float, float]], fechar: bool = False) -> None:
    pts = [QPointF(x, y) for x, y in pontos]
    if fechar:
        p.drawPolygon(pts)
    else:
        p.drawPolyline(pts)


def _ponta(p: QPainter, ponta: QPointF, direcao: QPointF, tamanho: float = 4.2) -> None:
    """Cabeça de seta aberta (duas hastes de 40° para trás) na `ponta`, apontando para `direcao` (vetor unitário)."""
    for graus in (40, -40):
        r = math.radians(graus)
        dx = direcao.x() * math.cos(r) - direcao.y() * math.sin(r)
        dy = direcao.x() * math.sin(r) + direcao.y() * math.cos(r)
        p.drawLine(ponta, QPointF(ponta.x() - dx * tamanho, ponta.y() - dy * tamanho))


def _seta_giro(p: QPainter, cor: QColor, horario: bool) -> None:
    """Arco de ~290° com ponta de seta: girar à direita (horário) ou à esquerda."""
    p.save()
    if not horario:
        p.translate(24, 0)
        p.scale(-1, 1)
    _pen(p, cor)
    cx, cy, r, ang = 12.0, 12.5, 7.5, 52.0   # `ang`: posição da ponta (graus do Qt, anti-horário a partir de leste)
    caminho = QPainterPath()
    caminho.arcMoveTo(QRectF(cx - r, cy - r, 2 * r, 2 * r), ang + 290)
    caminho.arcTo(QRectF(cx - r, cy - r, 2 * r, 2 * r), ang + 290, -290)
    p.drawPath(caminho)
    a = math.radians(ang)
    ponta = QPointF(cx + r * math.cos(a), cy - r * math.sin(a))
    _ponta(p, ponta, QPointF(math.sin(a), math.cos(a)))
    p.restore()


def desenhar(nome: str, p: QPainter, c: QColor) -> None:
    """Desenha o ícone `nome` na grade 24x24 (o chamador já ajustou a escala)."""
    if nome == "importar":
        _pen(p, c)
        p.drawLine(QPointF(12, 3.5), QPointF(12, 14.5))
        _poli(p, [(7.5, 10), (12, 14.5), (16.5, 10)])
        _poli(p, [(4, 14), (4, 19.5), (20, 19.5), (20, 14)])
    elif nome == "exportar":
        _pen(p, c)
        p.drawLine(QPointF(12, 3.5), QPointF(12, 14.5))
        _poli(p, [(7.5, 8), (12, 3.5), (16.5, 8)])
        _poli(p, [(4, 14), (4, 19.5), (20, 19.5), (20, 14)])
    elif nome == "pasta":
        _pen(p, c)
        _poli(p, [(3.5, 6.5), (9.5, 6.5), (11.5, 8.5), (20.5, 8.5), (20.5, 18.5), (3.5, 18.5)], fechar=True)
    elif nome == "abrir":
        _pen(p, c)
        _poli(p, [(3, 18.5), (3, 5.5), (9, 5.5), (11, 7.5), (18, 7.5), (18, 11)])
        _poli(p, [(3, 18.5), (5.5, 11), (21.5, 11), (19, 18.5), (3, 18.5)])
    elif nome == "salvar":
        _pen(p, c)
        _poli(p, [(5, 4.5), (16, 4.5), (19.5, 8), (19.5, 19.5), (4.5, 19.5), (4.5, 5)])
        p.drawRect(QRectF(8, 13, 8, 6.5))
        _poli(p, [(8.5, 4.5), (8.5, 8.5), (14, 8.5)])
    elif nome == "configuracoes":
        _pen(p, c)
        for y, x in ((6, 15), (12, 8), (18, 13)):
            p.drawLine(QPointF(4, y), QPointF(20, y))
            p.setBrush(QColor(tema.PAINEL))
            p.drawEllipse(QPointF(x, y), 2.4, 2.4)
            p.setBrush(Qt.BrushStyle.NoBrush)
    elif nome == "check":
        _pen(p, c, 2.2)
        _poli(p, [(5, 12.5), (10, 17), (19, 7)])
    elif nome == "mais":
        _pen(p, c, 2.0)
        p.drawLine(QPointF(12, 5), QPointF(12, 19))
        p.drawLine(QPointF(5, 12), QPointF(19, 12))
    elif nome == "fechar":
        _pen(p, c, 2.0)
        p.drawLine(QPointF(6.5, 6.5), QPointF(17.5, 17.5))
        p.drawLine(QPointF(17.5, 6.5), QPointF(6.5, 17.5))
    elif nome == "lixeira":
        _pen(p, c)
        p.drawLine(QPointF(4.5, 7), QPointF(19.5, 7))
        _poli(p, [(9.5, 7), (9.5, 4.5), (14.5, 4.5), (14.5, 7)])
        _poli(p, [(6.5, 7), (7.5, 19.5), (16.5, 19.5), (17.5, 7)])
        p.drawLine(QPointF(10.5, 10.5), QPointF(10.5, 16))
        p.drawLine(QPointF(13.5, 10.5), QPointF(13.5, 16))
    elif nome == "girar_direita":
        _seta_giro(p, c, True)
    elif nome == "girar_esquerda":
        _seta_giro(p, c, False)
    elif nome == "endireitar":
        # Moldura inclinada e a linha do horizonte reta: a foto é alinhada a ela.
        _pen(p, c)
        p.save()
        p.translate(12, 12)
        p.rotate(-12)
        p.drawRoundedRect(QRectF(-8, -5.5, 16, 11), 2, 2)
        p.restore()
        p.drawLine(QPointF(2, 12), QPointF(22, 12))
    elif nome in ("zoom_mais", "zoom_menos"):
        _pen(p, c, 2.0)
        p.drawEllipse(QPointF(10.5, 10.5), 6.5, 6.5)
        p.drawLine(QPointF(15.3, 15.3), QPointF(20.5, 20.5))
        _pen(p, c, 1.8)
        p.drawLine(QPointF(7.5, 10.5), QPointF(13.5, 10.5))
        if nome == "zoom_mais":
            p.drawLine(QPointF(10.5, 7.5), QPointF(10.5, 13.5))
    elif nome == "rosto":
        # Rosto dentro de quatro cantoneiras: a moldura da detecção.
        _pen(p, c, 1.7)
        for sx in (4, 20):
            for sy in (4, 20):
                dx = 3.2 if sx == 4 else -3.2
                dy = 3.2 if sy == 4 else -3.2
                _poli(p, [(sx + dx, sy), (sx, sy), (sx, sy + dy)])
        p.drawEllipse(QPointF(12, 12), 4.7, 4.7)
        _cheio(p, c)
        p.drawEllipse(QPointF(10.3, 11.2), 0.8, 0.8)
        p.drawEllipse(QPointF(13.7, 11.2), 0.8, 0.8)
        _pen(p, c, 1.4)
        arco = QPainterPath()
        arco.arcMoveTo(QRectF(9.6, 9.8, 4.8, 4.6), 210)
        arco.arcTo(QRectF(9.6, 9.8, 4.8, 4.6), 210, 120)
        p.drawPath(arco)
    elif nome == "recorte":
        _pen(p, c)
        _poli(p, [(7, 2.5), (7, 17), (21.5, 17)])
        _poli(p, [(2.5, 7), (17, 7), (17, 21.5)])
    elif nome == "grade":
        _pen(p, c)
        for x in (4, 13.5):
            for y in (4, 13.5):
                p.drawRoundedRect(QRectF(x, y, 6.5, 6.5), 1.6, 1.6)
    elif nome == "filtro":
        _pen(p, c)
        _poli(p, [(4, 5.5), (20, 5.5), (14, 12.5), (14, 19), (10, 17), (10, 12.5)], fechar=True)
    elif nome == "dinheiro":
        _pen(p, c)
        p.drawRoundedRect(QRectF(2.5, 6.5, 19, 11), 2.4, 2.4)
        p.drawEllipse(QPointF(12, 12), 2.7, 2.7)
        _cheio(p, c)
        p.drawEllipse(QPointF(6, 12), 0.9, 0.9)
        p.drawEllipse(QPointF(18, 12), 0.9, 0.9)
    elif nome == "info":
        _pen(p, c)
        p.drawEllipse(QPointF(12, 12), 9, 9)
        p.drawLine(QPointF(12, 11), QPointF(12, 16.5))
        _cheio(p, c)
        p.drawEllipse(QPointF(12, 7.8), 1.15, 1.15)
    elif nome == "aviso":
        _pen(p, c)
        _poli(p, [(12, 3.8), (21, 19.5), (3, 19.5)], fechar=True)
        p.drawLine(QPointF(12, 10), QPointF(12, 14.5))
        _cheio(p, c)
        p.drawEllipse(QPointF(12, 17), 1.05, 1.05)
    elif nome == "chevron":
        _pen(p, c, 2.0)
        _poli(p, [(8, 9.5), (12, 14), (16, 9.5)])
    elif nome == "reset":
        _pen(p, c)
        caminho = QPainterPath()
        caminho.arcMoveTo(QRectF(5, 5, 14, 14), 120)
        caminho.arcTo(QRectF(5, 5, 14, 14), 120, 290)
        p.drawPath(caminho)
        _poli(p, [(5.2, 4.8), (8.2, 7.9), (4.4, 9.6)])
    elif nome == "copiar":
        _pen(p, c)
        p.drawRoundedRect(QRectF(8.5, 8.5, 11, 11), 2.2, 2.2)
        _poli(p, [(15.5, 8.5), (15.5, 6.5), (13.5, 4.5), (6.7, 4.5), (4.5, 6.7), (4.5, 13.5), (6.5, 15.5), (8.5, 15.5)])
    elif nome == "colar":
        _pen(p, c)
        p.drawRoundedRect(QRectF(5, 5.5, 14, 15), 2.4, 2.4)
        p.drawRoundedRect(QRectF(9, 3.5, 6, 4), 1.4, 1.4)
        p.drawLine(QPointF(8.5, 12.5), QPointF(15.5, 12.5))
        p.drawLine(QPointF(8.5, 16), QPointF(13.5, 16))
    elif nome == "comparar":
        # Antes/depois: uma foto dividida ao meio.
        _pen(p, c)
        p.drawRoundedRect(QRectF(3.5, 5, 17, 14), 2.4, 2.4)
        p.drawLine(QPointF(12, 5), QPointF(12, 19))
        _cheio(p, c)
        _poli(p, [(12, 5), (20.5, 5), (20.5, 19), (12, 19)], fechar=True)
    elif nome == "foto":
        _pen(p, c)
        p.drawRoundedRect(QRectF(3.5, 5, 17, 14), 2.4, 2.4)
        _poli(p, [(4, 17), (9.5, 11.5), (13, 15), (15.5, 12.5), (20, 17)])
        p.drawEllipse(QPointF(15.5, 8.8), 1.4, 1.4)
    elif nome == "opcoes":
        # "⋯": três pontos na horizontal (menu de opções de um item, como uma pasta de tamanho).
        _cheio(p, c)
        for x in (5.5, 12, 18.5):
            p.drawEllipse(QPointF(x, 12), 1.9, 1.9)
    else:
        raise KeyError(nome)


NOMES = (
    "importar", "pasta", "exportar", "salvar", "abrir", "configuracoes", "check", "mais", "fechar", "lixeira",
    "girar_esquerda", "girar_direita", "endireitar", "zoom_mais", "zoom_menos", "rosto", "recorte", "grade",
    "filtro", "dinheiro", "info", "aviso", "chevron", "reset", "foto", "copiar", "colar", "comparar", "opcoes",
)


def _pixmap(nome: str, cor: str, tamanho: int, escala: int) -> QPixmap:
    pm = QPixmap(tamanho * escala, tamanho * escala)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(tamanho * escala / 24.0, tamanho * escala / 24.0)
    desenhar(nome, p, QColor(cor))
    p.end()
    pm.setDevicePixelRatio(escala)
    return pm


@lru_cache(maxsize=256)
def icone(nome: str, cor: str = tema.TEXTO, tamanho: int = 20) -> QIcon:
    """Ícone `nome` (veja ``NOMES``) na cor `cor` ("#rrggbb"), em 1x e 2x."""
    ic = QIcon()
    for escala in (1, 2):
        ic.addPixmap(_pixmap(nome, cor, tamanho, escala))
    return ic


def icone_dois_estados(nome: str, desmarcado: str, marcado: str, tamanho: int = 16) -> QIcon:
    """Ícone de botão marcável: uma cor desmarcado e outra marcado (ex.: texto cinza e texto escuro sobre o laranja)."""
    ic = QIcon()
    for estado, cor in ((QIcon.State.Off, desmarcado), (QIcon.State.On, marcado)):
        for escala in (1, 2):
            ic.addPixmap(_pixmap(nome, cor, tamanho, escala), QIcon.Mode.Normal, estado)
    return ic


@lru_cache(maxsize=64)
def bolinha(cor: str, tamanho: int = 12, anel: bool = False) -> QIcon:
    """Círculo cheio na cor `cor` ("#rrggbb") num quadrado de `tamanho` px (com folga de 1 px), em 1x e 2x.

    ``anel``: a bolinha menor dentro de um anel claro (a opção escolhida num menu, onde o ícone esconde o visto)."""
    ic = QIcon()
    for escala in (1, 2):
        pm = QPixmap(tamanho * escala, tamanho * escala)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(escala, escala, (tamanho - 2) * escala, (tamanho - 2) * escala)
        if anel:
            _pen(p, QColor(tema.TEXTO), 1.4 * escala)
            p.drawEllipse(r.adjusted(0.7 * escala, 0.7 * escala, -0.7 * escala, -0.7 * escala))
            r = r.adjusted(3 * escala, 3 * escala, -3 * escala, -3 * escala)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(cor))
        p.drawEllipse(r)
        p.end()
        pm.setDevicePixelRatio(escala)
        ic.addPixmap(pm)
    return ic


@lru_cache(maxsize=1)
def icone_app() -> QIcon:
    """Ícone do programa: `assets/logo.ico` e os PNGs; se faltarem, um quadrado laranja com a marca de corte."""
    from ..app import pasta_assets

    pasta = pasta_assets()
    ic = QIcon()
    for nome in ("logo-256.png", "logo-512.png"):
        arquivo = pasta / nome
        if arquivo.is_file():
            ic.addFile(str(arquivo))
    if not ic.isNull():
        return ic
    pm = QPixmap(64, 64)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(tema.DESTAQUE))
    p.drawRoundedRect(QRectF(2, 2, 60, 60), 14, 14)
    p.scale(64 / 24.0, 64 / 24.0)
    desenhar("recorte", p, QColor(tema.TEXTO_SOBRE_DESTAQUE))
    p.end()
    ic.addPixmap(pm)
    return ic
