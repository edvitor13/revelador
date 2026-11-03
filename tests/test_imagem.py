"""Carregamento de fotos: orientação, cor, transparência, formatos, proxy. Imagens geradas no código."""

from __future__ import annotations

import hashlib
import os
import struct
import threading
from datetime import datetime

import numpy as np
import pytest
from PIL import Image

from revelador import imagem
from revelador.imagem import ErroImagem


def _sha(p) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _perfil_adobe_rgb() -> bytes:
    """Perfil ICC v2 de matriz/curva: Adobe RGB (1998), colorantes adaptados a D50, gama 2,19921875."""
    def s15(v: float) -> bytes:
        return struct.pack(">i", round(v * 65536))

    def xyz(v) -> bytes:
        return b"XYZ \0\0\0\0" + b"".join(s15(c) for c in v)

    def texto(t: str) -> bytes:
        return b"text\0\0\0\0" + t.encode() + b"\0"

    nome = b"Adobe RGB teste\0"
    desc = b"desc\0\0\0\0" + struct.pack(">I", len(nome)) + nome + struct.pack(">II", 0, 0) + struct.pack(">HB", 0, 0) \
        + b"\0" * 67
    gama = b"curv\0\0\0\0" + struct.pack(">I", 1) + struct.pack(">H", 0x0233)
    tags = [
        (b"desc", desc), (b"cprt", texto("livre")), (b"wtpt", xyz((0.9642, 1.0, 0.8249))),
        (b"rXYZ", xyz((0.60974, 0.31111, 0.01947))), (b"gXYZ", xyz((0.20528, 0.62567, 0.06087))),
        (b"bXYZ", xyz((0.14919, 0.06322, 0.74457))), (b"rTRC", gama), (b"gTRC", gama), (b"bTRC", gama),
    ]
    offset = 128 + 4 + 12 * len(tags)
    tabela, corpo = b"", b""
    for sig, dados in tags:
        dados += b"\0" * (-len(dados) % 4)
        tabela += sig + struct.pack(">II", offset + len(corpo), len(dados))
        corpo += dados
    total = offset + len(corpo)
    cab = struct.pack(">I4sI4s4s4s", total, b"lcms", 0x02400000, b"mntr", b"RGB ", b"XYZ ")
    cab += b"\0" * 12 + b"acsp" + b"MSFT" + b"\0" * 4 + b"\0" * 4 + b"\0" * 4 + b"\0" * 8 + b"\0" * 4
    cab += s15(0.9642) + s15(1.0) + s15(0.8249) + b"\0" * 4
    cab = cab.ljust(128, b"\0")
    return cab + struct.pack(">I", len(tags)) + tabela + corpo


def _adobe_para_srgb(rgb8) -> np.ndarray:
    """Referência independente em numpy (matrizes D50)."""
    lin = (np.array(rgb8) / 255.0) ** 2.19921875
    m = np.array([[0.60974, 0.20528, 0.14919], [0.31111, 0.62567, 0.06322], [0.01947, 0.06087, 0.74457]])
    inv_srgb = np.array([[3.1338561, -1.6168667, -0.4906146], [-0.9787684, 1.9161415, 0.0334540],
                         [0.0719453, -0.2289914, 1.4052427]])
    s = np.clip(inv_srgb @ (m @ lin), 0, 1)
    cod = np.where(s <= 0.0031308, 12.92 * s, 1.055 * s ** (1 / 2.4) - 0.055)
    return cod * 255.0


@pytest.mark.parametrize("orient", range(1, 9))
def test_orientacao_exif(tmp_path, orient):
    # posição do canto superior esquerdo "de pé" dentro da imagem guardada, por orientação EXIF
    onde = {1: (0, 0), 2: (0, 1), 3: (1, 1), 4: (1, 0), 5: (0, 0), 6: (1, 0), 7: (1, 1), 8: (0, 1)}[orient]
    img = Image.new("RGB", (16, 8), (128, 128, 128))
    x0, y0 = onde[1] * 12, onde[0] * 4
    img.paste((255, 0, 0), (x0, y0, x0 + 4, y0 + 4))
    exif = Image.Exif()
    exif[0x0112] = orient
    p = tmp_path / "o.jpg"
    img.save(p, exif=exif, quality=95)

    a = imagem.carregar(p)
    assert a.shape == ((16, 8, 3) if orient >= 5 else (8, 16, 3))
    assert a.dtype == np.float32
    assert a[1, 1, 0] > 0.8 and a[1, 1, 1] < 0.3          # marcador vermelho no canto superior esquerdo
    assert abs(a[-2, -2, 0] - 0.5) < 0.1                    # canto oposto continua cinza
    info = imagem.abrir_info(p)
    assert (info.altura, info.largura) == a.shape[:2]


def test_perfil_adobe_rgb_vira_srgb(tmp_path):
    icc = _perfil_adobe_rgb()
    cor = (200, 100, 50)
    p = tmp_path / "a.jpg"
    Image.new("RGB", (32, 32), cor).save(p, icc_profile=icc, quality=100, subsampling=0)
    a = imagem.carregar(p)
    obtido = a[16, 16] * 255.0
    esperado = _adobe_para_srgb(cor)
    assert np.abs(obtido - esperado).max() < 4
    assert np.abs(obtido - np.array(cor)).max() > 10         # a cor realmente mudou
    assert imagem.abrir_info(p).perfil == "Adobe RGB teste"


def test_sem_perfil_assume_srgb(tmp_path):
    p = tmp_path / "s.png"
    Image.new("RGB", (8, 8), (10, 200, 30)).save(p)
    a = imagem.carregar(p)
    assert np.allclose(a[0, 0] * 255, (10, 200, 30), atol=0.5)
    assert imagem.abrir_info(p).perfil is None


def test_png_transparente_sobre_branco(tmp_path):
    img = Image.new("RGBA", (8, 8), (255, 0, 0, 0))
    img.putpixel((0, 0), (0, 0, 0, 255))
    p = tmp_path / "t.png"
    img.save(p)
    a = imagem.carregar(p)
    assert np.allclose(a[5, 5], 1.0)
    assert np.allclose(a[0, 0], 0.0)


def test_paleta_la_cinza_e_cmyk(tmp_path):
    pal = Image.new("P", (4, 4), 0)
    pal.putpalette([255, 0, 0] + [0] * 765)
    pal.save(tmp_path / "p.png", transparency=0)
    assert np.allclose(imagem.carregar(tmp_path / "p.png"), 1.0)  # índice 0 transparente -> branco

    Image.new("LA", (4, 4), (100, 255)).save(tmp_path / "la.png")
    assert np.allclose(imagem.carregar(tmp_path / "la.png"), 100 / 255, atol=0.01)

    Image.new("L", (4, 4), 50).save(tmp_path / "l.png")
    assert imagem.carregar(tmp_path / "l.png").shape == (4, 4, 3)

    Image.new("CMYK", (4, 4), (0, 0, 0, 0)).save(tmp_path / "c.jpg")
    a = imagem.carregar(tmp_path / "c.jpg")
    assert a.shape == (4, 4, 3) and a.mean() > 0.9


def test_16_bits(tmp_path):
    arr = np.full((6, 10), 32768, dtype=np.uint16)
    p = tmp_path / "g.png"
    Image.fromarray(arr).save(p)
    a = imagem.carregar(p)
    assert a.shape == (6, 10, 3)
    assert np.allclose(a, 32768 / 65535, atol=0.002)
    assert imagem.carregar(p, lado_max=5).shape[1] == 5


def test_heif(tmp_path):
    imagem.registrar_heif()
    imagem.registrar_heif()  # idempotente
    p = tmp_path / "h.heic"
    Image.new("RGB", (64, 48), (200, 30, 30)).save(p, format="HEIF")
    a = imagem.carregar(p)
    assert a.shape == (48, 64, 3)
    assert a[24, 32, 0] > 0.6 and a[24, 32, 1] < 0.3
    assert (imagem.abrir_info(p).largura, imagem.abrir_info(p).altura) == (64, 48)


def test_info_data_e_camera(tmp_path):
    exif = Image.Exif()
    exif[0x0110] = "Pixel 7"
    exif.get_ifd(0x8769)[0x9003] = "2024:05:06 07:08:09"
    p = tmp_path / "i.jpg"
    Image.new("RGB", (20, 10)).save(p, exif=exif)
    info = imagem.abrir_info(p)
    assert info.data == datetime(2024, 5, 6, 7, 8, 9)
    assert info.camera == "Pixel 7"
    assert info.bytes == p.stat().st_size and info.mtime == p.stat().st_mtime_ns


def test_erros_amigaveis(tmp_path):
    ruim = tmp_path / "ruim.jpg"
    ruim.write_bytes(b"isto nao e um jpeg")
    for f in (imagem.carregar, imagem.abrir_info, imagem.proxy):
        with pytest.raises(ErroImagem):
            f(ruim)
    with pytest.raises(ErroImagem, match="não foi encontrado"):
        imagem.carregar(tmp_path / "nao_existe.jpg")
    txt = tmp_path / "a.txt"
    txt.write_text("x")
    with pytest.raises(ErroImagem, match="não é suportado"):
        imagem.carregar(txt)


@pytest.mark.parametrize("formato", ["jpg", "png"])
def test_lado_max(tmp_path, formato):
    p = tmp_path / f"g.{formato}"
    Image.new("RGB", (900, 600), (90, 120, 200)).save(p)
    a = imagem.carregar(p, lado_max=200)
    assert max(a.shape[:2]) <= 200 and a.shape[:2] == (133, 200) or max(a.shape[:2]) == 200
    assert np.allclose(a[10, 10] * 255, (90, 120, 200), atol=3)
    assert imagem.carregar(p, lado_max=5000).shape[:2] == (600, 900)  # nunca amplia


def test_proxy_limite_e_cache(tmp_path):
    imagem.limpar_cache()
    p = tmp_path / "g.jpg"
    Image.new("RGB", (3000, 2000), (1, 2, 3)).save(p)
    a = imagem.proxy(p)
    assert max(a.shape[:2]) <= 2048
    assert imagem.proxy(p) is a                      # veio do cache
    assert max(imagem.proxy(p, lado=500).shape[:2]) <= 500
    imagem.limpar_cache()
    assert imagem.proxy(p) is not a


def test_proxy_lru_por_bytes(tmp_path, monkeypatch):
    imagem.limpar_cache()
    monkeypatch.setattr(imagem, "LIMITE_CACHE_BYTES", 2 * 100 * 100 * 3 * 4 + 10)
    ps = []
    for i in range(3):
        p = tmp_path / f"{i}.png"
        Image.new("RGB", (100, 100), (i, 0, 0)).save(p)
        ps.append(p)
    primeira = imagem.proxy(ps[0])
    imagem.proxy(ps[1])
    imagem.proxy(ps[2])                                # estoura: a mais antiga sai
    assert imagem.proxy(ps[0]) is not primeira
    imagem.limpar_cache()


def test_proxy_threads(tmp_path):
    imagem.limpar_cache()
    p = tmp_path / "g.jpg"
    Image.new("RGB", (800, 600), (5, 5, 5)).save(p)
    res = []
    ts = [threading.Thread(target=lambda: res.append(imagem.proxy(p, 256))) for _ in range(6)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(res) == 6 and all(r.shape == res[0].shape for r in res)
    imagem.limpar_cache()


def test_listar_fotos(tmp_path):
    (tmp_path / "sub" / "fundo").mkdir(parents=True)
    nomes = ["b.jpg", "A.PNG", "x.txt", "sub/c.heic", "sub/fundo/d.webp", "sub/e.TIFF", "sub/f.gif"]
    for n in nomes:
        (tmp_path / n).write_bytes(b"x")
    achadas = imagem.listar_fotos([tmp_path, tmp_path / "b.jpg", tmp_path / "x.txt"])
    rel = [p.relative_to(tmp_path).as_posix() for p in achadas]
    assert rel == ["A.PNG", "b.jpg", "sub/c.heic", "sub/e.TIFF", "sub/fundo/d.webp"]
    assert imagem.listar_fotos([tmp_path]) == achadas       # estável
    assert imagem.listar_fotos([tmp_path / "b.jpg", tmp_path / "b.jpg"]) == [tmp_path / "b.jpg"]


def test_original_intacto(tmp_path):
    p = tmp_path / "o.jpg"
    exif = Image.Exif()
    exif[0x0112] = 6
    Image.new("RGB", (64, 48), (9, 9, 9)).save(p, exif=exif, icc_profile=_perfil_adobe_rgb())
    antes, mt = _sha(p), os.stat(p).st_mtime_ns
    imagem.abrir_info(p)
    imagem.carregar(p)
    imagem.proxy(p, 32)
    assert _sha(p) == antes and os.stat(p).st_mtime_ns == mt
    imagem.limpar_cache()
