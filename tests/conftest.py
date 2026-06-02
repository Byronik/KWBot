"""
Fixtures condivise per l'intera suite di test KWBot.

Fornisce:
- config.ini temporaneo e import isolato di config
- database SQLite in-memory
- registri completi e risultati Modbus fittizi
"""

import os
import sys
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock
import pytest

# Garantisce che src/ sia in path PRIMA di qualsiasi import
SRC_DIR = str(Path(__file__).resolve().parent.parent / "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)


# ── Fixture: config.ini temporaneo ───────────────────────────────────────

@pytest.fixture(scope="session")
def tmp_config_ini(tmp_path_factory):
    """Crea un config.ini valido in una cartella temporanea."""
    tmp = tmp_path_factory.mktemp("config")
    ini = tmp / "config.ini"
    db_path = tmp / "test.db"
    ini.write_text(
        "[network]\n"
        "boiler_ip = 192.168.50.100\n"
        "boiler_port = 502\n"
        "slave_id = 1\n"
        "timeout = 5\n"
        "\n"
        "[equipment]\n"
        "num_heating_circuits = 2\n"
        "num_buffers = 1\n"
        "num_hot_water = 1\n"
        "has_solar = true\n"
        "\n"
        "[polling]\n"
        "interval_seconds = 300\n"
        "chart_hours = 24\n"
        "\n"
        "[database]\n"
        f"path = {db_path}\n"
        "\n"
        "[telegram]\n"
        "bot_token = FAKE_TOKEN\n"
        "allowed_ids = 111, 222\n"
        "\n"
        "[display]\n"
        "display_timezone = Europe/Rome\n"
        "\n"
        "[logging]\n"
        "level = WARNING\n",
        encoding="utf-8",
    )
    return ini


@pytest.fixture(scope="session")
def cfg(tmp_config_ini):
    """Carica il modulo config puntato al config.ini di test."""
    import importlib
    import configparser

    # Ricarica config ogni sessione con il file temporaneo
    if "config" in sys.modules:
        del sys.modules["config"]

    os.environ["_KWB_TEST_CONFIG"] = str(tmp_config_ini)

    # Monkey-patch: config.py legge dal percorso env se presente
    # Alternativa: importa e sovrascrivi _INI direttamente
    import config as _cfg_mod
    _cfg_mod._INI = tmp_config_ini
    _cfg_mod._ROOT = tmp_config_ini.parent

    _cp = configparser.ConfigParser(inline_comment_prefixes=("#", ";"))
    _cp.read(str(tmp_config_ini), encoding="utf-8")

    _cfg_mod.BOILER_IP             = _cp.get("network", "boiler_ip")
    _cfg_mod.BOILER_PORT           = _cp.getint("network", "boiler_port", fallback=502)
    _cfg_mod.SLAVE_ID              = _cp.getint("network", "slave_id", fallback=1)
    _cfg_mod.TIMEOUT_S             = _cp.getint("network", "timeout", fallback=5)
    _cfg_mod.NUM_HEATING_CIRCUITS  = _cp.getint("equipment", "num_heating_circuits", fallback=2)
    _cfg_mod.NUM_BUFFERS           = _cp.getint("equipment", "num_buffers", fallback=1)
    _cfg_mod.NUM_HOT_WATER         = _cp.getint("equipment", "num_hot_water", fallback=1)
    _cfg_mod.HAS_SOLAR             = _cp.getboolean("equipment", "has_solar", fallback=True)
    _cfg_mod.POLL_INTERVAL_SECONDS = _cp.getint("polling", "interval_seconds", fallback=300)
    _cfg_mod.CHART_HOURS           = _cp.getint("polling", "chart_hours", fallback=24)
    _cfg_mod.TELEGRAM_BOT_TOKEN    = "FAKE_TOKEN"
    _cfg_mod.TELEGRAM_ALLOWED_IDS  = [111, 222]
    _cfg_mod.DISPLAY_TIMEZONE      = "Europe/Rome"
    _cfg_mod.LOG_LEVEL             = "WARNING"

    return _cfg_mod


@pytest.fixture
def db():
    """Database SQLite in-memory con schema completo."""
    from db import open_db
    conn = open_db(":memory:")
    yield conn
    conn.close()


@pytest.fixture
def all_regs():
    """Lista completa dei registri."""
    from registers import all_registers
    return all_registers()


@pytest.fixture
def fake_results(all_regs):
    """ReadResult fittizi (tutti ok, scaled_value=10.0)."""
    from modbus_reader import ReadResult
    return [ReadResult(r, 100, 10.0) for r in all_regs]


@pytest.fixture
def now_utc():
    return datetime.now(timezone.utc)
