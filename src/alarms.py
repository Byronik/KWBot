"""
KWB EasyFire EF2 – Alarm monitor
Source: ModbusInfo-en-V25_4_0.xlsx — sheet "Alarms"

Protocol:
  - Function Code 02 (Read Discrete Inputs / Coils)
  - Each bit address = one alarm; 0 = OK, 1 = ACTIVE
  - Addresses are sparse (gaps between groups), read in contiguous blocks

Logic:
  - On every poll, read all alarm coils
  - For each newly active alarm (was 0, now 1): notify and persist to DB
  - For each alarm that clears (was 1, now 0): reset so it can re-trigger
  - State is kept in the `alarm_state` DB table (survives restarts)
"""

import logging
from dataclasses import dataclass

from pymodbus.client import ModbusTcpClient
from pymodbus.exceptions import ModbusException

logger = logging.getLogger(__name__)

# ── Italian translations ───────────────────────────────────────────────────
# Full map from xlsx — English → Italian. Untranslated entries fall back to English.
_IT: dict[str, str] = {
    "Battery empty":
        "Batteria scarica",
    "Ignition exhaust gas temperature increase not achieved 1!":
        "Accensione: incremento temperatura fumi non raggiunto (tentativo 1)!",
    "Ignition exhaust gas temperature increase not achieved 2!":
        "Accensione: incremento temperatura fumi non raggiunto (tentativo 2)!",
    "Ignition not working! (Pellets)":
        "Accensione non funzionante! (Pellet)",
    "Main drive speed too high!":
        "Velocità coclea principale troppo alta!",
    "Main drive speed too low!":
        "Velocità coclea principale troppo bassa!",
    "Main drive speed measurement not working!":
        "Misurazione velocità coclea non funzionante!",
    "Safety shutdown - room air CO value too high!":
        "Arresto di sicurezza – valore CO nell'aria ambiente troppo alto!",
    "No flame detectable!":
        "Nessuna fiamma rilevabile!",
    "Attention - emergency operation without lambda probe terminated!":
        "Attenzione – funzionamento di emergenza senza sonda lambda terminato!",
    "Exhaust gas temperature implausible!":
        "Temperatura fumi non plausibile!",
    "Exhaust gas temperature in operation too high!":
        "Temperatura fumi durante il funzionamento troppo alta!",
    "Exhaust gas temperature in operation too low!":
        "Temperatura fumi durante il funzionamento troppo bassa!",
    "Safety thermostat! Boiler overheating!":
        "Termostato di sicurezza attivato! Surriscaldamento caldaia!",
    "The emergency stop button has been activated!":
        "Il pulsante di arresto di emergenza è stato attivato!",
    "The ash container was incorrectly installed!":
        "Il contenitore della cenere non è installato correttamente!",
    "Electronic error on digital inputs!":
        "Errore elettronico sugli ingressi digitali!",
    "KSM module error!":
        "Errore modulo KSM!",
    "Temperature increase in the fuel storage!":
        "Aumento di temperatura nel deposito combustibile!",
    "Alarm! Internal error!":
        "Allarme! Errore interno!",
    "The secondary air fan speed is too low!":
        "Velocità ventilatore aria secondaria troppo bassa!",
    "The primary air fan speed is too low!":
        "Velocità ventilatore aria primaria troppo bassa!",
    "The induced draught fan speed is too low!":
        "Velocità ventilatore tiraggio troppo bassa!",
    "The negative pressure in the combustion chamber cannot be regulated!":
        "Impossibile regolare la depressione nella camera di combustione!",
    "Negative pressure sensor is faulty!":
        "Sensore depressione difettoso!",
    "Lambda probe is faulty!":
        "Sonda lambda difettosa!",
    "Conveyor motor is overheated!":
        "Motore coclea surriscaldato!",
    "Fuel storage is empty!":
        "Deposito combustibile vuoto!",
    "Fuel container is empty!":
        "Contenitore combustibile vuoto!",
    "Electronics are overheated!":
        "Elettronica surriscaldata!",
    "Boiler sensor is missing or faulty!":
        "Sensore caldaia mancante o difettoso!",
    "Boiler temperature implausible!":
        "Temperatura caldaia non plausibile!",
    "Return flow boost malfunction!":
        "Malfunzionamento elevatore temperatura ritorno!",
    "Return-flow sensor is missing or faulty!":
        "Sensore temperatura ritorno mancante o difettoso!",
    "Maintenance interval expired.":
        "Intervallo di manutenzione scaduto.",
    "Control interval expired!":
        "Intervallo di controllo scaduto!",
    "Measuring mode is activated!":
        "Modalità misurazione attivata!",
    "24V safety circuit not active, input 133!":
        "Circuito di sicurezza 24V non attivo, ingresso 133!",
    "Safety chain 230V reserve is interrupted":
        "Catena di sicurezza 230V (riserva) interrotta",
    "Error conveyor system fill level!":
        "Errore livello riempimento sistema di trasporto!",
    "Error in the sampling probe system!":
        "Errore nel sistema sonda di campionamento!",
    "Fuel storage is almost empty!":
        "Deposito combustibile quasi vuoto!",
    "Secondary air fan speed is too high!":
        "Velocità ventilatore aria secondaria troppo alta!",
    "24V safety circuit not active, input 130!":
        "Circuito di sicurezza 24V non attivo, ingresso 130!",
    "24V safety circuit not active, input 131!":
        "Circuito di sicurezza 24V non attivo, ingresso 131!",
    "24V safety circuit not active, input 132!":
        "Circuito di sicurezza 24V non attivo, ingresso 132!",
    "Primary fan speed is too high!":
        "Velocità ventilatore primario troppo alta!",
    "Induced draught fan speed is too high!":
        "Velocità ventilatore tiraggio troppo alta!",
    "Room air CO value too high!":
        "Valore CO nell'aria ambiente troppo alto!",
    "The flame temperature sensor is missing or faulty!":
        "Sensore temperatura fiamma mancante o difettoso!",
    "O2 value during operation too high!":
        "Valore O2 durante il funzionamento troppo alto!",
    "Heat exchanger temp. too high!":
        "Temperatura scambiatore di calore troppo alta!",
    "The automatic cleaning is not working!":
        "La pulizia automatica non funziona!",
    "The pellet module flame temperature sensor is missing or faulty!":
        "Sensore temperatura fiamma modulo pellet mancante o difettoso!",
    "Invalid boiler series number!":
        "Numero di serie caldaia non valido!",
    "KPM module error!":
        "Errore modulo KPM!",
    "The exhaust gas temperature sensor is missing or faulty!":
        "Sensore temperatura fumi mancante o difettoso!",
    "Flame temperature in operation too low!":
        "Temperatura fiamma durante il funzionamento troppo bassa!",
    "Ash container full! Please empty":
        "Contenitore cenere pieno! Svuotare",
    "The induced draught speed is implausible":
        "Velocità tiraggio non plausibile",
    "Modbus communication failure":
        "Errore di comunicazione Modbus",
    "Modbus communication failure Powerfire":
        "Errore di comunicazione Modbus Powerfire",
    "The buffer sensor for the modulating buffer operation is missing or faulty!":
        "Sensore puffer per funzionamento modulante mancante o difettoso!",
    "Return flow temperature sensor before boiler inlet (plug 237) is missing or faulty!":
        "Sensore temperatura ritorno prima dell'ingresso caldaia (connettore 237) mancante o difettoso!",
    "Check cleaning openings!":
        "Controllare le aperture di pulizia!",
    "The fuel range is too small":
        "La quantità di combustibile è troppo bassa",
    "Warning: Critical system operation! Cause: Boiler runtime too short.":
        "Avviso: Funzionamento critico! Causa: Tempo di accensione caldaia troppo breve.",
    "Fault shutdown critical system operation – please contact Customer Service immediately! Cause: Boiler runtime too short.":
        "Arresto per guasto – contattare immediatamente l'assistenza! Causa: Tempo di accensione caldaia troppo breve.",
    "The differential pressure in the combustion chamber cannot be regulated!":
        "Impossibile regolare la pressione differenziale nella camera di combustione!",
    "Differential pressure sensor is faulty!":
        "Sensore pressione differenziale difettoso!",
    "O2 value during operation too high or insufficient fuel!":
        "Valore O2 troppo alto o combustibile insufficiente!",
    "Boiler is switched off. The heat pump takes over the heat supply!":
        "Caldaia spenta. La pompa di calore subentra nella fornitura di calore!",
    "Ash container is almost full!":
        "Contenitore cenere quasi pieno!",
    "Warning: Critical system operation! Cause: Secondary air speed too low.":
        "Avviso: Funzionamento critico! Causa: Velocità aria secondaria troppo bassa.",
    "Fault shutdown critical system operation – please contact Customer Service immediately! Cause: Secondary air speed too low.":
        "Arresto per guasto – contattare immediatamente l'assistenza! Causa: Velocità aria secondaria troppo bassa.",
    "Warning: Critical system operation! Cause: Flame temperature too low.":
        "Avviso: Funzionamento critico! Causa: Temperatura fiamma troppo bassa.",
    "Fault shutdown critical system operation – please contact Customer Service immediately! Cause: Flame temperature too low.":
        "Arresto per guasto – contattare immediatamente l'assistenza! Causa: Temperatura fiamma troppo bassa.",
}

# ── Alarm map (address → metadata) ────────────────────────────────────────
# Built from ModbusInfo-en-V25_4_0.xlsx, sheet "Alarms"
# Only addresses relevant to EF2 are included (groups 1–5, plus battery/system)
# Template placeholders like {_0_} are replaced with index numbers at runtime.

@dataclass
class AlarmDef:
    address    : int
    alarm_id   : str   # e.g. "2.4"
    text_en    : str
    text_it    : str


def _make(address: int, alarm_id: str, text_en: str) -> AlarmDef:
    # Replace {_N_} placeholders with their numeric index
    import re
    clean_en = re.sub(r'\{_(\d+)_\}', lambda m: m.group(1), text_en)
    text_it  = _IT.get(text_en, _IT.get(clean_en, clean_en))
    return AlarmDef(address, alarm_id, clean_en, text_it)


# Build lookup: address → AlarmDef
ALARM_DEFS: dict[int, AlarmDef] = {}

_RAW_ALARMS = [
    # Group 0 – system
    (7,   "0.7",  "Battery empty"),
    # Group 1 – ignition / combustion
    (128, "1.0",  "Ignition exhaust gas temperature increase not achieved 1!"),
    (129, "1.1",  "Ignition exhaust gas temperature increase not achieved 2!"),
    (130, "1.2",  "Ignition not working! (Pellets)"),
    (131, "1.3",  "Main drive speed too high!"),
    (132, "1.4",  "Main drive speed too low!"),
    (133, "1.5",  "Main drive speed measurement not working!"),
    (134, "1.6",  "Safety shutdown - room air CO value too high!"),
    (135, "1.7",  "No flame detectable!"),
    (136, "1.8",  "Attention - emergency operation without lambda probe terminated!"),
    (137, "1.9",  "Exhaust gas temperature implausible!"),
    (138, "1.10", "Exhaust gas temperature in operation too high!"),
    (139, "1.11", "Exhaust gas temperature in operation too low!"),
    # Group 2 – boiler / system safety
    (256, "2.0",  "Safety thermostat! Boiler overheating!"),
    (257, "2.1",  "The emergency stop button has been activated!"),
    (258, "2.2",  "The ash container was incorrectly installed!"),
    (259, "2.3",  "Electronic error on digital inputs!"),
    (260, "2.4",  "KSM module error!"),
    (261, "2.5",  "Temperature increase in the fuel storage!"),
    (262, "2.6",  "Alarm! Internal error!"),
    (263, "2.7",  "The secondary air fan speed is too low!"),
    (264, "2.8",  "The primary air fan speed is too low!"),
    (265, "2.9",  "The induced draught fan speed is too low!"),
    (266, "2.10", "The negative pressure in the combustion chamber cannot be regulated!"),
    (267, "2.11", "Negative pressure sensor is faulty!"),
    (268, "2.12", "Lambda probe is faulty!"),
    (269, "2.13", "Conveyor motor is overheated!"),
    (270, "2.14", "Fuel storage is empty!"),
    (271, "2.15", "Fuel container is empty!"),
    (272, "2.16", "Electronics are overheated!"),
    (273, "2.17", "Boiler sensor is missing or faulty!"),
    (274, "2.18", "Boiler temperature implausible!"),
    (275, "2.19", "Return flow boost malfunction!"),
    (276, "2.20", "Return-flow sensor is missing or faulty!"),
    (277, "2.21", "Maintenance interval expired."),
    (278, "2.22", "Control interval expired!"),
    (279, "2.23", "Measuring mode is activated!"),
    (280, "2.24", "24V safety circuit not active, input 133!"),
    (281, "2.25", "Safety chain 230V reserve is interrupted"),
    (282, "2.26", "Error conveyor system fill level!"),
    (283, "2.27", "Error in the sampling probe system!"),
    (284, "2.28", "Fuel storage is almost empty!"),
    (285, "2.29", "Secondary air fan speed is too high!"),
    (286, "2.30", "24V safety circuit not active, input 130!"),
    (287, "2.31", "24V safety circuit not active, input 131!"),
    (288, "2.32", "24V safety circuit not active, input 132!"),
    (289, "2.33", "Primary fan speed is too high!"),
    (290, "2.34", "Induced draught fan speed is too high!"),
    (291, "2.35", "Room air CO value too high!"),
    (292, "2.36", "The flame temperature sensor is missing or faulty!"),
    (293, "2.37", "O2 value during operation too high!"),
    (294, "2.38", "Heat exchanger temp. too high!"),
    (295, "2.39", "The automatic cleaning is not working!"),
    (296, "2.40", "The pellet module flame temperature sensor is missing or faulty!"),
    (297, "2.41", "Invalid boiler series number!"),
    (298, "2.42", "KPM module error!"),
    (301, "2.46", "Flame temperature in operation too low!"),
    (304, "2.48", "Ash container full! Please empty"),
    (305, "2.49", "The induced draught speed is implausible"),
    (306, "2.50", "Modbus communication failure"),
    (308, "2.52", "The buffer sensor for the modulating buffer operation is missing or faulty!"),
    (311, "2.55", "Return flow temperature sensor before boiler inlet (plug 237) is missing or faulty!"),
    (312, "2.56", "Check cleaning openings!"),
    (313, "2.57", "The fuel range is too small"),
    (314, "2.58", "Warning: Critical system operation! Cause: Boiler runtime too short."),
    (315, "2.59", "Fault shutdown critical system operation – please contact Customer Service immediately! Cause: Boiler runtime too short."),
    (316, "2.60", "The differential pressure in the combustion chamber cannot be regulated!"),
    (317, "2.61", "Differential pressure sensor is faulty!"),
    (318, "2.62", "O2 value during operation too high or insufficient fuel!"),
    (319, "2.63", "Boiler is switched off. The heat pump takes over the heat supply!"),
    (320, "2.64", "Ash container is almost full!"),
    (322, "2.66", "Warning: Critical system operation! Cause: Secondary air speed too low."),
    (323, "2.67", "Fault shutdown critical system operation – please contact Customer Service immediately! Cause: Secondary air speed too low."),
    (324, "2.68", "Warning: Critical system operation! Cause: Flame temperature too low."),
    (325, "2.69", "Fault shutdown critical system operation – please contact Customer Service immediately! Cause: Flame temperature too low."),
    # Group 3 – buffer sensors (only buffer 0 and 1 — your installation)
    (384, "3.0",  "Sensor 1 of the buffer 0 is missing or faulty!"),
    (385, "3.1",  "Sensor 2 of the buffer 0 is missing or faulty!"),
    (386, "3.2",  "Sensor 3 of the buffer 0 is missing or faulty!"),
    (387, "3.3",  "Sensor 4 of the buffer 0 is missing or faulty!"),
    (388, "3.4",  "Sensor 5 of the buffer 0 is missing or faulty!"),
]

for _addr, _aid, _txt in _RAW_ALARMS:
    ALARM_DEFS[_addr] = _make(_addr, _aid, _txt)

# Unique addresses sorted for batched reads
ALARM_ADDRESSES = sorted(ALARM_DEFS.keys())


# ── Modbus read ───────────────────────────────────────────────────────────
def read_active_alarms(client: ModbusTcpClient, device_id: int) -> set[int]:
    """
    Read all alarm coils via FC02 and return the set of addresses that are ACTIVE (=1).
    Reads in contiguous blocks to minimise round trips.
    """
    active: set[int] = set()
    if not ALARM_ADDRESSES:
        return active

    # Build contiguous blocks
    blocks: list[tuple[int, int]] = []
    block_start = ALARM_ADDRESSES[0]
    block_end   = ALARM_ADDRESSES[0]
    for addr in ALARM_ADDRESSES[1:]:
        if addr <= block_end + 8:   # tolerate small gaps inside a block
            block_end = addr
        else:
            blocks.append((block_start, block_end))
            block_start = block_end = addr
    blocks.append((block_start, block_end))

    for start, end in blocks:
        count = end - start + 1
        try:
            resp = client.read_discrete_inputs(start, count=count, device_id=device_id)
            if resp.isError():
                logger.debug(f"Alarm read error addr={start} count={count}: {resp}")
                continue
            for i, bit in enumerate(resp.bits[:count]):
                addr = start + i
                if bit and addr in ALARM_DEFS:
                    active.add(addr)
        except ModbusException as e:
            logger.debug(f"Alarm ModbusException addr={start}: {e}")
        except Exception as e:
            logger.debug(f"Alarm read exception addr={start}: {e}")

    return active
