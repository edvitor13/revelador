"""Captura de tela da interface, para revisão visual sem abrir nada na tela.

Gera, em SAIDA (padrão ``saida/``):

- ``janela.png``: a janela principal em 1440x900, com fotos de teste importadas (a menos de ``--sem-fotos``);
- ``catalogo.png``: uma folha com os componentes do tema (botões, seletor, chave, sliders, cartões, campos, tabela,
  lista, ícones e cores de estado).

Nada aparece na tela (a janela usa ``WA_DontShowOnScreen`` e a imagem sai de ``QWidget.grab()``), as preferências vão
para uma pasta temporária e as fotos são geradas aqui mesmo (Pillow) mais a de ``tests/data``; nada é gravado fora de
SAIDA e da pasta temporária.

A plataforma ``windows`` (padrão no Windows) usa as fontes do sistema; ``offscreen`` não tem fontes (o texto sai como
quadradinhos) e serve só para automação e testes.

Uso:  python tools/captura_tela.py [--saida SAIDA] [--pasta FOTOS] [--sem-fotos] [--plataforma windows|offscreen]
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TAMANHO_JANELA = (1440, 900)
LARGURA_CATALOGO = 1240


# ------------------------------------------------------------------ fotos de teste
def gerar_fotos(pasta: Path, quantidade: int = 8) -> list[Path]:
    """Cria `quantidade` fotos sintéticas (retrato, paisagem, quadrada) e copia a foto de ``tests/data``."""
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter

    pasta.mkdir(parents=True, exist_ok=True)
    formatos = [(1800, 1200), (1200, 1800), (1500, 1500), (1800, 1200), (1200, 1800), (1600, 1200),
                (1800, 1200), (1200, 1600)]
    paletas = [((250, 190, 110), (60, 90, 140)), ((120, 170, 220), (40, 70, 50)), ((235, 120, 90), (50, 40, 70)),
               ((200, 220, 235), (90, 110, 70)), ((250, 215, 160), (130, 70, 60)), ((90, 150, 200), (20, 40, 80)),
               ((240, 160, 140), (70, 60, 90)), ((180, 200, 120), (60, 80, 60))]
    saidas: list[Path] = []
    for i in range(quantidade):
        w, h = formatos[i % len(formatos)]
        topo, base = paletas[i % len(paletas)]
        t = np.linspace(0.0, 1.0, h, dtype=np.float32)[:, None, None]
        grad = np.array(topo, np.float32) * (1 - t) + np.array(base, np.float32) * t
        arr = np.repeat(grad, w, axis=1)
        img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
        d = ImageDraw.Draw(img)
        d.ellipse((w * 0.62, h * 0.12, w * 0.62 + h * 0.2, h * 0.12 + h * 0.2), fill=(255, 245, 220))
        d.polygon([(0, h * 0.72), (w * 0.3, h * 0.45), (w * 0.55, h * 0.7), (w * 0.8, h * 0.5), (w, h * 0.72),
                   (w, h), (0, h)], fill=tuple(int(c * 0.45) for c in base))
        cx, cy, r = w * (0.3 + 0.05 * (i % 4)), h * 0.62, h * 0.09
        d.ellipse((cx - r, cy - r * 2.2, cx + r, cy - r * 0.2), fill=(236, 200, 170))
        d.rounded_rectangle((cx - r * 1.5, cy - r * 0.1, cx + r * 1.5, cy + r * 3), r * 0.5, fill=(200, 80, 70))
        img = img.filter(ImageFilter.GaussianBlur(1.2))
        caminho = pasta / f"foto_{i + 1:02d}.jpg"
        img.save(caminho, quality=90)
        saidas.append(caminho)
    exemplo = ROOT / "tests" / "data" / "rosto_neil_armstrong.jpg"
    if exemplo.is_file():
        destino = pasta / "retrato.jpg"
        shutil.copyfile(exemplo, destino)
        saidas.append(destino)
    return saidas


# ------------------------------------------------------------------ janela principal
def esperar_workers(app, maximo: float = 15.0) -> None:
    """Processa eventos até as threads do ``QThreadPool`` terminarem (e mais um pouco, para os sinais chegarem)."""
    from PySide6.QtCore import QThreadPool

    pool = QThreadPool.globalInstance()
    inicio = time.monotonic()
    calmo = 0
    while time.monotonic() - inicio < maximo and calmo < 6:
        app.processEvents()
        time.sleep(0.05)
        calmo = calmo + 1 if pool.activeThreadCount() == 0 else 0


def _grab(widget, caminho: Path) -> tuple[int, int]:
    from PySide6.QtCore import Qt

    widget.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    widget.show()
    pm = widget.grab()
    widget.hide()
    if pm.isNull() or not pm.save(str(caminho), "PNG"):
        raise RuntimeError(f"não consegui gravar {caminho}")
    return pm.width(), pm.height()


def capturar_janela(app, fotos: list[Path], caminho: Path) -> tuple[int, int]:
    from PySide6.QtCore import Qt

    from revelador.ui.main_window import MainWindow

    janela = MainWindow()
    janela.resize(*TAMANHO_JANELA)
    janela.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    janela.show()
    app.processEvents()
    if fotos:
        novas = janela.estado.adicionar(fotos)
        esperar_workers(app)
        if novas:
            janela.estado.definir_atual(novas[0])
            esperar_workers(app)
    app.processEvents()
    janela.resize(*TAMANHO_JANELA)
    app.processEvents()
    pm = janela.grab()
    if pm.isNull() or not pm.save(str(caminho), "PNG"):
        raise RuntimeError(f"não consegui gravar {caminho}")
    janela.salvar_estado = lambda: None   # não grava a geometria da captura nas preferências
    janela.close()
    return pm.width(), pm.height()


# ------------------------------------------------------------------ catálogo de componentes
def montar_catalogo():
    """Widget com todos os componentes do tema, na mesma ordem em que o painel de ajustes e a janela os usam."""
    from PySide6.QtCore import QSize, Qt
    from PySide6.QtGui import QStandardItem, QStandardItemModel
    from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialogButtonBox, QDoubleSpinBox, QFrame,
                                   QHBoxLayout, QLabel, QLineEdit, QListView, QProgressBar, QPushButton,
                                   QRadioButton, QSlider, QSpinBox, QTableWidget, QTableWidgetItem, QToolButton,
                                   QVBoxLayout, QWidget)

    from revelador.ui import icones, tema
    from revelador.ui.componentes import Card, Segmented, Slider, ToggleSwitch

    raiz = QWidget()
    raiz.setObjectName("Catalogo")
    raiz.setStyleSheet(f"QWidget#Catalogo {{ background: {tema.BG}; }}")
    raiz.setFixedWidth(LARGURA_CATALOGO)
    corpo = QHBoxLayout(raiz)
    corpo.setContentsMargins(28, 24, 28, 28)
    corpo.setSpacing(28)
    colunas = (QVBoxLayout(), QVBoxLayout())
    for col in colunas:
        col.setSpacing(24)
        corpo.addLayout(col, 1)

    def secao(titulo: str) -> tuple[QWidget, QVBoxLayout]:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)
        k = QLabel(titulo.upper())
        k.setObjectName("Kicker")
        v.addWidget(k)
        return w, v

    def linha(*widgets, esticar: bool = True) -> QHBoxLayout:
        h = QHBoxLayout()
        h.setSpacing(8)
        for w in widgets:
            h.addWidget(w)
        if esticar:
            h.addStretch(1)
        return h

    # -- botões
    s, v = secao("Botões")
    principal = QPushButton("  Exportar")
    principal.setObjectName("Primary")
    principal.setIcon(icones.icone("exportar", tema.TEXTO_SOBRE_DESTAQUE, 16))
    normal = QPushButton("  Importar")
    normal.setIcon(icones.icone("importar", tema.TEXTO, 16))
    perigo = QPushButton("  Remover")
    perigo.setObjectName("Danger")
    perigo.setIcon(icones.icone("lixeira", tema.PERIGO, 16))
    desligado = QPushButton("Desabilitado")
    desligado.setEnabled(False)
    v.addLayout(linha(principal, normal, perigo, desligado))
    planos = []
    for nome, dica in (("pasta", "Pasta"), ("salvar", "Salvar"), ("abrir", "Abrir"), ("configuracoes", "Ajustes")):
        b = QToolButton()
        b.setObjectName("Flat")
        b.setIcon(icones.icone(nome, tema.APAGADO, 18))
        b.setToolTip(dica)
        planos.append(b)
    marcado = QToolButton()
    marcado.setObjectName("Flat")
    marcado.setCheckable(True)
    marcado.setChecked(True)
    marcado.setIcon(icones.icone("grade", tema.DESTAQUE_HI, 18))
    planos.append(marcado)
    plano_texto = QPushButton("  Ajuda")
    plano_texto.setObjectName("Flat")
    plano_texto.setIcon(icones.icone("info", tema.APAGADO, 16))
    planos.append(plano_texto)
    v.addLayout(linha(*planos))
    seg = Segmented([("pe", "Em pé", ""), ("deitada", "Deitada", ""), ("auto", "Automática", "")],
                    icones_itens={"pe": "foto", "deitada": "foto"})
    seg.definir_atual("pe")
    seg2 = Segmented([("a", "Grade", ""), ("b", "Lista", "")], icones_itens={"a": "grade"})
    seg2.definir_atual("a")
    v.addLayout(linha(seg, seg2))
    t1, t2, t3 = ToggleSwitch(), ToggleSwitch(), ToggleSwitch()
    t1.setChecked(True)
    t3.setChecked(True)
    t3.setEnabled(False)
    ch = QCheckBox("Marcar para revelar")
    ch.setChecked(True)
    ch2 = QCheckBox("Sem marcar")
    rd = QRadioButton("Opção A")
    rd.setChecked(True)
    rd2 = QRadioButton("Opção B")
    v.addLayout(linha(t1, t2, t3, ch, ch2, rd, rd2))
    colunas[0].addWidget(s)

    # -- campos
    s, v = secao("Campos")
    combo = QComboBox()
    combo.addItems(["10x15 cm", "13x18 cm", "15x21 cm", "20x25 cm"])
    campo = QLineEdit()
    campo.setPlaceholderText("Buscar fotos…")
    campo2 = QLineEdit("Casamento da Ana")
    giro = QSpinBox()
    giro.setRange(1, 99)
    giro.setValue(2)
    preco = QDoubleSpinBox()
    preco.setPrefix("R$ ")
    preco.setValue(1.5)
    v.addLayout(linha(combo, campo, esticar=False))
    v.addLayout(linha(campo2, giro, preco, esticar=False))
    barra = QProgressBar()
    barra.setRange(0, 100)
    barra.setValue(62)
    barra.setTextVisible(False)
    v.addWidget(barra)
    sl = QSlider(Qt.Orientation.Horizontal)
    sl.setRange(0, 100)
    sl.setValue(40)
    v.addWidget(sl)
    bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    bb.button(QDialogButtonBox.StandardButton.Ok).setDefault(True)
    v.addWidget(bb)
    colunas[1].addWidget(s)

    # -- cartões e sliders
    s, v = secao("Cartões e sliders")
    c1 = Card("Luz", "Brilho, contraste e exposição", restaurar=True, dica_restaurar="Restaurar")
    for rot, mn, mx, st, pd, un, atual in (("Exposição", -2.0, 2.0, 0.05, 0, " EV", 0.35),
                                           ("Contraste", -100, 100, 1, 0, "", 18),
                                           ("Realces", -100, 100, 1, 0, "", -40)):
        sl_aj = Slider(rot, mn, mx, st, pd, un)
        sl_aj.definir_valor(atual)
        c1.adicionar(sl_aj)
    c2 = Card("Nitidez", "Realça detalhes finos", restaurar=True, com_chave=True, expandido=False)
    c2.chave.setChecked(True)
    c3 = Card("Cor", "Saturação e temperatura", restaurar=True, com_chave=True, expandido=False)
    v.addWidget(c1)
    v.addWidget(c2)
    v.addWidget(c3)
    colunas[0].addWidget(s)

    # -- tabela
    s, v = secao("Tabela (resumo do pedido)")
    tab = QTableWidget(5, 4)
    tab.setHorizontalHeaderLabels(["Tamanho", "Fotos", "Cópias", "Total"])
    tab.verticalHeader().setVisible(False)
    tab.setShowGrid(False)
    tab.setAlternatingRowColors(True)
    tab.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    tab.horizontalHeader().setStretchLastSection(True)
    dados = [("10x15 cm", "24", "30", "R$ 36,00"), ("13x18 cm", "6", "6", "R$ 15,00"),
             ("15x21 cm", "3", "3", "R$ 13,50"), ("20x25 cm", "1", "1", "R$ 12,00"),
             ("Total", "34", "40", "R$ 76,50")]
    for r, lin in enumerate(dados):
        for c, txt in enumerate(lin):
            it = QTableWidgetItem(txt)
            if c >= 1:
                it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            tab.setItem(r, c, it)
    tab.horizontalHeaderItem(0).setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    for c in (1, 2, 3):
        tab.horizontalHeaderItem(c).setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    tab.selectRow(1)
    tab.setFixedHeight(200)
    v.addWidget(tab)
    colunas[1].addWidget(s)

    # -- lista (grade de fotos) e ícones
    s, v = secao("Lista, estados e ícones")
    lista = QListView()
    lista.setViewMode(QListView.ViewMode.IconMode)
    lista.setIconSize(QSize(72, 72))
    lista.setGridSize(QSize(92, 100))
    lista.setSpacing(2)
    lista.setMovement(QListView.Movement.Static)
    lista.setResizeMode(QListView.ResizeMode.Adjust)
    modelo = QStandardItemModel(lista)
    for i in range(6):
        it = QStandardItem(f"foto_{i + 1:02d}")
        it.setIcon(icones.icone("foto", tema.FRACO, 48))
        modelo.appendRow(it)
    lista.setModel(modelo)
    lista.selectionModel().select(modelo.index(1, 0), lista.selectionModel().SelectionFlag.Select)
    lista.setFixedHeight(112)
    v.addWidget(lista)
    estados = []
    for cor, txt, ic in ((tema.OK, "Boa resolução", "check"), (tema.AVISO, "Resolução aceitável", "aviso"),
                         (tema.PERIGO, "Resolução baixa", "aviso")):
        e = QLabel(f" {txt}")
        e.setStyleSheet(f"color: {cor};")
        e.setPixmap(icones.icone(ic, cor, 16).pixmap(16, 16))
        t = QLabel(txt)
        t.setStyleSheet(f"color: {cor}; font-weight: 600;")
        estados.append(e)
        estados.append(t)
    v.addLayout(linha(*estados))
    txt1 = QLabel("Texto principal")
    txt2 = QLabel("Texto apagado")
    txt2.setObjectName("Muted")
    txt3 = QLabel("Texto fraco e dicas")
    txt3.setObjectName("Faint")
    tit = QLabel("Título do painel")
    tit.setObjectName("PanelTitle")
    v.addLayout(linha(tit, txt1, txt2, txt3))
    icos = []
    for nome in icones.NOMES:
        lb = QLabel()
        lb.setPixmap(icones.icone(nome, tema.TEXTO, 24).pixmap(24, 24))
        lb.setToolTip(nome)
        icos.append(lb)
    for i in range(0, len(icos), 13):
        v.addLayout(linha(*icos[i:i + 13]))
    quadro = QFrame()
    quadro.setFixedHeight(34)
    quadro.setStyleSheet(f"background: {tema.CANVAS_EDITOR}; border-radius: 8px;")
    v.addWidget(quadro)
    colunas[1].addWidget(s)
    for col in colunas:
        col.addStretch(1)
    return raiz


def capturar_catalogo(app, caminho: Path) -> tuple[int, int]:
    raiz = montar_catalogo()
    raiz.adjustSize()
    app.processEvents()
    return _grab(raiz, caminho)


# ------------------------------------------------------------------ principal
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Gera PNGs da interface para revisão visual.")
    ap.add_argument("--saida", type=Path, default=Path("saida"), help="pasta dos PNGs (padrão: ./saida)")
    ap.add_argument("--pasta", type=Path, help="pasta de fotos a importar (padrão: fotos geradas)")
    ap.add_argument("--sem-fotos", action="store_true", help="não importa fotos na janela principal")
    ap.add_argument("--plataforma", default="windows" if sys.platform == "win32" else "offscreen",
                    help="plataforma do Qt (windows renderiza as fontes do sistema; offscreen não abre nada)")
    args = ap.parse_args(argv)

    temporario = Path(tempfile.mkdtemp(prefix="revelador_captura_"))
    os.environ["QT_QPA_PLATFORM"] = args.plataforma
    os.environ["REVELADOR_SETTINGS_DIR"] = str(temporario / "prefs")      # não mexe nas preferências do usuário
    os.environ["LOCALAPPDATA"] = str(temporario / "localappdata")         # cache de miniaturas e afins
    os.environ["APPDATA"] = str(temporario / "appdata")
    for sub in ("prefs", "localappdata", "appdata"):
        (temporario / sub).mkdir(parents=True, exist_ok=True)
    args.saida.mkdir(parents=True, exist_ok=True)
    try:
        from PySide6.QtWidgets import QApplication

        from revelador.ui import tema

        app = QApplication.instance() or QApplication([sys.argv[0]])
        tema.instalar(app)
        fotos: list[Path] = []
        if not args.sem_fotos:
            if args.pasta:
                fotos = sorted(p for p in args.pasta.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"})
            else:
                fotos = gerar_fotos(temporario / "fotos")
        largura, altura = capturar_janela(app, fotos, args.saida / "janela.png")
        print(f"janela.png   {largura}x{altura}")
        largura, altura = capturar_catalogo(app, args.saida / "catalogo.png")
        print(f"catalogo.png {largura}x{altura}")
        return 0
    finally:
        shutil.rmtree(temporario, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
