"""Seção "Pastas" acima da grade e os diálogos das pastas de tamanho (#32).

Uma pasta de tamanho é um grupo virtual do trabalho (nada muda no disco): a foto que entra nela fica marcada para
revelação no tamanho da pasta. Tudo passa pela API de pastas do ``Estado`` (``criar_pasta``, ``alterar_pasta``,
``mover_pasta``, ``apagar_pasta``, ``adicionar_a_pasta``, ``tirar_da_pasta``...), que já agrupa cada operação num
passo do desfazer.

- ``SecaoPastas``: faixa compacta e recolhível no topo da grade. "Todas" e uma linha por pasta (bolinha da cor, nome,
  tamanho e número de fotos); clicar numa linha filtra a grade por ela (sinal ``filtro_mudou(id | None)``; clicar de
  novo na pasta escolhida, ou em "Todas", volta). Clique direito ou "⋯" abre o menu da pasta (``menu_pasta``):
  renomear, cor, tamanho (inclusive personalizado), cópias padrão, subir/descer e apagar. As linhas aceitam fotos
  arrastadas da grade (``MIME_FOTOS``). Com muitas pastas a lista rola (até ``MAX_LINHAS`` à vista).
- ``PastaDialog``: nome, tamanho (o padrão já escolhido; "Personalizado…" mostra as medidas e o preço) e cor da
  paleta (``tema.CORES_PASTA``). ``dialogo_nova_pasta`` o devolve já ligado: aceitar cria a pasta (e, se pedido,
  põe nela as fotos dadas, no mesmo passo do desfazer).
- ``PassoImportarPasta``: o passo curto de "Importar pasta": "Criar pasta de tamanho" (marcado), nome da pasta do
  disco, tamanho padrão e a próxima cor da paleta.

Nada aqui chama ``exec()`` em teste: os diálogos são criados por funções/métodos ``criar_*``/``dialogo_*`` e
aceitos com ``accept()``; as perguntas modais da seção (``pedir_nome``, ``confirmar_apagar``,
``pedir_personalizado``) são atributos que os testes trocam.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from PySide6.QtCore import QByteArray, QMimeData, QPoint, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QFont, QFontMetrics, QPainter, QPen, QTransform
from PySide6.QtWidgets import (QAbstractButton, QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMenu,
                               QMessageBox, QScrollArea, QSizePolicy, QSpinBox, QToolButton, QVBoxLayout, QWidget)

from .. import precos, tamanhos
from ..i18n import _
from ..projeto import Foto, Pasta
from . import icones, prefs, tema
from .componentes import botao_plano
from .estado import Estado
from .painel_impressoes import NOMES_GRUPOS, PersonalizadoDialog, escolher_no_combo, preencher_combo_tamanhos

MIME_FOTOS = "application/x-revelador-fotos"   # ids das fotos arrastadas da grade, um por linha (UTF-8)
ALTURA_LINHA = 28
ESPACO_LINHAS = 1
MAX_LINHAS = 5            # linhas à vista antes de a lista rolar (meia linha a mais avisa que rola)
LADO_BOLINHA = 10
COPIAS_PASTA = (1, 2, 3, 5, 10)
CHAVE_RECOLHIDA = "grade/pastas_recolhidas"
ATRASO_CONTAGEM_MS = 80   # debounce da contagem de fotos (foto_mudou dispara muito durante um gesto)
PAPEL_PADRAO_MM = (100.0, 150.0)


# ------------------------------------------------------------------------------------------------ utilidades
def mime_das_fotos(fotos: Iterable[Foto]) -> QMimeData:
    """``QMimeData`` com os ids das fotos (formato ``MIME_FOTOS``), na ordem dada. Sem URLs: soltar no Explorer
    não copia nem move o original."""
    mime = QMimeData()
    mime.setData(MIME_FOTOS, QByteArray("\n".join(f.id for f in fotos).encode("utf-8")))
    return mime


def ids_do_mime(mime: QMimeData | None) -> list[str]:
    """Ids das fotos de um arrasto da grade ([] se o arrasto não veio dela)."""
    if mime is None or not mime.hasFormat(MIME_FOTOS):
        return []
    texto = bytes(mime.data(MIME_FOTOS).data()).decode("utf-8", errors="replace")
    return [i for i in texto.split("\n") if i]


def fotos_do_mime(estado: Estado, mime: QMimeData | None) -> list[Foto]:
    """Fotos do trabalho cujos ids vieram no arrasto (ids desconhecidos são ignorados)."""
    fotos = (estado.por_id(i) for i in ids_do_mime(mime))
    return [f for f in fotos if f is not None]


def _chave_caminho(caminho: Path) -> str:
    try:
        return str(Path(caminho).resolve()).casefold()
    except OSError:
        return str(caminho).casefold()


def fotos_dos_caminhos(estado: Estado, caminhos: Iterable[Path]) -> list[Foto]:
    """Fotos do trabalho que apontam para esses arquivos (mesma comparação da importação), na ordem do trabalho."""
    chaves = {_chave_caminho(c) for c in caminhos}
    return [f for f in estado.trabalho.fotos if _chave_caminho(f.caminho) in chaves]


def nome_tamanho(tamanho: str, papel_mm: tuple[float, float] | None = None) -> str:
    """Nome curto do tamanho de uma pasta: "10x15" ou, no personalizado, "88x107 mm"."""
    if tamanho == tamanhos.PERSONALIZADO:
        try:
            menor, maior = tamanhos.papel_mm(tamanho, papel_mm)
        except (KeyError, ValueError):
            return _("Personalizado")
        return f"{menor:g}x{maior:g} mm"
    try:
        return _(tamanhos.obter(tamanho).nome)
    except KeyError:
        return tamanho


def contar_fotos(estado: Estado) -> dict[str, int]:
    """Número de fotos em cada pasta (id → n), numa passada só pelo trabalho; inclui as desmarcadas."""
    contagem = {p.id: 0 for p in estado.trabalho.pastas}
    for foto in estado.trabalho.fotos:
        for pid in {i.pasta for i in foto.impressoes if i.pasta is not None}:
            if pid in contagem:
                contagem[pid] += 1
    return contagem


def texto_fotos(n: int) -> str:
    return _("1 foto") if n == 1 else _("{n} fotos").format(n=n)


# ------------------------------------------------------------------------------------------------ cor
class BotaoCor(QAbstractButton):
    """Bolinha marcável de uma cor da paleta (anel claro quando marcada)."""

    LADO = 26

    def __init__(self, chave: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.chave = chave
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(tema.nome_cor_pasta(chave))
        self.setAccessibleName(tema.nome_cor_pasta(chave))
        self.setFixedSize(self.LADO, self.LADO)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self.LADO, self.LADO)

    def paintEvent(self, _evento) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        if self.isChecked():
            p.setPen(QPen(QColor(tema.TEXTO), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(r)
        elif self.underMouse():
            p.setPen(QPen(QColor(tema.BORDA_FORTE), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(r)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(tema.cor_pasta(self.chave)))
        p.drawEllipse(r.adjusted(4, 4, -4, -4))
        p.end()


class SeletorCor(QWidget):
    """As cores da paleta de pastas lado a lado, uma só marcada; sinal ``mudou(chave)``."""

    mudou = Signal(str)

    def __init__(self, cor: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.grupo = QButtonGroup(self)
        self.grupo.setExclusive(True)
        self.botoes: dict[str, BotaoCor] = {}
        for chave in tema.CORES_PASTA:
            b = BotaoCor(chave)
            self.grupo.addButton(b)
            lay.addWidget(b)
            self.botoes[chave] = b
            b.clicked.connect(lambda _c=False, k=chave: self.mudou.emit(k))
        lay.addStretch(1)
        self.definir_cor(cor)

    def cor(self) -> str:
        return next((k for k, b in self.botoes.items() if b.isChecked()), next(iter(tema.CORES_PASTA)))

    def definir_cor(self, chave: str) -> None:
        botao = self.botoes.get(chave) or next(iter(self.botoes.values()))
        botao.setChecked(True)


# ------------------------------------------------------------------------------------------------ diálogos
class PastaDialog(QDialog):
    """Nome, tamanho e cor de uma pasta de tamanho. ``valores()`` dá os argumentos de ``Estado.criar_pasta``.

    Testável sem ``exec()``: preencha ``campo_nome``/``combo_tamanho``/``seletor_cor`` e chame ``accept()``; com nome
    vazio ou medida/preço inválidos, o diálogo mostra o erro e continua aberto (``result()`` não muda).
    """

    def __init__(self, estado: Estado, titulo: str, texto_ok: str, nome: str = "", tamanho: str | None = None,
                 cor: str | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.estado = estado
        self.setWindowTitle(titulo)
        self.setMinimumWidth(400)
        self.raiz = QVBoxLayout(self)
        self.raiz.setContentsMargins(22, 20, 22, 18)
        self.raiz.setSpacing(14)
        self.topo = QVBoxLayout()   # subclasses põem aqui um título ou uma chave antes do formulário
        self.topo.setSpacing(6)
        self.raiz.addLayout(self.topo)

        self.campo_nome = QLineEdit(nome)
        self.campo_nome.setPlaceholderText(_("ex.: Família, 10x15 da festa"))
        self.campo_nome.setMaxLength(80)
        self.combo_tamanho = QComboBox()
        preencher_combo_tamanhos(self.combo_tamanho)
        escolher_no_combo(self.combo_tamanho, tamanho or estado.trabalho.tamanho_padrao)
        self.largura = self._spin(PAPEL_PADRAO_MM[0])
        self.altura = self._spin(PAPEL_PADRAO_MM[1])
        papel = QWidget()
        linha_papel = QHBoxLayout(papel)
        linha_papel.setContentsMargins(0, 0, 0, 0)
        linha_papel.setSpacing(6)
        vezes = QLabel("×")
        vezes.setObjectName("Muted")
        linha_papel.addWidget(self.largura, 1)
        linha_papel.addWidget(vezes)
        linha_papel.addWidget(self.altura, 1)
        self.preco = QLineEdit()
        self.preco.setPlaceholderText(_("sem preço"))
        if cor is None:
            cor = tema.proxima_cor_pasta(p.cor for p in estado.trabalho.pastas)
        self.seletor_cor = SeletorCor(cor)

        self.form = QFormLayout()
        self.form.setHorizontalSpacing(16)
        self.form.setVerticalSpacing(10)
        self.form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.form.addRow(_("Nome"), self.campo_nome)
        self.form.addRow(_("Tamanho"), self.combo_tamanho)
        self.form.addRow(_("Papel (mm)"), papel)
        self.form.addRow(_("Preço por cópia (R$)"), self.preco)
        self.spin_copias = QSpinBox()
        self.spin_copias.setRange(1, 999)
        self.spin_copias.setValue(1)
        self.spin_copias.setToolTip(_("Cópias de cada foto que entrar na pasta"))
        self.form.addRow(_("Cópias"), self.spin_copias)
        self.form.addRow(_("Cor"), self.seletor_cor)
        self.raiz.addLayout(self.form)
        self.erro = QLabel()
        self.erro.setStyleSheet(f"color: {tema.PERIGO};")
        self.erro.setWordWrap(True)
        self.erro.hide()
        self.raiz.addWidget(self.erro)
        self.botoes = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.botao_ok = self.botoes.button(QDialogButtonBox.StandardButton.Ok)
        self.botao_ok.setText(texto_ok)
        self.botao_ok.setDefault(True)
        self.botoes.button(QDialogButtonBox.StandardButton.Cancel).setText(_("Cancelar"))
        self.botoes.accepted.connect(self.accept)
        self.botoes.rejected.connect(self.reject)
        self.raiz.addWidget(self.botoes)
        self.combo_tamanho.currentIndexChanged.connect(lambda _i: self._mostrar_papel())
        self._mostrar_papel()
        self.campo_nome.setFocus()
        self.campo_nome.selectAll()

    @staticmethod
    def _spin(valor: float) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(tamanhos.LIMITE_LADO_MIN_MM, tamanhos.LIMITE_LADO_MAX_MM)
        spin.setDecimals(1)
        spin.setValue(valor)
        return spin

    def tamanho(self) -> str:
        return self.combo_tamanho.currentData(Qt.ItemDataRole.UserRole) or self.estado.trabalho.tamanho_padrao

    def _mostrar_papel(self) -> None:
        personalizado = self.tamanho() == tamanhos.PERSONALIZADO
        self.form.setRowVisible(2, personalizado)
        self.form.setRowVisible(3, personalizado)
        self.adjustSize()

    def valores(self) -> dict:
        """Argumentos de ``Estado.criar_pasta``: nome, tamanho, cor, papel_mm e preco_centavos.

        ``ValueError`` (com a mensagem para a pessoa) se o nome estiver vazio ou o preço for inválido.
        """
        nome = self.campo_nome.text().strip()
        if not nome:
            raise ValueError(_("A pasta precisa de um nome."))
        tamanho = self.tamanho()
        papel, preco = None, None
        if tamanho == tamanhos.PERSONALIZADO:
            papel = (self.largura.value(), self.altura.value())
            tamanhos.papel_mm(tamanho, papel)   # valida os limites
            preco = precos.ler(self.preco.text())
        valores = {"nome": nome, "tamanho": tamanho, "cor": self.seletor_cor.cor(), "papel_mm": papel,
                   "preco_centavos": preco}
        if self.spin_copias.value() != 1:
            valores["copias"] = self.spin_copias.value()
        return valores

    def _validar(self) -> bool:
        return True

    def accept(self) -> None:
        if self._validar():
            try:
                self.valores()
            except ValueError as e:
                self.erro.setText(str(e))
                self.erro.show()
                return
        super().accept()


def dialogo_nova_pasta(estado: Estado, parent: QWidget | None = None,
                       fotos: list[Foto] | None = None) -> PastaDialog:
    """Diálogo "Nova pasta" já ligado: aceitar cria a pasta (``dialogo.pasta_criada``) e, com ``fotos``, põe essas
    fotos nela, marcadas — criar e pôr as fotos é um passo só do desfazer. Quem chama faz ``exec()`` (ou ``accept()``
    num teste)."""
    dialogo = PastaDialog(estado, _("Nova pasta de tamanho"), _("Criar pasta"), parent=parent)
    dialogo.pasta_criada = None
    if fotos:
        texto = (_("As {n} fotos escolhidas entram nela, marcadas para revelação no tamanho da pasta.").format(
            n=len(fotos)) if len(fotos) > 1 else _("A foto escolhida entra nela, marcada para revelação no tamanho "
                                                   "da pasta."))
    else:
        texto = _("Toda foto que entrar nela fica marcada para revelação no tamanho da pasta. Arraste fotos da "
                  "grade para a pasta ou use o menu de contexto.")
    dica = QLabel(texto)
    dica.setObjectName("Faint")
    dica.setWordWrap(True)
    dialogo.topo.addWidget(dica)

    def criar() -> None:
        with estado.lote(_("Nova pasta")):
            pasta = estado.criar_pasta(**dialogo.valores())
            if fotos:
                estado.adicionar_a_pasta(list(fotos), pasta)
        dialogo.pasta_criada = pasta

    dialogo.accepted.connect(criar)
    return dialogo


class PassoImportarPasta(PastaDialog):
    """Passo curto antes de importar uma pasta do disco: criar (ou não) uma pasta de tamanho com as fotos dela.

    ``chave_criar`` já vem marcada; nome = nome da pasta do disco, tamanho = o padrão, cor = a próxima da paleta.
    ``criar()`` diz se a pessoa quer a pasta; ``valores()`` dá os argumentos de ``Estado.criar_pasta``. Cancelar
    não importa nada.
    """

    def __init__(self, estado: Estado, pasta_disco: Path, n_fotos: int, parent: QWidget | None = None) -> None:
        pasta_disco = Path(pasta_disco)
        super().__init__(estado, _("Importar pasta"), _("Importar"), nome=pasta_disco.name or str(pasta_disco),
                         parent=parent)
        self.pasta_disco = pasta_disco
        self.n_fotos = n_fotos
        titulo = QLabel(pasta_disco.name or str(pasta_disco))
        titulo.setObjectName("PanelTitle")
        titulo.setToolTip(str(pasta_disco))
        quantas = QLabel(texto_fotos(n_fotos) if n_fotos else _("Nenhuma foto nesta pasta"))
        quantas.setObjectName("Muted")
        self.chave_criar = QCheckBox(_("Criar pasta de tamanho"))
        self.chave_criar.setChecked(True)
        dica = QLabel(_("As fotos já entram marcadas para revelação, no tamanho da pasta. Desmarcando, só importa."))
        dica.setObjectName("Faint")
        dica.setWordWrap(True)
        self.topo.addWidget(titulo)
        self.topo.addWidget(quantas)
        self.topo.addSpacing(6)
        self.topo.addWidget(self.chave_criar)
        self.topo.addWidget(dica)
        self.chave_criar.toggled.connect(self._ao_alternar)
        self._ao_alternar(True)

    def criar(self) -> bool:
        return self.chave_criar.isChecked()

    def _ao_alternar(self, sim: bool) -> None:
        for linha in range(self.form.rowCount()):
            for papel in (QFormLayout.ItemRole.LabelRole, QFormLayout.ItemRole.FieldRole):
                item = self.form.itemAt(linha, papel)
                if item is not None and item.widget() is not None:
                    item.widget().setEnabled(sim)
        self.erro.hide()

    def _validar(self) -> bool:
        return self.criar()


# ------------------------------------------------------------------------------------------------ linhas da seção
class LinhaPasta(QWidget):
    """Uma linha da seção: "Todas" (``pasta=None``) ou uma pasta (bolinha, nome, tamanho, nº de fotos e "⋯").

    Desenhada à mão com as cores do tema; aceita fotos arrastadas da grade (só as linhas de pasta).
    """

    def __init__(self, secao: SecaoPastas, pasta: Pasta | None) -> None:
        super().__init__()
        self.secao = secao
        self.pasta = pasta
        self.n_fotos = 0
        self.ativa = False
        self.alvo = False          # um arrasto de fotos está sobre ela
        self.setFixedHeight(ALTURA_LINHA)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.botao_menu: QToolButton | None = None
        if pasta is not None:
            self.setAcceptDrops(True)
            b = botao_plano("opcoes", _("Opções da pasta"), tamanho=16, cor=tema.APAGADO)
            b.setParent(self)
            b.setStyleSheet("padding: 0px;")
            b.setFixedSize(26, ALTURA_LINHA - 6)
            b.clicked.connect(lambda: self.secao.abrir_menu(self.pasta, b.mapToGlobal(QPoint(0, b.height()))))
            self.botao_menu = b

    # ------------------------------------------------------------ desenho
    def resizeEvent(self, evento) -> None:  # noqa: N802
        super().resizeEvent(evento)
        if self.botao_menu is not None:
            self.botao_menu.move(self.width() - self.botao_menu.width() - 4, 3)

    def textos(self, largura: int | None = None) -> tuple[str, str, str]:
        """(nome já cortado com "…", tamanho — vazio se não couber —, nº de fotos) para a largura dada."""
        largura = self.width() if largura is None else largura
        if self.pasta is None:
            nome, tam = _("Todas"), ""
        else:
            nome, tam = self.pasta.nome, nome_tamanho(self.pasta.tamanho, self.pasta.papel_mm)
        n = str(self.n_fotos)
        f_nome = tema.fonte(9, QFont.Weight.DemiBold if self.ativa else QFont.Weight.Normal)
        f_info = tema.fonte(8.5)
        m_nome, m_info = QFontMetrics(f_nome), QFontMetrics(f_info)
        direita = self._direita(largura)
        livre = direita - 30 - m_info.horizontalAdvance(n) - 10
        if tam and livre - m_info.horizontalAdvance(tam) - 10 < 44:
            tam = ""
        if tam:
            livre -= m_info.horizontalAdvance(tam) + 10
        return m_nome.elidedText(nome, Qt.TextElideMode.ElideRight, max(livre, 0)), tam, n

    def _direita(self, largura: int) -> int:
        return largura - (32 if self.botao_menu is not None else 10)

    def paintEvent(self, _evento) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(4, 1, -4, -1)
        cor = QColor(tema.cor_pasta(self.pasta.cor)) if self.pasta is not None else QColor(tema.APAGADO)
        if self.alvo:
            fundo = QColor(cor)
            fundo.setAlpha(46)
            p.setBrush(fundo)
            p.setPen(QPen(cor, 1.4))
            p.drawRoundedRect(r.adjusted(0.7, 0.7, -0.7, -0.7), 7, 7)
        elif self.ativa:
            fundo = QColor(tema.DESTAQUE)
            fundo.setAlpha(34)
            p.setBrush(fundo)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(r, 7, 7)
        elif self.underMouse():
            p.setBrush(QColor(tema.PAINEL2))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(r, 7, 7)
        meio = self.height() / 2
        if self.pasta is None:
            icone = icones.icone("grade", tema.TEXTO if self.ativa else tema.APAGADO, 14)
            icone.paint(p, QRect(13, int(meio) - 7, 14, 14))
        else:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(cor)
            p.drawEllipse(QRectF(15, meio - LADO_BOLINHA / 2, LADO_BOLINHA, LADO_BOLINHA))
        nome, tam, n = self.textos()
        direita = self._direita(self.width())
        f_info = tema.fonte(8.5)
        p.setFont(f_info)
        p.setPen(QColor(tema.TEXTO if self.ativa else tema.APAGADO))
        caixa_n = QRect(0, 0, direita, self.height())
        p.drawText(caixa_n, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, n)
        largura_n = p.fontMetrics().horizontalAdvance(n)
        if tam:
            p.setPen(QColor(tema.FRACO))
            p.drawText(QRect(0, 0, direita - largura_n - 10, self.height()),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, tam)
        p.setFont(tema.fonte(9, QFont.Weight.DemiBold if self.ativa else QFont.Weight.Normal))
        p.setPen(QColor(tema.TEXTO))
        p.drawText(QRect(32, 0, max(direita - 32, 0), self.height()),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, nome)
        p.end()

    # ------------------------------------------------------------ mouse
    def mousePressEvent(self, evento) -> None:  # noqa: N802
        if evento.button() == Qt.MouseButton.LeftButton:
            self.secao.clicar(self.pasta)
            evento.accept()
            return
        super().mousePressEvent(evento)

    def mouseDoubleClickEvent(self, evento) -> None:  # noqa: N802
        if self.pasta is not None and evento.button() == Qt.MouseButton.LeftButton:
            self.secao.renomear(self.pasta)
            return
        super().mouseDoubleClickEvent(evento)

    def contextMenuEvent(self, evento) -> None:  # noqa: N802
        if self.pasta is not None:
            self.secao.abrir_menu(self.pasta, evento.globalPos())

    # ------------------------------------------------------------ arrastar fotos para a pasta
    def dragEnterEvent(self, evento) -> None:  # noqa: N802
        if self.pasta is not None and ids_do_mime(evento.mimeData()):
            evento.setDropAction(Qt.DropAction.CopyAction)
            evento.accept()
            self.alvo = True
            self.update()
        else:
            evento.ignore()

    def dragMoveEvent(self, evento) -> None:  # noqa: N802
        if self.alvo:
            evento.setDropAction(Qt.DropAction.CopyAction)
            evento.accept()

    def dragLeaveEvent(self, _evento) -> None:  # noqa: N802
        self.alvo = False
        self.update()

    def dropEvent(self, evento) -> None:  # noqa: N802
        self.alvo = False
        self.update()
        if self.pasta is None:
            evento.ignore()
            return
        evento.setDropAction(Qt.DropAction.CopyAction)
        evento.accept()
        self.secao.soltar(self.pasta, evento.mimeData())


# ------------------------------------------------------------------------------------------------ seção
class SecaoPastas(QWidget):
    """Faixa "Pastas" no topo da grade: filtro por pasta, nova pasta, menu da pasta e alvo de arrastar fotos.

    ``pasta_filtrada`` é o id da pasta escolhida (None = todas); ``filtro_mudou`` avisa a janela, que repassa à grade
    (``Grade.definir_pasta``). A pasta escolhida que deixa de existir (apagada, desfeita, outro trabalho) volta o
    filtro a "Todas". O estado recolhido é lembrado em ``grade/pastas_recolhidas``.
    """

    filtro_mudou = Signal(object)   # id da pasta | None

    def __init__(self, estado: Estado, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.estado = estado
        self.pasta_filtrada: str | None = None
        self.linhas: list[LinhaPasta] = []
        self.setObjectName("SecaoPastas")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Maximum)
        self.setAcceptDrops(True)   # um arrasto da grade sobre a seção recolhida a abre
        # perguntas modais (os testes trocam): devolvem o valor ou None/False se a pessoa cancelar
        self.pedir_nome = self._pedir_nome
        self.confirmar_apagar = self._confirmar_apagar
        self.pedir_personalizado = self._pedir_personalizado

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(6, 6, 6, 6)
        raiz.setSpacing(2)
        self.cabecalho = QWidget()
        self.cabecalho.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cabecalho.setToolTip(_("Recolher ou abrir as pastas de tamanho"))
        cab = QHBoxLayout(self.cabecalho)
        cab.setContentsMargins(6, 0, 0, 0)
        cab.setSpacing(6)
        self._seta = QLabel()
        self._seta.setFixedSize(14, 14)
        cab.addWidget(self._seta)
        self.titulo = QLabel(_("PASTAS"))
        self.titulo.setObjectName("SecaoTitulo")
        cab.addWidget(self.titulo)
        self.rotulo_filtro = QLabel()
        self.rotulo_filtro.setObjectName("Muted")
        self.rotulo_filtro.setMinimumWidth(0)
        self.rotulo_filtro.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        cab.addWidget(self.rotulo_filtro, 1)
        self.botao_nova = botao_plano("mais", _("Criar uma pasta de tamanho"), _("Nova pasta"), tamanho=14,
                                      cor=tema.APAGADO)
        self.botao_nova.setObjectName("Flat")
        self.botao_nova.setStyleSheet("padding: 3px 8px;")
        self.botao_nova.clicked.connect(lambda: self.nova_pasta())
        cab.addWidget(self.botao_nova)
        self.cabecalho.mousePressEvent = lambda _e: self.recolher(not self.recolhida)
        raiz.addWidget(self.cabecalho)

        self.rolagem = QScrollArea()
        self.rolagem.setWidgetResizable(True)
        self.rolagem.setFrameShape(QScrollArea.Shape.NoFrame)
        self.rolagem.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.rolagem.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        conteudo = QWidget()
        self.layout_linhas = QVBoxLayout(conteudo)
        self.layout_linhas.setContentsMargins(0, 2, 0, 0)
        self.layout_linhas.setSpacing(ESPACO_LINHAS)
        self.layout_linhas.addStretch(1)
        self.rolagem.setWidget(conteudo)
        raiz.addWidget(self.rolagem)

        self.recolhida = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(ATRASO_CONTAGEM_MS)
        self._timer.timeout.connect(self.atualizar)
        estado.pastas_mudaram.connect(self.atualizar)
        estado.fotos_mudaram.connect(self.atualizar)
        estado.foto_mudou.connect(lambda _id: self._timer.start())
        self.recolher(_recolhida_salva(), lembrar=False)
        self.atualizar()

    # ------------------------------------------------------------ consulta
    def linha_da_pasta(self, pasta: Pasta | str | None) -> LinhaPasta | None:
        """A linha de uma pasta (ou de "Todas", com None)."""
        pid = pasta.id if isinstance(pasta, Pasta) else pasta
        return next((l for l in self.linhas if (l.pasta.id if l.pasta else None) == pid), None)

    # ------------------------------------------------------------ montagem
    def atualizar(self) -> None:
        """Refaz as linhas (se a lista de pastas mudou) e as contagens; a pasta filtrada que sumiu volta a "Todas"."""
        self._timer.stop()
        pastas = list(self.estado.trabalho.pastas)
        if self.pasta_filtrada is not None and self.estado.pasta_por_id(self.pasta_filtrada) is None:
            self.filtrar(None)
        ids = [None] + [p.id for p in pastas]
        if [l.pasta.id if l.pasta else None for l in self.linhas] != ids:
            for linha in self.linhas:
                self.layout_linhas.removeWidget(linha)
                linha.hide()
                linha.deleteLater()
            self.linhas = [LinhaPasta(self, None)] + [LinhaPasta(self, p) for p in pastas]
            for i, linha in enumerate(self.linhas):
                self.layout_linhas.insertWidget(i, linha)
        else:
            for linha, pasta in zip(self.linhas[1:], pastas):
                linha.pasta = pasta   # o desfazer troca os objetos Pasta (mesmos ids)
        contagem = contar_fotos(self.estado)
        for linha in self.linhas:
            linha.n_fotos = len(self.estado.trabalho.fotos) if linha.pasta is None else contagem.get(linha.pasta.id, 0)
            linha.ativa = (linha.pasta.id if linha.pasta else None) == self.pasta_filtrada
            if linha.pasta is not None:
                linha.setToolTip(_("{nome} · {tamanho} · {fotos}\nClique para mostrar só as fotos desta pasta; "
                                   "arraste fotos para cá para pô-las nela.").format(
                    nome=linha.pasta.nome, tamanho=nome_tamanho(linha.pasta.tamanho, linha.pasta.papel_mm),
                    fotos=texto_fotos(linha.n_fotos)))
            else:
                linha.setToolTip(_("Sem filtro de pasta: todas as fotos do trabalho"))
            linha.update()
        n = len(pastas)
        visiveis = min(len(self.linhas), MAX_LINHAS)
        altura = visiveis * (ALTURA_LINHA + ESPACO_LINHAS) + 2
        if len(self.linhas) > MAX_LINHAS:
            altura += ALTURA_LINHA // 2
        self.rolagem.setFixedHeight(altura)
        self.rolagem.setVisible(not self.recolhida and n > 0)
        self._atualizar_cabecalho()

    def _atualizar_cabecalho(self) -> None:
        pasta = self.estado.pasta_por_id(self.pasta_filtrada)
        if pasta is not None and (self.recolhida or not self.estado.trabalho.pastas):
            self.rotulo_filtro.setText("· " + pasta.nome)
        elif self.recolhida and self.estado.trabalho.pastas:
            self.rotulo_filtro.setText(str(len(self.estado.trabalho.pastas)))
        else:
            self.rotulo_filtro.setText("")
        pm = icones.icone("chevron", tema.APAGADO, 14).pixmap(14, 14)
        if self.recolhida:
            pm = pm.transformed(QTransform().rotate(-90), Qt.TransformationMode.SmoothTransformation)
        self._seta.setPixmap(pm)
        self._seta.setVisible(bool(self.estado.trabalho.pastas))

    def recolher(self, sim: bool, lembrar: bool = True) -> None:
        """Recolhe (só o cabeçalho, com a pasta filtrada ao lado do título) ou abre a lista de pastas."""
        self.recolhida = bool(sim)
        if lembrar:
            prefs.settings().setValue(CHAVE_RECOLHIDA, self.recolhida)
        self.rolagem.setVisible(not self.recolhida and bool(self.estado.trabalho.pastas))
        self._atualizar_cabecalho()

    # ------------------------------------------------------------ filtro
    def clicar(self, pasta: Pasta | None) -> None:
        """Clique numa linha: filtra por ela; na pasta já escolhida (ou em "Todas"), volta a todas."""
        pid = pasta.id if pasta is not None else None
        self.filtrar(None if pid == self.pasta_filtrada else pid)

    def filtrar(self, pasta_id: str | None) -> None:
        """Mostra na grade só as fotos da pasta (None: todas). Avisa por ``filtro_mudou`` quando muda."""
        if pasta_id is not None and self.estado.pasta_por_id(pasta_id) is None:
            pasta_id = None
        if pasta_id == self.pasta_filtrada:
            return
        self.pasta_filtrada = pasta_id
        for linha in self.linhas:
            linha.ativa = (linha.pasta.id if linha.pasta else None) == pasta_id
            linha.update()
        self._atualizar_cabecalho()
        self.filtro_mudou.emit(pasta_id)

    # ------------------------------------------------------------ nova pasta
    def criar_dialogo_nova_pasta(self, fotos: list[Foto] | None = None) -> PastaDialog:
        return dialogo_nova_pasta(self.estado, self.window(), fotos)

    def nova_pasta(self, fotos: list[Foto] | None = None) -> Pasta | None:
        """Pede nome, tamanho e cor (modal) e cria a pasta; devolve a pasta criada (None se cancelou)."""
        dialogo = self.criar_dialogo_nova_pasta(fotos)
        dialogo.exec()
        pasta = dialogo.pasta_criada
        dialogo.deleteLater()
        if pasta is not None and self.recolhida:
            self.recolher(False)
        return pasta

    # ------------------------------------------------------------ arrastar
    def soltar(self, pasta: Pasta, mime: QMimeData) -> list[Foto]:
        """Fotos arrastadas da grade soltas na pasta: entram nela, marcadas (um passo do desfazer)."""
        fotos = fotos_do_mime(self.estado, mime)
        atual = self.estado.pasta_por_id(pasta.id)
        if not fotos or atual is None:
            return []
        return self.estado.adicionar_a_pasta(fotos, atual)

    def dragEnterEvent(self, evento) -> None:  # noqa: N802
        if ids_do_mime(evento.mimeData()) and self.estado.trabalho.pastas:
            if self.recolhida:
                self.recolher(False, lembrar=False)
            evento.accept()
        else:
            evento.ignore()

    def dropEvent(self, evento) -> None:  # noqa: N802
        evento.ignore()   # só as linhas das pastas recebem fotos

    # ------------------------------------------------------------ menu da pasta
    def abrir_menu(self, pasta: Pasta, posicao: QPoint) -> None:
        menu = self.menu_pasta(pasta)
        menu.exec(posicao)
        menu.deleteLater()

    def menu_pasta(self, pasta: Pasta) -> QMenu:
        """Menu da pasta, sem abrir (quem chama faz ``exec``). Itens por ``objectName``: ``renomear``, ``cor``
        (``cor_<chave>``), ``tamanho_pasta`` (ids da tabela e ``personalizado``), ``copias_pasta``
        (``copias_pasta_<n>``), ``subir``, ``descer`` e ``apagar``."""
        menu = QMenu(self)
        menu.setObjectName("menu_pasta")
        self._item(menu, "renomear", _("Renomear…"), lambda: self.renomear(pasta))

        cores = menu.addMenu(_("Cor"))
        cores.menuAction().setObjectName("cor")
        cores.setIcon(icones.bolinha(tema.cor_pasta(pasta.cor), 14))
        for chave in tema.CORES_PASTA:
            acao = self._item(cores, f"cor_{chave}", tema.nome_cor_pasta(chave),
                              lambda _c=False, k=chave: self.alterar(pasta, cor=k))
            acao.setCheckable(True)
            acao.setChecked(chave == pasta.cor)
            acao.setIcon(icones.bolinha(tema.cor_pasta(chave), 14, anel=chave == pasta.cor))

        tamanho = menu.addMenu(_("Tamanho"))
        tamanho.menuAction().setObjectName("tamanho_pasta")
        for grupo in tamanhos.GRUPOS:
            tamanho.addSection(_(NOMES_GRUPOS[grupo]))
            for t in tamanhos.TAMANHOS:
                if t.grupo == grupo:
                    acao = self._item(tamanho, t.id, _(t.nome),
                                      lambda _c=False, i=t.id: self.alterar(pasta, tamanho=i))
                    acao.setCheckable(True)
                    acao.setChecked(pasta.tamanho == t.id)
        tamanho.addSeparator()
        texto = (_("Personalizado {medida}…").format(medida=nome_tamanho(pasta.tamanho, pasta.papel_mm))
                 if pasta.tamanho == tamanhos.PERSONALIZADO else _("Personalizado…"))
        acao = self._item(tamanho, tamanhos.PERSONALIZADO, texto, lambda: self.mudar_personalizado(pasta))
        acao.setCheckable(True)
        acao.setChecked(pasta.tamanho == tamanhos.PERSONALIZADO)

        copias = menu.addMenu(_("Cópias padrão"))
        copias.menuAction().setObjectName("copias_pasta")
        for c in COPIAS_PASTA:
            texto = _("1 cópia") if c == 1 else _("{n} cópias").format(n=c)
            acao = self._item(copias, f"copias_pasta_{c}", texto, lambda _c=False, c=c: self.alterar(pasta, copias=c))
            acao.setCheckable(True)
            acao.setChecked(pasta.copias == c)

        menu.addSeparator()
        ids = [p.id for p in self.estado.trabalho.pastas]
        indice = ids.index(pasta.id) if pasta.id in ids else -1
        subir = self._item(menu, "subir", _("Mover para cima"), lambda: self.mover(pasta, -1))
        subir.setEnabled(indice > 0)
        descer = self._item(menu, "descer", _("Mover para baixo"), lambda: self.mover(pasta, +1))
        descer.setEnabled(0 <= indice < len(ids) - 1)
        menu.addSeparator()
        apagar = self._item(menu, "apagar", _("Apagar a pasta…"), lambda: self.apagar(pasta))
        apagar.setIcon(icones.icone("lixeira", tema.PERIGO, 16))
        return menu

    @staticmethod
    def _item(menu: QMenu, nome: str, texto: str, slot) -> QAction:
        acao = menu.addAction(texto)
        acao.setObjectName(nome)
        acao.triggered.connect(slot)
        return acao

    # ------------------------------------------------------------ ações do menu
    # As ações procuram a pasta pelo id na lista de agora: um desfazer troca os objetos ``Pasta`` (mesmos ids), e a
    # API do ``Estado`` mexe no objeto que recebe.
    def _atual(self, pasta: Pasta) -> Pasta | None:
        return self.estado.pasta_por_id(pasta.id)

    def alterar(self, pasta: Pasta, **campos) -> None:
        """Muda campos da pasta pela API do ``Estado`` (um passo do desfazer); ignora a pasta que já não existe."""
        atual = self._atual(pasta)
        if atual is not None:
            self.estado.alterar_pasta(atual, **campos)

    def mover(self, pasta: Pasta, passo: int) -> None:
        """Sobe (``passo < 0``) ou desce a pasta na lista (a ordem da tela)."""
        atual = self._atual(pasta)
        if atual is not None:
            self.estado.mover_pasta(atual, self.estado.trabalho.pastas.index(atual) + passo)

    def renomear(self, pasta: Pasta) -> None:
        nome = self.pedir_nome(pasta)
        if nome is not None and nome.strip():
            self.alterar(pasta, nome=nome.strip())

    def mudar_personalizado(self, pasta: Pasta) -> None:
        valores = self.pedir_personalizado(pasta)
        if valores is not None:
            largura, altura, preco = valores
            self.alterar(pasta, tamanho=tamanhos.PERSONALIZADO, papel_mm=(largura, altura), preco_centavos=preco)

    def apagar(self, pasta: Pasta) -> None:
        """Apaga a pasta depois de confirmar: as fotos continuam no trabalho, só perdem a impressão dela."""
        atual = self._atual(pasta)
        if atual is None:
            return
        fotos = self.estado.fotos_da_pasta(atual)
        resposta = self.confirmar_apagar(atual, len(fotos))
        if not resposta:
            return
        with self.estado.lote(_("apagar a pasta “{nome}”").format(nome=atual.nome)):
            self.estado.apagar_pasta(atual)
            if resposta == REMOVER_FOTOS and fotos:
                self.estado.remover(fotos)

    # ------------------------------------------------------------ perguntas modais (padrão)
    def _pedir_nome(self, pasta: Pasta) -> str | None:
        nome, ok = QInputDialog.getText(self.window(), _("Renomear a pasta"), _("Nome da pasta"), text=pasta.nome)
        return nome if ok else None

    def _confirmar_apagar(self, pasta: Pasta, n_fotos: int) -> bool | str:
        """Verdadeiro para apagar só a pasta; ``REMOVER_FOTOS`` se a pessoa marcou "remover as fotos também"."""
        caixa = QMessageBox(self.window())
        caixa.setIcon(QMessageBox.Icon.Question)
        caixa.setWindowTitle(_("Apagar a pasta"))
        caixa.setText(_("Apagar a pasta “{nome}”?").format(nome=pasta.nome))
        if n_fotos:
            caixa.setInformativeText(_("{fotos} continuam no trabalho; só deixam de ser reveladas no tamanho desta "
                                       "pasta. Dá para desfazer (Ctrl+Z).").format(fotos=texto_fotos(n_fotos)))
        remover = None
        if n_fotos:
            remover = QCheckBox(_("Remover também as fotos do trabalho (os arquivos não são apagados)"))
            remover.setChecked(False)
            caixa.setCheckBox(remover)
        apagar = caixa.addButton(_("Apagar"), QMessageBox.ButtonRole.DestructiveRole)
        caixa.addButton(_("Cancelar"), QMessageBox.ButtonRole.RejectRole)
        caixa.exec()
        if caixa.clickedButton() is not apagar:
            return False
        return REMOVER_FOTOS if remover is not None and remover.isChecked() else True

    def _pedir_personalizado(self, pasta: Pasta) -> tuple[float, float, int | None] | None:
        largura, altura = pasta.papel_mm or PAPEL_PADRAO_MM
        dialogo = PersonalizadoDialog(largura, altura, pasta.preco_centavos, self.window())
        aceito = dialogo.exec() == QDialog.DialogCode.Accepted
        return dialogo.valores() if aceito else None


REMOVER_FOTOS = "remover_fotos"   # resposta de confirmar_apagar: apagar a pasta e tirar as fotos dela do trabalho


def _recolhida_salva() -> bool:
    valor = prefs.settings().value(CHAVE_RECOLHIDA, False)
    return valor in (True, "true", "1", 1)
