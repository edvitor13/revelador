"""Tela de boas-vindas (#35): começar, trabalhos recentes, recuperação, novidades da versão e atualizações.

**Forma**: uma página (``PaginaBoasVindas``) que toma o lugar das três áreas (grade, editor e painel) logo abaixo da
barra superior e das faixas de aviso; a barra continua valendo (Importar, Projeto, engrenagem...). Some sozinha
quando a lista de fotos muda (trabalho novo, aberto ou restaurado, fotos importadas ou soltas na janela), pelo
"Fechar" e pelo Esc. Enquanto aparece, a página tem a mesma largura mínima das três áreas (a janela não pula ao
fechá-la) e se reorganiza em uma coluna quando falta largura.

**Quando aparece**: ``BoasVindas.ao_abrir()`` (chamado por ``app.main`` depois de tratar a linha de comando) mostra a
tela se não veio foto, pasta nem trabalho na linha de comando e a preferência ``boas_vindas/mostrar_ao_abrir``
(padrão ligada; a chave "Mostrar ao abrir" fica na própria tela) estiver ligada. Também abre as **novidades**
(``DialogoNovidades``, não modal) uma vez depois de cada atualização: ``boas_vindas/versao_vista`` guarda a última
versão vista; na primeira execução só grava a versão (quem acabou de instalar vê o resumo na própria tela). A
engrenagem → "Tela de boas-vindas" (``acao_boas_vindas``) abre a tela a qualquer momento.

**Recentes**: ``projeto_ui.recentes()`` (os que não existem mais já somem dali). O resumo de cada ``.revelador``
(nome, data, fotos, selecionadas, tamanhos e até quatro miniaturas do cache de ``miniaturas.py``) é lido num
``QThreadPool`` e chega por sinal; um clique abre (``projeto_ui.abrir``) e o "×" tira da lista (nunca do disco).

**Recuperação**: o trabalho recuperável (``projeto_ui.oferecer_recuperacao()``) vira um cartão em destaque com
"Recuperar" e "Descartar". Para não aparecer duas vezes, a faixa "recuperacao" da janela sai enquanto a tela está
aberta e volta ao fechá-la, se a cópia ainda existir.

**Atualizações**: usa o ``Verificador`` da janela (sinal ``verificado``). Na abertura do app, se a verificação do dia
vai rodar, espera o resultado dela; senão faz uma consulta silenciosa (``consultar_silencioso``), só com a busca
automática ligada. Com ``REVELADOR_SEM_REDE`` mostra só a versão atual, sem consultar.
"""

from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QDate, QLocale, QObject, QRectF, QRunnable, QSize, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QKeySequence, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QAbstractButton, QBoxLayout, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QPushButton, QScrollArea, QSizePolicy, QTextBrowser, QToolButton, QVBoxLayout,
                               QWidget)

from .. import APP_NAME, __date__, __version__, miniaturas, projeto, tamanhos, updater
from ..i18n import _
from ..projeto import ErroFormato
from . import icones, prefs, tema
from .componentes import Card, ToggleSwitch

log = logging.getLogger(__name__)

CHAVE_MOSTRAR = "boas_vindas/mostrar_ao_abrir"   # bool, padrão ligada
CHAVE_VERSAO_VISTA = "boas_vindas/versao_vista"   # última versão cujas novidades a pessoa já teve a chance de ver

MAX_MINIATURAS = 4
MAX_TENTATIVAS_MINIATURA = 8     # fotos que não abrem não seguram o resumo
LADO_MINIATURA = 320             # o mesmo lado da grade: reaproveita o cache
LADO_IMAGEM_ITEM = 128           # a miniatura já reduzida que vai para a tela
LARGURA_MAXIMA = 1180            # a coluna de conteúdo não passa disso (janela muito larga)
LARGURA_UMA_COLUNA = 820         # abaixo disso, recentes e cartões ficam um embaixo do outro
LARGURA_LATERAL = 360            # coluna dos cartões (como funciona, novidades) em duas colunas


# --------------------------------------------------------------------------------------------------------------------
# Funções puras (e preferências)
# --------------------------------------------------------------------------------------------------------------------
def pasta_novidades() -> Path:
    """``revelador/novidades`` (no executável: ``_internal/revelador/novidades``, incluída pelo ``Revelador.spec``)."""
    return Path(__file__).resolve().parents[1] / "novidades"


def arquivo_novidades(versao: str = __version__) -> Path:
    """O mesmo arquivo que o CI usa nas notas da release: ``release_v{versao}.md``."""
    return pasta_novidades() / f"release_v{versao}.md"


def texto_novidades(versao: str = __version__) -> str:
    """Texto (markdown) das novidades da versão, ou "" se o arquivo não existir."""
    try:
        return arquivo_novidades(versao).read_text(encoding="utf-8-sig")
    except OSError:
        return ""


def _sem_titulo(texto: str) -> list[str]:
    texto = re.sub(r"<!--.*?-->", "", texto, flags=re.DOTALL)
    linhas = texto.splitlines()
    while linhas and (not linhas[0].strip() or re.match(r"^#\s", linhas[0])):
        linhas.pop(0)   # o título principal ("# Revelador X.Y.Z") e as linhas vazias do começo
    return linhas


def corpo_novidades(texto: str) -> str:
    """O texto inteiro sem o título principal (o diálogo já tem o seu)."""
    return "\n".join(_sem_titulo(texto)).strip()


def resumo_novidades(texto: str) -> str:
    """As linhas antes da primeira divisória (``---``), sem o título principal: o resumo, como no aviso do CI.

    Subtítulos (``## ...``) viram negrito: o resumo vai num cartão pequeno."""
    saida: list[str] = []
    for linha in _sem_titulo(texto):
        if re.fullmatch(r"\s*([-*_])(\s*\1){2,}\s*", linha):
            break
        m = re.match(r"^#{1,6}\s+(.*)$", linha)
        saida.append(f"**{m.group(1).strip()}**" if m else linha.rstrip())
    return "\n".join(saida).strip()


def data_longa(iso: str) -> str:
    """``2026-11-03`` → "3 de novembro de 2026"."""
    d = QDate.fromString(iso[:10], "yyyy-MM-dd")
    if not d.isValid():
        return iso
    return QLocale(QLocale.Language.Portuguese, QLocale.Country.Brazil).toString(d, "d 'de' MMMM 'de' yyyy")


def data_curta(instante: float) -> str:
    return time.strftime("%d/%m/%Y %H:%M", time.localtime(instante)) if instante else ""


def mostrar_ao_abrir() -> bool:
    return bool(prefs.settings().value(CHAVE_MOSTRAR, True, bool))


def definir_mostrar_ao_abrir(sim: bool) -> None:
    s = prefs.settings()
    s.setValue(CHAVE_MOSTRAR, bool(sim))
    s.sync()


def novidades_pendentes(versao: str = __version__) -> bool:
    """True depois de uma atualização: já havia uma versão vista, e é outra. Na primeira execução, False."""
    vista = str(prefs.settings().value(CHAVE_VERSAO_VISTA, "", str) or "")
    return vista not in ("", versao)


def marcar_versao_vista(versao: str = __version__) -> None:
    s = prefs.settings()
    s.setValue(CHAVE_VERSAO_VISTA, versao)
    s.sync()


def nomes_tamanhos(ids: set[str] | list[str]) -> list[str]:
    """Nomes dos tamanhos, na ordem da tabela; o personalizado vai por último."""
    ids = set(ids)
    nomes = [_(t.nome) for t in tamanhos.TAMANHOS if t.id in ids]
    if tamanhos.PERSONALIZADO in ids:
        nomes.append(_("Personalizado"))
    return nomes


@dataclass
class ResumoTrabalho:
    """O que a lista de recentes mostra de um ``.revelador``."""

    caminho: Path
    nome: str
    salvo_em: float = 0.0                    # mtime do arquivo
    fotos: int = 0
    selecionadas: int = 0
    tamanhos: list[str] = field(default_factory=list)       # nomes, dos tamanhos das fotos selecionadas
    miniaturas: list[Path] = field(default_factory=list)    # JPEGs do cache (selecionadas primeiro)
    erro: str = ""


def resumir_trabalho(caminho: Path | str, max_miniaturas: int = MAX_MINIATURAS,
                     obter_miniatura=miniaturas.obter) -> ResumoTrabalho:
    """Lê um ``.revelador`` e resume (sem Qt; roda numa thread). As miniaturas vêm do cache (geradas se faltarem)."""
    caminho = Path(caminho)
    resumo = ResumoTrabalho(caminho=caminho, nome=caminho.stem)
    try:
        resumo.salvo_em = caminho.stat().st_mtime
        trabalho, _avisos = projeto.abrir(caminho)
    except ErroFormato as e:
        resumo.erro = str(e)
        return resumo
    except OSError:
        resumo.erro = _("Não consegui ler este arquivo.")
        return resumo
    selecionadas = [f for f in trabalho.fotos if f.selecionada]
    resumo.fotos = len(trabalho.fotos)
    resumo.selecionadas = len(selecionadas)
    resumo.tamanhos = nomes_tamanhos({i.tamanho for f in selecionadas for i in f.impressoes})
    tentativas = 0
    for foto in selecionadas + [f for f in trabalho.fotos if not f.selecionada]:
        if len(resumo.miniaturas) >= max_miniaturas or tentativas >= MAX_TENTATIVAS_MINIATURA:
            break
        arquivo = Path(os.path.normpath(foto.caminho))
        if not arquivo.is_file():
            continue
        tentativas += 1
        try:
            resumo.miniaturas.append(Path(obter_miniatura(arquivo, LADO_MINIATURA)))
        except Exception:  # noqa: BLE001 - uma foto que não abre só fica sem miniatura
            log.debug("sem miniatura para %s", arquivo.name, exc_info=True)
    return resumo


def texto_conteudo(resumo: ResumoTrabalho) -> str:
    """Linha do conteúdo: "12 fotos · 4 selecionadas · 10x15, 13x18"."""
    partes = [_("1 foto") if resumo.fotos == 1 else _("{n} fotos").format(n=resumo.fotos)]
    if resumo.selecionadas:
        partes.append(_("1 selecionada") if resumo.selecionadas == 1 else
                      _("{n} selecionadas").format(n=resumo.selecionadas))
    else:
        partes.append(_("nenhuma selecionada"))
    if resumo.tamanhos:
        partes.append(", ".join(resumo.tamanhos))
    return " · ".join(partes)


# --------------------------------------------------------------------------------------------------------------------
# Leitura dos recentes em segundo plano
# --------------------------------------------------------------------------------------------------------------------
class _Sinais(QObject):
    pronto = Signal(int, str, object)   # geração, caminho, (ResumoTrabalho, list[QImage])


class _TarefaResumo(QRunnable):
    def __init__(self, geracao: int, caminho: Path, sinais: _Sinais) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self.geracao, self.caminho, self.sinais = geracao, caminho, sinais

    def run(self) -> None:
        try:
            resumo = resumir_trabalho(self.caminho)
        except Exception:  # noqa: BLE001 - um trabalho ruim nunca derruba a tela
            log.exception("falha ao resumir %s", self.caminho.name)
            resumo = ResumoTrabalho(self.caminho, self.caminho.stem, erro=_("Não consegui ler este arquivo."))
        imagens: list[QImage] = []
        for arquivo in resumo.miniaturas:   # QImage pode ser lida fora da thread principal (QPixmap não)
            img = QImage(str(arquivo))
            if not img.isNull():
                imagens.append(img.scaled(LADO_IMAGEM_ITEM, LADO_IMAGEM_ITEM,
                                          Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                          Qt.TransformationMode.SmoothTransformation))
        try:
            self.sinais.pronto.emit(self.geracao, str(self.caminho), (resumo, imagens))
        except RuntimeError:   # a janela fechou no meio do caminho
            pass


# --------------------------------------------------------------------------------------------------------------------
# Widgets
# --------------------------------------------------------------------------------------------------------------------
def _alfa(cor: str, alfa: int) -> QColor:
    c = QColor(cor)
    c.setAlpha(alfa)
    return c


class BotaoAcao(QAbstractButton):
    """Botão grande: ícone numa caixa, título, subtítulo e o atalho. ``principal`` = laranja (a ação mais comum)."""

    ALTURA = 72

    def __init__(self, icone: str, titulo: str, subtitulo: str, atalho: str = "", principal: bool = False,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.icone, self.titulo, self.subtitulo, self.atalho, self.principal = (icone, titulo, subtitulo, atalho,
                                                                                principal)
        self.setText(titulo)
        self.setAccessibleName(titulo)
        self.setAccessibleDescription(subtitulo)
        self.setToolTip(f"{subtitulo} ({atalho})" if atalho else subtitulo)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def sizeHint(self) -> QSize:  # noqa: N802 - nome do Qt
        return QSize(250, self.ALTURA)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(170, self.ALTURA)

    def enterEvent(self, _e) -> None:  # noqa: N802
        self.update()

    def leaveEvent(self, _e) -> None:  # noqa: N802
        self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        sobre = self.underMouse() and self.isEnabled()
        if self.principal:
            fundo = QColor(tema.DESTAQUE_HI if sobre else tema.DESTAQUE)
            borda = fundo
            texto, apoio = QColor(tema.TEXTO_SOBRE_DESTAQUE), _alfa(tema.TEXTO_SOBRE_DESTAQUE, 185)
            caixa, cor_icone = _alfa(tema.TEXTO_SOBRE_DESTAQUE, 28), tema.TEXTO_SOBRE_DESTAQUE
        else:
            fundo = QColor(tema.PAINEL3 if sobre else tema.PAINEL2)
            borda = QColor(tema.BORDA_FORTE if sobre else tema.BORDA)
            texto, apoio = QColor(tema.TEXTO), QColor(tema.APAGADO)
            caixa, cor_icone = QColor(tema.BORDA if sobre else tema.PAINEL3), tema.TEXTO
        if not self.isEnabled():
            fundo, borda, texto, apoio = QColor(tema.PAINEL), QColor(tema.BORDA), QColor(tema.FRACO), QColor(tema.FRACO)
            cor_icone = tema.FRACO
        p.setPen(QPen(borda, 1))
        p.setBrush(fundo)
        p.drawRoundedRect(r, tema.RAIO_CARD, tema.RAIO_CARD)
        if self.hasFocus():
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(tema.TEXTO_SOBRE_DESTAQUE if self.principal else tema.DESTAQUE_DIM), 1.5))
            p.drawRoundedRect(r.adjusted(2, 2, -2, -2), tema.RAIO_CARD - 2, tema.RAIO_CARD - 2)
        lado = 40
        caixa_r = QRectF(r.left() + 14, r.center().y() - lado / 2, lado, lado)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(caixa)
        p.drawRoundedRect(caixa_r, 10, 10)
        p.drawPixmap(int(caixa_r.center().x()) - 11, int(caixa_r.center().y()) - 11,
                     icones.icone(self.icone, cor_icone, 22).pixmap(22, 22))
        x = caixa_r.right() + 12
        w = r.right() - x - 12
        f_titulo = tema.fonte(10.5, QFont.Weight.DemiBold, titulo=True)
        f_atalho = tema.fonte(8)
        larg_atalho = QFontMetrics(f_atalho).horizontalAdvance(self.atalho) + 10 if self.atalho else 0
        if QFontMetrics(f_titulo).horizontalAdvance(self.titulo) + larg_atalho > w:
            larg_atalho = 0   # falta lugar: o título vale mais que o atalho (que continua na dica)
        p.setFont(f_titulo)
        p.setPen(texto)
        p.drawText(QRectF(x, r.top() + 14, w - larg_atalho, 22), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   QFontMetrics(f_titulo).elidedText(self.titulo, Qt.TextElideMode.ElideRight, int(w - larg_atalho)))
        f_sub = tema.fonte(8.5)
        p.setFont(f_sub)
        p.setPen(apoio)
        p.drawText(QRectF(x, r.top() + 38, w, 20), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   QFontMetrics(f_sub).elidedText(self.subtitulo, Qt.TextElideMode.ElideRight, int(w)))
        if larg_atalho:
            p.setFont(f_atalho)
            p.drawText(QRectF(r.right() - 12 - larg_atalho, r.top() + 14, larg_atalho, 22),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, self.atalho)
        p.end()


class ItemRecente(QWidget):
    """Um trabalho recente: nome, conteúdo, data e miniaturas. Clique (ou Enter) abre; o "×" (ou Delete) tira da lista."""

    abrir = Signal(object)     # Path
    remover = Signal(object)   # Path

    ALTURA = 84
    LADO = 56

    def __init__(self, caminho: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.caminho = Path(caminho)
        self.resumo: ResumoTrabalho | None = None
        self.imagens: list[QImage] = []
        self.setFixedHeight(self.ALTURA)
        self.setMinimumWidth(260)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setToolTip(str(self.caminho))
        self.setAccessibleName(self.caminho.stem)
        self.botao_remover = QToolButton(self)
        self.botao_remover.setObjectName("Flat")
        self.botao_remover.setIcon(icones.icone("fechar", tema.FRACO, 14))
        self.botao_remover.setIconSize(QSize(14, 14))
        self.botao_remover.setToolTip(_("Tirar da lista (o arquivo continua no disco)"))
        self.botao_remover.setAccessibleName(_("Tirar da lista"))
        self.botao_remover.setCursor(Qt.CursorShape.PointingHandCursor)
        self.botao_remover.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.botao_remover.clicked.connect(lambda: self.remover.emit(self.caminho))

    def definir_resumo(self, resumo: ResumoTrabalho, imagens: list[QImage]) -> None:
        self.resumo = resumo
        self.imagens = list(imagens)
        self.update()

    def textos(self) -> tuple[str, str, str]:
        """(nome, conteúdo, data) como aparecem; o conteúdo é "Lendo…" até o resumo chegar."""
        r = self.resumo
        if r is None:
            return self.caminho.stem, _("Lendo…"), ""
        meio = r.erro if r.erro else texto_conteudo(r)
        return r.nome, meio, _("Salvo em {data}").format(data=data_curta(r.salvo_em)) if r.salvo_em else ""

    def resizeEvent(self, evento) -> None:  # noqa: N802
        super().resizeEvent(evento)
        tam = self.botao_remover.sizeHint()
        self.botao_remover.setGeometry(self.width() - tam.width() - 6, 6, tam.width(), tam.height())

    def enterEvent(self, _e) -> None:  # noqa: N802
        self.update()

    def leaveEvent(self, _e) -> None:  # noqa: N802
        self.update()

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.position().toPoint()):
            self.abrir.emit(self.caminho)
        super().mouseReleaseEvent(e)

    def keyPressEvent(self, e) -> None:  # noqa: N802
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.abrir.emit(self.caminho)
        elif e.key() == Qt.Key.Key_Delete:
            self.remover.emit(self.caminho)
        else:
            super().keyPressEvent(e)

    def _quantas_miniaturas(self, largura: float) -> int:
        """Quantas miniaturas cabem deixando pelo menos 200 px para o texto."""
        cabem = int((largura - 48 - 200) // (self.LADO + 6))
        desejadas = len(self.imagens) if self.imagens else 1
        return max(0, min(cabem, desejadas, MAX_MINIATURAS))

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        sobre = self.underMouse()
        p.setPen(QPen(QColor(tema.DESTAQUE_DIM if (sobre or self.hasFocus()) else tema.BORDA), 1))
        p.setBrush(QColor(tema.PAINEL3 if sobre else tema.PAINEL2))
        p.drawRoundedRect(r, tema.RAIO_CARD, tema.RAIO_CARD)

        n = self._quantas_miniaturas(r.width())
        lado = self.LADO
        fim = r.right() - 40   # o "×" fica no canto
        x0 = fim - n * lado - max(0, n - 1) * 6
        y = r.center().y() - lado / 2
        for i in range(n):
            area = QRectF(x0 + i * (lado + 6), y, lado, lado)
            caminho = QPainterPath()
            caminho.addRoundedRect(area, 8, 8)
            p.save()
            p.setClipPath(caminho)
            if i < len(self.imagens):
                img = self.imagens[i]
                # recorte central quadrado da miniatura já reduzida
                lado_img = min(img.width(), img.height())
                origem = QRectF((img.width() - lado_img) / 2, (img.height() - lado_img) / 2, lado_img, lado_img)
                p.drawImage(area, img, origem)
            else:
                p.fillRect(area, QColor(tema.PAINEL))
                p.drawPixmap(int(area.center().x()) - 12, int(area.center().y()) - 12,
                             icones.icone("foto", tema.FRACO, 24).pixmap(24, 24))
            p.restore()

        nome, meio, data = self.textos()
        x = r.left() + 16
        w = (x0 - 14 if n else fim) - x
        f_nome = tema.fonte(10.5, QFont.Weight.DemiBold, titulo=True)
        p.setFont(f_nome)
        p.setPen(QColor(tema.TEXTO))
        p.drawText(QRectF(x, r.top() + 12, w, 22), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   QFontMetrics(f_nome).elidedText(nome, Qt.TextElideMode.ElideRight, int(w)))
        f_meio = tema.fonte(9)
        p.setFont(f_meio)
        erro = self.resumo is not None and bool(self.resumo.erro)
        p.setPen(QColor(tema.PERIGO if erro else tema.APAGADO if self.resumo is not None else tema.FRACO))
        p.drawText(QRectF(x, r.top() + 35, w, 20), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   QFontMetrics(f_meio).elidedText(meio, Qt.TextElideMode.ElideRight, int(w)))
        if data:
            f_data = tema.fonte(8.5)
            p.setFont(f_data)
            p.setPen(QColor(tema.FRACO))
            p.drawText(QRectF(x, r.top() + 55, w, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       QFontMetrics(f_data).elidedText(data, Qt.TextElideMode.ElideRight, int(w)))
        p.end()


class DialogoNovidades(QDialog):
    """As novidades da versão (o arquivo inteiro da release), não modal."""

    def __init__(self, parent: QWidget | None, texto: str, versao: str = __version__) -> None:
        super().__init__(parent)
        self.setModal(False)
        self.setWindowTitle(_("Novidades do {app} {versao}").format(app=APP_NAME, versao=versao))
        self.resize(640, 600)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 16)
        lay.setSpacing(8)
        kicker = QLabel(_("NOVIDADES"))
        kicker.setObjectName("Kicker")
        lay.addWidget(kicker)
        titulo = QLabel(_("O que há de novo na versão {versao}").format(versao=versao))
        titulo.setObjectName("PanelTitle")
        lay.addWidget(titulo)
        self.texto = QTextBrowser()
        self.texto.setOpenExternalLinks(True)
        self.texto.setMarkdown(corpo_novidades(texto))
        lay.addWidget(self.texto, 1)
        linha = QHBoxLayout()
        linha.addStretch(1)
        fechar = QPushButton(_("Fechar"))
        fechar.setObjectName("Primary")
        fechar.clicked.connect(self.close)
        linha.addWidget(fechar)
        lay.addLayout(linha)


class PaginaBoasVindas(QWidget):
    """A página em si (só monta e mostra; quem decide é ``BoasVindas``)."""

    fechar_pedido = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("BoasVindas")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.itens: list[ItemRecente] = []
        self.botoes_acao: dict[str, BotaoAcao] = {}
        self.estado_atualizacao = "versao"
        self.uma_coluna = False

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        self.rolagem = QScrollArea()
        self.rolagem.setWidgetResizable(True)
        self.rolagem.setFrameShape(QFrame.Shape.NoFrame)
        self.rolagem.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        raiz.addWidget(self.rolagem)
        fora = QWidget()
        centro = QHBoxLayout(fora)
        centro.setContentsMargins(32, 26, 32, 32)
        centro.addStretch(1)
        self.coluna = QWidget()
        self.coluna.setMaximumWidth(LARGURA_MAXIMA)
        self.coluna.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        centro.addWidget(self.coluna, 100)
        centro.addStretch(1)
        self.rolagem.setWidget(fora)
        col = QVBoxLayout(self.coluna)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(14)

        col.addLayout(self._cabecalho())
        col.addSpacing(8)
        kicker = QLabel(_("COMEÇAR"))
        kicker.setObjectName("Kicker")
        col.addWidget(kicker)
        self.grade_acoes = QGridLayout()
        self.grade_acoes.setHorizontalSpacing(12)
        self.grade_acoes.setVerticalSpacing(12)
        col.addLayout(self.grade_acoes)
        self.cartao_recuperacao = self._cartao_recuperacao()
        col.addWidget(self.cartao_recuperacao)
        col.addSpacing(6)

        self.colunas = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self.colunas.setSpacing(24)
        self.colunas.addWidget(self._recentes(), 1)
        self.lateral = self._lateral()
        self.colunas.addWidget(self.lateral, 0)
        col.addLayout(self.colunas)
        col.addStretch(1)

    # ------------------------------------------------------------ montagem
    def _cabecalho(self) -> QHBoxLayout:
        cab = QHBoxLayout()
        cab.setSpacing(16)
        logo = QLabel()
        logo.setPixmap(icones.icone_app().pixmap(QSize(56, 56)))
        logo.setFixedSize(56, 56)
        cab.addWidget(logo, 0, Qt.AlignmentFlag.AlignTop)
        textos = QVBoxLayout()
        textos.setSpacing(4)
        titulo = QLabel(_("Boas-vindas ao {app}").format(app=APP_NAME))
        titulo.setObjectName("PanelTitle")
        titulo.setStyleSheet("font-size: 19pt;")
        textos.addWidget(titulo)
        linha = QHBoxLayout()
        linha.setSpacing(10)
        self.rotulo_versao = QLabel(_("Versão {versao} · {data}").format(versao=__version__, data=data_longa(__date__)))
        self.rotulo_versao.setObjectName("Muted")
        linha.addWidget(self.rotulo_versao)
        self.icone_atualizacao = QLabel()
        self.icone_atualizacao.hide()
        linha.addWidget(self.icone_atualizacao)
        self.rotulo_atualizacao = QLabel()
        self.rotulo_atualizacao.setObjectName("Muted")
        self.rotulo_atualizacao.hide()
        linha.addWidget(self.rotulo_atualizacao)
        self.botao_atualizar = QPushButton()
        self.botao_atualizar.setObjectName("Primary")
        self.botao_atualizar.setIcon(icones.icone("exportar", tema.TEXTO_SOBRE_DESTAQUE, 16))
        self.botao_atualizar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.botao_atualizar.hide()
        linha.addWidget(self.botao_atualizar)
        self.botao_verificar = QPushButton()
        self.botao_verificar.setObjectName("Flat")
        self.botao_verificar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.botao_verificar.hide()
        linha.addWidget(self.botao_verificar)
        linha.addStretch(1)
        textos.addLayout(linha)
        cab.addLayout(textos, 1)

        rotulo = QLabel(_("Mostrar ao abrir"))
        rotulo.setObjectName("Muted")
        self.chave_mostrar = ToggleSwitch()
        self.chave_mostrar.setToolTip(_("Mostrar esta tela quando o Revelador abrir sem um arquivo"))
        self.chave_mostrar.setAccessibleName(_("Mostrar ao abrir"))
        rotulo.setBuddy(self.chave_mostrar)
        self.botao_fechar = QPushButton("  " + _("Fechar"))
        self.botao_fechar.setObjectName("Flat")
        self.botao_fechar.setIcon(icones.icone("fechar", tema.APAGADO, 14))
        self.botao_fechar.setToolTip(_("Ir para o trabalho (Esc)"))
        self.botao_fechar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.botao_fechar.clicked.connect(self.fechar_pedido)
        for w in (rotulo, self.chave_mostrar, self.botao_fechar):
            cab.addWidget(w, 0, Qt.AlignmentFlag.AlignTop)
        return cab

    def _cartao_recuperacao(self) -> QFrame:
        cartao = QFrame()
        cartao.setObjectName("Recuperacao")
        cartao.setStyleSheet(f"QFrame#Recuperacao {{ background: {tema.PAINEL2}; border: 1px solid {tema.DESTAQUE_DIM}; "
                             f"border-left: 4px solid {tema.DESTAQUE}; border-radius: {tema.RAIO_CARD}px; }}")
        lay = QHBoxLayout(cartao)
        lay.setContentsMargins(16, 12, 14, 12)
        lay.setSpacing(14)
        icone = QLabel()
        icone.setPixmap(icones.icone("reset", tema.DESTAQUE, 24).pixmap(24, 24))
        lay.addWidget(icone, 0, Qt.AlignmentFlag.AlignTop)
        textos = QVBoxLayout()
        textos.setSpacing(2)
        titulo = QLabel(_("Há um trabalho para recuperar"))
        titulo.setObjectName("PanelTitle")
        textos.addWidget(titulo)
        self.texto_recuperacao = QLabel()
        self.texto_recuperacao.setObjectName("Muted")
        self.texto_recuperacao.setWordWrap(True)
        textos.addWidget(self.texto_recuperacao)
        lay.addLayout(textos, 1)
        self.botao_descartar = QPushButton(_("Descartar"))
        self.botao_descartar.setObjectName("Flat")
        self.botao_descartar.setToolTip(_("Apagar a cópia de recuperação"))
        self.botao_recuperar = QPushButton("  " + _("Recuperar"))
        self.botao_recuperar.setObjectName("Primary")
        self.botao_recuperar.setIcon(icones.icone("reset", tema.TEXTO_SOBRE_DESTAQUE, 16))
        for b in (self.botao_descartar, self.botao_recuperar):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            lay.addWidget(b, 0, Qt.AlignmentFlag.AlignVCenter)
        cartao.hide()
        return cartao

    def _recentes(self) -> QWidget:
        caixa = QWidget()
        lay = QVBoxLayout(caixa)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        topo = QHBoxLayout()
        kicker = QLabel(_("TRABALHOS RECENTES"))
        kicker.setObjectName("Kicker")
        topo.addWidget(kicker)
        topo.addStretch(1)
        dica = QLabel(_("Clique para abrir"))
        dica.setObjectName("Faint")
        topo.addWidget(dica)
        lay.addLayout(topo)
        self.lista_recentes = QVBoxLayout()
        self.lista_recentes.setSpacing(8)
        lay.addLayout(self.lista_recentes)
        self.vazio_recentes = QLabel(_("Nenhum trabalho salvo ainda. Importe as fotos, marque as que vão para o "
                                       "laboratório e use Projeto → Salvar para continuar depois de onde parou."))
        self.vazio_recentes.setObjectName("Muted")
        self.vazio_recentes.setWordWrap(True)
        self.vazio_recentes.setContentsMargins(2, 6, 2, 6)
        lay.addWidget(self.vazio_recentes)
        lay.addStretch(1)
        return caixa

    def _lateral(self) -> QWidget:
        caixa = QWidget()
        caixa.setFixedWidth(LARGURA_LATERAL)
        lay = QVBoxLayout(caixa)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        self.cartao_fluxo = Card(_("Como funciona"), _("Importar → Marcar e enquadrar → Exportar"))
        for n, (icone, titulo, texto) in enumerate((
                ("importar", _("Importar"), _("Fotos soltas ou uma pasta inteira; os originais nunca mudam.")),
                ("recorte", _("Marcar e enquadrar"),
                 _("Marque as que vão para o laboratório, escolha o tamanho e ajuste o corte.")),
                ("exportar", _("Exportar"), _("Uma pasta por tamanho, no tamanho exato do papel."))), start=1):
            linha = QHBoxLayout()
            linha.setSpacing(10)
            ic = QLabel()
            ic.setPixmap(icones.icone(icone, tema.DESTAQUE, 18).pixmap(18, 18))
            ic.setFixedWidth(20)
            linha.addWidget(ic, 0, Qt.AlignmentFlag.AlignTop)
            textos = QVBoxLayout()
            textos.setSpacing(0)
            t = QLabel(f"{n}. {titulo}")
            textos.addWidget(t)
            d = QLabel(texto)
            d.setObjectName("Faint")
            d.setWordWrap(True)
            textos.addWidget(d)
            linha.addLayout(textos, 1)
            self.cartao_fluxo.corpo_layout.addLayout(linha)
        lay.addWidget(self.cartao_fluxo)

        self.cartao_novidades = Card(_("Novidades da versão {versao}").format(versao=__version__))
        self.texto_novidades = QLabel()
        self.texto_novidades.setTextFormat(Qt.TextFormat.MarkdownText)
        self.texto_novidades.setWordWrap(True)
        self.texto_novidades.setOpenExternalLinks(True)
        self.cartao_novidades.adicionar(self.texto_novidades)
        self.botao_novidades = QPushButton("  " + _("Ver todas as novidades"))
        self.botao_novidades.setObjectName("Flat")
        self.botao_novidades.setIcon(icones.icone("info", tema.APAGADO, 16))
        self.botao_novidades.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cartao_novidades.corpo_layout.addWidget(self.botao_novidades, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(self.cartao_novidades)
        lay.addStretch(1)
        return caixa

    def adicionar_acao(self, chave: str, botao: BotaoAcao) -> None:
        self.botoes_acao[chave] = botao
        self.reorganizar(self.width() or LARGURA_MAXIMA)

    # ------------------------------------------------------------ conteúdo
    def definir_recentes(self, caminhos: list[Path]) -> list[ItemRecente]:
        for item in self.itens:
            self.lista_recentes.removeWidget(item)
            item.hide()
            item.deleteLater()
        self.itens = [ItemRecente(c) for c in caminhos]
        for item in self.itens:
            self.lista_recentes.addWidget(item)
        self.vazio_recentes.setVisible(not self.itens)
        return self.itens

    def item(self, caminho: Path | str) -> ItemRecente | None:
        chave = os.path.normcase(str(Path(caminho)))
        return next((i for i in self.itens if os.path.normcase(str(i.caminho)) == chave), None)

    def tirar_item(self, caminho: Path | str) -> None:
        item = self.item(caminho)
        if item is not None:
            self.itens.remove(item)
            self.lista_recentes.removeWidget(item)
            item.hide()
            item.deleteLater()
        self.vazio_recentes.setVisible(not self.itens)

    def definir_recuperacao(self, texto: str | None) -> None:
        if texto:
            self.texto_recuperacao.setText(texto)
        self.cartao_recuperacao.setVisible(bool(texto))

    def definir_novidades(self, resumo: str) -> None:
        self.texto_novidades.setText(resumo)
        self.cartao_novidades.setVisible(bool(resumo))

    def definir_atualizacao(self, estado: str, versao: str = "") -> None:
        """``versao`` (só a versão atual), ``procurando``, ``atualizado``, ``disponivel``, ``erro`` ou ``desligada``."""
        self.estado_atualizacao = estado
        textos = {
            "procurando": _("Procurando atualizações…"),
            "atualizado": _("Você está na versão mais recente"),
            "disponivel": _("Versão {versao} disponível").format(versao=versao),
            "erro": _("Não foi possível procurar atualizações."),
            "desligada": _("A busca automática de atualizações está desligada."),
        }
        texto = textos.get(estado, "")
        icone = {"atualizado": ("check", tema.OK), "disponivel": ("info", tema.DESTAQUE_HI)}.get(estado)
        self.rotulo_atualizacao.setText(texto if (icone or not texto) else "· " + texto)   # o ícone já separa
        self.rotulo_atualizacao.setVisible(bool(texto))
        if icone:
            self.icone_atualizacao.setPixmap(icones.icone(icone[0], icone[1], 14).pixmap(14, 14))
        self.icone_atualizacao.setVisible(bool(icone))
        self.botao_atualizar.setText("  " + _("Atualizar para a {versao}").format(versao=versao))
        self.botao_atualizar.setVisible(estado == "disponivel")
        self.botao_verificar.setText(_("Tentar de novo") if estado == "erro" else _("Procurar agora"))
        self.botao_verificar.setVisible(estado in ("erro", "desligada"))

    # ------------------------------------------------------------ largura
    def reorganizar(self, largura: int) -> None:
        """Botões em 4, 2 ou 1 coluna; recentes e cartões lado a lado ou um embaixo do outro."""
        util = min(largura - 64, LARGURA_MAXIMA)
        por_linha = 4 if util >= 900 else 2 if util >= 420 else 1
        botoes = list(self.botoes_acao.values())
        for b in botoes:
            self.grade_acoes.removeWidget(b)
        for i, b in enumerate(botoes):
            self.grade_acoes.addWidget(b, i // por_linha, i % por_linha)
        for c in range(4):
            self.grade_acoes.setColumnStretch(c, 1 if c < por_linha else 0)
        uma = util < LARGURA_UMA_COLUNA
        if uma != self.uma_coluna or self.colunas.direction() != (
                QBoxLayout.Direction.TopToBottom if uma else QBoxLayout.Direction.LeftToRight):
            self.uma_coluna = uma
            self.colunas.setDirection(QBoxLayout.Direction.TopToBottom if uma else QBoxLayout.Direction.LeftToRight)
            if uma:
                self.lateral.setMinimumWidth(0)
                self.lateral.setMaximumWidth(16777215)
            else:
                self.lateral.setFixedWidth(LARGURA_LATERAL)

    def resizeEvent(self, evento) -> None:  # noqa: N802
        super().resizeEvent(evento)
        self.reorganizar(self.width())

    def keyPressEvent(self, e) -> None:  # noqa: N802
        if e.key() == Qt.Key.Key_Escape:
            self.fechar_pedido.emit()
            return
        super().keyPressEvent(e)

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(tema.BG))
        p.end()


# --------------------------------------------------------------------------------------------------------------------
# Controlador
# --------------------------------------------------------------------------------------------------------------------
class BoasVindas(QObject):
    """Decide quando a tela aparece e liga a página às ações da janela, ao ``ProjetoUi`` e ao ``Verificador``."""

    def __init__(self, janela) -> None:
        super().__init__(janela)
        self.janela = janela
        self.pagina: PaginaBoasVindas | None = None
        self.dialogo_novidades: DialogoNovidades | None = None
        self.recuperacao: Path | None = None
        self.release: updater.Release | None = None
        self._geracao = 0
        self._pendentes = 0
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(2)
        self._sinais = _Sinais(self)
        self._sinais.pronto.connect(self._ao_resumo)

        janela.acao_boas_vindas.setEnabled(True)
        janela.acao_boas_vindas.triggered.connect(lambda _c=False: self.mostrar())
        janela.estado.fotos_mudaram.connect(self._ao_mudar_fotos)
        verificador = getattr(janela, "verificador", None)
        if verificador is not None and hasattr(verificador, "verificado"):
            verificador.verificado.connect(self._ao_verificado)

    # ------------------------------------------------------------ abertura do app
    def deve_mostrar_ao_abrir(self) -> bool:
        """Sem nada na linha de comando (nem trabalho aberto por ela) e com "Mostrar ao abrir" ligada."""
        j = self.janela
        return (mostrar_ao_abrir() and not j.arquivos_iniciais and j.estado.trabalho.caminho is None
                and not j.estado.trabalho.fotos)

    def ao_abrir(self) -> None:
        """Chamado uma vez por ``app.main``, depois de tratar a linha de comando."""
        pendentes = novidades_pendentes()
        marcar_versao_vista()
        if self.deve_mostrar_ao_abrir():
            self.mostrar(na_abertura=True)
        if pendentes and texto_novidades():
            QTimer.singleShot(0, self.mostrar_novidades)   # depois de a janela aparecer

    # ------------------------------------------------------------ mostrar e fechar
    def visivel(self) -> bool:
        return self.pagina is not None and not self.pagina.isHidden()

    def mostrar(self, na_abertura: bool = False) -> None:
        if self.pagina is None:
            self._criar_pagina()
        pagina = self.pagina
        pagina.chave_mostrar.blockSignals(True)
        pagina.chave_mostrar.setChecked(mostrar_ao_abrir())
        pagina.chave_mostrar.blockSignals(False)
        pagina.definir_novidades(resumo_novidades(texto_novidades()))
        pagina.setMinimumWidth(self.janela.divisor.minimumWidth())   # a janela não muda de largura ao fechar
        self.recarregar_recentes()
        self._atualizar_recuperacao()
        self._atualizar_aviso_versao(na_abertura)
        self.janela.divisor.hide()
        pagina.show()
        pagina.reorganizar(pagina.width())
        pagina.setFocus()

    def fechar(self) -> None:
        if not self.visivel():
            return
        self.pagina.hide()
        self.janela.divisor.show()
        QTimer.singleShot(0, self._devolver_faixa_recuperacao)

    def _ao_mudar_fotos(self) -> None:
        if self.visivel():
            self.fechar()

    def _criar_pagina(self) -> None:
        j = self.janela
        pagina = PaginaBoasVindas()
        for chave, acao, icone, titulo, subtitulo, principal in (
                ("importar", j.acao_importar, "importar", _("Importar fotos"), _("Escolha as fotos no computador"),
                 True),
                ("importar_pasta", j.acao_importar_pasta, "pasta", _("Importar pasta"),
                 _("Todas as fotos de uma pasta"), False),
                ("novo", j.acao_novo, "mais", _("Novo trabalho"), _("Começar do zero"), False),
                ("abrir", j.acao_abrir, "abrir", _("Abrir trabalho…"), _("Um .revelador salvo antes"), False)):
            atalho = acao.shortcut().toString(QKeySequence.SequenceFormat.NativeText)
            botao = BotaoAcao(icone, titulo, subtitulo, atalho, principal)
            botao.clicked.connect(acao.trigger)
            botao.setEnabled(acao.isEnabled())
            acao.changed.connect(lambda b=botao, a=acao: b.setEnabled(a.isEnabled()))
            pagina.adicionar_acao(chave, botao)
        pagina.fechar_pedido.connect(self.fechar)
        pagina.chave_mostrar.toggled.connect(definir_mostrar_ao_abrir)
        pagina.botao_recuperar.clicked.connect(lambda: self.recuperar())
        pagina.botao_descartar.clicked.connect(lambda: self.descartar_recuperacao())
        pagina.botao_atualizar.clicked.connect(lambda: self.abrir_atualizacao())
        pagina.botao_verificar.clicked.connect(lambda: self.procurar_atualizacao())
        pagina.botao_novidades.clicked.connect(lambda: self.mostrar_novidades())
        lay = j.centralWidget().layout()
        lay.insertWidget(lay.indexOf(j.divisor) + 1, pagina, 1)
        pagina.hide()
        self.pagina = pagina

    # ------------------------------------------------------------ recentes
    def recarregar_recentes(self) -> None:
        """Refaz a lista (os que não existem mais somem) e pede os resumos em segundo plano."""
        if self.pagina is None:
            return
        self._geracao += 1
        caminhos = self.janela.projeto_ui.recentes()
        self.pagina.definir_recentes(caminhos)
        for item in self.pagina.itens:
            item.abrir.connect(self.abrir_recente)
            item.remover.connect(self.remover_recente)
        for caminho in caminhos:
            self._pendentes += 1
            self._pool.start(_TarefaResumo(self._geracao, caminho, self._sinais))

    def ocupado(self) -> bool:
        """True enquanto há resumos de recentes sendo lidos."""
        return self._pendentes > 0

    def _ao_resumo(self, geracao: int, caminho: str, carga) -> None:
        self._pendentes = max(0, self._pendentes - 1)
        if geracao != self._geracao or self.pagina is None:
            return
        item = self.pagina.item(caminho)
        if item is not None:
            resumo, imagens = carga
            item.definir_resumo(resumo, imagens)

    def abrir_recente(self, caminho: Path | str) -> bool:
        caminho = Path(caminho)
        if not caminho.is_file():
            self.recarregar_recentes()   # sumiu do disco: some da lista também
            return False
        ok = self.janela.projeto_ui.abrir(caminho)
        if not ok and self.visivel():
            self.recarregar_recentes()   # arquivo danificado: o ProjetoUi já o tirou dos recentes
        return ok

    def remover_recente(self, caminho: Path | str) -> None:
        """Tira da lista de recentes (o arquivo continua no disco)."""
        pu = self.janela.projeto_ui
        esquecer = getattr(pu, "esquecer_recente", None) or pu._esquecer_recente   # noqa: SLF001 - sem API pública
        esquecer(Path(caminho))
        if self.pagina is not None:
            self.pagina.tirar_item(caminho)

    # ------------------------------------------------------------ recuperação
    def _atualizar_recuperacao(self) -> None:
        """Mostra o cartão no lugar da faixa "recuperacao" (o ProjetoUi escolhe o arquivo e monta o texto)."""
        pu = self.janela.projeto_ui
        arquivo = pu.oferecer_recuperacao()
        texto = None
        if arquivo is not None:
            faixa = self.janela.faixas.faixas.get("recuperacao")
            texto = faixa.rotulo.text() if faixa is not None else arquivo.stem
            self.janela.faixas.fechar("recuperacao")
        self.recuperacao = arquivo
        self.pagina.definir_recuperacao(texto)

    def recuperar(self) -> bool:
        if self.recuperacao is None:
            return False
        return self.janela.projeto_ui.restaurar_recuperacao(self.recuperacao)   # deu certo: as fotos mudam e a tela sai

    def descartar_recuperacao(self) -> None:
        if self.recuperacao is not None:
            self.janela.projeto_ui.descartar_recuperacao([self.recuperacao])
        self._atualizar_recuperacao()   # se houver outra cópia, ela aparece

    def _devolver_faixa_recuperacao(self) -> None:
        arquivo, self.recuperacao = self.recuperacao, None
        if not self.visivel() and arquivo is not None and arquivo.exists():
            self.janela.projeto_ui.oferecer_recuperacao()

    # ------------------------------------------------------------ atualizações
    def _sem_rede(self) -> bool:
        return bool(os.environ.get("REVELADOR_SEM_REDE"))

    def _atualizar_aviso_versao(self, na_abertura: bool = False) -> None:
        from .atualizacao import automatica_ligada

        v = getattr(self.janela, "verificador", None)
        if self._sem_rede() or v is None or not hasattr(v, "consultar_silencioso"):
            self.pagina.definir_atualizacao("versao")
        elif v.ultimo is not None:
            self._ao_verificado(*v.ultimo)
        elif v.consultando or (na_abertura and v.deve_verificar_ao_abrir()):
            self.pagina.definir_atualizacao("procurando")   # a verificação do dia já vai responder
        elif automatica_ligada():
            self.procurar_atualizacao()
        else:
            self.pagina.definir_atualizacao("desligada")

    def procurar_atualizacao(self) -> None:
        v = getattr(self.janela, "verificador", None)
        if v is None or self._sem_rede():
            return
        if self.pagina is not None:
            self.pagina.definir_atualizacao("procurando")
        v.consultar_silencioso()

    def _ao_verificado(self, rel, erro: str) -> None:
        self.release = rel if rel is not None and updater.is_newer(rel) else None
        if self.pagina is None:
            return
        if rel is None:
            self.pagina.definir_atualizacao("erro")
        elif self.release is not None:
            self.pagina.definir_atualizacao("disponivel", rel.tag.lstrip("v"))
        else:
            self.pagina.definir_atualizacao("atualizado")

    def abrir_atualizacao(self):
        """Abre o diálogo de atualização (#10) da versão encontrada."""
        v = getattr(self.janela, "verificador", None)
        if v is None or self.release is None:
            return None
        return v.mostrar_dialogo(self.release)

    # ------------------------------------------------------------ novidades
    def mostrar_novidades(self) -> DialogoNovidades | None:
        texto = texto_novidades()
        if not texto:
            return None
        if self.dialogo_novidades is None:
            self.dialogo_novidades = DialogoNovidades(self.janela, texto)
        self.dialogo_novidades.show()
        self.dialogo_novidades.raise_()
        return self.dialogo_novidades
