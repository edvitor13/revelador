"""Janela principal (subprocesso offscreen): áreas, ações, geometria salva e restaurada, "Sobre"."""

from __future__ import annotations

from conftest import rodar_python

PREAMBULO = """
import sys
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv[:1])
from revelador.ui.main_window import MainWindow
"""


def rodar(corpo: str) -> None:
    p = rodar_python(PREAMBULO + corpo)
    assert p.returncode == 0, p.stderr
    assert p.stdout.strip().endswith("ok"), p.stdout


def test_tres_areas_e_acoes():
    rodar("""
j = MainWindow()
j.show(); app.processEvents()
assert j.divisor.count() == 3
assert [j.divisor.widget(i) for i in range(3)] == [j.area_grade, j.area_editor, j.area_painel]
for area in (j.area_grade, j.area_editor, j.area_painel):
    assert area.layout() is not None
assert "Arraste fotos ou pastas" in j.orientacao_grade.text()
assert j.acao_importar.text() == "Importar…" and j.acao_importar.isEnabled()
assert j.acao_exportar.text() == "Exportar para revelação…" and not j.acao_exportar.isEnabled()
assert j.statusBar() is not None and j.arquivos_iniciais == []
assert not j.menuBar().isVisible() or j.menuBar().actions() == []      # sem barra de menus nem de ferramentas
assert j.findChildren(__import__("PySide6.QtWidgets", fromlist=["QToolBar"]).QToolBar) == []
print("ok")
""")


def test_barra_superior_itens_menus_e_atalhos():
    rodar("""
from PySide6.QtWidgets import QPushButton, QToolButton
from PySide6.QtGui import QKeySequence
j = MainWindow()
j.show(); app.processEvents()
barra = j.barra_superior
assert barra.objectName() == "TopBar" and j.centralWidget().layout().itemAt(0).widget() is barra
# importar e projeto: botões planos com menu; ações desligadas aparecem desligadas
assert j.botao_importar.menu().actions() == [j.acao_importar, j.acao_importar_pasta]
nomes = [a.text() for a in j.botao_projeto.menu().actions() if not a.isSeparator()]
assert nomes == ["Novo trabalho", "Abrir trabalho…", "Abrir recente", "Salvar", "Salvar como…", "Desfazer",
                 "Refazer"], nomes
assert j.acao_salvar.isEnabled() and j.acao_abrir.isEnabled() and j.acao_importar.isEnabled()   # ligadas pela #9
assert j.botao_projeto.menu().actions()[2].menu() is j.menu_recentes
# engrenagem
assert [a.text() for a in j.botao_menu.menu().actions() if not a.isSeparator()] == [
    "Preços do laboratório…", "Resumo do pedido…", "Configurações…", "Tela de boas-vindas",
    "Verificar atualizações…", "Sobre o Revelador"]
# mostrar, tamanho padrão, custo, exportar
assert list(j.filtro_mostrar.botoes) == ["todas", "selecionadas"] and j.filtro_mostrar.chave_atual() == "todas"
assert j.seletor_tamanho.parent() is not None and j.botao_custo.objectName() == "Pilula"
assert j.botao_exportar.objectName() == "Primary" and not j.botao_exportar.isEnabled()
j.acao_exportar.setEnabled(True)
assert j.botao_exportar.isEnabled()
chamadas = []
class Falso:
    def exec(self):
        chamadas.append(1)
j.criar_dialogo_exportacao = lambda: Falso()          # nada de diálogo modal em teste
j.botao_exportar.click()
assert chamadas == [1]
# os atalhos continuam valendo sem barra de menus: as ações estão na janela
na_janela = set(j.actions())
for acao in (j.acao_importar, j.acao_importar_pasta, j.acao_exportar, j.acao_novo, j.acao_abrir, j.acao_salvar,
             j.acao_salvar_como, j.acao_sair):
    assert acao in na_janela and not acao.shortcut().isEmpty(), acao.text()
assert j.acao_importar.shortcut() == QKeySequence("Ctrl+I") and j.acao_sair.shortcut() == QKeySequence("Ctrl+Q")
print("ok")
""")


def test_barra_superior_encolhe_em_janela_estreita():
    rodar("""
j = MainWindow()
j.resize(1500, 700); j.show()
for _ in range(4): app.processEvents()
assert j.barra_superior.nivel <= j.barra_superior.ETAPAS - 1
j.resize(1000, 700)
for _ in range(4): app.processEvents()
b = j.barra_superior
assert b.nivel >= 2, b.nivel                                       # só ícones
assert j.botao_importar.toolButtonStyle().name.endswith("IconOnly") and j.botao_exportar.toolButtonStyle().name.endswith("IconOnly")
# o custo continua inteiro em ``text()`` mesmo quando a pílula o encurta
j.estado.adicionar([])
assert "Nenhuma foto" in j.botao_custo.text()
print("ok")
""")


def test_grade_vazia_mostra_orientacao_e_some_com_fotos():
    rodar("""
from pathlib import Path
j = MainWindow(); j.show(); app.processEvents()
assert j.vazio_grade.isVisible() and not j.grade.isVisible() and j.orientacao_grade.isVisible()
import tempfile
from PIL import Image
d = Path(tempfile.mkdtemp()); Image.new("RGB", (60, 40), (10, 20, 30)).save(d / "a.jpg")
j.importar([d]); app.processEvents()
assert not j.vazio_grade.isVisible() and j.grade.isVisible()
print("ok")
""")


def test_sobre_menciona_licenca_modelo_e_privacidade():
    rodar("""
t = MainWindow().texto_sobre()
for parte in ("MIT", "YuNet", "OpenCV Zoo", "nenhuma foto sai do seu computador"):
    assert parte in t, parte
print("ok")
""")


def test_geometria_salva_e_restaurada_pelo_ini():
    rodar("""
import os
from pathlib import Path
j = MainWindow()
j.show(); app.processEvents()
j.resize(700, 500)
j.divisor.setSizes([150, 300, 200]); app.processEvents()
tamanho, divisores = j.size(), j.divisor.sizes()
j.close()
ini = Path(os.environ["REVELADOR_SETTINGS_DIR"]) / "Revelador.ini"
assert ini.is_file() and "geometria" in ini.read_text(encoding="utf-8", errors="replace")
k = MainWindow()
k.show(); app.processEvents()
assert k.size() == tamanho, (k.size(), tamanho)
assert k.divisor.sizes() == divisores, (k.divisor.sizes(), divisores)
print("ok")
""")
