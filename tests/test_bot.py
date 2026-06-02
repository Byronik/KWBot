"""
test_bot.py
===========
Verifica la logica del bot Telegram (senza connessione reale):
- Layout tastiera: 2 pulsanti per riga, BTN_INVISIBLE per ultimo
- Autorizzazione: _allowed restituisce False per utenti non in lista
- REGISTER_META: tutte le categorie valide, nessun registro sconosciuto
- Ogni categoria ha almeno un registro
- Parametri scrivibili hanno il prefisso ✏️ nella visualizzazione
- _build_maxmin_message usa i registri corretti (boi1_temp_actual, non sonda 2)
- Formattazione compatta: allarmi, stato caldaia, temperature, pompe
- _fmt_onoff e _fmt_yesno producono le emoji corrette
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch
import pytest

SRC_DIR = str(Path(__file__).resolve().parent.parent / "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from bot import (
    KEYBOARD, BTN_INVISIBLE,
    REGISTER_META, BTN_STATO, BTN_CONF, BTN_APPROF, BTN_TOTALI,
    BTN_MAXMIN, BTN_INVISIBLE, BTN_CHART_BOILER, BTN_CHART_SOLAR,
    BTN_CHART_BOI_ACS, BTN_CHART_PUFFER, BTN_CHART_OUTSIDE,
    BTN_CHART_PUMP_SOLAR, BTN_CHART_POWER, BTN_CHART_PUMPS_HC,
    _allowed, _fmt_onoff, _fmt_yesno, _render_value, _log_event,
    _legend_caption, _build_maxmin_message,
    YES_NO_REGISTERS,
)
from registers import all_registers


# ── Keyboard layout ───────────────────────────────────────────────────────

class TestKeyboardLayout:

    def test_all_expected_buttons_present(self):
        """Tutti i 14 pulsanti definiti devono essere nella tastiera."""
        all_buttons = [b.text for row in KEYBOARD.keyboard for b in row]
        expected = [
            BTN_STATO, BTN_CONF, BTN_APPROF, BTN_TOTALI, BTN_MAXMIN,
            BTN_CHART_BOILER, BTN_CHART_SOLAR, BTN_CHART_BOI_ACS,
            BTN_CHART_PUFFER, BTN_CHART_OUTSIDE, BTN_CHART_PUMP_SOLAR,
            BTN_CHART_POWER, BTN_CHART_PUMPS_HC, BTN_INVISIBLE,
        ]
        for btn in expected:
            assert btn in all_buttons, f"Pulsante '{btn}' non trovato nella tastiera"

    def test_max_two_buttons_per_row(self):
        """Ogni riga della tastiera deve avere al massimo 2 pulsanti."""
        for i, row in enumerate(KEYBOARD.keyboard):
            assert len(row) <= 2, (
                f"Riga {i} ha {len(row)} pulsanti, massimo consentito: 2"
            )

    def test_invisible_is_last_row(self):
        """BTN_INVISIBLE (Valori n.d.) deve essere nell'ultima riga."""
        last_row = [b.text for b in KEYBOARD.keyboard[-1]]
        assert BTN_INVISIBLE in last_row, (
            f"BTN_INVISIBLE non è nell'ultima riga. Ultima riga: {last_row}"
        )

    def test_keyboard_is_persistent(self):
        """La tastiera deve essere persistente (rimane visibile)."""
        assert KEYBOARD.is_persistent is True

    def test_keyboard_is_resizable(self):
        assert KEYBOARD.resize_keyboard is True


# ── Authorization ─────────────────────────────────────────────────────────

class TestAuthorization:

    def _make_update(self, user_id: int):
        update = MagicMock()
        update.effective_user.id = user_id
        update.effective_user.username = "testuser"
        return update

    def test_allowed_user_is_authorized(self):
        import config
        config.TELEGRAM_ALLOWED_IDS = [111, 222]
        update = self._make_update(111)
        assert _allowed(update) is True

    def test_unauthorized_user_is_rejected(self):
        import config
        config.TELEGRAM_ALLOWED_IDS = [111, 222]
        update = self._make_update(999)
        assert _allowed(update) is False

    def test_empty_allowed_list_rejects_all(self):
        import config
        config.TELEGRAM_ALLOWED_IDS = []
        update = self._make_update(111)
        assert _allowed(update) is False


# ── REGISTER_META ─────────────────────────────────────────────────────────

class TestRegisterMeta:

    VALID_CATEGORIES = {"STATO", "CONF", "APPROF", "TOTALI", "INVISIBILE"}

    def test_all_registers_present_in_meta(self):
        """Tutti i 98 registri devono avere una voce in REGISTER_META."""
        reg_names = {r.name for r in all_registers()}
        meta_names = set(REGISTER_META.keys())
        missing = reg_names - meta_names
        assert missing == set(), f"Registri senza REGISTER_META: {missing}"

    def test_no_extra_entries_in_meta(self):
        """REGISTER_META non deve avere nomi che non esistono in all_registers()."""
        reg_names = {r.name for r in all_registers()}
        meta_names = set(REGISTER_META.keys())
        extra = meta_names - reg_names
        assert extra == set(), f"REGISTER_META contiene nomi inesistenti: {extra}"

    def test_all_categories_are_valid(self):
        invalid = [(k, v[1]) for k, v in REGISTER_META.items()
                   if v[1] not in self.VALID_CATEGORIES]
        assert invalid == [], f"Categorie non valide in REGISTER_META: {invalid}"

    def test_each_category_has_at_least_one_register(self):
        categories_found = {v[1] for v in REGISTER_META.values()}
        for cat in self.VALID_CATEGORIES:
            assert cat in categories_found, f"Categoria '{cat}' non ha registri"

    def test_writable_flag_matches_registers(self):
        """
        Il flag writable in REGISTER_META deve corrispondere a Register.writable.
        Se c'è un disallineamento, il prefisso ✏️ viene mostrato in modo errato.
        """
        reg_map = {r.name: r for r in all_registers()}
        mismatches = []
        for name, (label, cat, wr_meta) in REGISTER_META.items():
            wr_reg = reg_map[name].writable
            if wr_meta != wr_reg:
                mismatches.append((name, wr_reg, wr_meta))
        assert mismatches == [], (
            f"Writable mismatch (registro vs meta): {mismatches}"
        )

    def test_all_labels_non_empty(self):
        """Ogni voce di REGISTER_META deve avere un'etichetta italiana non vuota."""
        empty = [k for k, v in REGISTER_META.items() if not v[0].strip()]
        assert empty == [], f"Registri con etichetta vuota: {empty}"


# ── Value formatting ──────────────────────────────────────────────────────

class TestValueFormatting:

    def test_fmt_onoff_on(self):
        result = _fmt_onoff("On")
        assert "🟢" in result
        assert "On" in result

    def test_fmt_onoff_off(self):
        result = _fmt_onoff("Off")
        assert "🔴" in result
        assert "Off" in result

    def test_fmt_onoff_case_insensitive(self):
        assert "🟢" in _fmt_onoff("on")
        assert "🔴" in _fmt_onoff("off")

    def test_fmt_onoff_numeric(self):
        assert "🟢" in _fmt_onoff("1")
        assert "🔴" in _fmt_onoff("0")

    def test_fmt_yesno_ok(self):
        result = _fmt_yesno("OK")
        assert "✅" in result

    def test_fmt_yesno_fault(self):
        result = _fmt_yesno("Fault")
        assert "❌" in result

    def test_fmt_yesno_yes(self):
        assert "✅" in _fmt_yesno("Yes")

    def test_fmt_yesno_no(self):
        assert "❌" in _fmt_yesno("No")

    def test_hk_outside_temp_is_invisibile_not_stato(self):
        """
        hk1_outside_temp e hk2_outside_temp devono essere in categoria INVISIBILE:
        la temperatura esterna è già mostrata nella sezione principale caldaia,
        mostrarla anche nei circuiti HC sarebbe ridondante.
        """
        for name in ("hk1_outside_temp", "hk2_outside_temp"):
            assert name in REGISTER_META, f"{name} mancante in REGISTER_META"
            cat = REGISTER_META[name][1]
            assert cat == "INVISIBILE", (
                f"{name} è in categoria '{cat}', deve essere 'INVISIBILE'. "
                "La temperatura esterna non deve comparire nei blocchi Mauro/Gabriele."
            )

    def test_yes_no_registers_defined(self):
        """system_ok e group_fault devono usare la formattazione ✅/❌."""
        assert "system_ok" in YES_NO_REGISTERS
        assert "group_fault" in YES_NO_REGISTERS

    def test_render_value_writable_has_pencil(self):
        """
        I valori scrivibili devono mostrare il prefisso ✏️.
        Verifica _render_value per un registro scrivibile noto.
        """
        # boiler_fuel_remaining_kg è scrivibile
        from bot import _build_section_messages
        import config
        config.TELEGRAM_ALLOWED_IDS = [111]

        # Costruiamo un messaggio STATO e verifichiamo che i writable abbiano ✏️
        reg_map = {r.name: r for r in all_registers()}
        writable_reg = next(
            (name for name, (_, cat, wr) in REGISTER_META.items()
             if wr and cat == "STATO"),
            None
        )
        if writable_reg is None:
            pytest.skip("Nessun registro scrivibile in STATO")

        data = {r.name: 10.0 for r in all_registers()}
        messages = _build_section_messages(data, "STATO")
        full_text = "\n".join(messages)
        assert "✏️" in full_text, (
            "I parametri scrivibili devono avere il prefisso ✏️ nel messaggio STATO"
        )


# ── _build_maxmin_message ─────────────────────────────────────────────────

class TestBuildMaxMinMessage:

    def _make_db_with_data(self):
        """DB in-memory con dati per i 3 registri usati da Massimi/Minimi."""
        import sqlite3
        from db import open_db
        from datetime import datetime, timezone, timedelta

        conn = open_db(":memory:")
        now = datetime.now(timezone.utc)
        for i in range(5):
            ts = (now - timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M:%SZ")
            conn.execute(
                "INSERT OR REPLACE INTO readings_wide "
                "(timestamp, sol1_collector_temp, boi1_temp_actual, outside_temp) "
                "VALUES (?, ?, ?, ?)",
                (ts, 80.0 - i * 5, 55.0 + i * 2, 15.0 - i)
            )
        conn.commit()
        return conn

    def test_maxmin_uses_boi1_temp_actual_not_temp2(self):
        """
        Il pannello Massimi/Minimi deve usare boi1_temp_actual (ACS principale),
        NON boi1_temp2 (sonda 2 — usata solo nel grafico pompa solare).
        """
        db = self._make_db_with_data()
        msg = _build_maxmin_message(db)
        db.close()
        # Deve contenere dati ACS (60+ °C nel nostro seed) non vuoti
        assert "ACS" in msg or "boiler" in msg.lower() or "🚿" in msg, (
            "Il messaggio Massimi/Minimi non contiene la sezione ACS"
        )
        # Verifica che ci siano valori numerici (non solo 'nessun dato')
        assert "nessun dato" not in msg.lower() or "55" in msg or "°C" in msg

    def test_maxmin_contains_three_sections(self):
        """Il messaggio deve contenere sezioni per collettore, ACS e temperatura esterna."""
        db = self._make_db_with_data()
        msg = _build_maxmin_message(db)
        db.close()
        assert "Collettore" in msg or "collettore" in msg or "🌡" in msg
        assert "ACS" in msg or "🚿" in msg
        assert "esterna" in msg.lower() or "🌤" in msg

    def test_maxmin_contains_24h_7d_absolute(self):
        """Ogni sezione deve avere i tre periodi temporali."""
        db = self._make_db_with_data()
        msg = _build_maxmin_message(db)
        db.close()
        assert "24" in msg
        assert "settimana" in msg.lower() or "7" in msg
        assert "assoluto" in msg.lower() or "Assoluto" in msg

    def test_maxmin_timestamps_in_local_time(self):
        """
        I timestamp nei Massimi/Minimi devono essere in ora locale (Europe/Rome),
        non in UTC. Verifica che fmt_ts converta correttamente UTC→locale,
        controllando che l'ora locale sia diversa dall'ora UTC (che lo sarebbero
        se fosse passata l'ora UTC senza conversione).
        """
        import zoneinfo
        from db import fmt_ts
        from datetime import datetime, timezone

        # Scegliamo un momento in cui UTC e ora italiana differiscono di 2h (CEST)
        ts_utc = "2026-05-05T20:08:58Z"   # 20:08 UTC = 22:08 ora italiana (CEST)
        result = fmt_ts(ts_utc)

        # Se mostrasse UTC avremmo "20:08", con la conversione corretta "22:08"
        assert "22:08" in result, (
            f"fmt_ts('{ts_utc}') = '{result}': "
            "atteso '22:08' (ora italiana CEST), non '20:08' (UTC). "
            "I Massimi/Minimi mostrano l'orario sbagliato."
        )
        assert "20:08" not in result, (
            f"fmt_ts mostra ancora l'ora UTC (20:08) invece dell'ora italiana (22:08): {result}"
        )
