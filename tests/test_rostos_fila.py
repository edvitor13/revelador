"""Fila de rostos aos poucos (#36), em subprocesso offscreen.

A detecção de verdade (``rostos.detectar``) é trocada por uma função falsa que conta quantas rodam ao mesmo tempo,
dorme um pouco e devolve um rosto fixo. A ordem de entrega ao pool (``despacho``) é gravada trocando a tarefa de
rostos por uma subclasse; a ordem de chegada (``ordem``), envolvendo ``Estado.definir_rostos``.
"""

from __future__ import annotations

from conftest import rodar_python

PREAMBULO = """
import os, sys, threading, time
from pathlib import Path
from tempfile import mkdtemp
from PIL import Image
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv[:1])
from revelador import rostos as _rostos
from revelador.projeto import Rosto
from revelador.ui.main_window import MainWindow
from revelador.ui import tarefas
from revelador.ui.tarefas import limite_rostos

ROSTO = Rosto(0.4, 0.3, 0.1, 0.13, None, 0.9)
trava = threading.Lock()
conta = {"agora": 0, "max": 0, "chamadas": 0, "antes_das_miniaturas": 0}
ATRASO = [0.05]
JANELA = []

def falso(rgb):
    with trava:
        conta["agora"] += 1
        conta["chamadas"] += 1
        conta["max"] = max(conta["max"], conta["agora"])
    time.sleep(ATRASO[0])
    with trava:
        conta["agora"] -= 1
    return [ROSTO]

_rostos.detectar = falso

despacho = []                                       # ordem em que a fila entrega as fotos ao pool

class _Gravada(tarefas._TarefaRostos):
    def __init__(self, foto_id, *args):
        despacho.append(foto_id)
        super().__init__(foto_id, *args)

tarefas._TarefaRostos = _Gravada

def esperar(cond, ms=30000):
    fim = time.time() + ms / 1000
    while time.time() < fim:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.005)
    return False

def pausa(ms):
    fim = time.time() + ms / 1000
    while time.time() < fim:
        app.processEvents()
        time.sleep(0.005)

def pasta_com(n):
    d = Path(mkdtemp(prefix="fotos_"))
    for i in range(n):
        Image.new("RGB", (400 + i, 300), (i * 20 % 255, 90, 150)).save(d / f"f{i:02d}.jpg")
    return d

def janela():
    j = MainWindow(); j.resize(1200, 800); j.show()
    ordem = []
    orig = j.estado.definir_rostos
    def gravar(fid, achados):
        ordem.append(fid)
        orig(fid, achados)
    j.estado.definir_rostos = gravar
    return j, ordem

def miniaturas_prontas(j):
    return j.importacao._feitas >= j.importacao._total

def pronto(j):
    return esperar(lambda: not j.importacao.ocupado and j.importacao._total == 0)
"""


def rodar(corpo: str) -> None:
    p = rodar_python(PREAMBULO + corpo, timeout=180)
    assert p.returncode == 0, p.stderr
    assert p.stdout.strip().endswith("ok"), p.stdout + p.stderr


def test_limite_de_trabalhadores():
    rodar("""
assert limite_rostos(1) == limite_rostos(4) == limite_rostos(7) == 1
assert limite_rostos(8) == limite_rostos(32) == 2
j, ordem = janela()
fila = j.importacao.rostos
assert fila.limite == limite_rostos(os.cpu_count()) and fila.pool.maxThreadCount() == fila.limite
print("ok")
""")


def test_nunca_passa_do_limite_e_espera_as_miniaturas():
    rodar("""
_falso = _rostos.detectar
def falso_vigiado(rgb):
    if not miniaturas_prontas(J[0]):
        conta["antes_das_miniaturas"] += 1
    return _falso(rgb)
_rostos.detectar = falso_vigiado
J = []
j, ordem = janela(); J.append(j)
mensagens = []
j.importacao.mensagem.connect(mensagens.append)
j.estado.definir_atual(None)
j.importar([pasta_com(12)])
assert pronto(j)
assert conta["chamadas"] == 12 and len(ordem) == 12 and len(set(ordem)) == 12
assert 1 <= conta["max"] <= j.importacao.rostos.limite, conta
assert conta["antes_das_miniaturas"] == 0          # nada furou a fila: rostos só depois das miniaturas
assert any(m.startswith("Rostos: ") and m.endswith(" de 12") for m in mensagens), mensagens
assert mensagens[-1] == "Pronto." and j.statusBar().currentMessage() == "Pronto."
assert all(f.rostos == [ROSTO] for f in j.estado.trabalho.fotos)
print("ok")
""")


def test_foto_aberta_ou_marcada_fura_a_fila():
    rodar("""
ATRASO[0] = 0.12
j, ordem = janela()
e = j.estado
fotos = j.importar([pasta_com(10)])
e.definir_atual(fotos[-1])                          # a última da fila, aberta no editor: vai primeiro
assert esperar(lambda: len(despacho) >= 1)
assert despacho[0] == fotos[-1].id, despacho
assert esperar(lambda: len(ordem) >= 2)
k = len(despacho)
assert fotos[-2].id not in despacho and fotos[-3].id not in despacho
e.definir_atual(fotos[-2])                          # outra do fim, no meio do caminho
e.selecionar(fotos[-3])                             # recém-marcada para revelar
assert pronto(j)
# as duas são as próximas entregues (a mais recente primeiro), antes de qualquer outra
assert despacho[k:k + 2] == [fotos[-3].id, fotos[-2].id], (despacho, k)
assert len(despacho) == len(ordem) == 10 and conta["max"] <= j.importacao.rostos.limite
print("ok")
""")


def test_fotos_na_tela_vem_antes_do_resto():
    rodar("""
j, ordem = janela()
e = j.estado
e.definir_exportando(True)                          # segura a fila enquanto a grade rola
fotos = j.importar([pasta_com(40)])
assert esperar(lambda: miniaturas_prontas(j))
e.definir_atual(None)
j.grade.lista.scrollToBottom()
assert esperar(lambda: e.na_tela and e.na_tela[-1] == fotos[-1].id)
na_tela = list(e.na_tela)
assert fotos[0].id not in na_tela and set(na_tela) <= set(e.visiveis)
assert na_tela == [i for i in e.visiveis if i in set(na_tela)]   # na ordem da grade
pausa(200)
assert conta["chamadas"] == 0 and j.importacao.ocupado           # pausada: nada começou
e.definir_exportando(False)
assert pronto(j)
assert despacho[:len(na_tela)] == na_tela, (despacho, na_tela)
assert despacho[len(na_tela):] == [i for i in e.visiveis if i not in set(na_tela)]  # depois, a ordem da grade
assert sorted(ordem) == sorted(despacho)
print("ok")
""")


def test_pausa_durante_a_exportacao():
    rodar("""
ATRASO[0] = 0.1
j, ordem = janela()
e = j.estado
fotos = j.importar([pasta_com(8)])
e.definir_atual(None)
assert esperar(lambda: conta["chamadas"] >= 1)
e.definir_exportando(True)
pausa(50)
feitas = conta["chamadas"]
pausa(500)
assert conta["chamadas"] == feitas and conta["agora"] == 0      # as que já rodavam terminam; nenhuma começa
assert j.importacao.ocupado and len(ordem) < 8
e.definir_exportando(False)
assert pronto(j) and len(ordem) == 8

# o diálogo de exportação avisa o Estado ao começar e ao terminar
e.selecionar(fotos[0])
d = j.criar_dialogo_exportacao()
d.definir_destino(Path(mkdtemp(prefix="saida_")))
assert d.iniciar()
assert e.exportando
assert d.aguardar(60000) and d.resultado is not None
assert not e.exportando
print("ok")
""")


def test_rostos_salvos_nao_sao_detectados_de_novo_e_foto_alterada_e():
    rodar("""
from revelador.imagem import InfoFoto
from revelador.projeto import Foto, Trabalho
from revelador.ui.estado import Estado

d = pasta_com(3)
a, b, c = sorted(d.glob("*.jpg"))
guardado = Rosto(0.1, 0.1, 0.2, 0.25, None, 0.8)
def dados(p):
    st = p.stat()
    return st.st_size, st.st_mtime_ns / 1e9
fa = Foto(id="a", caminho=a, rostos=[guardado]); fa.bytes, fa.mtime = dados(a)
fb = Foto(id="b", caminho=b, rostos=[guardado]); fb.bytes, fb.mtime = dados(b)
fc = Foto(id="c", caminho=c)                        # nunca detectada
Image.new("RGB", (900, 700), (10, 200, 30)).save(b)  # b mudou no disco depois de salvo o trabalho
os.utime(b, ns=(time.time_ns(), time.time_ns() + 5_000_000_000))

j, ordem = janela()
t = Trabalho(); t.fotos = [fa, fb, fc]
j.estado.definir_trabalho(t)
assert pronto(j)
assert sorted(ordem) == ["b", "c"] and conta["chamadas"] == 2, ordem
assert fa.rostos == [guardado]                      # foto igual: rostos guardados, sem detectar de novo
assert fb.rostos == [ROSTO] and fc.rostos == [ROSTO]

# Estado.definir_info: só zera os rostos quando bytes/mtime do disco diferem dos guardados
e = Estado()
f = Foto(id="x", caminho=a, rostos=[guardado], bytes=100, mtime=5.0)
e.trabalho.fotos.append(f)
e.definir_info("x", InfoFoto(400, 300, None, None, None, 100, 5_000_000_000))
assert f.rostos == [guardado]
e.definir_info("x", InfoFoto(400, 300, None, None, None, 101, 5_000_000_000))
assert f.rostos is None and f.bytes == 101
f.rostos = [guardado]
e.definir_info("x", InfoFoto(400, 300, None, None, None, 101, 9_000_000_000))
assert f.rostos is None and f.mtime == 9.0
g = Foto(id="y", caminho=a, rostos=[guardado])       # sem bytes/mtime guardados: não há como comparar
e.trabalho.fotos.append(g)
e.definir_info("y", InfoFoto(400, 300, None, None, None, 7, 1))
assert g.rostos == [guardado]
print("ok")
""")


def test_enquadrar_pelos_rostos_detecta_na_hora():
    rodar("""
j, ordem = janela()
e = j.estado
fotos = j.importar([pasta_com(1)])
assert pronto(j)
foto = fotos[0]
e.definir_atual(foto)
e.selecionar(foto)
assert esperar(lambda: j.editor.proxy is not None)
imp = foto.impressoes[0]
from dataclasses import replace
imp.recorte = replace(imp.recorte, cx=0.3, origem="manual")
foto.rostos = None                                  # como uma foto que ainda não foi detectada
pedidos = []
e.rostos_pedidos.connect(pedidos.append)
assert j.editor.enquadrar_pelos_rostos()
assert pedidos == [foto.id] and imp.recorte.origem != "manual"
assert esperar(lambda: foto.rostos is not None)
assert foto.rostos == [ROSTO] and imp.recorte.origem == "auto"
assert not e.pedir_rostos(foto)                     # já tem rostos: nada a pedir
print("ok")
""")
