"""Registro de erros: grava o arquivo, avisa a interface, mantém a pasta pequena."""

from __future__ import annotations

import sys
import threading

import pytest

from revelador import __version__, crashlog


@pytest.fixture(autouse=True)
def limpo():
    yield
    crashlog.desinstalar()
    crashlog.ao_gravar = None


def info():
    try:
        raise ValueError("deu errado aqui")
    except ValueError:
        return sys.exc_info()


def test_instalar_troca_e_desinstalar_devolve_os_ganchos(tmp_path):
    antes = (sys.excepthook, threading.excepthook)
    crashlog.instalar(tmp_path)
    assert sys.excepthook is crashlog._excepthook and threading.excepthook is crashlog._thread_excepthook
    crashlog.instalar(tmp_path)  # idempotente
    crashlog.desinstalar()
    assert (sys.excepthook, threading.excepthook) == antes


def test_excecao_vira_arquivo_e_avisa_a_interface(tmp_path):
    crashlog.instalar(tmp_path)
    vistos = []
    crashlog.ao_gravar = lambda caminho, texto: vistos.append((caminho, texto))
    sys.excepthook(*info())
    arquivos = list(tmp_path.iterdir())
    assert len(arquivos) == 1 and arquivos[0].name.startswith("erro-")
    texto = arquivos[0].read_text(encoding="utf-8")
    for parte in (f"Revelador {__version__}", "Sistema:", "Python:", "ValueError: deu errado aqui"):
        assert parte in texto
    assert vistos == [(arquivos[0], texto)]


def test_excecao_em_thread(tmp_path):
    crashlog.instalar(tmp_path)

    def falha():
        raise RuntimeError("na thread")

    t = threading.Thread(target=falha, name="trabalho")
    t.start()
    t.join()
    (arquivo,) = tmp_path.iterdir()
    texto = arquivo.read_text(encoding="utf-8")
    assert "Onde: thread trabalho" in texto and "na thread" in texto


def test_rotacao_e_limite_de_tamanho(tmp_path, monkeypatch):
    caminho = crashlog.gravar("x" * (crashlog.MAX_BYTES * 3), tmp_path)
    assert caminho.stat().st_size <= crashlog.MAX_BYTES + 16
    monkeypatch.setattr(crashlog, "MAX_ARQUIVOS", 4)
    for i in range(8):
        crashlog.gravar(f"registro {i}", tmp_path)
    nomes = sorted(p.name for p in tmp_path.iterdir())
    assert len(nomes) == 4
    assert (tmp_path / nomes[-1]).read_text(encoding="utf-8") == "registro 7"


def test_pasta_padrao_fica_em_dados_do_app():
    assert crashlog.pasta_logs().parts[-2:] == ("Revelador", "logs")
