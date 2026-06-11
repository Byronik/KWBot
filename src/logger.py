"""KWB logger – main scheduler + bot launcher + alarm monitor

Architettura thread:
  - Thread principale: bot Telegram (run_polling richiede il main thread per i signal handlers)
  - Thread secondario: scheduler polling Modbus (schedule + loop infinito)

Le notifiche allarmi dal thread polling usano asyncio.run_coroutine_threadsafe()
per accodarsi sull'event loop del bot invece di creare un loop separato.
"""

import argparse
import asyncio
import logging
import sys
import threading
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import schedule

import config
from db import (open_db, insert_readings_wide, insert_error,
                latest_readings_wide,
                get_open_alarm_addresses, insert_alarm,
                get_unnotified_raised_alarms, get_unnotified_cleared_alarms,
                mark_raise_notified, mark_clear_notified, close_alarms, fmt_ts)
from modbus_reader import connect, read_registers
from registers import all_registers, decode_enum
from alarms import read_active_alarms, ALARM_DEFS

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            Path(config.DB_PATH).parent / "kwb_logger.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("kwb_logger")

# Event loop del bot — impostato dal thread principale prima di avviare il polling
_bot_loop: asyncio.AbstractEventLoop | None = None

# Stato alert temperatura boiler (evita notifiche ripetute finché la soglia resta superata)
_alert_sent        : bool = False
_intervention_sent : bool = False


# ── Healthcheck ping ──────────────────────────────────────────────────────
def ping_healthcheck() -> None:
    """Invia un ping a healthchecks.io. Job separato, indipendente dal polling Modbus."""
    url = config.HEALTHCHECK_URL
    if not url:
        logger.warning("Healthcheck ping saltato: HEALTHCHECK_URL non configurato")
        return
    try:
        urllib.request.urlopen(url, timeout=5)
        logger.debug("Healthcheck ping inviato")
    except Exception as e:
        logger.warning(f"Healthcheck ping fallito: {e}")


# ── Alarm notifications ───────────────────────────────────────────────────
async def _notify_async(messages: list[str]) -> None:
    """Invia notifiche Telegram. Deve girare sull'event loop del bot."""
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_ALLOWED_IDS:
        return
    try:
        from telegram import Bot
        bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
        for text in messages:
            for uid in config.TELEGRAM_ALLOWED_IDS:
                try:
                    await bot.send_message(chat_id=uid, text=text, parse_mode="Markdown")
                except Exception as e:
                    logger.warning(f"Cannot notify user {uid}: {e}")
        await bot.shutdown()
    except Exception as e:
        logger.error(f"Notification failed: {e}")


def _notify(messages: list[str]) -> None:
    """
    Invia notifiche dal thread polling.
    Se il loop del bot è disponibile, accoda la coroutine su di esso.
    Altrimenti apre un loop temporaneo (modalità --no-bot o --once).
    """
    global _bot_loop
    if _bot_loop is not None and _bot_loop.is_running():
        future = asyncio.run_coroutine_threadsafe(_notify_async(messages), _bot_loop)
        try:
            future.result(timeout=15)
        except Exception as e:
            logger.error(f"Notification via bot loop failed: {e}")
    else:
        # Modalità senza bot: crea un loop temporaneo
        try:
            asyncio.run(_notify_async(messages))
        except Exception as e:
            logger.error(f"Notification (standalone) failed: {e}")


# ── Boiler temperature alerts ─────────────────────────────────────────────
def check_boiler_temp(temp: float) -> None:
    global _alert_sent, _intervention_sent

    t_alert = config.BOILER_ALERT_TEMP
    t_inter = config.BOILER_INTERVENTION_TEMP

    if t_inter > 0 and temp >= t_inter:
        # Soglia intervento superata — solo messaggio intervento
        _alert_sent = True  # sopprime l'alert minore
        if not _intervention_sent:
            msg = (
                f"🚨 *ALLARME – Temperatura caldaia critica*\n\n"
                f"La temperatura della caldaia ha superato la soglia di intervento.\n\n"
                f"🌡 Temperatura attuale: *{temp:.1f} °C*\n"
                f"🚨 Soglia di intervento: *{t_inter:.0f} °C*\n\n"
                f"⚠️ Intervenire subito!"
            )
            _notify([msg])
            _intervention_sent = True
            logger.warning(f"Boiler intervention alert inviato: {temp:.1f} °C >= {t_inter:.0f} °C")

    elif t_alert > 0 and temp >= t_alert:
        # Solo soglia allerta superata
        if _intervention_sent:
            # Transizione da intervento ad allerta: resetta entrambi i flag
            _intervention_sent = False
            _alert_sent = False
        if not _alert_sent:
            msg = (
                f"⚠️ *ATTENZIONE – Temperatura caldaia elevata*\n\n"
                f"La temperatura attuale della caldaia ha raggiunto la soglia di allerta.\n\n"
                f"🌡 Temperatura attuale: *{temp:.1f} °C*\n"
                f"⚠️ Soglia di allerta: *{t_alert:.0f} °C*\n\n"
                f"Monitorare la situazione."
            )
            _notify([msg])
            _alert_sent = True
            logger.warning(f"Boiler alert inviato: {temp:.1f} °C >= {t_alert:.0f} °C")

    else:
        # Sotto entrambe le soglie — reset stato
        _alert_sent = False
        _intervention_sent = False


# ── Alarm check ───────────────────────────────────────────────────────────
def check_alarms(db, client) -> None:
    now = datetime.now(timezone.utc)
    try:
        current_active = read_active_alarms(client, config.SLAVE_ID)
    except Exception as e:
        logger.warning(f"Alarm read failed: {e}")
        return

    open_in_db = get_open_alarm_addresses(db)

    # New alarms
    for addr in sorted(current_active - open_in_db):
        defn = ALARM_DEFS[addr]
        insert_alarm(db, addr, defn.alarm_id, defn.text_it, now)
        logger.warning(f"🚨 ALARM RAISED [{defn.alarm_id}] {defn.text_it}")

    # Send raise notifications
    unnotified_raised = get_unnotified_raised_alarms(db)
    if unnotified_raised:
        parts = ["🚨 *ALLARME CALDAIA KWB*", ""]
        for a in unnotified_raised:
            parts.append(f"⚠️ [{a['alarm_id']}] {a['text_it']}")
            parts.append(f"   Rilevato: {fmt_ts(a['raise_time'])}")
            parts.append("")
        try:
            _notify(["\n".join(parts)])
            mark_raise_notified(db, [a["id"] for a in unnotified_raised])
            logger.info(f"Raise notifications sent: {len(unnotified_raised)}")
        except Exception as e:
            logger.error(f"Failed to send raise notifications: {e}")

    # Cleared alarms
    cleared = open_in_db - current_active
    if cleared:
        close_alarms(db, list(cleared), now)
        for addr in sorted(cleared):
            defn = ALARM_DEFS.get(addr)
            logger.info(f"✅ ALARM CLEARED [{defn.alarm_id if defn else '?'}] "
                        f"{defn.text_it if defn else addr}")

    # Send clear notifications
    unnotified_cleared = get_unnotified_cleared_alarms(db)
    if unnotified_cleared:
        parts = ["✅ *ALLARME RIENTRATO \u2013 CALDAIA KWB*", ""]
        for a in unnotified_cleared:
            parts.append(f"✔️ [{a['alarm_id']}] {a['text_it']}")
            parts.append(f"   Inizio: {fmt_ts(a['raise_time'])}")
            parts.append(f"   Fine:   {fmt_ts(a['clear_time'])}")
            parts.append("")
        try:
            _notify(["\n".join(parts)])
            mark_clear_notified(db, [a["id"] for a in unnotified_cleared])
            logger.info(f"Clear notifications sent: {len(unnotified_cleared)}")
        except Exception as e:
            logger.error(f"Failed to send clear notifications: {e}")

    if current_active:
        logger.info(f"Alarm check: {len(current_active)} active alarm(s)")
    else:
        logger.debug("Alarm check: no active alarms")


# ── Single poll ───────────────────────────────────────────────────────────
def poll_once(db, registers) -> None:
    ts = datetime.now(timezone.utc)
    logger.info(f"Polling {len(registers)} registers …")

    try:
        client = connect(config.BOILER_IP, config.BOILER_PORT, config.TIMEOUT_S)
    except ConnectionError as exc:
        logger.error(f"Connection failed: {exc}")
        return

    try:
        results = read_registers(client, registers, config.SLAVE_ID)
        check_alarms(db, client)
    finally:
        client.close()

    insert_readings_wide(db, ts, results)

    # Alert temperatura boiler
    temp_result = next((r for r in results
                        if r.register.name == "boiler_temp_actual" and r.error is None), None)
    if temp_result is not None:
        check_boiler_temp(temp_result.scaled_value)

    err = 0
    for res in results:
        if res.error:
            err += 1
            logger.debug(f"  SKIP {res.register.name}: {res.error}")
            insert_error(db, ts, res.register.name, res.register.address, res.error)
        else:
            v = res.scaled_value
            if res.register.vt:
                label = decode_enum(res.register.vt, v)
                logger.debug(f"  {res.register.name:<40} = {int(v):>4} [{label}]")
            elif res.register.unit:
                logger.debug(f"  {res.register.name:<40} = {v:.2f} {res.register.unit}")
            else:
                logger.debug(f"  {res.register.name:<40} = {v:.2f}")

    ok = len([r for r in results if not r.error])
    logger.info(f"Poll complete: {ok} ok, {err} errors")


# ── Status printer ────────────────────────────────────────────────────────
def print_status(db) -> None:
    row = latest_readings_wide(db)
    if not row:
        print("Nessun dato nel DB. Esegui prima un poll.")
        return
    ts = row.pop("_timestamp", "—")
    print(f"\n{'─'*70}")
    print("  KWB EasyFire EF2 – Ultimi valori")
    print(f"{'─'*70}")
    for name, val in row.items():
        if val is not None:
            print(f"  {name:<42} {val:>10.2f}")
    print(f"\n  Ultimo poll: {ts}")
    print(f"{'─'*70}\n")


# ── Polling thread ────────────────────────────────────────────────────────
def _polling_thread(db, regs) -> None:
    """
    Gira in un thread secondario.
    Esegue subito un primo poll e un primo ping, poi schedula i successivi.
    """
    logger.info(f"Scheduler avviato – intervallo {config.POLL_INTERVAL_SECONDS}s")
    ping_healthcheck()
    poll_once(db, regs)
    schedule.every(300).seconds.do(ping_healthcheck)
    schedule.every(config.POLL_INTERVAL_SECONDS).seconds.do(
        poll_once, db=db, registers=regs)
    while True:
        schedule.run_pending()
        time.sleep(1)


# ── Entry point ───────────────────────────────────────────────────────────
def main():
    global _bot_loop

    parser = argparse.ArgumentParser()
    parser.add_argument("--once",   action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--no-bot", action="store_true")
    args = parser.parse_args()

    db   = open_db(config.DB_PATH)
    regs = all_registers()
    logger.info(f"Register list: {len(regs)} registers")

    if args.status:
        print_status(db); return
    if args.once:
        poll_once(db, regs); print_status(db); return

    if args.no_bot:
        # Senza bot: il polling gira nel thread principale
        logger.info(f"Scheduler avviato – intervallo {config.POLL_INTERVAL_SECONDS}s")
        ping_healthcheck()
        poll_once(db, regs)
        schedule.every(300).seconds.do(ping_healthcheck)
        schedule.every(config.POLL_INTERVAL_SECONDS).seconds.do(
            poll_once, db=db, registers=regs)
        while True:
            schedule.run_pending()
            time.sleep(1)
        return

    # Modalità normale: bot nel thread principale, polling in thread secondario
    try:
        from bot import build_application
        app = build_application(db)
    except (ImportError, ValueError) as exc:
        logger.warning(f"Bot non avviato: {exc}")
        # Fallback: polling nel thread principale
        logger.info(f"Scheduler avviato – intervallo {config.POLL_INTERVAL_SECONDS}s")
        ping_healthcheck()
        poll_once(db, regs)
        schedule.every(300).seconds.do(ping_healthcheck)
        schedule.every(config.POLL_INTERVAL_SECONDS).seconds.do(
            poll_once, db=db, registers=regs)
        while True:
            schedule.run_pending()
            time.sleep(1)
        return

    # Avvia il thread di polling
    t = threading.Thread(
        target=_polling_thread, args=(db, regs),
        name="modbus-poller", daemon=True,
    )
    t.start()

    # Il bot gira nel thread principale.
    # Cattura il loop asyncio appena creato da run_polling per le notifiche allarmi.
    async def _post_init(application) -> None:
        global _bot_loop
        _bot_loop = asyncio.get_running_loop()
        logger.info("Telegram bot avviato (polling)")

    app.post_init = _post_init
    app.run_polling(drop_pending_updates=True)
