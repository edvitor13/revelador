"""Ponto de entrada da interface do Revelador.

Instala o registro de erros, aplica o tema (``ui/tema.py``) e abre a janela principal (``ui/main_window.py``); as fotos passadas
na linha de comando ficam em ``janela.arquivos_iniciais`` para a importação. ``--diagnostico ARQUIVO.json``
confere as dependências nativas e sai sem abrir janela
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


def _ligar_aviso_de_erro(janela) -> None:
    """Mostra um aviso curto, com "Abrir registro", quando o crashlog grava um erro (de qualquer thread)."""
    from PySide6.QtCore import QObject, Qt, Signal
    from PySide6.QtWidgets import QMessageBox

    from . import crashlog, system
    from .i18n import _

    class Ponte(QObject):
        erro = Signal(str)

    ponte = Ponte(janela)

    def mostrar(caminho: str) -> None:
        texto = _("Ocorreu um erro inesperado. O programa continua aberto e suas fotos não foram alteradas.")
        caixa = QMessageBox(QMessageBox.Icon.Warning, _("Algo deu errado"), texto,
                            QMessageBox.StandardButton.Ok, janela)
        abrir = caixa.addButton(_("Abrir registro"), QMessageBox.ButtonRole.ActionRole)
        caixa.exec()
        if caixa.clickedButton() is abrir:
            system.reveal(caminho) if caminho else system.open_path(crashlog.pasta_logs())

    ponte.erro.connect(mostrar, Qt.ConnectionType.QueuedConnection)
    crashlog.ao_gravar = lambda caminho, _texto: ponte.erro.emit(str(caminho or ""))


def separar_argumentos(args: list[str]) -> tuple[list[str], list[str]]:
    """Separa os trabalhos ``.revelador`` (abrem o trabalho) do resto (fotos e pastas, que vão para a importação)."""
    uteis = [a for a in args if not a.startswith("--")]
    trabalhos = [a for a in uteis if a.lower().endswith(".revelador")]
    return trabalhos, [a for a in uteis if a not in trabalhos]


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "--diagnostico":
        from . import diagnostico

        return diagnostico.main(Path(args[1]) if len(args) > 1 else None)

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

    from . import crashlog
    from .ui import tema
    from .ui.main_window import MainWindow

    crashlog.instalar()
    tema.instalar(app)  # Fusion + paleta escura + folha de estilo + fonte + ícone do app
    janela = MainWindow()
    trabalhos, janela.arquivos_iniciais = separar_argumentos(args)
    if trabalhos:
        janela.projeto_ui.abrir(Path(trabalhos[0]))   # o primeiro .revelador; fotos e pastas entram depois
    _ligar_aviso_de_erro(janela)
    janela.show()
    return app.exec()
