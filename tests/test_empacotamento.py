"""Contrato do empacotamento: versão, marcador de instalação, .msi e nomes dos pacotes.

O atualizador automático (#10) depende de tudo isto: o nome dos pacotes da release, o marcador
revelador-install.json e o UpgradeCode do .msi nunca podem mudar sem cuidado.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

import revelador

ROOT = Path(__file__).resolve().parent.parent
UPGRADE_CODE = "E717D955-5229-48D9-BAF0-C0C95B783A82"


def _carregar(caminho: Path):
    # A pasta packaging/ não é um pacote (e "packaging" é o nome de uma biblioteca do pip): carrega pelo caminho.
    spec = importlib.util.spec_from_file_location(caminho.stem, caminho)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


install_marker = _carregar(ROOT / "packaging" / "install_marker.py")
license_rtf = _carregar(ROOT / "packaging" / "windows" / "license_rtf.py")


def test_versao_e_data():
    assert re.fullmatch(r"\d+\.\d+\.\d+", revelador.__version__)
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", revelador.__date__)
    assert revelador.APP_NAME == "Revelador"


def test_marcador_le_a_mesma_versao_do_app():
    assert install_marker.read_version() == revelador.__version__


@pytest.mark.parametrize("tipo", install_marker.KINDS)
def test_marcador_grava_o_json(tmp_path, tipo):
    caminho = install_marker.write_marker(tmp_path, tipo, "1.2.3")
    assert caminho.name == "revelador-install.json"
    assert json.loads(caminho.read_text(encoding="utf-8")) == {"kind": tipo, "version": "1.2.3"}


@pytest.mark.parametrize("tipo, versao", [("deb", "1.2.3"), ("msi", "1.2"), ("msi", "1.2.3-beta"), ("zip", "")])
def test_marcador_recusa_tipo_ou_versao_invalidos(tmp_path, tipo, versao):
    with pytest.raises(SystemExit):
        install_marker.write_marker(tmp_path, tipo, versao)


def test_upgrade_code_do_msi_nunca_muda():
    wxs = (ROOT / "packaging" / "windows" / "Revelador.wxs").read_text(encoding="utf-8")
    assert re.findall(r'UpgradeCode="([0-9A-F-]{36})"', wxs) == [UPGRADE_CODE]
    assert UPGRADE_CODE in (ROOT / "AGENTS.md").read_text(encoding="utf-8")


def test_guids_dos_componentes_sao_unicos():
    wxs = (ROOT / "packaging" / "windows" / "Revelador.wxs").read_text(encoding="utf-8")
    guids = re.findall(r'Guid="([0-9A-F-]{36})"', wxs)
    assert len(guids) == len(set(guids)) >= 3
    assert UPGRADE_CODE not in guids


def test_nomes_dos_pacotes_batem_com_o_ci():
    # O atualizador escolhe o pacote da release por estes sufixos (updater.PATTERNS, #10).
    build = (ROOT / ".github" / "workflows" / "build.yml").read_text(encoding="utf-8")
    assert 'echo "base=Revelador-$label-windows-x64"' in build
    assert '"$env:BASE.msi"' in build and '"$env:BASE.zip"' in build
    assert "sha256sum Revelador-* > SHA256SUMS.txt" in build


def test_spec_le_a_versao_e_leva_os_assets():
    spec = (ROOT / "Revelador.spec").read_text(encoding="utf-8")
    assert '"revelador", "__init__.py"' in spec
    assert '"assets"' in spec and "logo.ico" in spec
    assert (ROOT / "assets" / "logo.ico").is_file()


def test_licenca_em_rtf_escapa_chaves_e_acentos():
    rtf = license_rtf.to_rtf(r"Licença {MIT}\fim")
    assert rtf.startswith(r"{\rtf1") and rtf.rstrip().endswith("}")
    assert r"Licen\u231?a \{MIT\}\\fim" in rtf
    assert "Revelador" in rtf
    rtf.encode("ascii")  # o .msi lê a licença como ASCII puro


def test_scripts_powershell_com_bom():
    # O Windows PowerShell 5.1 (build.bat local) só lê acentos de um .ps1 em UTF-8 com BOM.
    for ps1 in (ROOT / "packaging" / "windows").glob("*.ps1"):
        assert ps1.read_bytes().startswith(b"\xef\xbb\xbf"), ps1.name
