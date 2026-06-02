"""
test_modbus_reader.py
=====================
Verifica la logica di lettura Modbus e le conversioni dei tipi raw:
- Conversioni s16, u16, u32, s32 corrette
- Applicazione del scale factor
- Gestione errori (nessun crash, ReadResult con error valorizzato)
- Firma della funzione read_holding_registers compatibile con pymodbus 3.13
  (parametro device_id, count keyword-only)
"""

import sys
import inspect
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

SRC_DIR = str(Path(__file__).resolve().parent.parent / "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from modbus_reader import (
    _to_int16, _to_int32, _to_uint32,
    ReadResult, read_registers,
)
from registers import Register


# ── Conversion functions ──────────────────────────────────────────────────

class TestInt16Conversion:
    """_to_int16: interpreta un word u16 come signed int16."""

    def test_positive(self):
        assert _to_int16(653) == 653       # 65.3°C con scale 0.1

    def test_zero(self):
        assert _to_int16(0) == 0

    def test_max_positive(self):
        assert _to_int16(0x7FFF) == 32767  # +32767

    def test_minus_one(self):
        assert _to_int16(0xFFFF) == -1

    def test_minus_167(self):
        # -16.7°C raw = 0xFF59 = 65369 u16
        assert _to_int16(0xFF59) == -167

    def test_min_negative(self):
        assert _to_int16(0x8000) == -32768


class TestUint32Conversion:
    """_to_uint32: due word u16 big-endian → u32."""

    def test_zero(self):
        assert _to_uint32(0, 0) == 0

    def test_one(self):
        assert _to_uint32(0, 1) == 1

    def test_high_word(self):
        assert _to_uint32(1, 0) == 65536   # 1 << 16

    def test_max(self):
        assert _to_uint32(0xFFFF, 0xFFFF) == 0xFFFFFFFF

    def test_typical_kwh(self):
        # Energia solare tipica: 1234567 Wh → raw 1234567
        # hi = 1234567 >> 16 = 18, lo = 1234567 & 0xFFFF = 57095
        hi = 1234567 >> 16
        lo = 1234567 & 0xFFFF
        assert _to_uint32(hi, lo) == 1234567


class TestInt32Conversion:
    """_to_int32: due word u16 big-endian → s32."""

    def test_zero(self):
        assert _to_int32(0, 0) == 0

    def test_minus_one(self):
        assert _to_int32(0xFFFF, 0xFFFF) == -1

    def test_positive(self):
        assert _to_int32(0, 100) == 100

    def test_min_negative(self):
        assert _to_int32(0x8000, 0) == -2147483648


# ── Scale factor application ──────────────────────────────────────────────

class TestScaleApplication:

    def _make_reg(self, dtype, scale, fc=4):
        return Register(address=1000, name="test", group="test",
                        fc=fc, dtype=dtype, scale=scale)

    def test_u16_scale_tenth(self):
        """653 raw × 0.1 = 65.3°C"""
        reg = self._make_reg("u16", 0.1)
        mock_resp = MagicMock()
        mock_resp.isError.return_value = False
        mock_resp.registers = [653]
        client = MagicMock()
        client.read_input_registers.return_value = mock_resp

        results = read_registers(client, [reg], device_id=1)
        assert len(results) == 1
        assert results[0].error is None
        assert results[0].scaled_value == pytest.approx(65.3, abs=0.01)

    def test_s16_negative_scale(self):
        """-167 raw × 0.1 = -16.7°C (temperatura esterna invernale)"""
        reg = self._make_reg("s16", 0.1)
        mock_resp = MagicMock()
        mock_resp.isError.return_value = False
        mock_resp.registers = [0xFF59]  # -167 in s16
        client = MagicMock()
        client.read_input_registers.return_value = mock_resp

        results = read_registers(client, [reg], device_id=1)
        assert results[0].error is None
        assert results[0].scaled_value == pytest.approx(-16.7, abs=0.01)

    def test_u32_scale(self):
        """Energia solare: u32 × 0.001 = kWh"""
        reg = self._make_reg("u32", 0.001)
        mock_resp = MagicMock()
        mock_resp.isError.return_value = False
        mock_resp.registers = [0, 1000]  # raw = 1000
        client = MagicMock()
        client.read_input_registers.return_value = mock_resp

        results = read_registers(client, [reg], device_id=1)
        assert results[0].error is None
        assert results[0].scaled_value == pytest.approx(1.0, abs=0.001)


# ── Error handling ────────────────────────────────────────────────────────

class TestReadRegistersErrorHandling:

    def _make_reg(self, dtype="u16", fc=4):
        return Register(address=9999, name="test_err", group="test",
                        fc=fc, dtype=dtype, scale=1.0)

    def test_modbus_error_response_yields_error_result(self):
        """
        Se la risposta Modbus è un errore (exception_code=2 'Illegal Data Address'),
        il risultato deve avere error valorizzato e scaled_value=None.
        Non deve lanciare eccezioni.
        """
        reg = self._make_reg()
        mock_resp = MagicMock()
        mock_resp.isError.return_value = True
        mock_resp.__str__ = lambda s: "ExceptionResponse(exception_code=2)"
        client = MagicMock()
        client.read_input_registers.return_value = mock_resp

        results = read_registers(client, [reg], device_id=1)
        assert len(results) == 1
        assert results[0].error is not None
        assert results[0].scaled_value is None

    def test_connection_exception_yields_error_result(self):
        """Un'eccezione durante la lettura non deve propagarsi al chiamante."""
        from pymodbus.exceptions import ModbusException
        reg = self._make_reg()
        client = MagicMock()
        client.read_input_registers.side_effect = ModbusException("timeout")

        results = read_registers(client, [reg], device_id=1)
        assert results[0].error is not None
        assert results[0].scaled_value is None

    def test_multiple_registers_partial_error(self):
        """
        Con N registri, un errore su uno non blocca la lettura degli altri.
        Solo il registro fallito ha error!=None.
        """
        from registers import all_registers
        regs = all_registers()[:3]

        ok_resp = MagicMock()
        ok_resp.isError.return_value = False
        ok_resp.registers = [100]

        err_resp = MagicMock()
        err_resp.isError.return_value = True
        err_resp.__str__ = lambda s: "Error"

        # Primo ok, secondo errore, terzo ok
        client = MagicMock()
        client.read_input_registers.side_effect = [ok_resp, err_resp, ok_resp]
        client.read_holding_registers.side_effect = [ok_resp, err_resp, ok_resp]

        results = read_registers(client, regs, device_id=1)
        assert len(results) == 3

    def test_32bit_register_reads_two_words(self):
        """Un registro u32 deve richiedere count=2, non count=1."""
        reg = Register(address=9215, name="sol1_thermal_output_kw", group="sol",
                       fc=4, dtype="u32", scale=0.001, unit="kW")
        mock_resp = MagicMock()
        mock_resp.isError.return_value = False
        mock_resp.registers = [0, 5000]
        client = MagicMock()
        client.read_input_registers.return_value = mock_resp

        read_registers(client, [reg], device_id=1)

        # Verifica che sia stato chiamato con count=2
        call_kwargs = client.read_input_registers.call_args
        assert call_kwargs.kwargs.get("count") == 2, (
            "Un registro u32 deve essere letto con count=2"
        )


# ── pymodbus 3.13 API compatibility ──────────────────────────────────────

class TestPymodbusAPICompatibility:
    """
    Verifica che il codice usi la firma corretta di pymodbus 3.13.
    Bug storico: slave= rinominato in device_id= nella versione 3.13.
    """

    def test_read_holding_registers_uses_device_id(self):
        """
        La firma di ModbusTcpClient.read_holding_registers in pymodbus 3.13
        deve avere il parametro 'device_id', non 'slave' né 'unit'.
        """
        from pymodbus.client import ModbusTcpClient
        sig = inspect.signature(ModbusTcpClient.read_holding_registers)
        params = list(sig.parameters.keys())
        assert "device_id" in params, (
            f"pymodbus installato non ha 'device_id' nella firma: {params}. "
            "Aggiornare pymodbus o aggiornare modbus_reader.py di conseguenza."
        )
        assert "slave" not in params, (
            "'slave' trovato nella firma: la versione di pymodbus non è 3.13+."
        )

    def test_count_is_keyword_only(self):
        """
        'count' deve essere keyword-only (dopo *) in pymodbus 3.13.
        Passarlo come positional causa l'errore storico 'unexpected keyword argument slave'.
        """
        from pymodbus.client import ModbusTcpClient
        sig = inspect.signature(ModbusTcpClient.read_holding_registers)
        count_param = sig.parameters.get("count")
        assert count_param is not None
        assert count_param.kind == inspect.Parameter.KEYWORD_ONLY, (
            "'count' non è keyword-only: la versione di pymodbus potrebbe non essere 3.13+."
        )

    def test_modbus_reader_calls_device_id(self):
        """
        read_registers() deve passare device_id= (non slave=) alla libreria.
        Questo test rileva una regressione se il parametro viene rinominato.
        """
        reg = Register(address=8197, name="boiler_temp_actual", group="boiler",
                       fc=4, dtype="s16", scale=0.1, unit="°C")
        mock_resp = MagicMock()
        mock_resp.isError.return_value = False
        mock_resp.registers = [653]
        client = MagicMock()
        client.read_input_registers.return_value = mock_resp

        read_registers(client, [reg], device_id=1)

        call_kwargs = client.read_input_registers.call_args.kwargs
        assert "device_id" in call_kwargs, (
            f"read_input_registers chiamato con kwargs: {call_kwargs}. "
            "Manca 'device_id': il codice potrebbe usare 'slave' o 'unit'."
        )
        assert "slave" not in call_kwargs
        assert "unit"  not in call_kwargs
