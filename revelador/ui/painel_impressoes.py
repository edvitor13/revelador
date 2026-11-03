"""Seção "Impressões" do painel lateral (um ``Card``) e o seletor de tamanho padrão da barra superior.

Tudo conversa só pelo ``Estado``: selecionar a foto atual, listar/alterar/remover as impressões dela e avisar com
``estado.alterar(foto, pedido=True)``. Trocar tamanho, orientação ou papel refaz o recorte automático ou reencaixa o
manual (que continua "manual"). Os métodos públicos do painel (``trocar_tamanho`` etc.) são o que os controles
chamam, então dá para testar sem clicar.

Impressão de uma pasta de tamanho (#32): a linha mostra a bolinha da cor e o nome da pasta; o tamanho é o da pasta
(o combo fica desligado; muda-se pelo menu da pasta, para todas as fotos dela) e remover a impressão é tirar a foto
da pasta (``estado.tirar_da_pasta``), mesmo que seja a última impressão (a foto deixa de estar marcada).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QFrame, QGridLayout,
                               QHBoxLayout, QLabel, QLineEdit, QSpinBox, QToolButton, QVBoxLayout, QWidget)

from .. import enquadramento, precos, tamanhos
from ..i18n import N_, _
from ..projeto import Foto, Impressao
from . import icones, prefs, tema
from .componentes import Card, Segmented, ToggleSwitch, botao_plano
from .estado import Estado

NOMES_GRUPOS = {
    tamanhos.COMUM: N_("Comuns"),
    tamanhos.AMPLIACAO: N_("Ampliações"),
    tamanhos.QUADRADO: N_("Quadrados"),
}
ORIENTACOES_FIXAS = (("retrato", N_("Retrato")), ("paisagem", N_("Paisagem")))   # "auto" é só o padrão do modelo
LIMITE_COPIAS = (1, 999)
MODOS = (("preencher", N_("Preencher")), ("caber", N_("Caber")))
NOMES_QUALIDADE = {"boa": N_("Boa"), "aceitavel": N_("Aceitável"), "baixa": N_("Baixa")}
COR_QUALIDADE = {"boa": tema.OK, "aceitavel": tema.AVISO, "baixa": tema.PERIGO}   # cores de estado


# ------------------------------------------------------------------------------------------------ combos e contas
def preencher_combo_tamanhos(combo: QComboBox, personalizado: bool = True) -> None:
    """Combo de tamanhos agrupado (comuns, ampliações, quadrados e, se pedido, "Personalizado…"); dado = id."""
    modelo = QStandardItemModel(combo)
    for grupo in tamanhos.GRUPOS:
        cabecalho = QStandardItem(_(NOMES_GRUPOS[grupo]))
        cabecalho.setFlags(Qt.ItemFlag.NoItemFlags)
        fonte = cabecalho.font()
        fonte.setBold(True)
        cabecalho.setFont(fonte)
        modelo.appendRow(cabecalho)
        for t in tamanhos.TAMANHOS:
            if t.grupo == grupo:
                item = QStandardItem(_(t.nome))
                item.setData(t.id, Qt.ItemDataRole.UserRole)
                modelo.appendRow(item)
    if personalizado:
        item = QStandardItem(_("Personalizado…"))
        item.setData(tamanhos.PERSONALIZADO, Qt.ItemDataRole.UserRole)
        modelo.appendRow(item)
    combo.setModel(modelo)


def escolher_no_combo(combo: QComboBox, tamanho_id: str) -> None:
    indice = combo.findData(tamanho_id, Qt.ItemDataRole.UserRole)
    if indice >= 0:
        combo.setCurrentIndex(indice)


def _botao_copia(texto: str, dica: str) -> QToolButton:
    """Botão − ou + ao lado da quantidade: texto grande e bordado, para ser fácil de acertar."""
    b = QToolButton()
    b.setObjectName("Flat")            # o padrão do tema tem margens largas demais para um caractere
    b.setText(texto)
    b.setToolTip(dica)
    b.setFixedSize(34, 30)
    fonte = b.font()
    fonte.setPointSizeF(fonte.pointSizeF() + 3)
    fonte.setBold(True)
    b.setFont(fonte)
    b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


def _dim_girada(estado: Estado, foto: Foto, imp: Impressao) -> tuple[int, int] | None:
    """Largura e altura da imagem já girada pelo giro da impressão (None sem metadados)."""
    info = estado.info.get(foto.id)
    if info is None:
        return None
    if int(imp.recorte.giro) % 2:
        return info.altura, info.largura
    return info.largura, info.altura


def _orientacao_e_proporcao(imp: Impressao, w: int, h: int) -> tuple[str, float]:
    orient = tamanhos.orientacao_efetiva(imp.orientacao, w, h)
    return orient, tamanhos.proporcao(imp.tamanho, orient, imp.papel_mm)


def refazer_enquadramento(estado: Estado, foto: Foto, imp: Impressao) -> None:
    """Depois de trocar tamanho/orientação/papel: refaz o recorte automático ou reencaixa o manual; avisa o Estado."""
    if imp.recorte.origem != "manual":
        estado.refazer_recortes_auto(foto)   # sem metadados não faz nada; o Estado refaz quando chegarem
    else:
        dim = _dim_girada(estado, foto, imp)
        if dim is not None:
            _orient, prop = _orientacao_e_proporcao(imp, *dim)
            imp.recorte = enquadramento.reencaixar(imp.recorte, dim[0], dim[1], prop)
    estado.alterar(foto, pedido=True)


def qualidade_impressao(estado: Estado, foto: Foto, imp: Impressao) -> tuple[float, str] | None:
    """(dpi efetivo, "boa" | "aceitavel" | "baixa") da impressão, ou None sem metadados."""
    dim = _dim_girada(estado, foto, imp)
    if dim is None:
        return None
    orient, prop = _orientacao_e_proporcao(imp, *dim)
    largura = enquadramento.retangulo(imp.recorte, dim[0], dim[1], prop).w
    dpi = tamanhos.resolucao_efetiva(round(largura), imp.tamanho, orient, imp.papel_mm)
    return dpi, tamanhos.qualidade(dpi)


def texto_qualidade(resultado: tuple[float, str] | None) -> str:
    if resultado is None:
        return ""
    dpi, qual = resultado
    nome = _(NOMES_QUALIDADE[qual])
    return f"{nome} ({round(dpi)} dpi)" if qual == "baixa" else nome


# ------------------------------------------------------------------------------------------------ personalizado
class PersonalizadoDialog(QDialog):
    """Tamanho personalizado: lados em mm (20 a 1000) e preço por cópia opcional (reais)."""

    def __init__(self, largura_mm: float = 100.0, altura_mm: float = 150.0, preco_centavos: int | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("Tamanho personalizado"))
        form = QFormLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)
        self.largura = self._spin(largura_mm)
        self.altura = self._spin(altura_mm)
        self.preco = QLineEdit()
        self.preco.setPlaceholderText(_("sem preço"))
        if preco_centavos is not None:
            self.preco.setText(precos.formatar(preco_centavos).removeprefix("R$ "))
        self.erro = QLabel()
        self.erro.setStyleSheet(f"color: {tema.PERIGO};")
        self.erro.hide()
        form.addRow(_("Largura (mm)"), self.largura)
        form.addRow(_("Altura (mm)"), self.altura)
        form.addRow(_("Preço por cópia (R$)"), self.preco)
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(22, 20, 22, 18)
        raiz.setSpacing(14)
        raiz.addLayout(form)
        raiz.addWidget(self.erro)
        botoes = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        botoes.button(QDialogButtonBox.StandardButton.Ok).setText(_("Aplicar"))
        botoes.button(QDialogButtonBox.StandardButton.Cancel).setText(_("Cancelar"))
        botoes.accepted.connect(self.accept)
        botoes.rejected.connect(self.reject)
        raiz.addWidget(botoes)

    @staticmethod
    def _spin(valor: float) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(tamanhos.LIMITE_LADO_MIN_MM, tamanhos.LIMITE_LADO_MAX_MM)
        spin.setDecimals(1)
        spin.setValue(valor)
        return spin

    def valores(self) -> tuple[float, float, int | None]:
        """(largura, altura, preço em centavos ou None). ``ValueError`` se o preço for inválido."""
        return self.largura.value(), self.altura.value(), precos.ler(self.preco.text())

    def accept(self) -> None:
        try:
            self.valores()
        except ValueError as e:
            self.erro.setText(str(e))
            self.erro.show()
            return
        super().accept()


# ------------------------------------------------------------------------------------------------ linha de impressão
class LinhaImpressao(QFrame):
    """Controles de UMA impressão: tamanho, cópias, orientação, modo, qualidade e remover."""

    def __init__(self, painel: PainelImpressoes, indice: int) -> None:
        super().__init__()
        self.painel = painel
        self.indice = indice
        self.qualidade: str | None = None
        self.pasta = None   # a Pasta de tamanho da impressão (None: avulsa)
        self.setObjectName("LinhaImp")
        self.combo_tamanho = QComboBox()
        preencher_combo_tamanhos(self.combo_tamanho)
        # o valor das cópias fica neste spin (fora do layout: o tema apertava o campo e o número não aparecia);
        # o que a pessoa vê é o rótulo "× n", atualizado em atualizar()
        self.spin_copias = QSpinBox()
        self.spin_copias.setRange(*LIMITE_COPIAS)
        self.spin_copias.setPrefix("× ")
        self.spin_copias.setToolTip(_("Cópias"))
        self.rotulo_copias = QLabel()
        self.rotulo_copias.setObjectName("Value")
        self.rotulo_copias.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.rotulo_copias.setToolTip(_("Cópias"))
        self.rotulo_copias.setMinimumWidth(56)
        self.botao_menos = _botao_copia("−", _("Uma cópia a menos (−)"))
        self.botao_mais = _botao_copia("+", _("Uma cópia a mais (+)"))
        caixa_copias = QWidget()
        copias = QHBoxLayout(caixa_copias)
        copias.setContentsMargins(0, 0, 0, 0)
        copias.setSpacing(4)
        for w in (self.botao_menos, self.rotulo_copias, self.botao_mais):
            copias.addWidget(w)
        self.seg_orientacao = Segmented([(valor, _(nome), _("Papel em pé") if valor == "retrato" else _("Papel deitado"))
                                         for valor, nome in ORIENTACOES_FIXAS])
        self.rotulo_auto = QLabel(_("auto"))
        self.rotulo_auto.setObjectName("Faint")
        self.rotulo_auto.setToolTip(_("escolhida pela forma da foto"))
        self.botao_voltar = botao_plano("reset", _("Voltar à orientação automática (pela forma da foto)"),
                                        _("Voltar ao automático"))
        self.botao_girar = botao_plano("girar_direita", _("Girar o papel: retrato ↔ paisagem"), _("Girar papel"))
        self.combo_modo = QComboBox()
        for valor, nome in MODOS:
            self.combo_modo.addItem(_(nome), valor)
        self.ponto_qualidade = QLabel()
        self.ponto_qualidade.setFixedSize(8, 8)
        self.rotulo_qualidade = QLabel()
        self.botao_remover = botao_plano("lixeira", _("Remover este tamanho"), tamanho=16, cor=tema.APAGADO)
        # pasta de tamanho (#32): bolinha da cor e nome, só nas impressões de pasta
        self.caixa_pasta = QWidget()
        linha_pasta = QHBoxLayout(self.caixa_pasta)
        linha_pasta.setContentsMargins(2, 0, 0, 0)
        linha_pasta.setSpacing(7)
        self.bolinha_pasta = QLabel()
        self.bolinha_pasta.setFixedSize(10, 10)
        self.rotulo_pasta = QLabel()
        self.rotulo_pasta.setObjectName("Muted")
        self.rotulo_pasta.setMinimumWidth(0)
        linha_pasta.addWidget(self.bolinha_pasta)
        linha_pasta.addWidget(self.rotulo_pasta, 1)
        self.caixa_pasta.hide()
        acao_orientacao = QHBoxLayout()
        acao_orientacao.setSpacing(6)
        acao_orientacao.addWidget(self.rotulo_auto)
        acao_orientacao.addStretch(1)
        acao_orientacao.addWidget(self.botao_girar)
        grade = QGridLayout(self)
        grade.setContentsMargins(10, 10, 10, 10)
        grade.setHorizontalSpacing(8)
        grade.setVerticalSpacing(8)
        grade.addWidget(self.caixa_pasta, 0, 0, 1, 3)
        grade.addWidget(self.combo_tamanho, 1, 0, 1, 2)
        grade.addWidget(self.botao_remover, 1, 2)
        grade.addWidget(self.seg_orientacao, 2, 0, 1, 3)
        grade.addWidget(caixa_copias, 3, 0)
        grade.addWidget(self.combo_modo, 3, 1, 1, 2)
        qualidade = QHBoxLayout()
        qualidade.setSpacing(7)
        qualidade.addWidget(self.ponto_qualidade)
        qualidade.addWidget(self.rotulo_qualidade, 1)
        grade.addLayout(qualidade, 4, 0, 1, 3)
        grade.addLayout(acao_orientacao, 5, 0, 1, 3)
        grade.addWidget(self.botao_voltar, 6, 0, 1, 3, Qt.AlignmentFlag.AlignLeft)
        grade.setColumnStretch(1, 1)
        self.combo_tamanho.currentIndexChanged.connect(self._ao_tamanho)
        self.botao_menos.clicked.connect(lambda: self.spin_copias.setValue(self.spin_copias.value() - 1))
        self.botao_mais.clicked.connect(lambda: self.spin_copias.setValue(self.spin_copias.value() + 1))
        self.spin_copias.valueChanged.connect(lambda v: self._agir(self.painel.definir_copias, v))
        self.seg_orientacao.mudou.connect(lambda chave: self._agir(self.painel.definir_orientacao, chave))
        self.botao_voltar.clicked.connect(lambda: self._agir(self.painel.definir_orientacao, "auto"))
        self.botao_girar.clicked.connect(lambda: self._agir(lambda i, _v: self.painel.girar_papel(i), None))
        self.combo_modo.currentIndexChanged.connect(
            lambda _i: self._agir(self.painel.definir_modo, self.combo_modo.currentData()))
        self.botao_remover.clicked.connect(lambda: self.painel.remover_impressao(self.indice))

    def _agir(self, funcao, valor) -> None:
        self.painel.estado.definir_impressao(self.indice)
        funcao(self.indice, valor)

    def _ao_tamanho(self, _i: int) -> None:
        tamanho_id = self.combo_tamanho.currentData(Qt.ItemDataRole.UserRole)
        if tamanho_id is None:
            return
        self.painel.estado.definir_impressao(self.indice)
        if tamanho_id == tamanhos.PERSONALIZADO:
            self.painel.pedir_personalizado(self.indice)
        else:
            self.painel.trocar_tamanho(self.indice, tamanho_id)

    def mousePressEvent(self, evento) -> None:  # noqa: N802 - nome do Qt
        self.painel.estado.definir_impressao(self.indice)
        super().mousePressEvent(evento)

    def atualizar(self, foto: Foto, imp: Impressao, ativa: bool) -> None:
        """Põe nos controles os valores do modelo, sem disparar os sinais deles."""
        estado = self.painel.estado
        for w in (self.combo_tamanho, self.spin_copias, self.combo_modo):
            w.blockSignals(True)
        item = self.combo_tamanho.model().item(self.combo_tamanho.count() - 1)
        if imp.tamanho == tamanhos.PERSONALIZADO and imp.papel_mm:
            menor, maior = tamanhos.papel_mm(imp.tamanho, imp.papel_mm)
            item.setText(_("Personalizado {menor}x{maior} mm").format(
                menor=f"{menor:g}", maior=f"{maior:g}"))
        else:
            item.setText(_("Personalizado…"))
        escolher_no_combo(self.combo_tamanho, imp.tamanho)
        self.spin_copias.setValue(imp.copias)
        self.rotulo_copias.setText(f"× {imp.copias}")
        self.combo_modo.setCurrentIndex(max(0, self.combo_modo.findData(imp.modo)))
        for w in (self.combo_tamanho, self.spin_copias, self.combo_modo):
            w.blockSignals(False)

        # orientação: a resolvida pela forma da foto (auto) ou a fixa; "auto" aparece como indicador discreto
        dim = _dim_girada(estado, foto, imp)
        resolvida = tamanhos.orientacao_efetiva(imp.orientacao, *dim) if dim else (
            None if imp.orientacao == "auto" else imp.orientacao)
        automatica = imp.orientacao == "auto"
        if resolvida is None:
            for b in self.seg_orientacao.botoes.values():
                b.setChecked(False)
        else:
            self.seg_orientacao.definir_atual(resolvida)
        self.rotulo_auto.setVisible(automatica)
        self.botao_voltar.setVisible(not automatica)

        resultado = qualidade_impressao(estado, foto, imp)
        self.qualidade = resultado[1] if resultado else None
        self.rotulo_qualidade.setText(texto_qualidade(resultado))
        if resultado:
            self.rotulo_qualidade.setToolTip(_("Resolução efetiva: {dpi} dpi").format(dpi=round(resultado[0])))
        cor = COR_QUALIDADE.get(self.qualidade or "", tema.APAGADO)
        peso = "font-weight: 600;" if self.qualidade == "baixa" else ""
        self.rotulo_qualidade.setStyleSheet(f"color: {cor}; {peso}")
        self.ponto_qualidade.setStyleSheet(f"background: {cor}; border-radius: 4px;" if self.qualidade else "")
        pasta = estado.pasta_por_id(imp.pasta)
        self.pasta = pasta
        self.caixa_pasta.setVisible(pasta is not None)
        if pasta is not None:
            self.bolinha_pasta.setPixmap(icones.bolinha(tema.cor_pasta(pasta.cor), 10).pixmap(10, 10))
            self.rotulo_pasta.setText(_("Pasta “{nome}”").format(nome=pasta.nome))
            self.rotulo_pasta.setToolTip(tema.nome_cor_pasta(pasta.cor))
            self.combo_tamanho.setEnabled(False)
            self.combo_tamanho.setToolTip(_("O tamanho é o da pasta “{nome}”: mude pelo menu da pasta (vale para "
                                            "todas as fotos dela).").format(nome=pasta.nome))
            self.botao_remover.setEnabled(True)
            self.botao_remover.setToolTip(_("Tirar da pasta “{nome}”").format(nome=pasta.nome))
        else:
            self.combo_tamanho.setEnabled(True)
            self.combo_tamanho.setToolTip("")
            self.botao_remover.setEnabled(len(foto.impressoes) > 1)
            self.botao_remover.setToolTip(_("Remover este tamanho"))
        self.setProperty("ativa", "true" if ativa else "false")
        self.style().unpolish(self)
        self.style().polish(self)


# ------------------------------------------------------------------------------------------------ painel
class PainelImpressoes(Card):
    """"Revelar esta foto" e a lista de impressões (tamanho, cópias, orientação, modo) da foto atual."""

    def __init__(self, estado: Estado, parent: QWidget | None = None) -> None:
        super().__init__(_("Impressões"), _("Tamanho e cópias da foto escolhida"), parent=parent)
        self.estado = estado
        self.linhas: list[LinhaImpressao] = []
        raiz = self.corpo_layout
        self.rotulo_vazio = QLabel(_("Escolha uma foto na grade"))
        self.rotulo_vazio.setObjectName("Faint")
        self.rotulo_vazio.setWordWrap(True)
        raiz.addWidget(self.rotulo_vazio)
        self.caixa_foto = QWidget()
        interno = QVBoxLayout(self.caixa_foto)
        interno.setContentsMargins(0, 0, 0, 0)
        interno.setSpacing(10)
        self.rotulo_nome = QLabel()
        self.rotulo_nome.setObjectName("Muted")
        self.rotulo_nome.setWordWrap(True)
        interno.addWidget(self.rotulo_nome)
        linha_selecao = QHBoxLayout()
        linha_selecao.addWidget(QLabel(_("Revelar esta foto")))
        linha_selecao.addStretch(1)
        self.caixa_selecao = ToggleSwitch()
        linha_selecao.addWidget(self.caixa_selecao)
        interno.addLayout(linha_selecao)
        self.caixa_linhas = QWidget()
        self.layout_linhas = QVBoxLayout(self.caixa_linhas)
        self.layout_linhas.setContentsMargins(0, 0, 0, 0)
        self.layout_linhas.setSpacing(8)
        interno.addWidget(self.caixa_linhas)
        self.botao_adicionar = botao_plano("mais", "", _("Outro tamanho"), tamanho=16, cor=tema.APAGADO)
        interno.addWidget(self.botao_adicionar, 0, Qt.AlignmentFlag.AlignLeft)
        raiz.addWidget(self.caixa_foto)

        self.caixa_selecao.toggled.connect(self.alternar_selecao)
        self.botao_adicionar.clicked.connect(lambda: self.adicionar_impressao())
        estado.atual_mudou.connect(lambda _foto: self.sincronizar())
        estado.foto_mudou.connect(self._foto_mudou)
        estado.impressao_mudou.connect(lambda _i: self.sincronizar())
        estado.pastas_mudaram.connect(self.sincronizar)   # nome/cor/tamanho de uma pasta de tamanho (#32)
        # atalhos + e − (e = sem Shift) mudam as cópias da impressão atual
        for chave, delta in (("+", 1), ("=", 1), ("-", -1)):
            QShortcut(QKeySequence(chave), self, activated=lambda d=delta: self.mudar_copias_atual(d),
                      context=Qt.ShortcutContext.WindowShortcut)
        self.sincronizar()

    # ------------------------------------------------------------ sincronia com o modelo
    def _foto_mudou(self, foto_id: str) -> None:
        if self.estado.atual is not None and self.estado.atual.id == foto_id:
            self.sincronizar()

    def sincronizar(self) -> None:
        foto = self.estado.atual
        self.rotulo_vazio.setVisible(foto is None)
        self.caixa_foto.setVisible(foto is not None)
        if foto is None:
            return
        self.rotulo_nome.setText(foto.caminho.name)
        self.caixa_selecao.blockSignals(True)
        self.caixa_selecao.setChecked(foto.selecionada)
        self.caixa_selecao.blockSignals(False)
        mostrar = foto.selecionada and bool(foto.impressoes)
        self.caixa_linhas.setVisible(mostrar)
        self.botao_adicionar.setVisible(mostrar)
        if len(self.linhas) != len(foto.impressoes):
            self._reconstruir(len(foto.impressoes))
        ativa = min(self.estado.indice_impressao, len(foto.impressoes) - 1)
        for i, (linha, imp) in enumerate(zip(self.linhas, foto.impressoes)):
            linha.atualizar(foto, imp, i == ativa)

    def _reconstruir(self, quantidade: int) -> None:
        for linha in self.linhas:
            self.layout_linhas.removeWidget(linha)
            linha.deleteLater()
        self.linhas = [LinhaImpressao(self, i) for i in range(quantidade)]
        for linha in self.linhas:
            self.layout_linhas.addWidget(linha)

    # ------------------------------------------------------------ ações (chamadas pelos controles)
    def alternar_selecao(self, sim: bool) -> None:
        if self.estado.atual is not None:
            self.estado.selecionar(self.estado.atual, sim)

    def _imp(self, indice: int) -> tuple[Foto, Impressao] | None:
        foto = self.estado.atual
        if foto is None or not 0 <= indice < len(foto.impressoes):
            return None
        return foto, foto.impressoes[indice]

    def trocar_tamanho(self, indice: int, tamanho_id: str) -> None:
        """Troca o tamanho de uma impressão avulsa (a de pasta tem o tamanho da pasta: não muda por aqui)."""
        alvo = self._imp(indice)
        if alvo is None or alvo[1].pasta is not None:
            return
        foto, imp = alvo
        tamanhos.obter(tamanho_id)   # valida (KeyError em id desconhecido)
        imp.tamanho, imp.papel_mm, imp.preco_centavos = tamanho_id, None, None
        refazer_enquadramento(self.estado, foto, imp)

    def definir_personalizado(self, indice: int, largura_mm: float, altura_mm: float,
                              preco_centavos: int | None = None) -> None:
        alvo = self._imp(indice)
        if alvo is None or alvo[1].pasta is not None:
            return
        foto, imp = alvo
        tamanhos.papel_mm(tamanhos.PERSONALIZADO, (largura_mm, altura_mm))   # valida os limites
        imp.tamanho, imp.papel_mm, imp.preco_centavos = tamanhos.PERSONALIZADO, (largura_mm, altura_mm), preco_centavos
        refazer_enquadramento(self.estado, foto, imp)

    def pedir_personalizado(self, indice: int) -> None:
        """Abre o diálogo (modal) do tamanho personalizado; cancelar devolve o combo ao valor do modelo."""
        alvo = self._imp(indice)
        if alvo is None:
            return
        _foto, imp = alvo
        largura, altura = (imp.papel_mm if imp.papel_mm else (100.0, 150.0))
        dialogo = PersonalizadoDialog(largura, altura, imp.preco_centavos, self)
        if dialogo.exec() == QDialog.DialogCode.Accepted:
            self.definir_personalizado(indice, *dialogo.valores())
        else:
            self.sincronizar()

    def definir_copias(self, indice: int, copias: int) -> None:
        alvo = self._imp(indice)
        if alvo is not None:
            alvo[1].copias = max(LIMITE_COPIAS[0], min(LIMITE_COPIAS[1], int(copias)))
            self.estado.alterar(alvo[0], pedido=True)

    def mudar_copias_atual(self, delta: int) -> None:
        """Atalho + / −: soma ``delta`` às cópias da impressão que o editor mostra (limitado a 1 e 999)."""
        imp = self.estado.impressao_atual
        if imp is not None:
            self.definir_copias(self.estado.indice_impressao, imp.copias + delta)

    def definir_orientacao(self, indice: int, orientacao: str) -> None:
        """Fixa "retrato" ou "paisagem"; "auto" volta à orientação dada pela forma da foto."""
        alvo = self._imp(indice)
        if alvo is not None:
            alvo[1].orientacao = orientacao
            refazer_enquadramento(self.estado, *alvo)

    def girar_papel(self, indice: int) -> None:
        """Troca retrato ↔ paisagem da impressão (fixa a escolha). O recorte é refeito ou reencaixado."""
        alvo = self._imp(indice)
        if alvo is None:
            return
        foto, imp = alvo
        dim = _dim_girada(self.estado, foto, imp)
        if dim is not None:
            atual = tamanhos.orientacao_efetiva(imp.orientacao, *dim)
        else:
            atual = "paisagem" if imp.orientacao == "paisagem" else "retrato"
        imp.orientacao = "paisagem" if atual == "retrato" else "retrato"
        refazer_enquadramento(self.estado, foto, imp)

    def definir_modo(self, indice: int, modo: str) -> None:
        alvo = self._imp(indice)
        if alvo is not None:
            alvo[1].modo = modo
            self.estado.alterar(alvo[0], pedido=True)

    def adicionar_impressao(self, tamanho_id: str | None = None) -> None:
        """Mais uma impressão da foto atual: o tamanho dado ou o primeiro ainda não usado (a partir do padrão)."""
        foto = self.estado.atual
        if foto is None:
            return
        if tamanho_id is None:
            usados = {i.tamanho for i in foto.impressoes}
            ids = [t.id for t in tamanhos.TAMANHOS]
            padrao = self.estado.trabalho.tamanho_padrao
            ordem = ids[ids.index(padrao):] + ids[:ids.index(padrao)] if padrao in ids else ids
            tamanho_id = next((t for t in ordem if t not in usados), padrao)
        foto.selecionada = True
        foto.impressoes.append(Impressao(tamanho=tamanho_id))
        self.estado.refazer_recortes_auto(foto)
        self.estado.alterar(foto, pedido=True)
        self.estado.definir_impressao(len(foto.impressoes) - 1)

    def remover_impressao(self, indice: int) -> None:
        """Remove a impressão avulsa (nunca a última) ou, se for de uma pasta de tamanho, tira a foto da pasta."""
        alvo = self._imp(indice)
        if alvo is not None and alvo[1].pasta is not None:
            pasta = self.estado.pasta_por_id(alvo[1].pasta)
            if pasta is not None:
                self.estado.tirar_da_pasta([alvo[0]], pasta)
                return
        if alvo is None or len(alvo[0].impressoes) <= 1:
            return
        foto = alvo[0]
        del foto.impressoes[indice]
        self.estado.indice_impressao = min(self.estado.indice_impressao, len(foto.impressoes) - 1)
        self.estado.alterar(foto, pedido=True)
        self.estado.impressao_mudou.emit(self.estado.indice_impressao)


# ------------------------------------------------------------------------------------------------ tamanho padrão
def tamanho_padrao_salvo() -> str | None:
    """Tamanho padrão lembrado nas preferências (None se não houver ou for inválido)."""
    valor = prefs.settings().value("tamanho_padrao")
    return valor if isinstance(valor, str) and valor in {t.id for t in tamanhos.TAMANHOS} else None


class SeletorTamanhoPadrao(QWidget):
    """"Tamanho padrão [10x15 ▾]" da barra superior: vale para as próximas fotos selecionadas."""

    def __init__(self, estado: Estado, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.estado = estado
        caixa = QHBoxLayout(self)
        caixa.setContentsMargins(0, 0, 0, 0)
        caixa.setSpacing(8)
        self.combo = QComboBox()
        preencher_combo_tamanhos(self.combo, personalizado=False)
        self.combo.setToolTip(_(tamanhos.AJUDA))
        self.rotulo = QLabel(_("Tamanho padrão"))
        self.rotulo.setObjectName("Muted")
        caixa.addWidget(self.rotulo)
        caixa.addWidget(self.combo)
        self.atualizar()
        self.combo.currentIndexChanged.connect(self._mudou)
        estado.fotos_mudaram.connect(self.atualizar)

    def atualizar(self) -> None:
        self.combo.blockSignals(True)
        escolher_no_combo(self.combo, self.estado.trabalho.tamanho_padrao)
        self.combo.blockSignals(False)

    def definir(self, tamanho_id: str) -> None:
        escolher_no_combo(self.combo, tamanho_id)

    def _mudou(self, _i: int) -> None:
        tamanho_id = self.combo.currentData(Qt.ItemDataRole.UserRole)
        if tamanho_id is None or tamanho_id == self.estado.trabalho.tamanho_padrao:
            return
        self.estado.trabalho.tamanho_padrao = tamanho_id
        s = prefs.settings()
        s.setValue("tamanho_padrao", tamanho_id)
        s.sync()
        self.estado.marcar_modificado()
