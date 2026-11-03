"""Ponto de entrada da interface do Revelador.

Por enquanto abre a janela provisória da 0.1.0 em construção; a issue #1 troca pela janela principal
(``ui/main_window.py``). ``--diagnostico ARQUIVO.json`` confere as dependências nativas e sai sem abrir janela
(usado pelo CI no executável empacotado; veja ``diagnostico.py``).
"""

from __future__ import annotations

import sys
from pathlib import Path

from . import APP_NAME, __version__

# Identidade do app na barra de tarefas do Windows (sem ela, o pythonw agrupa o ícone com o do Python).
APP_USER_MODEL_ID = "VitorGabriel.Revelador"


def pasta_assets() -> Path:
    """Pasta ``assets`` no código-fonte ou dentro do executável do PyInstaller (``_internal/assets``)."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / "assets"
    return Path(__file__).resolve().parent.parent / "assets"


def criar_janela():
    """Janela provisória (até a #1): título, versão e onde acompanhar o andamento."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QLabel, QMainWindow

    janela = QMainWindow()
    janela.setWindowTitle(f"{APP_NAME} {__version__}")
    texto = QLabel(
        f"<h2>{APP_NAME} {__version__}</h2>"
        "<p>Em construção: escolher fotos, enquadrar no tamanho do papel e separar para revelação.</p>"
        "<p>Acompanhe em <a href='https://github.com/edvitor13/revelador/issues'>"
        "github.com/edvitor13/revelador</a>.</p>")
    texto.setAlignment(Qt.AlignmentFlag.AlignCenter)
    texto.setOpenExternalLinks(True)
    texto.setWordWrap(True)
    janela.setCentralWidget(texto)
    janela.resize(720, 420)
    return janela


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "--diagnostico":
        from . import diagnostico

        return diagnostico.main(Path(args[1]) if len(args) > 1 else None)

    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
        except (AttributeError, OSError):
            pass

    app = QApplication.instance() or QApplication([sys.argv[0], *args])
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    app.setApplicationVersion(__version__)
    icone = pasta_assets() / "logo-256.png"
    if icone.is_file():
        app.setWindowIcon(QIcon(str(icone)))

    janela = criar_janela()
    janela.show()
    return app.exec()
