"""Converte o LICENSE (texto) no .rtf que a tela de licença do instalador .msi mostra.

Uso:  python packaging/windows/license_rtf.py LICENSE saida.rtf
"""

from __future__ import annotations

import sys
from pathlib import Path

CABECALHO = "O Revelador é software livre, distribuído sob a licença MIT (texto original abaixo)."


def _escape(text: str) -> str:
    out = []
    for ch in text:
        if ch in "\\{}":
            out.append("\\" + ch)
        elif ord(ch) > 127:
            code = ord(ch)
            out.append(f"\\u{code if code < 32768 else code - 65536}?")
        else:
            out.append(ch)
    return "".join(out)


def to_rtf(text: str) -> str:
    paragrafos = [_escape(CABECALHO), ""]
    paragrafos += [_escape(line.rstrip()) for line in text.splitlines()]
    corpo = "\\par\n".join(paragrafos)
    return (
        "{\\rtf1\\ansi\\ansicpg1252\\deff0\\uc1"
        "{\\fonttbl{\\f0\\fswiss\\fcharset0 Segoe UI;}}"
        "\\viewkind4\\pard\\sa0\\sl240\\slmult1\\f0\\fs18\n"
        f"{corpo}\\par\n}}\n"
    )


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__.strip())
        return 2
    src, dst = Path(argv[0]), Path(argv[1])
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(to_rtf(src.read_text(encoding="utf-8")), encoding="ascii", newline="\r\n")
    print(f"Licença em RTF: {dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
