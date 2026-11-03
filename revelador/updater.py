"""Atualização automática pelas releases do GitHub.

Fluxo: consulta a última release, compara com a versão instalada, baixa o pacote do mesmo tipo
da instalação atual (.msi ou .zip), confere o SHA-256 publicado em SHA256SUMS.txt e entrega a
troca para um script PowerShell que roda depois que o app fecha (o executável em uso não pode ser
substituído enquanto está aberto).

Só Windows por enquanto (#12 cuida de Linux e macOS). O repositório precisa ser público para a
consulta funcionar sem login. Para testar com o repositório privado, defina a variável de ambiente
REVELADOR_GITHUB_TOKEN.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Callable

from . import APP_NAME, __version__

REPO = "edvitor13/revelador"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases"
SUMS_NAME = "SHA256SUMS.txt"
MARKER = "revelador-install.json"
NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
NEW_PROCESS_GROUP = 0x00000200 if sys.platform == "win32" else 0


class UpdateError(Exception):
    pass


@dataclass
class Release:
    tag: str
    version: tuple
    name: str
    body: str
    url: str
    published: str
    assets: dict[str, tuple[str, int]] = field(default_factory=dict)  # nome -> (url, tamanho)


def parse_version(text: str) -> tuple:
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", text or "")
    return tuple(int(x) for x in m.groups() if x is not None) if m else (0,)


def current_version() -> tuple:
    return parse_version(__version__)


def _headers(accept: str = "application/vnd.github+json") -> dict:
    h = {"User-Agent": f"{APP_NAME}/{__version__}", "Accept": accept}
    token = os.environ.get("REVELADOR_GITHUB_TOKEN")
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def check(timeout: float = 8.0) -> Release:
    """Última release publicada. Lança UpdateError se não der para consultar."""
    req = urllib.request.Request(API_LATEST, headers=_headers())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise UpdateError("no-public-release") from exc
        raise UpdateError(f"http-{exc.code}") from exc
    except (OSError, ValueError) as exc:
        raise UpdateError("offline") from exc
    assets = {}
    for a in data.get("assets", []):
        # Com token (repositório privado) o download precisa passar pela API.
        url = a.get("url") if os.environ.get("REVELADOR_GITHUB_TOKEN") else a.get("browser_download_url")
        assets[a.get("name", "")] = (url, int(a.get("size") or 0))
    tag = data.get("tag_name", "")
    return Release(tag=tag, version=parse_version(tag), name=data.get("name") or tag, body=data.get("body") or "",
                   url=data.get("html_url") or RELEASES_PAGE, published=(data.get("published_at") or "")[:10],
                   assets=assets)


def is_newer(rel: Release) -> bool:
    """Versão maior que a instalada. Pre-release (tag com `-`, ex.: v0.2.0-beta.1) é ignorada."""
    if "-" in rel.tag:
        return False
    return rel.version > current_version()


def install_info() -> dict:
    """Como o app foi instalado: msi, zip ou source (código-fonte)."""
    if not getattr(sys, "frozen", False):
        return {"kind": "source"}
    exe_dir = Path(sys.executable).resolve().parent
    for cand in (exe_dir / MARKER, exe_dir / "_internal" / MARKER):
        try:
            data = json.loads(cand.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("kind"):
                return data
        except (OSError, ValueError):
            continue
    return {"kind": "zip"}


PATTERNS = {
    "msi": r"-windows-x64\.msi$",
    "zip": r"-windows-x64\.zip$",
}


def pick_asset(rel: Release, kind: str | None = None) -> tuple[str, str, int] | None:
    kind = kind or install_info()["kind"]
    pat = PATTERNS.get(kind)
    if not pat:
        return None
    for name, (url, size) in rel.assets.items():
        if re.search(pat, name):
            return name, url, size
    return None


def can_auto_install(kind: str | None = None) -> bool:
    kind = kind or install_info()["kind"]
    if sys.platform != "win32":
        return False  # Linux e macOS ainda desativados (#12)
    return kind in PATTERNS


def _get(url: str, dest: Path | None, progress: Callable[[int, int], None] | None, cancel: threading.Event | None,
         timeout: float = 60.0) -> bytes:
    accept = "application/octet-stream" if "api.github.com" in url else "*/*"
    req = urllib.request.Request(url, headers=_headers(accept))
    h = hashlib.sha256()
    buf = bytearray()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        fh = open(dest, "wb") if dest else None
        try:
            while True:
                if cancel is not None and cancel.is_set():
                    raise UpdateError("cancelled")
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                if fh:
                    fh.write(chunk)
                    h.update(chunk)
                else:
                    buf.extend(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
        finally:
            if fh:
                fh.close()
    return h.hexdigest().encode() if dest else bytes(buf)


def download(rel: Release, asset: tuple[str, str, int], progress: Callable[[int, int], None] | None = None,
             cancel: threading.Event | None = None) -> str:
    """Baixa o pacote e confere o SHA-256 com o SHA256SUMS.txt da release."""
    name, url, _size = asset
    sums = rel.assets.get(SUMS_NAME)
    if not sums:
        raise UpdateError("no-checksums")
    sums_txt = _get(sums[0], None, None, cancel).decode("utf-8", "replace")
    expected = None
    for line in sums_txt.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[-1].lstrip("*") == name:
            expected = parts[0].lower()
    if not expected:
        raise UpdateError("no-checksums")
    folder = Path(tempfile.mkdtemp(prefix="revelador_atualizacao_"))
    dest = folder / name
    digest = _get(url, dest, progress, cancel, timeout=120).decode()
    if digest.lower() != expected:
        dest.unlink(missing_ok=True)
        raise UpdateError("checksum-mismatch")
    return str(dest)


def _app_dir() -> Path:
    return Path(sys.executable).resolve().parent


def _ps(text: str) -> str:
    """Texto entre aspas simples do PowerShell (aspas simples dentro do caminho viram duas)."""
    return "'" + str(text).replace("'", "''") + "'"


def _caminho_seguro(nome: str) -> bool:
    """Entrada do zip que fica dentro da pasta de destino: nem absoluta (com barra inicial, unidade ou
    UNC, em qualquer separador) nem com `..`. `Path("/x").is_absolute()` é falso no Windows, por isso
    confere-se também a barra inicial."""
    if nome.startswith(("/", "\\")):
        return False
    if PurePosixPath(nome).is_absolute() or PureWindowsPath(nome).is_absolute():
        return False
    return ".." not in re.split(r"[\\/]", nome)


def spawn_powershell(script: Path) -> subprocess.Popen:
    """Roda um .ps1 num PowerShell que continua vivo depois que o app fecha.

    Não usar DETACHED_PROCESS: iniciado sem console por um app sem console (o executável do
    PyInstaller), o powershell.exe encerra antes de rodar o script, sem erro nenhum. Com
    CREATE_NO_WINDOW ele ganha um console próprio e invisível e sobrevive ao fim do app.
    """
    return subprocess.Popen(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", str(script)],
        creationflags=NO_WINDOW | NEW_PROCESS_GROUP, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, close_fds=True)


def install(package: str, kind: str | None = None) -> None:
    """Prepara a instalação para rodar quando o app fechar. O app deve sair logo em seguida."""
    kind = kind or install_info()["kind"]
    if sys.platform != "win32" or kind not in PATTERNS:
        raise UpdateError("unsupported")
    pid = os.getpid()
    exe = str(Path(sys.executable).resolve())
    work = Path(package).parent
    # O registro fica em atualizar.log (e instalar.log, do msiexec) na pasta do download.
    head = (f"Start-Transcript -Path {_ps(work / 'atualizar.log')} -Append | Out-Null\n"
            f"Wait-Process -Id {pid} -ErrorAction SilentlyContinue\n"
            f"Start-Sleep -Milliseconds 500\n")
    # Reabre o app direto (CreateProcess), sem passar pelo shell do Windows: com Start-Process
    # (ShellExecute), a primeira abertura do executável recém-instalado levava ~25 s e criava uma
    # segunda instância passageira do app.
    tail = ("$psi = New-Object System.Diagnostics.ProcessStartInfo\n"
            f"$psi.FileName = {_ps(exe)}\n"
            f"$psi.WorkingDirectory = {_ps(Path(exe).parent)}\n"
            "$psi.UseShellExecute = $false\n"
            "[void][System.Diagnostics.Process]::Start($psi)\n"
            "Stop-Transcript | Out-Null\n")
    if kind == "msi":
        msi_args = ", ".join(_ps(a) for a in ("/i", f'"{package}"', "/passive", "/norestart", "/l*v",
                                              f'"{work / "instalar.log"}"'))
        body = (head + f"$p = Start-Process msiexec.exe -ArgumentList @({msi_args}) -Wait -PassThru\n"
                "Write-Output \"msiexec terminou com o código $($p.ExitCode)\"\n" + tail)
    else:
        new_dir = work / "novo"
        with zipfile.ZipFile(package) as z:
            # Confere todas as entradas antes de extrair qualquer uma.
            if not all(_caminho_seguro(m) for m in z.namelist()):
                raise UpdateError("bad-archive")
            z.extractall(new_dir)
        src = next((p.parent for p in new_dir.rglob("Revelador.exe")), None)
        if src is None:
            raise UpdateError("bad-archive")
        body = (head + f"robocopy {_ps(src)} {_ps(_app_dir())} /MIR /R:3 /W:1 /NFL /NDL /NJH /NJS | Out-Null\n"
                "Write-Output \"robocopy terminou com o código $LASTEXITCODE\"\n" + tail)
    script = work / "atualizar.ps1"
    script.write_text(body, encoding="utf-8-sig")
    spawn_powershell(script)
