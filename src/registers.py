"""
KWB EasyFire EF2 – Modbus register map
Source: ModbusInfo-en-V25_4_0.xlsx (KWB official, v25.4.0)
Protocol sheet confirms: 0-based addressing, BigEndian, Modbus TCP port 502.
"""

from dataclasses import dataclass


@dataclass
class Register:
    address  : int
    name     : str
    group    : str
    fc       : int       # 3=holding, 4=input
    dtype    : str       # s16 | u16 | u32 | s32
    scale    : float = 1.0
    unit     : str   = ""
    writable : bool  = False
    vt       : str   = ""   # ValueTable name for enum decoding


# ── Value Tables ──────────────────────────────────────────────────────────
VALUE_TABLES: dict[str, dict[int, str]] = {
    "kfk_kesselstatus_t": {
        0: "Off", 1: "Standby", 2: "Ignition", 3: "Operation",
        4: "Afterrun", 5: "Fault", 6: "Ready (LW)", 7: "Operation (LW)",
    },
    "ksm_kesselstatus_anzeige_t": {
        0: "Off", 1: "Measuring mode", 2: "Operation (Cleaning)",
        3: "Measuring", 4: "Operation", 5: "Afterrun", 6: "Restart",
        7: "Fault afterrun", 8: "Fault Off", 9: "Maintenance",
        10: "Ready (-IgnStart)", 11: "Ignite start suction",
        12: "Ignition fill fuel", 13: "Ignition feeding 1",
        14: "Ignition feeding 3", 15: "Ignition heating",
        16: "Heating - complete ignition", 17: "Ignition feeding 2",
        18: "Ignition wait", 19: "Complete ignition", 20: "1. IB operation",
        21: "Ready (-Ext1)", 22: "Ready (-SecondBoiler)", 23: "Ready (-CS)",
        24: "Ready (-Cleaning)", 25: "Ready (+Stop)", 26: "Ready (-Ext3)",
        27: "Ready (-lambda probe)", 30: "Ready (-Requ)",
        31: "Ready (+Wait time)", 32: "Ready (+Requ)",
        34: "Empty out operation", 35: "Off", 36: "Heating-up",
        37: "Wait ignition requ.", 38: "Wait ignition rel.",
        39: "Start ignition", 40: "Ignition", 41: "Heating",
        42: "Fire maintenance", 43: "Fire off", 44: "Fault fire out",
        45: "Door open", 46: "Overheating", 47: "Fault, fire maintenance",
        49: "Sh off, PM released", 50: "Start pellet module",
        51: "Pellet module locked", 52: "Maintenance",
        53: "Operation before maint.", 54: "Maintenance switch off",
    },
    "system_sensor_status_t": {0: "Faulty", 1: "Missing", 2: "OK"},
    "system_ein_aus_t":        {0: "Off", 1: "On"},
    "system_yes_no_t":         {0: "No", 1: "Yes"},
    "solar_status_t": {
        0: "Off", 1: "Manual mode", 2: "Charge tank 1",
        3: "Charge tank 2", 4: "Fault", 5: "Solar protection",
        6: "Back cooling 1", 7: "Back cooling 2", 8: "Frost protection",
    },
    "solar_status_ursache_t": {
        0: "Program Off", 1: "Manual mode", 2: "Collector temp. sufficient",
        3: "Temp.diff.coll/tank 1 insuf.", 4: "Max. temp. tank 1 exceeded",
        5: "Max. temp. tank 2 exceeded", 6: "Absolute priority",
        7: "Blocking protection", 8: "Collector temp. too high",
        9: "Alarm active", 10: "Max. temp. tank 1+2 exceeded",
        11: "Coll. min. temp. undershot", 12: "Frost protection",
        13: "Interval function", 14: "Back cooling",
    },
    "hk_status_t": {
        0: "Reduct", 1: "Comfort", 2: "Frost protection", 3: "Holiday",
        4: "Off", 5: "Screed", 6: "Max. heat reduction",
        7: "Max. heat reduction", 8: "Modbus Fwd flow temp.",
        9: "Modbus Reduct", 10: "Modbus Comfort",
        11: "Modbus Frost protection", 12: "Premixer operation",
    },
    "hk_programm_t": {
        0: "Automatic", 1: "Frost protection", 2: "Off", 3: "Comfort", 4: "Reduct",
    },
    "hk_modbus_programm_t": {0: "Frost protection", 1: "Reduct", 2: "Comfort"},
    "boiler_status_t": {
        0: "Fault", 1: "Off", 2: "Legionella protection", 3: "Holiday",
        4: "One-time charge", 5: "Outside charging time",
        6: "Charge to target temp.", 7: "Temp. sufficient",
        8: "Blocking protection", 9: "Waiting pump release",
        10: "Boiler overheating", 11: "SHS overheating",
        12: "Max. heat reduction", 13: "Afterrun",
        14: "Afterrun (waiting release)",
    },
    "boiler_programm_t":  {0: "Time", 1: "Temp.", 2: "Off"},
    "puffer_programm_t":  {0: "Time", 1: "Temperature", 2: "Off", 3: "Time+", 4: "Summer"},
    "puffer_o_umschaltventil_t": {0: "Not available", 1: "Top", 2: "Bottom"},
    "ak_kesselprogramm_t": {
        0: "Request", 1: "Time program", 2: "Continuous",
        3: "Modbus temperature", 4: "Modbus output+temperature",
    },
    "ak_externe_vorgabe_t": {0: "Off", 1: "Temp.", 2: "Power", 3: "Modbus", 4: "Modbus"},
    "system_gui_kessel_typ_t": {
        0: "-", 1: "KWB Easyfire", 2: "KWB CF 2", 3: "KWB Combifire",
        4: "KWB Multifire", 5: "KWB Pelletfire+", 6: "KWB CF 1",
        7: "None", 8: "KWB CF 1.5", 9: "KWB Easyfire 3",
    },
}


def decode_enum(vt_name: str, value: int) -> str:
    table = VALUE_TABLES.get(vt_name, {})
    return table.get(int(value), f"{vt_name}:{int(value)}")


# ── Universal (system-wide) ───────────────────────────────────────────────
UNIVERSAL_REGISTERS: list[Register] = [
    Register(8192,  "fw_version_major",     "sys", 4, "u16", 1.0, "",    False),
    Register(8193,  "fw_version_minor",     "sys", 4, "u16", 1.0, "",    False),
    Register(8194,  "fw_version_patch",     "sys", 4, "u16", 1.0, "",    False),
    Register(8204,  "system_ok",            "sys", 4, "s16", 1.0, "",    False, "system_yes_no_t"),
    Register(8205,  "group_fault",          "sys", 4, "s16", 1.0, "",    False, "system_yes_no_t"),
    Register(8252,  "alarms_total",         "sys", 4, "u32", 1.0, "",    False),
    Register(8254,  "alarms_pending",       "sys", 4, "u32", 1.0, "",    False),
    Register(10024, "boiler_type",          "sys", 4, "s16", 1.0, "",    False, "system_gui_kessel_typ_t"),
    Register(25166, "serial_number",        "sys", 3, "u32", 1.0, "",    False),
]

# ── Boiler (KWB Easyfire sheet) ───────────────────────────────────────────
BOILER_REGISTERS: list[Register] = [
    # FC4 read-only
    Register(8197,  "boiler_temp_actual",       "boiler", 4, "s16", 0.1,  "°C",  False),
    Register(8199,  "boiler_temp_setpoint",      "boiler", 4, "s16", 0.1,  "°C",  False),
    Register(8200,  "boiler_pump",               "boiler", 4, "s16", 1.0,  "",    False, "system_ein_aus_t"),
    Register(8201,  "boiler_pump_pct",           "boiler", 4, "u16", 0.1,  "%",   False),
    Register(8202,  "boiler_return_temp",        "boiler", 4, "s16", 0.1,  "°C",  False),
    Register(8207,  "boiler_output_pct",         "boiler", 4, "s16", 0.1,  "%",   False),
    Register(8208,  "boiler_status",             "boiler", 4, "s16", 1.0,  "",    False, "ksm_kesselstatus_anzeige_t"),
    Register(8209,  "boiler_full_load_h",        "boiler", 4, "u32", 1/60, "h",   False),  # stored in min → /60
    Register(8214,  "boiler_oxygen_pct",         "boiler", 4, "s16", 0.1,  "%",   False),
    Register(8215,  "boiler_flame_temp",         "boiler", 4, "s16", 0.1,  "°C",  False),
    Register(8218,  "boiler_neg_pressure",       "boiler", 4, "s16", 0.1,  "Pa",  False),
    Register(8221,  "boiler_primary_fan_pct",    "boiler", 4, "s16", 0.1,  "%",   False),
    Register(8223,  "boiler_draught_pct",        "boiler", 4, "s16", 0.1,  "%",   False),
    Register(8224,  "boiler_next_service_h",     "boiler", 4, "s16", 1.0,  "h",   False),
    Register(8226,  "boiler_conveyor",           "boiler", 4, "s16", 1.0,  "",    False, "system_ein_aus_t"),
    Register(8231,  "boiler_exhaust_temp",       "boiler", 4, "s16", 0.1,  "°C",  False),
    Register(8233,  "boiler_fuel_consumed_kg",   "boiler", 4, "u32", 1.0,  "kg",  False),
    Register(8250,  "outside_temp",              "boiler", 4, "s16", 0.1,  "°C",  False),
    Register(9497,  "boiler_ash_level_pct",      "boiler", 4, "u16", 0.1,  "%",   False),
    Register(9498,  "boiler_draught_rpm",        "boiler", 4, "u16", 1.0,  "rpm", False),
    Register(9878,  "boiler_heat_total_kwh",     "boiler", 4, "u32", 0.1,  "kWh", False),
    Register(9970,  "boiler_status2",            "boiler", 4, "s16", 1.0,  "",    False, "kfk_kesselstatus_t"),
    # FC3 holding
    Register(24576, "boiler_on_off",             "boiler", 3, "s16", 1.0,  "",    True,  "system_ein_aus_t"),
    Register(24577, "boiler_setpoint_temp1",     "boiler", 3, "s16", 0.1,  "°C",  False),
    Register(24578, "boiler_setpoint_temp2",     "boiler", 3, "s16", 0.1,  "°C",  False),
    Register(24581, "boiler_return_min_temp",    "boiler", 3, "s16", 0.1,  "°C",  False),
    Register(24583, "boiler_ext_spec",           "boiler", 3, "s16", 1.0,  "",    False, "ak_externe_vorgabe_t"),
    Register(24584, "boiler_program",            "boiler", 3, "s16", 1.0,  "",    False, "ak_kesselprogramm_t"),
    Register(24851, "modbus_boiler_temp_sp",     "boiler", 3, "s16", 0.1,  "°C",  False),
    Register(24852, "modbus_boiler_output_sp",   "boiler", 3, "s16", 0.1,  "%",   False),
    Register(24927, "boiler_fuel_remaining_kg",  "boiler", 3, "u32", 1.0,  "kg",  True),
]

# ── Heating Circuit 1 (HC 1.1) ────────────────────────────────────────────
HC1_REGISTERS: list[Register] = [
    Register(8260,  "hk1_flow_temp_actual",      "hk", 4, "s16", 0.1, "°C", False),
    Register(8328,  "hk1_flow_temp_setpoint",    "hk", 4, "s16", 0.1, "°C", False),
    Register(8365,  "hk1_room_temp_actual",      "hk", 4, "s16", 0.1, "°C", False),
    Register(8435,  "hk1_outside_temp",          "hk", 4, "s16", 0.1, "°C", False),
    Register(8503,  "hk1_pump",                  "hk", 4, "s16", 1.0, "",   False, "system_ein_aus_t"),
    Register(8538,  "hk1_room_temp_setpoint",    "hk", 4, "s16", 0.1, "°C", False),
    Register(8573,  "hk1_status",                "hk", 4, "s16", 1.0, "",   False, "hk_status_t"),
    # FC3 holding — read/write
    Register(24589, "hk1_program",               "hk", 3, "s16", 1.0, "",   True,  "hk_programm_t"),
    Register(24624, "hk1_comfort_temp",          "hk", 3, "s16", 0.1, "°C", True),
    Register(24659, "hk1_reduct_temp",           "hk", 3, "s16", 0.1, "°C", True),
]


# ── Heating Circuit 1.2 "Gabriele" (HC 1.2) ─────────────────────────────
# HC 1.1 = "Mauro",  HC 1.2 = "Gabriele" — both on heating group 1
# HC 2.x would be a physically separate second heating system (not present)
HC2_REGISTERS: list[Register] = [
    Register(8262,  "hk2_flow_temp_actual",      "hk2", 4, "s16", 0.1, "°C", False),
    Register(8329,  "hk2_flow_temp_setpoint",    "hk2", 4, "s16", 0.1, "°C", False),
    Register(8367,  "hk2_room_temp_actual",      "hk2", 4, "s16", 0.1, "°C", False),
    Register(8437,  "hk2_outside_temp",          "hk2", 4, "s16", 0.1, "°C", False),
    Register(8504,  "hk2_pump",                  "hk2", 4, "s16", 1.0, "",   False, "system_ein_aus_t"),
    Register(8539,  "hk2_room_temp_setpoint",    "hk2", 4, "s16", 0.1, "°C", False),
    Register(8574,  "hk2_status",                "hk2", 4, "s16", 1.0, "",   False, "hk_status_t"),
    # FC3 holding — read/write
    Register(24590, "hk2_program",               "hk2", 3, "s16", 1.0, "",   True,  "hk_programm_t"),
    Register(24625, "hk2_comfort_temp",          "hk2", 3, "s16", 0.1, "°C", True),
    Register(24660, "hk2_reduct_temp",           "hk2", 3, "s16", 0.1, "°C", True),
]

# ── Buffer Storage (BUF 0) ────────────────────────────────────────────────
# Interface shows "Tipo tamp. 1.1" and T1=50, T2=45, T5=31 → BUF 0 addresses
PUF1_REGISTERS: list[Register] = [
    Register(8708,  "puf1_temp1",          "puf", 4, "s16", 0.1, "°C", False),
    Register(8742,  "puf1_temp2",          "puf", 4, "s16", 0.1, "°C", False),
    Register(8776,  "puf1_temp3",          "puf", 4, "s16", 0.1, "°C", False),
    Register(8810,  "puf1_temp4",          "puf", 4, "s16", 0.1, "°C", False),
    Register(8844,  "puf1_temp5",          "puf", 4, "s16", 0.1, "°C", False),
    Register(8878,  "puf1_pump",           "puf", 4, "s16", 1.0, "",   False, "system_ein_aus_t"),
    Register(8895,  "puf1_request",        "puf", 4, "s16", 1.0, "",   False, "system_ein_aus_t"),
    Register(8912,  "puf1_valve",          "puf", 4, "s16", 1.0, "",   False, "puffer_o_umschaltventil_t"),
    # FC3 holding
    Register(24760, "puf1_program",        "puf", 3, "s16", 1.0, "",   True,  "puffer_programm_t"),
    Register(24777, "puf1_temp_min",       "puf", 3, "s16", 0.1, "°C", True),
    Register(24778, "puf1_temp_max",       "puf", 3, "s16", 0.1, "°C", True),
    Register(24811, "puf1_dhw_temp_min",   "puf", 3, "s16", 0.1, "°C", True),
]

# ── DHWC 1 (Domestic Hot Water Circuit) ──────────────────────────────────
BOI1_REGISTERS: list[Register] = [
    Register(8608,  "boi1_temp_actual",    "boi", 4, "s16", 0.1, "°C", False),
    Register(8641,  "boi1_charging_pump",  "boi", 4, "s16", 1.0, "",   False, "system_ein_aus_t"),
    Register(8658,  "boi1_request",        "boi", 4, "s16", 1.0, "",   False, "system_ein_aus_t"),
    Register(8675,  "boi1_temp_setpoint",  "boi", 4, "s16", 0.1, "°C", False),
    Register(8692,  "boi1_status",         "boi", 4, "s16", 1.0, "",   False, "boiler_status_t"),
    Register(9433,  "boi1_temp2",          "boi", 4, "s16", 0.1, "°C", False),
    # FC3 holding
    Register(24693, "boi1_program",        "boi", 3, "s16", 1.0, "",   True,  "boiler_programm_t"),
    Register(24711, "boi1_temp_min",       "boi", 3, "s16", 0.1, "°C", True),
    Register(24712, "boi1_temp_max",       "boi", 3, "s16", 0.1, "°C", True),
    Register(24744, "boi1_heat_once",      "boi", 3, "s16", 1.0, "",   True,  "system_ein_aus_t"),
]

# ── Solar 1 (SOL 1) ───────────────────────────────────────────────────────
SOL1_REGISTERS: list[Register] = [
    Register(9049,  "sol1_status",              "sol", 4, "s16", 1.0,   "",      False, "solar_status_t"),
    Register(9064,  "sol1_status_reason",       "sol", 4, "s16", 1.0,   "",      False, "solar_status_ursache_t"),
    Register(9080,  "sol1_collector_temp",      "sol", 4, "s16", 0.1,   "°C",    False),
    Register(9110,  "sol1_tank1_temp",          "sol", 4, "s16", 0.1,   "°C",    False),
    Register(9140,  "sol1_tank2_temp",          "sol", 4, "s16", 0.1,   "°C",    False),
    Register(9169,  "sol1_pump1",               "sol", 4, "s16", 1.0,   "",      False, "system_ein_aus_t"),
    Register(9184,  "sol1_pump2",               "sol", 4, "s16", 1.0,   "",      False, "system_ein_aus_t"),
    Register(9199,  "sol1_switchover_valve",    "sol", 4, "s16", 1.0,   "",      False, "system_ein_aus_t"),
    Register(9215,  "sol1_thermal_output_kw",   "sol", 4, "u32", 0.001, "kW",    False),
    Register(9245,  "sol1_heat_day_kwh",        "sol", 4, "u32", 0.001, "kWh",   False),
    Register(9275,  "sol1_heat_total_kwh",      "sol", 4, "u32", 0.001, "kWh",   False),
    Register(9305,  "sol1_fwd_flow_temp",       "sol", 4, "s16", 0.1,   "°C",    False),
    Register(9335,  "sol1_ret_flow_temp",       "sol", 4, "s16", 0.1,   "°C",    False),
    Register(9365,  "sol1_flow_rate",           "sol", 4, "s16", 0.01,  "l/min", False),
    Register(9466,  "sol1_pump1_pct",           "sol", 4, "u16", 0.1,   "%",     False),
    Register(9481,  "sol1_pump2_pct",           "sol", 4, "u16", 0.1,   "%",     False),
]


def all_registers() -> list[Register]:
    return (
        UNIVERSAL_REGISTERS +
        BOILER_REGISTERS    +
        HC1_REGISTERS       +
        HC2_REGISTERS       +
        PUF1_REGISTERS      +
        BOI1_REGISTERS      +
        SOL1_REGISTERS
    )
