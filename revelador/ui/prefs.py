"""Preferências do app: a única porta para o ``QSettings``.

Por padrão ficam no registro do Windows (``HKCU\Software\Revelador\Revelador``). Com a variável
``REVELADOR_SETTINGS_DIR`` (modo portátil e testes) tudo vai para um ``.ini`` nessa pasta, sem tocar no registro.
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QSettings

from .. import APP_NAME


def settings() -> QSettings:
    """Preferências do usuário (registro ou ``.ini`` em ``REVELADOR_SETTINGS_DIR``)."""
    pasta = os.environ.get("REVELADOR_SETTINGS_DIR")
    if pasta:
        Path(pasta).mkdir(parents=True, exist_ok=True)
        return QSettings(str(Path(pasta) / f"{APP_NAME}.ini"), QSettings.Format.IniFormat)
    return QSettings(QSettings.Format.NativeFormat, QSettings.Scope.UserScope, APP_NAME, APP_NAME)
