"""``prefs.settings()``: .ini em REVELADOR_SETTINGS_DIR, sem tocar no registro."""

from __future__ import annotations

from conftest import rodar_python


def test_usa_o_ini_da_pasta_de_teste(tmp_path):
    pasta = tmp_path / "novo"
    codigo = f"""
import os
from pathlib import Path
os.environ["REVELADOR_SETTINGS_DIR"] = r"{pasta}"
from PySide6.QtCore import QSettings
from revelador.ui import prefs
s = prefs.settings()
assert s.format() == QSettings.Format.IniFormat
s.setValue("a/b", 3); s.sync()
assert (Path(r"{pasta}") / "Revelador.ini").is_file()
assert prefs.settings().value("a/b", type=int) == 3
print("ok")
"""
    p = rodar_python(codigo)
    assert p.returncode == 0, p.stderr
    assert p.stdout.strip().endswith("ok")


def test_sem_a_variavel_usa_o_registro_nativo():
    codigo = """
import os
os.environ.pop("REVELADOR_SETTINGS_DIR", None)
from PySide6.QtCore import QSettings
from revelador.ui import prefs
s = prefs.settings()
assert s.format() == QSettings.Format.NativeFormat
assert s.organizationName() == "Revelador" and s.applicationName() == "Revelador"
print("ok")
"""
    p = rodar_python(codigo)
    assert p.returncode == 0, p.stderr
    assert p.stdout.strip().endswith("ok")
