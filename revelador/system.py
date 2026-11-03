"""Abrir arquivos e pastas no sistema e pastas do usuário."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from . import APP_NAME


def open_path(caminho) -> None:
    """Abre um arquivo ou pasta com o programa padrão do sistema."""
    caminho = str(caminho)
    if sys.platform == "win32":
        os.startfile(caminho)  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", caminho])
    else:
        subprocess.Popen(["xdg-open", caminho])


def reveal(caminho) -> None:
    """Mostra o arquivo selecionado na sua pasta (Explorer com ``/select,``); numa pasta, abre a pasta."""
    caminho = str(caminho)
    if sys.platform == "win32" and os.path.isfile(caminho):
        subprocess.Popen(["explorer", "/select,", os.path.normpath(caminho)])
    elif os.path.isdir(caminho):
        open_path(caminho)
    else:
        open_path(os.path.dirname(caminho) or ".")


def pasta_imagens() -> Path:
    """Pasta Imagens do usuário (a pasta pessoal, se ela não existir)."""
    home = Path.home()
    for nome in ("Pictures", "Imagens"):
        if (home / nome).is_dir():
            return home / nome
    return home


def pasta_dados() -> Path:
    r"""Pasta de dados do app: ``%LOCALAPPDATA%\Revelador`` (``~/.local/share/Revelador`` fora do Windows)."""
    base = os.environ.get("LOCALAPPDATA")
    raiz = Path(base) if base else Path.home() / ".local" / "share"
    return raiz / APP_NAME
