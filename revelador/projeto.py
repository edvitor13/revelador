"""Modelo do trabalho: fotos, impressões (tamanho, cópias, recorte) e ajustes.

Dados puros, sem Qt e sem acesso a disco: o mesmo modelo serve à interface, à receita de imagem, à exportação, ao
orçamento e ao arquivo ``.revelador``. Contrato em ``docs/ARQUITETURA.md`` (seção 2; JSON na seção 9).

Regras: nomes de campos em português sem acento e **nunca renomeados** (são as chaves do ``.revelador``); campo novo
com padrão neutro; coordenadas normalizadas (0..1). A gravação e a leitura do ``.revelador`` chegam com a #9.
"""

from __future__ import annotations

import json
import math
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from revelador import __version__
from revelador.i18n import _

TAMANHO_PADRAO = "10x15"
DPI_PADRAO = 300
MARGEM_CORTE_MM_PADRAO = 2.0

ORIGENS_RECORTE = ("auto", "centro", "manual")
ORIENTACOES = ("auto", "retrato", "paisagem")
MODOS = ("preencher", "caber")


@dataclass
class Rosto:
    """Rosto detectado, em coordenadas normalizadas da imagem ORIENTADA (EXIF aplicado, sem giro de 90°)."""

    x: float
    y: float
    w: float
    h: float
    olhos: tuple[tuple[float, float], tuple[float, float]] | None = None
    confianca: float = 1.0


@dataclass
class Recorte:
    """Recorte de uma impressão. A proporção não fica aqui: vem do papel e da orientação da impressão."""

    cx: float = 0.5          # centro, normalizado à imagem orientada E girada (giro aplicado)
    cy: float = 0.5
    zoom: float = 1.0        # 1 = maior recorte possível na proporção do papel; 2 = metade da largura...
    angulo: float = 0.0      # endireitar, graus (-45..45), em torno do centro do recorte
    giro: int = 0            # giros de 90° no sentido horário (0..3), sem perda
    origem: str = "auto"     # "auto" (rostos) | "centro" (sem rosto) | "manual" (a pessoa mexeu)


@dataclass
class Impressao:
    """Uma foto num tamanho de papel, com a quantidade de cópias e o recorte próprio."""

    tamanho: str = TAMANHO_PADRAO   # id de tamanhos.TAMANHOS, ou "personalizado"
    copias: int = 1
    orientacao: str = "auto"        # "auto" (segue a foto) | "retrato" | "paisagem"
    modo: str = "preencher"         # "preencher" (corta na proporção) | "caber" (foto inteira com borda branca)
    recorte: Recorte = field(default_factory=Recorte)
    papel_mm: tuple[float, float] | None = None  # só no "personalizado": (lado menor, lado maior) em mm
    preco_centavos: int | None = None            # só no "personalizado": valor por cópia (seção 13)
    pasta: str | None = None        # id da Pasta de tamanho de onde veio (#32); None = impressão avulsa


@dataclass
class Pasta:
    """Pasta de tamanho (#32): grupo virtual do trabalho; a foto que entra ganha uma impressão no tamanho dela.

    Nada muda nas pastas do disco. O ``id`` nunca muda; a ordem de ``Trabalho.pastas`` é a da tela.
    """

    id: str
    nome: str
    cor: str                        # chave da paleta de pastas em ``ui/tema.py`` (não um hexadecimal)
    tamanho: str = TAMANHO_PADRAO   # id de tamanhos.TAMANHOS, ou "personalizado"
    copias: int = 1                 # cópias padrão das impressões novas da pasta
    papel_mm: tuple[float, float] | None = None  # só no "personalizado"
    preco_centavos: int | None = None            # só no "personalizado"


@dataclass
class Foto:
    """Uma foto importada. Os ajustes valem para todas as impressões dela; o recorte é de cada impressão."""

    id: str
    caminho: Path
    bytes: int = 0
    mtime: float = 0.0
    selecionada: bool = False
    ajustes: dict[str, float] = field(default_factory=dict)     # só as chaves fora do padrão
    rostos: list[Rosto] | None = None                           # None = ainda não detectado; [] = nenhum
    impressoes: list[Impressao] = field(default_factory=list)   # vazia até a foto ser selecionada


@dataclass
class Trabalho:
    """O conjunto de fotos de um pedido de revelação."""

    fotos: list[Foto] = field(default_factory=list)
    tamanho_padrao: str = TAMANHO_PADRAO
    dpi: int = DPI_PADRAO
    margem_corte_mm: float = MARGEM_CORTE_MM_PADRAO
    caminho: Path | None = None     # o .revelador, quando salvo
    pastas: list[Pasta] = field(default_factory=list)   # pastas de tamanho (#32), na ordem da tela

    def selecionadas(self) -> list[Foto]:
        return [f for f in self.fotos if f.selecionada]


# --------------------------------------------------------------------------------------------------------------------
# Arquivo .revelador (seção 9 da arquitetura)
# --------------------------------------------------------------------------------------------------------------------

FORMATO = 1
MIGRACOES: dict[int, Callable[[dict], dict]] = {}   # formato n -> passo puro que devolve o dict no formato n+1
DPI_MIN, DPI_MAX = 100, 600
COPIAS_MIN, COPIAS_MAX = 1, 999
TAMANHO_PERSONALIZADO = "personalizado"


class ErroFormato(Exception):
    """Arquivo .revelador ilegível ou de uma versão mais nova; a mensagem já é amigável."""


def _numero(v: object, padrao: float, minimo: float, maximo: float, nome: str, avisos: list[str]) -> float:
    """Converte para número finito e limita à faixa; avisa quando mudou algo."""
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        if v is not None:
            avisos.append(_("Valor inválido em “{nome}”; usei o padrão.").format(nome=nome))
        return padrao
    if v < minimo or v > maximo:
        avisos.append(_("Valor de “{nome}” fora da faixa; ajustei.").format(nome=nome))
        return min(max(float(v), minimo), maximo)
    return v


def _inteiro(v: object, padrao: int, minimo: int, maximo: int, nome: str, avisos: list[str]) -> int:
    return int(round(_numero(v, padrao, minimo, maximo, nome, avisos)))


def _escolha(v: object, validos: tuple[str, ...], padrao: str, nome: str, avisos: list[str]) -> str:
    if v is None:
        return padrao
    if v not in validos:
        avisos.append(_("Valor desconhecido em “{nome}”; usei o padrão.").format(nome=nome))
        return padrao
    return v  # type: ignore[return-value]


def _recorte_de(d: object, avisos: list[str]) -> Recorte:
    d = d if isinstance(d, dict) else {}
    return Recorte(
        cx=float(_numero(d.get("cx"), 0.5, 0.0, 1.0, "cx", avisos)),
        cy=float(_numero(d.get("cy"), 0.5, 0.0, 1.0, "cy", avisos)),
        zoom=float(_numero(d.get("zoom"), 1.0, 1.0, 20.0, "zoom", avisos)),
        angulo=float(_numero(d.get("angulo"), 0.0, -45.0, 45.0, "angulo", avisos)),
        giro=_inteiro(d.get("giro"), 0, 0, 3, "giro", avisos),
        origem=_escolha(d.get("origem"), ORIGENS_RECORTE, "auto", "origem", avisos),
    )


def _papel_de(v: object, avisos: list[str]) -> tuple[float, float] | None:
    if v is None:
        return None
    if (isinstance(v, (list, tuple)) and len(v) == 2
            and all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and x > 0 for x in v)):
        return (float(min(v)), float(max(v)))
    avisos.append(_("Medida do papel inválida; ignorei."))
    return None


def _impressao_de(d: object, padrao_tamanho: str, tamanhos_validos: set[str] | None, avisos: list[str]) -> Impressao:
    d = d if isinstance(d, dict) else {}
    tamanho = d.get("tamanho", padrao_tamanho)
    if not isinstance(tamanho, str) or (
            tamanhos_validos is not None and tamanho != TAMANHO_PERSONALIZADO and tamanho not in tamanhos_validos):
        avisos.append(_("Tamanho de revelação desconhecido; usei o padrão."))
        tamanho = padrao_tamanho
    preco = d.get("preco_centavos")
    if preco is not None and (isinstance(preco, bool) or not isinstance(preco, int) or preco < 0):
        avisos.append(_("Preço inválido; ignorei."))
        preco = None
    return Impressao(
        tamanho=tamanho,
        copias=_inteiro(d.get("copias"), 1, COPIAS_MIN, COPIAS_MAX, "copias", avisos),
        orientacao=_escolha(d.get("orientacao"), ORIENTACOES, "auto", "orientacao", avisos),
        modo=_escolha(d.get("modo"), MODOS, "preencher", "modo", avisos),
        recorte=_recorte_de(d.get("recorte"), avisos),
        papel_mm=_papel_de(d.get("papel_mm"), avisos),
        preco_centavos=preco,
    )


def _rosto_de(d: object) -> Rosto | None:
    if not isinstance(d, dict):
        return None
    try:
        x, y, w, h = (float(d[k]) for k in ("x", "y", "w", "h"))
        olhos = d.get("olhos")
        if olhos is not None:
            olhos = ((float(olhos[0][0]), float(olhos[0][1])), (float(olhos[1][0]), float(olhos[1][1])))
        conf = float(d.get("confianca", 1.0))
    except (KeyError, TypeError, ValueError, IndexError):
        return None
    if not all(math.isfinite(v) for v in (x, y, w, h, conf)):
        return None
    return Rosto(x, y, w, h, olhos, conf)


def _resolver(d: dict, base: Path | None) -> Path | None:
    """Relativo primeiro, depois o absoluto; sem exigir que exista (a interface oferece “Procurar…”)."""
    rel, absoluto = d.get("caminho"), d.get("caminho_absoluto")
    candidatos: list[Path] = []
    if isinstance(rel, str) and rel:
        candidatos.append(Path(base) / Path(*rel.split("/")) if base is not None else Path(rel))
    if isinstance(absoluto, str) and absoluto:
        candidatos.append(Path(absoluto))
    for c in candidatos:
        if c.exists():
            return c
    return candidatos[0] if candidatos else None


def _ajustes_de(v: object, limitar: Callable[[dict], dict] | None, avisos: list[str]) -> dict[str, float]:
    if not isinstance(v, dict):
        return {}
    limpo = {str(k): float(x) for k, x in v.items()
             if isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)}
    if len(limpo) != len(v):
        avisos.append(_("Ajustes inválidos foram ignorados."))
    return limitar(limpo) if limitar else limpo


def de_dict(dados: object, base: Path | None, tamanhos_validos: set[str] | list[str] | None = None,
            limitar_ajustes: Callable[[dict], dict] | None = None) -> tuple[Trabalho, list[str]]:
    """Valida e converte o dict lido do JSON em Trabalho, migrando formatos antigos. Devolve (trabalho, avisos)."""
    if not isinstance(dados, dict) or dados.get("app") != "Revelador":
        raise ErroFormato(_("Este arquivo não parece ser um trabalho do Revelador."))
    formato = dados.get("formato")
    if isinstance(formato, bool) or not isinstance(formato, int) or formato < 1:
        raise ErroFormato(_("Este arquivo não parece ser um trabalho do Revelador."))
    if formato > FORMATO:
        raise ErroFormato(_("Este trabalho foi feito por uma versão mais nova do Revelador. "
                            "Atualize o app para abri-lo."))
    while formato < FORMATO:
        dados = MIGRACOES[formato](dados)
        formato += 1
    avisos: list[str] = []
    validos = set(tamanhos_validos) if tamanhos_validos is not None else None
    pad = dados.get("padrao") if isinstance(dados.get("padrao"), dict) else {}
    tam_pad = pad.get("tamanho", TAMANHO_PADRAO)
    if not isinstance(tam_pad, str) or (validos is not None and tam_pad not in validos):
        avisos.append(_("Tamanho de revelação desconhecido; usei o padrão."))
        tam_pad = TAMANHO_PADRAO
    trabalho = Trabalho(
        tamanho_padrao=tam_pad,
        dpi=_inteiro(pad.get("dpi"), DPI_PADRAO, DPI_MIN, DPI_MAX, "dpi", avisos),
        margem_corte_mm=float(_numero(pad.get("margem_corte_mm"), MARGEM_CORTE_MM_PADRAO, 0.0, 20.0,
                                      "margem_corte_mm", avisos)),
    )
    fotos = dados.get("fotos")
    for i, fd in enumerate(fotos if isinstance(fotos, list) else []):
        if not isinstance(fd, dict):
            continue
        caminho = _resolver(fd, base)
        if caminho is None:
            avisos.append(_("Uma foto sem caminho foi ignorada."))
            continue
        rostos = fd.get("rostos")
        rostos = [r for r in map(_rosto_de, rostos) if r is not None] if isinstance(rostos, list) else None
        imps = fd.get("impressoes")
        nb, mt = fd.get("bytes"), fd.get("mtime")
        trabalho.fotos.append(Foto(
            id=str(fd.get("id") or f"f{i + 1}"),
            caminho=caminho,
            bytes=nb if isinstance(nb, int) and not isinstance(nb, bool) and nb >= 0 else 0,
            mtime=float(mt) if isinstance(mt, (int, float)) and not isinstance(mt, bool) and math.isfinite(mt) else 0.0,
            selecionada=fd.get("selecionada") is True,
            ajustes=_ajustes_de(fd.get("ajustes"), limitar_ajustes, avisos),
            rostos=rostos,
            impressoes=[_impressao_de(x, tam_pad, validos, avisos) for x in imps] if isinstance(imps, list) else [],
        ))
    return trabalho, list(dict.fromkeys(avisos))


def _rosto_para_dict(r: Rosto) -> dict:
    d: dict = {"x": r.x, "y": r.y, "w": r.w, "h": r.h}
    if r.olhos is not None:
        d["olhos"] = [list(r.olhos[0]), list(r.olhos[1])]
    d["confianca"] = r.confianca
    return d


def _impressao_para_dict(i: Impressao) -> dict:
    d: dict = {"tamanho": i.tamanho}
    if i.copias != 1:
        d["copias"] = i.copias
    if i.orientacao != "auto":
        d["orientacao"] = i.orientacao
    if i.modo != "preencher":
        d["modo"] = i.modo
    padrao = Recorte()
    r = {k: getattr(i.recorte, k) for k in ("cx", "cy", "zoom", "angulo", "giro", "origem")
         if getattr(i.recorte, k) != getattr(padrao, k)}
    if r:
        d["recorte"] = r
    if i.papel_mm is not None:
        d["papel_mm"] = list(i.papel_mm)
    if i.preco_centavos is not None:
        d["preco_centavos"] = i.preco_centavos
    return d


def _relativo(caminho: Path, base: Path | None) -> str | None:
    if base is None:
        return None
    try:
        return Path(os.path.relpath(caminho, base)).as_posix()
    except ValueError:   # outro disco
        return None


def para_dict(trabalho: Trabalho, base: Path | None) -> dict:
    """Dict do formato da seção 9, só com os campos fora do padrão. ``caminho`` é relativo a ``base`` quando dá."""
    fotos = []
    for f in trabalho.fotos:
        rel = _relativo(f.caminho, base)
        d: dict = {"id": f.id, "caminho": rel if rel is not None else str(f.caminho),
                   "caminho_absoluto": str(f.caminho), "bytes": f.bytes, "mtime": f.mtime}
        if f.selecionada:
            d["selecionada"] = True
        if f.ajustes:
            d["ajustes"] = dict(f.ajustes)
        if f.rostos is not None:
            d["rostos"] = [_rosto_para_dict(r) for r in f.rostos]
        if f.impressoes:
            d["impressoes"] = [_impressao_para_dict(i) for i in f.impressoes]
        fotos.append(d)
    return {
        "app": "Revelador",
        "formato": FORMATO,
        "versao_app": __version__,
        "padrao": {"tamanho": trabalho.tamanho_padrao, "dpi": trabalho.dpi,
                   "margem_corte_mm": trabalho.margem_corte_mm},
        "fotos": fotos,
    }


def gravar_texto_seguro(caminho: Path, texto: str) -> None:
    """Grava em ``.tmp`` na mesma pasta e troca com ``os.replace``; nunca deixa o arquivo pela metade."""
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tmp = caminho.with_name(caminho.name + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(texto)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, caminho)
    finally:
        tmp.unlink(missing_ok=True)


def _texto(trabalho: Trabalho, base: Path | None) -> str:
    return json.dumps(para_dict(trabalho, base), ensure_ascii=False, indent=2) + "\n"


def salvar(trabalho: Trabalho, caminho: Path) -> None:
    """Grava o trabalho em ``caminho`` (gravação segura) e atualiza ``trabalho.caminho``."""
    caminho = Path(caminho).absolute()
    gravar_texto_seguro(caminho, _texto(trabalho, caminho.parent))
    trabalho.caminho = caminho


def abrir(caminho: Path, tamanhos_validos: set[str] | list[str] | None = None,
          limitar_ajustes: Callable[[dict], dict] | None = None) -> tuple[Trabalho, list[str]]:
    """Lê um ``.revelador``. JSON inválido ou versão mais nova levantam ``ErroFormato``."""
    caminho = Path(caminho).absolute()
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8-sig"))
    except (ValueError, UnicodeDecodeError) as e:
        raise ErroFormato(_("Não consegui ler este arquivo: ele está danificado.")) from e
    trabalho, avisos = de_dict(dados, caminho.parent, tamanhos_validos, limitar_ajustes)
    trabalho.caminho = caminho
    return trabalho, avisos


def pasta_recuperacao() -> Path:
    """``%LOCALAPPDATA%/Revelador/recuperacao``."""
    raiz = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(raiz) / "Revelador" / "recuperacao"


def salvar_recuperacao(trabalho: Trabalho) -> Path:
    """Autossalvamento: grava uma cópia na pasta de recuperação (caminhos absolutos) e devolve o arquivo."""
    nome = trabalho.caminho.stem if trabalho.caminho else "sem-nome"
    destino = pasta_recuperacao() / f"{nome}.revelador"
    gravar_texto_seguro(destino, _texto(trabalho, None))
    return destino


def listar_recuperacao() -> list[Path]:
    """Arquivos de recuperação, o mais recente primeiro."""
    pasta = pasta_recuperacao()
    if not pasta.is_dir():
        return []
    return sorted(pasta.glob("*.revelador"), key=lambda p: p.stat().st_mtime, reverse=True)


def apagar_recuperacao(caminho: Path) -> None:
    """Apaga um arquivo de recuperação (só dentro da pasta de recuperação)."""
    caminho = Path(caminho)
    if caminho.parent.resolve() == pasta_recuperacao().resolve():
        caminho.unlink(missing_ok=True)
