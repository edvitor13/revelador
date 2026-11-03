"""Fluxo da interface de exportação (subprocesso offscreen, sem diálogo modal)."""

from __future__ import annotations

from conftest import rodar_python

PREAMBULO = """
import os, sys, tempfile
os.environ["REVELADOR_SETTINGS_DIR"] = tempfile.mkdtemp()
from pathlib import Path
import numpy as np
from PIL import Image
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv[:1])
from revelador.projeto import Foto
from revelador.imagem import abrir_info
from revelador.ui.main_window import MainWindow
from revelador.ui import prefs

base = Path(tempfile.mkdtemp())
(base / "fotos").mkdir()

def nova(j, nome, larg=900, alt=600, selecionar=True):
    caminho = base / "fotos" / (nome + ".jpg")
    Image.fromarray(np.full((alt, larg, 3), 120, np.uint8)).save(caminho)
    f = Foto(id=nome, caminho=caminho)
    j.estado.trabalho.fotos.append(f)
    j.estado.definir_info(f.id, abrir_info(caminho))
    if selecionar:
        j.estado.selecionar(f)
    return f

j = MainWindow()
e = j.estado
"""


def rodar(corpo: str) -> None:
    proc = rodar_python(PREAMBULO + corpo, timeout=120)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip().endswith("ok"), proc.stdout


def test_acao_exportar_segue_a_selecao():
    rodar("""
assert not j.acao_exportar.isEnabled()
f = nova(j, "a", selecionar=False)
assert not j.acao_exportar.isEnabled()
e.selecionar(f)
assert j.acao_exportar.isEnabled()
e.selecionar(f, False)
assert not j.acao_exportar.isEnabled()
print("ok")
""")


def test_dialogo_exporta_e_lembra_a_pasta():
    rodar("""
f = nova(j, "a"); g = nova(j, "b")
f.impressoes[0].copias = 2
e.alterar(f, pedido=True)
d = j.criar_dialogo_exportacao()
destino = base / "saida"
destino.mkdir()
d.definir_destino(destino)
assert d.spin_dpi.value() == 300
assert "2 foto(s), 3 cópia(s)" in d.rotulo_resumo.text(), d.rotulo_resumo.text()
assert d.botao_exportar.isEnabled() and d.botao_exportar.objectName() == "Primary"
assert d.iniciar() and not d.iniciar()      # a segunda chamada não faz nada
assert d.aguardar(60000)
r = d.resultado
assert r is not None and r.ok and len(r.arquivos) == 2 and r.pedido.is_file()
assert d.barra.value() == 2
assert "Exportação concluída" in d.rotulo_fim.text()
pasta = r.pedido.parent
assert (pasta / "10x15" / "2 cópias" / "a.jpg").is_file() and (pasta / "10x15" / "1 cópia" / "b.jpg").is_file()
assert str(prefs.settings().value("exportar/pasta")) == str(destino)
d2 = j.criar_dialogo_exportacao()
assert Path(d2.campo_pasta.text()) == destino
print("ok")
""")


def test_erro_aparece_na_lista_e_cancelar_nao_deixa_tmp():
    rodar("""
f = nova(j, "a"); g = nova(j, "b")
g.caminho.write_bytes(b"quebrada")
d = j.criar_dialogo_exportacao()
d.definir_destino(base)
assert d.iniciar() and d.aguardar(60000)
assert len(d.resultado.erros) == 1 and d.lista_erros.count() == 1 and not d.lista_erros.isHidden()
assert "erros" in d.rotulo_fim.text()

d = j.criar_dialogo_exportacao()
d.definir_destino(base)
assert d.iniciar()
d.cancelar()
assert d.aguardar(60000)
assert d.resultado.cancelado and d.resultado.pedido is None
assert not list(base.rglob("*.tmp"))
assert "cancelada" in d.rotulo_fim.text()
print("ok")
""")


def test_avisos_de_resolucao_baixa_listados():
    rodar("""
f = nova(j, "a", larg=600, alt=400)
f.impressoes[0].tamanho = "30x45"
e.alterar(f, pedido=True)
d = j.criar_dialogo_exportacao()
d.definir_destino(base)
d.atualizar()
assert d.lista_avisos.count() == 1 and "resolução baixa" in d.lista_avisos.item(0).text()
print("ok")
""")


def test_nome_da_pasta_e_acabamento_por_tamanho_no_dialogo():
    rodar("""
from revelador import exportar
f = nova(j, "a"); g = nova(j, "b")
g.impressoes[0].tamanho = "15x21"
e.alterar(g, pedido=True)
d = j.criar_dialogo_exportacao()
destino = base / "saida"
destino.mkdir()
d.definir_destino(destino)
assert d.campo_nome.text().startswith("Revelação ")              # padrão: Revelação AAAA-MM-DD
assert list(d.combos_acabamento) == ["10x15", "15x21"]            # uma linha por tamanho exportado
d.definir_nome("Casamento da Ana")
d.definir_acabamento("10x15", "fina", "fosco")
d.definir_acabamento("15x21", "", "brilho")
assert "Casamento da Ana/10x15 - borda fina - fosco/a.jpg" in d.rotulo_estrutura.text(), d.rotulo_estrutura.text()
assert d.iniciar() and d.aguardar(60000) and d.resultado.ok
raiz = destino / "Casamento da Ana"
assert (raiz / "10x15 - borda fina - fosco" / "a.jpg").is_file()
assert (raiz / "15x21 - brilho" / "b.jpg").is_file()
d2 = j.criar_dialogo_exportacao()                                 # o acabamento é lembrado por tamanho
assert d2.acabamentos() == {"10x15": exportar.Acabamento("fina", "fosco"), "15x21": exportar.Acabamento("", "brilho")}
print("ok")
""")
