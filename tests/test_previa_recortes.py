"""A ferramenta ``tools/previa_recortes.py`` gera as prévias sem tocar na pasta das fotos."""

from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

from PIL import Image

RAIZ = Path(__file__).resolve().parent.parent


def _ferramenta():
    spec = importlib.util.spec_from_file_location("previa_recortes", RAIZ / "tools" / "previa_recortes.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def test_gera_previas_sem_mexer_nas_fotos(tmp_path):
    fotos = tmp_path / "fotos"
    fotos.mkdir()
    shutil.copy(Path(__file__).parent / "data" / "rosto_neil_armstrong.jpg", fotos / "a.jpg")
    Image.new("RGB", (300, 200), (90, 120, 150)).save(fotos / "b.png")
    (fotos / "leia.txt").write_text("não é foto", encoding="utf-8")
    antes = {p.name: p.read_bytes() for p in fotos.iterdir()}

    saida = tmp_path / "saida"
    ferramenta = _ferramenta()
    assert ferramenta.main([str(fotos), str(saida), "--proporcao", "2:3", "--lado", "300"]) == 0
    assert ferramenta.main([str(fotos), str(saida)]) == 0       # de novo: não sobrescreve

    assert {p.name: p.read_bytes() for p in fotos.iterdir()} == antes
    gerados = sorted(p.name for p in saida.iterdir())
    assert gerados == ["a_recortes.jpg", "a_recortes_1.jpg", "b_recortes.jpg", "b_recortes_1.jpg"]
    with Image.open(saida / "a_recortes.jpg") as img:
        assert img.height == 300 and img.width > 2 * 240     # dois painéis (em pé e deitado) lado a lado


def test_proporcao_aceita_dois_pontos_e_x():
    ferramenta = _ferramenta()
    assert ferramenta.ler_proporcao("2:3") == 2 / 3
    assert ferramenta.ler_proporcao("3x2") == 3 / 2
    assert ferramenta.ler_proporcao("1.5") == 1.5
