"""Grava o marcador ``revelador-install.json`` ao lado do executável do Revelador.

O atualizador do app lê esse arquivo para saber como o programa foi instalado e, assim, qual pacote baixar na
hora de atualizar:

    {"kind": "msi" | "zip", "version": "x.y.z"}

Uso:
    python packaging/install_marker.py PASTA TIPO [--version X.Y.Z]
    python packaging/install_marker.py --print-version

PASTA é a pasta do executável (``dist/Revelador``). Sem ``--version``, a versão vem de
``revelador/__init__.py`` (lida como texto, sem importar o pacote).

Só biblioteca padrão: roda no CI e em qualquer Python 3.10+. Quando o Linux chegar, os tipos ``deb`` e ``tar``
entram aqui e em ``updater.PATTERNS``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

MARKER = "revelador-install.json"
KINDS = ("msi", "zip")
ROOT = Path(__file__).resolve().parent.parent


def read_version(root: Path = ROOT) -> str:
    """Versão de ``revelador/__init__.py`` (``__version__ = "x.y.z"``)."""
    text = (root / "revelador" / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r"""^__version__\s*=\s*["']([^"']+)["']""", text, re.MULTILINE)
    if not m:
        raise SystemExit("Não encontrei __version__ em revelador/__init__.py")
    return m.group(1)


def write_marker(folder: Path, kind: str, version: str) -> Path:
    if kind not in KINDS:
        raise SystemExit(f"Tipo inválido: {kind!r} (use um de: {', '.join(KINDS)})")
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise SystemExit(f"Versão inválida: {version!r} (use x.y.z)")
    if not folder.is_dir():
        raise SystemExit(f"A pasta não existe: {folder}")
    path = folder / MARKER
    data = {"kind": kind, "version": version}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Grava o revelador-install.json ao lado do executável.")
    ap.add_argument("folder", nargs="?", type=Path, help="pasta do executável")
    ap.add_argument("kind", nargs="?", choices=KINDS, help="tipo de pacote")
    ap.add_argument("--version", help="versão x.y.z (padrão: revelador/__init__.py)")
    ap.add_argument("--print-version", action="store_true", help="só mostra a versão do app e sai")
    args = ap.parse_args(argv)

    if args.print_version:
        print(read_version())
        return 0
    if args.folder is None or args.kind is None:
        ap.error("informe PASTA e TIPO (ou --print-version)")

    path = write_marker(args.folder, args.kind, args.version or read_version())
    print(f"Marcador gravado: {path} -> {path.read_text(encoding='utf-8').strip()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
