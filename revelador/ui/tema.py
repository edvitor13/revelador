"""Cores, fontes e folha de estilo do Revelador (só tema escuro, cinzas neutros e destaque laranja do logo).

Decisões de design:

- **Cinzas neutros** (R = G = B): o app serve para julgar a cor de fotos, e uma interface tingida engana o olho.
  A única cor da interface é o laranja das marcas de corte do logo (``assets/logo.svg``), usado com parcimônia:
  botão principal, seleção, controle ligado e foco. Os demais estados (OK, aviso, perigo) só aparecem em
  indicadores pequenos.
- **Foto em destaque**: a janela é a mais escura (``BG``); os painéis laterais ficam um degrau acima (``PAINEL``);
  campos e botões, outro degrau (``PAINEL2``); o fundo do editor (``CANVAS_EDITOR``) é um cinza de meio-tom, sem matiz.
- **Cantos suaves e respiro**: raios de 8 px nos controles e 12 px nos cartões; botões com ~34 px de altura.
- Toda cor/medida da interface vem daqui: nenhum widget escreve hexadecimal nem ``setStyleSheet`` próprio, exceto
  para trocar o ``objectName`` de estilo (``Primary``, ``Flat`` etc.).

Nomes de objeto da folha de estilo: ``TopBar``, ``Panel``, ``Card``, ``Primary``, ``Danger``, ``Flat``, ``Seg``,
``SegBox``, ``Muted``, ``Faint``, ``PanelTitle``, ``Kicker``, ``Value``, ``Mono``, ``Thumb``.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette

# ---------------------------------------------------------------- cinzas neutros (R = G = B)
BG = "#121212"        # janela e grade de fotos
PAINEL = "#1a1a1a"    # barra superior, painéis laterais, barra de status
PAINEL2 = "#232323"   # campos, botões, cartões
PAINEL3 = "#2d2d2d"   # passar o mouse, trilhos, fundo de menu
BORDA = "#333333"
BORDA_FORTE = "#474747"  # borda de campo com o mouse em cima, caixas de marcar
TEXTO = "#ececec"
APAGADO = "#a0a0a0"   # texto secundário (contraste AA sobre todos os painéis)
FRACO = "#8a8a8a"     # dicas e texto desabilitado (AA, ≥ 4,5:1, sobre BG, PAINEL e PAINEL2)

# ---------------------------------------------------------------- destaque (laranja das marcas de corte do logo)
DESTAQUE = "#ff7a45"
DESTAQUE_HI = "#ff9468"     # passar o mouse e texto de destaque sobre fundo escuro
DESTAQUE_DIM = "#8a4325"    # bordas de foco, trilho preenchido desabilitado
TEXTO_SOBRE_DESTAQUE = "#1f0e06"  # texto/ícone sobre o laranja
SELECAO = "rgba(255, 122, 69, 0.20)"  # fundo de item selecionado (grade, tabela, lista)

# ---------------------------------------------------------------- estados
OK = "#4cc38a"
AVISO = "#f2c14e"    # resolução aceitável
PERIGO = "#f06573"   # resolução baixa, erro

# ---------------------------------------------------------------- editor
CANVAS_EDITOR = "#262626"  # fundo atrás da foto no editor: cinza escuro sem matiz

RAIO = 8      # controles
RAIO_CARD = 12


# ---------------------------------------------------------------- fontes
def _familias() -> set[str]:
    return set(QFontDatabase.families())


def fonte_ui() -> str:
    familias = _familias()
    for nome in ("Segoe UI Variable Text", "Segoe UI", "Inter", "Helvetica Neue", "Arial"):
        if nome in familias:
            return nome
    return "Sans Serif"


def fonte_titulo() -> str:
    familias = _familias()
    for nome in ("Segoe UI Variable Display", "Segoe UI Semibold", "Segoe UI", "Inter", "Arial"):
        if nome in familias:
            return nome
    return fonte_ui()


def fonte_mono() -> str:
    familias = _familias()
    for nome in ("Cascadia Mono", "Consolas", "DejaVu Sans Mono"):
        if nome in familias:
            return nome
    return "monospace"


def fonte(tamanho: float = 9.5, peso: QFont.Weight = QFont.Weight.Normal, titulo: bool = False) -> QFont:
    f = QFont(fonte_titulo() if titulo else fonte_ui())
    f.setPointSizeF(tamanho)
    f.setWeight(peso)
    return f


# ---------------------------------------------------------------- paleta
def paleta() -> QPalette:
    p = QPalette()
    P, G = QPalette.ColorRole, QPalette.ColorGroup
    p.setColor(P.Window, QColor(BG))
    p.setColor(P.WindowText, QColor(TEXTO))
    p.setColor(P.Base, QColor(PAINEL2))
    p.setColor(P.AlternateBase, QColor(PAINEL))
    p.setColor(P.Text, QColor(TEXTO))
    p.setColor(P.Button, QColor(PAINEL2))
    p.setColor(P.ButtonText, QColor(TEXTO))
    p.setColor(P.Highlight, QColor(DESTAQUE))
    p.setColor(P.HighlightedText, QColor(TEXTO_SOBRE_DESTAQUE))
    p.setColor(P.ToolTipBase, QColor(PAINEL3))
    p.setColor(P.ToolTipText, QColor(TEXTO))
    p.setColor(P.PlaceholderText, QColor(FRACO))
    p.setColor(P.Link, QColor(DESTAQUE_HI))
    for papel in (P.Text, P.ButtonText, P.WindowText):
        p.setColor(G.Disabled, papel, QColor(FRACO))
    return p


# ---------------------------------------------------------------- folha de estilo
def folha_de_estilo(seta: str = "", marca: str = "") -> str:
    """Folha de estilo única do app. ``seta`` e ``marca``: caminhos (com ``/``) dos PNGs da seta dos combos e do
    "visto" das caixas de marcar (veja ``instalar``); vazios, o combo fica sem seta e a caixa sem visto."""
    f = fonte_ui()
    t = fonte_titulo()
    m = fonte_mono()
    return f"""
* {{ font-family: "{f}"; font-size: 9.5pt; color: {TEXTO}; }}
QMainWindow, QDialog {{ background: {BG}; }}
QMessageBox {{ background: {PAINEL}; }}
QToolTip {{ background: {PAINEL3}; color: {TEXTO}; border: 1px solid {BORDA_FORTE}; padding: 6px 9px;
    border-radius: 6px; }}

QWidget#Panel {{ background: {PAINEL}; }}
QWidget#TopBar {{ background: {PAINEL}; border-bottom: 1px solid {BORDA}; }}
QFrame#Card {{ background: {PAINEL2}; border: 1px solid {BORDA}; border-radius: {RAIO_CARD}px; }}
QLabel {{ background: transparent; }}
QLabel#Muted {{ color: {APAGADO}; }}
QLabel#Faint {{ color: {FRACO}; font-size: 8.5pt; }}
QLabel#PanelTitle {{ font-family: "{t}"; font-size: 10.5pt; font-weight: 600; color: {TEXTO}; }}
QLabel#Kicker {{ font-family: "{t}"; font-size: 8pt; font-weight: 600; color: {DESTAQUE}; }}
QLabel#Mono {{ font-family: "{m}"; font-size: 9pt; color: {APAGADO}; }}

QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 12px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {PAINEL3}; border-radius: 4px; min-height: 36px; margin: 0 2px; }}
QScrollBar::handle:vertical:hover {{ background: {BORDA_FORTE}; }}
QScrollBar::handle:vertical:pressed {{ background: {DESTAQUE_DIM}; }}
QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {PAINEL3}; border-radius: 4px; min-width: 36px; margin: 2px 0; }}
QScrollBar::handle:horizontal:hover {{ background: {BORDA_FORTE}; }}
QScrollBar::handle:horizontal:pressed {{ background: {DESTAQUE_DIM}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QPushButton, QToolButton {{
    background: {PAINEL2}; border: 1px solid {BORDA}; border-radius: {RAIO}px; padding: 7px 14px; color: {TEXTO};
}}
QPushButton:hover, QToolButton:hover {{ background: {PAINEL3}; border-color: {BORDA_FORTE}; }}
QPushButton:pressed, QToolButton:pressed {{ background: {PAINEL}; }}
QPushButton:focus {{ border-color: {DESTAQUE_DIM}; }}
QPushButton:disabled, QToolButton:disabled {{ color: {FRACO}; background: {PAINEL}; border-color: {BORDA}; }}
QPushButton#Primary {{ background: {DESTAQUE}; color: {TEXTO_SOBRE_DESTAQUE}; border: 1px solid {DESTAQUE};
    font-weight: 600; padding: 7px 16px; }}
QPushButton#Primary:hover {{ background: {DESTAQUE_HI}; border-color: {DESTAQUE_HI}; }}
QPushButton#Primary:pressed {{ background: {DESTAQUE}; }}
QPushButton#Primary:disabled {{ background: {DESTAQUE_DIM}; border-color: {DESTAQUE_DIM}; color: {PAINEL2}; }}
QPushButton#Danger {{ color: {PERIGO}; }}
QPushButton#Danger:hover {{ border-color: {PERIGO}; }}
QToolButton#Flat, QPushButton#Flat {{ background: transparent; border: 1px solid transparent; padding: 6px 10px; }}
QToolButton#Flat:hover, QPushButton#Flat:hover {{ background: {PAINEL3}; }}
QToolButton#Flat:pressed, QPushButton#Flat:pressed {{ background: {PAINEL2}; }}
QToolButton#Flat:checked {{ background: {PAINEL3}; color: {DESTAQUE_HI}; }}
QToolButton#Flat:disabled, QPushButton#Flat:disabled {{ background: transparent; border-color: transparent; }}
QToolButton#Seg {{ background: transparent; border: none; border-radius: 6px; padding: 5px 12px; color: {APAGADO}; }}
QToolButton#Seg:hover {{ color: {TEXTO}; background: {PAINEL3}; }}
QToolButton#Seg:checked {{ color: {TEXTO_SOBRE_DESTAQUE}; background: {DESTAQUE}; font-weight: 600; }}
QFrame#SegBox {{ background: {PAINEL}; border: 1px solid {BORDA}; border-radius: {RAIO + 2}px; }}
QToolButton::menu-indicator {{ image: none; width: 0; }}

QComboBox {{
    background: {PAINEL2}; border: 1px solid {BORDA}; border-radius: {RAIO}px; padding: 6px 11px; min-height: 20px;
}}
QComboBox:hover {{ border-color: {BORDA_FORTE}; }}
QComboBox:focus, QComboBox:on {{ border-color: {DESTAQUE_DIM}; }}
QComboBox:disabled {{ color: {FRACO}; background: {PAINEL}; }}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox::down-arrow {{ image: url("{seta}"); width: 12px; height: 12px; margin-right: 8px; }}
QComboBox QAbstractItemView {{
    background: {PAINEL3}; border: 1px solid {BORDA_FORTE}; selection-background-color: {SELECAO};
    selection-color: {DESTAQUE_HI}; outline: 0; padding: 4px;
}}
QLineEdit, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit {{
    background: {PAINEL2}; border: 1px solid {BORDA}; border-radius: {RAIO}px; padding: 6px 10px;
    selection-background-color: {DESTAQUE}; selection-color: {TEXTO_SOBRE_DESTAQUE};
}}
QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover {{ border-color: {BORDA_FORTE}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QPlainTextEdit:focus, QTextEdit:focus {{
    border-color: {DESTAQUE_DIM}; }}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{ color: {FRACO}; background: {PAINEL}; }}
QLineEdit#Value {{ background: transparent; border: 1px solid transparent; border-radius: 6px; padding: 2px 5px;
    color: {TEXTO}; font-family: "{m}"; font-size: 8.5pt; }}
QLineEdit#Value:hover {{ border-color: {BORDA}; background: {PAINEL2}; }}
QLineEdit#Value:focus {{ border-color: {DESTAQUE_DIM}; background: {PAINEL2}; }}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    width: 0; border: none; }}

QCheckBox {{ spacing: 9px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 5px; border: 1px solid {BORDA_FORTE};
    background: {PAINEL2}; }}
QCheckBox::indicator:hover {{ border-color: {DESTAQUE_DIM}; }}
QCheckBox::indicator:checked {{ background: {DESTAQUE}; border-color: {DESTAQUE}; image: url("{marca}"); }}
QCheckBox:disabled {{ color: {FRACO}; }}
QRadioButton {{ spacing: 9px; }}
QRadioButton::indicator {{ width: 16px; height: 16px; border-radius: 9px; border: 1px solid {BORDA_FORTE};
    background: {PAINEL2}; }}
QRadioButton::indicator:hover {{ border-color: {DESTAQUE_DIM}; }}
QRadioButton::indicator:checked {{ border-color: {DESTAQUE}; background: qradialgradient(cx:0.5, cy:0.5,
    radius:0.5, fx:0.5, fy:0.5, stop:0 {DESTAQUE}, stop:0.45 {DESTAQUE}, stop:0.55 {PAINEL2}, stop:1 {PAINEL2}); }}

QMenu {{ background: {PAINEL3}; border: 1px solid {BORDA_FORTE}; border-radius: 10px; padding: 6px; }}
QMenu::item {{ padding: 7px 24px 7px 12px; border-radius: 6px; }}
QMenu::item:selected {{ background: {SELECAO}; color: {DESTAQUE_HI}; }}
QMenu::item:disabled {{ color: {FRACO}; }}
QMenu::separator {{ height: 1px; background: {BORDA_FORTE}; margin: 5px 8px; }}
QMenu::icon {{ padding-left: 6px; }}
QMenuBar {{ background: {PAINEL}; }}
QMenuBar::item:selected {{ background: {PAINEL3}; }}

QSplitter::handle {{ background: {BORDA}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}
QSplitter::handle:hover {{ background: {DESTAQUE_DIM}; }}
QStatusBar {{ background: {PAINEL}; border-top: 1px solid {BORDA}; color: {APAGADO}; }}
QStatusBar::item {{ border: none; }}
QStatusBar QLabel {{ color: {APAGADO}; font-size: 9pt; padding: 0 8px; }}
QProgressBar {{ background: {PAINEL3}; border: none; border-radius: 3px; min-height: 6px; max-height: 6px;
    text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: {DESTAQUE}; border-radius: 3px; }}
QGroupBox {{ border: 1px solid {BORDA}; border-radius: {RAIO_CARD}px; margin-top: 14px; padding: 14px 12px 12px 12px;
    background: {PAINEL}; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 14px; padding: 0 6px; color: {APAGADO};
    font-family: "{t}"; font-weight: 600; }}
QTabWidget::pane {{ border: 1px solid {BORDA}; border-radius: {RAIO}px; }}
QTabBar::tab {{ background: transparent; padding: 8px 16px; color: {APAGADO}; border-bottom: 2px solid transparent; }}
QTabBar::tab:hover {{ color: {TEXTO}; }}
QTabBar::tab:selected {{ color: {TEXTO}; border-bottom: 2px solid {DESTAQUE}; }}

QListView, QListWidget {{ background: {BG}; border: none; outline: 0; }}
QListView::item, QListWidget::item {{ border-radius: {RAIO}px; }}
QListView::item:hover {{ background: {PAINEL2}; }}
QListView::item:selected {{ background: {SELECAO}; color: {TEXTO}; }}
QListView:focus {{ border: none; }}

QTableView, QTableWidget {{ background: {PAINEL2}; alternate-background-color: {PAINEL}; border: 1px solid {BORDA};
    border-radius: {RAIO}px; gridline-color: transparent; outline: 0; selection-background-color: {SELECAO};
    selection-color: {TEXTO}; }}
QTableView::item {{ padding: 5px 10px; border: none; }}
QTableView::item:hover {{ background: {PAINEL3}; }}
QTableCornerButton::section {{ background: {PAINEL}; border: none; }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{ background: {PAINEL}; color: {APAGADO}; border: none; border-bottom: 1px solid {BORDA};
    padding: 7px 10px; font-weight: 600; font-size: 8.5pt; }}
QHeaderView::section:hover {{ color: {TEXTO}; }}
QTreeView {{ background: {PAINEL2}; border: 1px solid {BORDA}; border-radius: {RAIO}px; outline: 0; }}
QTreeView::item:selected {{ background: {SELECAO}; color: {TEXTO}; }}

QSlider {{ min-height: 22px; }}
QSlider::groove:horizontal {{ height: 4px; background: {PAINEL3}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {DESTAQUE}; border-radius: 2px; }}
QSlider::sub-page:horizontal:disabled {{ background: {DESTAQUE_DIM}; }}
QSlider::handle:horizontal {{ background: {TEXTO}; border: 2px solid {DESTAQUE}; width: 12px; height: 12px;
    margin: -7px 0; border-radius: 8px; }}
QSlider::handle:horizontal:hover {{ background: #ffffff; }}
QSlider::handle:horizontal:disabled {{ background: {FRACO}; border-color: {DESTAQUE_DIM}; }}

QDialogButtonBox QPushButton {{ min-width: 88px; }}
QDialogButtonBox QPushButton:default {{ background: {DESTAQUE}; color: {TEXTO_SOBRE_DESTAQUE};
    border-color: {DESTAQUE}; font-weight: 600; }}
QDialogButtonBox QPushButton:default:hover {{ background: {DESTAQUE_HI}; border-color: {DESTAQUE_HI}; }}
QMessageBox QPushButton:default {{ background: {DESTAQUE}; color: {TEXTO_SOBRE_DESTAQUE};
    border-color: {DESTAQUE}; font-weight: 600; }}
QMessageBox QPushButton {{ min-width: 88px; }}
"""


# ---------------------------------------------------------------- aplicação
def _pasta_cache() -> Path:
    return Path(tempfile.gettempdir())


def instalar(app) -> None:
    """Aplica o tema no ``QApplication``: Fusion, paleta, folha de estilo (com as setas geradas em PNG), fonte, ícone."""
    from . import icones

    app.setStyle("Fusion")
    app.setPalette(paleta())
    seta = _pasta_cache() / "revelador_seta.png"
    marca = _pasta_cache() / "revelador_marca.png"
    icones.icone("chevron", APAGADO, 12).pixmap(24, 24).save(str(seta))
    icones.icone("check", TEXTO_SOBRE_DESTAQUE, 12).pixmap(24, 24).save(str(marca))
    app.setStyleSheet(folha_de_estilo(str(seta).replace(os.sep, "/"), str(marca).replace(os.sep, "/")))
    app.setFont(fonte(9.5))
    app.setWindowIcon(icones.icone_app())
