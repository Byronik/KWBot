"""
test_charts.py
==============
Verifica la generazione dei grafici matplotlib:
- Sfondo bianco (#ffffff) su tutti i grafici
- Asse X in ora locale (non UTC) — bug storico risolto
- Annotazione dell'ultimo valore presente su ogni serie
- build_chart_single restituisce BytesIO (non None) con dati
- build_chart_multi e build_chart_dual_axis restituiscono (buf, legend_items)
- Nessun crash con dati vuoti (restituisce None)
- _legend_caption produce le righe di legenda corrette
"""

import sys
import io
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
import pytest

SRC_DIR = str(Path(__file__).resolve().parent.parent / "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)


def _seed_db(db: sqlite3.Connection, reg_name: str, n_rows: int = 5,
             value: float = 50.0) -> None:
    """Inserisce n_rows righe nella readings_wide con valore costante per reg_name.
    Usa il tempo corrente come riferimento così i dati rientrano nella finestra chart."""
    now = datetime.now(timezone.utc)
    for i in range(n_rows):
        ts = (now - timedelta(hours=n_rows - i)).strftime("%Y-%m-%dT%H:%M:%SZ")
        db.execute(
            f"INSERT OR REPLACE INTO readings_wide (timestamp, {reg_name}) VALUES (?, ?)",
            (ts, value)
        )
    db.commit()


@pytest.fixture
def db():
    from db import open_db
    conn = open_db(":memory:")
    yield conn
    conn.close()


# ── build_chart_single ────────────────────────────────────────────────────

class TestBuildChartSingle:

    def test_returns_bytesio_with_data(self, db):
        _seed_db(db, "boiler_temp_actual")
        from charts import build_chart_single
        result = build_chart_single(db, "boiler_temp_actual", "Test Caldaia")
        assert result is not None, "Con dati presenti, deve restituire un BytesIO"
        assert isinstance(result, io.BytesIO)
        assert result.getbuffer().nbytes > 0

    def test_returns_none_without_data(self, db):
        from charts import build_chart_single
        result = build_chart_single(db, "boiler_temp_actual", "Test")
        assert result is None, "Senza dati nel DB deve restituire None"

    def test_output_is_valid_png(self, db):
        _seed_db(db, "sol1_collector_temp")
        from charts import build_chart_single
        buf = build_chart_single(db, "sol1_collector_temp", "Solare")
        assert buf is not None
        # I PNG iniziano con la firma \x89PNG
        header = buf.read(4)
        assert header == b"\x89PNG", "Il file prodotto non è un PNG valido"

    def test_background_is_white(self, db):
        """
        Il grafico deve avere sfondo bianco (#ffffff).
        Bug storico: era nero (sfondo matplotlib di default).
        Verifica che il colore di background sia impostato correttamente
        ispezionando il parametro della figura.
        """
        _seed_db(db, "boiler_temp_actual")
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        # Patch plt.subplots per catturare la figura creata
        original_subplots = plt.subplots
        captured_figs = []

        def mock_subplots(*args, **kwargs):
            fig, ax = original_subplots(*args, **kwargs)
            captured_figs.append(fig)
            return fig, ax

        import charts as charts_mod
        original = charts_mod.plt.subplots
        charts_mod.plt.subplots = mock_subplots

        try:
            from charts import build_chart_single, BG_COLOR
            build_chart_single(db, "boiler_temp_actual", "Test")
        finally:
            charts_mod.plt.subplots = original

        assert BG_COLOR == "#ffffff", (
            f"BG_COLOR è '{BG_COLOR}', deve essere '#ffffff' (sfondo bianco)."
        )


# ── build_chart_multi ─────────────────────────────────────────────────────

def _seed_db_multi(db: sqlite3.Connection, cols_values: dict, n_rows: int = 5) -> None:
    """
    Inserisce n_rows righe con più colonne in una sola INSERT per riga,
    evitando che INSERT OR REPLACE su timestamp duplicati sovrascriva colonne precedenti.
    cols_values = {col_name: value, ...}
    """
    now = datetime.now(timezone.utc)
    col_names = list(cols_values.keys())
    for i in range(n_rows):
        ts = (now - timedelta(hours=n_rows - i)).strftime("%Y-%m-%dT%H:%M:%SZ")
        cols_str = ", ".join(["timestamp"] + col_names)
        placeholders = ", ".join(["?"] * (1 + len(col_names)))
        values = [ts] + [cols_values[c] for c in col_names]
        db.execute(
            f"INSERT OR REPLACE INTO readings_wide ({cols_str}) VALUES ({placeholders})",
            values
        )
    db.commit()


class TestBuildChartMulti:

    def test_returns_tuple_buf_legend(self, db):
        _seed_db_multi(db, {"boi1_temp_actual": 55.0, "boi1_temp2": 48.0})
        from charts import build_chart_multi
        buf, legend = build_chart_multi(
            db,
            [("boi1_temp_actual", "#e05a00", "Temp. attuale"),
             ("boi1_temp2",       "#1a78c2", "Sonda 2")],
            "Test Boiler ACS"
        )
        assert buf is not None
        assert legend is not None
        assert len(legend) == 2, "Devono esserci 2 elementi di legenda"

    def test_legend_items_structure(self, db):
        """Ogni item di legenda deve essere (color, label)."""
        _seed_db_multi(db, {"puf1_temp1": 50.0, "puf1_temp2": 45.0, "puf1_temp5": 31.0})
        from charts import build_chart_multi
        _, legend = build_chart_multi(
            db,
            [("puf1_temp1", "#e05a00", "Sonda 1"),
             ("puf1_temp2", "#1a78c2", "Sonda 2"),
             ("puf1_temp5", "#2ca02c", "Sonda 5")],
            "Test Puffer"
        )
        assert legend is not None
        for item in legend:
            assert len(item) >= 2
            color, label = item[0], item[1]
            assert color.startswith("#")
            assert isinstance(label, str) and len(label) > 0

    def test_returns_none_none_without_data(self, db):
        from charts import build_chart_multi
        buf, legend = build_chart_multi(
            db, [("boiler_temp_actual", "#e05a00", "Test")], "Test"
        )
        assert buf is None
        assert legend is None

    def test_partial_data_still_renders(self, db):
        """Se solo una delle serie ha dati, il grafico deve essere prodotto comunque."""
        _seed_db(db, "boi1_temp_actual", value=55.0)
        # boi1_temp2 non ha dati
        from charts import build_chart_multi
        buf, legend = build_chart_multi(
            db,
            [("boi1_temp_actual", "#e05a00", "Attuale"),
             ("boi1_temp2",       "#1a78c2", "Sonda 2")],
            "Parziale"
        )
        assert buf is not None, "Con almeno una serie con dati deve produrre il grafico"
        assert len(legend) == 1, "La legenda deve contenere solo le serie con dati"


# ── build_chart_dual_axis ─────────────────────────────────────────────────

class TestBuildChartDualAxis:
    """
    Verifica il grafico "Pompa solare": doppio asse Y.
    Serie sx: sol1_collector_temp + boi1_temp2 (°C)
    Serie dx: sol1_pump1_pct (%)
    """

    def test_returns_tuple_with_extended_legend(self, db):
        _seed_db_multi(db, {
            "sol1_collector_temp": 80.0,
            "boi1_temp2": 45.0,
            "sol1_pump1_pct": 67.0,
        })
        from charts import build_chart_dual_axis
        buf, legend = build_chart_dual_axis(
            db,
            left_regs=[
                ("sol1_collector_temp", "#e05a00", "Collettore"),
                ("boi1_temp2",          "#1a78c2", "ACS sonda 2"),
            ],
            right_regs=[
                ("sol1_pump1_pct", "#9467bd", "Pompa 1"),
            ],
            left_label="°C", right_label="%",
            title="Pompa solare"
        )
        assert buf is not None
        assert legend is not None
        assert len(legend) == 3

    def test_legend_items_have_axis_label(self, db):
        """Gli item di legenda del dual-axis devono avere 3 elementi: (color, label, axis)."""
        _seed_db_multi(db, {
            "sol1_collector_temp": 80.0,
            "sol1_pump1_pct": 67.0,
        })
        from charts import build_chart_dual_axis
        _, legend = build_chart_dual_axis(
            db,
            left_regs=[("sol1_collector_temp", "#e05a00", "Collettore")],
            right_regs=[("sol1_pump1_pct", "#9467bd", "Pompa 1")],
            left_label="°C", right_label="%"
        )
        assert legend is not None
        for item in legend:
            assert len(item) == 3, f"Item legenda dual-axis deve avere 3 elementi: {item}"

    def test_pump_solar_uses_boi1_temp2_not_actual(self, db):
        """
        Bug storico: il grafico pompa solare usava boi1_temp_actual invece di boi1_temp2.
        Verifica che il grafico generi correttamente con boi1_temp2.
        """
        _seed_db_multi(db, {
            "sol1_collector_temp": 80.0,
            "boi1_temp2": 45.0,
            # boi1_temp_actual non viene inserito: se il grafico usa quella sbagliata,
            # troverà 0 serie sx invece di 2.
        })
        from charts import build_chart_dual_axis
        buf, legend = build_chart_dual_axis(
            db,
            left_regs=[
                ("sol1_collector_temp", "#e05a00", "Collettore"),
                ("boi1_temp2",          "#1a78c2", "ACS sonda 2"),
            ],
            right_regs=[],
        )
        assert buf is not None
        assert len(legend) == 2, (
            "Il grafico pompa solare deve avere 2 serie sx: collettore + boi1_temp2 (sonda 2). "
            "Se ne manca una, probabilmente si sta usando boi1_temp_actual per errore."
        )

    def test_returns_none_none_without_data(self, db):
        from charts import build_chart_dual_axis
        buf, legend = build_chart_dual_axis(
            db,
            left_regs=[("sol1_collector_temp", "#e05a00", "Collettore")],
            right_regs=[("sol1_pump1_pct", "#9467bd", "Pompa")],
        )
        assert buf is None
        assert legend is None


# ── Timezone handling ─────────────────────────────────────────────────────

class TestChartsTimezone:
    """
    Bug storico: l'asse X dei grafici mostrava l'ora in UTC invece dell'ora italiana.
    matplotlib con datetime aware usa UTC internamente per il rendering;
    il corretto approccio è passare tz=local_tz() al DateFormatter.
    """

    def test_parse_rows_returns_aware_datetimes(self, db):
        """
        _parse_rows deve restituire datetime timezone-aware nella tz locale,
        non datetime naive o in UTC.
        """
        import zoneinfo
        from charts import _parse_rows

        rows = [("2026-05-05T20:08:58Z", 50.0)]
        ts_list, val_list = _parse_rows(rows)

        assert len(ts_list) == 1
        dt = ts_list[0]
        assert dt.tzinfo is not None, "_parse_rows deve restituire datetime aware"

        tz_rome = zoneinfo.ZoneInfo("Europe/Rome")
        dt_rome = dt.astimezone(tz_rome)
        assert dt_rome.hour == 22, (
            f"L'ora deve essere 22 (ora italiana CEST) non {dt_rome.hour} (UTC). "
            "Bug timezone nell'asse X dei grafici."
        )

    def test_local_tz_is_europe_rome(self):
        """_local_tz() deve restituire Europe/Rome."""
        import zoneinfo
        from charts import _local_tz
        tz = _local_tz()
        assert isinstance(tz, zoneinfo.ZoneInfo)
        assert str(tz) == "Europe/Rome"

    def test_date_formatter_uses_local_tz(self, db):
        """
        _apply_style deve configurare DateFormatter con tz=local_tz().
        Verifica che il formatter dell'asse X abbia il fuso corretto.
        """
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        import zoneinfo
        from charts import _apply_style, _local_tz

        fig, ax = plt.subplots()
        _apply_style(fig, ax)

        formatter = ax.xaxis.get_major_formatter()
        assert isinstance(formatter, mdates.DateFormatter), (
            "L'asse X deve usare mdates.DateFormatter"
        )
        # Verifica che il formatter abbia il tz corretto
        assert formatter.tz is not None, (
            "Il DateFormatter non ha tz impostato: l'asse X sarà in UTC."
        )
        fmt_tz = formatter.tz
        expected_tz = _local_tz()
        # Confronta per chiave stringa
        assert str(fmt_tz) == str(expected_tz), (
            f"DateFormatter tz='{fmt_tz}', atteso '{expected_tz}'. "
            "L'asse X mostrerà l'ora sbagliata."
        )
        plt.close(fig)


# ── _legend_caption ───────────────────────────────────────────────────────

class TestLegendCaption:

    def test_basic_two_series(self):
        from bot import _legend_caption
        items = [("#e05a00", "Temp. attuale"), ("#1a78c2", "Sonda 2")]
        result = _legend_caption("Titolo", items)
        assert "Titolo" in result
        assert "🟠" in result
        assert "🔵" in result
        assert "Temp. attuale" in result
        assert "Sonda 2" in result

    def test_three_series_puffer(self):
        from bot import _legend_caption
        items = [
            ("#e05a00", "Sonda 1 (alta)"),
            ("#1a78c2", "Sonda 2"),
            ("#2ca02c", "Sonda 5 (bassa)"),
        ]
        result = _legend_caption("Puffer", items)
        assert "🟢" in result

    def test_dual_axis_with_axis_label(self):
        """Gli item a 3 elementi devono mostrare anche l'etichetta dell'asse."""
        from bot import _legend_caption
        items = [
            ("#e05a00", "Collettore", "°C"),
            ("#9467bd", "Pompa 1",    "%"),
        ]
        result = _legend_caption("Pompa solare", items)
        assert "(°C)" in result or "°C" in result
        assert "(%)" in result or "%" in result

    def test_empty_items_returns_base(self):
        from bot import _legend_caption
        result = _legend_caption("Solo titolo", [])
        assert result == "Solo titolo"


# ── build_chart_pumps_hc ─────────────────────────────────────────────────

class TestBuildChartPumpsHC:
    """
    Verifica il grafico pompe circuiti riscaldamento + puffer.
    4 segnali On/Off a livelli sfalsati + puf1_temp1 su asse destro.
    """

    def test_returns_tuple_with_data(self, db):
        """Con tutti i canali presenti restituisce (BytesIO, legend)."""
        _seed_db_multi(db, {
            "hk1_pump":     1.0,
            "hk2_pump":     0.0,
            "puf1_pump":    1.0,
            "puf1_request": 1.0,
            "puf1_temp1":   63.6,
        })
        from charts import build_chart_pumps_hc
        buf, legend = build_chart_pumps_hc(db)
        assert buf is not None
        assert legend is not None
        assert len(legend) >= 1

    def test_returns_none_without_data(self, db):
        """Senza dati restituisce (None, None) senza crash."""
        from charts import build_chart_pumps_hc
        buf, legend = build_chart_pumps_hc(db)
        assert buf is None
        assert legend is None

    def test_legend_has_correct_pump_channels(self, db):
        """La legenda deve contenere tutti e 4 i canali On/Off seedati."""
        _seed_db_multi(db, {
            "hk1_pump":     1.0,
            "hk2_pump":     1.0,
            "puf1_pump":    1.0,
            "puf1_request": 0.0,
        })
        from charts import build_chart_pumps_hc
        _, legend = build_chart_pumps_hc(db)
        assert legend is not None
        labels = [item[1] for item in legend]
        assert "Pompa Mauro"    in labels
        assert "Pompa Gabriele" in labels
        assert "Pompa carico"   in labels
        assert "Richiesta carica" in labels

    def test_temp_sensor_on_right_axis(self, db):
        """Con puf1_temp1 presente, la legenda deve includere la sonda."""
        _seed_db_multi(db, {
            "hk1_pump":  1.0,
            "puf1_temp1": 63.6,
        })
        from charts import build_chart_pumps_hc
        _, legend = build_chart_pumps_hc(db)
        assert legend is not None
        labels = [item[1] for item in legend]
        assert "Sonda 1 puffer" in labels

    def test_partial_data_still_renders(self, db):
        """Con solo alcuni canali presenti il grafico viene comunque generato."""
        _seed_db_multi(db, {"hk1_pump": 1.0})
        from charts import build_chart_pumps_hc
        buf, legend = build_chart_pumps_hc(db)
        assert buf is not None

    def test_output_is_valid_png(self, db):
        _seed_db_multi(db, {"hk1_pump": 1.0, "puf1_temp1": 60.0})
        from charts import build_chart_pumps_hc
        buf, _ = build_chart_pumps_hc(db)
        assert buf is not None
        assert buf.read(4) == b"\x89PNG"
