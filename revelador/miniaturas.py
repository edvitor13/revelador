"""Cache de miniaturas em disco (JPEG q85, lado maior 320 px). Sem Qt: as threads ficam com a interface."""

from __future__ import annotations

import hashlib
import os
import threading
import uuid
from pathlib import Path

import numpy as np
from PIL import Image

from . import imagem
from .i18n import _

LADO_PADRAO = 320
QUALIDADE = 85
LIMITE_PADRAO = 500 * 1024**2


def pasta_cache() -> Path:
    """``%LOCALAPPDATA%\\Revelador\\cache\\miniaturas`` (fora do Windows: ``$XDG_CACHE_HOME`` ou ``~/.cache``)."""
    base = os.environ.get("LOCALAPPDATA")
    if base:
        raiz = Path(base) / "Revelador" / "cache"
    else:
        raiz = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "Revelador"
    return raiz / "miniaturas"


def chave(caminho: str | os.PathLike, bytes: int, mtime: int | float, lado: int) -> str:
    """sha1 de (caminho, bytes, mtime, lado): muda quando o arquivo muda."""
    ident = f"{os.path.normcase(os.path.abspath(caminho))}|{bytes}|{mtime}|{lado}"
    return hashlib.sha1(ident.encode("utf-8")).hexdigest()


def obter(caminho: str | os.PathLike, lado: int = LADO_PADRAO) -> Path:
    """Caminho do JPEG da miniatura no cache; gera se faltar (seguro se duas threads gerarem a mesma)."""
    caminho = Path(caminho)
    try:
        st = caminho.stat()
    except OSError:
        raise imagem.ErroImagem(_("O arquivo \"{nome}\" não foi encontrado.").format(nome=caminho.name)) from None
    pasta = pasta_cache()
    destino = pasta / f"{chave(caminho, st.st_size, st.st_mtime_ns, lado)}.jpg"
    if destino.is_file():
        try:
            os.utime(destino)  # "acessada agora": a limpeza apaga primeiro as menos usadas
        except OSError:
            pass
        return destino

    a = imagem.carregar(caminho, lado)
    pixels = np.clip(np.rint(a * 255.0), 0, 255).astype(np.uint8)
    pasta.mkdir(parents=True, exist_ok=True)
    tmp = pasta / f"{destino.stem}.{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex[:8]}.tmp"
    try:
        Image.fromarray(pixels, "RGB").save(tmp, format="JPEG", quality=QUALIDADE)
        try:
            os.replace(tmp, destino)
        except PermissionError:
            # Windows: outra thread acabou de gravar o mesmo destino; vale o dela se estiver lá
            if not destino.is_file():
                raise
    finally:
        tmp.unlink(missing_ok=True)
    return destino


def limpar(limite_bytes: int = LIMITE_PADRAO) -> None:
    """Apaga as miniaturas mais antigas (por mtime) até o cache caber em ``limite_bytes``."""
    pasta = pasta_cache()
    if not pasta.is_dir():
        return
    itens: list[tuple[float, int, Path]] = []
    for f in pasta.iterdir():
        try:
            if f.suffix == ".jpg" and f.is_file():
                st = f.stat()
                itens.append((st.st_mtime, st.st_size, f))
        except OSError:
            continue
    total = sum(i[1] for i in itens)
    for _mtime, tam, f in sorted(itens, key=lambda x: x[0]):
        if total <= limite_bytes:
            break
        try:
            f.unlink()
            total -= tam
        except OSError:
            pass
