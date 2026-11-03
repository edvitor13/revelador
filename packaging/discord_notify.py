"""Avisos do CI no Discord (release publicada, build quebrado, mensagem de teste).

Uso (no GitHub Actions):
    python packaging/discord_notify.py release --tag v0.1.0 --assets-dir pacotes [--notes ARQ.md]
    python packaging/discord_notify.py falha
    python packaging/discord_notify.py teste

O endereço do webhook vem SÓ da variável de ambiente ``DISCORD_WEBHOOK`` (segredo do repositório)
e nunca é impresso. Sem a variável, o script avisa e sai com código 0 (forks, PRs, builds locais).
``--dry-run`` mostra o JSON que seria enviado, sem enviar nada.

O resto do contexto sai das variáveis padrão do Actions: ``GITHUB_REPOSITORY``,
``GITHUB_SERVER_URL``, ``GITHUB_RUN_ID``, ``GITHUB_REF_NAME``, ``GITHUB_SHA``, ``GITHUB_ACTOR``,
``GITHUB_WORKFLOW`` e ``GITHUB_EVENT_PATH``.

Só biblioteca padrão.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

APP = "Revelador"
AMBAR = 0xF0A63A
VERMELHO = 0xE5484D
LIMITE_RESUMO = 1500  # caracteres do resumo das novidades (o Discord aceita até 4096)
LINHAS_RESUMO = 10


# --------------------------------------------------------------------------- contexto do GitHub
def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, "").strip() or default


def repo() -> str:
    return _env("GITHUB_REPOSITORY", "edvitor13/revelador")


def repo_url() -> str:
    return f"{_env('GITHUB_SERVER_URL', 'https://github.com')}/{repo()}"


def run_url() -> str:
    run_id = _env("GITHUB_RUN_ID")
    return f"{repo_url()}/actions/runs/{run_id}" if run_id else f"{repo_url()}/actions"


def logo_url(ref: str | None = None) -> str:
    # Enquanto o repositório for privado, o Discord não consegue baixar a imagem (fica sem miniatura).
    ref = ref or _env("GITHUB_SHA", "main")
    return f"https://raw.githubusercontent.com/{repo()}/{ref}/assets/logo-256.png"


def head_commit() -> dict:
    """Commit do evento ``push`` (mensagem, autor), se houver."""
    path = _env("GITHUB_EVENT_PATH")
    if not path or not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f).get("head_commit") or {}
    except (OSError, ValueError):
        return {}


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- resumo das novidades
def resumo_novidades(texto: str, limite: int = LIMITE_RESUMO, linhas: int = LINHAS_RESUMO) -> str:
    """Primeiras linhas do arquivo de novidades, em markdown que o Discord entende.

    Tira o título principal (``# ...``), comentários HTML e imagens; subtítulos viram negrito.
    Uma linha divisória (``---``) marca o fim do resumo.
    """
    texto = re.sub(r"<!--.*?-->", "", texto, flags=re.DOTALL)
    out: list[str] = []
    total = 0
    cortado = False
    for raw in texto.splitlines():
        line = raw.rstrip()
        if not out and (not line.strip() or re.match(r"^#\s", line)):
            continue  # título principal e linhas vazias do começo
        if out and re.fullmatch(r"\s*([-*_])(\s*\1){2,}\s*", line):
            break  # divisória: o resto é detalhe (downloads, notas técnicas)
        line = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", line)  # imagens não aparecem no Discord
        m = re.match(r"^#{2,6}\s+(.*)$", line)
        if m:
            line = f"**{m.group(1).strip()}**"
        if not line.strip():
            if out and out[-1] != "":
                out.append("")
            continue
        if len([x for x in out if x]) >= linhas or total + len(line) > limite:
            cortado = True
            break
        out.append(line)
        total += len(line) + 1
    while out and out[-1] == "":
        out.pop()
    resumo = "\n".join(out)
    if cortado:
        resumo += "\n…"
    return resumo


# --------------------------------------------------------------------------- pacotes da release
GRUPOS = [
    # (campo, sufixo, rótulo) — só Windows por enquanto; o Linux entra aqui junto com os pacotes dele.
    ("Windows", ".msi", "Instalador (.msi)"),
    ("Windows", ".zip", "Portátil (.zip)"),
]


def campos_pacotes(nomes: list[str], tag: str) -> list[dict]:
    base = f"{repo_url()}/releases/download/{tag}"
    campos: dict[str, list[str]] = {}
    for campo, sufixo, rotulo in GRUPOS:
        for nome in sorted(nomes):
            if nome.endswith(sufixo):
                campos.setdefault(campo, []).append(f"[{rotulo}]({base}/{nome})")
    out = [{"name": k, "value": "\n".join(v), "inline": True} for k, v in campos.items()]
    if "SHA256SUMS.txt" in nomes:
        out.append({"name": "Conferência", "value": f"[SHA256SUMS.txt]({base}/SHA256SUMS.txt)", "inline": True})
    return out


# --------------------------------------------------------------------------- mensagens
def msg_release(tag: str, notes: Path | None, assets_dir: Path | None) -> dict:
    versao = tag[1:] if tag.startswith("v") else tag
    pagina = f"{repo_url()}/releases/tag/{tag}"
    partes = []
    if notes and notes.is_file():
        resumo = resumo_novidades(notes.read_text(encoding="utf-8"))
        if resumo:
            partes.append(resumo)
    partes.append(f"[Ver todas as novidades e downloads]({pagina})")
    nomes = sorted(p.name for p in assets_dir.iterdir() if p.is_file()) if assets_dir and assets_dir.is_dir() else []
    embed = {
        "title": f"{APP} {versao} está disponível",
        "url": pagina,
        "description": "\n\n".join(partes)[:4000],
        "color": AMBAR,
        "thumbnail": {"url": logo_url(tag)},
        "fields": campos_pacotes(nomes, tag),
        "footer": {"text": repo()},
        "timestamp": now_iso(),
    }
    return {"username": APP, "embeds": [embed], "allowed_mentions": {"parse": []}}


def msg_falha() -> dict:
    ref = _env("GITHUB_REF_NAME", "?")
    sha = _env("GITHUB_SHA")[:7] or "?"
    commit = head_commit()
    titulo_commit = (commit.get("message") or "").strip().splitlines()[0:1]
    autor = (commit.get("author") or {}).get("name") or _env("GITHUB_ACTOR")
    linhas = [f"O workflow **{_env('GITHUB_WORKFLOW', 'Build')}** falhou em `{ref}` (commit `{sha}`)."]
    if titulo_commit:
        linhas.append(f"> {titulo_commit[0][:200]}")
    if autor:
        linhas.append(f"Autor: {autor}")
    linhas.append(f"[Abrir a execução no GitHub Actions]({run_url()})")
    embed = {
        "title": f"Build do {APP} falhou",
        "url": run_url(),
        "description": "\n".join(linhas),
        "color": VERMELHO,
        "footer": {"text": repo()},
        "timestamp": now_iso(),
    }
    return {"username": APP, "embeds": [embed], "allowed_mentions": {"parse": []}}


def msg_teste() -> dict:
    embed = {
        "title": "Teste de notificação",
        "url": run_url(),
        "description": (
            f"Se esta mensagem chegou, o webhook do Discord do **{APP}** está funcionando.\n"
            f"Branch: `{_env('GITHUB_REF_NAME', '?')}` · [execução]({run_url()})"
        ),
        "color": AMBAR,
        "thumbnail": {"url": logo_url()},
        "footer": {"text": repo()},
        "timestamp": now_iso(),
    }
    return {"username": APP, "embeds": [embed], "allowed_mentions": {"parse": []}}


# --------------------------------------------------------------------------- envio
def enviar(payload: dict, webhook: str) -> int:
    if not re.match(r"^https://(discord\.com|discordapp\.com|canary\.discord\.com|ptb\.discord\.com)/api/webhooks/",
                    webhook):
        print("DISCORD_WEBHOOK não parece ser um webhook do Discord; nada enviado.", file=sys.stderr)
        return 1
    url = webhook + ("&" if "?" in webhook else "?") + "wait=true"
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    for tentativa in range(3):
        req = urllib.request.Request(url, data=data, method="POST", headers={
            "Content-Type": "application/json; charset=utf-8",
            # O Discord recusa o User-Agent padrão do urllib em alguns casos.
            "User-Agent": f"{APP}-CI (https://github.com/{repo()}, 1.0)",
        })
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                print(f"Mensagem enviada ao Discord (HTTP {resp.status}).")
                return 0
        except urllib.error.HTTPError as e:  # str(e) não inclui o endereço do webhook
            corpo = e.read().decode("utf-8", "replace")[:300]
            if e.code == 429 and tentativa < 2:
                try:
                    espera = float(json.loads(corpo).get("retry_after", 2))
                except ValueError:
                    espera = 2.0
                time.sleep(min(espera, 30) + 0.5)
                continue
            print(f"O Discord recusou a mensagem: HTTP {e.code} {corpo}", file=sys.stderr)
            return 1
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if tentativa < 2:
                time.sleep(3)
                continue
            print(f"Falha de rede ao falar com o Discord: {type(e).__name__}", file=sys.stderr)
            return 1
    return 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Avisos do CI do Revelador no Discord.")
    ap.add_argument("--dry-run", action="store_true", help="só mostra o JSON, sem enviar")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("release", help="release publicada")
    r.add_argument("--tag", required=True)
    r.add_argument("--notes", type=Path, help="arquivo de novidades (markdown)")
    r.add_argument("--assets-dir", type=Path, help="pasta com os pacotes publicados")
    sub.add_parser("falha", help="build quebrado")
    sub.add_parser("teste", help="mensagem de teste")
    args = ap.parse_args(argv)

    if args.cmd == "release":
        payload = msg_release(args.tag, args.notes, args.assets_dir)
    elif args.cmd == "falha":
        payload = msg_falha()
    else:
        payload = msg_teste()

    if args.dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    webhook = os.environ.get("DISCORD_WEBHOOK", "").strip()
    if not webhook:
        print("DISCORD_WEBHOOK não definido; nenhuma mensagem enviada.")
        return 0
    return enviar(payload, webhook)


if __name__ == "__main__":
    sys.exit(main())
