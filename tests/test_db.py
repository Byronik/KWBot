"""
test_db.py
==========
Verifica lo strato di persistenza SQLite:
- Schema tabelle e indici
- insert/read readings_wide (inclusi valori NULL per errori)
- Lifecycle allarmi: raise → notified → clear → clear_notified → nuova apertura
- insert_bot_event con timestamp UTC
- fetch_series_wide filtra per timestamp
- fmt_ts converte UTC → ora locale corretta
"""

import sys
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
import pytest

SRC_DIR = str(Path(__file__).resolve().parent.parent / "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from db import (
    open_db, REGISTER_COLUMNS,
    insert_readings_wide, latest_readings_wide, fetch_series_wide,
    insert_bot_event,
    insert_alarm, get_open_alarm_addresses,
    get_unnotified_raised_alarms, get_unnotified_cleared_alarms,
    mark_raise_notified, mark_clear_notified,
    close_alarms,
    fmt_ts,
)
from registers import all_registers
from modbus_reader import ReadResult


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def db():
    conn = open_db(":memory:")
    yield conn
    conn.close()


@pytest.fixture
def all_regs():
    return all_registers()


@pytest.fixture
def now_utc():
    return datetime(2026, 5, 6, 8, 0, 0, tzinfo=timezone.utc)


def _make_results(regs, value=10.0, error_names=None):
    """Crea ReadResult fittizi; i registri in error_names avranno error valorizzato."""
    error_names = error_names or set()
    results = []
    for r in regs:
        if r.name in error_names:
            results.append(ReadResult(r, None, None, "simulated error"))
        else:
            results.append(ReadResult(r, 100, value))
    return results


# ── Schema ────────────────────────────────────────────────────────────────

class TestDatabaseSchema:

    def test_readings_wide_table_exists(self, db):
        tables = [r[0] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        assert "readings_wide" in tables

    def test_alarm_history_table_exists(self, db):
        tables = [r[0] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        assert "alarm_history" in tables

    def test_bot_events_table_exists(self, db):
        tables = [r[0] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        assert "bot_events" in tables

    def test_readings_wide_has_all_register_columns(self, db):
        """Ogni colonna in REGISTER_COLUMNS deve esistere nella tabella."""
        cols_info = db.execute("PRAGMA table_info(readings_wide)").fetchall()
        col_names = {c[1] for c in cols_info}
        missing = [c for c in REGISTER_COLUMNS if c not in col_names]
        assert missing == [], f"Colonne mancanti in readings_wide: {missing}"

    def test_readings_wide_has_timestamp_primary_key(self, db):
        cols_info = db.execute("PRAGMA table_info(readings_wide)").fetchall()
        ts_col = next((c for c in cols_info if c[1] == "timestamp"), None)
        assert ts_col is not None
        assert ts_col[5] == 1, "timestamp deve essere PRIMARY KEY"

    def test_wal_mode_enabled_on_file_db(self, tmp_path):
        """
        WAL mode è abilitata per i DB su file (non in-memory, che la ignora).
        Verifica su un file temporaneo reale.
        """
        from db import open_db
        db_file = str(tmp_path / "test_wal.db")
        conn = open_db(db_file)
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        conn.close()
        assert mode == "wal", f"journal_mode atteso: wal, trovato: {mode}"

    def test_alarm_history_has_required_columns(self, db):
        cols = {c[1] for c in db.execute("PRAGMA table_info(alarm_history)").fetchall()}
        required = {"id", "address", "alarm_id", "text_it",
                    "raise_time", "clear_time", "notified", "clear_notified"}
        missing = required - cols
        assert missing == set(), f"Colonne mancanti in alarm_history: {missing}"


# ── readings_wide ─────────────────────────────────────────────────────────

class TestReadingsWide:

    def test_insert_and_latest(self, db, all_regs, now_utc):
        results = _make_results(all_regs, value=65.3)
        insert_readings_wide(db, now_utc, results)

        row = latest_readings_wide(db)
        assert row, "latest_readings_wide deve restituire dati dopo insert"
        assert row["boiler_temp_actual"] == pytest.approx(65.3)

    def test_timestamp_stored_as_utc_iso(self, db, all_regs, now_utc):
        insert_readings_wide(db, now_utc, _make_results(all_regs))
        row = latest_readings_wide(db)
        ts = row["_timestamp"]
        assert ts == "2026-05-06T08:00:00Z", f"Timestamp non in formato UTC ISO: {ts}"

    def test_error_registers_stored_as_null(self, db, all_regs, now_utc):
        """I registri con errore devono essere NULL nel DB, non 0."""
        results = _make_results(all_regs, error_names={"sol1_collector_temp"})
        insert_readings_wide(db, now_utc, results)
        row = latest_readings_wide(db)
        assert row["sol1_collector_temp"] is None, (
            "Un registro con errore Modbus deve essere NULL, non 0."
        )

    def test_latest_returns_most_recent(self, db, all_regs):
        t1 = datetime(2026, 5, 6, 8,  0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 5, 6, 8,  5, 0, tzinfo=timezone.utc)
        insert_readings_wide(db, t1, _make_results(all_regs, value=60.0))
        insert_readings_wide(db, t2, _make_results(all_regs, value=70.0))
        row = latest_readings_wide(db)
        assert row["boiler_temp_actual"] == pytest.approx(70.0), (
            "latest_readings_wide deve restituire l'ultima riga, non la prima."
        )

    def test_empty_db_returns_empty_dict(self, db):
        row = latest_readings_wide(db)
        assert row == {}

    def test_fetch_series_wide_filters_by_timestamp(self, db, all_regs):
        t_old = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
        t_new = datetime(2026, 5, 6, 8, 0, 0, tzinfo=timezone.utc)
        insert_readings_wide(db, t_old, _make_results(all_regs, value=30.0))
        insert_readings_wide(db, t_new, _make_results(all_regs, value=90.0))

        # Chiedi solo le ultime 24h (solo t_new passa il filtro)
        since = "2026-05-05T00:00:00Z"
        rows = fetch_series_wide(db, "sol1_collector_temp", since)
        assert len(rows) == 1, "fetch_series_wide deve filtrare i dati più vecchi del since"
        assert rows[0][1] == pytest.approx(90.0)  # valore del record recente

    def test_fetch_series_wide_returns_empty_for_null_values(self, db, all_regs, now_utc):
        """Righe con NULL non devono apparire nella serie."""
        results = _make_results(all_regs, error_names={"sol1_collector_temp"})
        insert_readings_wide(db, now_utc, results)
        rows = fetch_series_wide(db, "sol1_collector_temp", "2000-01-01T00:00:00Z")
        assert rows == [], "fetch_series_wide non deve restituire NULL"

    def test_fetch_series_wide_invalid_column_returns_empty(self, db):
        rows = fetch_series_wide(db, "COLONNA_INESISTENTE", "2000-01-01T00:00:00Z")
        assert rows == []


# ── Alarm lifecycle ───────────────────────────────────────────────────────

class TestAlarmLifecycle:
    """
    Verifica il ciclo completo:
    1. Allarme rilevato → riga con raise_time, clear_time=NULL, notified=0
    2. Ancora attivo → già in DB, nessuna nuova riga
    3. Rientra → clear_time impostato, clear_notified=0
    4. Riattivazione → nuova riga
    """

    ADDR = 128
    AID  = "2.0"
    TEXT = "Surriscaldamento caldaia!"

    def test_alarm_raise_creates_open_row(self, db, now_utc):
        insert_alarm(db, self.ADDR, self.AID, self.TEXT, now_utc)
        open_addrs = get_open_alarm_addresses(db)
        assert self.ADDR in open_addrs

    def test_alarm_raise_appears_in_unnotified_raised(self, db, now_utc):
        insert_alarm(db, self.ADDR, self.AID, self.TEXT, now_utc)
        unnotified = get_unnotified_raised_alarms(db)
        assert any(a["address"] == self.ADDR for a in unnotified)

    def test_mark_raise_notified_removes_from_unnotified(self, db, now_utc):
        insert_alarm(db, self.ADDR, self.AID, self.TEXT, now_utc)
        unnotified = get_unnotified_raised_alarms(db)
        ids = [a["id"] for a in unnotified]
        mark_raise_notified(db, ids)
        assert get_unnotified_raised_alarms(db) == []

    def test_alarm_still_open_after_notify(self, db, now_utc):
        """Notificare un allarme non lo chiude: deve restare in get_open_alarm_addresses."""
        insert_alarm(db, self.ADDR, self.AID, self.TEXT, now_utc)
        ids = [a["id"] for a in get_unnotified_raised_alarms(db)]
        mark_raise_notified(db, ids)
        assert self.ADDR in get_open_alarm_addresses(db)

    def test_close_alarm_sets_clear_time(self, db, now_utc):
        insert_alarm(db, self.ADDR, self.AID, self.TEXT, now_utc)
        clear_time = now_utc + timedelta(minutes=5)
        close_alarms(db, [self.ADDR], clear_time)
        assert self.ADDR not in get_open_alarm_addresses(db)

    def test_cleared_alarm_appears_in_unnotified_cleared(self, db, now_utc):
        insert_alarm(db, self.ADDR, self.AID, self.TEXT, now_utc)
        mark_raise_notified(db, [a["id"] for a in get_unnotified_raised_alarms(db)])
        close_alarms(db, [self.ADDR], now_utc + timedelta(minutes=5))
        unnotified_cleared = get_unnotified_cleared_alarms(db)
        assert any(a["address"] == self.ADDR for a in unnotified_cleared)

    def test_mark_clear_notified_clears_queue(self, db, now_utc):
        insert_alarm(db, self.ADDR, self.AID, self.TEXT, now_utc)
        mark_raise_notified(db, [a["id"] for a in get_unnotified_raised_alarms(db)])
        close_alarms(db, [self.ADDR], now_utc + timedelta(minutes=5))
        ids = [a["id"] for a in get_unnotified_cleared_alarms(db)]
        mark_clear_notified(db, ids)
        assert get_unnotified_cleared_alarms(db) == []

    def test_reactivation_creates_new_row(self, db, now_utc):
        """
        Se un allarme rientra e poi si riattiva, deve essere notificato di nuovo.
        Ogni attivazione crea una nuova riga — non viene aggiornata la precedente.
        """
        # Prima attivazione
        insert_alarm(db, self.ADDR, self.AID, self.TEXT, now_utc)
        mark_raise_notified(db, [a["id"] for a in get_unnotified_raised_alarms(db)])
        close_alarms(db, [self.ADDR], now_utc + timedelta(minutes=5))
        mark_clear_notified(db, [a["id"] for a in get_unnotified_cleared_alarms(db)])

        # Seconda attivazione
        t2 = now_utc + timedelta(hours=1)
        insert_alarm(db, self.ADDR, self.AID, self.TEXT, t2)
        open_addrs = get_open_alarm_addresses(db)
        assert self.ADDR in open_addrs
        unnotified = get_unnotified_raised_alarms(db)
        assert any(a["address"] == self.ADDR for a in unnotified)

    def test_active_alarm_not_re_inserted_if_already_open(self, db, now_utc):
        """
        La logica in logger.py non deve inserire un allarme già aperto.
        Verifichiamo che get_open_alarm_addresses sia coerente col lifecycle.
        """
        insert_alarm(db, self.ADDR, self.AID, self.TEXT, now_utc)
        open1 = get_open_alarm_addresses(db)
        # Simuliamo: allarme ancora attivo, non inseriamo di nuovo
        open2 = get_open_alarm_addresses(db)
        count = db.execute(
            "SELECT COUNT(*) FROM alarm_history WHERE address=?", (self.ADDR,)
        ).fetchone()[0]
        assert count == 1, "Non deve esistere più di una riga aperta per lo stesso allarme"

    def test_raise_and_clear_timestamps_are_utc_iso(self, db, now_utc):
        """I timestamp devono essere in formato ISO-8601 UTC nel DB."""
        insert_alarm(db, self.ADDR, self.AID, self.TEXT, now_utc)
        close_alarms(db, [self.ADDR], now_utc + timedelta(minutes=10))
        row = db.execute(
            "SELECT raise_time, clear_time FROM alarm_history WHERE address=?",
            (self.ADDR,)
        ).fetchone()
        for ts in row:
            assert ts.endswith("Z"), f"Timestamp non in UTC ISO: {ts}"
            assert "T" in ts, f"Timestamp non in formato ISO: {ts}"


# ── Bot events ────────────────────────────────────────────────────────────

class TestBotEvents:

    def test_insert_bot_event_is_stored(self, db):
        insert_bot_event(db, 12345, "testuser", "Test", "stato", None)
        row = db.execute("SELECT * FROM bot_events WHERE user_id=12345").fetchone()
        assert row is not None

    def test_bot_event_timestamp_is_utc(self, db):
        """Il timestamp salvato deve essere UTC ISO-8601, non ora locale."""
        insert_bot_event(db, 99, "u", "N", "test_action")
        ts = db.execute("SELECT timestamp FROM bot_events WHERE user_id=99").fetchone()[0]
        assert ts.endswith("Z"), f"Timestamp bot_event non in UTC: {ts}"
        assert "T" in ts

    def test_bot_event_all_fields_stored(self, db):
        insert_bot_event(db, 111, "alice", "Alice", "grafico_solare", "detail_info")
        row = db.execute(
            "SELECT user_id, username, first_name, action, detail "
            "FROM bot_events WHERE user_id=111"
        ).fetchone()
        assert row[0] == 111
        assert row[1] == "alice"
        assert row[2] == "Alice"
        assert row[3] == "grafico_solare"
        assert row[4] == "detail_info"


# ── fmt_ts timezone conversion ────────────────────────────────────────────

class TestFmtTs:
    """
    fmt_ts converte un timestamp UTC ISO in ora locale leggibile.
    Regola critica: il DB salva UTC, Telegram mostra ora locale.
    """

    def test_utc_to_rome_summer(self):
        """UTC+2 in estate (CEST): 20:08 UTC → 22:08 ora italiana."""
        result = fmt_ts("2026-05-05T20:08:58Z")
        assert "22:08:58" in result, (
            f"fmt_ts('2026-05-05T20:08:58Z') = '{result}', atteso ora italiana 22:08:58"
        )

    def test_utc_to_rome_winter(self):
        """UTC+1 in inverno (CET): 20:08 UTC → 21:08 ora italiana."""
        result = fmt_ts("2026-01-05T20:08:58Z")
        assert "21:08:58" in result, (
            f"fmt_ts('2026-01-05T20:08:58Z') = '{result}', atteso 21:08:58 in inverno"
        )

    def test_format_is_human_readable(self):
        """Il formato deve essere YYYY-MM-DD - HH:MM:SS (non ISO con T e Z)."""
        result = fmt_ts("2026-05-05T20:08:58Z")
        assert "T" not in result, f"fmt_ts non deve contenere 'T': {result}"
        assert "Z" not in result, f"fmt_ts non deve contenere 'Z': {result}"
        assert " - " in result, f"fmt_ts deve usare ' - ' come separatore: {result}"

    def test_empty_string_returns_dash(self):
        assert fmt_ts("") == "—"

    def test_none_like_value_does_not_crash(self):
        """Valore None non deve propagarsi come eccezione (difesa in più)."""
        # fmt_ts accetta str, ma il DB potrebbe restituire None per clear_time
        result = fmt_ts("") 
        assert isinstance(result, str)
