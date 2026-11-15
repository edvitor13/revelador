"""Visualizar: passa pelas fotos e mostra como cada uma vai sair no papel, em cada tamanho que vai ser revelado.

Cada impressão é desenhada pela receita única (``RenderizarPrevia``, a mesma da prévia do editor), lado a lado,
com o rótulo "10x15 ×2" embaixo. ←/→ (ou os botões) passam as fotos; Esc fecha. Só a estrela de favorita (F ou o botão)
muda o trabalho.

A janela tem os botões de maximizar e minimizar do sistema, "Maximizar" e "Tela cheia" (F11; Esc sai da tela cheia
antes de fechar). Ela lembra se estava maximizada (``visualizar/maximizada`` nas preferências).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QThreadPool, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from .. import receita
from ..i18n import _
from ..projeto import Foto
from . import icones, prefs, tema
from .componentes import botao_plano
from .editor import rotulo_impressao
from .estado import Estado
from .previa import CarregarProxy, RenderizarPrevia, Sinais, para_qimage

ESPACO = 16   # px entre as impressões lado a lado
PREF_MAXIMIZADA = "visualizar/maximizada"
INTEIRA = -1  # chave da coluna da foto inteira (modo comparar)


class VisualizarDialog(QDialog):
    """Tela de visualização: ``fotos`` na ordem dada, começando em ``inicio``."""

    def __init__(self, estado: Estado, fotos: list[Foto], inicio: int = 0, parent: QWidget | None = None,
                 comparar: bool = False) -> None:
        """``comparar``: mostra a foto inteira (sem recorte), com o nome, a resolução e os tamanhos marcados — para
        conferir fotos repetidas lado a lado."""
        super().__init__(parent)
        self.estado = estado
        self.fotos = fotos
        self.comparar = comparar
        self.indice = max(0, min(inicio, len(fotos) - 1))
        self.setWindowTitle(_("Comparar fotos parecidas") if comparar else _("Visualizar a revelação"))
        self.setObjectName("Panel")
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowTitleHint | Qt.WindowType.WindowSystemMenuHint
                            | Qt.WindowType.WindowMinMaxButtonsHint | Qt.WindowType.WindowCloseButtonHint)
        self.resize(1200, 820)
        self.sinais = Sinais(self)
        self.sinais.proxy_pronto.connect(self._proxy_pronto)
        self.sinais.proxy_erro.connect(lambda _g, _c, msg: self._aviso(msg))
        self.sinais.previa_pronta.connect(self._previa_pronta)
        self.sinais.previa_erro.connect(lambda _g, msg: self._aviso(msg))
        self._geracao = 0
        self._proxy = None
        self._inteira: QPixmap | None = None
        self._imagens: dict[int, QLabel] = {}

        self.titulo = QLabel()
        self.titulo.setObjectName("PanelTitle")
        self.contador = QLabel()
        self.contador.setObjectName("Muted")
        self.area = QWidget()
        self.linha = QHBoxLayout(self.area)
        self.linha.setContentsMargins(0, 0, 0, 0)
        self.linha.setSpacing(ESPACO)
        self.botao_ant = QPushButton("‹  " + _("Anterior"))
        self.botao_prox = QPushButton(_("Próxima") + "  ›")
        self.botao_prox.setObjectName("Primary")
        for b in (self.botao_ant, self.botao_prox):
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
        self.botao_ant.clicked.connect(lambda: self.passar(-1))
        self.botao_prox.clicked.connect(lambda: self.passar(+1))
        self.botao_favorita = botao_plano("estrela", _("Favorita: põe ou tira a estrela desta foto (F)"))
        self.botao_favorita.clicked.connect(self.alternar_favorita)
        self.botao_maximizar = botao_plano("maximizar", _("Maximizar a janela"), _("Maximizar"))
        self.botao_maximizar.clicked.connect(self.alternar_maximizada)
        self.botao_tela_cheia = botao_plano("tela_cheia", _("Tela cheia (F11)"), _("Tela cheia"))
        self.botao_tela_cheia.clicked.connect(self.alternar_tela_cheia)
        topo = QHBoxLayout()
        topo.addWidget(self.botao_favorita)
        topo.addWidget(self.titulo, 1)
        topo.addWidget(self.contador)
        topo.addSpacing(8)
        topo.addWidget(self.botao_maximizar)
        topo.addWidget(self.botao_tela_cheia)
        base = QHBoxLayout()
        base.addWidget(self.botao_ant)
        dica = QLabel(_("← → passam as fotos · F favorita · F11 tela cheia · Esc fecha"))
        dica.setObjectName("Faint")
        base.addStretch(1)
        base.addWidget(dica)
        base.addStretch(1)
        base.addWidget(self.botao_prox)
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(20, 16, 20, 16)
        raiz.setSpacing(12)
        raiz.addLayout(topo)
        raiz.addWidget(self.area, 1)
        raiz.addLayout(base)
        self._timer = QTimer(self, singleShot=True, interval=80)
        self._timer.timeout.connect(self._renderizar)
        self._maximizada_antes = False   # como estava antes da tela cheia (para voltar igual)
        if _preferencia_maximizada():
            self.setWindowState(self.windowState() | Qt.WindowState.WindowMaximized)
        self._atualizar_botoes_janela()
        self.mostrar()

    # ------------------------------------------------------------ janela: maximizar e tela cheia
    @property
    def tela_cheia(self) -> bool:
        return bool(self.windowState() & Qt.WindowState.WindowFullScreen)

    @property
    def maximizada(self) -> bool:
        return bool(self.windowState() & Qt.WindowState.WindowMaximized)

    def alternar_tela_cheia(self) -> None:
        """Entra ou sai da tela cheia (F11). Ao sair, volta como estava (maximizada ou não)."""
        if self.tela_cheia:
            estado = Qt.WindowState.WindowMaximized if self._maximizada_antes else Qt.WindowState.WindowNoState
            self.setWindowState(estado)
        else:
            self._maximizada_antes = self.maximizada
            self.setWindowState(Qt.WindowState.WindowFullScreen)
        self._atualizar_botoes_janela()

    def alternar_maximizada(self) -> None:
        """Maximiza ou restaura a janela (na tela cheia, sai dela maximizada). Lembrado para a próxima vez."""
        if self.tela_cheia or not self.maximizada:
            self.setWindowState(Qt.WindowState.WindowMaximized)
        else:
            self.setWindowState(Qt.WindowState.WindowNoState)
        self._atualizar_botoes_janela()

    def changeEvent(self, e) -> None:  # noqa: N802 - nome do Qt
        super().changeEvent(e)
        if e.type() == e.Type.WindowStateChange and hasattr(self, "botao_tela_cheia"):
            self._atualizar_botoes_janela()
            if not self.tela_cheia:
                _lembrar_maximizada(self.maximizada)

    def _atualizar_botoes_janela(self) -> None:
        cheia = self.tela_cheia
        self.botao_tela_cheia.setText(_("Sair da tela cheia") if cheia else _("Tela cheia"))
        self.botao_tela_cheia.setToolTip(_("Sair da tela cheia (F11 ou Esc)") if cheia else _("Tela cheia (F11)"))
        restaurar = self.maximizada and not cheia
        self.botao_maximizar.setText(_("Restaurar") if restaurar else _("Maximizar"))
        self.botao_maximizar.setToolTip(_("Restaurar o tamanho da janela") if restaurar else _("Maximizar a janela"))

    # ------------------------------------------------------------ favorita
    def alternar_favorita(self) -> None:
        """Põe ou tira a estrela da foto mostrada (entra no desfazer do trabalho)."""
        foto = self.foto
        if foto is not None:
            self.estado.favoritar([foto], not foto.favorita)
            self._atualizar_favorita()

    def _atualizar_favorita(self) -> None:
        foto = self.foto
        favorita = foto is not None and foto.favorita
        self.botao_favorita.setEnabled(foto is not None)
        self.botao_favorita.setIcon(icones.icone("estrela_cheia", tema.FAVORITA, 18) if favorita
                                    else icones.icone("estrela", tema.APAGADO, 18))

    # ------------------------------------------------------------ navegação
    @property
    def foto(self) -> Foto | None:
        return self.fotos[self.indice] if self.fotos else None

    def passar(self, passo: int) -> None:
        novo = max(0, min(len(self.fotos) - 1, self.indice + passo))
        if novo != self.indice:
            self.indice = novo
            self.mostrar()

    def keyPressEvent(self, e) -> None:  # noqa: N802 - nome do Qt
        if e.key() in (Qt.Key.Key_Left, Qt.Key.Key_Up, Qt.Key.Key_PageUp):
            self.passar(-1)
        elif e.key() in (Qt.Key.Key_Right, Qt.Key.Key_Down, Qt.Key.Key_PageDown, Qt.Key.Key_Space):
            self.passar(+1)
        elif e.key() == Qt.Key.Key_F11:
            self.alternar_tela_cheia()
        elif e.key() == Qt.Key.Key_Escape and self.tela_cheia:
            self.alternar_tela_cheia()     # Esc na tela cheia só sai dela; outro Esc fecha
        elif e.key() == Qt.Key.Key_F and e.modifiers() == Qt.KeyboardModifier.NoModifier:
            self.alternar_favorita()
        else:
            super().keyPressEvent(e)

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        self._timer.start()

    # ------------------------------------------------------------ montagem
    def mostrar(self) -> None:
        """Monta a foto atual: título, uma coluna por impressão (imagem + rótulo) e pede o proxy."""
        self._geracao += 1
        self._proxy = None
        self._inteira = None
        self._imagens.clear()
        while self.linha.count():
            item = self.linha.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        foto = self.foto
        self._atualizar_favorita()
        self.botao_ant.setEnabled(self.indice > 0)
        self.botao_prox.setEnabled(self.indice < len(self.fotos) - 1)
        if foto is None:
            self.titulo.setText(_("Nenhuma foto marcada para revelação"))
            self.contador.clear()
            return
        self.titulo.setText(foto.caminho.name)
        self.contador.setText(_("{n} de {total}").format(n=self.indice + 1, total=len(self.fotos)))
        imps = foto.impressoes if foto.selecionada else []
        if self.comparar:
            info = self.estado.info.get(foto.id)
            partes = [f"{info.largura} × {info.altura} px"] if info is not None else []
            partes.append(" · ".join(rotulo_impressao(i) for i in imps) if imps else _("não marcada"))
            self._coluna(INTEIRA, " — ".join(partes))
        elif not imps:
            self._aviso(_("Esta foto não está marcada para revelação."))
            return
        for n, imp in enumerate([] if self.comparar else imps):
            coluna = QVBoxLayout()
            imagem = QLabel(_("Carregando…"))
            imagem.setObjectName("Muted")
            imagem.setAlignment(Qt.AlignmentFlag.AlignCenter)
            imagem.setMinimumSize(80, 80)
            rotulo = QLabel(rotulo_impressao(imp))
            rotulo.setObjectName("PanelTitle")
            rotulo.setAlignment(Qt.AlignmentFlag.AlignCenter)
            caixa = QWidget()
            caixa.setLayout(coluna)
            coluna.setContentsMargins(0, 0, 0, 0)
            coluna.addWidget(imagem, 1)
            coluna.addWidget(rotulo)
            self.linha.addWidget(caixa, 1)
            self._imagens[n] = imagem
        QThreadPool.globalInstance().start(CarregarProxy(self.sinais, self._geracao, foto.caminho))

    def _coluna(self, chave: int, texto: str) -> None:
        imagem = QLabel(_("Carregando…"))
        imagem.setObjectName("Muted")
        imagem.setAlignment(Qt.AlignmentFlag.AlignCenter)
        imagem.setMinimumSize(80, 80)
        rotulo = QLabel(texto)
        rotulo.setObjectName("PanelTitle")
        rotulo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        caixa = QWidget()
        coluna = QVBoxLayout(caixa)
        coluna.setContentsMargins(0, 0, 0, 0)
        coluna.addWidget(imagem, 1)
        coluna.addWidget(rotulo)
        self.linha.addWidget(caixa, 1)
        self._imagens[chave] = imagem

    def _aviso(self, texto: str) -> None:
        if not self._imagens:
            rotulo = QLabel(texto)
            rotulo.setObjectName("Muted")
            rotulo.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.linha.addWidget(rotulo, 1)
        else:
            for imagem in self._imagens.values():
                imagem.setText(texto)

    def _proxy_pronto(self, geracao: int, _caminho: str, proxy) -> None:
        if geracao != self._geracao:
            return
        self._proxy = proxy
        self._renderizar()

    def _renderizar(self) -> None:
        foto = self.foto
        if foto is None or self._proxy is None:
            return
        altura, largura = self._proxy.shape[:2]
        for n, imagem in self._imagens.items():
            if n == INTEIRA:     # a foto inteira, como está no arquivo (orientada), sem recorte nem ajustes
                if self._inteira is None:
                    self._inteira = QPixmap.fromImage(para_qimage(receita.para_uint8(self._proxy)))
                imagem.setPixmap(self._inteira.scaled(imagem.width() - 8, imagem.height() - 8,
                                                      Qt.AspectRatioMode.KeepAspectRatio,
                                                      Qt.TransformationMode.SmoothTransformation))
                continue
            imp = foto.impressoes[n]
            w, h = receita.destino_na_caixa(imp, largura, altura, imagem.width() - 8, imagem.height() - 8)
            ger = self._geracao * 1000 + n
            QThreadPool.globalInstance().start(RenderizarPrevia(self.sinais, ger, self._proxy, imp,
                                                                foto.ajustes, (w, h), foto.fundo))

    def _previa_pronta(self, geracao: int, imagem) -> None:
        if geracao // 1000 != self._geracao:
            return
        alvo = self._imagens.get(geracao % 1000)
        if alvo is not None:
            alvo.setPixmap(QPixmap.fromImage(imagem))


def _preferencia_maximizada() -> bool:
    valor = prefs.settings().value(PREF_MAXIMIZADA, False)
    return valor is True or str(valor).lower() == "true"


def _lembrar_maximizada(sim: bool) -> None:
    prefs.settings().setValue(PREF_MAXIMIZADA, bool(sim))


def fotos_para_visualizar(estado: Estado, visiveis: list[Foto]) -> list[Foto]:
    """As fotos marcadas para revelação, na ordem da grade (as visíveis primeiro, depois o resto do trabalho)."""
    ids = {f.id for f in visiveis}
    ordem = list(visiveis) + [f for f in estado.trabalho.fotos if f.id not in ids]
    return [f for f in ordem if f.selecionada and f.impressoes]
