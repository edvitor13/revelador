"""Cache de miniaturas em disco."""

from __future__ import annotations

import hashlib
import os
import threading

from PIL import Image

from revelador import miniaturas


def _foto(tmp_path, nome="f.jpg", tam=(1200, 800), cor=(10, 120, 200)):
    p = tmp_path / nome
    Image.new("RGB", tam, cor).save(p)
    return p


def test_pasta_cache_no_localappdata():
    p = miniaturas.pasta_cache()
    assert p.parts[-3:] == ("Revelador", "cache", "miniaturas")
    assert str(p).startswith(os.environ["LOCALAPPDATA"])


def test_chave_muda_com_mtime_bytes_e_lado(tmp_path):
    p = _foto(tmp_path)
    base = miniaturas.chave(p, 100, 5, 320)
    assert base == miniaturas.chave(p, 100, 5, 320)
    assert len(base) == 40
    assert base != miniaturas.chave(p, 100, 6, 320)
    assert base != miniaturas.chave(p, 101, 5, 320)
    assert base != miniaturas.chave(p, 100, 5, 160)
    assert base != miniaturas.chave(tmp_path / "outra.jpg", 100, 5, 320)


def test_gera_uma_vez_e_reaproveita(tmp_path):
    p = _foto(tmp_path)
    m1 = miniaturas.obter(p)
    assert m1.is_file() and m1.parent == miniaturas.pasta_cache()
    with Image.open(m1) as im:
        assert im.format == "JPEG" and im.size == (320, 213)
    marca = m1.stat().st_mtime_ns
    m1.write_bytes(m1.read_bytes())          # conteúdo igual; só para ver se é regravada
    conteudo = m1.read_bytes()
    assert miniaturas.obter(p) == m1
    assert m1.read_bytes() == conteudo       # não regenerou
    assert not list(miniaturas.pasta_cache().glob("*.tmp"))
    assert marca  # só para usar a variável


def test_muda_o_arquivo_gera_outra(tmp_path):
    p = _foto(tmp_path)
    m1 = miniaturas.obter(p)
    st = p.stat()
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
    assert miniaturas.obter(p) != m1


def test_threads_geram_a_mesma(tmp_path):
    p = _foto(tmp_path, "t.jpg", (2000, 1000))
    res, erros = [], []

    def tarefa():
        try:
            res.append(miniaturas.obter(p))
        except Exception as e:  # pragma: no cover
            erros.append(e)

    ts = [threading.Thread(target=tarefa) for _ in range(6)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not erros and len(set(res)) == 1
    with Image.open(res[0]) as im:
        im.load()
    assert not list(miniaturas.pasta_cache().glob("*.tmp"))


def test_limpar_respeita_o_limite(tmp_path):
    pasta = miniaturas.pasta_cache()
    pasta.mkdir(parents=True, exist_ok=True)
    for f in pasta.glob("*"):
        f.unlink()
    for i in range(5):
        f = pasta / f"{i}.jpg"
        f.write_bytes(b"x" * 1000)
        os.utime(f, (1_000_000 + i, 1_000_000 + i))
    miniaturas.limpar(2500)
    restantes = sorted(f.name for f in pasta.glob("*.jpg"))
    assert restantes == ["3.jpg", "4.jpg"]       # os mais antigos saíram
    miniaturas.limpar(10**9)
    assert len(list(pasta.glob("*.jpg"))) == 2
    miniaturas.limpar(0)
    assert not list(pasta.glob("*.jpg"))


def test_original_intacto(tmp_path):
    p = _foto(tmp_path)
    antes = hashlib.sha256(p.read_bytes()).hexdigest()
    mt = p.stat().st_mtime_ns
    miniaturas.obter(p)
    assert hashlib.sha256(p.read_bytes()).hexdigest() == antes and p.stat().st_mtime_ns == mt
