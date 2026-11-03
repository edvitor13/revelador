"""Preços da revelação: ler/formatar em centavos inteiros, chave do personalizado e orçamento (puro, sem Qt)."""

from __future__ import annotations

from pathlib import Path

import pytest

from revelador import precos
from revelador.projeto import Foto, Impressao, Trabalho


def foto(id_: str, *impressoes: Impressao, selecionada: bool = True) -> Foto:
    return Foto(id=id_, caminho=Path(f"{id_}.jpg"), selecionada=selecionada, impressoes=list(impressoes))


def trabalho(*fotos: Foto) -> Trabalho:
    return Trabalho(fotos=list(fotos))


@pytest.mark.parametrize("texto, esperado", [
    ("1,5", 150),
    ("1,50", 150),
    ("1,05", 105),
    ("2", 200),
    ("R$ 2", 200),
    ("R$2,5", 250),
    ("r$ 3,00", 300),
    ("1.234,56", 123456),
    ("R$ 1.234,56", 123456),
    ("1.234.567,89", 123456789),
    ("  2,5  ", 250),
    ("0,05", 5),
    ("0", 0),
])
def test_ler_aceita_formatos_em_reais(texto, esperado):
    valor = precos.ler(texto)
    assert valor == esperado
    assert type(valor) is int


@pytest.mark.parametrize("texto", ["", "   ", "R$", "R$ "])
def test_ler_vazio_ou_so_espacos_e_sem_preco(texto):
    assert precos.ler(texto) is None


@pytest.mark.parametrize("texto", ["abc", "1,500", "1,", "12,3a", "1.5", "1.23", ",50", "1 234,56"])
def test_ler_recusa_texto_invalido_em_ptbr(texto):
    with pytest.raises(ValueError, match="inválido"):
        precos.ler(texto)


def test_ler_recusa_negativo():
    with pytest.raises(ValueError, match="negativo"):
        precos.ler("-1,50")


def test_formatar_em_ptbr_com_milhar_e_centavos():
    assert precos.formatar(150) == "R$ 1,50"
    assert precos.formatar(123456) == "R$ 1.234,56"
    assert precos.formatar(0) == "R$ 0,00"
    assert precos.formatar(5) == "R$ 0,05"
    assert precos.formatar(100000000) == "R$ 1.000.000,00"


@pytest.mark.parametrize("centavos", [0, 5, 150, 123456, 100000000])
def test_formatar_e_ler_sao_ida_e_volta(centavos):
    assert precos.ler(precos.formatar(centavos)) == centavos


def test_formatar_recusa_float():
    with pytest.raises(TypeError):
        precos.formatar(1.5)  # type: ignore[arg-type]


def test_chave_preco_do_tamanho_padrao_e_o_proprio_id():
    assert precos.chave_preco(Impressao("10x15")) == "10x15"


def test_chave_preco_do_personalizado_em_mm_sem_zeros_inuteis():
    assert precos.chave_preco(Impressao("personalizado", papel_mm=(150, 200))) == "personalizado-150x200"
    assert precos.chave_preco(Impressao("personalizado", papel_mm=(200, 150))) == "personalizado-150x200"
    assert precos.chave_preco(Impressao("personalizado", papel_mm=(152.4, 101.6))) == "personalizado-101.6x152.4"


def test_chave_preco_do_personalizado_nao_depende_do_preco():
    a = Impressao("personalizado", papel_mm=(150, 200), preco_centavos=900)
    b = Impressao("personalizado", papel_mm=(150, 200), preco_centavos=None)
    assert precos.chave_preco(a) == precos.chave_preco(b)


TABELA = {"10x15": 150, "15x20": 300, "a4": 500}


def test_orcamento_com_varios_tamanhos_e_copias():
    t = trabalho(foto("a", Impressao("10x15", copias=2), Impressao("15x20", copias=1)))
    o = precos.orcamento(t, TABELA)
    assert [(l.tamanho, l.fotos, l.copias, l.unitario, l.subtotal) for l in o.linhas] == [
        ("10x15", 1, 2, 150, 300),
        ("15x20", 1, 1, 300, 300),
    ]
    assert o.total == 600
    assert o.completo is True


def test_orcamento_soma_fotos_e_copias_de_varias_fotos_no_mesmo_tamanho():
    t = trabalho(
        foto("a", Impressao("10x15", copias=2)),
        foto("b", Impressao("10x15", copias=3)),
    )
    o = precos.orcamento(t, TABELA)
    assert len(o.linhas) == 1
    linha = o.linhas[0]
    assert (linha.fotos, linha.copias, linha.subtotal) == (2, 5, 750)
    assert o.total == 750


def test_foto_em_dois_tamanhos_conta_em_cada_linha_e_so_uma_vez_por_tamanho():
    t = trabalho(foto("a", Impressao("10x15", copias=1), Impressao("15x20", copias=2), Impressao("10x15", copias=4)))
    o = precos.orcamento(t, TABELA)
    por_tamanho = {l.tamanho: l for l in o.linhas}
    assert (por_tamanho["10x15"].fotos, por_tamanho["10x15"].copias) == (1, 5)
    assert (por_tamanho["15x20"].fotos, por_tamanho["15x20"].copias) == (1, 2)
    assert o.total == 5 * 150 + 2 * 300


def test_foto_nao_selecionada_fica_fora_da_conta():
    t = trabalho(
        foto("a", Impressao("10x15", copias=1)),
        foto("b", Impressao("10x15", copias=4), selecionada=False),
    )
    o = precos.orcamento(t, TABELA)
    assert o.linhas[0].copias == 1
    assert o.total == 150


def test_tamanho_sem_preco_deixa_o_total_parcial_nunca_zero_calado():
    t = trabalho(foto("a", Impressao("10x15", copias=2), Impressao("a4", copias=1)))
    o = precos.orcamento(t, {"10x15": 150})
    por_tamanho = {l.tamanho: l for l in o.linhas}
    assert por_tamanho["a4"].unitario is None
    assert por_tamanho["a4"].subtotal is None
    assert por_tamanho["10x15"].subtotal == 300
    assert o.total == 300
    assert o.completo is False


def test_sem_nenhuma_foto_selecionada_o_orcamento_e_vazio_e_completo():
    o = precos.orcamento(trabalho(foto("a", Impressao("10x15"), selecionada=False)), TABELA)
    assert o.linhas == []
    assert o.total == 0
    assert o.completo is True


def test_linhas_na_ordem_da_tabela_e_personalizados_no_fim():
    t = trabalho(foto(
        "a",
        Impressao("personalizado", papel_mm=(150, 200), preco_centavos=900),
        Impressao("a4"),
        Impressao("10x15"),
    ))
    o = precos.orcamento(t, TABELA)
    assert [l.tamanho for l in o.linhas] == ["10x15", "a4", "personalizado-150x200"]


def test_personalizado_com_preco_usa_o_da_impressao_e_nao_a_tabela():
    tabela = {**TABELA, "personalizado": 99999}
    t = trabalho(foto("a", Impressao("personalizado", papel_mm=(150, 200), preco_centavos=900, copias=2)))
    o = precos.orcamento(t, tabela)
    linha = o.linhas[0]
    assert (linha.tamanho, linha.unitario, linha.subtotal, linha.copias) == ("personalizado-150x200", 900, 1800, 2)
    assert o.total == 1800
    assert o.completo is True


def test_personalizado_sem_preco_e_parcial():
    t = trabalho(
        foto("a", Impressao("10x15", copias=1)),
        foto("b", Impressao("personalizado", papel_mm=(150, 200), copias=1)),
    )
    o = precos.orcamento(t, TABELA)
    linha = {l.tamanho: l for l in o.linhas}["personalizado-150x200"]
    assert linha.unitario is None and linha.subtotal is None
    assert o.total == 150
    assert o.completo is False


def test_personalizados_agrupam_por_papel_e_preco():
    t = trabalho(
        foto("a", Impressao("personalizado", papel_mm=(150, 200), preco_centavos=900, copias=1)),
        foto("b", Impressao("personalizado", papel_mm=(200, 150), preco_centavos=900, copias=2)),
        foto("c", Impressao("personalizado", papel_mm=(150, 200), preco_centavos=1000, copias=1)),
    )
    o = precos.orcamento(t, TABELA)
    assert len(o.linhas) == 2
    precos_por_linha = sorted((l.unitario, l.copias, l.fotos) for l in o.linhas)
    assert precos_por_linha == [(900, 3, 2), (1000, 1, 1)]
    assert o.total == 900 * 3 + 1000


def test_todos_os_valores_monetarios_sao_int():
    t = trabalho(
        foto("a", Impressao("10x15", copias=3), Impressao("personalizado", papel_mm=(150, 200), preco_centavos=900)),
        foto("b", Impressao("a4", copias=1)),
    )
    o = precos.orcamento(t, TABELA)
    for linha in o.linhas:
        assert type(linha.unitario) is int
        assert type(linha.subtotal) is int
        assert type(linha.copias) is int
        assert type(linha.fotos) is int
    assert type(o.total) is int
    assert o.completo is True
