"""Atualizador: versões, escolha do pacote, conferência do SHA-256, zip seguro e script gerado (sem rede)."""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
import sys
import urllib.error
import zipfile
from pathlib import Path

import pytest

from revelador import __version__, updater


def release(names, tag="v9.0.0"):
    assets = {n: (f"https://example.invalid/{n}", 10) for n in names}
    return updater.Release(tag=tag, version=updater.parse_version(tag), name=tag, body="", url="u",
                           published="2026-11-03", assets=assets)


@pytest.mark.parametrize("text, expected", [("v1.2.3", (1, 2, 3)), ("1.10", (1, 10)), ("v2.0.0-beta", (2, 0, 0)),
                                            ("", (0,)), ("abc", (0,))])
def test_parse_version(text, expected):
    assert updater.parse_version(text) == expected


def test_is_newer():
    cur = updater.current_version()
    assert updater.is_newer(release([], "v" + ".".join(str(n) for n in (cur[0] + 1, 0, 0))))
    assert not updater.is_newer(release([], "v" + __version__))
    assert not updater.is_newer(release([], "v0.0.1"))


def test_is_newer_ignora_pre_release():
    cur = updater.current_version()
    beta = "v" + ".".join(str(n) for n in (cur[0] + 1, 0, 0)) + "-beta.1"
    assert not updater.is_newer(release([], beta))


NAMES = ["Revelador-v9.0.0-windows-x64.msi", "Revelador-v9.0.0-windows-x64.zip",
         "Revelador-v9.0.0-linux-x64.deb", "Revelador-v9.0.0-linux-x64.tar.gz",
         "Revelador-v9.0.0-macos.dmg", "SHA256SUMS.txt"]


@pytest.mark.parametrize("kind, expected", [("msi", NAMES[0]), ("zip", NAMES[1])])
def test_pick_asset(kind, expected):
    assert updater.pick_asset(release(NAMES), kind)[0] == expected


@pytest.mark.parametrize("kind", ["deb", "tar", "dmg"])
def test_pick_asset_outros_sistemas_ignorados(kind):
    assert updater.pick_asset(release(NAMES), kind) is None


def test_pick_asset_missing_or_source():
    assert updater.pick_asset(release(NAMES[1:]), "msi") is None
    assert updater.pick_asset(release(NAMES), "source") is None


def test_install_info_from_source():
    assert updater.install_info() == {"kind": "source"}
    assert not updater.can_auto_install("source")


def test_install_info_com_marcador(monkeypatch, tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    (app / "revelador-install.json").write_text(json.dumps({"kind": "msi", "version": "9.0.0"}), encoding="utf-8")
    monkeypatch.setattr(updater.sys, "frozen", True, raising=False)
    monkeypatch.setattr(updater.sys, "executable", str(app / "Revelador.exe"))
    assert updater.install_info() == {"kind": "msi", "version": "9.0.0"}


def test_install_info_sem_marcador_e_zip(monkeypatch, tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    monkeypatch.setattr(updater.sys, "frozen", True, raising=False)
    monkeypatch.setattr(updater.sys, "executable", str(app / "Revelador.exe"))
    assert updater.install_info() == {"kind": "zip"}


def test_marcador_em_internal(monkeypatch, tmp_path):
    app = tmp_path / "app"
    (app / "_internal").mkdir(parents=True)
    (app / "_internal" / "revelador-install.json").write_text('{"kind": "zip"}', encoding="utf-8")
    monkeypatch.setattr(updater.sys, "frozen", True, raising=False)
    monkeypatch.setattr(updater.sys, "executable", str(app / "Revelador.exe"))
    assert updater.install_info() == {"kind": "zip"}


def test_can_auto_install_so_windows(monkeypatch):
    monkeypatch.setattr(updater.sys, "platform", "win32")
    assert updater.can_auto_install("msi") and updater.can_auto_install("zip")
    assert not updater.can_auto_install("source")
    monkeypatch.setattr(updater.sys, "platform", "linux")
    assert not updater.can_auto_install("zip")


class FakeResponse(io.BytesIO):
    def __init__(self, data: bytes):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake_urlopen(routes):
    def opener(req, timeout=0):
        url = req.full_url if hasattr(req, "full_url") else req
        if url not in routes:
            raise urllib.error.HTTPError(url, 404, "nf", {}, None)
        return FakeResponse(routes[url])
    return opener


def test_check_parses_api(monkeypatch):
    api = {"tag_name": "v9.0.0", "name": "9.0", "body": "notas", "html_url": "https://github.com/x",
           "published_at": "2026-11-03T10:00:00Z",
           "assets": [{"name": NAMES[0], "browser_download_url": "https://d/msi", "url": "https://api/msi", "size": 5}]}
    monkeypatch.delenv("REVELADOR_GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(updater.urllib.request, "urlopen", fake_urlopen({updater.API_LATEST: json.dumps(api).encode()}))
    rel = updater.check()
    assert rel.tag == "v9.0.0" and rel.version == (9, 0, 0)
    assert rel.assets[NAMES[0]] == ("https://d/msi", 5)
    assert rel.published == "2026-11-03" and rel.body == "notas"


def test_check_com_token_usa_api(monkeypatch):
    api = {"tag_name": "v9.0.0", "assets": [{"name": NAMES[0], "browser_download_url": "https://d/msi",
                                              "url": "https://api/msi", "size": 5}]}
    monkeypatch.setenv("REVELADOR_GITHUB_TOKEN", "segredo")
    monkeypatch.setattr(updater.urllib.request, "urlopen", fake_urlopen({updater.API_LATEST: json.dumps(api).encode()}))
    assert updater.check().assets[NAMES[0]] == ("https://api/msi", 5)


def test_check_private_repo_404(monkeypatch):
    monkeypatch.setattr(updater.urllib.request, "urlopen", fake_urlopen({}))
    with pytest.raises(updater.UpdateError, match="no-public-release"):
        updater.check()


def test_check_offline(monkeypatch):
    def boom(*a, **k):
        raise OSError("sem rede")
    monkeypatch.setattr(updater.urllib.request, "urlopen", boom)
    with pytest.raises(updater.UpdateError, match="offline"):
        updater.check()


def test_download_verifies_checksum(monkeypatch):
    payload = b"conteudo do instalador" * 100
    good = hashlib.sha256(payload).hexdigest()
    rel = release(NAMES)
    name = NAMES[1]
    sums_url = rel.assets["SHA256SUMS.txt"][0]
    routes = {rel.assets[name][0]: payload, sums_url: f"{good}  {name}\n".encode()}
    monkeypatch.setattr(updater.urllib.request, "urlopen", fake_urlopen(routes))
    path = updater.download(rel, (name, rel.assets[name][0], len(payload)))
    assert Path(path).read_bytes() == payload


def test_download_rejects_bad_checksum(monkeypatch):
    rel = release(NAMES)
    name = NAMES[1]
    routes = {rel.assets[name][0]: b"adulterado", rel.assets["SHA256SUMS.txt"][0]: f"{'0' * 64}  {name}\n".encode()}
    monkeypatch.setattr(updater.urllib.request, "urlopen", fake_urlopen(routes))
    with pytest.raises(updater.UpdateError, match="checksum-mismatch"):
        updater.download(rel, (name, rel.assets[name][0], 10))


def test_download_requires_checksums(monkeypatch):
    rel = release(NAMES[:-1])
    with pytest.raises(updater.UpdateError, match="no-checksums"):
        updater.download(rel, (NAMES[1], rel.assets[NAMES[1]][0], 10))


# ------------------------------------------------------------------ instalação (Windows)
windows_only = pytest.mark.skipif(sys.platform != "win32", reason="instalação por PowerShell só no Windows")


def _zip_com(tmp_path: Path, entradas: dict[str, bytes]) -> Path:
    pacote = tmp_path / "Revelador-v9.0.0-windows-x64.zip"
    with zipfile.ZipFile(pacote, "w") as z:
        for nome, dados in entradas.items():
            z.writestr(nome, dados)
    return pacote


@pytest.mark.parametrize("nome", ["/evil.txt", "C:/evil.txt", "\\\\servidor\\x.txt", "../evil.txt",
                                  "a/../../evil.txt", "..\\evil.txt"])
def test_zip_com_caminho_perigoso_recusado(tmp_path, monkeypatch, nome):
    pacote = _zip_com(tmp_path, {"Revelador.exe": b"x", nome: b"y"})
    spawned = []
    monkeypatch.setattr(updater, "spawn_powershell", spawned.append)
    monkeypatch.setattr(updater.sys, "platform", "win32")
    with pytest.raises(updater.UpdateError, match="bad-archive"):
        updater.install(str(pacote), "zip")
    assert spawned == []
    assert not (tmp_path / "novo").exists()


@windows_only
def test_install_msi_writes_logged_script(tmp_path, monkeypatch):
    work = tmp_path / "pasta d'Ana"  # apóstrofo no caminho precisa ser escapado
    work.mkdir()
    pkg = work / "Revelador-v9.0.0-windows-x64.msi"
    pkg.write_bytes(b"x")
    spawned = []
    monkeypatch.setattr(updater, "spawn_powershell", spawned.append)
    monkeypatch.setattr(updater.sys, "executable", str(tmp_path / "App d'Ana" / "Revelador.exe"))
    updater.install(str(pkg), "msi")
    assert spawned == [work / "atualizar.ps1"]
    body = spawned[0].read_text(encoding="utf-8-sig")
    assert body.startswith("Start-Transcript -Path '") and "d''Ana" in body
    assert "msiexec.exe" in body and "'/passive'" in body and "'/l*v'" in body and "instalar.log" in body
    assert body.index("msiexec.exe") < body.index("Process]::Start(") < body.index("Stop-Transcript")
    assert "$psi.UseShellExecute = $false" in body  # reabre direto, sem o shell do Windows
    assert "App d''Ana" in body


@windows_only
def test_install_zip_script_usa_robocopy(tmp_path, monkeypatch):
    pacote = _zip_com(tmp_path, {"Revelador/Revelador.exe": b"x", "Revelador/_internal/a.dll": b"y"})
    spawned = []
    monkeypatch.setattr(updater, "spawn_powershell", spawned.append)
    monkeypatch.setattr(updater.sys, "executable", str(tmp_path / "App" / "Revelador.exe"))
    updater.install(str(pacote), "zip")
    body = spawned[0].read_text(encoding="utf-8-sig")
    assert "robocopy" in body and "/MIR" in body
    assert (tmp_path / "novo" / "Revelador" / "Revelador.exe").is_file()


def test_install_tipo_desconhecido_unsupported(monkeypatch, tmp_path):
    monkeypatch.setattr(updater.sys, "platform", "win32")
    with pytest.raises(updater.UpdateError, match="unsupported"):
        updater.install(str(tmp_path / "x.deb"), "deb")


def test_spawn_does_not_use_detached_process(monkeypatch):
    calls = []
    monkeypatch.setattr(updater.subprocess, "Popen", lambda *a, **k: calls.append(k))
    updater.spawn_powershell(Path("x.ps1"))
    flags = calls[0]["creationflags"]
    assert not flags & 0x00000008  # DETACHED_PROCESS derruba o PowerShell sem console
    assert calls[0]["stdin"] is subprocess.DEVNULL


def test_ps_escapa_aspas_simples():
    assert updater._ps("a'b") == "'a''b'"
