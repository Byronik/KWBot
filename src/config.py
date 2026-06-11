"""Reads config.ini and exposes typed attributes.

Search order:
  1. /data/config.ini          -- Docker volume (priorita' massima)
  2. <project_root>/config.ini -- sviluppo locale / esecuzione diretta
"""

import configparser
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent

# Cerca config.ini: prima nel volume Docker /data/, poi nella root del progetto
_CANDIDATES = [Path("/data/config.ini"), _ROOT / "config.ini"]
_INI = next((p for p in _CANDIDATES if p.exists()), None)

if _INI is None:
    raise FileNotFoundError(
        "config.ini non trovato. Cercato in:\n"
        + "\n".join(f"  {p}" for p in _CANDIDATES)
    )

_cfg = configparser.ConfigParser(inline_comment_prefixes=("#", ";"))
_cfg.read(_INI, encoding="utf-8")

# [network]
BOILER_IP   : str = _cfg.get("network", "boiler_ip")
BOILER_PORT : int = _cfg.getint("network", "boiler_port", fallback=502)
SLAVE_ID    : int = _cfg.getint("network", "slave_id",    fallback=1)
TIMEOUT_S   : int = _cfg.getint("network", "timeout",     fallback=5)

# [equipment]
NUM_HEATING_CIRCUITS : int  = _cfg.getint    ("equipment", "num_heating_circuits", fallback=1)
NUM_BUFFERS          : int  = _cfg.getint    ("equipment", "num_buffers",          fallback=1)
NUM_HOT_WATER        : int  = _cfg.getint    ("equipment", "num_hot_water",        fallback=1)
HAS_SOLAR            : bool = _cfg.getboolean("equipment", "has_solar",            fallback=False)

# [polling]
POLL_INTERVAL_SECONDS : int = _cfg.getint("polling", "interval_seconds", fallback=300)
CHART_HOURS           : int = _cfg.getint("polling", "chart_hours",       fallback=24)

# [database]
# Se il path e' assoluto (es. /data/kwb_data.db) viene usato direttamente.
# Se e' relativo (es. data/kwb_data.db) viene risolto rispetto alla root del progetto.
_db_raw = _cfg.get("database", "path", fallback="data/kwb_data.db")
_db_path = Path(_db_raw)
DB_PATH : str = str(_db_path if _db_path.is_absolute() else (_ROOT / _db_raw).resolve())
Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)

# [telegram]
TELEGRAM_BOT_TOKEN   : str       = _cfg.get("telegram", "bot_token",   fallback="").strip()
_ids_raw                          = _cfg.get("telegram", "allowed_ids", fallback="").strip()
TELEGRAM_ALLOWED_IDS : list[int] = (
    [int(x.strip()) for x in _ids_raw.split(",") if x.strip()] if _ids_raw else []
)

# [display]
DISPLAY_TIMEZONE : str = _cfg.get("display", "display_timezone", fallback="Europe/Rome")

# [logging]
LOG_LEVEL : str = _cfg.get("logging", "level", fallback="INFO").upper()

# [monitoring]
HEALTHCHECK_URL      : str   = _cfg.get  ("monitoring", "healthcheck_url",      fallback="").strip()
BOILER_ALERT_TEMP    : float = _cfg.getfloat("monitoring", "boiler_alert",       fallback=0.0)
BOILER_INTERVENTION_TEMP : float = _cfg.getfloat("monitoring", "boiler_intervention", fallback=0.0)
