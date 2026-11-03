"""``system``: comandos montados certos (nada é aberto de verdade) e pastas do usuário."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from revelador import system


def test_reveal_no_windows_usa_explorer_com_select(monkeypatch, tmp_path):
    arq = tmp_path / "foto.jpg"
    arq.write_bytes(b"x")
    chamadas = []
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(system.subprocess, "Popen", lambda cmd, *a, **k: chamadas.append(cmd))
    system.reveal(arq)
    assert chamadas == [["explorer", "/select,", os.path.normpath(str(arq))]]


def test_reveal_de_pasta_abre_a_pasta(monkeypatch, tmp_path):
    abertos = []
    monkeypatch.setattr(system, "open_path", abertos.append)
    system.reveal(tmp_path)
    assert abertos == [str(tmp_path)]
    system.reveal(tmp_path / "inexistente.jpg")
    assert abertos[-1] == str(tmp_path)


def test_open_path_usa_xdg_open_fora_do_windows(monkeypatch):
    chamadas = []
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(system.subprocess, "Popen", lambda cmd, *a, **k: chamadas.append(cmd))
    system.open_path("/tmp/x")
    assert chamadas == [["xdg-open", "/tmp/x"]]


def test_open_path_no_windows_usa_startfile(monkeypatch):
    abertos = []
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(os, "startfile", abertos.append, raising=False)
    system.open_path(Path("C:/pasta"))
    assert abertos == [str(Path("C:/pasta"))]


def test_pastas_do_usuario(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert system.pasta_dados() == tmp_path / "Revelador"
    assert system.pasta_imagens().is_dir()
