"""KWB EasyFire – Chart generation (matplotlib)."""

import io
import logging
import sqlite3
import zoneinfo
from datetime import datetime, timezone, timedelta

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

import config
from db import fetch_series_wide

logger = logging.getLogger("kwb_charts")

# ── Style constants ───────────────────────────────────────────────────────
BG_COLOR    = "#ffffff"
GRID_COLOR  = "#e0e0e0"
TEXT_COLOR  = "#222222"
TICK_COLOR  = "#555555"
SPINE_COLOR = "#bbbbbb"
LINE_WIDTH  = 1.8
FIG_W, FIG_H = 10, 4.2
DPI = 130


def _local_tz() -> zoneinfo.ZoneInfo:
    return zoneinfo.ZoneInfo(getattr(config, "DISPLAY_TIMEZONE", "Europe/Rome"))


def _since_str() -> str:
    hours = getattr(config, "CHART_HOURS", 24)
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _parse_rows(rows: list[tuple]) -> tuple[list, list]:
    """Parse (iso_utc_str, value) → aware datetime in local tz + float.

    Datetime objects are kept timezone-aware so matplotlib receives them
    correctly. The x-axis formatter is then set with tz=local_tz() so labels
    are displayed in local time rather than UTC.
    """
    tz = _local_tz()
    ts_list, val_list = [], []
    for ts, val in rows:
        try:
            dt = (datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")
                  .replace(tzinfo=timezone.utc)
                  .astimezone(tz))
            ts_list.append(dt)
            val_list.append(float(val))
        except Exception:
            pass
    return ts_list, val_list


def _apply_style(fig: plt.Figure, ax: plt.Axes) -> None:
    tz = _local_tz()
    hours = getattr(config, "CHART_HOURS", 24)
    fig.patch.set_facecolor(BG_COLOR)
    ax.set_facecolor(BG_COLOR)
    ax.tick_params(colors=TICK_COLOR, labelsize=8)
    ax.xaxis.label.set_color(TEXT_COLOR)
    ax.yaxis.label.set_color(TEXT_COLOR)
    ax.title.set_color(TEXT_COLOR)
    for spine in ax.spines.values():
        spine.set_color(SPINE_COLOR)
    ax.grid(True, color=GRID_COLOR, linewidth=0.6, linestyle="--")
    fmt = "%H:%M" if hours <= 12 else "%d/%m %H:%M"
    ax.xaxis.set_major_formatter(mdates.DateFormatter(fmt, tz=tz))
    ax.xaxis.set_major_locator(mdates.HourLocator(interval=3))
    fig.autofmt_xdate(rotation=30, ha="right")


def _annotate_last(ax: plt.Axes, ts: list, vals: list,
                   color: str, unit: str = "°C") -> None:
    """Annotate the last data point with its value."""
    if not ts or not vals:
        return
    last_ts, last_val = ts[-1], vals[-1]
    ax.annotate(
        f"{last_val:.1f} {unit}".strip(),
        xy=(last_ts, last_val),
        xytext=(8, 6),
        textcoords="offset points",
        fontsize=8,
        color=color,
        bbox=dict(boxstyle="round,pad=0.25", fc="white", ec=color, alpha=0.88),
    )


def _to_buf(fig: plt.Figure) -> io.BytesIO:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=DPI, bbox_inches="tight",
                facecolor=BG_COLOR, edgecolor="none")
    buf.seek(0)
    plt.close(fig)
    return buf


# ── Public builders ───────────────────────────────────────────────────────

def build_chart_single(
    db: sqlite3.Connection,
    reg: str,
    title: str,
    color: str = "#e05a00",
    ylabel: str = "°C",
) -> io.BytesIO | None:
    """Single-series line chart with last-value annotation."""
    rows = fetch_series_wide(db, reg, _since_str())
    if not rows:
        return None
    ts, vals = _parse_rows(rows)
    if not ts:
        return None

    fig, ax = plt.subplots(figsize=(FIG_W, FIG_H))
    _apply_style(fig, ax)
    ax.plot(ts, vals, color=color, linewidth=LINE_WIDTH, solid_capstyle="round")
    ax.fill_between(ts, vals, alpha=0.12, color=color)
    _annotate_last(ax, ts, vals, color, ylabel)
    ax.set_title(title, fontsize=12, fontweight="bold", pad=10)
    ax.set_ylabel(ylabel, fontsize=9)
    return _to_buf(fig)


def build_chart_multi(
    db: sqlite3.Connection,
    regs: list[tuple[str, str, str]],   # [(reg_name, color, label), ...]
    title: str,
    ylabel: str = "°C",
) -> tuple[io.BytesIO, list[tuple[str, str]]] | tuple[None, None]:
    """Multi-series chart, single Y axis, last-value annotation on each series."""
    since = _since_str()
    series = []
    legend_items = []
    for reg, color, label in regs:
        rows = fetch_series_wide(db, reg, since)
        if rows:
            ts, vals = _parse_rows(rows)
            if ts:
                series.append((ts, vals, color))
                legend_items.append((color, label))

    if not series:
        return None, None

    fig, ax = plt.subplots(figsize=(FIG_W, FIG_H))
    _apply_style(fig, ax)
    for ts, vals, color in series:
        ax.plot(ts, vals, color=color, linewidth=LINE_WIDTH, solid_capstyle="round")
        ax.fill_between(ts, vals, alpha=0.08, color=color)
        _annotate_last(ax, ts, vals, color, ylabel)
    ax.set_title(title, fontsize=12, fontweight="bold", pad=10)
    ax.set_ylabel(ylabel, fontsize=9)
    return _to_buf(fig), legend_items


def build_chart_dual_axis(
    db: sqlite3.Connection,
    left_regs:  list[tuple[str, str, str]],   # [(reg, color, label), ...]
    right_regs: list[tuple[str, str, str]],
    left_label:  str = "°C",
    right_label: str = "%",
    title: str = "",
) -> tuple[io.BytesIO, list[tuple[str, str, str]]] | tuple[None, None]:
    """Dual Y-axis chart with last-value annotation on each series."""
    since = _since_str()

    def _load(specs):
        out = []
        for reg, color, lbl in specs:
            rows = fetch_series_wide(db, reg, since)
            if rows:
                ts, vals = _parse_rows(rows)
                if ts:
                    out.append((ts, vals, color, lbl))
        return out

    left_series  = _load(left_regs)
    right_series = _load(right_regs)
    if not left_series and not right_series:
        return None, None

    legend_items = []
    fig, ax_l = plt.subplots(figsize=(FIG_W, FIG_H))
    _apply_style(fig, ax_l)
    ax_l.set_ylabel(left_label, fontsize=9, color=TEXT_COLOR)

    for ts, vals, color, lbl in left_series:
        ax_l.plot(ts, vals, color=color, linewidth=LINE_WIDTH, solid_capstyle="round")
        ax_l.fill_between(ts, vals, alpha=0.08, color=color)
        _annotate_last(ax_l, ts, vals, color, left_label)
        legend_items.append((color, lbl, left_label))

    if right_series:
        ax_r = ax_l.twinx()
        ax_r.set_facecolor(BG_COLOR)
        ax_r.set_ylabel(right_label, fontsize=9, color=TEXT_COLOR)
        ax_r.tick_params(colors=TICK_COLOR, labelsize=8)
        for spine in ax_r.spines.values():
            spine.set_color(SPINE_COLOR)
        ax_r.set_ylim(0, 110)
        for ts, vals, color, lbl in right_series:
            ax_r.plot(ts, vals, color=color, linewidth=LINE_WIDTH,
                      linestyle="--", solid_capstyle="round")
            ax_r.fill_between(ts, vals, alpha=0.10, color=color)
            _annotate_last(ax_r, ts, vals, color, right_label)
            legend_items.append((color, lbl, right_label))

    if title:
        ax_l.set_title(title, fontsize=12, fontweight="bold", pad=10, color=TEXT_COLOR)

    return _to_buf(fig), legend_items


def build_chart_pumps_hc(
    db: sqlite3.Connection,
) -> tuple[io.BytesIO, list[tuple[str, str, str]]] | tuple[None, None]:
    """
    Grafico pompe circuiti riscaldamento + puffer.

    Asse sinistro (On/Off a livelli sfalsati, nessuna sovrapposizione):
      livello 3  hk1_pump    – Pompa Mauro       #e05a00 arancione
      livello 2  hk2_pump    – Pompa Gabriele     #1a78c2 blu
      livello 1  puf1_pump   – Pompa carico       #2ca02c verde
      livello 0  puf1_request– Richiesta carica   #9467bd viola

    Asse destro (°C):
      puf1_temp1 – Sonda 1 puffer                 #8c564b marrone, tratteggiata

    I segnali On/Off (0/1) vengono scalati su fasce di altezza 0.8
    con gap di 0.2 tra una fascia e l'altra:
      fascia k: da k*1.0 a k*1.0 + 0.8  (k = 0..3)
    """
    since = _since_str()
    tz = _local_tz()

    # ── Definizione canali On/Off ──────────────────────────────────────
    ONOFF_CHANNELS = [
        ("puf1_request", "#9467bd", "Richiesta carica"),   # livello 0 (basso)
        ("puf1_pump",    "#2ca02c", "Pompa carico"),        # livello 1
        ("hk2_pump",     "#1a78c2", "Pompa Gabriele"),      # livello 2
        ("hk1_pump",     "#e05a00", "Pompa Mauro"),         # livello 3 (alto)
    ]
    BAND_HEIGHT = 0.8   # altezza banda On per ogni segnale
    BAND_STEP   = 1.0   # passo tra bande (step - height = 0.2 gap)

    # ── Carica serie On/Off ────────────────────────────────────────────
    onoff_series = []
    legend_items = []
    for level, (reg, color, label) in enumerate(ONOFF_CHANNELS):
        rows = fetch_series_wide(db, reg, since)
        if not rows:
            continue
        ts_list, val_list = _parse_rows(rows)
        if not ts_list:
            continue
        # Scala: 0 → base del livello, 1 → base + BAND_HEIGHT
        base = level * BAND_STEP
        scaled = [base + v * BAND_HEIGHT for v in val_list]
        onoff_series.append((ts_list, scaled, color, label, base, level))
        legend_items.append((color, label, "On/Off"))

    # ── Carica serie temperatura puffer ───────────────────────────────
    temp_rows = fetch_series_wide(db, "puf1_temp1", since)
    temp_series = None
    if temp_rows:
        ts_t, vals_t = _parse_rows(temp_rows)
        if ts_t:
            temp_series = (ts_t, vals_t)
            legend_items.append(("#8c564b", "Sonda 1 puffer", "°C"))

    if not onoff_series and temp_series is None:
        return None, None

    # ── Figura ────────────────────────────────────────────────────────
    fig, ax_l = plt.subplots(figsize=(FIG_W, FIG_H + 0.8))
    _apply_style(fig, ax_l)

    # Asse sinistro: segnali On/Off
    n_channels = len(ONOFF_CHANNELS)
    ax_l.set_ylim(-0.15, n_channels * BAND_STEP)
    ax_l.set_ylabel("", fontsize=9)   # nessuna etichetta: i tick sono sostituiti
    ax_l.set_yticks([])               # nascondi i tick numerici

    # Aggiungi linee guida orizzontali e label per ogni canale
    for level, (_, color, label) in enumerate(ONOFF_CHANNELS):
        base = level * BAND_STEP
        # Linea base canale
        ax_l.axhline(base, color=color, linewidth=0.4, linestyle=":", alpha=0.5)
        # Etichetta a sinistra della y
        ax_l.text(
            -0.01, base + BAND_HEIGHT / 2,
            label,
            transform=ax_l.get_yaxis_transform(),
            ha="right", va="center",
            fontsize=7, color=color,
        )

    # Disegna i segnali On/Off come step (fill_between)
    for ts_list, scaled, color, label, base, level in onoff_series:
        ax_l.step(ts_list, scaled, where="post",
                  color=color, linewidth=1.6, solid_capstyle="butt")
        ax_l.fill_between(ts_list, base, scaled,
                          step="post", alpha=0.30, color=color)

    # ── Asse destro: temperatura puffer ───────────────────────────────
    if temp_series:
        ts_t, vals_t = temp_series
        ax_r = ax_l.twinx()
        ax_r.set_facecolor(BG_COLOR)
        ax_r.set_ylabel("°C", fontsize=9, color=TEXT_COLOR)
        ax_r.tick_params(colors=TICK_COLOR, labelsize=8)
        for spine in ax_r.spines.values():
            spine.set_color(SPINE_COLOR)
        ax_r.plot(ts_t, vals_t, color="#8c564b", linewidth=LINE_WIDTH,
                  linestyle="--", solid_capstyle="round")
        ax_r.fill_between(ts_t, vals_t, alpha=0.10, color="#8c564b")
        _annotate_last(ax_r, ts_t, vals_t, "#8c564b", "°C")

    ax_l.set_title(
        f"Pompe circuiti + puffer – ultime {getattr(config, 'CHART_HOURS', 24)}h",
        fontsize=12, fontweight="bold", pad=10, color=TEXT_COLOR,
    )

    return _to_buf(fig), legend_items
