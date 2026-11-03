"""O diagnóstico das dependências nativas (o mesmo que o CI roda no executável empacotado)."""

from __future__ import annotations

import json

from revelador import diagnostico

from conftest import rodar_python


def test_todas_as_dependencias_funcionam():
    r = diagnostico.executar()
    falhas = {nome: item.get("erro") for nome, item in r["itens"].items() if not item["ok"]}
    assert r["ok"], falhas
    assert set(r["itens"]) == {"numpy", "pillow", "pillow-heif", "opencv", "qt"}
    assert r["empacotado"] is False


def test_linha_de_comando_grava_o_json(tmp_path):
    destino = tmp_path / "sub" / "diagnostico.json"
    p = rodar_python(f"import sys; from revelador.app import main; sys.exit(main(['--diagnostico', r'{destino}']))")
    assert p.returncode == 0, p.stderr
    dados = json.loads(destino.read_text(encoding="utf-8"))
    assert dados["app"] == "Revelador" and dados["ok"] is True


def test_falha_de_um_item_vira_resultado_e_nao_excecao(monkeypatch):
    def quebra() -> str:
        raise ImportError("DLL load failed")

    monkeypatch.setitem(diagnostico.ITENS, "opencv", quebra)
    r = diagnostico.executar()
    assert r["ok"] is False
    assert r["itens"]["opencv"]["ok"] is False
    assert "DLL load failed" in r["itens"]["opencv"]["erro"]
