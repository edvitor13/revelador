"""Prévia do enquadramento automático em fotos reais, para validar a política de ``enquadramento.py``.

Para cada foto da PASTA: abre (com a orientação EXIF aplicada e suporte a HEIC), detecta os rostos, calcula o
recorte automático no papel em pé e deitado e grava em SAIDA um JPEG reduzido com:

- caixas dos rostos (verde = principal, amarelo = ignorado por ser pequeno demais) e os olhos;
- o recorte em pé (azul) e o deitado (laranja), com a área de fora escurecida em cada metade da imagem.

Nada é gravado na pasta das fotos, e nada sai do computador. As fotos de saída são de uso local (não as ponha no
repositório).

Uso:  python tools/previa_recortes.py PASTA SAIDA [--proporcao 2:3] [--margem 0.02] [--lado 1200]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

EXTENSOES = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".tif", ".tiff"}
AZUL, LARANJA, VERDE, AMARELO = (40, 140, 255), (255, 140, 0), (0, 220, 90), (255, 220, 0)


def ler_proporcao(texto: str) -> float:
    """``"2:3"`` → 2/3 (largura:altura do papel em pé; a versão deitada é o inverso)."""
    a, _, b = texto.replace("x", ":").partition(":")
    valor = float(a) / float(b) if b else float(a)
    if valor <= 0:
        raise argparse.ArgumentTypeError(f"proporção inválida: {texto}")
    return valor


def abrir(caminho: Path):
    from PIL import Image, ImageOps

    with Image.open(caminho) as img:
        return ImageOps.exif_transpose(img).convert("RGB")


def desenhar(img, rostos, recortes, lado: int):
    """Imagem reduzida com os rostos e os recortes desenhados. ``recortes``: [(Retangulo, cor)]."""
    from PIL import Image, ImageDraw

    from revelador.enquadramento import PRINCIPAL

    W, H = img.size
    escala = min(1.0, lado / max(W, H))
    base = img.resize((max(1, round(W * escala)), max(1, round(H * escala))), Image.Resampling.LANCZOS)
    paineis = []
    for ret, cor in recortes:
        painel = base.copy()
        sombra = Image.new("L", painel.size, 140)
        d = ImageDraw.Draw(sombra)
        caixa = [(ret.cx - ret.w / 2) * escala, (ret.cy - ret.h / 2) * escala,
                 (ret.cx + ret.w / 2) * escala, (ret.cy + ret.h / 2) * escala]
        d.rectangle(caixa, fill=0)
        painel = Image.composite(Image.new("RGB", painel.size, (0, 0, 0)), painel, sombra)
        d = ImageDraw.Draw(painel)
        espessura = max(2, round(painel.width / 300))
        d.rectangle(caixa, outline=cor, width=espessura)
        # terço superior (onde a linha dos olhos deveria ficar)
        y_terco = caixa[1] + (caixa[3] - caixa[1]) / 3
        d.line([caixa[0], y_terco, caixa[2], y_terco], fill=cor, width=max(1, espessura // 2))
        maior = max((r.w * r.h * r.confianca for r in rostos), default=0.0)
        for r in rostos:
            principal = r.w * r.h * r.confianca >= PRINCIPAL * maior
            bw, bh = base.size
            d.rectangle([r.x * bw, r.y * bh, (r.x + r.w) * bw, (r.y + r.h) * bh],
                        outline=VERDE if principal else AMARELO, width=espessura)
            if r.olhos:
                for ox, oy in r.olhos:
                    raio = espessura * 1.5
                    d.ellipse([ox * bw - raio, oy * bh - raio, ox * bw + raio, oy * bh + raio], fill=VERDE)
            d.text((r.x * bw, (r.y + r.h) * bh + 2), f"{r.confianca:.2f}", fill=VERDE if principal else AMARELO)
        paineis.append(painel)
    sep = 12
    total = Image.new("RGB", (sum(p.width for p in paineis) + sep * (len(paineis) - 1), base.height), (255, 255, 255))
    x = 0
    for p in paineis:
        total.paste(p, (x, 0))
        x += p.width + sep
    return total


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Prévia do enquadramento automático pelos rostos.")
    ap.add_argument("pasta", type=Path, help="pasta com as fotos (não é alterada)")
    ap.add_argument("saida", type=Path, help="pasta onde gravar as prévias")
    ap.add_argument("--proporcao", type=ler_proporcao, default=2 / 3,
                    help="largura:altura do papel em pé (padrão 2:3, o 10x15)")
    ap.add_argument("--margem", type=float, default=0.0,
                    help="margem de corte como fração do lado menor do papel (ex.: 0.02)")
    ap.add_argument("--lado", type=int, default=1200, help="lado maior de cada metade da prévia, em px")
    args = ap.parse_args(argv)

    import numpy as np
    import pillow_heif

    from revelador import enquadramento, rostos as detector

    pillow_heif.register_heif_opener()
    em_pe = min(args.proporcao, 1 / args.proporcao)
    pasta, saida = args.pasta.resolve(), args.saida.resolve()
    if saida == pasta:
        print("A pasta de saída tem de ser diferente da pasta das fotos.", file=sys.stderr)
        return 2
    saida.mkdir(parents=True, exist_ok=True)

    fotos = sorted(p for p in pasta.iterdir() if p.suffix.lower() in EXTENSOES and p.is_file())
    if not fotos:
        print(f"Nenhuma foto em {pasta}.", file=sys.stderr)
        return 1
    for caminho in fotos:
        try:
            img = abrir(caminho)
        except Exception as exc:  # noqa: BLE001 - ferramenta: segue para a próxima foto
            print(f"{caminho.name}: não abriu ({exc})", file=sys.stderr)
            continue
        W, H = img.size
        achados = detector.detectar(np.asarray(img))
        recortes = []
        for proporcao, cor in ((em_pe, AZUL), (1 / em_pe, LARANJA)):
            rec = enquadramento.recorte_automatico(W, H, proporcao, achados, margem=args.margem)
            recortes.append((enquadramento.retangulo(rec, W, H, proporcao), cor))
        destino = saida / f"{caminho.stem}_recortes.jpg"
        n = 1
        while destino.exists():   # nunca sobrescreve
            destino = saida / f"{caminho.stem}_recortes_{n}.jpg"
            n += 1
        desenhar(img, achados, recortes, args.lado).save(destino, "JPEG", quality=88)
        print(f"{caminho.name}: {len(achados)} rosto(s) → {destino.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
