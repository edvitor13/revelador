"""Detecção de rostos (YuNet empacotado): modelo íntegro, rosto real achado, nunca lança exceção."""

from __future__ import annotations

import logging
import threading
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from revelador import rostos
from revelador.projeto import Rosto

FOTO = Path(__file__).parent / "data" / "rosto_neil_armstrong.jpg"
# Caixa do rosto conferida à mão na foto de 500×625 px (sobrancelhas ao queixo), normalizada.
ROSTO_ESPERADO = (267 / 500, 121 / 625, 81 / 500, 108 / 625)


@pytest.fixture(scope="module")
def foto() -> np.ndarray:
    return np.asarray(Image.open(FOTO).convert("RGB"))


def test_modelo_empacotado_com_sha256_fixo():
    assert rostos.MODELO == Path(rostos.__file__).parent / "data" / "modelos" / "face_detection_yunet_2023mar.onnx"
    assert rostos.MODELO.stat().st_size > 200_000           # o ONNX de verdade, não o ponteiro do Git LFS
    assert rostos.sha256_modelo() == rostos.SHA256_MODELO
    licenca = (rostos.PASTA_MODELOS / "LICENSE").read_text(encoding="utf-8")
    assert "MIT License" in licenca and "Shiqi Yu" in licenca


def test_foto_de_teste_registrada_e_pequena():
    assert FOTO.stat().st_size <= 100_000
    assert FOTO.name in (FOTO.parent / "LICENCAS.md").read_text(encoding="utf-8")


def _iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    ax1, ay1, bx1, by1 = a[0] + a[2], a[1] + a[3], b[0] + b[2], b[1] + b[3]
    iw = max(0.0, min(ax1, bx1) - max(a[0], b[0]))
    ih = max(0.0, min(ay1, by1) - max(a[1], b[1]))
    inter = iw * ih
    return inter / (a[2] * a[3] + b[2] * b[3] - inter)


def confere_rosto_da_foto(achados: list[Rosto]) -> None:
    assert len(achados) == 1, achados
    r = achados[0]
    assert isinstance(r, Rosto)
    assert _iou((r.x, r.y, r.w, r.h), ROSTO_ESPERADO) > 0.6
    assert 0.6 <= r.confianca <= 1.0
    assert r.olhos is not None
    (ox1, oy1), (ox2, oy2) = r.olhos
    for ox, oy in r.olhos:
        assert r.x < ox < r.x + r.w and r.y < oy < r.y + r.h * 0.6   # olhos na metade de cima do rosto
    assert abs(oy1 - oy2) < 0.02                                      # retrato reto: olhos na mesma altura
    assert ox1 != ox2


def test_acha_o_rosto_na_foto_uint8(foto):
    confere_rosto_da_foto(rostos.detectar(foto))


def test_acha_o_rosto_na_foto_float(foto):
    a = foto.astype(np.float32) / 255.0
    achados = rostos.detectar(a)
    confere_rosto_da_foto(achados)
    u = rostos.detectar(foto)[0]
    f = achados[0]
    assert (f.x, f.y, f.w, f.h) == pytest.approx((u.x, u.y, u.w, u.h), abs=0.01)


def test_imagem_grande_e_reduzida_e_coordenadas_continuam_normalizadas(foto):
    """Foto ampliada 4× (2000×2500): a detecção roda a 1280 px e devolve as mesmas coordenadas normalizadas."""
    grande = np.asarray(Image.fromarray(foto).resize((2000, 2500), Image.Resampling.BICUBIC))
    confere_rosto_da_foto(rostos.detectar(grande))


def test_foto_com_borda_lateral_larga(foto):
    """O rosto no meio de uma foto bem mais larga (panorâmica) continua achado, na posição certa."""
    alt, larg = foto.shape[:2]
    pano = np.zeros((alt, larg * 3, 3), np.uint8)
    pano[:, larg:2 * larg] = foto
    achados = rostos.detectar(pano)
    assert len(achados) == 1
    r = achados[0]
    esperado = ((ROSTO_ESPERADO[0] + 1) / 3, ROSTO_ESPERADO[1], ROSTO_ESPERADO[2] / 3, ROSTO_ESPERADO[3])
    assert _iou((r.x, r.y, r.w, r.h), esperado) > 0.6


@pytest.mark.parametrize("imagem", [
    np.zeros((480, 640, 3), np.uint8),
    np.full((300, 300, 3), 255, np.uint8),
    np.linspace(0, 1, 200 * 320 * 3, dtype=np.float32).reshape(200, 320, 3),
    np.random.default_rng(4).integers(0, 256, (240, 320, 3), dtype=np.uint8),
])
def test_imagem_sem_rosto_devolve_lista_vazia(imagem):
    assert rostos.detectar(imagem) == []


def test_aceita_cinza_e_rgba(foto):
    cinza = np.asarray(Image.fromarray(foto).convert("L"))
    assert len(rostos.detectar(cinza)) == 1
    rgba = np.dstack([foto, np.full(foto.shape[:2], 255, np.uint8)])
    assert len(rostos.detectar(rgba)) == 1


def test_rosto_pequeno_demais_e_descartado(foto, monkeypatch):
    monkeypatch.setattr(rostos, "LARGURA_MINIMA", 0.5)    # o rosto tem ~16% da largura
    assert rostos.detectar(foto) == []


@pytest.mark.parametrize("entrada", [None, "foto.jpg", np.zeros((10,), np.uint8), np.zeros((1, 1, 3), np.uint8),
                                     np.zeros((0, 0, 3), np.uint8), np.zeros((20, 20, 2), np.uint8)])
def test_entrada_invalida_nunca_lanca(entrada, caplog):
    with caplog.at_level(logging.ERROR, logger="revelador.rostos"):
        assert rostos.detectar(entrada) == []


def test_falha_do_opencv_vira_lista_vazia_e_registro(foto, monkeypatch, caplog):
    def quebra(*_args):
        raise RuntimeError("DNN quebrado")

    monkeypatch.setattr(rostos, "_detector_da_thread", quebra)
    with caplog.at_level(logging.ERROR, logger="revelador.rostos"):
        assert rostos.detectar(foto) == []
    assert "DNN quebrado" in caplog.text


def test_um_detector_por_thread(foto):
    """Várias threads ao mesmo tempo (o detector do OpenCV não é seguro entre threads): todas acham o rosto."""
    resultados: list[list[Rosto]] = []
    trava = threading.Lock()

    def trabalho():
        r = rostos.detectar(foto)
        with trava:
            resultados.append(r)

    threads = [threading.Thread(target=trabalho) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(resultados) == 4
    for r in resultados:
        confere_rosto_da_foto(r)
