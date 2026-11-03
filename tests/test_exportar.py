"""Exportação para revelação (sem Qt): plano, nomes, JPEG, pedido.txt, erros e fidelidade à prévia."""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from revelador import exportar, imagem, receita, tamanhos
from revelador.projeto import Foto, Impressao, Recorte, Trabalho

HOJE = date(2026, 3, 9)


def gerar(pasta: Path, nome: str, largura: int, altura: int, exif_data: str | None = None,
          orientacao: int | None = None) -> Path:
    """Foto sintética com gradientes (assim o recorte e as cores são conferíveis)."""
    x = np.linspace(0, 255, largura, dtype=np.float32)[None, :]
    y = np.linspace(0, 255, altura, dtype=np.float32)[:, None]
    rgb = np.stack([np.broadcast_to(x, (altura, largura)), np.broadcast_to(y, (altura, largura)),
                    np.broadcast_to((x + y) / 2, (altura, largura))], axis=-1).astype(np.uint8)
    caminho = pasta / nome
    exif = Image.Exif()
    if exif_data:
        exif.get_ifd(0x8769)[0x9003] = exif_data
        exif[0x010F] = "Marca"
    if orientacao:
        exif[0x0112] = orientacao
    Image.fromarray(rgb).save(caminho, quality=95, exif=exif.tobytes())
    return caminho


def foto(caminho: Path, *impressoes: Impressao, selecionada: bool = True) -> Foto:
    st = caminho.stat()
    return Foto(id=caminho.stem, caminho=caminho, bytes=st.st_size, mtime=st.st_mtime, selecionada=selecionada,
                impressoes=list(impressoes))


def sha(caminho: Path) -> str:
    return hashlib.sha256(caminho.read_bytes()).hexdigest()


@pytest.fixture
def fotos(tmp_path):
    pasta = tmp_path / "fotos"
    pasta.mkdir()
    return pasta


@pytest.fixture
def saida(tmp_path):
    return tmp_path / "saida"


def rel(plano_ou_resultado, pasta: Path) -> list[str]:
    return sorted(p.relative_to(pasta).as_posix() for p in pasta.rglob("*") if p.is_file())


# ------------------------------------------------------------------------------------------ pixels / JPEG

@pytest.mark.parametrize("tam,orient,larg,alt", [
    ("10x15", "auto", 1800, 1200),     # foto deitada -> paisagem
    ("10x15", "auto", 1200, 1800),     # foto em pé -> retrato
    ("13x18", "retrato", 1800, 1200),
    ("a4", "paisagem", 1200, 1800),
    ("15x15", "auto", 1500, 1000),
])
@pytest.mark.parametrize("dpi", [300, 200])
def test_pixels_exatos_dpi_e_perfil(fotos, saida, tam, orient, larg, alt, dpi):
    caminho = gerar(fotos, "a.jpg", larg, alt)
    t = Trabalho(fotos=[foto(caminho, Impressao(tamanho=tam, orientacao=orient))])
    r = exportar.executar(exportar.planejar(t, saida, dpi=dpi, hoje=HOJE))
    assert not r.erros and len(r.arquivos) == 1
    orient_ef = tamanhos.orientacao_efetiva(orient, larg, alt)
    esperado = tamanhos.px(tam, orient_ef, dpi)
    with Image.open(r.arquivos[0]) as im:
        assert im.size == esperado
        assert round(im.info["dpi"][0]) == dpi and round(im.info["dpi"][1]) == dpi
        assert im.info["icc_profile"] == exportar.perfil_srgb()
        assert im.format == "JPEG" and im.mode == "RGB"


def test_jpeg_baseline_444_qualidade_95_sem_orientacao_nem_gps(fotos, saida):
    caminho = gerar(fotos, "a.jpg", 1800, 1200, exif_data="2024:05:06 07:08:09", orientacao=1)
    t = Trabalho(fotos=[foto(caminho, Impressao())])
    r = exportar.executar(exportar.planejar(t, saida, hoje=HOJE))
    with Image.open(r.arquivos[0]) as im:
        assert "progressive" not in im.info and "progression" not in im.info
        assert im.layer[0][1:3] == (1, 1) and im.layer[1][1:3] == (1, 1)    # 4:4:4: sem subamostragem
        luma = im.quantization[0]
        ref = Image.new("RGB", (8, 8))
        import io
        buf = io.BytesIO()
        ref.save(buf, "JPEG", quality=95, subsampling=0)
        assert list(luma) == list(Image.open(io.BytesIO(buf.getvalue())).quantization[0])   # q95 do Pillow
        exif = im.getexif()
        assert 0x0112 not in exif and 0x8825 not in exif                  # sem orientação e sem GPS
        assert 0x010F not in exif                                         # nem fabricante
        assert exif.get_ifd(0x8769)[0x9003] == "2024:05:06 07:08:09"      # só a data original


def test_sem_data_nao_grava_exif(fotos, saida):
    caminho = gerar(fotos, "a.jpg", 1800, 1200)
    t = Trabalho(fotos=[foto(caminho, Impressao())])
    r = exportar.executar(exportar.planejar(t, saida, hoje=HOJE))
    with Image.open(r.arquivos[0]) as im:
        assert len(im.getexif()) == 0


def test_foto_com_orientacao_exif_sai_em_pe_e_sem_a_tag(fotos, saida):
    caminho = gerar(fotos, "a.jpg", 1800, 1200, orientacao=6)     # gira 90°: fica em pé (1200x1800)
    assert imagem.abrir_info(caminho).largura == 1200
    t = Trabalho(fotos=[foto(caminho, Impressao())])
    r = exportar.executar(exportar.planejar(t, saida, hoje=HOJE))
    with Image.open(r.arquivos[0]) as im:
        assert im.size == tamanhos.px("10x15", "retrato", 300)
        assert 0x0112 not in im.getexif()


def test_exportada_reduzida_bate_com_a_previa(fotos, saida):
    caminho = gerar(fotos, "a.jpg", 2400, 1600)
    imp = Impressao(tamanho="13x18", recorte=Recorte(cx=0.4, cy=0.55, zoom=1.5, angulo=3.0, origem="manual"))
    f = foto(caminho, imp)
    f.ajustes = {"exposicao": 0.3}
    t = Trabalho(fotos=[f])
    r = exportar.executar(exportar.planejar(t, saida, hoje=HOJE))
    with Image.open(r.arquivos[0]) as im:
        exportada = np.asarray(im, dtype=np.float32) / 255.0
        tam = im.size
    pequeno = (tam[0] // 8, tam[1] // 8)
    previa = receita.renderizar(receita.carregar_fonte(caminho, "proxy"), imp, f.ajustes, pequeno)
    import cv2
    reduzida = cv2.resize(exportada, pequeno, interpolation=cv2.INTER_AREA)
    assert np.abs(reduzida - previa).mean() < 0.02


# ------------------------------------------------------------------------------------- pastas e nomes

def trabalho_misto(fotos: Path) -> Trabalho:
    a = gerar(fotos, "IMG_1.jpg", 900, 600)
    b = gerar(fotos, "IMG_2.jpg", 600, 900)
    c = gerar(fotos, "IMG_3.jpg", 900, 600)
    return Trabalho(fotos=[
        foto(a, Impressao(tamanho="10x15", copias=1), Impressao(tamanho="10x15", copias=3)),   # mesma foto, 2x
        foto(b, Impressao(tamanho="a4", copias=2)),
        foto(c, Impressao(tamanho="10x15"), selecionada=False),
    ])


def test_modo_pastas(fotos, saida):
    r = exportar.executar(exportar.planejar(trabalho_misto(fotos), saida, exportar.MODO_PASTAS, 100, hoje=HOJE))
    raiz = saida / "Revelação 2026-03-09"
    assert rel(r, raiz) == sorted([
        "10x15/1 cópia/IMG_1.jpg", "10x15/3 cópias/IMG_1.jpg",
        "A4 (21x29,7)/2 cópias/IMG_2.jpg", "pedido.txt",
    ])


def test_modo_pastas_sem_subpasta_quando_todas_sao_uma_copia(fotos, saida):
    a = gerar(fotos, "IMG_1.jpg", 900, 600)
    b = gerar(fotos, "IMG_2.jpg", 900, 600)
    t = Trabalho(fotos=[foto(a, Impressao()), foto(b, Impressao(tamanho="a4", copias=2))])
    exportar.executar(exportar.planejar(t, saida, exportar.MODO_PASTAS, 100, hoje=HOJE))
    raiz = saida / "Revelação 2026-03-09"
    assert rel(None, raiz) == sorted(["10x15/IMG_1.jpg", "A4 (21x29,7)/2 cópias/IMG_2.jpg", "pedido.txt"])


def test_modo_nome(fotos, saida):
    exportar.executar(exportar.planejar(trabalho_misto(fotos), saida, exportar.MODO_NOME, 100, hoje=HOJE))
    raiz = saida / "Revelação 2026-03-09"
    assert rel(None, raiz) == sorted([
        "10x15/IMG_1 (1 cópia).jpg", "10x15/IMG_1 (3 cópias).jpg", "A4 (21x29,7)/IMG_2 (2 cópias).jpg", "pedido.txt",
    ])


def test_modo_repetir(fotos, saida):
    exportar.executar(exportar.planejar(trabalho_misto(fotos), saida, exportar.MODO_REPETIR, 100, hoje=HOJE))
    raiz = saida / "Revelação 2026-03-09"
    # IMG_1: 1 + 3 cópias no mesmo tamanho = 4 arquivos, sem colisão
    assert rel(None, raiz) == sorted([
        "10x15/IMG_1.jpg", "10x15/IMG_1 - 2.jpg", "10x15/IMG_1 - 3.jpg", "10x15/IMG_1 - 4.jpg",
        "A4 (21x29,7)/IMG_2.jpg", "A4 (21x29,7)/IMG_2 - 2.jpg", "pedido.txt",
    ])


def test_mesma_foto_duas_vezes_no_mesmo_tamanho_ganha_sufixo(fotos, saida):
    a = gerar(fotos, "IMG_1.jpg", 900, 600)
    t = Trabalho(fotos=[foto(a, Impressao(), Impressao())])
    p = exportar.planejar(t, saida, exportar.MODO_PASTAS, 100, hoje=HOJE)
    nomes = [d.name for i in p.itens for d in i.destinos]
    assert nomes == ["IMG_1.jpg", "IMG_1 - 2.jpg"]


def test_nomes_iguais_de_pastas_diferentes_nao_colidem(fotos, tmp_path, saida):
    outra = tmp_path / "outra"
    outra.mkdir()
    a = gerar(fotos, "IMG.jpg", 900, 600)
    b = gerar(outra, "IMG.JPG", 900, 600)
    t = Trabalho(fotos=[foto(a, Impressao()), foto(b, Impressao())])
    p = exportar.planejar(t, saida, hoje=HOJE)
    destinos = [str(d).lower() for i in p.itens for d in i.destinos]
    assert len(set(destinos)) == 2


def test_nao_sobrescreve_pasta_existente(fotos, saida):
    t = trabalho_misto(fotos)
    r1 = exportar.executar(exportar.planejar(t, saida, hoje=HOJE))
    antes = {p: sha(p) for p in r1.arquivos}
    r2 = exportar.executar(exportar.planejar(t, saida, hoje=HOJE))
    r3 = exportar.executar(exportar.planejar(t, saida, hoje=HOJE))
    assert sorted(p.name for p in saida.iterdir()) == [
        "Revelação 2026-03-09", "Revelação 2026-03-09 (2)", "Revelação 2026-03-09 (3)"]
    assert {p: sha(p) for p in r1.arquivos} == antes
    assert r2.pedido.parent.name.endswith("(2)") and r3.pedido.parent.name.endswith("(3)")


def test_gravar_nao_sobrescreve_arquivo_que_apareceu_no_meio(tmp_path):
    destino = tmp_path / "x.jpg"
    destino.write_bytes(b"outro")
    final = exportar._gravar_bytes(destino, b"novo")
    assert destino.read_bytes() == b"outro" and final.name == "x (2).jpg" and final.read_bytes() == b"novo"
    assert not list(tmp_path.glob("*.tmp"))


def test_original_intacto_e_sem_tmp(fotos, saida):
    t = trabalho_misto(fotos)
    antes = {f.caminho: (sha(f.caminho), f.caminho.stat().st_mtime_ns) for f in t.fotos}
    exportar.executar(exportar.planejar(t, saida, hoje=HOJE))
    for caminho, (h, m) in antes.items():
        assert sha(caminho) == h and caminho.stat().st_mtime_ns == m
    assert sorted(p.name for p in fotos.iterdir()) == ["IMG_1.jpg", "IMG_2.jpg", "IMG_3.jpg"]
    assert not list(saida.rglob("*.tmp"))


def test_modelo_nao_e_alterado_e_plano_e_copia(fotos, saida):
    t = trabalho_misto(fotos)
    p = exportar.planejar(t, saida, hoje=HOJE)
    t.fotos[0].impressoes[0].copias = 9
    assert p.itens[0].impressao.copias == 1 and p.trabalho is not t
    assert not saida.exists()     # planejar não toca no disco


# -------------------------------------------------------------------------------- pedido.txt / erros

def test_pedido_txt_com_totais_e_aviso_de_parcial(fotos, saida):
    t = trabalho_misto(fotos)
    p = exportar.planejar(t, saida, exportar.MODO_PASTAS, 100, {"10x15": 150}, hoje=HOJE)
    r = exportar.executar(p)
    texto = r.pedido.read_text(encoding="utf-8")
    assert r.pedido == p.pasta / "pedido.txt"
    assert "10x15: 1 foto(s), 4 cópia(s) — R$ 1,50 por cópia, subtotal R$ 6,00" in texto
    assert "A4 (21x29,7): 1 foto(s), 2 cópia(s) — sem preço" in texto
    assert "Total estimado PARCIAL" in texto and "R$ 6,00" in texto
    assert "estimado" in texto
    assert "Total: 2 foto(s), 6 cópia(s), 3 arquivo(s)" in texto
    assert "10x15/3 cópias/IMG_1.jpg  (3 cópias)" in texto
    assert "Resolução: 100 dpi" in texto and "09/03/2026" in texto


def test_pedido_txt_completo(fotos, saida):
    t = trabalho_misto(fotos)
    r = exportar.executar(exportar.planejar(t, saida, tabela_precos={"10x15": 150, "a4": 1000}, hoje=HOJE))
    texto = r.pedido.read_text(encoding="utf-8")
    assert "Total estimado: R$ 26,00" in texto and "PARCIAL" not in texto


def test_erro_num_item_nao_derruba_os_outros(fotos, saida):
    ruim = fotos / "ruim.jpg"
    ruim.write_bytes(b"isto nao e uma imagem")
    bom = gerar(fotos, "bom.jpg", 900, 600)
    sumiu = foto(bom, Impressao())
    sumiu.id, sumiu.caminho = "sumiu", fotos / "nao_existe.jpg"
    t = Trabalho(fotos=[foto(ruim, Impressao()), foto(bom, Impressao()), sumiu])
    r = exportar.executar(exportar.planejar(t, saida, exportar.MODO_PASTAS, 100, hoje=HOJE))
    assert [i.foto.caminho.name for i in r.feitos] == ["bom.jpg"]
    assert len(r.erros) == 2 and all(isinstance(m, str) and m for _i, m in r.erros)
    assert (saida / "Revelação 2026-03-09" / "10x15" / "bom.jpg").is_file()
    texto = r.pedido.read_text(encoding="utf-8")
    assert "2 item(ns) não foram exportados" in texto
    assert not list(saida.rglob("*.tmp"))


def test_cancelar_nao_deixa_tmp_nem_pedido(fotos, saida):
    t = trabalho_misto(fotos)
    p = exportar.planejar(t, saida, hoje=HOJE)
    r = exportar.executar(p, cancelado=lambda: True)
    assert r.cancelado and r.arquivos == [] and r.pedido is None
    assert not list(saida.rglob("*.tmp")) and not list(saida.rglob("*.jpg"))


def test_cancelar_no_meio_mantem_o_que_ficou_pronto(fotos, saida):
    t = trabalho_misto(fotos)
    p = exportar.planejar(t, saida, hoje=HOJE)
    estado = {"n": 0}

    def progresso(feitos, total):
        estado["n"] = feitos

    r = exportar.executar(p, ao_progresso=progresso, cancelado=lambda: estado["n"] >= 1, trabalhadores=1)
    assert r.cancelado and len(r.arquivos) == 1 and not list(saida.rglob("*.tmp"))
    assert all(a.is_file() for a in r.arquivos)


def test_progresso_chega_ao_total(fotos, saida):
    vistos = []
    exportar.executar(exportar.planejar(trabalho_misto(fotos), saida, hoje=HOJE),
                      ao_progresso=lambda f, tot: vistos.append((f, tot)))
    assert sorted(vistos) == [(1, 3), (2, 3), (3, 3)]


# ------------------------------------------------------------------------------------------ conferência

def test_conferir(fotos):
    a = gerar(fotos, "a.jpg", 900, 600)
    b = gerar(fotos, "b.jpg", 900, 600)
    c = gerar(fotos, "c.jpg", 900, 600)
    pequena = foto(a, Impressao(tamanho="30x45"))          # 900 px para 30 cm: ~76 dpi
    mudou = foto(b, Impressao())
    mudou.bytes += 5
    sumiu = foto(c, Impressao())
    sumiu.caminho = fotos / "x.jpg"
    sem = foto(c, selecionada=True)
    sem.id = "sem"
    fora = foto(c, Impressao(tamanho="30x45"), selecionada=False)
    fora.id = "fora"
    t = Trabalho(fotos=[pequena, mudou, sumiu, sem, fora])
    infos = {pequena.id: imagem.abrir_info(a)}
    por_tipo = {av.tipo: av.foto_id for av in exportar.conferir(t, infos)}
    assert por_tipo == {"baixa": "a", "mudou": "b", "sumiu": "c", "sem_impressao": "sem"}
