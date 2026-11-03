"""Salvar e abrir o trabalho na interface (subprocesso offscreen, fotos geradas, nenhum diálogo modal)."""

from __future__ import annotations

from conftest import rodar_python

from revelador.app import separar_argumentos

PREAMBULO = """
import os, sys, shutil, tempfile, time
from pathlib import Path
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv[:1])
from PIL import Image
from revelador import projeto
from revelador.projeto import Trabalho, Rosto
from revelador.ui.main_window import MainWindow
from revelador.ui import projeto_ui as pu

RAIZ = Path(tempfile.mkdtemp(prefix="rev_pui_"))
os.environ["LOCALAPPDATA"] = str(RAIZ / "local")      # recuperação isolada deste teste


def fotos(n, pasta="fotos"):
    d = RAIZ / pasta
    d.mkdir(parents=True, exist_ok=True)
    saida = []
    for i in range(n):
        p = d / f"img_{i}.jpg"
        Image.new("RGB", (240, 160), (40 * i % 255, 90, 160)).save(p)
        saida.append(p)
    return saida


def esperar(cond, ms=20000):
    fim = time.time() + ms / 1000
    while time.time() < fim:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


def pronto(j):
    n = len(j.estado.trabalho.fotos)
    return esperar(lambda: len(j.estado.info) + len(j.estado.erros) >= n and not j.importacao.ocupado)


def janela_com_fotos(n=3):
    j = MainWindow()
    j.show()
    j.importar([str(p) for p in fotos(n)])
    assert pronto(j)
    for f in j.estado.trabalho.fotos:
        f.rostos = []          # evita a detecção (e o "modificado" que ela causa) nos testes
    return j
"""


def rodar(corpo: str) -> None:
    p = rodar_python(PREAMBULO + corpo, timeout=120)
    assert p.returncode == 0, p.stderr
    assert p.stdout.strip().endswith("ok"), p.stdout + p.stderr


def test_argumentos_separam_trabalho_de_fotos():
    trabalhos, resto = separar_argumentos(["a.jpg", "T.REVELADOR", "--x", "pasta", "b.revelador"])
    assert trabalhos == ["T.REVELADOR", "b.revelador"]
    assert resto == ["a.jpg", "pasta"]


def test_salvar_novo_abrir_devolve_o_mesmo_trabalho():
    rodar("""
j = janela_com_fotos(3)
ui, est = j.projeto_ui, j.estado
a, b, c = est.trabalho.fotos
est.selecionar(a)
est.selecionar(b)
rosto = Rosto(0.4, 0.2, 0.1, 0.1, ((0.42, 0.24), (0.47, 0.24)), 0.9)
a.rostos = [rosto]
imp = a.impressoes[0]
imp.copias = 3
imp.recorte.cx, imp.recorte.cy, imp.recorte.zoom, imp.recorte.origem = 0.3, 0.6, 1.5, "manual"
a.ajustes = {"exposicao": 10.0}
est.alterar(a, pedido=True)
assert est.modificado
destino = RAIZ / "trabalhos" / "festa.revelador"
ui.escolher_arquivo_salvar = lambda: destino
assert ui.salvar() and destino.is_file() and not est.modificado
antes = projeto.para_dict(est.trabalho, destino.parent)

assert ui.novo() and est.trabalho.fotos == [] and j.grade.total() == 0
assert ui.abrir(destino)
depois = projeto.para_dict(est.trabalho, destino.parent)
import json; assert depois == antes, (json.dumps(antes), json.dumps(depois))
assert j.grade.total() == 3 and not est.modificado
assert pronto(j)                                  # miniaturas e metadados lidos de novo
assert len(est.miniaturas) == 3 and not est.erros
a2 = est.trabalho.fotos[0]
assert a2.rostos == [rosto] and a2.impressoes[0].recorte.origem == "manual"
assert (a2.impressoes[0].recorte.cx, a2.impressoes[0].recorte.zoom) == (0.3, 1.5)   # não foi refeito
assert a2.ajustes == {"exposicao": 10.0}
assert not est.modificado
print("ok")
""")


def test_titulo_com_bolinha_e_pergunta_de_salvar():
    rodar("""
j = janela_com_fotos(2)
ui, est = j.projeto_ui, j.estado
assert j.windowTitle().startswith("• ") and "Sem título — Revelador" in j.windowTitle()
respostas = []
ui.perguntar_salvar = lambda: respostas.pop(0)
destino = RAIZ / "t" / "casa.revelador"
ui.escolher_arquivo_salvar = lambda: destino

respostas[:] = [pu.CANCELAR] * 3
assert ui.novo() is False and len(est.trabalho.fotos) == 2          # cancelar não perde nada
assert ui.abrir(destino) is False                                     # nem Abrir
assert j.close() is False and j.isVisible()                           # nem fechar a janela
respostas[:] = [pu.SALVAR]
assert ui.novo() is True and destino.is_file() and est.trabalho.fotos == []
assert j.windowTitle() == "Revelador " + __import__("revelador").__version__   # trabalho vazio e limpo
assert ui.abrir(destino) and j.windowTitle() == "casa — Revelador"
est.marcar_modificado()
assert j.windowTitle() == "• casa — Revelador"
respostas[:] = [pu.DESCARTAR]
assert ui.novo() is True and len(est.trabalho.fotos) == 0 and respostas == []
est.marcar_modificado()
respostas[:] = [pu.DESCARTAR]
assert j.close() is True                                              # fecha sem salvar
print("ok")
""")


def test_recentes_ordem_limite_e_inexistente():
    rodar("""
j = MainWindow()
ui = j.projeto_ui
ui.limpar_recentes()                                  # as preferências são compartilhadas entre os testes
assert not j.menu_recentes.isEnabled() and ui.recentes() == []
arquivos = []
for i in range(12):
    p = RAIZ / "r" / f"t{i}.revelador"
    projeto.salvar(Trabalho(), p)
    arquivos.append(p)
    ui.adicionar_recente(p)
rec = ui.recentes()
assert rec == list(reversed(arquivos))[:10] and len(rec) == 10
ui.adicionar_recente(arquivos[5])                                      # reabrir sobe para o topo, sem duplicar
assert ui.recentes()[0] == arquivos[5] and len(ui.recentes()) == 10
arquivos[5].unlink()
assert arquivos[5] not in ui.recentes() and len(ui.recentes()) == 9
ui.reconstruir_menu()
nomes = [a.text() for a in j.menu_recentes.actions() if not a.isSeparator()]
assert nomes[0] == "t11.revelador" and nomes[-1] == "Limpar lista" and len(nomes) == 10
assert j.menu_recentes.isEnabled()
acao = next(a for a in j.menu_recentes.actions() if a.text() == "t10.revelador")
acao.trigger()                                                         # abre o trabalho recente
assert ui.estado.trabalho.caminho == arquivos[10]
ui.limpar_recentes()
assert ui.recentes() == [] and not j.menu_recentes.isEnabled()
print("ok")
""")


def test_recuperacao_gravada_oferecida_e_apagada():
    rodar("""
j = janela_com_fotos(2)
ui, est = j.projeto_ui, j.estado
assert ui.timer.interval() == 120000 and ui.timer.isActive()
est.marcar_modificado(False)
assert ui.autossalvar() is None and projeto.listar_recuperacao() == []   # limpo: não grava
est.marcar_modificado()
arq = ui.autossalvar()
assert arq is not None and arq.is_file() and projeto.listar_recuperacao() == [arq]
destino = RAIZ / "s" / "ok.revelador"
ui.escolher_arquivo_salvar = lambda: destino
assert ui.salvar() and projeto.listar_recuperacao() == []                 # salvar apaga a recuperação

est.marcar_modificado()
arq = ui.autossalvar()                                                    # ...e agora o app "cai"
assert arq is not None
k = MainWindow()                                                          # próxima abertura do app
assert "recuperacao" in k.faixas.faixas
assert "Quer restaurar" in k.faixas.textos()["recuperacao"]
k.faixas.faixas["recuperacao"].botoes["Restaurar"].click()
assert len(k.estado.trabalho.fotos) == 2 and k.estado.modificado
assert k.estado.trabalho.caminho is None and k.windowTitle().startswith("• ")
assert projeto.listar_recuperacao() == [] and "recuperacao" not in k.faixas.faixas
k.show()
respostas = [pu.DESCARTAR]
k.projeto_ui.perguntar_salvar = lambda: respostas.pop(0)
assert k.close() and projeto.listar_recuperacao() == []

# descartar a oferta apaga o arquivo
est.marcar_modificado(); ui.autossalvar()
m = MainWindow()
m.faixas.faixas["recuperacao"].botoes["Descartar"].click()
assert projeto.listar_recuperacao() == [] and not m.faixas.faixas
print("ok")
""")


def test_foto_movida_e_marcada_e_religada_pela_pasta_nova():
    rodar("""
j = janela_com_fotos(3)
ui, est = j.projeto_ui, j.estado
destino = RAIZ / "w" / "viagem.revelador"
ui.escolher_arquivo_salvar = lambda: destino
assert ui.salvar()
originais = [f.caminho for f in est.trabalho.fotos]
nova = RAIZ / "novo_lugar" / "sub"
nova.mkdir(parents=True)
for p in originais[:2]:
    shutil.move(str(p), str(nova / p.name))                               # duas fotos mudaram de pasta

assert ui.abrir(destino)
ids = [f.id for f in est.trabalho.fotos]
assert "faltando" in j.faixas.faixas and "2 fotos" in j.faixas.textos()["faltando"]
assert set(est.erros) == set(ids[:2])
assert pronto(j) and set(est.erros) == set(ids[:2]) and ids[2] in est.miniaturas

ui.escolher_pasta_busca = lambda: RAIZ / "novo_lugar"                    # a pessoa aponta a pasta nova
j.faixas.faixas["faltando"].botoes["Procurar…"].click()
assert [f.caminho for f in est.trabalho.fotos[:2]] == [nova / p.name for p in originais[:2]]
assert est.trabalho.fotos[2].caminho == originais[2]
assert not est.erros and "faltando" not in j.faixas.faixas and est.modificado
assert esperar(lambda: len(est.miniaturas) == 3)                          # as religadas ganham miniatura
assert not est.erros
assert ui.procurar_faltando(RAIZ) == 0                                   # nada mais a procurar
print("ok")
""")


def test_arquivo_ruim_e_formato_novo_viram_faixa_de_erro():
    rodar("""
j = MainWindow()
ui = j.projeto_ui
ruim = RAIZ / "ruim.revelador"
ruim.write_text("{ não é json", encoding="utf-8")
assert ui.abrir(ruim) is False and "danificado" in j.faixas.textos()["erro"]
novo = RAIZ / "novo.revelador"
novo.write_text('{"app": "Revelador", "formato": 999, "fotos": []}', encoding="utf-8")
assert ui.abrir(novo) is False and "versão mais nova" in j.faixas.textos()["erro"]
assert ui.abrir(RAIZ / "nao_existe.revelador") is False
print("ok")
""")


def test_linha_de_comando_abre_o_trabalho():
    rodar("""
from PySide6.QtCore import QTimer
from revelador import app as revapp
foto = fotos(1)[0]
t = Trabalho()
from revelador.projeto import Foto
t.fotos.append(Foto(id="x1", caminho=foto, selecionada=False, rostos=[]))
alvo = RAIZ / "cmd" / "linha.revelador"
projeto.salvar(t, alvo)
resultado = {}

def conferir():
    try:
        jan = next(w for w in app.topLevelWidgets() if isinstance(w, MainWindow))
        resultado["titulo"] = jan.windowTitle()
        resultado["fotos"] = [f.caminho.name for f in jan.estado.trabalho.fotos]
        resultado["caminho"] = jan.estado.trabalho.caminho
        jan.projeto_ui.perguntar_salvar = lambda: pu.DESCARTAR
    finally:
        app.quit()

QTimer.singleShot(1500, conferir)
outra = fotos(1, "outras")[0]
revapp.main([str(alvo), str(outra)])
assert resultado["titulo"].endswith("linha — Revelador"), resultado
assert resultado["caminho"] == alvo
assert resultado["fotos"] == ["img_0.jpg", "img_0.jpg"], resultado
print("ok")
""")
