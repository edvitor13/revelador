"""Ajustes de luz e cor (#7): esquema, identidade, sentido de cada ajuste, limites, determinismo e prévia ≈ exportação."""

from __future__ import annotations

import time

import cv2
import numpy as np
import pytest

from revelador import ajustes
from revelador.ajustes import PARAMS, POR_CHAVE, aplicar, e_neutro, sanitizar

CHAVES = [p.chave for p in PARAMS]
LUMA = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)


# ------------------------------------------------------------------------------------------- imagens

def foto_sintetica(w: int = 600, h: int = 400, semente: int = 7, sigma_px: float | None = None) -> np.ndarray:
    """Cena com céu, gradiente, objetos coloridos, bordas nítidas e textura fina (sem nada pessoal)."""
    rng = np.random.default_rng(semente)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    u, v = xx / w, yy / h
    img = np.empty((h, w, 3), np.float32)
    img[..., 0] = 0.25 + 0.5 * u
    img[..., 1] = 0.30 + 0.4 * v
    img[..., 2] = 0.65 - 0.4 * u * v
    for _ in range(14):  # manchas coloridas de bordas nítidas
        cx, cy, r = rng.random() * w, rng.random() * h, (0.04 + 0.1 * rng.random()) * min(w, h)
        cor = rng.random(3).astype(np.float32)
        img[(xx - cx) ** 2 + (yy - cy) ** 2 < r * r] = cor
    img[: h // 5] = np.array([0.55, 0.7, 0.92], np.float32)  # céu
    img += (rng.random(img.shape).astype(np.float32) - 0.5) * 0.03
    # um pouco macia, como uma foto real
    img = cv2.GaussianBlur(img, (0, 0), min(w, h) / 400.0 if sigma_px is None else sigma_px)
    return np.clip(img, 0.0, 1.0).astype(np.float32)


def luminancia(img: np.ndarray) -> np.ndarray:
    return img @ LUMA


def croma_oklab(img: np.ndarray) -> np.ndarray:
    lab = ajustes._linear_para_oklab(ajustes._decodificar(img))
    return np.hypot(lab[..., 1], lab[..., 2])


def cor_uniforme(rgb, tam: int = 64) -> np.ndarray:
    return np.tile(np.array(rgb, np.float32), (tam, tam, 1))


def reduzir(img: np.ndarray, fator: int) -> np.ndarray:
    h, w = img.shape[:2]
    return cv2.resize(img, (w // fator, h // fator), interpolation=cv2.INTER_AREA)


# --------------------------------------------------------------------------------------------- esquema

def test_esquema_das_chaves_e_faixas():
    assert len(CHAVES) == len(set(CHAVES)) == 11
    assert set(CHAVES) == {"temperatura", "matiz", "exposicao", "brancos", "pretos", "realces", "sombras",
                           "contraste", "saturacao", "vibracao", "nitidez"}
    assert set(POR_CHAVE) == set(CHAVES)
    for p in PARAMS:
        assert p.padrao == 0 and p.minimo <= p.padrao <= p.maximo and p.passo > 0
        assert p.grupo in ajustes.GRUPOS
        assert p.nome and p.chave.isascii()
    assert (POR_CHAVE["nitidez"].minimo, POR_CHAVE["nitidez"].maximo) == (0, 100)
    assert all((p.minimo, p.maximo) == (-100, 100) for p in PARAMS if p.chave != "nitidez")
    assert [g for g in ajustes.GRUPOS if any(p.grupo == g for p in PARAMS)] == list(ajustes.GRUPOS)


def test_sanitizar():
    assert sanitizar(None) == {} and sanitizar({}) == {}
    assert sanitizar({"exposicao": 0, "contraste": 0.0}) == {}
    s = sanitizar({"exposicao": "30", "contraste": 500, "nitidez": -20, "matiz": float("nan"), "xis": 5,
                   "brilho": 1, "sombras": None, "realces": -400})
    assert s == {"exposicao": 30.0, "realces": -100.0, "contraste": 100.0}
    assert all(isinstance(v, float) for v in s.values())
    assert sanitizar({"nitidez": 250}) == {"nitidez": 100.0}


def test_e_neutro():
    assert e_neutro(None) and e_neutro({}) and e_neutro({"exposicao": 0, "desconhecida": 9, "nitidez": -5})
    assert not e_neutro({"exposicao": 1})


# -------------------------------------------------------------------------------------------- identidade

def test_padrao_e_identidade_exata():
    img = foto_sintetica()
    for valores in ({}, None, {p.chave: p.padrao for p in PARAMS}, {"inexistente": 80}, {"nitidez": -30}):
        saida = aplicar(img, valores)
        assert saida.dtype == np.float32 and saida.shape == img.shape
        assert saida is not img and not np.shares_memory(saida, img)
        assert np.array_equal(saida, img)
        assert saida.tobytes() == img.tobytes()


def test_nao_modifica_a_entrada():
    img = foto_sintetica()
    copia = img.copy()
    aplicar(img, {p.chave: 60 for p in PARAMS})
    assert np.array_equal(img, copia)


def test_aceita_entrada_nao_contigua_e_float64():
    img = foto_sintetica(200, 120)
    a = aplicar(np.asfortranarray(img), {"contraste": 30, "saturacao": 20, "nitidez": 40})
    b = aplicar(img, {"contraste": 30, "saturacao": 20, "nitidez": 40})
    assert np.array_equal(a, b)
    assert aplicar(img.astype(np.float64), {"exposicao": 10}).dtype == np.float32


# --------------------------------------------------------------------------------- sentido de cada ajuste

@pytest.mark.parametrize("chave", ["exposicao", "brancos", "pretos", "realces", "sombras"])
def test_ajustes_de_luz_clareiam_de_forma_monotona(chave):
    img = foto_sintetica()
    medias = [float(luminancia(aplicar(img, {chave: v})).mean()) for v in (-100, -50, 0, 50, 100)]
    assert all(b > a for a, b in zip(medias, medias[1:])), (chave, medias)


def test_exposicao_em_ev():
    cinza = cor_uniforme((0.2, 0.2, 0.2))
    lin = ajustes._decodificar(cinza)[0, 0, 0]
    mais = ajustes._decodificar(aplicar(cinza, {"exposicao": 50}))[0, 0, 0]
    assert mais / lin == pytest.approx(2.0, rel=1e-3)  # +1 EV dobra a luz linear
    menos = ajustes._decodificar(aplicar(cinza, {"exposicao": -50}))[0, 0, 0]
    assert menos / lin == pytest.approx(0.5, rel=1e-3)


def test_contraste_abre_e_fecha_o_histograma():
    img = foto_sintetica()
    base = luminancia(img).std()
    assert luminancia(aplicar(img, {"contraste": 60})).std() > base * 1.1
    assert luminancia(aplicar(img, {"contraste": -60})).std() < base * 0.9
    # preserva o preto e o branco e leva o claro para cima e o escuro para baixo do cinza médio
    degrau = np.linspace(0, 1, 11, dtype=np.float32)[None, :, None].repeat(3, axis=2)
    mais = aplicar(degrau, {"contraste": 100})[0, :, 0]
    assert mais[0] == 0 and mais[-1] == pytest.approx(1.0, abs=1e-6)
    assert mais[2] < degrau[0, 2, 0] and mais[8] > degrau[0, 8, 0]
    assert np.all(np.diff(mais) > 0) and np.all(np.diff(aplicar(degrau, {"contraste": -100})[0, :, 0]) > 0)


@pytest.mark.parametrize("valor", [-100, -50, 50, 100])
def test_croma_segue_a_saturacao(valor):
    img = foto_sintetica()
    base = croma_oklab(img).mean()
    croma = croma_oklab(aplicar(img, {"saturacao": valor})).mean()
    assert (croma > base * 1.05) if valor > 0 else (croma < base * 0.95)


def test_saturacao_menos_100_e_preto_e_branco():
    saida = aplicar(foto_sintetica(), {"saturacao": -100})
    assert croma_oklab(saida).max() < 0.01
    assert np.abs(saida - saida[..., :1]).max() < 0.01


def test_vibracao_aumenta_a_croma_de_forma_geral():
    img = foto_sintetica()
    assert croma_oklab(aplicar(img, {"vibracao": 60})).mean() > croma_oklab(img).mean() * 1.03
    assert croma_oklab(aplicar(img, {"vibracao": -60})).mean() < croma_oklab(img).mean() * 0.97


def test_vibracao_protege_pele_e_poupa_cores_saturadas():
    azul_fraco = cor_uniforme((0.45, 0.52, 0.68))
    pele = cor_uniforme((0.82, 0.62, 0.52))
    azul_forte = cor_uniforme((0.05, 0.2, 0.95))

    def ganho(cor, valores):
        return float(croma_oklab(aplicar(cor, valores)).mean() / croma_oklab(cor).mean())

    vib, sat = {"vibracao": 80}, {"saturacao": 80}
    assert ganho(azul_fraco, vib) > ganho(pele, vib) + 0.15
    assert ganho(pele, vib) < ganho(pele, sat) - 0.3
    assert ganho(pele, vib) > 1.0 and ganho(pele, vib) < 1.2
    assert ganho(azul_fraco, vib) > ganho(azul_forte, vib)  # pouco saturado ganha mais que o muito saturado


def test_temperatura_e_matiz():
    cinza = cor_uniforme((0.5, 0.5, 0.5))
    quente = aplicar(cinza, {"temperatura": 60})[0, 0]
    fria = aplicar(cinza, {"temperatura": -60})[0, 0]
    assert quente[0] > 0.5 > quente[2] and fria[2] > 0.5 > fria[0]
    assert quente[0] / quente[2] > 1.1 and fria[2] / fria[0] > 1.1
    # a luminância fica praticamente igual
    assert luminancia(quente) == pytest.approx(0.5, abs=0.01) and luminancia(fria) == pytest.approx(0.5, abs=0.01)
    magenta = aplicar(cinza, {"matiz": 60})[0, 0]
    verde = aplicar(cinza, {"matiz": -60})[0, 0]
    assert magenta[1] < 0.5 < verde[1]
    assert magenta[0] == pytest.approx(magenta[2], abs=1e-6) and verde[0] == pytest.approx(verde[2], abs=1e-6)
    # na imagem toda: razão R/B média sobe com a temperatura
    img = foto_sintetica()
    razao = lambda a: float(a[..., 0].mean() / a[..., 2].mean())  # noqa: E731
    assert razao(aplicar(img, {"temperatura": 50})) > razao(img) > razao(aplicar(img, {"temperatura": -50}))


ESCALA_NITIDEZ = 15.0  # px por mm: raio de 0,1 mm = 1,5 px (a imagem de teste é pequena demais para o padrão)


def contraste_local(img: np.ndarray) -> float:
    """Média de |Y − gaussiana(Y)|: quanto de detalhe fino a imagem tem."""
    y = luminancia(img)
    return float(np.abs(y - cv2.GaussianBlur(y, (0, 0), 3.0)).mean())


def test_nitidez_aumenta_o_contraste_local_sem_mexer_na_media():
    img = foto_sintetica(800, 600)
    antes = contraste_local(img)
    pouco = aplicar(img, {"nitidez": 30}, ESCALA_NITIDEZ)
    muito = aplicar(img, {"nitidez": 100}, ESCALA_NITIDEZ)
    assert antes < contraste_local(pouco) < contraste_local(muito)
    assert contraste_local(muito) > antes * 1.05
    assert abs(float(luminancia(muito).mean() - luminancia(img).mean())) < 0.01
    assert croma_oklab(muito).mean() == pytest.approx(croma_oklab(img).mean(), rel=0.05)


def test_nitidez_nao_amplifica_ruido_fraco():
    rng = np.random.default_rng(3)
    plano = np.clip(0.5 + (rng.random((300, 400, 3)).astype(np.float32) - 0.5) * 0.004, 0, 1)  # ruído de ±0,2%
    saida = aplicar(plano, {"nitidez": 100}, ESCALA_NITIDEZ)
    assert float(np.abs(saida - plano).mean()) < 0.003
    # um degrau forte, ao contrário, ganha o contorno característico (sobe e desce além do degrau)
    degrau = np.full((200, 200, 3), 0.3, np.float32)
    degrau[:, 100:] = 0.7
    nitido = aplicar(degrau, {"nitidez": 100}, ESCALA_NITIDEZ)
    assert nitido[:, 100:].max() > 0.72 and nitido[:, :100].min() < 0.28


def test_escala_mm_px_muda_o_raio_da_nitidez():
    img = foto_sintetica(800, 600)
    padrao = aplicar(img, {"nitidez": 80})  # sem escala = lado menor de 100 mm = 6 px/mm
    igual = aplicar(img, {"nitidez": 80}, escala_mm_px=6.0)
    assert np.array_equal(padrao, igual)
    maior = aplicar(img, {"nitidez": 80}, escala_mm_px=24.0)
    assert not np.array_equal(padrao, maior)
    # raio de 0,6 px mexe pouco; o de 2,4 px pega detalhes mais grossos e muda mais a imagem
    assert float(np.abs(maior - img).mean()) > float(np.abs(padrao - img).mean())


# ------------------------------------------------------------------------- realces e sombras sem estragar

def cena_com_ceu(w: int = 600, h: int = 400):
    """Metade de cima: céu quase estourado com textura; metade de baixo: sombra com textura."""
    rng = np.random.default_rng(11)
    img = np.empty((h, w, 3), np.float32)
    ruido = cv2.GaussianBlur(rng.random((h, w)).astype(np.float32), (0, 0), 3.0)
    ruido = (ruido - ruido.mean()) / ruido.std()
    img[: h // 2] = (0.95 + 0.012 * ruido[: h // 2])[..., None] * np.array([0.97, 0.99, 1.0], np.float32)
    img[h // 2:] = (0.10 + 0.02 * ruido[h // 2:])[..., None] * np.array([1.0, 1.0, 1.0], np.float32)
    return np.clip(img, 0, 1), (slice(0, h * 3 // 10), slice(None)), (slice(h * 7 // 10, h), slice(None))


def test_realces_recupera_o_ceu_sem_mexer_nas_sombras():
    img, ceu, sombra = cena_com_ceu()
    saida = aplicar(img, {"realces": -100})
    assert luminancia(saida[ceu]).mean() < luminancia(img[ceu]).mean() - 0.2
    assert float(np.abs(saida[sombra] - img[sombra]).max()) < 1e-3  # sombras intactas
    # a textura do céu continua lá (a curva comprime, mas não achata)
    assert luminancia(saida[ceu]).std() > luminancia(img[ceu]).std() * 0.35
    # e o contrário: realces positivo não mexe nas sombras
    mais = aplicar(img, {"realces": 100})
    assert float(np.abs(mais[sombra] - img[sombra]).max()) < 1e-3


def test_sombras_abre_as_sombras_sem_mexer_no_ceu():
    img, ceu, sombra = cena_com_ceu()
    saida = aplicar(img, {"sombras": 100})
    assert luminancia(saida[sombra]).mean() > luminancia(img[sombra]).mean() + 0.1
    assert float(np.abs(saida[ceu] - img[ceu]).max()) < 1e-3


def test_realces_sem_halo_perto_de_uma_borda():
    """Perto de um degrau claro/escuro, o lado escuro não pode escurecer de forma visível por causa do claro."""
    img = np.full((300, 600, 3), 0.15, np.float32)
    img[:, 300:] = 0.9
    saida = aplicar(img, {"realces": -100})
    lado_escuro_perto = luminancia(saida[:, 280:296]).mean()
    lado_escuro_longe = luminancia(saida[:, 20:100]).mean()
    assert abs(float(lado_escuro_perto - lado_escuro_longe)) < 0.02


# ------------------------------------------------------------------------------------------------ limites

def extremos(img: np.ndarray, valores: dict) -> None:
    saida = aplicar(img, valores)
    assert saida.dtype == np.float32 and saida.shape == img.shape
    assert np.isfinite(saida).all()
    assert saida.min() >= 0.0 and saida.max() <= 1.0, valores


def imagens_de_borda():
    ruido = np.random.default_rng(5).random((120, 160, 3)).astype(np.float32)
    return [foto_sintetica(240, 160), cor_uniforme((0, 0, 0), 48), cor_uniforme((1, 1, 1), 48),
            cor_uniforme((1, 0, 0), 48), cor_uniforme((0, 0, 1), 48), ruido, np.round(ruido)]


@pytest.mark.parametrize("chave", CHAVES)
def test_cada_ajuste_nos_extremos_fica_em_0_1(chave):
    for img in imagens_de_borda():
        for valor in (-100, 100):
            extremos(img, {chave: valor})


def test_todos_juntos_nos_extremos_ficam_em_0_1():
    for img in imagens_de_borda():
        for sinal in (-1, 1):
            extremos(img, {p.chave: (100 if p.chave == "nitidez" else sinal * 100) for p in PARAMS})
        extremos(img, {p.chave: (100 if i % 2 else p.minimo) for i, p in enumerate(PARAMS)})


def test_imagem_minuscula_e_nao_quadrada():
    for forma in ((1, 1), (2, 3), (5, 400), (400, 5), (37, 53)):
        img = np.random.default_rng(1).random((*forma, 3)).astype(np.float32)
        extremos(img, {p.chave: 70 for p in PARAMS})


# -------------------------------------------------------------------------------------------- determinismo

def test_determinismo_bit_a_bit():
    img = foto_sintetica(500, 340)
    valores = {p.chave: (35 if i % 2 else -45) for i, p in enumerate(PARAMS)}
    valores["nitidez"] = 55
    a, b, c = aplicar(img, valores), aplicar(img.copy(), dict(valores)), aplicar(img, valores, escala_mm_px=None)
    assert a.tobytes() == b.tobytes() == c.tobytes()


# --------------------------------------------------------------------------- prévia pequena ≈ exportação

def foto_grande_com_detalhes() -> np.ndarray:
    """2400×1600: gradientes, objetos de borda nítida (quase de 1 px) e textura fina (10×15: 16 px/mm)."""
    return foto_sintetica(2400, 1600, semente=21, sigma_px=0.7)


def diferenca_previa_exportacao(valores: dict, grande: np.ndarray, fator: int = 4) -> float:
    """Média |reduzir(aplicar(grande)) − aplicar(reduzir(grande))|, passando a escala em mm correta a cada tamanho."""
    mm_grande = min(grande.shape[:2]) / 100.0  # 10×15: lado menor = 100 mm
    exportacao_reduzida = reduzir(aplicar(grande, valores, escala_mm_px=mm_grande), fator)
    previa = aplicar(reduzir(grande, fator), valores, escala_mm_px=mm_grande / fator)
    return float(np.abs(exportacao_reduzida - previa).mean())


# Limites (escala 0..1) com folga de 3 a 4× sobre o medido em foto_grande_com_detalhes (máx. medido: saturação
# 0,0003; nitidez 0,00027; os demais ≤ 0,0001).
LIMITE_PREVIA = {
    "exposicao": 0.0005, "brancos": 0.0005, "pretos": 0.0005, "contraste": 0.0005,
    "temperatura": 0.0005, "matiz": 0.0005,
    "realces": 0.0005, "sombras": 0.0005,
    "saturacao": 0.001, "vibracao": 0.001,
    "nitidez": 0.001,
}


@pytest.mark.parametrize("chave", CHAVES)
def test_previa_pequena_e_quase_igual_a_exportacao_reduzida(chave):
    grande = foto_grande_com_detalhes()
    for valor in ((60, -60) if chave != "nitidez" else (60,)):
        dif = diferenca_previa_exportacao({chave: valor}, grande)
        print(f"previa~exportacao {chave}={valor}: diferenca media {dif:.5f}")
        assert dif < LIMITE_PREVIA[chave], (chave, valor, dif)


def test_previa_pequena_e_quase_igual_a_exportacao_com_todos_ligados():
    grande = foto_grande_com_detalhes()
    valores = {p.chave: (40 if i % 2 else -40) for i, p in enumerate(PARAMS)}
    valores["nitidez"] = 50
    dif = diferenca_previa_exportacao(valores, grande)
    print(f"previa~exportacao todos: diferenca media {dif:.5f}")
    assert dif < 0.001  # medido: 0,0002


def test_previa_sem_escala_explicita_equivale_a_escala_relativa():
    grande = foto_grande_com_detalhes()
    valores = {"nitidez": 70, "realces": -50, "sombras": 40, "vibracao": 30}
    export = reduzir(aplicar(grande, valores), 4)
    previa = aplicar(reduzir(grande, 4), valores)
    dif = float(np.abs(export - previa).mean())
    print(f"previa~exportacao sem escala explicita: diferenca media {dif:.5f}")
    assert dif < 0.002


# ------------------------------------------------------------------------------------------- desempenho

def test_desempenho_todos_os_ajustes_em_1600x1067():
    img = foto_sintetica(1600, 1067)
    valores = {p.chave: (45 if i % 2 else -45) for i, p in enumerate(PARAMS)}
    valores["nitidez"] = 60
    aplicar(img, valores)  # aquece
    tempos = []
    for _ in range(3):
        t0 = time.perf_counter()
        aplicar(img, valores)
        tempos.append(time.perf_counter() - t0)
    print(f"1600x1067, todos os ajustes: melhor {min(tempos) * 1000:.0f} ms")
    assert min(tempos) < 3.0  # teto folgado: o executor do CI é ~2x mais lento; o alvo real é bem menor
