"""
test_boiler_alerts.py
=====================
Verifica la macchina a stati di check_boiler_temp() in logger.py.

Stati:
  0 = normale   (T < boiler_alert)
  1 = allerta   (boiler_alert <= T < boiler_intervention)
  2 = intervento (T >= boiler_intervention)

Transizioni attese:
  0→1 : messaggio allerta
  1→2 : messaggio intervento
  0→2 : messaggio intervento (salto diretto)
  2→1 : messaggio intervento rientrato
  1→0 : messaggio situazione normalizzata
  2→0 : messaggio situazione normalizzata (salto diretto)
  stesso stato: nessun messaggio
"""

import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

SRC_DIR = str(Path(__file__).resolve().parent.parent / "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

# Inietta un mock config prima che logger lo importi
if "config" not in sys.modules:
    _mock_cfg = types.ModuleType("config")
    _mock_cfg.BOILER_ALERT_TEMP = 75.0
    _mock_cfg.BOILER_INTERVENTION_TEMP = 80.0
    _mock_cfg.TELEGRAM_BOT_TOKEN = ""
    _mock_cfg.TELEGRAM_ALLOWED_IDS = []
    _mock_cfg.DB_PATH = ":memory:"
    _mock_cfg.POLL_INTERVAL_SECONDS = 300
    _mock_cfg.LOG_LEVEL = "WARNING"
    _mock_cfg.DISPLAY_TIMEZONE = "Europe/Rome"
    _mock_cfg.HEALTHCHECK_URL = ""
    sys.modules["config"] = _mock_cfg

import logger  # noqa: E402


@pytest.fixture(autouse=True)
def reset_state():
    import config
    config.BOILER_ALERT_TEMP = 75.0
    config.BOILER_INTERVENTION_TEMP = 80.0
    logger._boiler_acs_state = 0
    yield
    logger._boiler_acs_state = 0


class TestBoilerAcsAlerts:

    def test_no_notification_below_alert(self):
        """Stato 0: nessuna notifica sotto boiler_alert."""
        with patch.object(logger, "_notify") as mock_notify:
            logger.check_boiler_temp(70.0)
            mock_notify.assert_not_called()

    def test_0_to_1_sends_alert(self):
        """Transizione 0→1: messaggio allerta, parla di boiler ACS."""
        with patch.object(logger, "_notify") as mock_notify:
            logger.check_boiler_temp(77.0)
            mock_notify.assert_called_once()
            msg = mock_notify.call_args[0][0][0]
            assert "ATTENZIONE" in msg
            assert "ACS" in msg
            assert "77.0" in msg

    def test_1_to_2_sends_intervention(self):
        """Transizione 1→2: messaggio intervento, parla di boiler ACS."""
        with patch.object(logger, "_notify") as mock_notify:
            logger.check_boiler_temp(77.0)  # 0→1
            logger.check_boiler_temp(82.0)  # 1→2
            assert mock_notify.call_count == 2
            msg = mock_notify.call_args[0][0][0]
            assert "ALLARME" in msg
            assert "ACS" in msg
            assert "82.0" in msg

    def test_0_to_2_direct_sends_intervention(self):
        """Salto diretto 0→2: solo messaggio intervento."""
        with patch.object(logger, "_notify") as mock_notify:
            logger.check_boiler_temp(85.0)
            mock_notify.assert_called_once()
            msg = mock_notify.call_args[0][0][0]
            assert "ALLARME" in msg

    def test_2_to_1_sends_intervention_cleared(self):
        """Transizione 2→1: messaggio intervento rientrato."""
        with patch.object(logger, "_notify") as mock_notify:
            logger.check_boiler_temp(82.0)  # 0→2
            logger.check_boiler_temp(77.0)  # 2→1
            assert mock_notify.call_count == 2
            msg = mock_notify.call_args[0][0][0]
            assert "rientrato" in msg.lower()
            assert "ACS" in msg

    def test_1_to_0_sends_normalized(self):
        """Transizione 1→0: messaggio situazione normalizzata."""
        with patch.object(logger, "_notify") as mock_notify:
            logger.check_boiler_temp(77.0)  # 0→1
            logger.check_boiler_temp(70.0)  # 1→0
            assert mock_notify.call_count == 2
            msg = mock_notify.call_args[0][0][0]
            assert "normalizzata" in msg.lower() or "OK" in msg

    def test_2_to_0_direct_sends_normalized(self):
        """Salto diretto 2→0: messaggio situazione normalizzata."""
        with patch.object(logger, "_notify") as mock_notify:
            logger.check_boiler_temp(82.0)  # 0→2
            logger.check_boiler_temp(70.0)  # 2→0
            assert mock_notify.call_count == 2
            msg = mock_notify.call_args[0][0][0]
            assert "normalizzata" in msg.lower() or "OK" in msg

    def test_no_repeat_in_same_state(self):
        """Nessuna notifica ripetuta finché lo stato non cambia."""
        with patch.object(logger, "_notify") as mock_notify:
            logger.check_boiler_temp(77.0)  # 0→1
            logger.check_boiler_temp(76.0)  # rimane in 1
            logger.check_boiler_temp(78.0)  # rimane in 1
            assert mock_notify.call_count == 1

    def test_full_cycle(self):
        """Ciclo completo 0→1→2→1→0: 4 notifiche totali."""
        with patch.object(logger, "_notify") as mock_notify:
            logger.check_boiler_temp(77.0)  # 0→1
            logger.check_boiler_temp(82.0)  # 1→2
            logger.check_boiler_temp(77.0)  # 2→1
            logger.check_boiler_temp(70.0)  # 1→0
            assert mock_notify.call_count == 4
