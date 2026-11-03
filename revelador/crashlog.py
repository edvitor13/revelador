r"""Registro de erros sem tratamento (sem Qt). Nada é enviado: tudo fica em ``<pasta de dados>\logs``.

``instalar()`` troca ``sys.excepthook`` e ``threading.excepthook``: cada exceção que escapa vira um arquivo
``erro-<data>.txt`` com versão, sistema e traceback. A pasta é pequena: só os ``MAX_ARQUIVOS`` mais novos ficam
e cada registro tem no máximo ``MAX_BYTES``. Se a interface registrou ``ao_gravar``, ela mostra o aviso curto.
"""

from __future__ import annotations

import platform
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Callable

from . import APP_NAME, __version__, system

PREFIXO = "erro-"
MAX_ARQUIVOS = 20
MAX_BYTES = 256 * 1024

# Chamado com (caminho do registro | None, texto) depois de gravar; pode vir de qualquer thread.
ao_gravar: Callable[[Path | None, str], None] | None = None
_antigos: tuple | None = None
_pasta: Path | None = None


def pasta_logs() -> Path:
    return system.pasta_dados() / "logs"


def formatar(tipo, exc, tb, onde: str = "") -> str:
    """Texto do registro: quando, onde, ambiente e traceback."""
    linhas = [f"{APP_NAME} - registro de erro", f"Data: {time.strftime('%Y-%m-%d %H:%M:%S')}"]
    if onde:
        linhas.append(f"Onde: {onde}")
    linhas += [f"Versão: {APP_NAME} {__version__}", f"Sistema: {platform.platform()}",
               f"Python: {platform.python_version()}", ""]
    return "\n".join(linhas) + "".join(traceback.format_exception(tipo, exc, tb))


def _limpar(pasta: Path) -> None:
    try:
        arquivos = sorted((p for p in pasta.iterdir() if p.name.startswith(PREFIXO)), key=lambda p: p.name,
                          reverse=True)
    except OSError:
        return
    for antigo in arquivos[MAX_ARQUIVOS:]:
        try:
            antigo.unlink()
        except OSError:
            pass


def gravar(texto: str, pasta: Path | None = None) -> Path | None:
    """Grava um registro (cortado em ``MAX_BYTES``) e mantém a pasta pequena. ``None`` se não deu."""
    pasta = Path(pasta) if pasta is not None else (_pasta or pasta_logs())
    dados = texto.encode("utf-8", "replace")
    if len(dados) > MAX_BYTES:
        dados = dados[: MAX_BYTES // 4] + b"\n...\n" + dados[-(MAX_BYTES * 3 // 4):]
    agora = time.time()
    carimbo = time.strftime("%Y%m%d-%H%M%S", time.localtime(agora)) + f"{int(agora * 1000) % 1000:03d}"
    try:
        pasta.mkdir(parents=True, exist_ok=True)
        caminho = pasta / f"{PREFIXO}{carimbo}.txt"
        n = 1
        while caminho.exists():
            n += 1
            caminho = pasta / f"{PREFIXO}{carimbo}_{n}.txt"
        caminho.write_bytes(dados)
    except OSError:
        return None
    _limpar(pasta)
    return caminho


def _tratar(tipo, exc, tb, onde: str) -> None:
    texto = formatar(tipo, exc, tb, onde)
    caminho = gravar(texto)
    if ao_gravar is not None:
        try:
            ao_gravar(caminho, texto)
        except Exception:  # noqa: BLE001 - o aviso nunca pode gerar outro erro
            pass


def _imprimir(tipo, exc, tb) -> None:
    if sys.stderr is not None:
        try:
            traceback.print_exception(tipo, exc, tb)
        except Exception:  # noqa: BLE001
            pass


def _excepthook(tipo, exc, tb) -> None:
    if issubclass(tipo, KeyboardInterrupt):
        sys.__excepthook__(tipo, exc, tb)
        return
    _imprimir(tipo, exc, tb)
    _tratar(tipo, exc, tb, threading.current_thread().name)


def _thread_excepthook(args) -> None:
    if args.exc_type is SystemExit:
        return
    _imprimir(args.exc_type, args.exc_value, args.exc_traceback)
    nome = args.thread.name if args.thread is not None else "?"
    _tratar(args.exc_type, args.exc_value, args.exc_traceback, f"thread {nome}")


def instalar(pasta: Path | None = None) -> None:
    """Liga os dois ganchos de exceção (idempotente). ``pasta`` troca a pasta dos registros (testes)."""
    global _antigos, _pasta
    _pasta = Path(pasta) if pasta is not None else None
    if _antigos is None:
        _antigos = (sys.excepthook, threading.excepthook)
    sys.excepthook = _excepthook
    threading.excepthook = _thread_excepthook


def desinstalar() -> None:
    """Devolve os ganchos que havia antes de ``instalar()``."""
    global _antigos, _pasta
    if _antigos is not None:
        sys.excepthook, threading.excepthook = _antigos
        _antigos = None
    _pasta = None
