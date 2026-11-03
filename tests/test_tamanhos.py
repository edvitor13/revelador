"""Tabela de tamanhos de revelação: px, proporção, orientação, qualidade e personalizado (puro, sem Qt)."""

from __future__ import annotations

import pytest

from revelador import tamanhos

# Tabela da docs/ARQUITETURA.md, seção 4: id -> px a 300 dpi (retrato: largura × altura).
PX_300_RETRATO = {
    "9x13": (1050, 1500),
    "10x15": (1200, 1800),
    "13x18": (1500, 2100),
    "15x20": (1800, 2400),
    "15x21": (1800, 2480),
    "20x25": (2400, 3000),
    "20x30": (2400, 3600),
    "a4": (2480, 3508),
    "30x40": (3600, 4800),
    "30x45": (3600, 5400),
    "40x60": (4800, 7200),
    "10x10": (1200, 1200),
    "15x15": (1800, 1800),
    "20x20": (2400, 2400),
}


def test_tabela_tem_os_14_tamanhos_na_ordem_comuns_ampliacoes_quadrados():
    assert [t.id for t in tamanhos.TAMANHOS] == list(PX_300_RETRATO)
    assert len(tamanhos.TAMANHOS) == 14
    grupos = [t.grupo for t in tamanhos.TAMANHOS]
    assert grupos == sorted(grupos, key=tamanhos.GRUPOS.index)


def test_padrao_e_10x15_e_existe_na_tabela():
    assert tamanhos.PADRAO == "10x15"
    assert tamanhos.obter(tamanhos.PADRAO).lado_menor_mm == pytest.approx(101.6)
    assert tamanhos.obter(tamanhos.PADRAO).lado_maior_mm == pytest.approx(152.4)


@pytest.mark.parametrize("tamanho_id, esperado", PX_300_RETRATO.items())
def test_px_a_300_dpi_bate_com_a_tabela_da_arquitetura(tamanho_id, esperado):
    assert tamanhos.px(tamanho_id, "retrato") == esperado
    largura, altura = esperado
    assert tamanhos.px(tamanho_id, "paisagem") == (altura, largura)


def test_px_respeita_o_dpi():
    assert tamanhos.px("10x15", "retrato", dpi=150) == (600, 900)
    assert tamanhos.px("10x15", "retrato", dpi=240) == (960, 1440)


def test_dpi_invalido_e_recusado():
    with pytest.raises(ValueError):
        tamanhos.px("10x15", "retrato", dpi=0)


def test_ids_sao_unicos_sem_acento_e_sem_espaco():
    ids = [t.id for t in tamanhos.TAMANHOS]
    assert len(set(ids)) == len(ids)
    for i in ids:
        assert i.isascii(), i
        assert " " not in i and i == i.lower(), i


def test_obter_tamanho_inexistente_da_keyerror_claro():
    with pytest.raises(KeyError, match="nao-existe"):
        tamanhos.obter("nao-existe")


def test_proporcao_retrato_e_paisagem_sao_inversas():
    assert tamanhos.proporcao("10x15", "retrato") == pytest.approx(2 / 3)
    assert tamanhos.proporcao("10x15", "paisagem") == pytest.approx(1.5)
    assert tamanhos.proporcao("9x13", "paisagem") == pytest.approx(127 / 88.9)
    assert tamanhos.proporcao("a4", "retrato") == pytest.approx(1 / 2 ** 0.5, rel=1e-3)


def test_proporcao_quadrada_e_1_nas_duas_orientacoes():
    for quadrado in ("10x10", "15x15", "20x20"):
        assert tamanhos.proporcao(quadrado, "retrato") == pytest.approx(1)
        assert tamanhos.proporcao(quadrado, "paisagem") == pytest.approx(1)


def test_orientacao_auto_retrato_paisagem_e_quadrada():
    assert tamanhos.orientacao_auto(300, 200) == "paisagem"
    assert tamanhos.orientacao_auto(200, 300) == "retrato"
    assert tamanhos.orientacao_auto(200, 200) == "retrato"


def test_orientacao_efetiva_resolve_auto_e_mantem_as_fixas():
    assert tamanhos.orientacao_efetiva("auto", 4000, 3000) == "paisagem"
    assert tamanhos.orientacao_efetiva("auto", 3000, 4000) == "retrato"
    assert tamanhos.orientacao_efetiva("retrato", 4000, 3000) == "retrato"
    assert tamanhos.orientacao_efetiva("paisagem", 3000, 4000) == "paisagem"


def test_orientacao_desconhecida_e_recusada():
    with pytest.raises(ValueError):
        tamanhos.orientacao_efetiva("diagonal", 10, 10)
    with pytest.raises(ValueError):
        tamanhos.proporcao("10x15", "auto")


def test_resolucao_efetiva_do_recorte_na_largura_do_papel():
    # 10x15 em paisagem: largura do papel = 6 pol; 1800 px no recorte = 300 dpi.
    assert tamanhos.resolucao_efetiva(1800, "10x15", "paisagem") == pytest.approx(300)
    # 10x15 em retrato: largura do papel = 4 pol; 600 px no recorte = 150 dpi.
    assert tamanhos.resolucao_efetiva(600, "10x15", "retrato") == pytest.approx(150)


@pytest.mark.parametrize("dpi, esperado", [
    (300, "boa"), (200, "boa"), (199.9, "aceitavel"), (150, "aceitavel"), (149.9, "baixa"), (0, "baixa"),
])
def test_qualidade_pelos_limites(dpi, esperado):
    assert tamanhos.qualidade(dpi) == esperado


def test_personalizado_usa_o_papel_dado_em_ordem_qualquer():
    assert tamanhos.papel_mm("personalizado", (150, 200)) == (150, 200)
    assert tamanhos.papel_mm("personalizado", (200, 150)) == (150, 200)
    assert tamanhos.proporcao("personalizado", "retrato", (200, 150)) == pytest.approx(0.75)
    assert tamanhos.px("personalizado", "retrato", 300, (200, 150)) == (1772, 2362)


def test_personalizado_sem_medida_e_recusado():
    with pytest.raises(ValueError):
        tamanhos.papel_mm("personalizado", None)


@pytest.mark.parametrize("medida", [(19.9, 100), (100, 1000.1), (0, 100), (float("nan"), 100)])
def test_personalizado_fora_dos_limites_e_recusado(medida):
    with pytest.raises(ValueError):
        tamanhos.papel_mm("personalizado", medida)


def test_personalizado_nos_limites_20_e_1000_e_aceito():
    assert tamanhos.papel_mm("personalizado", (20, 1000)) == (20, 1000)


def test_ajuda_e_texto_nao_vazio():
    assert "15x21" in tamanhos.AJUDA
