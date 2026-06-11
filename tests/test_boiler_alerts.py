"""
test_boiler_alerts.py
=====================
Verifica la logica di check_boiler_temp() in logger.py:
- Nessuna notifica sotto soglia
- Alert inviato al primo superamento di boiler_alert
- Alert NON ripetuto se la temperatura resta sopra soglia
- Reset e nuova notifica dopo discesa e risalita
- Soglia intervento: solo messaggio intervento (non alert)
- Reset stato quando si scende sotto boiler_alert
"""

import sys
import types
import logging
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
    """Imposta soglie e resetta lo stato globale degli alert prima di ogni test."""
    import config
    config.BOILER_ALERT_TEMP = 75.0
    config.BOILER_INTERVENTION_TEMP = 80.0
    logger._alert_sent = False
    logger._intervention_sent = False
    yield
    logger._alert_sent = False
    logger._intervention_sent = False


class TestBoilerAlerts:

    def test_no_notification_below_alert(self):
        """Sotto boiler_alert: nessuna notifica."""
        with patch.object(logger, "_notify") as mock_notify:
            logger.check_boiler_temp(70.0)
            mock_notify.assert_not_called()

    def test_alert_sent_at_threshold(self):
        """Al raggiungimento esatto di boiler_alert: notifica allerta."""
        with patch.object(logger, "_notify") as mock_notify:
            logger.check_boiler_temp(75.0)
            mock_notify.assert_called_once()
            msg = mock_notify.call_args[0][0][0]
            assert "ATTENZIONE" in msg
            assert "75.0" in msg

    def test_alert_sent_above_threshold(self):
        """Sopra boiler_alert ma sotto boiler_intervention: notifica allerta."""
        with patch.object(logger, "_notify") as mock_notify:
            logger.check_boiler_temp(77.0)
            mock_notify.assert_called_once()
            msg = mock_notify.call_args[0][0][0]
            assert "ATTENZIONE" in msg

    def test_alert_not_repeated(self):
        """Alert non ripetuto se la temperatura resta sopra soglia."""
        with patch.object(logger, "_notify") as mock_notify:
            logger.check_boiler_temp(76.0)
            logger.check_boiler_temp(77.0)
            logger.check_boiler_temp(78.0)
            assert mock_notify.call_count == 1

    def test_alert_reset_after_drop(self):
        """Dopo discesa sotto soglia, il successivo superamento manda nuovo alert."""
        with patch.object(logger, "_notify") as mock_notify:
            logger.check_boiler_temp(76.0)
            logger.check_boiler_temp(70.0)
            logger.check_boiler_temp(76.0)
            assert mock_notify.call_count == 2

    def test_intervention_sent_at_threshold(self):
        """Al raggiungimento di boiler_intervention: solo messaggio intervento."""
        with patch.object(logger, "_notify") as mock_notify:
            logger.check_boiler_temp(80.0)
            mock_notify.assert_called_once()
            msg = mock_notify.call_args[0][0][0]
            assert "ALLARME" in msg
            assert "ATTENZIONE" not in msg

    def test_intervention_not_repeated(self):
        """Messaggio intervento non ripetuto se temperatura resta sopra soglia."""
        with patch.object(logger, "_notify") as mock_notify:
            logger.check_boiler_temp(82.0)
            logger.check_boiler_temp(85.0)
            assert mock_notify.call_count == 1

    def test_intervention_no_alert_message(self):
        """Superando boiler_intervention direttamente: solo intervento, non alert."""
        with patch.object(logger, "_notify") as mock_notify:
            logger.check_boiler_temp(82.0)
            assert mock_notify.call_count == 1
            msg = mock_notify.call_args[0][0][0]
            assert "ALLARME" in msg

    def test_drop_from_intervention_to_alert_range(self):
        """
        Scendendo da sopra boiler_intervention a range alert (tra 75 e 80):
        deve mandare il messaggio di allerta (non intervento).
        """
        with patch.object(logger, "_notify") as mock_notify:
            logger.check_boiler_temp(82.0)
            logger.check_boiler_temp(77.0)
            assert mock_notify.call_count == 2
            msg0 = mock_notify.call_args_list[0][0][0][0]
            msg1 = mock_notify.call_args_list[1][0][0][0]
            assert "ALLARME" in msg0
            assert "ATTENZIONE" in msg1

    def test_full_reset_below_alert(self):
        """Scendendo sotto boiler_alert: stato completamente resettato."""
        with patch.object(logger, "_notify") as mock_notify:
            logger.check_boiler_temp(82.0)
            logger.check_boiler_temp(70.0)
            assert logger._alert_sent is False
            assert logger._intervention_sent is False
