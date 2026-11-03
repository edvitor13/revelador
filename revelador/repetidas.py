"""Fotos repetidas: arquivos diferentes com a mesma imagem (ou quase), achados por uma assinatura visual.

A assinatura é um *dHash* de 64 bits: a imagem em tons de cinza reduzida a 9×8 e, em cada linha, um bit por par de
vizinhos (o da esquerda é mais claro?). Fotos iguais em outra resolução, recomprimidas ou com pequenas diferenças
de cor ficam a poucos bits de distância. Funções puras; quem chama roda fora da thread da interface.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from PIL import Image

LIMITE_PADRAO = 6   # bits diferentes (de 64) para considerar duas fotos repetidas


def assinatura(imagem: Image.Image) -> int:
    """dHash de 64 bits da imagem (já orientada)."""
    cinza = imagem.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
    px = cinza.tobytes()
    bits = 0
    for y in range(8):
        for x in range(8):
            bits = (bits << 1) | (px[y * 9 + x] > px[y * 9 + x + 1])
    return bits


def assinatura_do_arquivo(caminho: Path) -> int | None:
    """Assinatura de um arquivo de imagem (a miniatura do cache serve); None se não abrir."""
    try:
        with Image.open(caminho) as im:
            im.draft("L", (64, 64))
            return assinatura(im)
    except (OSError, ValueError):
        return None


def distancia(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def agrupar(assinaturas: Iterable[tuple[str, int]], limite: int = LIMITE_PADRAO) -> list[list[str]]:
    """Grupos (com 2 ou mais) de chaves cujas assinaturas estão a até ``limite`` bits umas das outras (ligação em
    cadeia), na ordem de entrada."""
    itens = list(assinaturas)
    pai = list(range(len(itens)))

    def raiz(i: int) -> int:
        while pai[i] != i:
            pai[i] = pai[pai[i]]
            i = pai[i]
        return i

    for i in range(len(itens)):
        for j in range(i + 1, len(itens)):
            if distancia(itens[i][1], itens[j][1]) <= limite:
                ri, rj = raiz(i), raiz(j)
                if ri != rj:
                    pai[max(ri, rj)] = min(ri, rj)
    grupos: dict[int, list[str]] = {}
    for i, (chave, _a) in enumerate(itens):
        grupos.setdefault(raiz(i), []).append(chave)
    return [g for g in grupos.values() if len(g) > 1]
