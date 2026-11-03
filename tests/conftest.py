"""Configuração comum dos testes: nada de sujar o ambiente do usuário.

- Preferências num .ini temporário (``REVELADOR_SETTINGS_DIR``), nunca no registro.
- ``LOCALAPPDATA``/``APPDATA`` temporários (cache de miniaturas, registros, recuperação).
- Qt sem tela nos subprocessos de interface (``QT_QPA_PLATFORM=offscreen``).
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

_BASE = Path(tempfile.mkdtemp(prefix="revelador_testes_"))
for _var, _sub in (("REVELADOR_SETTINGS_DIR", "prefs"), ("LOCALAPPDATA", "localappdata"), ("APPDATA", "appdata")):
    (_BASE / _sub).mkdir(parents=True, exist_ok=True)
    os.environ[_var] = str(_BASE / _sub)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["REVELADOR_SEM_REDE"] = "1"   # a janela não consulta atualizações durante os testes


def rodar_python(codigo: str, timeout: float = 60.0) -> subprocess.CompletedProcess:
    """Roda código Python num subprocesso (com o mesmo ambiente dos testes) a partir da raiz do projeto."""
    return subprocess.run([sys.executable, "-c", codigo], cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout, env=dict(os.environ))


@pytest.fixture
def raiz() -> Path:
    return ROOT
