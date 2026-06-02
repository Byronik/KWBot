"""
Migrazione da readings (EAV) a readings_wide.
Eseguire UNA SOLA VOLTA prima di riavviare il logger.

    python migrate.py

Dopo aver verificato che tutto funziona, puoi eliminare la vecchia tabella:
    python migrate.py --drop-old
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
import config
from db import open_db, REGISTER_COLUMNS

def migrate(conn, drop_old: bool = False) -> None:
    print("=== Migrazione readings → readings_wide ===")

    # Fetch all distinct timestamps from old table
    timestamps = [r[0] for r in conn.execute(
        "SELECT DISTINCT timestamp FROM readings ORDER BY timestamp"
    ).fetchall()]
    print(f"Timestamps da migrare: {len(timestamps)}")

    cols_ph = ", ".join(["?"] * (1 + len(REGISTER_COLUMNS)))
    col_names = "timestamp, " + ", ".join(REGISTER_COLUMNS)

    migrated = 0
    for ts in timestamps:
        # Fetch all values for this timestamp
        rows = conn.execute(
            "SELECT register_name, scaled_value FROM readings WHERE timestamp=?", (ts,)
        ).fetchall()
        val_map: dict[str, float | None] = {c: None for c in REGISTER_COLUMNS}
        for name, val in rows:
            if name in val_map:
                val_map[name] = val

        row = [ts] + [val_map[c] for c in REGISTER_COLUMNS]
        conn.execute(
            f"INSERT OR IGNORE INTO readings_wide ({col_names}) VALUES ({cols_ph})", row
        )
        migrated += 1
        if migrated % 500 == 0:
            conn.commit()
            print(f"  {migrated}/{len(timestamps)} righe migrate…")

    conn.commit()
    print(f"Migrazione completata: {migrated} righe inserite in readings_wide.")

    if drop_old:
        conn.execute("DROP TABLE IF EXISTS readings")
        conn.commit()
        print("Tabella 'readings' eliminata.")
    else:
        count = conn.execute("SELECT COUNT(*) FROM readings").fetchone()[0]
        print(f"\nTabella 'readings' ancora presente ({count} righe EAV).")
        print("Dopo aver verificato i dati, esegui:")
        print("  python migrate.py --drop-old")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--drop-old", action="store_true",
                        help="Elimina la vecchia tabella readings dopo la migrazione")
    args = parser.parse_args()
    conn = open_db(config.DB_PATH)
    migrate(conn, drop_old=args.drop_old)


if __name__ == "__main__":
    main()
