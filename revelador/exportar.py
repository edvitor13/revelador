"""Exportação para revelação (docs/ARQUITETURA.md, seção 8). Puro: sem Qt.

Fluxo
-----
1. ``conferir(trabalho, infos)``: avisos antes de exportar (resolução baixa, original que sumiu ou mudou, foto
   selecionada sem impressão).
2. ``planejar(trabalho, destino, modo_copias, ..., organizar=...)``: o ``Plano``, sem tocar no disco: pasta
   ``Revelação AAAA-MM-DD`` (nunca uma pasta que já existe: sufixo `` (2)``...), uma subpasta por tamanho (ou, com
   ``organizar="pasta"``, uma por pasta de tamanho, #32, e as impressões avulsas por tamanho) e um ``Item`` por
   impressão de foto selecionada, com os caminhos finais já sem colisão. O plano guarda CÓPIAS do modelo, então
   pode ser executado em outra thread enquanto a interface continua viva.
3. ``exportar_item(item, dpi)``: ``carregar_fonte(original)`` → ``renderizar`` nos px exatos do papel →
   ``para_uint8`` → JPEG baseline, qualidade 95, 4:4:4, perfil sRGB, dpi e EXIF mínimo (só a data original), gravado
   em ``.tmp`` na mesma pasta e trocado com ``os.replace``. O original nunca é aberto para escrita.
4. ``executar(plano, ...)``: roda tudo (``ThreadPoolExecutor``) e grava o ``pedido.txt``. A interface usa as mesmas
   peças com ``QThreadPool`` (``preparar`` + ``exportar_item`` + ``finalizar``).

Erros por item não derrubam a exportação: ficam em ``Resultado.erros``.
"""

from __future__ import annotations

import copy
import io
import os
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import numpy as np
from PIL import Image, ImageCms

from . import imagem, precos, receita, tamanhos
from . import __version__
from .i18n import _
from .imagem import ErroImagem, InfoFoto
from .projeto import Foto, Impressao, Trabalho, gravar_texto_seguro

MODO_PASTAS = "pastas"
MODO_NOME = "nome"
MODO_REPETIR = "repetir"
MODOS = (MODO_PASTAS, MODO_NOME, MODO_REPETIR)

ORGANIZAR_TAMANHO = "tamanho"   # uma subpasta por tamanho (padrão)
ORGANIZAR_PASTA = "pasta"       # uma subpasta por pasta de tamanho (#32); avulsas continuam por tamanho
ORGANIZACOES = (ORGANIZAR_TAMANHO, ORGANIZAR_PASTA)

QUALIDADE_JPEG = 95
MAX_PARALELO = 4
NOME_PEDIDO = "pedido.txt"
_PROIBIDOS = '<>:"/\\|?*'
_RESERVADOS = {"CON", "PRN", "AUX", "NUL", *(f"COM{n}" for n in range(1, 10)), *(f"LPT{n}" for n in range(1, 10))}
MAX_NOME_SUBPASTA = 80
_TAG_EXIF_IFD = 0x8769
_TAG_DATA_ORIGINAL = 0x9003


# ----------------------------------------------------------------------------------------------- modelos

@dataclass
class Item:
    """Uma impressão a gravar: renderiza uma vez e escreve em todos os ``destinos`` (mais de um no modo repetir)."""

    foto: Foto
    impressao: Impressao
    tamanho_id: str              # chave de preço (``precos.chave_preco``)
    tamanho_nome: str            # nome da subpasta ("10x15")
    copias: int
    destinos: list[Path]
    grupo: str = ""              # nome da subpasta de primeiro nível (o tamanho, ou a pasta de tamanho)
    pasta: str | None = None     # id da pasta de tamanho da impressão (None = avulsa)


@dataclass
class Plano:
    pasta: Path                  # a pasta da exportação (ainda não criada)
    itens: list[Item]
    modo_copias: str
    dpi: int
    data: date
    trabalho: Trabalho           # cópia, para o orçamento do pedido.txt
    tabela_precos: dict[str, int] = field(default_factory=dict)
    organizar: str = ORGANIZAR_TAMANHO

    @property
    def arquivos(self) -> int:
        return sum(len(i.destinos) for i in self.itens)

    @property
    def copias(self) -> int:
        return sum(i.copias for i in self.itens)

    @property
    def fotos(self) -> int:
        return len({i.foto.id for i in self.itens})

    def orcamento(self) -> precos.Orcamento:
        return precos.orcamento(self.trabalho, self.tabela_precos)


@dataclass
class Resultado:
    arquivos: list[Path] = field(default_factory=list)
    feitos: list[Item] = field(default_factory=list)
    erros: list[tuple[Item, str]] = field(default_factory=list)
    cancelado: bool = False
    pedido: Path | None = None

    @property
    def ok(self) -> bool:
        return not self.erros and not self.cancelado


@dataclass
class Aviso:
    tipo: str        # "baixa" | "sumiu" | "mudou" | "sem_impressao"
    foto_id: str
    texto: str


# ------------------------------------------------------------------------------------------------ nomes

def _limpo(nome: str) -> str:
    nome = "".join("_" if c in _PROIBIDOS or ord(c) < 32 else c for c in nome).strip().rstrip(".")
    return nome or "_"


def nome_tamanho(impressao: Impressao) -> str:
    """Nome legível do tamanho, usado como subpasta ("10x15", "A4 (21x29,7)", "Personalizado 100x150 mm")."""
    if impressao.tamanho == tamanhos.PERSONALIZADO:
        menor, maior = tamanhos.papel_mm(impressao.tamanho, impressao.papel_mm)
        return _limpo(_("Personalizado {menor}x{maior} mm").format(menor=f"{menor:g}", maior=f"{maior:g}"))
    return _limpo(_(tamanhos.obter(impressao.tamanho).nome))


def nome_subpasta(nome: str) -> str:
    """Nome de pasta válido no Windows: sem caracteres proibidos, sem ponto/espaço no fim, sem nome reservado
    (``CON``, ``COM1``...) e com no máximo ``MAX_NOME_SUBPASTA`` caracteres."""
    nome = _limpo(" ".join(str(nome).split())[:MAX_NOME_SUBPASTA])
    if nome.split(".")[0].strip().upper() in _RESERVADOS:
        nome = f"{nome}_"
    return nome


def texto_copias(n: int) -> str:
    return _("{n} cópia").format(n=n) if n == 1 else _("{n} cópias").format(n=n)


def nome_pasta(dia: date) -> str:
    return _("Revelação {data}").format(data=dia.isoformat())


def pasta_livre(destino: Path, nome: str) -> Path:
    """``destino/nome``; se já existir, ``nome (2)``, ``nome (3)``..."""
    candidata = destino / nome
    n = 2
    while candidata.exists():
        candidata = destino / f"{nome} ({n})"
        n += 1
    return candidata


class _Reserva:
    """Nomes já usados no plano (sem diferenciar maiúsculas: o Windows não diferencia)."""

    def __init__(self) -> None:
        self.usados: set[str] = set()

    def reservar(self, pasta: Path, nome: str, extensao: str = ".jpg") -> Path:
        n = 1
        while True:
            candidato = pasta / (f"{nome}{extensao}" if n == 1 else f"{nome} - {n}{extensao}")
            chave = str(candidato).lower()
            if chave not in self.usados:
                self.usados.add(chave)
                return candidato
            n += 1


def _grupos(trabalho: Trabalho, brutos: list[tuple[Foto, Impressao]], organizar: str) -> list[str]:
    """Nome da subpasta de primeiro nível de cada impressão (mesma ordem de ``brutos``).

    Por tamanho: ``nome_tamanho``. Por pasta: a pasta de tamanho da impressão vira uma subpasta com o nome dela
    (``nome_subpasta``), e a impressão avulsa (ou de pasta que não existe mais) fica na subpasta do tamanho. Os nomes
    são únicos sem diferenciar maiúsculas: as pastas de tamanho escolhem primeiro (na ordem de ``trabalho.pastas``),
    depois os tamanhos das avulsas; um nome repetido ganha `` (2)``, `` (3)``...
    """
    if organizar == ORGANIZAR_TAMANHO:
        return [nome_tamanho(imp) for _foto, imp in brutos]
    pastas = {p.id: p for p in trabalho.pastas}
    usadas = {imp.pasta for _foto, imp in brutos if imp.pasta in pastas}
    usados: set[str] = set()
    nomes: dict[tuple[str, str], str] = {}

    def reservar(chave: tuple[str, str], nome: str) -> None:
        candidato, n = nome, 2
        while candidato.casefold() in usados:
            candidato = f"{nome} ({n})"
            n += 1
        usados.add(candidato.casefold())
        nomes[chave] = candidato

    for p in trabalho.pastas:
        if p.id in usadas:
            reservar(("pasta", p.id), nome_subpasta(p.nome))
    chaves = [("pasta", imp.pasta) if imp.pasta in pastas else ("tamanho", nome_tamanho(imp)) for _foto, imp in brutos]
    for chave in dict.fromkeys(chaves):
        if chave not in nomes:
            reservar(chave, chave[1])
    return [nomes[c] for c in chaves]


def planejar(trabalho: Trabalho, destino: str | os.PathLike, modo_copias: str = MODO_PASTAS, dpi: int | None = None,
             tabela_precos: Mapping[str, int] | None = None, hoje: date | None = None,
             organizar: str = ORGANIZAR_TAMANHO) -> Plano:
    """O que será gravado, sem tocar no disco. Um item por impressão de foto selecionada (ordem do trabalho).

    ``organizar``: ``"tamanho"`` (uma subpasta por tamanho) ou ``"pasta"`` (uma por pasta de tamanho; as impressões
    avulsas continuam por tamanho). Dentro de cada subpasta, o mesmo esquema de cópias (``modo_copias``).
    """
    if modo_copias not in MODOS:
        raise ValueError(f"modo de cópias desconhecido: {modo_copias!r} (use {MODOS})")
    if organizar not in ORGANIZACOES:
        raise ValueError(f"organização desconhecida: {organizar!r} (use {ORGANIZACOES})")
    dia = hoje or date.today()
    dpi = int(dpi or trabalho.dpi)
    pasta = pasta_livre(Path(destino), nome_pasta(dia))
    congelado = copy.deepcopy(trabalho)

    brutos = [(foto, imp) for foto in congelado.selecionadas() for imp in foto.impressoes]
    grupos = _grupos(congelado, brutos, organizar)
    ids_pastas = {p.id for p in congelado.pastas}
    # modo "pastas": sem subpasta de quantidade nas subpastas em que todas as impressões são de 1 cópia
    so_uma: dict[str, bool] = {}
    for (_foto, imp), grupo in zip(brutos, grupos):
        so_uma[grupo] = so_uma.get(grupo, True) and imp.copias == 1

    reserva = _Reserva()
    itens: list[Item] = []
    for (foto, imp), grupo in zip(brutos, grupos):
        tam = nome_tamanho(imp)
        base = pasta / grupo
        copias = max(1, int(imp.copias))
        stem = _limpo(foto.caminho.stem)
        if modo_copias == MODO_PASTAS:
            if not so_uma[grupo]:
                base = base / texto_copias(copias)
            destinos = [reserva.reservar(base, stem)]
        elif modo_copias == MODO_NOME:
            destinos = [reserva.reservar(base, f"{stem} ({texto_copias(copias)})")]
        else:
            destinos = [reserva.reservar(base, stem) for _i in range(copias)]
        itens.append(Item(foto, imp, precos.chave_preco(imp), tam, copias, destinos, grupo,
                          imp.pasta if imp.pasta in ids_pastas else None))
    return Plano(pasta, itens, modo_copias, dpi, dia, congelado, dict(tabela_precos or {}), organizar)


# ------------------------------------------------------------------------------------------- conferência

def conferir(trabalho: Trabalho, infos: Mapping[str, InfoFoto] | None = None) -> list[Aviso]:
    """Avisos antes de exportar. ``infos`` (id da foto → InfoFoto) é o que a interface já leu; sem ela, não há
    aviso de resolução. O arquivo é conferido por ``stat`` (existe? mesmo tamanho?)."""
    infos = infos or {}
    avisos: list[Aviso] = []
    for foto in trabalho.fotos:
        if not foto.selecionada:
            continue
        nome = foto.caminho.name
        if not foto.impressoes:
            avisos.append(Aviso("sem_impressao", foto.id,
                                _("{nome}: selecionada, mas sem nenhuma impressão.").format(nome=nome)))
            continue
        try:
            st = foto.caminho.stat()
        except OSError:
            avisos.append(Aviso("sumiu", foto.id, _("{nome}: o arquivo original não foi encontrado.").format(nome=nome)))
            continue
        if foto.bytes and st.st_size != foto.bytes:
            avisos.append(Aviso("mudou", foto.id, _("{nome}: o arquivo original mudou desde que foi importado.")
                                .format(nome=nome)))
        info = infos.get(foto.id)
        if info is None:
            continue
        for imp in foto.impressoes:
            if imp.modo == receita.MODO_CABER:
                continue
            ret = receita.retangulo_da_impressao(imp, info.largura, info.altura)
            orient = receita.orientacao(imp, info.largura, info.altura)
            dpi = tamanhos.resolucao_efetiva(round(ret.w), imp.tamanho, orient, imp.papel_mm)
            if tamanhos.qualidade(dpi) == "baixa":
                avisos.append(Aviso("baixa", foto.id, _("{nome} em {tamanho}: resolução baixa ({dpi} dpi).")
                                    .format(nome=nome, tamanho=nome_tamanho(imp), dpi=round(dpi))))
    return avisos


# ------------------------------------------------------------------------------------------------ JPEG

_ICC_SRGB: bytes | None = None


def perfil_srgb() -> bytes:
    global _ICC_SRGB
    if _ICC_SRGB is None:
        _ICC_SRGB = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    return _ICC_SRGB


def _exif_minimo(foto: Foto) -> bytes:
    """Só a data original (sem GPS, sem orientação, sem miniatura); vazio se a foto não a tem."""
    try:
        data = imagem.abrir_info(foto.caminho).data
    except Exception:
        data = None
    if data is None:
        return b""
    exif = Image.Exif()
    exif.get_ifd(_TAG_EXIF_IFD)[_TAG_DATA_ORIGINAL] = data.strftime("%Y:%m:%d %H:%M:%S")
    return exif.tobytes()


def codificar_jpeg(rgb8: np.ndarray, dpi: int, exif: bytes = b"") -> bytes:
    """JPEG baseline, qualidade 95, 4:4:4, perfil sRGB e dpi gravado."""
    buf = io.BytesIO()
    extras = {"exif": exif} if exif else {}
    Image.fromarray(rgb8, "RGB").save(buf, "JPEG", quality=QUALIDADE_JPEG, subsampling=0, progressive=False,
                                      optimize=False, dpi=(dpi, dpi), icc_profile=perfil_srgb(), **extras)
    return buf.getvalue()


def _gravar_bytes(destino: Path, dados: bytes) -> Path:
    """``.tmp`` na mesma pasta + ``os.replace``; se o nome foi tomado nesse meio tempo, usa `` (2)``..."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    final, n = destino, 2
    while final.exists():
        final = destino.with_name(f"{destino.stem} ({n}){destino.suffix}")
        n += 1
    tmp = final.with_name(final.name + ".tmp")
    try:
        with open(tmp, "wb") as fh:
            fh.write(dados)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, final)
    finally:
        tmp.unlink(missing_ok=True)
    return final


def renderizar_item(item: Item, dpi: int = 300) -> np.ndarray:
    """``uint8`` H×W×3 nos px exatos do papel: o que vai para o JPEG (e o que o teste compara com a prévia)."""
    fonte = receita.carregar_fonte(item.foto.caminho, "original")
    altura, largura = fonte.shape[:2]
    destino_px = receita.tamanho_exportacao(item.impressao, largura, altura, dpi)
    return receita.para_uint8(receita.renderizar(fonte, item.impressao, item.foto.ajustes, destino_px))


def exportar_item(item: Item, dpi: int = 300, cancelado: Callable[[], bool] | None = None) -> list[Path]:
    """Gera o JPEG do item e grava em todos os destinos. Devolve os arquivos gravados (vazio se cancelado antes)."""
    if cancelado is not None and cancelado():
        return []
    rgb8 = renderizar_item(item, dpi)
    if cancelado is not None and cancelado():
        return []
    dados = codificar_jpeg(rgb8, dpi, _exif_minimo(item.foto))
    return [_gravar_bytes(d, dados) for d in item.destinos]


def mensagem_erro(item: Item, erro: Exception) -> str:
    nome = item.foto.caminho.name
    if isinstance(erro, ErroImagem):
        return str(erro)
    if isinstance(erro, FileNotFoundError):
        return _("{nome}: o arquivo original não foi encontrado.").format(nome=nome)
    return _("{nome}: não foi possível exportar ({erro}).").format(nome=nome, erro=erro)


# -------------------------------------------------------------------------------------------- pedido.txt

def texto_pedido(plano: Plano, resultado: Resultado | None = None) -> str:
    """O resumo para mostrar ou enviar ao laboratório."""
    orc = plano.orcamento()
    feitos = plano.itens if resultado is None else resultado.feitos
    linhas = [
        _("Pedido de revelação — Revelador {versao}").format(versao=__version__),
        _("Data: {data}").format(data=plano.data.strftime("%d/%m/%Y")),
        _("Resolução: {dpi} dpi (JPEG sRGB)").format(dpi=plano.dpi),
        "",
        _("Resumo por tamanho"),
    ]
    for ln in orc.linhas:
        txt = _("{nome}: {fotos} foto(s), {copias} cópia(s)").format(nome=ln.nome, fotos=ln.fotos, copias=ln.copias)
        if ln.unitario is not None:
            txt += " — " + _("{unit} por cópia, subtotal {sub}").format(unit=precos.formatar(ln.unitario),
                                                                        sub=precos.formatar(ln.subtotal or 0))
        else:
            txt += " — " + _("sem preço")
        linhas.append(txt)
    linhas += _linhas_pastas(plano, feitos)
    linhas.append("")
    if any(ln.unitario is not None for ln in orc.linhas):
        rotulo = _("Total estimado") if orc.completo else _("Total estimado PARCIAL (há tamanhos sem preço)")
        linhas.append(f"{rotulo}: {precos.formatar(orc.total)}")
        linhas.append(_("Valor apenas estimado: o laboratório pode cobrar diferente (descontos, entrega)."))
    else:
        linhas.append(_("Total estimado: sem preços cadastrados."))
    linhas += ["", _("Total: {fotos} foto(s), {copias} cópia(s), {arquivos} arquivo(s)").format(
        fotos=len({i.foto.id for i in feitos}), copias=sum(i.copias for i in feitos),
        arquivos=sum(len(i.destinos) for i in feitos))]
    if resultado is not None and resultado.erros:
        linhas.append(_("ATENÇÃO: {n} item(ns) não foram exportados:").format(n=len(resultado.erros)))
        linhas += [f"  - {msg}" for _item, msg in resultado.erros]
    linhas += ["", _("Arquivos")]
    for item in feitos:
        for d in item.destinos:
            rel = d.relative_to(plano.pasta).as_posix()
            linhas.append(f"{rel}  ({texto_copias(item.copias)})")
    return "\n".join(linhas) + "\n"


def _linhas_pastas(plano: Plano, feitos: list[Item]) -> list[str]:
    """Organizado por pasta: que subpasta é de que tamanho (o laboratório não adivinha pelo nome "Família")."""
    if plano.organizar != ORGANIZAR_PASTA:
        return []
    linhas: list[str] = []
    for p in plano.trabalho.pastas:
        dela = [i for i in feitos if i.pasta == p.id]
        if dela:
            linhas.append(_("{pasta}/ — {tamanho}: {fotos} foto(s), {copias} cópia(s)").format(
                pasta=dela[0].grupo, tamanho=dela[0].tamanho_nome, fotos=len({i.foto.id for i in dela}),
                copias=sum(i.copias for i in dela)))
    if not linhas:
        return []
    return ["", _("Pastas")] + linhas


# ------------------------------------------------------------------------------------------------ execução

def preparar(plano: Plano) -> None:
    """Cria a pasta da exportação (falha se já existir: nada é sobrescrito)."""
    plano.pasta.mkdir(parents=True, exist_ok=False)


def finalizar(plano: Plano, resultado: Resultado) -> Resultado:
    """Grava o ``pedido.txt`` (não, se foi cancelado: o pedido ficaria incompleto) e ordena o resultado."""
    ordem = {id(i): n for n, i in enumerate(plano.itens)}
    resultado.feitos.sort(key=lambda i: ordem[id(i)])
    resultado.erros.sort(key=lambda e: ordem[id(e[0])])
    if not resultado.cancelado:
        resultado.pedido = plano.pasta / NOME_PEDIDO
        gravar_texto_seguro(resultado.pedido, texto_pedido(plano, resultado))
    return resultado


def trabalhadores_padrao() -> int:
    return max(1, min(MAX_PARALELO, (os.cpu_count() or 2) - 1))


def executar(plano: Plano, ao_progresso: Callable[[int, int], None] | None = None,
             cancelado: Callable[[], bool] | None = None, trabalhadores: int | None = None) -> Resultado:
    """Exporta o plano inteiro (bloqueia). ``ao_progresso(feitos, total)`` roda em threads de trabalho."""
    preparar(plano)
    resultado = Resultado()
    total, contados = len(plano.itens), [0]

    def um(item: Item) -> None:
        try:
            gravados = exportar_item(item, plano.dpi, cancelado)
        except Exception as e:  # noqa: BLE001 - um item ruim não derruba os outros
            resultado.erros.append((item, mensagem_erro(item, e)))
        else:
            if gravados:
                resultado.feitos.append(item)
                resultado.arquivos.extend(gravados)
            else:
                resultado.cancelado = True
        contados[0] += 1
        if ao_progresso is not None:
            ao_progresso(contados[0], total)

    with ThreadPoolExecutor(max_workers=trabalhadores or trabalhadores_padrao()) as pool:
        list(pool.map(um, plano.itens))
    if cancelado is not None and cancelado():
        resultado.cancelado = True
    return finalizar(plano, resultado)
