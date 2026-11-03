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
discord = _carregar(ROOT / "packaging" / "discord_notify.py")


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


def test_msi_associa_revelador_por_usuario():
    wxs = (ROOT / "packaging" / "windows" / "Revelador.wxs").read_text(encoding="utf-8")
    assert 'Feature Id="AssociacaoRevelador"' in wxs
    classes = re.findall(r'Root="(\w+)" Key="(Software[\\]Classes[^"]*)"', wxs)
    assert len(classes) == 4 and {r for r, _k in classes} == {"HKCU"}   # nada em HKLM: instalação sem administrador
    assert r'Key="Software\Classes\.revelador" Type="string" Value="Revelador.Trabalho"' in wxs
    assert "&quot;%1&quot;" in wxs and "DefaultIcon" in wxs


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


# ------------------------------------------------------------------ avisos no Discord
def test_discord_resumo_para_na_divisoria_e_pula_o_titulo():
    texto = "# Título\n\n<!-- nota -->\n## Novidades\n- um\n- dois\n![img](x.png)\n\n---\n\nDetalhes\n"
    resumo = discord.resumo_novidades(texto)
    assert resumo.splitlines()[0] == "**Novidades**"
    assert "- um" in resumo and "- dois" in resumo
    assert "Título" not in resumo and "Detalhes" not in resumo and "img" not in resumo and "nota" not in resumo


def test_discord_resumo_e_cortado():
    resumo = discord.resumo_novidades("\n".join(f"- item {i}" for i in range(50)), limite=2000, linhas=5)
    assert resumo.count("- item") == 5 and resumo.endswith("…")


def test_discord_mensagem_da_release(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "dono/repo")
    monkeypatch.setenv("DISCORD_WEBHOOK", "https://discord.com/api/webhooks/123/segredo")
    for nome in ("Revelador-v0.1.0-windows-x64.msi", "Revelador-v0.1.0-windows-x64.zip", "SHA256SUMS.txt"):
        (tmp_path / nome).write_text("x", encoding="utf-8")
    notas = tmp_path / "notas.md"
    notas.write_text("# Revelador 0.1.0\n\n## Novidades\n- enquadramento pelos rostos\n\n---\n\nresto\n",
                     encoding="utf-8")
    payload = discord.msg_release("v0.1.0", notas, tmp_path)
    assert "segredo" not in json.dumps(payload, ensure_ascii=False)  # o webhook nunca entra na mensagem
    embed = payload["embeds"][0]
    assert embed["title"] == "Revelador 0.1.0 está disponível"
    assert "enquadramento pelos rostos" in embed["description"] and "resto" not in embed["description"]
    campos = {c["name"]: c["value"] for c in embed["fields"]}
    assert set(campos) == {"Windows", "Conferência"}
    base = "https://github.com/dono/repo/releases/download/v0.1.0/"
    assert base + "Revelador-v0.1.0-windows-x64.msi" in campos["Windows"]
    assert base + "Revelador-v0.1.0-windows-x64.zip" in campos["Windows"]


def test_discord_sem_webhook_nao_envia_nada(monkeypatch, capsys):
    monkeypatch.delenv("DISCORD_WEBHOOK", raising=False)

    def proibido(*a, **k):
        raise AssertionError("não deveria acessar a rede")

    monkeypatch.setattr(discord.urllib.request, "urlopen", proibido)
    assert discord.main(["teste"]) == 0
    assert "não definido" in capsys.readouterr().out


def test_discord_recusa_endereco_que_nao_e_do_discord(monkeypatch):
    def proibido(*a, **k):
        raise AssertionError("não deveria acessar a rede")

    monkeypatch.setattr(discord.urllib.request, "urlopen", proibido)
    assert discord.enviar({"content": "x"}, "https://exemplo.com/api/webhooks/1/2") == 1
