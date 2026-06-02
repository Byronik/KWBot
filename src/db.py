"""
KWB logger – SQLite storage layer

Tables:
  readings_wide  : one row per poll cycle, one column per register (98 cols)
  errors         : registers that failed to respond
  bot_events     : Telegram button presses
  alarm_history  : alarm raise/clear history with timestamps
"""

import sqlite3
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Register column names (must match registers.all_registers() order) ────
REGISTER_COLUMNS = [
    "fw_version_major","fw_version_minor","fw_version_patch",
    "system_ok","group_fault","alarms_total","alarms_pending",
    "boiler_type","serial_number",
    "boiler_temp_actual","boiler_temp_setpoint","boiler_pump","boiler_pump_pct",
    "boiler_return_temp","boiler_output_pct","boiler_status","boiler_full_load_h",
    "boiler_oxygen_pct","boiler_flame_temp","boiler_neg_pressure",
    "boiler_primary_fan_pct","boiler_draught_pct","boiler_next_service_h",
    "boiler_conveyor","boiler_exhaust_temp","boiler_fuel_consumed_kg",
    "outside_temp","boiler_ash_level_pct","boiler_draught_rpm",
    "boiler_heat_total_kwh","boiler_status2",
    "boiler_on_off","boiler_setpoint_temp1","boiler_setpoint_temp2",
    "boiler_return_min_temp","boiler_ext_spec","boiler_program",
    "modbus_boiler_temp_sp","modbus_boiler_output_sp","boiler_fuel_remaining_kg",
    "hk1_flow_temp_actual","hk1_flow_temp_setpoint","hk1_room_temp_actual",
    "hk1_outside_temp","hk1_pump","hk1_room_temp_setpoint","hk1_status",
    "hk1_program","hk1_comfort_temp","hk1_reduct_temp",
    "hk2_flow_temp_actual","hk2_flow_temp_setpoint","hk2_room_temp_actual",
    "hk2_outside_temp","hk2_pump","hk2_room_temp_setpoint","hk2_status",
    "hk2_program","hk2_comfort_temp","hk2_reduct_temp",
    "puf1_temp1","puf1_temp2","puf1_temp3","puf1_temp4","puf1_temp5",
    "puf1_pump","puf1_request","puf1_valve","puf1_program",
    "puf1_temp_min","puf1_temp_max","puf1_dhw_temp_min",
    "boi1_temp_actual","boi1_charging_pump","boi1_request",
    "boi1_temp_setpoint","boi1_status","boi1_temp2",
    "boi1_program","boi1_temp_min","boi1_temp_max","boi1_heat_once",
    "sol1_status","sol1_status_reason","sol1_collector_temp",
    "sol1_tank1_temp","sol1_tank2_temp",
    "sol1_pump1","sol1_pump2","sol1_switchover_valve",
    "sol1_thermal_output_kw","sol1_heat_day_kwh","sol1_heat_total_kwh",
    "sol1_fwd_flow_temp","sol1_ret_flow_temp","sol1_flow_rate",
    "sol1_pump1_pct","sol1_pump2_pct",
]

# ── DDL ───────────────────────────────────────────────────────────────────
def _wide_cols_ddl() -> str:
    return ",\n    ".join(f"{c} REAL" for c in REGISTER_COLUMNS)

_DDL = f"""
CREATE TABLE IF NOT EXISTS readings_wide (
    timestamp TEXT PRIMARY KEY,
    {_wide_cols_ddl()}
);
CREATE INDEX IF NOT EXISTS idx_rw_ts ON readings_wide(timestamp);

CREATE TABLE IF NOT EXISTS errors (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp     TEXT    NOT NULL,
    register_name TEXT    NOT NULL,
    address       INTEGER NOT NULL,
    error_msg     TEXT
);

CREATE TABLE IF NOT EXISTS bot_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp  TEXT    NOT NULL,
    user_id    INTEGER NOT NULL,
    username   TEXT,
    first_name TEXT,
    action     TEXT    NOT NULL,
    detail     TEXT
);
CREATE INDEX IF NOT EXISTS idx_bot_events_ts   ON bot_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_bot_events_user ON bot_events(user_id, timestamp);

CREATE TABLE IF NOT EXISTS alarm_history (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    address        INTEGER NOT NULL,
    alarm_id       TEXT    NOT NULL,
    text_it        TEXT    NOT NULL,
    raise_time     TEXT    NOT NULL,
    clear_time     TEXT,
    notified       INTEGER NOT NULL DEFAULT 0,
    clear_notified INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_alarm_history_addr ON alarm_history(address, clear_time);
"""


def open_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.executescript(_DDL)
    conn.commit()
    logger.info(f"Database opened: {path}")
    return conn


# ── Wide table: write ─────────────────────────────────────────────────────
def insert_readings_wide(conn: sqlite3.Connection,
                         timestamp: datetime,
                         results: list) -> None:
    """
    Insert one row into readings_wide.
    `results` is the list of ReadResult from modbus_reader.read_registers().
    Missing/error registers are stored as NULL.
    """
    ts = timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")

    # Build a name→value map from results
    values: dict[str, float | None] = {c: None for c in REGISTER_COLUMNS}
    for res in results:
        if res.error is None and res.scaled_value is not None:
            name = res.register.name
            if name in values:
                values[name] = res.scaled_value

    cols   = ", ".join(["timestamp"] + REGISTER_COLUMNS)
    placeh = ", ".join(["?"] * (1 + len(REGISTER_COLUMNS)))
    row    = [ts] + [values[c] for c in REGISTER_COLUMNS]

    conn.execute(f"INSERT OR REPLACE INTO readings_wide ({cols}) VALUES ({placeh})", row)
    conn.commit()
    logger.debug(f"Wide row inserted at {ts}")


# ── Wide table: read ──────────────────────────────────────────────────────
def latest_readings_wide(conn: sqlite3.Connection) -> dict[str, float | None]:
    """Return the most recent row as a name→value dict."""
    row = conn.execute(
        f"SELECT {', '.join(REGISTER_COLUMNS)}, timestamp "
        "FROM readings_wide ORDER BY timestamp DESC LIMIT 1"
    ).fetchone()
    if not row:
        return {}
    result = {REGISTER_COLUMNS[i]: row[i] for i in range(len(REGISTER_COLUMNS))}
    result["_timestamp"] = row[-1]
    return result


def fetch_series_wide(conn: sqlite3.Connection,
                      register_name: str,
                      since_iso: str) -> list[tuple[str, float]]:
    """Return (timestamp, value) pairs for a single register since `since_iso`."""
    if register_name not in REGISTER_COLUMNS:
        return []
    rows = conn.execute(
        f"SELECT timestamp, {register_name} FROM readings_wide "
        f"WHERE timestamp >= ? AND {register_name} IS NOT NULL "
        f"ORDER BY timestamp",
        (since_iso,),
    ).fetchall()
    return [(r[0], r[1]) for r in rows]


# ── Errors ────────────────────────────────────────────────────────────────
def insert_error(conn: sqlite3.Connection, timestamp: datetime,
                 name: str, address: int, msg: str) -> None:
    ts = timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute(
        "INSERT INTO errors(timestamp,register_name,address,error_msg) VALUES (?,?,?,?)",
        (ts, name, address, msg),
    )
    conn.commit()


# ── Bot events ────────────────────────────────────────────────────────────
def insert_bot_event(conn: sqlite3.Connection, user_id: int,
                     username: str | None, first_name: str | None,
                     action: str, detail: str | None = None) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute(
        "INSERT INTO bot_events(timestamp,user_id,username,first_name,action,detail) "
        "VALUES (?,?,?,?,?,?)",
        (ts, user_id, username, first_name, action, detail),
    )
    conn.commit()
    logger.debug(f"Bot event: {action} by {first_name} (@{username})")


# ── Alarm history ─────────────────────────────────────────────────────────
def fmt_ts(iso_ts: str) -> str:
    """Convert ISO-8601 UTC timestamp to human-readable local time for Telegram."""
    if not iso_ts:
        return "—"
    try:
        import zoneinfo
        from datetime import timezone
        import config as _cfg
        tz_name  = getattr(_cfg, "DISPLAY_TIMEZONE", "Europe/Rome")
        tz       = zoneinfo.ZoneInfo(tz_name)
        dt_utc   = datetime.strptime(iso_ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        dt_local = dt_utc.astimezone(tz)
        return dt_local.strftime("%Y-%m-%d - %H:%M:%S")
    except Exception:
        return iso_ts.replace("T", " - ").replace("Z", "")


def get_open_alarm_addresses(conn: sqlite3.Connection) -> set[int]:
    rows = conn.execute(
        "SELECT address FROM alarm_history WHERE clear_time IS NULL"
    ).fetchall()
    return {r[0] for r in rows}


def insert_alarm(conn: sqlite3.Connection, address: int,
                 alarm_id: str, text_it: str, raise_time: datetime) -> None:
    ts = raise_time.strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute(
        "INSERT INTO alarm_history(address,alarm_id,text_it,raise_time,notified,clear_notified) "
        "VALUES (?,?,?,?,0,0)",
        (address, alarm_id, text_it, ts),
    )
    conn.commit()
    logger.info(f"Alarm raised [{alarm_id}] {text_it} at {ts}")


def get_unnotified_raised_alarms(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT id,address,alarm_id,text_it,raise_time "
        "FROM alarm_history WHERE clear_time IS NULL AND notified=0"
    ).fetchall()
    return [{"id":r[0],"address":r[1],"alarm_id":r[2],"text_it":r[3],"raise_time":r[4]}
            for r in rows]


def get_unnotified_cleared_alarms(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT id,address,alarm_id,text_it,raise_time,clear_time "
        "FROM alarm_history WHERE clear_time IS NOT NULL AND clear_notified=0"
    ).fetchall()
    return [{"id":r[0],"address":r[1],"alarm_id":r[2],"text_it":r[3],
             "raise_time":r[4],"clear_time":r[5]} for r in rows]


def mark_raise_notified(conn: sqlite3.Connection, ids: list[int]) -> None:
    conn.executemany("UPDATE alarm_history SET notified=1 WHERE id=?", [(i,) for i in ids])
    conn.commit()


def mark_clear_notified(conn: sqlite3.Connection, ids: list[int]) -> None:
    conn.executemany("UPDATE alarm_history SET clear_notified=1 WHERE id=?", [(i,) for i in ids])
    conn.commit()


def close_alarms(conn: sqlite3.Connection,
                 addresses: list[int], clear_time: datetime) -> None:
    ts = clear_time.strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.executemany(
        "UPDATE alarm_history SET clear_time=? WHERE address=? AND clear_time IS NULL",
        [(ts, a) for a in addresses],
    )
    conn.commit()
    logger.info(f"Alarms closed at {ts}: {addresses}")
