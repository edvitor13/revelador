"""Mede o tempo de ``ajustes.aplicar`` por ajuste e com tudo ligado, e a diferença contra a referência lenta.

Uso:  python tools/medir_ajustes.py [--largura 1600] [--altura 1067] [--repeticoes 5] [--referencia]

Imprime o melhor tempo (ms) de N repetições para: nenhum ajuste, cada ajuste sozinho (em +45) e todos ligados.
Com ``--referencia``, também mede a versão lenta guardada em ``tests/ajustes_referencia.py`` e mostra a diferença
máxima e média (escala 0..1) entre as duas. Imagens sintéticas; nada é lido nem gravado em disco.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "tests"))

from revelador import ajustes  # noqa: E402


def melhor_ms(funcao, repeticoes: int) -> float:
    funcao()  # aquece (alocações, tabelas)
    tempos = []
    for _ in range(repeticoes):
        t0 = time.perf_counter()
        funcao()
        tempos.append(time.perf_counter() - t0)
    return min(tempos) * 1000.0


def cenarios() -> list[tuple[str, dict]]:
    todos = {p.chave: (45 if i % 2 else -45) for i, p in enumerate(ajustes.PARAMS)}
    todos["nitidez"] = 60
    lista: list[tuple[str, dict]] = [("nenhum", {})]
    lista += [(p.chave, {p.chave: 45}) for p in ajustes.PARAMS]
    lista.append(("todos (alternados)", todos))
    lista.append(("todos em +100", {p.chave: 100 for p in ajustes.PARAMS}))
    lista.append(("todos em -100", {p.chave: (0 if p.chave == "nitidez" else -100) for p in ajustes.PARAMS}))
    return lista


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--largura", type=int, default=1600)
    ap.add_argument("--altura", type=int, default=1067)
    ap.add_argument("--repeticoes", type=int, default=5)
    ap.add_argument("--referencia", action="store_true", help="mede também a versão lenta e compara")
    args = ap.parse_args()

    from test_ajustes import foto_sintetica  # imagem sintética dos testes

    img = foto_sintetica(args.largura, args.altura)
    ref = None
    if args.referencia:
        import ajustes_referencia as ref

    cab = f"{'ajuste':<22}{'ms':>8}"
    if ref:
        cab += f"{'ms ref.':>10}{'x':>7}{'dif. máx.':>12}{'dif. média':>12}"
    print(f"{args.largura}x{args.altura}, melhor de {args.repeticoes}\n{cab}")
    for nome, valores in cenarios():
        ms = melhor_ms(lambda: ajustes.aplicar(img, valores), args.repeticoes)
        linha = f"{nome:<22}{ms:>8.1f}"
        if ref:
            ms_ref = melhor_ms(lambda: ref.aplicar(img, valores), args.repeticoes)
            d = np.abs(ajustes.aplicar(img, valores) - ref.aplicar(img, valores))
            linha += f"{ms_ref:>10.1f}{ms_ref / max(ms, 1e-3):>7.1f}{d.max():>12.6f}{d.mean():>12.7f}"
        print(linha)


if __name__ == "__main__":
    main()
