"""Pastas de tamanho (#32), núcleo: arquivo .revelador, paleta, API do Estado e exportação organizada por pasta."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from conftest import rodar_python

from revelador import exportar, projeto, tamanhos
from revelador.projeto import Foto, Impressao, Pasta, Recorte, Trabalho, abrir, de_dict, para_dict, salvar
from revelador.ui import tema

DADOS = Path(__file__).parent / "data"
HOJE = date(2026, 3, 9)
VALIDOS = {t.id for t in tamanhos.TAMANHOS}


def _base(**extra) -> dict:
    return {"app": "Revelador", "formato": 1, **extra}


# --------------------------------------------------------------------------------------------- .revelador

def test_ida_e_volta_com_pastas(tmp_path):
    pastas = [Pasta("p1", "Família", "azul"), Pasta("p2", "Polaroide", "rosa", "personalizado", 3, (88.0, 107.0), 350)]
    f = Foto(id="f1", caminho=tmp_path / "a.jpg", selecionada=True, impressoes=[
        Impressao(pasta="p1"),
        Impressao(tamanho="personalizado", copias=3, papel_mm=(88.0, 107.0), preco_centavos=350, pasta="p2",
                  recorte=Recorte(cx=0.3, origem="manual")),
        Impressao(tamanho="13x18")])
    t = Trabalho(fotos=[f], pastas=pastas)
    salvar(t, tmp_path / "x.revelador")
    lido, avisos = abrir(tmp_path / "x.revelador", VALIDOS)
    assert avisos == []
    assert lido.pastas == pastas and lido.fotos == t.fotos
    d = json.loads((tmp_path / "x.revelador").read_text(encoding="utf-8"))
    assert d["pastas"][0] == {"id": "p1", "nome": "Família", "cor": "azul", "tamanho": "10x15"}   # só o fora do padrão
    assert [i.get("pasta") for i in d["fotos"][0]["impressoes"]] == ["p1", "p2", None]
    assert "pasta" not in d["fotos"][0]["impressoes"][2]


def test_sem_pastas_nao_grava_o_campo(tmp_path):
    t = Trabalho(fotos=[Foto(id="f1", caminho=tmp_path / "a.jpg", impressoes=[Impressao()])])
    d = para_dict(t, tmp_path)
    assert "pastas" not in d and "pasta" not in d["fotos"][0]["impressoes"][0]


def test_arquivo_antigo_sem_pastas():
    t, avisos = abrir(DADOS / "exemplo_formato_1.revelador")
    assert avisos == [] and t.pastas == []
    assert all(i.pasta is None for f in t.fotos for i in f.impressoes)


def test_exemplo_com_pastas():
    t, avisos = abrir(DADOS / "exemplo_pastas.revelador", VALIDOS)
    assert avisos == []
    assert [(p.id, p.nome, p.cor, p.tamanho, p.copias) for p in t.pastas] == [
        ("p1", "Família", "azul", "10x15", 1), ("p2", "Ampliações", "verde", "20x30", 2),
        ("p3", "Polaroide", "rosa", "personalizado", 1)]
    assert t.pastas[2].papel_mm == (88.0, 107.0) and t.pastas[2].preco_centavos == 350
    f1, f2, f3 = t.fotos
    assert [i.pasta for i in f1.impressoes] == ["p1", "p2", None]
    assert f1.impressoes[1].recorte.origem == "manual" and f1.impressoes[1].copias == 2
    assert f2.impressoes[0].papel_mm == (88.0, 107.0) and f3.impressoes == []


def test_leitura_robusta_das_pastas():
    dados = _base(pastas=[
        {"id": "p1", "nome": "  Festa ", "cor": "azul", "tamanho": "99x99"},   # tamanho desconhecido
        {"id": "p1", "nome": "Outra", "cor": "", "tamanho": "13x18"},          # id repetido, cor vazia
        {"nome": "", "cor": "inventada", "tamanho": "personalizado"},          # sem id, sem nome, sem papel
        "lixo",
        {"id": "p9", "nome": "Cópias", "cor": "verde", "copias": 5000, "papel_mm": [10, 10], "preco_centavos": 5},
    ], fotos=[{"id": "f1", "caminho": "a.jpg", "impressoes": [
        {"tamanho": "20x30", "pasta": "p1"},          # tamanho errado: vale o da pasta
        {"tamanho": "10x15", "pasta": "nao_existe"},  # pasta que não existe: avulsa
        {"tamanho": "10x15", "pasta": "p1"},          # segunda impressão da mesma pasta: avulsa
        {"tamanho": "10x15", "pasta": 7},             # id que não é texto: avulsa
    ]}])
    t, avisos = de_dict(dados, None, VALIDOS)
    ids = [p.id for p in t.pastas]
    assert len(ids) == 4 and len(set(ids)) == 4 and ids[0] == "p1" and ids[3] == "p9"
    festa, outra, sem_nome, copias = t.pastas
    assert (festa.nome, festa.tamanho) == ("Festa", "10x15")
    assert outra.cor == projeto.COR_PASTA_PADRAO and outra.tamanho == "13x18"
    assert sem_nome.nome == "Pasta" and sem_nome.cor == "inventada"     # chave desconhecida: a interface resolve
    assert sem_nome.tamanho == "10x15" and sem_nome.papel_mm is None
    assert copias.copias == 999 and copias.papel_mm is None and copias.preco_centavos is None   # só no personalizado
    imps = t.fotos[0].impressoes
    assert [i.pasta for i in imps] == ["p1", None, None, None]
    assert imps[0].tamanho == "10x15"      # o da pasta (que virou o padrão)
    assert len(avisos) >= 6


def test_pasta_nao_lista_e_ignorada():
    t, avisos = de_dict(_base(pastas={"x": 1}, fotos=[]), None)
    assert t.pastas == [] and avisos == []


# --------------------------------------------------------------------------------------------- paleta

def test_paleta_de_pastas():
    assert 6 <= len(tema.CORES_PASTA) <= 10
    assert next(iter(tema.CORES_PASTA)) == projeto.COR_PASTA_PADRAO
    assert set(tema.NOMES_CORES_PASTA) == set(tema.CORES_PASTA)
    for chave, cor in tema.CORES_PASTA.items():
        assert chave.isascii() and chave.islower()
        assert cor.startswith("#") and len(cor) == 7
        assert cor.lower() != tema.DESTAQUE.lower()
    assert len(set(tema.CORES_PASTA.values())) == len(tema.CORES_PASTA)
    assert tema.cor_pasta("nao_existe") == tema.CORES_PASTA[projeto.COR_PASTA_PADRAO]
    assert tema.nome_cor_pasta("azul") == "Azul"


def test_contraste_das_cores_de_pasta_no_tema_escuro():
    from test_tema import _contraste
    for cor in tema.CORES_PASTA.values():
        for fundo in (tema.BG, tema.PAINEL, tema.PAINEL2):
            assert _contraste(cor, fundo) >= 4.5, (cor, fundo)


def test_proxima_cor():
    chaves = list(tema.CORES_PASTA)
    assert tema.proxima_cor_pasta([]) == chaves[0]
    assert tema.proxima_cor_pasta([chaves[0], "inventada"]) == chaves[1]
    assert tema.proxima_cor_pasta([chaves[0], chaves[2]]) == chaves[1]
    assert tema.proxima_cor_pasta(chaves) == chaves[0]                  # todas usadas: recomeça
    assert tema.proxima_cor_pasta(chaves + [chaves[0]]) == chaves[1]    # a menos usada


# --------------------------------------------------------------------------------------------- Estado

def _rodar(corpo: str) -> None:
    p = rodar_python("""
from pathlib import Path
from revelador.imagem import InfoFoto
from revelador.projeto import Impressao, Pasta, Recorte, Rosto
from revelador.ui.estado import Estado
from revelador.ui import tema

e = Estado()
ev = []
e.pastas_mudaram.connect(lambda: ev.append("pastas"))
e.pedido_mudou.connect(lambda: ev.append("pedido"))
e.foto_mudou.connect(lambda i: ev.append("foto:" + i))
lotes = []
from contextlib import contextmanager
_lote = e.lote
@contextmanager
def espiao(texto=""):
    lotes.append(texto)
    with _lote(texto):
        yield
e.lote = espiao

def info(f, w=4000, h=3000):
    e.definir_info(f.id, InfoFoto(w, h, None, None, None, 10, 1_000_000_000))
""" + corpo + "\nprint('ok')\n", timeout=60)
    assert p.returncode == 0, p.stderr
    assert p.stdout.strip().endswith("ok"), p.stdout


def test_criar_alterar_e_validar_pastas():
    _rodar("""
e.trabalho.tamanho_padrao = "13x18"
a = e.criar_pasta("  Família ")
assert (a.nome, a.tamanho, a.copias, a.cor) == ("Família", "13x18", 1, list(tema.CORES_PASTA)[0])
b = e.criar_pasta("Ampliações", "20x30", copias=2)
assert b.cor == list(tema.CORES_PASTA)[1] and b.id != a.id and b.id.startswith("p")
assert e.trabalho.pastas == [a, b] and e.pasta_por_id(b.id) is b and e.pasta_por_id(None) is None
assert "pastas" in ev and lotes == ["Nova pasta", "Nova pasta"] and e.modificado
for ruim in (lambda: e.criar_pasta("   "), lambda: e.criar_pasta("x", "99x99"),
             lambda: e.criar_pasta("x", "personalizado"), lambda: e.criar_pasta("x", "personalizado", papel_mm=(1, 2))):
    try:
        ruim()
    except (ValueError, KeyError):
        pass
    else:
        raise AssertionError("aceitou pasta inválida")
assert len(e.trabalho.pastas) == 2
c = e.criar_pasta("Polaroide", "personalizado", cor="rosa", papel_mm=(107, 88), preco_centavos=300)
assert c.papel_mm == (88.0, 107.0) and c.preco_centavos == 300 and c.cor == "rosa"

ev.clear()
e.alterar_pasta(a, nome="Família 2", cor="verde")
assert (a.nome, a.cor, a.id) == ("Família 2", "verde", a.id) and ev.count("pastas") == 1
ev.clear()
e.alterar_pasta(a, nome="Família 2")          # nada mudou: nenhum sinal
assert ev == []
e.alterar_pasta(c, tamanho="10x15")           # sai do personalizado: papel e preço zerados
assert (c.tamanho, c.papel_mm, c.preco_centavos) == ("10x15", None, None)
e.mover_pasta(c, 0)
assert e.trabalho.pastas == [c, a, b]
e.mover_pasta(c, 99)
assert e.trabalho.pastas == [a, b, c]
""")


def test_entrar_e_sair_da_pasta_e_mesma_foto_em_duas_pastas():
    _rodar("""
f, g, h = e.adicionar([Path("f.jpg"), Path("g.jpg"), Path("h.jpg")])
info(f); info(g)                                 # h ainda sem metadados
p10 = e.criar_pasta("Família", "10x15")
p20 = e.criar_pasta("Ampliações", "20x30", copias=2)
ev.clear(); lotes.clear()
mudaram = e.adicionar_a_pasta([f, g, h, f], p10)
assert mudaram == [f, g, h] and lotes == ["Adicionar à pasta"]
for x in (f, g, h):
    assert x.selecionada and len(x.impressoes) == 1
    imp = x.impressoes[0]
    assert (imp.tamanho, imp.copias, imp.pasta) == ("10x15", 1, p10.id)
assert f.impressoes[0].recorte.origem == "centro"          # recorte sugerido (sem rostos: centro)
assert h.impressoes[0].recorte == Recorte()                # sem metadados: refeito quando chegarem
info(h)
assert h.impressoes[0].recorte.origem == "centro"
assert "pastas" in ev and "pedido" in ev and f"foto:{f.id}" in ev
assert e.adicionar_a_pasta([f], p10) == []                 # já está: não ganha outra
assert len(f.impressoes) == 1

e.adicionar_a_pasta([f], p20)                              # a mesma foto em duas pastas
assert [(i.tamanho, i.copias, i.pasta) for i in f.impressoes] == [("10x15", 1, p10.id), ("20x30", 2, p20.id)]
assert e.pastas_da_foto(f) == [p10, p20] and e.pastas_da_foto(g) == [p10]
assert e.fotos_da_pasta(p10) == [f, g, h] and e.fotos_da_pasta(p20) == [f]
assert e.impressao_da_pasta(f, p20) is f.impressoes[1]

assert e.tirar_da_pasta([f], p10) == [f]
assert f.selecionada and [i.pasta for i in f.impressoes] == [p20.id]
assert e.tirar_da_pasta([f], p20) == [f]
assert not f.selecionada and f.impressoes == []            # a última impressão saiu: desmarcada
assert e.tirar_da_pasta([f], p20) == []

# avulsa no mesmo tamanho vira a da pasta (não revela duas vezes); em outro tamanho, fica
k, m = e.adicionar([Path("k.jpg"), Path("m.jpg")])
info(k); info(m)
e.selecionar(k)                                            # avulsa 10x15 (o padrão)
k.impressoes[0].copias = 3
k.impressoes[0].recorte = Recorte(cx=0.4, origem="manual")
e.adicionar_a_pasta([k], p10)
assert [(i.tamanho, i.copias, i.pasta, i.recorte.cx) for i in k.impressoes] == [("10x15", 3, p10.id, 0.4)]
e.selecionar(m)
e.adicionar_a_pasta([m], p20)
assert [(i.tamanho, i.pasta) for i in m.impressoes] == [("10x15", None), ("20x30", p20.id)]
e.tirar_da_pasta([m], p20)
assert m.selecionada and [i.pasta for i in m.impressoes] == [None]

# desmarcada com avulsa guardada: entra marcada só no tamanho da pasta
e.selecionar(m, False)
e.adicionar_a_pasta([m], p20)
assert m.selecionada and [(i.tamanho, i.pasta) for i in m.impressoes] == [("20x30", p20.id)]

# a foto atual: o índice da impressão continua válido
e.definir_atual(m)
e.adicionar_a_pasta([m], p10)
e.definir_impressao(1)
e.tirar_da_pasta([m], p10)
assert e.indice_impressao == 0 and e.impressao_atual is m.impressoes[0]
""")


def test_mudar_tamanho_e_copias_da_pasta_e_apagar():
    _rodar("""
from revelador import enquadramento, tamanhos
f, g = e.adicionar([Path("f.jpg"), Path("g.jpg")])
info(f); info(g)
p = e.criar_pasta("Festa", "10x15")
outra = e.criar_pasta("Outra", "13x18")
e.adicionar_a_pasta([f, g], p)
e.adicionar_a_pasta([f], outra)
g.impressoes[0].recorte = Recorte(cx=0.3, cy=0.5, zoom=1.5, origem="manual")
g.impressoes[0].copias = 4                                 # a pessoa mudou as cópias desta
manual = g.impressoes[0].recorte
esperado = enquadramento.reencaixar(manual, 4000, 3000, tamanhos.proporcao("15x15", "paisagem"))

ev.clear(); lotes.clear()
e.alterar_pasta(p, tamanho="15x15", copias=2)
assert lotes == ["Alterar a pasta"] and "pastas" in ev and f"foto:{f.id}" in ev and f"foto:{g.id}" in ev
fi, gi = e.impressao_da_pasta(f, p), e.impressao_da_pasta(g, p)
assert (fi.tamanho, fi.copias) == ("15x15", 2)             # cópias antigas da pasta: seguem a pasta
assert (gi.tamanho, gi.copias) == ("15x15", 4)             # mudadas pela pessoa: ficam
assert fi.recorte.origem == "centro"                      # automático refeito
assert gi.recorte.origem == "manual" and gi.recorte == esperado   # manual reencaixado, continua manual
assert e.impressao_da_pasta(f, outra).tamanho == "13x18"   # a outra pasta não muda

e.alterar_pasta(p, tamanho="personalizado", papel_mm=(50, 70), preco_centavos=120)
assert (fi.tamanho, fi.papel_mm, fi.preco_centavos) == ("personalizado", (50.0, 70.0), 120)
e.alterar_pasta(p, preco_centavos=150)
assert fi.preco_centavos == 150 and fi.papel_mm == (50.0, 70.0)

ev.clear(); lotes.clear()
e.apagar_pasta(p)
assert lotes == ["Apagar a pasta"] and "pastas" in ev and p not in e.trabalho.pastas
assert [x.id for x in e.trabalho.fotos] == [f.id, g.id]    # as fotos ficam no trabalho
assert [i.pasta for i in f.impressoes] == [outra.id] and f.selecionada
assert g.impressoes == [] and not g.selecionada           # sem impressão sobrando: desmarcada
e.apagar_pasta(p)                                          # já apagada: nada
""")


# --------------------------------------------------------------------------------------------- exportação

def _gerar(pasta: Path, nome: str) -> Path:
    from PIL import Image
    caminho = pasta / nome
    Image.new("RGB", (300, 200), (120, 90, 60)).save(caminho)
    return caminho


def _trabalho_pastas(fotos: Path) -> Trabalho:
    a, b, c = (_gerar(fotos, n) for n in ("IMG_1.jpg", "IMG_2.jpg", "IMG_3.jpg"))
    pastas = [Pasta("p1", "Família", "azul", "10x15"), Pasta("p2", "FAMÍLIA", "verde", "10x15"),
              Pasta("p3", "CON", "rosa", "13x18"), Pasta("p4", "10x15", "roxo", "20x30"),
              Pasta("p5", "Vazia", "azul", "10x15")]
    return Trabalho(pastas=pastas, fotos=[
        Foto(id="a", caminho=a, selecionada=True, impressoes=[
            Impressao(pasta="p1"), Impressao(tamanho="13x18", copias=2, pasta="p3"), Impressao()]),
        Foto(id="b", caminho=b, selecionada=True, impressoes=[
            Impressao(pasta="p2"), Impressao(tamanho="20x30", pasta="p4"), Impressao(tamanho="10x15", copias=2)]),
        Foto(id="c", caminho=c, selecionada=False, impressoes=[Impressao(pasta="p1")]),   # desmarcada: não sai
    ])


def test_nome_subpasta():
    assert exportar.nome_subpasta('a<b>:c"d/e\\\\f|g?h*') == "a_b__c_d_e__f_g_h_"
    assert exportar.nome_subpasta("Festa.  ") == "Festa"
    assert exportar.nome_subpasta("con") == "con_" and exportar.nome_subpasta("COM1.txt") == "COM1.txt_"
    assert exportar.nome_subpasta("...") == "_"
    assert len(exportar.nome_subpasta("x" * 300)) == exportar.MAX_NOME_SUBPASTA


def test_exportacao_organizada_por_pasta(tmp_path):
    fotos = tmp_path / "fotos"
    fotos.mkdir()
    t = _trabalho_pastas(fotos)
    plano = exportar.planejar(t, tmp_path / "saida", exportar.MODO_PASTAS, 100, hoje=HOJE,
                              organizar=exportar.ORGANIZAR_PASTA)
    assert plano.organizar == exportar.ORGANIZAR_PASTA
    r = exportar.executar(plano)
    assert r.ok
    raiz = tmp_path / "saida" / "Revelação 2026-03-09"
    arquivos = sorted(p.relative_to(raiz).as_posix() for p in raiz.rglob("*") if p.is_file())
    assert arquivos == sorted([
        "Família/IMG_1.jpg",
        "FAMÍLIA (2)/IMG_2.jpg",            # único sem diferenciar maiúsculas
        "CON_/2 cópias/IMG_1.jpg",          # nome reservado do Windows; só esta pasta tem 2 cópias
        "10x15/IMG_2.jpg",                  # a pasta "10x15" (de 20x30) escolhe o nome primeiro...
        "10x15 (2)/1 cópia/IMG_1.jpg",      # ...e as avulsas de 10x15 ficam com o sufixo
        "10x15 (2)/2 cópias/IMG_2.jpg",
        "pedido.txt",
    ])
    assert {i.grupo for i in plano.itens} == {"Família", "FAMÍLIA (2)", "CON_", "10x15", "10x15 (2)"}
    assert [i.pasta for i in plano.itens] == ["p1", "p3", None, "p2", "p4", None]
    pedido = r.pedido.read_text(encoding="utf-8")
    assert "Pastas" in pedido
    assert "Família/ — 10x15: 1 foto(s), 1 cópia(s)" in pedido
    assert "CON_/ — 13x18: 1 foto(s), 2 cópia(s)" in pedido
    assert "10x15/ — 20x30: 1 foto(s), 1 cópia(s)" in pedido
    assert "Vazia" not in pedido
    # o custo não muda: continua por tamanho
    assert plano.orcamento() == exportar.planejar(t, tmp_path / "x", exportar.MODO_PASTAS, 100, hoje=HOJE).orcamento()


def test_exportacao_por_tamanho_ignora_as_pastas(tmp_path):
    fotos = tmp_path / "fotos"
    fotos.mkdir()
    plano = exportar.planejar(_trabalho_pastas(fotos), tmp_path / "saida", exportar.MODO_NOME, 100, hoje=HOJE)
    assert plano.organizar == exportar.ORGANIZAR_TAMANHO
    assert sorted({i.grupo for i in plano.itens}) == ["10x15", "13x18", "20x30"]
    assert "Pastas" not in exportar.texto_pedido(plano)


def test_por_pasta_sem_pastas_e_igual_a_por_tamanho(tmp_path):
    fotos = tmp_path / "fotos"
    fotos.mkdir()
    t = Trabalho(fotos=[Foto(id="a", caminho=_gerar(fotos, "a.jpg"), selecionada=True,
                             impressoes=[Impressao(), Impressao(tamanho="a4", copias=2, pasta="sumiu")])])
    por_pasta = exportar.planejar(t, tmp_path, exportar.MODO_PASTAS, 100, hoje=HOJE, organizar=exportar.ORGANIZAR_PASTA)
    por_tam = exportar.planejar(t, tmp_path, exportar.MODO_PASTAS, 100, hoje=HOJE)
    assert [i.destinos for i in por_pasta.itens] == [i.destinos for i in por_tam.itens]
    with pytest.raises(ValueError):
        exportar.planejar(t, tmp_path, organizar="cor")


def test_dialogo_organizar_por_pasta():
    p = rodar_python("""
import os, sys, tempfile
from pathlib import Path
from PIL import Image
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv[:1])
from revelador import exportar
from revelador.imagem import abrir_info
from revelador.projeto import Foto
from revelador.ui import prefs
from revelador.ui.main_window import MainWindow

base = Path(tempfile.mkdtemp())
caminho = base / "a.jpg"
Image.new("RGB", (300, 200), (100, 100, 100)).save(caminho)
j = MainWindow()
e = j.estado
f = Foto(id="a", caminho=caminho)
e.trabalho.fotos.append(f)
e.definir_info(f.id, abrir_info(caminho))
e.selecionar(f)

d = j.criar_dialogo_exportacao()
assert d.organizar == exportar.ORGANIZAR_TAMANHO and d.seg_organizar.isHidden()   # sem pastas: não aparece
pasta = e.criar_pasta("Família", "13x18")
e.adicionar_a_pasta([f], pasta)
d = j.criar_dialogo_exportacao()
assert not d.seg_organizar.isHidden() and d.organizar == exportar.ORGANIZAR_TAMANHO   # padrão: tamanho
destino = base / "saida"
destino.mkdir()
d.definir_destino(destino)
assert "13x18/a.jpg" in d.rotulo_estrutura.text()
d.definir_organizar(exportar.ORGANIZAR_PASTA)
assert "Família/a.jpg" in d.rotulo_estrutura.text() and "10x15/a.jpg" in d.rotulo_estrutura.text()
assert d.iniciar() and d.aguardar(60000) and d.resultado.ok
raiz = d.resultado.pedido.parent
assert (raiz / "Família" / "a.jpg").is_file() and (raiz / "10x15" / "a.jpg").is_file()
assert prefs.settings().value("exportar/organizar") == exportar.ORGANIZAR_PASTA
d2 = j.criar_dialogo_exportacao()
assert d2.organizar == exportar.ORGANIZAR_PASTA                                       # lembrado
print("ok")
""", timeout=120)
    assert p.returncode == 0, p.stderr
    assert p.stdout.strip().endswith("ok"), p.stdout


def test_pasta_antiga_depois_do_desfazer_muda_a_pasta_viva():
    # o desfazer restaura cópias das pastas: um objeto antigo, igual em valor, não pode receber a mudança
    _rodar("""
f, = e.adicionar([Path("a.jpg")])
info(f)
p = e.criar_pasta("Festa", "10x15")
e.alterar_pasta(p, nome="Natal")
e.desfazer()                                   # volta a "Festa": a pasta viva agora é outro objeto
viva = e.pasta_por_id(p.id)
assert viva is not p and viva.nome == "Festa" and p.nome == "Natal"
velha = Pasta(**{**p.__dict__, "nome": "Festa"})   # igual em valor à viva, mas fora do trabalho
e.alterar_pasta(velha, nome="Ano novo")
assert e.pasta_por_id(p.id).nome == "Ano novo"
e.adicionar_a_pasta([f], velha)
assert e.fotos_da_pasta(viva) == [f] and f.impressoes[-1].pasta == p.id
e.mover_pasta(velha, 0)
e.apagar_pasta(velha)
assert e.trabalho.pastas == [] and not f.selecionada
try:
    e.alterar_pasta(velha, nome="x")
except ValueError:
    pass
else:
    raise AssertionError("pasta apagada devia dar ValueError")
"""
)


def test_exportacao_por_pasta_leva_o_acabamento_do_tamanho_da_pasta(tmp_path):
    fotos = tmp_path / "fotos"
    fotos.mkdir()
    t = _trabalho_pastas(fotos)
    acab = {"10x15": exportar.Acabamento("grossa", "fosco"), "20x30": exportar.Acabamento(papel="brilho")}
    plano = exportar.planejar(t, tmp_path / "saida", exportar.MODO_PASTAS, 100, hoje=HOJE,
                              organizar=exportar.ORGANIZAR_PASTA, acabamentos=acab)
    assert {i.grupo for i in plano.itens} == {
        "Família - borda grossa - fosco", "FAMÍLIA - borda grossa - fosco (2)", "CON_",   # CON_ é 13x18: sem
        "10x15 - brilho",                                                               # a pasta "10x15" é 20x30
        "10x15 - borda grossa - fosco"}                                                 # avulsas de 10x15
