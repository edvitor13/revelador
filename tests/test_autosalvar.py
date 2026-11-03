"""Salvamento automático (#34) e o diálogo de Configurações (subprocesso offscreen, pastas temporárias)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from conftest import rodar_python

from revelador.ui import autosalvar

PREAMBULO = """
import json, os, sys, tempfile, time
from pathlib import Path
RAIZ = Path(tempfile.mkdtemp(prefix="rev_auto_"))
os.environ["REVELADOR_SETTINGS_DIR"] = str(RAIZ / "prefs")   # preferências só deste caso
os.environ["LOCALAPPDATA"] = str(RAIZ / "local")             # recuperação isolada
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv[:1])
from PIL import Image
from revelador import projeto
from revelador.ui.main_window import MainWindow
from revelador.ui import autosalvar as auto, projeto_ui as pu

TRABALHOS = RAIZ / "prefs" / "Trabalhos"        # pasta padrão no modo portátil/testes


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


def girar(ms):
    fim = time.time() + ms / 1000
    while time.time() < fim:
        app.processEvents()
        time.sleep(0.01)


def acelerar(j):
    j.autosalvar.ms_por_minuto = 60              # "1 minuto" vira 60 ms
    j.autosalvar.aplicar_preferencias()


def janela(importar=None, n=2, rapido=True):
    j = MainWindow()
    j.show()
    j.projeto_ui.perguntar_salvar = lambda: (_ for _ in ()).throw(AssertionError("perguntou"))
    if rapido:
        acelerar(j)
    if importar is not None or n:
        j.importar(importar if importar is not None else [str(p) for p in fotos(n)], marcar=False)
        nf = len(j.estado.trabalho.fotos)
        assert esperar(lambda: len(j.estado.info) + len(j.estado.erros) >= nf and not j.importacao.ocupado)
        assert esperar(lambda: all(f.rostos is not None for f in j.estado.trabalho.fotos))
    return j


def ler(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))
"""


def rodar(corpo: str) -> None:
    p = rodar_python(PREAMBULO + corpo, timeout=120)
    assert p.returncode == 0, p.stderr
    assert p.stdout.strip().endswith("ok"), p.stdout + p.stderr


# --------------------------------------------------------------------------------------------------------------------
# Funções puras
# --------------------------------------------------------------------------------------------------------------------
def test_arquivo_livre_nunca_sobrescreve(tmp_path: Path):
    assert autosalvar.arquivo_livre(tmp_path, "Festa") == tmp_path / "Festa.revelador"
    (tmp_path / "Festa.revelador").write_text("x", encoding="utf-8")
    assert autosalvar.arquivo_livre(tmp_path, "Festa") == tmp_path / "Festa (2).revelador"
    (tmp_path / "Festa (2).revelador.tmp").write_text("x", encoding="utf-8")   # gravação de outro em curso
    assert autosalvar.arquivo_livre(tmp_path, "Festa") == tmp_path / "Festa (3).revelador"


def test_nomes_automaticos():
    assert autosalvar.nome_por_data(datetime(2026, 11, 3, 14, 5)) == "Revelação 2026-11-03 14-05"
    assert autosalvar.limpar_nome('Viagem: "praia"?. ') == "Viagem   praia"
    assert autosalvar.limpar_nome("...") == ""


# --------------------------------------------------------------------------------------------------------------------
# Interface
# --------------------------------------------------------------------------------------------------------------------
def test_alteracao_grava_no_proprio_arquivo_sem_tocar_nas_fotos():
    rodar("""
j = janela(rapido=False)
ui, est = j.projeto_ui, j.estado
assert j.autosalvar.ligado and j.autosalvar.timer.interval() == 60000      # padrão: 1 minuto
destino = RAIZ / "meus" / "casa.revelador"
ui.escolher_arquivo_salvar = lambda: destino
assert ui.salvar() and not est.modificado and not auto.e_automatico(destino)
acelerar(j)
assert j.autosalvar.timer.interval() == 60
assert j.autosalvar.indicador.text().startswith("Salvo às")
originais = {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in (RAIZ / "fotos").iterdir()}
a = est.trabalho.fotos[0]
est.selecionar(a)
a.ajustes = {"exposicao": 15.0}
est.alterar(a, pedido=True)
assert est.modificado
salvos = []
j.autosalvar.salvo.connect(salvos.append)
assert esperar(lambda: not est.modificado)
assert salvos == [destino.absolute()] and est.trabalho.caminho == destino.absolute()
d = ler(destino)
assert d["fotos"][0]["selecionada"] is True and d["fotos"][0]["ajustes"] == {"exposicao": 15.0}
assert d["fotos"][0]["caminho"] == "../fotos/img_0.jpg"                # relativo, como no "Salvar"
assert j.autosalvar.indicador.text().startswith("Salvo às") and "•" not in j.windowTitle()
assert not TRABALHOS.exists()                                         # nada criado na pasta automática
assert {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in (RAIZ / "fotos").iterdir()} == originais
assert not list(destino.parent.glob("*.tmp"))
print("ok")
""")


def test_trabalho_novo_ganha_nome_e_pasta_e_entra_nos_recentes():
    rodar("""
pasta = RAIZ / "Casamento Ana"
fotos(2, "Casamento Ana")
j = janela(importar=[str(pasta)])                  # importou uma pasta: o trabalho leva o nome dela
ui, est = j.projeto_ui, j.estado
assert esperar(lambda: not est.modificado)        # gravou sozinho (o temporizador corre durante a importação)
alvo = (TRABALHOS / "Casamento Ana.revelador").absolute()
assert est.trabalho.caminho == alvo and alvo.is_file() and auto.e_automatico(alvo)
assert ui.recentes()[0] == alvo and j.windowTitle() == "Casamento Ana — Revelador"
assert len(ler(alvo)["fotos"]) == 2

k = janela(importar=[str(pasta)])                  # mesmo nome de novo: nome livre, sem sobrescrever
assert esperar(lambda: not k.estado.modificado)
assert k.estado.trabalho.caminho == (TRABALHOS / "Casamento Ana (2).revelador").absolute()

antes = time.strftime("%Y-%m-%d")
m = janela(n=1)                                     # só arquivos: nome pela data e hora
assert esperar(lambda: not m.estado.modificado)
nome = m.estado.trabalho.caminho.name
assert nome.startswith("Revelação " + antes) and nome.endswith(".revelador"), nome
assert m.estado.trabalho.caminho.parent == TRABALHOS.absolute()

vazia = janela(n=0)                                 # trabalho novo sem fotos não vira arquivo
vazia.estado.marcar_modificado()
girar(300)
assert vazia.estado.trabalho.caminho is None and len(list(TRABALHOS.glob("*.revelador"))) == 3
print("ok")
""")


def test_salvar_como_move_e_apaga_o_automatico():
    rodar("""
j = janela()
ui, est = j.projeto_ui, j.estado
assert esperar(lambda: not est.modificado)
automatico = est.trabalho.caminho
assert auto.e_automatico(automatico) and automatico.is_file()
destino = RAIZ / "meus" / "festa"
ui.escolher_arquivo_salvar = lambda: destino
assert ui.salvar()                                   # Ctrl+S num automático pergunta onde (e move)
novo = (RAIZ / "meus" / "festa.revelador").absolute()
assert est.trabalho.caminho == novo and novo.is_file()
assert not automatico.exists() and not auto.e_automatico(automatico) and not auto.e_automatico(novo)
assert automatico not in ui.recentes() and ui.recentes()[0] == novo
assert ui.salvar() and est.trabalho.caminho == novo       # agora é arquivo da pessoa: grava direto

outro = RAIZ / "meus" / "copia.revelador"                 # "Salvar como" de arquivo da pessoa não apaga nada
ui.escolher_arquivo_salvar = lambda: outro
assert ui.salvar_como() and novo.is_file() and outro.is_file()

k = janela()                                              # adotar o próprio automático: nada é apagado
assert esperar(lambda: not k.estado.modificado)
arq = k.estado.trabalho.caminho
k.projeto_ui.escolher_arquivo_salvar = lambda: arq
assert k.projeto_ui.salvar_como() and arq.is_file() and not auto.e_automatico(arq)
print("ok")
""")


def test_sem_alteracoes_nada_e_gravado():
    rodar("""
j = janela(rapido=False)
ui, est = j.projeto_ui, j.estado
destino = RAIZ / "meus" / "quieto.revelador"
ui.escolher_arquivo_salvar = lambda: destino
assert ui.salvar()
acelerar(j)
antes = (destino.stat().st_mtime_ns, destino.read_bytes())
chamadas = []
original = projeto.gravar_texto_seguro
projeto.gravar_texto_seguro = lambda *a: chamadas.append(a) or original(*a)
girar(400)                                            # vários intervalos sem alteração
assert chamadas == [] and (destino.stat().st_mtime_ns, destino.read_bytes()) == antes
assert not TRABALHOS.exists()
print("ok")
""")


def test_gravacao_em_segundo_plano_e_alteracao_no_meio():
    rodar("""
import threading
j = janela(rapido=False)
ui, est = j.projeto_ui, j.estado
destino = RAIZ / "meus" / "lento.revelador"
ui.escolher_arquivo_salvar = lambda: destino
assert ui.salvar()
original = projeto.gravar_texto_seguro
liberar = threading.Event()
threads = []
def lento(caminho, texto):
    threads.append(threading.current_thread() is threading.main_thread())
    liberar.wait(10)
    original(caminho, texto)
projeto.gravar_texto_seguro = lento
a = est.trabalho.fotos[0]
est.selecionar(a)
est.alterar(a, pedido=True)
t0 = time.time()
j.autosalvar.tique()                                    # não trava: volta antes de a gravação acabar
assert time.time() - t0 < 1 and j.autosalvar.gravando and j.autosalvar.indicador.text() == "Salvando…"
assert esperar(lambda: threads == [False])              # grava fora da thread principal
b = est.trabalho.fotos[1]
est.selecionar(b)                                       # mexeu durante a gravação
est.alterar(b, pedido=True)
liberar.set()
assert esperar(lambda: not j.autosalvar.gravando)
assert est.modificado                                   # a mudança do meio ainda não está no arquivo
assert ler(destino)["fotos"][1].get("selecionada") is None
projeto.gravar_texto_seguro = original
j.autosalvar.tique()
assert esperar(lambda: not est.modificado) and ler(destino)["fotos"][1]["selecionada"] is True
print("ok")
""")


def test_fechar_salva_sem_perguntar():
    rodar("""
j = janela(rapido=False)                                # intervalo normal: só o fechamento grava
est = j.estado
assert est.modificado and est.trabalho.caminho is None
assert j.close() is True                                # perguntar_salvar levantaria erro
salvos = list(TRABALHOS.glob("*.revelador"))
assert len(salvos) == 1 and len(ler(salvos[0])["fotos"]) == 2 and auto.e_automatico(salvos[0])
assert not j.autosalvar.timer.isActive()

k = MainWindow()
k.show()
k.projeto_ui.perguntar_salvar = lambda: (_ for _ in ()).throw(AssertionError("perguntou"))
assert k.projeto_ui.abrir(salvos[0])
f = k.estado.trabalho.fotos[0]
k.estado.selecionar(f)
k.estado.alterar(f, pedido=True)
assert k.projeto_ui.novo()                              # trocar de trabalho também grava sem perguntar
assert ler(salvos[0])["fotos"][0]["selecionada"] is True and projeto.listar_recuperacao() == []
print("ok")
""")


def test_falha_mostra_faixa_e_mantem_modificado():
    rodar("""
j = janela(rapido=False)
ui, est = j.projeto_ui, j.estado
falhas = []
j.autosalvar.falhou.connect(falhas.append)
original = projeto.gravar_texto_seguro
def quebrada(caminho, texto):
    raise PermissionError(13, "Permissão negada")
projeto.gravar_texto_seguro = quebrada
acelerar(j)
assert esperar(lambda: len(falhas) >= 3)               # tenta de novo a cada intervalo...
assert "autosalvar" in j.faixas.faixas                   # ...mas a faixa aparece uma vez, sem diálogo
assert "Permissão negada" in j.faixas.textos()["autosalvar"]
assert est.modificado and est.trabalho.caminho is None and j.autosalvar.indicador.text() == "Não salvo"
assert not TRABALHOS.exists() or not list(TRABALHOS.glob("*.revelador"))

respostas = []
ui.perguntar_salvar = lambda: respostas.append(1) or pu.CANCELAR
assert j.close() is False and respostas == [1]           # ao fechar, a falha devolve a pergunta: nada se perde

projeto.gravar_texto_seguro = original
assert esperar(lambda: not est.modificado)             # voltou a funcionar: grava e tira a faixa
assert "autosalvar" not in j.faixas.faixas and j.autosalvar.indicador.text().startswith("Salvo às")

k = janela(rapido=False)                                 # pasta impossível (dentro de um arquivo)
bloqueio = RAIZ / "arquivo.txt"
bloqueio.write_text("x", encoding="utf-8")
auto.gravar_preferencias(ligar=True, minutos=1, pasta=bloqueio / "Trabalhos")
acelerar(k)
assert esperar(lambda: "autosalvar" in k.faixas.faixas)
assert k.estado.modificado and k.estado.trabalho.caminho is None
print("ok")
""")


def test_configuracoes_desligar_intervalo_e_pasta():
    rodar("""
j = janela(n=0)
assert j.acao_configuracoes.isEnabled()
d = j.criar_dialogo_configuracoes()
s = d.secoes["salvamento"]
assert s.ligado.isChecked() and s.intervalo.value() == 1 and s.pasta == TRABALHOS
nova = RAIZ / "outra pasta"
s.escolher_pasta = lambda: nova
s.botao_pasta.click()
s.intervalo.setValue(5)
assert d.salvar()
assert auto.pasta_trabalhos() == nova and auto.intervalo_min() == 5
assert j.autosalvar.timer.interval() == 5 * 60 and j.autosalvar.ligado
s.restaurar_padrao()
assert s.pasta == TRABALHOS and s.intervalo.value() == 1 and s.ligado.isChecked()
s.definir_pasta(nova)

s.ligado.setChecked(False)                              # desligado: nada automático e a pergunta volta
assert not s.intervalo.isEnabled() and d.salvar() and not j.autosalvar.ligado and not auto.ligado()
d2 = j.criar_dialogo_configuracoes()                    # reabrir mostra o que foi salvo
assert not d2.secoes["salvamento"].ligado.isChecked() and d2.secoes["salvamento"].pasta == nova

k = janela()                                            # janela nova já começa desligada
assert not k.autosalvar.ligado
girar(300)
assert k.estado.modificado and k.estado.trabalho.caminho is None
respostas = []
k.projeto_ui.perguntar_salvar = lambda: respostas.append(1) or pu.DESCARTAR
assert k.close() is True and respostas == [1] and not nova.exists()
print("ok")
""")
