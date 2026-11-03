"""Carregar fotos: formatos, orientação EXIF, cor em sRGB, proxy com cache em memória.

Sem Qt. Nunca escreve nos arquivos originais. A "imagem orientada" (EXIF já aplicado) é a base de todas as
coordenadas do app; a cor de trabalho é sempre sRGB, float32 0..1, formato H×W×3.
"""

from __future__ import annotations

import io
import os
import threading
from collections import OrderedDict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image, ImageCms, UnidentifiedImageError

from .i18n import _

FORMATOS = frozenset({".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".tif", ".tiff"})

LADO_PROXY = 2048
LIMITE_CACHE_BYTES = 512 * 1024**2

_TAG_ORIENTACAO = 0x0112
_TAG_MODELO = 0x0110
_TAG_FABRICANTE = 0x010F
_TAG_DATA = 0x0132
_TAG_EXIF_IFD = 0x8769
_TAG_DATA_ORIGINAL = 0x9003

_TRANSPOSICOES = {
    2: Image.Transpose.FLIP_LEFT_RIGHT,
    3: Image.Transpose.ROTATE_180,
    4: Image.Transpose.FLIP_TOP_BOTTOM,
    5: Image.Transpose.TRANSPOSE,
    6: Image.Transpose.ROTATE_270,
    7: Image.Transpose.TRANSVERSE,
    8: Image.Transpose.ROTATE_90,
}

_heif_registrado = False
_trava_heif = threading.Lock()


class ErroImagem(Exception):
    """Foto que não abre; a mensagem já é amigável e traduzida, pronta para a pessoa ler."""


@dataclass
class InfoFoto:
    """Metadados leves de uma foto (sem decodificar a imagem inteira)."""

    largura: int                 # px, já orientada
    altura: int                  # px, já orientada
    data: datetime | None        # data original do EXIF (DateTimeOriginal)
    camera: str | None
    perfil: str | None           # nome do perfil de cor embutido; None = sem perfil (assume sRGB)
    bytes: int
    mtime: int                   # st_mtime_ns do arquivo


def registrar_heif() -> None:
    """Registra o leitor HEIC/HEIF no Pillow (idempotente e seguro entre threads)."""
    global _heif_registrado
    with _trava_heif:
        if _heif_registrado:
            return
        import pillow_heif
        pillow_heif.register_heif_opener()
        _heif_registrado = True


def listar_fotos(caminhos: Iterable[str | os.PathLike]) -> list[Path]:
    """Arquivos e pastas (recursivo) -> fotos de formato aceito, sem repetidas, em ordem estável.

    A ordem segue a dos ``caminhos`` dados; dentro de cada pasta, a ordem alfabética (sem diferenciar caixa).
    """
    vistos: set[str] = set()
    saida: list[Path] = []

    def _juntar(p: Path) -> None:
        chave = os.path.normcase(os.path.abspath(p))
        if chave not in vistos:
            vistos.add(chave)
            saida.append(p)

    for bruto in caminhos:
        p = Path(bruto)
        if p.is_dir():
            achados = [f for f in p.rglob("*") if f.suffix.lower() in FORMATOS and f.is_file()]
            for f in sorted(achados, key=lambda f: [s.lower() for s in f.relative_to(p).parts]):
                _juntar(f)
        elif p.is_file() and p.suffix.lower() in FORMATOS:
            _juntar(p)
    return saida


# ---------------------------------------------------------------------------------------------------------------
# Abertura
# ---------------------------------------------------------------------------------------------------------------

def _msg_corrompido(nome: str) -> str:
    return _("Não foi possível abrir \"{nome}\": o arquivo parece estar corrompido.").format(nome=nome)


def _abrir(caminho: Path) -> Image.Image:
    """Abre (preguiçosamente) ou levanta ErroImagem com mensagem amigável."""
    nome = caminho.name
    if not caminho.is_file():
        raise ErroImagem(_("O arquivo \"{nome}\" não foi encontrado.").format(nome=nome))
    if caminho.suffix.lower() not in FORMATOS:
        raise ErroImagem(_("O formato de \"{nome}\" não é suportado.").format(nome=nome))
    try:
        registrar_heif()
        return Image.open(caminho)
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, Image.DecompressionBombError) as e:
        raise ErroImagem(_msg_corrompido(nome)) from e


def _orientacao(img: Image.Image) -> int:
    try:
        valor = int(img.getexif().get(_TAG_ORIENTACAO, 1))
    except (ValueError, TypeError, SyntaxError, OSError):
        return 1
    return valor if 1 <= valor <= 8 else 1


def _nome_perfil(icc: bytes | None) -> str | None:
    if not icc:
        return None
    try:
        nome = ImageCms.getProfileDescription(ImageCms.ImageCmsProfile(io.BytesIO(icc))).strip()
    except Exception:  # perfil ilegível: ainda assim existe um perfil
        return _("(desconhecido)")
    return nome or _("(sem nome)")


def _texto_exif(valor: object) -> str | None:
    if isinstance(valor, bytes):
        valor = valor.decode("utf-8", "replace")
    if not isinstance(valor, str):
        return None
    valor = valor.replace("\x00", "").strip()
    return valor or None


def _data_exif(exif: Image.Exif) -> datetime | None:
    candidatos: list[object] = []
    try:
        candidatos.append(exif.get_ifd(_TAG_EXIF_IFD).get(_TAG_DATA_ORIGINAL))
    except Exception:
        pass
    candidatos.append(exif.get(_TAG_DATA))
    for c in candidatos:
        texto = _texto_exif(c)
        if texto:
            try:
                return datetime.strptime(texto[:19], "%Y:%m:%d %H:%M:%S")
            except ValueError:
                continue
    return None


def abrir_info(caminho: str | os.PathLike) -> InfoFoto:
    """Metadados da foto sem decodificar os pixels."""
    caminho = Path(caminho)
    img = _abrir(caminho)
    try:
        with img:
            largura, altura = img.size
            if _orientacao(img) >= 5:
                largura, altura = altura, largura
            try:
                exif = img.getexif()
            except Exception:
                exif = Image.Exif()
            modelo = _texto_exif(exif.get(_TAG_MODELO))
            fabricante = _texto_exif(exif.get(_TAG_FABRICANTE))
            if modelo and fabricante and not modelo.lower().startswith(fabricante.lower().split()[0]):
                modelo = f"{fabricante} {modelo}"
            st = caminho.stat()
            return InfoFoto(largura, altura, _data_exif(exif), modelo or fabricante,
                            _nome_perfil(img.info.get("icc_profile")), st.st_size, st.st_mtime_ns)
    except ErroImagem:
        raise
    except Exception as e:
        raise ErroImagem(_msg_corrompido(caminho.name)) from e


# ---------------------------------------------------------------------------------------------------------------
# Carregamento
# ---------------------------------------------------------------------------------------------------------------

def _reduzir_draft(img: Image.Image, lado_max: int) -> None:
    """JPEG: decodificação reduzida pelo DCT (várias vezes mais rápida); mantém lado maior >= lado_max."""
    if img.format != "JPEG":
        return
    maior = max(img.size)
    if maior <= lado_max:
        return
    k = lado_max / maior
    try:
        img.draft(None, (max(1, round(img.width * k)), max(1, round(img.height * k))))
    except Exception:
        pass


def _para_float(img: Image.Image) -> np.ndarray:
    """Modos de 16/32 bits (cinza) -> H×W float32 0..1."""
    a = np.asarray(img).astype(np.float32)
    if img.mode.startswith("I;16"):
        return a / 65535.0
    if img.mode == "I":
        return a / (65535.0 if a.max() > 255 else 255.0)
    return a


_srgb_perfil: ImageCms.ImageCmsProfile | None = None


def _srgb() -> ImageCms.ImageCmsProfile:
    global _srgb_perfil
    if _srgb_perfil is None:
        _srgb_perfil = ImageCms.createProfile("sRGB")
    return _srgb_perfil


def _converter_perfil(img: Image.Image, origem: ImageCms.ImageCmsProfile) -> Image.Image:
    return ImageCms.profileToProfile(img, origem, _srgb(), renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC,
                                     flags=ImageCms.Flags.BLACKPOINTCOMPENSATION, outputMode="RGB")


def _para_srgb(img: Image.Image, icc: bytes | None) -> Image.Image:
    """RGB/CMYK com perfil embutido -> sRGB; sem perfil utilizável, assume sRGB (CMYK: conversão simples)."""
    try:
        if icc:
            origem = ImageCms.ImageCmsProfile(io.BytesIO(icc))
            espaco = origem.profile.xcolor_space.strip()
            if img.mode == "CMYK" and espaco == "CMYK":
                return _converter_perfil(img, origem)
            if img.mode == "RGB" and espaco == "RGB" and "srgb" not in ImageCms.getProfileDescription(origem).lower():
                return _converter_perfil(img, origem)
    except Exception:  # perfil quebrado: segue sem ele
        pass
    return img.convert("RGB") if img.mode == "CMYK" else img


def _sobre_branco(img: Image.Image) -> Image.Image:
    fundo = Image.new("RGB", img.size, (255, 255, 255))
    fundo.paste(img, mask=img.getchannel("A"))
    return fundo


def _tamanho_reduzido(tamanho: tuple[int, int], lado_max: int) -> tuple[int, int]:
    k = lado_max / max(tamanho)
    return max(1, round(tamanho[0] * k)), max(1, round(tamanho[1] * k))


def _orientar(img: Image.Image, orientacao: int) -> Image.Image:
    op = _TRANSPOSICOES.get(orientacao)
    return img.transpose(op) if op is not None else img


def _decodificar(img: Image.Image, lado_max: int | None) -> np.ndarray:
    icc = img.info.get("icc_profile")
    orientacao = _orientacao(img)
    if lado_max:
        _reduzir_draft(img, lado_max)
    modo = img.mode

    if modo.startswith("I;16") or modo in ("I", "F"):
        cinza = Image.fromarray(_para_float(img), "F")
        if lado_max and max(cinza.size) > lado_max:
            cinza = cinza.resize(_tamanho_reduzido(cinza.size, lado_max), Image.Resampling.LANCZOS)
        cinza = _orientar(cinza, orientacao)
        a = np.clip(np.asarray(cinza, dtype=np.float32), 0.0, 1.0)
        return np.ascontiguousarray(np.repeat(a[:, :, None], 3, axis=2))

    if modo not in ("RGB", "RGBA", "CMYK"):
        # P, L, LA, PA, 1...: tudo vira RGB(A); transparência (canal alfa ou tRNS) é preservada até compor
        tem_alfa = "A" in modo or "transparency" in img.info
        img = img.convert("RGBA" if tem_alfa else "RGB")
    elif modo == "RGB" and "transparency" in img.info:
        img = img.convert("RGBA")

    if lado_max and max(img.size) > lado_max:
        img = img.resize(_tamanho_reduzido(img.size, lado_max), Image.Resampling.LANCZOS)
    if img.mode == "RGBA":
        img = _sobre_branco(img)
    img = _para_srgb(img, icc)
    img = _orientar(img, orientacao)
    return np.ascontiguousarray(np.asarray(img, dtype=np.float32) / 255.0)


def carregar(caminho: str | os.PathLike, lado_max: int | None = None) -> np.ndarray:
    """Foto -> float32 0..1, H×W×3, sRGB, orientada. Com ``lado_max``, o lado maior sai <= ``lado_max``."""
    caminho = Path(caminho)
    img = _abrir(caminho)
    try:
        with img:
            return _decodificar(img, lado_max)
    except ErroImagem:
        raise
    except Exception as e:
        raise ErroImagem(_msg_corrompido(caminho.name)) from e


# ---------------------------------------------------------------------------------------------------------------
# Proxy com cache LRU em memória
# ---------------------------------------------------------------------------------------------------------------

_cache: OrderedDict[tuple, np.ndarray] = OrderedDict()
_cache_bytes = 0
_trava_cache = threading.Lock()


def proxy(caminho: str | os.PathLike, lado: int = LADO_PROXY) -> np.ndarray:
    """Cópia reduzida (lado maior <= ``lado``) com cache LRU por bytes (~512 MB), segura entre threads.

    O array devolvido é compartilhado e somente leitura: copie antes de alterar.
    """
    global _cache_bytes
    caminho = Path(caminho)
    try:
        st = caminho.stat()
    except OSError:
        raise ErroImagem(_("O arquivo \"{nome}\" não foi encontrado.").format(nome=caminho.name)) from None
    chave = (os.path.normcase(os.path.abspath(caminho)), st.st_size, st.st_mtime_ns, lado)
    with _trava_cache:
        achado = _cache.get(chave)
        if achado is not None:
            _cache.move_to_end(chave)
            return achado
    a = carregar(caminho, lado)
    a.flags.writeable = False
    with _trava_cache:
        antigo = _cache.pop(chave, None)
        if antigo is not None:
            _cache_bytes -= antigo.nbytes
        _cache[chave] = a
        _cache_bytes += a.nbytes
        while _cache_bytes > LIMITE_CACHE_BYTES and len(_cache) > 1:
            _, saiu = _cache.popitem(last=False)
            _cache_bytes -= saiu.nbytes
    return a


def limpar_cache() -> None:
    """Esvazia o cache de proxies."""
    global _cache_bytes
    with _trava_cache:
        _cache.clear()
        _cache_bytes = 0
