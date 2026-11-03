"""Tela de boas-vindas (#35): quando aparece, recentes, recuperação, novidades e aviso de atualização.

As funções puras rodam aqui; a interface, só em subprocesso *offscreen* (``rodar_python``). Trabalhos e fotos são
gerados no código, em pastas temporárias; a rede é simulada trocando ``updater.check``.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
from PIL import Image

from conftest import rodar_python
from revelador import __version__, projeto
from revelador.projeto import Foto, Impressao, Trabalho
from revelador.ui import boas_vindas


def _foto(caminho: Path, cor: tuple[int, int, int]) -> Path:
    Image.fromarray(np.full((60, 90, 3), cor, np.uint8)).save(caminho, quality=90)
    return caminho


def _trabalho(pasta: Path, nome: str, n: int = 3, selecionadas: int = 2, tamanhos=("10x15", "13x18")) -> Path:
    pasta.mkdir(parents=True, exist_ok=True)
    fotos = []
    for i in range(n):
        f = Foto(id=f"{nome}{i}", caminho=_foto(pasta / f"{nome}_{i}.jpg", (40 * i % 255, 120, 200)))
        if i < selecionadas:
            f.selecionada = True
            f.impressoes = [Impressao(tamanho=tamanhos[i % len(tamanhos)])]
        fotos.append(f)
    destino = pasta / f"{nome}.revelador"
    projeto.salvar(Trabalho(fotos=fotos), destino)
    return destino


# ------------------------------------------------------------------ funções puras
def test_resumir_trabalho(tmp_path):
    caminho = _trabalho(tmp_path, "casamento", n=5, selecionadas=2)
    r = boas_vindas.resumir_trabalho(caminho)
    assert r.erro == "" and r.nome == "casamento"
    assert (r.fotos, r.selecionadas) == (5, 2)
    assert r.tamanhos == ["10x15", "13x18"]
    assert len(r.miniaturas) == boas_vindas.MAX_MINIATURAS and all(m.is_file() for m in r.miniaturas)
    assert r.salvo_em == caminho.stat().st_mtime
    assert boas_vindas.texto_conteudo(r) == "5 fotos · 2 selecionadas · 10x15, 13x18"


def test_resumir_trabalho_danificado_e_sem_fotos(tmp_path):
    ruim = tmp_path / "ruim.revelador"
    ruim.write_text("{ isto não é json", encoding="utf-8")
    assert boas_vindas.resumir_trabalho(ruim).erro
    vazio = tmp_path / "vazio.revelador"
    projeto.salvar(Trabalho(), vazio)
    r = boas_vindas.resumir_trabalho(vazio)
    assert (r.fotos, r.selecionadas, r.miniaturas, r.erro) == (0, 0, [], "")
    assert boas_vindas.texto_conteudo(r) == "0 fotos · nenhuma selecionada"


def test_nomes_tamanhos_na_ordem_da_tabela():
    assert boas_vindas.nomes_tamanhos({"20x30", "personalizado", "10x15", "a4"}) == [
        "10x15", "20x30", "A4 (21x29,7)", "Personalizado"]


def test_resumo_das_novidades():
    texto = "# Revelador 1.2.3\n\n<!-- nota -->\nIntro.\n\n## Novidades\n- um\n\n---\n\nDetalhes\n"
    assert boas_vindas.resumo_novidades(texto) == "Intro.\n\n**Novidades**\n- um"
    assert boas_vindas.corpo_novidades(texto).startswith("Intro.")
    assert boas_vindas.corpo_novidades(texto).endswith("Detalhes")


def test_arquivo_de_novidades_da_versao_atual(raiz):
    arquivo = boas_vindas.arquivo_novidades()
    assert arquivo == raiz / "revelador" / "novidades" / f"release_v{__version__}.md"
    texto = boas_vindas.texto_novidades()
    assert texto.startswith(f"# Revelador {__version__}")
    assert boas_vindas.resumo_novidades(texto) and "---" in texto
    assert boas_vindas.texto_novidades("99.0.0") == ""


def test_spec_inclui_as_novidades(raiz):
    spec = (raiz / "Revelador.spec").read_text(encoding="utf-8")
    assert '"novidades"' in spec


# ------------------------------------------------------------------ interface (subprocesso offscreen)
PREAMBULO = r"""
import json, os, sys, time
from pathlib import Path
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv[:1])
from revelador import __version__, projeto, updater
from revelador.ui import boas_vindas, prefs, tema
from revelador.ui.main_window import MainWindow
tema.instalar(app)
for _chave in ("boas_vindas", "projeto/recentes", "atualizacao"):   # as preferências dos testes são compartilhadas
    prefs.settings().remove(_chave)


def esperar(cond, maximo=10.0):
    fim = time.time() + maximo
    while time.time() < fim:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.02)
    app.processEvents()
    return cond()


def janela():
    j = MainWindow()
    j.salvar_estado = lambda: None
    j.show()
    app.processEvents()
    return j


def fechar(j):
    j.estado.marcar_modificado(False)
    j.boas_vindas._pool.waitForDone(5000)
    j.editor.encerrar()
    j.close()
"""


def rodar(corpo: str, **valores) -> None:
    codigo = PREAMBULO + "".join(f"{k} = {v!r}\n" for k, v in valores.items()) + corpo
    p = rodar_python(codigo, timeout=90)
    assert p.returncode == 0, p.stderr[-4000:]
    assert p.stdout.strip().endswith("ok"), p.stdout + p.stderr[-2000:]


def test_aparece_sem_argumentos_e_nao_com_arquivo(tmp_path):
    trabalho = str(_trabalho(tmp_path, "festa"))
    foto = str(tmp_path / "festa_0.jpg")
    rodar(r"""
QApplication.exec = lambda self=None: 0     # app.main sem laço de eventos
from revelador import app as modapp


def abrir(args):
    antes = set(QApplication.topLevelWidgets())
    assert modapp.main(args) == 0
    novas = [w for w in QApplication.topLevelWidgets() if isinstance(w, MainWindow) and w not in antes]
    app.processEvents()
    return novas[0]


j = abrir([])
assert j.boas_vindas.visivel() and not j.divisor.isVisible(), "sem argumentos: a tela aparece"
pg = j.boas_vindas.pagina
assert pg.chave_mostrar.isChecked()
assert set(pg.botoes_acao) == {"importar", "importar_pasta", "novo", "abrir"}
assert j.acao_boas_vindas.isEnabled()
assert prefs.settings().value(boas_vindas.CHAVE_VERSAO_VISTA, "", str) == __version__
assert j.boas_vindas.dialogo_novidades is None, "primeira execução: as novidades não abrem sozinhas"
assert pg.estado_atualizacao == "versao", "REVELADOR_SEM_REDE: só a versão"
assert "0.1.0" in pg.rotulo_versao.text() or __version__ in pg.rotulo_versao.text()
pg.botoes_acao["novo"].click()                 # Novo trabalho: o trabalho troca e a tela sai
assert not j.boas_vindas.visivel() and j.divisor.isVisible()
j.acao_boas_vindas.trigger()                   # a engrenagem abre de novo
assert j.boas_vindas.visivel()
pg.fechar_pedido.emit()
assert not j.boas_vindas.visivel()
fechar(j)

k = abrir([TRABALHO])
assert k.estado.trabalho.caminho is not None and not k.boas_vindas.visivel(), "com .revelador: não aparece"
fechar(k)
m = abrir([FOTO])
assert not m.boas_vindas.visivel(), "com foto: não aparece"
fechar(m)
boas_vindas.definir_mostrar_ao_abrir(False)
n = abrir([])
assert not n.boas_vindas.visivel(), "preferência desligada"
fechar(n)
print("ok")
""", TRABALHO=trabalho, FOTO=foto)


def test_recentes_listam_os_dados_certos_e_abrem(tmp_path):
    t1 = str(_trabalho(tmp_path / "a", "aniversario", n=5, selecionadas=3, tamanhos=("10x15", "20x30")))
    t2 = str(_trabalho(tmp_path / "b", "viagem", n=2, selecionadas=0))
    sumido = str(tmp_path / "nao_existe.revelador")
    rodar(r"""
prefs.settings().setValue("projeto/recentes", json.dumps([T1, SUMIDO, T2]))
j = janela()
bv = j.boas_vindas
bv.mostrar()
pg = bv.pagina
assert [str(i.caminho) for i in pg.itens] == [T1, T2], "o inexistente some"
assert SUMIDO not in prefs.settings().value("projeto/recentes", "", str)
assert pg.itens[0].textos()[1] == "Lendo…"
assert esperar(lambda: not bv.ocupado() and all(i.resumo for i in pg.itens))
a, b = pg.itens
assert (a.resumo.fotos, a.resumo.selecionadas, a.resumo.tamanhos) == (5, 3, ["10x15", "20x30"])
assert len(a.imagens) == 4 and not a.imagens[0].isNull()
assert a.textos()[0] == "aniversario" and a.textos()[1] == "5 fotos · 3 selecionadas · 10x15, 20x30"
assert a.textos()[2].startswith("Salvo em ")
assert b.textos()[1] == "2 fotos · nenhuma selecionada"
a.grab(); b.grab()                              # pinta sem erro

b.botao_remover.click()                         # tira da lista, não do disco
assert [str(i.caminho) for i in pg.itens] == [T1]
assert T2 not in prefs.settings().value("projeto/recentes", "", str) and Path(T2).is_file()
assert pg.vazio_recentes.isHidden()

pg.itens[0].abrir.emit(pg.itens[0].caminho)     # o clique
assert str(j.estado.trabalho.caminho) == T1 and len(j.estado.trabalho.fotos) == 5
assert not bv.visivel()

bv.mostrar()                                    # um recente apagado do disco some
assert esperar(lambda: not bv.ocupado())
os.remove(T1)
bv.recarregar_recentes()
assert pg.itens == [] and not pg.vazio_recentes.isHidden()
fechar(j)
print("ok")
""", T1=t1, T2=t2, SUMIDO=sumido)


def test_largura_estreita_vira_uma_coluna():
    rodar(r"""
j = janela()
j.boas_vindas.mostrar()
pg = j.boas_vindas.pagina
pg.reorganizar(1400)
assert not pg.uma_coluna and pg.grade_acoes.columnCount() == 4
pg.reorganizar(600)
assert pg.uma_coluna
assert pg.grade_acoes.itemAtPosition(1, 0) is not None and pg.grade_acoes.itemAtPosition(0, 2) is None
pg.reorganizar(400)
assert pg.grade_acoes.itemAtPosition(3, 0) is not None
assert pg.minimumWidth() == j.divisor.minimumWidth()
fechar(j)
print("ok")
""")


def test_recuperacao_em_destaque_sem_duplicar_a_faixa(tmp_path):
    t = str(_trabalho(tmp_path, "perdido", n=2, selecionadas=1))
    rodar(r"""
trabalho, _ = projeto.abrir(Path(T))
trabalho.caminho = None
projeto.salvar_recuperacao(trabalho)
j = janela()
assert "recuperacao" in j.faixas.faixas
bv = j.boas_vindas
bv.mostrar()
pg = bv.pagina
assert "recuperacao" not in j.faixas.faixas, "o cartão substitui a faixa"
assert not pg.cartao_recuperacao.isHidden() and "Sem título" in pg.texto_recuperacao.text()
bv.fechar()
esperar(lambda: "recuperacao" in j.faixas.faixas, 2)
assert "recuperacao" in j.faixas.faixas, "fechar a tela devolve a faixa"
bv.mostrar()
pg.botao_recuperar.click()
assert len(j.estado.trabalho.fotos) == 2 and j.estado.modificado
assert not bv.visivel()
esperar(lambda: False, 0.2)
assert "recuperacao" not in j.faixas.faixas and projeto.listar_recuperacao() == []
fechar(j)
print("ok")
""", T=t)


def test_novidades_abrem_uma_vez_por_versao():
    rodar(r"""
prefs.settings().setValue(boas_vindas.CHAVE_VERSAO_VISTA, "0.0.1")   # veio de uma versão anterior
j = janela()
j.boas_vindas.ao_abrir()
esperar(lambda: j.boas_vindas.dialogo_novidades is not None, 2)
d = j.boas_vindas.dialogo_novidades
assert d is not None and d.isVisible() and not d.isModal()
assert "Novidades" in d.texto.toMarkdown() and not d.texto.toPlainText().startswith("Revelador")
assert prefs.settings().value(boas_vindas.CHAVE_VERSAO_VISTA, "", str) == __version__
assert j.boas_vindas.visivel()
assert "Novidades" in j.boas_vindas.pagina.texto_novidades.text()
d.close()
fechar(j)
k = janela()
k.boas_vindas.ao_abrir()
esperar(lambda: False, 0.3)
assert k.boas_vindas.dialogo_novidades is None, "a mesma versão não mostra de novo"
fechar(k)
print("ok")
""")


def test_aviso_de_atualizacao_vem_do_updater_simulado():
    rodar(r"""
from revelador.ui import atualizacao
NOVA = updater.Release(tag="v9.9.9", version=(9, 9, 9), name="9.9.9", body="## Novidades\n- coisa", url="https://x",
                       published="", assets={})
ATUAL = updater.Release(tag="v" + __version__, version=updater.parse_version(__version__), name="", body="",
                        url="https://x", published="", assets={})
CONSULTAS = []
resposta = {"rel": NOVA}


def check(*a, **k):
    CONSULTAS.append(1)
    if resposta["rel"] is None:
        raise updater.UpdateError("offline")
    return resposta["rel"]


updater.check = check
j = janela()
bv = j.boas_vindas
bv.mostrar()
assert bv.pagina.estado_atualizacao == "versao" and CONSULTAS == [], "sem rede: nenhuma consulta"
bv.fechar()

os.environ.pop("REVELADOR_SEM_REDE")
bv.mostrar()
assert bv.pagina.estado_atualizacao == "procurando"
assert esperar(lambda: not j.verificador.consultando)
pg = bv.pagina
assert pg.estado_atualizacao == "disponivel" and "9.9.9" in pg.rotulo_atualizacao.text()
assert pg.botao_atualizar.isVisibleTo(pg) and "9.9.9" in pg.botao_atualizar.text()
assert j.verificador.dialogo is None, "a consulta silenciosa não abre o diálogo sozinha"
assert prefs.settings().value(atualizacao.CHAVE_ULTIMA, None) is None, "nem conta como a verificação do dia"
pg.botao_atualizar.click()
assert j.verificador.dialogo is not None and j.verificador.dialogo.isVisible()
j.verificador.dialogo.close()
n = len(CONSULTAS)
bv.fechar(); bv.mostrar()
assert len(CONSULTAS) == n and pg.estado_atualizacao == "disponivel", "reaproveita o último resultado"

j.verificador.ultimo = None
resposta["rel"] = ATUAL
bv.fechar(); bv.mostrar()
assert esperar(lambda: not j.verificador.consultando)
assert pg.estado_atualizacao == "atualizado" and "mais recente" in pg.rotulo_atualizacao.text()
assert not pg.botao_atualizar.isVisibleTo(pg)

j.verificador.ultimo = None
resposta["rel"] = None
bv.fechar(); bv.mostrar()
assert esperar(lambda: not j.verificador.consultando)
assert pg.estado_atualizacao == "erro" and pg.botao_verificar.isVisibleTo(pg)

j.verificador.ultimo = None
prefs.settings().setValue(atualizacao.CHAVE_AUTOMATICA, False)
n = len(CONSULTAS)
bv.fechar(); bv.mostrar()
assert pg.estado_atualizacao == "desligada" and len(CONSULTAS) == n, "busca automática desligada: não consulta"
resposta["rel"] = NOVA
pg.botao_verificar.click()                    # "Procurar agora"
assert esperar(lambda: not j.verificador.consultando) and pg.estado_atualizacao == "disponivel"
os.environ["REVELADOR_SEM_REDE"] = "1"
fechar(j)
print("ok")
""")


def test_verificador_ao_abrir_continua_igual_e_avisa_a_tela():
    rodar(r"""
from revelador.ui import atualizacao
from PySide6.QtWidgets import QWidget
from revelador.ui.estado import Estado
NOVA = updater.Release(tag="v9.9.9", version=(9, 9, 9), name="9.9.9", body="", url="https://x", published="",
                       assets={})
updater.check = lambda *a, **k: NOVA


class Janela(QWidget):
    def __init__(self):
        super().__init__()
        self.estado = Estado(self)


v = atualizacao.Verificador(Janela())
recebidos = []
v.verificado.connect(lambda rel, erro: recebidos.append((rel.tag if rel else None, erro)))
assert v.deve_verificar_ao_abrir()
v.verificar_ao_abrir()
assert esperar(lambda: not v.consultando)
assert recebidos == [("v9.9.9", "")] and v.ultimo[0] is NOVA
assert v.dialogo is not None, "a verificação do dia segue abrindo o diálogo"
assert not v.deve_verificar_ao_abrir()
print("ok")
""")
