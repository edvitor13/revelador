"""Atualização na interface (subprocesso offscreen): verificação ao abrir, diálogo, pular, caminho manual.

A rede é simulada trocando ``updater.check``/``download``/``install``; caixas de mensagem e a abertura do navegador
são trocadas por listas (nada de ``exec()`` nem de navegador em teste).
"""

from __future__ import annotations

from conftest import rodar_python

PREAMBULO = """
import sys, time
from PySide6.QtWidgets import QApplication, QWidget
app = QApplication(sys.argv[:1])
from revelador import updater
from revelador.ui import atualizacao, prefs
from revelador.ui.atualizacao import Verificador, texto_erro
from revelador.ui.estado import Estado

RELEASE = updater.Release(
    tag="v9.9.9", version=(9, 9, 9), name="9.9.9", body="## Novidades\\n- coisa nova", url="https://exemplo/paginas",
    published="", assets={"Revelador-9.9.9-windows-x64.zip": ("https://exemplo/pacote.zip", 10),
                          "SHA256SUMS.txt": ("https://exemplo/sums", 1)})
CH = {"check": 0, "info": [], "perguntas": [], "install": [], "encerrado": [], "abrir": []}


class Janela(QWidget):
    def __init__(self):
        super().__init__()
        self.estado = Estado(self)


def preparar(check, kind="zip", pode=True, download=None, perguntar=None):
    prefs.settings().remove("atualizacao")
    CH.update(check=0, info=[], perguntas=[], install=[], encerrado=[], abrir=[])

    def contar():
        CH["check"] += 1
        return check()

    updater.check = contar
    updater.install_info = lambda: {"kind": kind}
    updater.can_auto_install = lambda kind=None: pode
    updater.download = download or (lambda rel, asset, progresso, cancelar: "C:/pacote.zip")
    updater.install = lambda caminho, kind=None: CH["install"].append(caminho)
    atualizacao.informar = lambda janela, titulo, texto: CH["info"].append(texto)
    atualizacao.perguntar = perguntar or (lambda janela, titulo, texto, confirmar: CH["perguntas"].append(texto) or True)
    atualizacao.abrir_pagina = lambda url: CH["abrir"].append(url)
    atualizacao._encerrar = lambda: CH["encerrado"].append(1)


def esperar(v):
    fim = time.time() + 5
    while v.consultando and time.time() < fim:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()


def esperar_download(d):
    fim = time.time() + 5
    while d.ocupado and time.time() < fim:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()
"""


def rodar(corpo: str) -> None:
    p = rodar_python(PREAMBULO + corpo)
    assert p.returncode == 0, p.stderr
    assert p.stdout.strip().endswith("ok"), p.stdout


def test_versao_nova_mostra_dialogo():
    rodar("""
preparar(lambda: RELEASE)
j = Janela()
v = Verificador(j)
v.verificar_ao_abrir(); esperar(v)
assert CH["check"] == 1
d = v.dialogo
assert d is not None and not d.isHidden()
assert "9.9.9" in d.findChild(QWidget, "PanelTitle").text()
assert d.atualizar.objectName() == "Primary" and not d.atualizar.isHidden()
assert not d.pagina.isHidden() and d.pagina.objectName() == "Flat"
print("ok")
""")


def test_pular_grava_a_versao_e_nao_mostra_de_novo():
    rodar("""
preparar(lambda: RELEASE)
j = Janela()
v = Verificador(j)
v.verificar_ao_abrir(); esperar(v)
d = v.dialogo
d.pular.click()
assert d.isHidden()
assert prefs.settings().value("atualizacao/pulada") == "v9.9.9"
prefs.settings().setValue("atualizacao/ultima_verificacao", 0)
v2 = Verificador(j)
v2.verificar_ao_abrir(); esperar(v2)
assert CH["check"] == 2
assert v2.dialogo is None
print("ok")
""")


def test_verificacao_ao_abrir_uma_vez_por_dia():
    rodar("""
import time
preparar(lambda: updater.Release(tag="v0.1.0", version=(0, 1, 0), name="", body="", url="", published="",
                                 assets={}))
j = Janela()
v = Verificador(j)
v.verificar_ao_abrir(); esperar(v)
v.verificar_ao_abrir(); esperar(v)
assert CH["check"] == 1
prefs.settings().setValue("atualizacao/ultima_verificacao", time.time() - 25 * 3600)
v.verificar_ao_abrir(); esperar(v)
assert CH["check"] == 2
print("ok")
""")


def test_desligada_nao_consulta_mas_o_manual_continua():
    rodar("""
preparar(lambda: RELEASE)
prefs.settings().setValue("atualizacao/automatica", False)
j = Janela()
v = Verificador(j)
v.verificar_ao_abrir()
assert not v.consultando and CH["check"] == 0
v.verificar_manual(); esperar(v)
assert CH["check"] == 1
print("ok")
""")


def test_erro_de_rede_e_silencioso_ao_abrir_e_avisa_no_manual():
    rodar("""
def sem_rede():
    raise updater.UpdateError("offline")
preparar(sem_rede)
j = Janela()
v = Verificador(j)
v.verificar_ao_abrir(); esperar(v)
assert CH["info"] == [] and v.dialogo is None
v.verificar_manual(); esperar(v)
assert len(CH["info"]) == 1 and CH["info"][0] == texto_erro("offline")
assert "conexão" in CH["info"][0]
print("ok")
""")


def test_manual_sem_versao_nova_diz_que_esta_atualizado():
    rodar("""
preparar(lambda: updater.Release(tag="v0.1.0", version=(0, 1, 0), name="", body="", url="", published="",
                                 assets={}))
j = Janela()
v = Verificador(j)
v.verificar_manual(); esperar(v)
assert len(CH["info"]) == 1 and "versão mais recente" in CH["info"][0]
assert v.dialogo is None
print("ok")
""")


def test_sem_instalacao_automatica_mostra_so_o_caminho_manual():
    rodar("""
preparar(lambda: RELEASE, kind="source", pode=False)
j = Janela()
v = Verificador(j)
v.verificar_manual(); esperar(v)
d = v.dialogo
assert d.atualizar.isHidden() and not d.pagina.isHidden()
assert d.pagina.objectName() == "Primary"
assert "git pull" in d.situacao.text()
d.pagina.click()
assert CH["abrir"] == ["https://exemplo/paginas"]
print("ok")
""")


def test_instalar_com_trabalho_modificado_pede_confirmacao_e_cancela():
    rodar("""
preparar(lambda: RELEASE, perguntar=lambda j, t, texto, c: CH["perguntas"].append(texto) or False)
j = Janela()
j.estado.marcar_modificado()
v = Verificador(j)
v.verificar_manual(); esperar(v)
d = v.dialogo
d.atualizar.click(); esperar_download(d)
assert len(CH["perguntas"]) == 1 and "não salvas" in CH["perguntas"][0]
assert CH["install"] == [] and CH["encerrado"] == []
assert d.atualizar.isEnabled()
print("ok")
""")


def test_download_confirmado_instala_e_encerra():
    rodar("""
preparar(lambda: RELEASE)
j = Janela()
v = Verificador(j)
v.verificar_manual(); esperar(v)
d = v.dialogo
d.atualizar.click(); esperar_download(d)
assert CH["install"] == ["C:/pacote.zip"] and CH["encerrado"] == [1]
print("ok")
""")


def test_falha_do_download_mostra_o_erro_traduzido():
    rodar("""
def falha(rel, asset, progresso, cancelar):
    raise updater.UpdateError("checksum-mismatch")
preparar(lambda: RELEASE, download=falha)
j = Janela()
v = Verificador(j)
v.verificar_manual(); esperar(v)
d = v.dialogo
d.atualizar.click(); esperar_download(d)
assert CH["install"] == [] and CH["encerrado"] == []
assert d.situacao.text() == texto_erro("checksum-mismatch")
assert d.atualizar.isEnabled()
print("ok")
""")
