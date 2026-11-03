# -*- mode: python ; coding: utf-8 -*-
# Receita do PyInstaller para o Revelador (Windows; o código fica portável para o Linux depois).
#
# Gera uma pasta única (onedir):
#     dist/Revelador/Revelador.exe     (janela, sem console)
#     dist/Revelador/_internal/        (Python, Qt, numpy, Pillow, pillow-heif, OpenCV, assets)
#
# Uso:  python -m PyInstaller --noconfirm --clean Revelador.spec
#
# Depois de gerar, confira as dependências nativas de verdade:
#     powershell -File packaging\windows\diagnosticar.ps1 -Exe dist\Revelador\Revelador.exe
# Os pacotes (.msi e .zip) são montados a partir desta pasta: veja packaging/.

import os
import re
import sys

ROOT = SPECPATH  # noqa: F821  (variável injetada pelo PyInstaller)
NAME = "Revelador"

# Versão lida do código (sem importar o pacote), usada nos metadados do executável.
with open(os.path.join(ROOT, "revelador", "__init__.py"), encoding="utf-8") as _f:
    VERSION = re.search(r'__version__\s*=\s*"([^"]+)"', _f.read()).group(1)

ICON = os.path.join(ROOT, "assets", "logo.ico") if sys.platform == "win32" else None


def version_info(description, filename):
    """Metadados do .exe (Propriedades > Detalhes)."""
    if sys.platform != "win32":
        return None
    from PyInstaller.utils.win32.versioninfo import (FixedFileInfo, StringFileInfo, StringStruct, StringTable,
                                                     VarFileInfo, VarStruct, VSVersionInfo)
    nums = tuple(int(n) for n in re.findall(r"\d+", VERSION)[:3])
    nums = nums + (0,) * (4 - len(nums))
    return VSVersionInfo(
        ffi=FixedFileInfo(filevers=nums, prodvers=nums, mask=0x3F, flags=0x0, OS=0x40004, fileType=0x1,
                          subtype=0x0, date=(0, 0)),
        kids=[
            StringFileInfo([StringTable("041604B0", [  # pt-BR, Unicode
                StringStruct("CompanyName", "Vitor Gabriel"),
                StringStruct("FileDescription", description),
                StringStruct("FileVersion", VERSION),
                StringStruct("InternalName", filename.rsplit(".", 1)[0]),
                StringStruct("LegalCopyright", "© 2026 Vitor Gabriel. Licença MIT."),
                StringStruct("OriginalFilename", filename),
                StringStruct("ProductName", NAME),
                StringStruct("ProductVersion", VERSION),
            ])]),
            VarFileInfo([VarStruct("Translation", [0x0416, 1200])]),
        ],
    )


# Dados lidos em tempo de execução: assets sempre; modelos (rostos) e notas da versão quando existirem.
DATAS = [(os.path.join(ROOT, "assets"), "assets")]
for _sub in ("data", "novidades"):
    _src = os.path.join(ROOT, "revelador", _sub)
    if os.path.isdir(_src):
        DATAS.append((_src, os.path.join("revelador", _sub)))

a = Analysis(  # noqa: F821
    [os.path.join(ROOT, "Revelador.pyw")],
    pathex=[ROOT],
    binaries=[],
    datas=DATAS,
    # pillow_heif é registrado em tempo de execução (register_heif_opener) e o diagnóstico o importa dentro
    # de função; listado aqui para nunca depender da análise automática.
    hiddenimports=["revelador.diagnostico", "pillow_heif"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=ICON,
    version=version_info(NAME, f"{NAME}.exe"),
)
coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=NAME,
)
