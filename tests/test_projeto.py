"""Testes do modelo e do arquivo .revelador."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from revelador import projeto
from revelador.projeto import (ErroFormato, Foto, Impressao, Recorte, Rosto, Trabalho, abrir, de_dict, para_dict,
                               salvar)

DADOS = Path(__file__).parent / "data"


def _trabalho(base: Path) -> Trabalho:
    f = Foto(id="f1", caminho=base / "Fotos" / "a.jpg", bytes=123, mtime=5.5, selecionada=True,
             ajustes={"exposicao": 12.0},
             rostos=[Rosto(0.1, 0.2, 0.3, 0.4, ((0.2, 0.3), (0.25, 0.3)), 0.9)],
             impressoes=[Impressao(copias=3, recorte=Recorte(cx=0.4, zoom=2.0, angulo=-3.0, giro=1, origem="manual")),
                         Impressao(tamanho="personalizado", modo="caber", orientacao="paisagem",
                                   papel_mm=(50.0, 70.0), preco_centavos=250)])
    g = Foto(id="f2", caminho=base / "Fotos" / "b.jpg", rostos=[])
    return Trabalho(fotos=[f, g], tamanho_padrao="13x18", dpi=400, margem_corte_mm=3.0)


def test_ida_e_volta(tmp_path):
    t = _trabalho(tmp_path)
    salvar(t, tmp_path / "x.revelador")
    assert t.caminho == tmp_path / "x.revelador"
    lido, avisos = abrir(tmp_path / "x.revelador")
    assert avisos == []
    assert lido.fotos == t.fotos
    assert (lido.tamanho_padrao, lido.dpi, lido.margem_corte_mm) == ("13x18", 400, 3.0)


def test_so_campos_fora_do_padrao(tmp_path):
    t = Trabalho(fotos=[Foto(id="f1", caminho=tmp_path / "a.jpg", impressoes=[Impressao()])])
    d = para_dict(t, tmp_path)
    assert d["fotos"][0]["impressoes"] == [{"tamanho": "10x15"}]
    for k in ("ajustes", "rostos", "selecionada"):
        assert k not in d["fotos"][0]
    assert d["fotos"][0]["caminho"] == "a.jpg"


def test_sem_tmp(tmp_path):
    salvar(_trabalho(tmp_path), tmp_path / "x.revelador")
    assert [p.name for p in tmp_path.iterdir()] == ["x.revelador"]
    json.loads((tmp_path / "x.revelador").read_text(encoding="utf-8"))


def test_exemplo_formato_1():
    t, avisos = abrir(DADOS / "exemplo_formato_1.revelador")
    assert avisos == []
    f = t.fotos[0]
    assert f.selecionada and f.ajustes == {"exposicao": 12, "sombras": 30}
    assert f.rostos[0].olhos == ((0.43, 0.26), (0.47, 0.26))
    assert f.impressoes[0].copias == 2 and f.impressoes[0].recorte.cx == 0.45
    assert f.impressoes[1].modo == "caber" and f.impressoes[1].orientacao == "paisagem"
    assert t.fotos[1].impressoes == [] and t.fotos[1].rostos is None


def test_formato_maior_recusado():
    with pytest.raises(ErroFormato, match="mais nova"):
        de_dict({"app": "Revelador", "formato": projeto.FORMATO + 1, "fotos": []}, None)


def test_json_invalido(tmp_path):
    (tmp_path / "x.revelador").write_text("{nao é json", encoding="utf-8")
    with pytest.raises(ErroFormato):
        abrir(tmp_path / "x.revelador")


def test_migracao(monkeypatch):
    chamadas = []
    monkeypatch.setattr(projeto, "FORMATO", 2)
    monkeypatch.setitem(projeto.MIGRACOES, 1, lambda d: chamadas.append(1) or {**d, "formato": 2})
    de_dict({"app": "Revelador", "formato": 1, "fotos": []}, None)
    assert chamadas == [1]


def test_valores_fora_da_faixa():
    dados = {"app": "Revelador", "formato": 1, "padrao": {"dpi": 5000}, "fotos": [
        {"id": "a", "caminho": "a.jpg", "impressoes": [
            {"copias": 5000, "orientacao": "xyz",
             "recorte": {"zoom": 99, "angulo": 90, "giro": 7, "cx": -1, "cy": "x", "origem": "?"}}]}]}
    t, avisos = de_dict(dados, Path("."))
    assert t.dpi == 600 and avisos
    i = t.fotos[0].impressoes[0]
    assert (i.copias, i.orientacao) == (999, "auto")
    r = i.recorte
    assert (r.zoom, r.angulo, r.giro, r.cx, r.cy, r.origem) == (20.0, 45.0, 3, 0.0, 0.5, "auto")


def test_tamanho_invalido_e_ajustes():
    dados = {"app": "Revelador", "formato": 1, "fotos": [
        {"id": "a", "caminho": "a.jpg", "ajustes": {"x": 1, "y": 200},
         "impressoes": [{"tamanho": "99x99"}, {"tamanho": "20x30"}, {"tamanho": "personalizado"}]}]}
    t, avisos = de_dict(dados, None, tamanhos_validos={"10x15", "20x30"},
                        limitar_ajustes=lambda a: {k: min(v, 100) for k, v in a.items()})
    assert [i.tamanho for i in t.fotos[0].impressoes] == ["10x15", "20x30", "personalizado"]
    assert t.fotos[0].ajustes == {"x": 1, "y": 100}
    assert len(avisos) == 1


def test_pasta_inteira_muda_de_lugar(tmp_path):
    a = tmp_path / "a"
    (a / "Fotos").mkdir(parents=True)
    (a / "Fotos" / "a.jpg").write_bytes(b"x")
    t = Trabalho(fotos=[Foto(id="f1", caminho=a / "Fotos" / "a.jpg")])
    salvar(t, a / "x.revelador")
    shutil.move(str(a), str(tmp_path / "b"))
    lido, _ = abrir(tmp_path / "b" / "x.revelador")
    assert lido.fotos[0].caminho == tmp_path / "b" / "Fotos" / "a.jpg"


def test_foto_sumida_nao_quebra(tmp_path):
    t = Trabalho(fotos=[Foto(id="f1", caminho=tmp_path / "some.jpg")])
    salvar(t, tmp_path / "x.revelador")
    assert abrir(tmp_path / "x.revelador")[0].fotos[0].caminho == tmp_path / "some.jpg"


def test_recuperacao(tmp_path):
    assert projeto.listar_recuperacao() == []
    t1 = _trabalho(tmp_path)
    t2 = _trabalho(tmp_path)
    t2.caminho = tmp_path / "outro.revelador"
    c1 = projeto.salvar_recuperacao(t1)
    c2 = projeto.salvar_recuperacao(t2)
    os.utime(c1, (1, 1))
    assert projeto.listar_recuperacao() == [c2, c1]
    assert abrir(c1)[0].fotos == t1.fotos
    projeto.apagar_recuperacao(c1)
    assert projeto.listar_recuperacao() == [c2]


# ------------------------------------------------------------- campos novos: favorita, fundo, zoom < 1, última foto

def test_campos_novos_ida_e_volta(tmp_path):
    t = _trabalho(tmp_path)
    t.fotos[0].favorita = True
    t.fotos[0].fundo = "#102030"
    t.fotos[0].impressoes[0].recorte.zoom = 0.4
    t.ultima_foto = "f2"
    salvar(t, tmp_path / "x.revelador")
    lido, avisos = abrir(tmp_path / "x.revelador")
    assert avisos == []
    assert lido.fotos == t.fotos and lido.ultima_foto == "f2"
    assert (lido.fotos[0].favorita, lido.fotos[0].fundo, lido.fotos[0].impressoes[0].recorte.zoom) == (
        True, "#102030", 0.4)


def test_campos_novos_so_gravados_quando_usados(tmp_path):
    """Sem favorita, fundo branco e sem última foto, o arquivo fica igual ao das versões anteriores."""
    d = para_dict(_trabalho(tmp_path), tmp_path)
    assert "ultima_foto" not in d and d["formato"] == 1
    for f in d["fotos"]:
        assert "favorita" not in f and "fundo" not in f


def test_versao_anterior_abre_igual(tmp_path):
    """Arquivo de antes (formato 1, sem os campos novos): nada de favorita, fundo branco, sem última foto."""
    t, avisos = abrir(DADOS / "exemplo_formato_1.revelador")
    assert avisos == [] and t.ultima_foto is None
    assert all(not f.favorita and f.fundo == projeto.FUNDO_PADRAO for f in t.fotos)


def test_versao_anterior_entende_o_arquivo_novo(tmp_path):
    """O que uma versão anterior faria com o arquivo novo: ela só lê os campos que conhece e limita o zoom a 1..20
    (com um aviso). Simulado aqui pelo dict sem os campos novos e com o zoom limitado como ela limitava."""
    t = _trabalho(tmp_path)
    t.fotos[0].favorita, t.fotos[0].fundo, t.ultima_foto = True, "#000000", "f1"
    t.fotos[0].impressoes[0].recorte.zoom = 0.3
    d = para_dict(t, tmp_path)
    assert d["formato"] == projeto.FORMATO == 1            # nenhuma versão anterior recusa o arquivo
    antigo = json.loads(json.dumps(d))
    for f in antigo["fotos"]:
        f.pop("favorita", None)
        f.pop("fundo", None)
        for i in f.get("impressoes", []):
            if "zoom" in i.get("recorte", {}):
                i["recorte"]["zoom"] = max(1.0, i["recorte"]["zoom"])
    antigo.pop("ultima_foto")
    lido, _avisos = de_dict(antigo, tmp_path)
    assert lido.fotos[0].impressoes[0].recorte.zoom == 1.0 and lido.fotos[0].ajustes == {"exposicao": 12.0}


def test_campos_novos_invalidos():
    dados = {"app": "Revelador", "formato": 1, "ultima_foto": "nao_existe", "fotos": [
        {"id": "a", "caminho": "a.jpg", "favorita": "sim", "fundo": "vermelho",
         "impressoes": [{"recorte": {"zoom": 0.001}}]},
        {"id": "b", "caminho": "b.jpg", "fundo": "#ABCDEF"}]}
    t, avisos = de_dict(dados, Path("."))
    a, b = t.fotos
    assert not a.favorita and a.fundo == "#ffffff" and b.fundo == "#abcdef"
    assert a.impressoes[0].recorte.zoom == projeto.ZOOM_MINIMO
    assert t.ultima_foto is None and avisos
