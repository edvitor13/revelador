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


def para_lixeira(caminho) -> None:
    """Manda o arquivo ou a pasta para a Lixeira (dá para recuperar). Só no Windows; nos outros sistemas, por ora,
    ``OSError`` (quem chama avisa e não apaga nada)."""
    caminho = Path(caminho)
    if sys.platform != "win32":
        raise OSError(f"Lixeira não suportada neste sistema: {caminho}")
    import ctypes
    from ctypes import wintypes

    class _SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR),
                    ("pTo", wintypes.LPCWSTR), ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]

    FO_DELETE, FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO, FOF_NOERRORUI = 3, 0x4, 0x10, 0x40, 0x400
    op = _SHFILEOPSTRUCTW(None, FO_DELETE, str(caminho.resolve()) + "\0\0", None,
                          FOF_SILENT | FOF_NOCONFIRMATION | FOF_ALLOWUNDO | FOF_NOERRORUI, False, None, None)
    erro = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if erro or op.fAnyOperationsAborted or caminho.exists():
        raise OSError(f"não foi possível mandar para a Lixeira: {caminho} (código {erro})")
