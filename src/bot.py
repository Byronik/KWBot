"""KWB EasyFire – Telegram Bot (python-telegram-bot >= 22.0)"""

import logging
import sqlite3
from datetime import datetime, timezone, timedelta

import zoneinfo

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes, filters,
)

import config
from charts import build_chart_single, build_chart_multi, build_chart_dual_axis, build_chart_pumps_hc


def _legend_caption(base: str, items: list) -> str:
    """Build a caption string appending a color-dot legend for multi-series charts."""
    if not items:
        return base
    # Each item is (color_hex, label) or (color_hex, label, axis_label)
    COLOR_DOTS = {
        "#e05a00": "🟠", "#1a78c2": "🔵", "#2ca02c": "🟢",
        "#9467bd": "🟣", "#d62728": "🔴", "#8c564b": "🟤",
    }
    parts = []
    for item in items:
        color, label = item[0], item[1]
        axis = f" ({item[2]})" if len(item) > 2 else ""
        dot = COLOR_DOTS.get(color, "●")
        parts.append(f"{dot} {label}{axis}")
    return base + "\n" + "  ".join(parts)

from db import insert_bot_event, latest_readings_wide, fetch_series_wide
from modbus_reader import connect, read_registers
from registers import all_registers, decode_enum

logger = logging.getLogger("kwb_bot")

# ── Button labels ─────────────────────────────────────────────────────────
BTN_STATO            = "🔥 Stato"
BTN_CONF             = "⚙️ Configurazione"
BTN_APPROF           = "🔍 Valori minori"
BTN_TOTALI           = "📊 Totali"
BTN_MAXMIN           = "📉 Massimi/Minimi"
BTN_CHART_BOILER     = "📈 Temp. caldaia"
BTN_CHART_SOLAR      = "☀️ Temp. solare"
BTN_CHART_BOI_ACS    = "🚿 Temp. boiler ACS"
BTN_CHART_PUFFER     = "💧 Temp. puffer"
BTN_CHART_OUTSIDE    = "🌡 Temp. esterna"
BTN_CHART_PUMP_SOLAR = "⚡ Pompa solare"
BTN_CHART_POWER      = "🔆 Potenza caldaia"
BTN_CHART_PUMPS_HC   = "🔄 Pompe circuiti"
BTN_INVISIBLE        = "🔕 Valori n.d."

KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton(BTN_STATO),            KeyboardButton(BTN_CONF)],
        [KeyboardButton(BTN_APPROF),           KeyboardButton(BTN_TOTALI)],
        [KeyboardButton(BTN_MAXMIN),           KeyboardButton(BTN_CHART_BOILER)],
        [KeyboardButton(BTN_CHART_SOLAR),      KeyboardButton(BTN_CHART_BOI_ACS)],
        [KeyboardButton(BTN_CHART_PUFFER),     KeyboardButton(BTN_CHART_OUTSIDE)],
        [KeyboardButton(BTN_CHART_PUMP_SOLAR), KeyboardButton(BTN_CHART_POWER)],
        [KeyboardButton(BTN_CHART_PUMPS_HC),   KeyboardButton(BTN_INVISIBLE)],
    ],
    resize_keyboard=True, is_persistent=True, input_field_placeholder="Scegli…",
)

# ── Register metadata ─────────────────────────────────────────────────────
# Maps register_name → (italian_label, category, writable)
REGISTER_META: dict[str, tuple[str, str, bool]] = {
    # Sistema
    "system_ok":                ("Sistema OK",                   "STATO",      False),
    "group_fault":              ("Guasto di gruppo",             "STATO",      False),
    "alarms_total":             ("Allarmi totali",               "STATO",      False),
    "alarms_pending":           ("Allarmi attivi",               "STATO",      False),
    "boiler_type":              ("Tipo caldaia",                 "APPROF",     False),
    "serial_number":            ("Numero di serie",              "APPROF",     False),
    "fw_version_major":         ("Firmware Major",               "APPROF",     False),
    "fw_version_minor":         ("Firmware Minor",               "APPROF",     False),
    "fw_version_patch":         ("Firmware Patch",               "APPROF",     False),
    # Caldaia – stato
    "boiler_status":            ("Stato caldaia (esteso)",       "STATO",      False),
    "boiler_status2":           ("Stato caldaia (sintetico)",    "STATO",      False),
    "boiler_temp_actual":       ("Temperatura attuale",          "STATO",      False),
    "boiler_return_temp":       ("Temperatura ritorno",          "STATO",      False),
    "boiler_output_pct":        ("Potenza (%)",                  "STATO",      False),
    "boiler_pump":              ("Pompa caldaia",                "STATO",      False),
    "boiler_pump_pct":          ("Pompa caldaia (%)",            "STATO",      False),
    "boiler_conveyor":          ("Coclea pellet",                "STATO",      False),
    "outside_temp":             ("Temperatura esterna",          "STATO",      False),
    "boiler_on_off":            ("Caldaia accesa/spenta",        "STATO",      True),
    "boiler_program":           ("Programma caldaia",            "STATO",      False),
    "boiler_fuel_remaining_kg": ("Pellet residuo (kg)",          "STATO",      True),
    # Caldaia – conf
    "boiler_temp_setpoint":     ("Temperatura nominale",         "CONF",       False),
    "boiler_setpoint_temp1":    ("Setpoint temperatura 1",       "CONF",       False),
    "boiler_setpoint_temp2":    ("Setpoint temperatura 2",       "CONF",       False),
    "boiler_return_min_temp":   ("Temp. minima ritorno",         "CONF",       False),
    # Caldaia – approf
    "boiler_oxygen_pct":        ("Ossigeno nei fumi (λ)",        "APPROF",     False),
    "boiler_flame_temp":        ("Temperatura fiamma",           "APPROF",     False),
    "boiler_neg_pressure":      ("Depressione camera",           "APPROF",     False),
    "boiler_primary_fan_pct":   ("Ventilatore primario (%)",     "APPROF",     False),
    "boiler_draught_pct":       ("Ventilatore tiraggio (%)",     "APPROF",     False),
    "boiler_draught_rpm":       ("Ventilatore tiraggio (rpm)",   "APPROF",     False),
    "boiler_exhaust_temp":      ("Temperatura fumi",             "INVISIBILE", False),
    # Caldaia – totali
    "boiler_full_load_h":       ("Ore a pieno carico",           "TOTALI",     False),
    "boiler_next_service_h":    ("Ore al prossimo service",      "TOTALI",     False),
    "boiler_ash_level_pct":     ("Livello cenere (%)",           "TOTALI",     False),
    "boiler_fuel_consumed_kg":  ("Pellet consumato totale (kg)", "TOTALI",     False),
    "boiler_heat_total_kwh":    ("Energia termica totale (kWh)", "INVISIBILE", False),
    # Caldaia – invisibile
    "boiler_ext_spec":          ("Tipo sorgente setpoint ext.",  "INVISIBILE", False),
    "modbus_boiler_temp_sp":    ("Setpoint temp. via Modbus",    "INVISIBILE", False),
    "modbus_boiler_output_sp":  ("Setpoint potenza via Modbus",  "INVISIBILE", False),
    # Riscaldamento Mauro (HK1)
    "hk1_flow_temp_actual":     ("Temperatura mandata",          "STATO",      False),
    "hk1_flow_temp_setpoint":   ("Mandata nominale",             "CONF",       False),
    "hk1_outside_temp":         ("Temperatura esterna",          "INVISIBILE", False),
    "hk1_pump":                 ("Pompa circuito",               "STATO",      False),
    "hk1_status":               ("Stato circuito",               "STATO",      False),
    "hk1_room_temp_setpoint":   ("Temp. ambiente nominale",      "CONF",       False),
    "hk1_program":              ("Programma",                    "CONF",       True),
    "hk1_comfort_temp":         ("Temperatura comfort",          "CONF",       True),
    "hk1_reduct_temp":          ("Temperatura abbassamento",     "CONF",       True),
    "hk1_room_temp_actual":     ("Temperatura ambiente",         "INVISIBILE", False),
    # Riscaldamento Gabriele (HK2)
    "hk2_flow_temp_actual":     ("Temperatura mandata",          "STATO",      False),
    "hk2_flow_temp_setpoint":   ("Mandata nominale",             "CONF",       False),
    "hk2_outside_temp":         ("Temperatura esterna",          "INVISIBILE", False),
    "hk2_pump":                 ("Pompa circuito",               "STATO",      False),
    "hk2_status":               ("Stato circuito",               "STATO",      False),
    "hk2_room_temp_setpoint":   ("Temp. ambiente nominale",      "CONF",       False),
    "hk2_program":              ("Programma",                    "CONF",       True),
    "hk2_comfort_temp":         ("Temperatura comfort",          "CONF",       True),
    "hk2_reduct_temp":          ("Temperatura abbassamento",     "CONF",       True),
    "hk2_room_temp_actual":     ("Temperatura ambiente",         "INVISIBILE", False),
    # Puffer
    "puf1_temp1":               ("Sonda 1 – alta",               "STATO",      False),
    "puf1_temp2":               ("Sonda 2",                      "STATO",      False),
    "puf1_temp5":               ("Sonda 5 – bassa",              "STATO",      False),
    "puf1_pump":                ("Pompa carico",                 "STATO",      False),
    "puf1_request":             ("Richiesta carica",             "STATO",      False),
    "puf1_program":             ("Programma",                    "CONF",       True),
    "puf1_temp_min":            ("Temperatura minima",           "CONF",       True),
    "puf1_temp_max":            ("Temperatura massima",          "CONF",       True),
    "puf1_dhw_temp_min":        ("Temp. minima ACS",             "CONF",       True),
    "puf1_temp3":               ("Sonda 3",                      "INVISIBILE", False),
    "puf1_temp4":               ("Sonda 4",                      "INVISIBILE", False),
    "puf1_valve":               ("Valvola commutazione",         "INVISIBILE", False),
    # Boiler ACS
    "boi1_temp_actual":         ("Temperatura attuale",          "STATO",      False),
    "boi1_temp2":               ("Temperatura sonda 2",          "STATO",      False),
    "boi1_charging_pump":       ("Pompa di carico",              "STATO",      False),
    "boi1_request":             ("Richiesta carica",             "STATO",      False),
    "boi1_status":              ("Stato boiler",                 "STATO",      False),
    "boi1_heat_once":           ("Riscaldamento una-tantum",     "STATO",      True),
    "boi1_temp_setpoint":       ("Temperatura nominale",         "CONF",       False),
    "boi1_program":             ("Programma",                    "CONF",       True),
    "boi1_temp_min":            ("Temperatura minima",           "CONF",       True),
    "boi1_temp_max":            ("Temperatura massima",          "CONF",       True),
    # Solare
    "sol1_status":              ("Stato solare",                 "STATO",      False),
    "sol1_status_reason":       ("Causa stato",                  "STATO",      False),
    "sol1_collector_temp":      ("Temperatura collettore",       "STATO",      False),
    "sol1_tank1_temp":          ("Temperatura serbatoio 1",      "STATO",      False),
    "sol1_pump1":               ("Pompa 1",                      "STATO",      False),
    "sol1_pump1_pct":           ("Pompa 1 (%)",                  "STATO",      False),
    "sol1_switchover_valve":    ("Valvola commutazione",         "STATO",      False),
    "sol1_ret_flow_temp":       ("Temperatura ritorno",          "STATO",      False),
    "sol1_tank2_temp":          ("Temperatura serbatoio 2",      "INVISIBILE", False),
    "sol1_pump2":               ("Pompa 2",                      "INVISIBILE", False),
    "sol1_pump2_pct":           ("Pompa 2 (%)",                  "INVISIBILE", False),
    "sol1_thermal_output_kw":   ("Potenza termica (kW)",         "INVISIBILE", False),
    "sol1_heat_day_kwh":        ("Energia solare oggi (kWh)",    "INVISIBILE", False),
    "sol1_heat_total_kwh":      ("Energia solare totale (kWh)",  "INVISIBILE", False),
    "sol1_fwd_flow_temp":       ("Temperatura mandata",          "INVISIBILE", False),
    "sol1_flow_rate":           ("Portata (l/min)",              "INVISIBILE", False),
}

# Section display order and labels
SECTIONS = [
    ("sys",    "⚙️ Sistema"),
    ("boiler", "🔥 Caldaia"),
    ("hk",     "🌡 Riscaldamento – Mauro"),
    ("hk2",    "🌡 Riscaldamento – Gabriele"),
    ("puf",    "💧 Puffer"),
    ("boi",    "🚿 Boiler ACS"),
    ("sol",    "☀️ Solare"),
]

ON_OFF_REGISTERS = {
    "boiler_pump", "boiler_conveyor", "boiler_on_off",
    "hk1_pump", "hk2_pump",
    "puf1_pump", "puf1_request",
    "boi1_charging_pump", "boi1_request", "boi1_heat_once",
    "sol1_pump1", "sol1_pump2", "sol1_switchover_valve",
}
YES_NO_REGISTERS = {"system_ok", "group_fault"}

_GROUP_MAP: dict[str, str] = {}


def _build_group_map() -> dict[str, str]:
    from registers import all_registers as _ar
    return {r.name: r.group for r in _ar()}


def _allowed(update: Update) -> bool:
    uid = update.effective_user.id
    ok = uid in config.TELEGRAM_ALLOWED_IDS
    if not ok:
        logger.warning(f"Unauthorized: {uid} @{update.effective_user.username}")
    return ok


async def _deny(update: Update) -> None:
    await update.message.reply_text("⛔ Non sei autorizzato.")


def _log_event(update: Update, db: sqlite3.Connection,
               action: str, detail: str | None = None) -> None:
    u = update.effective_user
    insert_bot_event(db, u.id, u.username, u.first_name, action, detail)


def _fmt_val(name: str, val: float) -> str:
    for r in all_registers():
        if r.name == name:
            if r.vt:
                return decode_enum(r.vt, val)
            elif r.unit:
                return f"{val:.1f} {r.unit}"
            else:
                return str(int(val))
    return str(val)


def _fmt_onoff(raw: str) -> str:
    if raw.lower() in ("on", "yes", "sì", "si", "1"):
        return "🟢 On"
    if raw.lower() in ("off", "no", "0"):
        return "🔴 Off"
    return raw


def _fmt_yesno(raw: str) -> str:
    if raw.lower() in ("yes", "sì", "si", "1", "ok"):
        return "✅"
    if raw.lower() in ("no", "0", "fault", "error"):
        return "❌"
    return raw


def _render_value(name: str, val: float) -> str:
    raw = _fmt_val(name, val)
    if name in YES_NO_REGISTERS:
        return _fmt_yesno(raw)
    if name in ON_OFF_REGISTERS:
        return _fmt_onoff(raw)
    return raw


def _local_ts(iso_ts: str) -> str:
    try:
        tz = zoneinfo.ZoneInfo(getattr(config, "DISPLAY_TIMEZONE", "Europe/Rome"))
        dt = datetime.strptime(iso_ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        return dt.astimezone(tz).strftime("%d/%m %H:%M")
    except Exception:
        return iso_ts


def _build_section_messages(data: dict[str, float | None], category: str) -> list[str]:
    global _GROUP_MAP
    if not _GROUP_MAP:
        _GROUP_MAP = _build_group_map()

    tz = zoneinfo.ZoneInfo(getattr(config, "DISPLAY_TIMEZONE", "Europe/Rome"))
    now = datetime.now(timezone.utc).astimezone(tz).strftime("%d/%m/%Y %H:%M")
    cat_labels = {
        "STATO":      "🔥 Stato caldaia",
        "CONF":       "⚙️ Configurazione",
        "APPROF":     "🔍 Valori minori",
        "TOTALI":     "📊 Totali",
        "INVISIBILE": "🔕 Valori n.d.",
    }
    header = f"📡 *{cat_labels.get(category, category)}* — {now}\n"

    messages: list[str] = []
    current = header

    for group_key, section_title in SECTIONS:
        group_regs = {
            name: (label, writable)
            for name, (label, cat, writable) in REGISTER_META.items()
            if cat == category and _GROUP_MAP.get(name, "") == group_key
        }
        if not group_regs:
            continue

        lines: list[str] = []
        rendered: set[str] = set()

        # ── Compact: alarms ──────────────────────────────────────────────
        if (category == "STATO"
                and "alarms_total" in group_regs and "alarms_pending" in group_regs):
            t = int(data.get("alarms_total") or 0)
            p = int(data.get("alarms_pending") or 0)
            lines.append(f"Allarmi: Totali {t} — Attivi {p}")
            rendered |= {"alarms_total", "alarms_pending"}

        # ── Compact: boiler status ───────────────────────────────────────
        if (category == "STATO"
                and "boiler_status" in group_regs and "boiler_status2" in group_regs):
            v2 = data.get("boiler_status2")
            v1 = data.get("boiler_status")
            s2 = _render_value("boiler_status2", v2) if v2 is not None else "—"
            s1 = _render_value("boiler_status", v1) if v1 is not None else "—"
            lines.append(f"Stato Caldaia: {s2} ({s1})")
            rendered |= {"boiler_status", "boiler_status2"}

        # ── Compact: mandata + ritorno ───────────────────────────────────
        if (category == "STATO"
                and "boiler_temp_actual" in group_regs
                and "boiler_return_temp" in group_regs):
            ta = data.get("boiler_temp_actual")
            tr = data.get("boiler_return_temp")
            sa = _render_value("boiler_temp_actual", ta) if ta is not None else "—"
            sr = _render_value("boiler_return_temp", tr) if tr is not None else "—"
            lines.append(f"Temperatura attuale: mandata {sa} — ritorno {sr}")
            rendered |= {"boiler_temp_actual", "boiler_return_temp"}

        # ── Compact: pompa caldaia ───────────────────────────────────────
        if (category == "STATO"
                and "boiler_pump" in group_regs and "boiler_pump_pct" in group_regs):
            vp  = data.get("boiler_pump")
            vpp = data.get("boiler_pump_pct")
            sp  = _render_value("boiler_pump", vp) if vp is not None else "—"
            spp = _render_value("boiler_pump_pct", vpp) if vpp is not None else "—"
            lines.append(f"Pompa Caldaia: {sp} ({spp})")
            rendered |= {"boiler_pump", "boiler_pump_pct"}

        # ── Compact: pompa solare 1 ──────────────────────────────────────
        if (category == "STATO"
                and "sol1_pump1" in group_regs and "sol1_pump1_pct" in group_regs):
            v1  = data.get("sol1_pump1")
            v1p = data.get("sol1_pump1_pct")
            s1  = _render_value("sol1_pump1", v1) if v1 is not None else "—"
            s1p = _render_value("sol1_pump1_pct", v1p) if v1p is not None else "—"
            lines.append(f"Pompa 1: {s1} — {s1p}")
            rendered |= {"sol1_pump1", "sol1_pump1_pct"}

        # ── Regular rows ─────────────────────────────────────────────────
        for name, (label, writable) in group_regs.items():
            if name in rendered:
                continue
            val = data.get(name)
            if val is None:
                continue
            prefix = "✏️ " if writable else ""
            lines.append(f"{prefix}{label}: {_render_value(name, val)}")

        if not lines:
            continue

        block = f"\n*{section_title}*\n" + "\n".join(lines) + "\n"
        if len(current) + len(block) > 3800:
            messages.append(current.strip())
            current = block
        else:
            current += block

    if current.strip() and current.strip() != header.strip():
        messages.append(current.strip())

    return messages or ["⚠️ Nessun dato disponibile."]


def _build_maxmin_message(db: sqlite3.Connection) -> str:
    tz = zoneinfo.ZoneInfo(getattr(config, "DISPLAY_TIMEZONE", "Europe/Rome"))
    now_utc = datetime.now(timezone.utc)
    since_24h = (now_utc - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
    since_7d  = (now_utc - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    since_all = "2000-01-01T00:00:00Z"

    targets = [
        ("sol1_collector_temp", "🌡 Collettore solare"),
        ("boi1_temp_actual",    "🚿 Temperatura ACS"),
        ("outside_temp",        "🌤 Temperatura esterna"),
    ]

    lines = [f"📉 *Massimi e Minimi* — {now_utc.astimezone(tz).strftime('%d/%m/%Y %H:%M')}\n"]

    for reg, label in targets:
        lines.append(f"\n*{label}*")
        for period_label, since in [
            ("Ultime 24h",       since_24h),
            ("Ultima settimana", since_7d),
            ("Assoluto",         since_all),
        ]:
            rows = fetch_series_wide(db, reg, since)
            if not rows:
                lines.append(f"  _{period_label}_: nessun dato")
                continue
            # rows = list of (timestamp, value)
            max_row = max(rows, key=lambda r: r[1])
            min_row = min(rows, key=lambda r: r[1])
            lines.append(
                f"  _{period_label}_:\n"
                f"    🔺 max: *{max_row[1]:.1f} °C* ({_local_ts(max_row[0])})\n"
                f"    🔻 min: *{min_row[1]:.1f} °C* ({_local_ts(min_row[0])})"
            )

    return "\n".join(lines)


async def _fetch_live_data() -> dict[str, float | None]:
    client = connect(config.BOILER_IP, config.BOILER_PORT, config.TIMEOUT_S)
    results = read_registers(client, all_registers(), config.SLAVE_ID)
    client.close()
    data: dict[str, float | None] = {}
    for res in results:
        if res.error is None and res.scaled_value is not None:
            data[res.register.name] = res.scaled_value
    return data


async def _send_category(update: Update, context: ContextTypes.DEFAULT_TYPE,
                          category: str, action_log: str) -> None:
    if not _allowed(update):
        await _deny(update); return
    _log_event(update, context.bot_data["db"], action_log)
    loading = await update.message.reply_text("⏳ Interrogo la caldaia…")
    try:
        data = await _fetch_live_data()
        messages = _build_section_messages(data, category)
        await loading.delete()
        for i, text in enumerate(messages):
            is_last = (i == len(messages) - 1)
            await update.message.reply_text(
                text, parse_mode="Markdown",
                reply_markup=KEYBOARD if is_last else None,
            )
    except ConnectionError as exc:
        await loading.edit_text(f"❌ Connessione fallita: {exc}")
    except Exception as exc:
        logger.exception("send_category error")
        await loading.edit_text(f"❌ Errore: {exc}")


async def handle_stato(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_category(update, context, "STATO", "stato")

async def handle_conf(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_category(update, context, "CONF", "conf")

async def handle_approf(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_category(update, context, "APPROF", "approf")

async def handle_totali(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_category(update, context, "TOTALI", "totali")

async def handle_invisible(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_category(update, context, "INVISIBILE", "invisibile")


async def handle_maxmin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        await _deny(update); return
    _log_event(update, context.bot_data["db"], "maxmin")
    loading = await update.message.reply_text("⏳ Calcolo massimi e minimi…")
    try:
        text = _build_maxmin_message(context.bot_data["db"])
        await loading.delete()
        await update.message.reply_text(text, parse_mode="Markdown",
                                        reply_markup=KEYBOARD)
    except Exception as exc:
        logger.exception("handle_maxmin error")
        await loading.edit_text(f"❌ Errore: {exc}")


async def _send_chart_single(update: Update, db: sqlite3.Connection,
                              reg: str, title: str, action: str) -> None:
    _log_event(update, db, action)
    loading = await update.message.reply_text("⏳ Genero il grafico…")
    buf = build_chart_single(db, reg, title)
    if buf is None:
        await loading.edit_text(
            f"⚠️ Nessun dato per '{title}' nelle ultime {config.CHART_HOURS}h."
        )
        await update.message.reply_text("Usa i pulsanti per continuare.",
                                        reply_markup=KEYBOARD)
        return
    await loading.delete()
    await update.message.reply_photo(
        photo=buf,
        caption=f"📈 {title} – ultime {config.CHART_HOURS}h",
        reply_markup=KEYBOARD,
    )


async def handle_chart_boiler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update): await _deny(update); return
    await _send_chart_single(update, context.bot_data["db"],
                              "boiler_temp_actual", "Temperatura caldaia", "grafico_caldaia")


async def handle_chart_solar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update): await _deny(update); return
    await _send_chart_single(update, context.bot_data["db"],
                              "sol1_collector_temp", "Temp. collettore solare", "grafico_solare")


async def handle_chart_boi_acs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update): await _deny(update); return
    _log_event(update, context.bot_data["db"], "grafico_boiler_acs")
    loading = await update.message.reply_text("⏳ Genero il grafico…")
    buf, legend = build_chart_multi(
        context.bot_data["db"],
        regs=[
            ("boi1_temp_actual", "#e05a00", "Temp. attuale"),
            ("boi1_temp2",       "#1a78c2", "Sonda 2"),
        ],
        title="Temperatura boiler ACS",
    )
    if buf is None:
        await loading.edit_text("⚠️ Nessun dato per boiler ACS.")
        await update.message.reply_text("Usa i pulsanti per continuare.", reply_markup=KEYBOARD)
        return
    await loading.delete()
    caption = _legend_caption(f"🚿 Temp. boiler ACS – ultime {config.CHART_HOURS}h", legend)
    await update.message.reply_photo(photo=buf, caption=caption, reply_markup=KEYBOARD)


async def handle_chart_puffer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update): await _deny(update); return
    _log_event(update, context.bot_data["db"], "grafico_puffer")
    loading = await update.message.reply_text("⏳ Genero il grafico…")
    buf, legend = build_chart_multi(
        context.bot_data["db"],
        regs=[
            ("puf1_temp1", "#e05a00", "Sonda 1 (alta)"),
            ("puf1_temp2", "#1a78c2", "Sonda 2"),
            ("puf1_temp5", "#2ca02c", "Sonda 5 (bassa)"),
        ],
        title="Temperatura puffer (sonde 1 – 2 – 5)",
    )
    if buf is None:
        await loading.edit_text("⚠️ Nessun dato per il puffer.")
        await update.message.reply_text("Usa i pulsanti per continuare.", reply_markup=KEYBOARD)
        return
    await loading.delete()
    caption = _legend_caption(f"💧 Temp. puffer – ultime {config.CHART_HOURS}h", legend)
    await update.message.reply_photo(photo=buf, caption=caption, reply_markup=KEYBOARD)


async def handle_chart_outside(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update): await _deny(update); return
    await _send_chart_single(update, context.bot_data["db"],
                              "outside_temp", "Temperatura esterna", "grafico_esterna")


async def handle_chart_pump_solar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update): await _deny(update); return
    _log_event(update, context.bot_data["db"], "grafico_pompa_solare")
    loading = await update.message.reply_text("⏳ Genero il grafico…")
    buf, legend = build_chart_dual_axis(
        context.bot_data["db"],
        left_regs=[
            ("sol1_collector_temp", "#e05a00", "Collettore"),
            ("boi1_temp2",          "#1a78c2", "ACS sonda 2"),
        ],
        right_regs=[
            ("sol1_pump1_pct", "#9467bd", "Pompa 1"),
        ],
        left_label="°C",
        right_label="%",
        title="Pompa solare + temperature",
    )
    if buf is None:
        await loading.edit_text("⚠️ Nessun dato per pompa solare.")
        await update.message.reply_text("Usa i pulsanti per continuare.", reply_markup=KEYBOARD)
        return
    await loading.delete()
    caption = _legend_caption(f"⚡ Pompa solare – ultime {config.CHART_HOURS}h", legend)
    await update.message.reply_photo(photo=buf, caption=caption, reply_markup=KEYBOARD)


async def handle_chart_power(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update): await _deny(update); return
    _log_event(update, context.bot_data["db"], "grafico_potenza")
    loading = await update.message.reply_text("⏳ Genero il grafico…")
    buf, legend = build_chart_multi(
        context.bot_data["db"],
        regs=[
            ("boiler_output_pct", "#e05a00", "Potenza caldaia"),
            ("boiler_pump_pct",   "#1a78c2", "Pompa caldaia"),
        ],
        title="Potenza % caldaia + pompa",
        ylabel="%",
    )
    if buf is None:
        await loading.edit_text("⚠️ Nessun dato per potenza caldaia.")
        await update.message.reply_text("Usa i pulsanti per continuare.", reply_markup=KEYBOARD)
        return
    await loading.delete()
    caption = _legend_caption(f"🔆 Potenza caldaia – ultime {config.CHART_HOURS}h", legend)
    await update.message.reply_photo(photo=buf, caption=caption, reply_markup=KEYBOARD)


async def handle_chart_pumps_hc(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update): await _deny(update); return
    _log_event(update, context.bot_data["db"], "grafico_pompe_circuiti")
    loading = await update.message.reply_text("⏳ Genero il grafico…")
    buf, legend = build_chart_pumps_hc(context.bot_data["db"])
    if buf is None:
        await loading.edit_text("⚠️ Nessun dato per pompe circuiti.")
        await update.message.reply_text("Usa i pulsanti per continuare.", reply_markup=KEYBOARD)
        return
    await loading.delete()
    caption = _legend_caption(
        f"🔄 Pompe circuiti + puffer – ultime {config.CHART_HOURS}h", legend
    )
    await update.message.reply_photo(photo=buf, caption=caption, reply_markup=KEYBOARD)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update): await _deny(update); return
    _log_event(update, context.bot_data["db"], "start")
    name = update.effective_user.first_name or "utente"
    await update.message.reply_text(
        f"👋 Ciao {name}! Sono il monitor della tua caldaia KWB EasyFire EF2.\n\n"
        "Usa i pulsanti qui sotto per interrogare la caldaia o visualizzare i grafici.",
        reply_markup=KEYBOARD,
    )


async def handle_unknown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update): await _deny(update); return
    await update.message.reply_text("Usa i pulsanti 👇", reply_markup=KEYBOARD)


def build_application(db: sqlite3.Connection) -> Application:
    if not config.TELEGRAM_BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN mancante in config.ini")
    if not config.TELEGRAM_ALLOWED_IDS:
        raise ValueError("TELEGRAM_ALLOWED_IDS vuoto in config.ini")

    app = (Application.builder()
           .token(config.TELEGRAM_BOT_TOKEN)
           .get_updates_read_timeout(30)
           .get_updates_write_timeout(30)
           .get_updates_connect_timeout(30)
           .build())
    app.bot_data["db"] = db

    app.add_handler(CommandHandler("start", cmd_start))

    app.add_handler(MessageHandler(filters.Text([BTN_STATO]),     handle_stato))
    app.add_handler(MessageHandler(filters.Text([BTN_CONF]),      handle_conf))
    app.add_handler(MessageHandler(filters.Text([BTN_APPROF]),    handle_approf))
    app.add_handler(MessageHandler(filters.Text([BTN_TOTALI]),    handle_totali))
    app.add_handler(MessageHandler(filters.Text([BTN_MAXMIN]),    handle_maxmin))
    app.add_handler(MessageHandler(filters.Text([BTN_INVISIBLE]), handle_invisible))

    app.add_handler(MessageHandler(filters.Text([BTN_CHART_BOILER]),     handle_chart_boiler))
    app.add_handler(MessageHandler(filters.Text([BTN_CHART_SOLAR]),      handle_chart_solar))
    app.add_handler(MessageHandler(filters.Text([BTN_CHART_BOI_ACS]),    handle_chart_boi_acs))
    app.add_handler(MessageHandler(filters.Text([BTN_CHART_PUFFER]),     handle_chart_puffer))
    app.add_handler(MessageHandler(filters.Text([BTN_CHART_OUTSIDE]),    handle_chart_outside))
    app.add_handler(MessageHandler(filters.Text([BTN_CHART_PUMP_SOLAR]), handle_chart_pump_solar))
    app.add_handler(MessageHandler(filters.Text([BTN_CHART_POWER]),      handle_chart_power))
    app.add_handler(MessageHandler(filters.Text([BTN_CHART_PUMPS_HC]),   handle_chart_pumps_hc))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_unknown))

    logger.info(f"Bot pronto — autorizzati: {config.TELEGRAM_ALLOWED_IDS}")
    return app
