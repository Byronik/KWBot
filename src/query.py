"""
KWB logger – query CLI (readings_wide version)

Usage: python main.py query <comando>

  status                           ultimo valore per ogni registro
  history <register> [--days N]    storico di un registro
  export [--out file.csv]          esporta tutto in CSV
  errors                           errori di lettura recenti
  bot-events [--limit N]           log pressioni pulsanti Telegram
"""

import argparse
import csv
import sqlite3
import sys
from datetime import datetime, timezone, timedelta

import config
from db import REGISTER_COLUMNS, latest_readings_wide, fetch_series_wide


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def cmd_status(conn):
    from registers import all_registers, decode_enum
    reg_map = {r.name: r for r in all_registers()}
    data = latest_readings_wide(conn)
    if not data:
        print("Nessun dato."); return
    ts = data.pop("_timestamp", "—")
    grp = None
    for name, val in data.items():
        if val is None: continue
        reg = reg_map.get(name)
        g = reg.group if reg else "?"
        if g != grp:
            grp = g
            print(f"\n[{grp.upper()}]")
        if reg and reg.vt:
            display = decode_enum(reg.vt, val)
        elif reg and reg.unit:
            display = f"{val:.2f} {reg.unit}"
        else:
            display = f"{val:.2f}"
        print(f"  {name:<42} {display}")
    print(f"\nUltimo poll: {ts}")


def cmd_history(conn, register: str, days: int):
    if register not in REGISTER_COLUMNS:
        print(f"Registro '{register}' non trovato."); return
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows  = fetch_series_wide(conn, register, since)
    if not rows:
        print(f"Nessun dato per '{register}' negli ultimi {days} giorni."); return
    print(f"\nStorico '{register}' (ultimi {days}g, {len(rows)} campioni):\n")
    for ts, val in rows:
        print(f"  {ts}   {val:>10.3f}")


def cmd_export(conn, out: str):
    rows = conn.execute(
        f"SELECT timestamp, {', '.join(REGISTER_COLUMNS)} "
        "FROM readings_wide ORDER BY timestamp"
    ).fetchall()
    if not rows:
        print("Nessun dato da esportare."); return
    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp"] + REGISTER_COLUMNS)
        writer.writerows(rows)
    print(f"Esportate {len(rows)} righe in {out}")


def cmd_errors(conn, limit: int = 50):
    rows = conn.execute(
        "SELECT timestamp,register_name,address,error_msg FROM errors "
        "ORDER BY timestamp DESC LIMIT ?", (limit,)
    ).fetchall()
    if not rows:
        print("Nessun errore registrato."); return
    for row in rows:
        print(f"  {row[0]}  {row[1]:<35} @{row[2]}  {row[3]}")


def cmd_bot_events(conn, limit: int = 100):
    rows = conn.execute(
        "SELECT timestamp,first_name,username,action,detail "
        "FROM bot_events ORDER BY timestamp DESC LIMIT ?", (limit,)
    ).fetchall()
    if not rows:
        print("Nessun evento bot registrato."); return
    print(f"\n{'─'*75}")
    print(f"  {'Timestamp':<22} {'Nome':<15} {'Username':<18} {'Azione'}")
    print(f"{'─'*75}")
    for row in rows:
        ts, name, uname, action, detail = row
        uname_s  = f"@{uname}" if uname else "—"
        detail_s = f"  [{detail}]" if detail else ""
        print(f"  {ts:<22} {(name or '—'):<15} {uname_s:<18} {action}{detail_s}")
    print(f"{'─'*75}\n")


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("status")
    ph = sub.add_parser("history")
    ph.add_argument("register")
    ph.add_argument("--days", type=int, default=1)
    pe = sub.add_parser("export")
    pe.add_argument("--out", default="kwb_export.csv")
    sub.add_parser("errors")
    pbe = sub.add_parser("bot-events")
    pbe.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    if not args.cmd:
        parser.print_help(); sys.exit(1)
    conn = _conn()
    {
        "status":     lambda: cmd_status(conn),
        "history":    lambda: cmd_history(conn, args.register, args.days),
        "export":     lambda: cmd_export(conn, args.out),
        "errors":     lambda: cmd_errors(conn),
        "bot-events": lambda: cmd_bot_events(conn, args.limit),
    }[args.cmd]()
