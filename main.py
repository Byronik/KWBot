"""
KWB EasyFire – entry point

Usage:
    python main.py                  # polling + bot Telegram
    python main.py --no-bot         # solo polling
    python main.py --once           # singolo poll (test)
    python main.py --status         # stampa ultimi valori dal DB
    python main.py query status
    python main.py query history boiler_temp_actual --days 7
    python main.py query export --out dati.csv
    python main.py query errors
"""

import sys
from pathlib import Path

# src/ deve essere primo nel path per evitare collisioni con pacchetti di sistema
_src = str(Path(__file__).resolve().parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "query":
        sys.argv = [sys.argv[0]] + sys.argv[2:]
        from query import main
    else:
        from logger import main
    main()
