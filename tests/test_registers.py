"""
test_registers.py
=================
Verifica la mappa registri Modbus:
- Nomi univoci e coerenza con REGISTER_COLUMNS del DB
- Indirizzi puffer corretti (BUF 0, non BUF 1)
- Tutti i registri scrivibili usano FC 03
- Coerenza FC/dtype
- Decodifica enum funzionante
- boiler_full_load_h usa scale=1/60 (raw in minuti → ore)
- Presenza obbligatoria di registri critici per grafici
"""

import sys
from pathlib import Path
import pytest

SRC_DIR = str(Path(__file__).resolve().parent.parent / "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from registers import all_registers, decode_enum, VALUE_TABLES, Register
from db import REGISTER_COLUMNS


class TestRegisterCompleteness:

    def test_total_count_is_98(self):
        """Il progetto deve avere esattamente 98 registri configurati."""
        assert len(all_registers()) == 98

    def test_no_duplicate_names(self):
        """Nessun nome di registro può essere duplicato."""
        names = [r.name for r in all_registers()]
        dupes = [n for n in names if names.count(n) > 1]
        assert dupes == [], f"Registri duplicati: {dupes}"

    def test_no_duplicate_addresses_within_same_fc(self):
        """
        Due registri con stesso FC e stesso indirizzo sarebbero un errore di mappatura.
        (Indirizzi uguali su FC diversi sono ammessi: FC3 writable vs FC4 readable.)
        """
        seen = {}
        conflicts = []
        for r in all_registers():
            key = (r.fc, r.address)
            if key in seen:
                conflicts.append((seen[key], r.name))
            else:
                seen[key] = r.name
        assert conflicts == [], f"Indirizzi duplicati per stesso FC: {conflicts}"

    def test_register_columns_match_all_registers(self):
        """
        REGISTER_COLUMNS in db.py deve contenere esattamente gli stessi nomi
        di all_registers() — nessun nome aggiuntivo, nessuno mancante.
        Questo garantisce che DB schema e registro siano sempre allineati.
        """
        reg_names = {r.name for r in all_registers()}
        col_names = set(REGISTER_COLUMNS)
        assert reg_names == col_names, (
            f"In COLUMNS ma non in registers: {col_names - reg_names}\n"
            f"In registers ma non in COLUMNS: {reg_names - col_names}"
        )

    def test_register_columns_order_matches_all_registers(self):
        """
        L'ordine di REGISTER_COLUMNS deve corrispondere all'ordine di all_registers(),
        perché insert_readings_wide() costruisce la riga usando questa corrispondenza posizionale.
        """
        reg_names  = [r.name for r in all_registers()]
        col_names  = REGISTER_COLUMNS
        assert reg_names == col_names, (
            "L'ordine di REGISTER_COLUMNS non corrisponde a all_registers(). "
            "Primo disallineamento all'indice "
            f"{next(i for i,(a,b) in enumerate(zip(reg_names,col_names)) if a!=b)}"
        )


class TestCriticalRegisters:

    def test_required_chart_registers_exist(self):
        """
        Tutti i registri usati dai grafici del bot devono essere presenti.
        Se manca uno di questi il grafico non mostra dati senza errori espliciti.
        """
        required = [
            "boiler_temp_actual",   # grafico temp. caldaia
            "sol1_collector_temp",  # grafico temp. solare
            "boi1_temp_actual",     # grafico boiler ACS (serie 1)
            "boi1_temp2",           # grafico boiler ACS (serie 2 – sonda 2)
            "puf1_temp1",           # grafico puffer sonda 1
            "puf1_temp2",           # grafico puffer sonda 2
            "puf1_temp5",           # grafico puffer sonda 5 (bassa)
            "outside_temp",         # grafico temperatura esterna
            "sol1_pump1_pct",       # grafico pompa solare (asse destro)
            "boiler_output_pct",    # grafico potenza caldaia (serie 1)
            "boiler_pump_pct",      # grafico potenza caldaia (serie 2)
        ]
        reg_names = {r.name for r in all_registers()}
        missing = [n for n in required if n not in reg_names]
        assert missing == [], f"Registri mancanti per i grafici: {missing}"

    def test_required_maxmin_registers_exist(self):
        """
        I registri usati dal pannello Massimi/Minimi devono esistere.
        """
        required = ["sol1_collector_temp", "boi1_temp_actual", "outside_temp"]
        reg_names = {r.name for r in all_registers()}
        missing = [n for n in required if n not in reg_names]
        assert missing == [], f"Registri mancanti per Massimi/Minimi: {missing}"

    def test_alarm_system_registers_exist(self):
        """Registri di sistema per il conteggio allarmi devono essere presenti."""
        required = ["alarms_total", "alarms_pending"]
        reg_names = {r.name for r in all_registers()}
        missing = [n for n in required if n not in reg_names]
        assert missing == [], f"Registri allarmi mancanti: {missing}"

    def test_boiler_heat_once_is_writable(self):
        """boi1_heat_once deve essere scrivibile (funzionalità automazione futura)."""
        reg = next((r for r in all_registers() if r.name == "boi1_heat_once"), None)
        assert reg is not None, "boi1_heat_once non trovato"
        assert reg.writable, "boi1_heat_once deve essere writable=True"
        assert reg.fc == 3, "boi1_heat_once deve usare FC3 (holding register)"


class TestPufferOffsets:
    """
    Bug critico risolto: il puffer usava BUF 1 (offset +2) invece di BUF 0.
    Gli indirizzi corretti per BUF 0 iniziano da 8708.
    Questo test previene la regressione.
    """

    def test_puf1_temp1_address_is_buf0(self):
        """puf1_temp1 deve avere indirizzo 8708 (BUF 0), non 8710 (BUF 1)."""
        reg = next((r for r in all_registers() if r.name == "puf1_temp1"), None)
        assert reg is not None, "puf1_temp1 non trovato"
        assert reg.address == 8708, (
            f"puf1_temp1 ha indirizzo {reg.address}, atteso 8708 (BUF 0). "
            "Possibile regressione: controllare che non sia tornato a BUF 1 (8710)."
        )

    def test_puf1_temp2_address_is_buf0(self):
        """puf1_temp2 deve avere indirizzo 8742 (BUF 0)."""
        reg = next((r for r in all_registers() if r.name == "puf1_temp2"), None)
        assert reg is not None
        assert reg.address == 8742, f"puf1_temp2 ha indirizzo {reg.address}, atteso 8742"

    def test_puf1_temp5_address_is_buf0(self):
        """puf1_temp5 deve avere indirizzo 8844 (BUF 0)."""
        reg = next((r for r in all_registers() if r.name == "puf1_temp5"), None)
        assert reg is not None
        assert reg.address == 8844, f"puf1_temp5 ha indirizzo {reg.address}, atteso 8844"


class TestWritableRegisters:

    def test_all_writable_use_fc3(self):
        """
        Tutti i registri scrivibili devono usare FC 03 (Holding Registers).
        FC 04 (Input Registers) è read-only per definizione del protocollo Modbus.
        """
        bad = [r for r in all_registers() if r.writable and r.fc != 3]
        assert bad == [], (
            f"Registri scrivibili con FC!=3: {[(r.name, r.fc) for r in bad]}"
        )

    def test_expected_writable_registers(self):
        """
        Verifica che i registri scrivibili attesi siano tutti presenti.
        Se uno viene rimosso per errore, i comandi Modbus di scrittura non funzionerebbero.
        """
        expected_writable = {
            "boiler_on_off", "boiler_fuel_remaining_kg",
            "hk1_program", "hk1_comfort_temp", "hk1_reduct_temp",
            "hk2_program", "hk2_comfort_temp", "hk2_reduct_temp",
            "puf1_program", "puf1_temp_min", "puf1_temp_max", "puf1_dhw_temp_min",
            "boi1_program", "boi1_temp_min", "boi1_temp_max", "boi1_heat_once",
        }
        actual_writable = {r.name for r in all_registers() if r.writable}
        missing = list(expected_writable - actual_writable)
        assert missing == [], f"Registri scrivibili mancanti: {missing}"


class TestScaleFactors:

    def test_boiler_full_load_h_scale(self):
        """
        boiler_full_load_h: il raw è in MINUTI, la scala deve essere 1/60
        per restituire le ore. Bug rilevato in produzione.
        """
        reg = next((r for r in all_registers() if r.name == "boiler_full_load_h"), None)
        assert reg is not None, "boiler_full_load_h non trovato"
        expected = pytest.approx(1 / 60, rel=1e-4)
        assert reg.scale == expected, (
            f"Scale di boiler_full_load_h = {reg.scale}, atteso 1/60 ≈ 0.01667. "
            "Il raw è in minuti: dividere per 60 per avere ore."
        )

    def test_temperature_registers_scale(self):
        """
        I registri di temperatura devono avere scale=0.1 (raw in decimi di grado).
        Controlla i principali per prevenire regressioni.
        """
        temp_regs = ["boiler_temp_actual", "sol1_collector_temp",
                     "boi1_temp_actual", "puf1_temp1"]
        reg_map = {r.name: r for r in all_registers()}
        for name in temp_regs:
            assert name in reg_map, f"{name} non trovato"
            assert reg_map[name].scale == pytest.approx(0.1), (
                f"{name} ha scale={reg_map[name].scale}, atteso 0.1"
            )

    def test_percentage_registers_scale(self):
        """I registri percentuale devono avere scale=0.1."""
        pct_regs = ["boiler_output_pct", "sol1_pump1_pct"]
        reg_map = {r.name: r for r in all_registers()}
        for name in pct_regs:
            if name in reg_map:
                assert reg_map[name].scale == pytest.approx(0.1), (
                    f"{name} scale={reg_map[name].scale}, atteso 0.1"
                )


class TestEnumDecoding:

    def test_boiler_status_known_values(self):
        """decode_enum decodifica correttamente gli stati principali della caldaia."""
        cases = [
            (41, "Heating"),
            (30, "Ready (-Requ)"),
            (5,  "Afterrun"),     # raw=5 = Afterrun nella tabella ksm_kesselstatus_anzeige_t
            (8,  "Fault Off"),
            (0,  "Off"),
        ]
        for raw, expected in cases:
            result = decode_enum("ksm_kesselstatus_anzeige_t", raw)
            assert result == expected, f"raw={raw}: '{result}' != '{expected}'"

    def test_solar_status_known_values(self):
        """decode_enum decodifica correttamente gli stati solare."""
        assert decode_enum("solar_status_t", 2) == "Charge tank 1"
        assert decode_enum("solar_status_t", 0) == "Off"

    def test_boiler_acs_status_known_values(self):
        """decode_enum decodifica correttamente gli stati boiler ACS."""
        assert decode_enum("boiler_status_t", 7) == "Temp. sufficient"
        assert decode_enum("boiler_status_t", 4) == "One-time charge"

    def test_decode_enum_unknown_value_returns_string(self):
        """Un valore sconosciuto deve restituire una stringa non vuota (non crashare)."""
        result = decode_enum("solar_status_t", 9999)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_on_off_table(self):
        """Tabella system_ein_aus_t: 0=Off, 1=On."""
        assert decode_enum("system_ein_aus_t", 0) == "Off"
        assert decode_enum("system_ein_aus_t", 1) == "On"

    def test_hk_status_table(self):
        """Stato circuito riscaldamento: 0=Reduct, 1=Comfort."""
        assert decode_enum("hk_status_t", 0) == "Reduct"
        assert decode_enum("hk_status_t", 1) == "Comfort"

    def test_all_vt_references_exist_in_value_tables(self):
        """
        Ogni registro che referenzia un ValueTable (vt != '') deve
        avere una corrispondente chiave in VALUE_TABLES.
        """
        missing = []
        for r in all_registers():
            if r.vt and r.vt not in VALUE_TABLES:
                missing.append((r.name, r.vt))
        assert missing == [], f"Registri con vt non trovato in VALUE_TABLES: {missing}"


class TestHKCircuits:
    """
    Verifica la mappatura dei circuiti di riscaldamento.
    HC 1.1 = "Mauro" → prefisso hk1_
    HC 1.2 = "Gabriele" → prefisso hk2_ (offset +1 rispetto a hk1)
    """

    def test_both_circuits_present(self):
        names = {r.name for r in all_registers()}
        for prefix in ("hk1_", "hk2_"):
            circuit_regs = [n for n in names if n.startswith(prefix)]
            assert len(circuit_regs) >= 8, (
                f"Circuito {prefix} ha solo {len(circuit_regs)} registri, attesi almeno 8"
            )

    def test_hk1_hk2_address_offset(self):
        """
        HC 1.2 ("Gabriele") ha indirizzi di 1 o 2 unità maggiori rispetto a HC 1.1 ("Mauro")
        per i registri analoghi — mai uguali.
        """
        reg_map = {r.name: r for r in all_registers()}
        pairs = [
            ("hk1_flow_temp_actual",   "hk2_flow_temp_actual"),
            ("hk1_room_temp_actual",   "hk2_room_temp_actual"),
            ("hk1_pump",               "hk2_pump"),
        ]
        for n1, n2 in pairs:
            if n1 in reg_map and n2 in reg_map:
                addr1 = reg_map[n1].address
                addr2 = reg_map[n2].address
                assert addr1 != addr2, (
                    f"{n1} e {n2} hanno lo stesso indirizzo {addr1}: mappatura errata"
                )
                assert addr2 > addr1, (
                    f"{n2} (addr={addr2}) non è maggiore di {n1} (addr={addr1})"
                )
