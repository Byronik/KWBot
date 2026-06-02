"""
test_alarms.py
==============
Verifica il modulo allarmi:
- ALARM_DEFS completo (almeno 71 allarmi, nessun testo vuoto)
- read_active_alarms filtra correttamente i bit attivi
- Nessun allarme nell'insieme "ritornato" se non era aperto
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock
import pytest

SRC_DIR = str(Path(__file__).resolve().parent.parent / "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from alarms import ALARM_DEFS, read_active_alarms


class TestAlarmDefs:

    def test_minimum_alarm_count(self):
        """Deve esserci almeno 71 allarmi definiti (KWB EF2 v25.4.x)."""
        assert len(ALARM_DEFS) >= 71, (
            f"ALARM_DEFS ha solo {len(ALARM_DEFS)} allarmi, attesi almeno 71."
        )

    def test_all_alarms_have_non_empty_italian_text(self):
        """Ogni allarme deve avere un testo italiano non vuoto."""
        empty = [aid for aid, defn in ALARM_DEFS.items() if not defn.text_it.strip()]
        assert empty == [], f"Allarmi con testo vuoto (address): {empty}"

    def test_all_alarms_have_alarm_id(self):
        """Ogni allarme deve avere un alarm_id non vuoto."""
        empty = [addr for addr, defn in ALARM_DEFS.items() if not defn.alarm_id.strip()]
        assert empty == [], f"Allarmi senza alarm_id: {empty}"

    def test_known_alarm_22_present(self):
        """
        L'allarme 2.2 (contenitore cenere) è stato testato in produzione.
        Deve essere presente con la descrizione corretta.
        """
        found = [defn for defn in ALARM_DEFS.values() if defn.alarm_id == "2.2"]
        assert len(found) >= 1, "Allarme 2.2 non trovato in ALARM_DEFS"
        assert "cenere" in found[0].text_it.lower() or "ash" in found[0].text_it.lower(), (
            f"Testo allarme 2.2 non contiene 'cenere': '{found[0].text_it}'"
        )

    def test_no_duplicate_alarm_ids(self):
        """Nessun alarm_id deve essere duplicato."""
        ids = [defn.alarm_id for defn in ALARM_DEFS.values()]
        dupes = [i for i in set(ids) if ids.count(i) > 1]
        assert dupes == [], f"alarm_id duplicati: {dupes}"


class TestReadActiveAlarms:
    """
    read_active_alarms legge i coil via FC02 e restituisce il set di indirizzi attivi.
    """

    def _mock_client(self, active_addresses):
        """
        Crea un client Modbus mock che risponde ai discrete inputs (FC02):
        bit=1 se il suo indirizzo (base + offset) è in active_addresses.
        Nota: read_active_alarms usa read_discrete_inputs, non read_coils.
        """
        client = MagicMock()

        def side_effect(address, count, device_id):
            resp = MagicMock()
            resp.isError.return_value = False
            bits = []
            for i in range(count):
                bits.append(1 if (address + i) in active_addresses else 0)
            resp.bits = bits
            return resp

        client.read_discrete_inputs.side_effect = side_effect
        return client

    def test_no_active_alarms(self):
        """Senza allarmi attivi, il set restituito deve essere vuoto."""
        client = self._mock_client(active_addresses=set())
        result = read_active_alarms(client, device_id=1)
        assert result == set()

    def test_single_active_alarm(self):
        """Un singolo allarme attivo deve comparire nel set restituito."""
        first_addr = sorted(ALARM_DEFS.keys())[0]
        client = self._mock_client(active_addresses={first_addr})
        result = read_active_alarms(client, device_id=1)
        assert first_addr in result

    def test_multiple_active_alarms(self):
        """Più allarmi attivi devono comparire tutti nel set."""
        addresses = sorted(ALARM_DEFS.keys())[:3]
        client = self._mock_client(active_addresses=set(addresses))
        result = read_active_alarms(client, device_id=1)
        for addr in addresses:
            assert addr in result, f"Allarme {addr} non rilevato"

    def test_read_error_returns_empty_set(self):
        """Se la lettura FC02 fallisce, read_active_alarms deve restituire set vuoto (no crash)."""
        client = MagicMock()
        resp = MagicMock()
        resp.isError.return_value = True
        client.read_discrete_inputs.return_value = resp

        try:
            result = read_active_alarms(client, device_id=1)
            assert isinstance(result, set)
        except Exception as e:
            pytest.fail(f"read_active_alarms ha sollevato un'eccezione: {e}")
